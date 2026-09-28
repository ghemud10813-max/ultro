"""PC ⇄ phone bridge: the phone's share sheet sends text, links and files to the PC; the PC
pushes files, screenshots, clipboard text and wallpapers to the phone.

Phone -> PC   {"t":"share","text":..,"subject":..}                  (text / link)
              {"t":"file","transferId","name","mime","index","total","data":b64}   (chunks, in order)
PC -> phone   {"t":"file_ack","transferId","ok",("name"|"error")}   after the last chunk / on error
              file.push chunks (method), clipboard.set, device.wallpaper
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from pathlib import Path

from nixin.features.base import Feature, Intent, Outcome, TaskContext, tr

CHUNK_BYTES = 480_000  # raw bytes per file.push chunk (base64 ≈ 640 KB, protocol limit 800 KB)
MAX_INCOMING_BYTES = 500 * 1024 * 1024
_URL_ANY = re.compile(r"https?://\S+", re.I)
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")


def safe_name(name: str, default: str = "file") -> str:
    name = Path(str(name or "")).name
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", name).strip(" .")
    return name[:180] or default


def unique_path(folder: Path, name: str) -> Path:
    p = folder / name
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    for i in range(1, 1000):
        cand = folder / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
    return folder / f"{stem}-{uuid.uuid4().hex[:6]}{suffix}"


@dataclass
class InboxItem:
    kind: str  # text | url | file
    time: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    text: str | None = None
    name: str | None = None
    path: str | None = None
    size: int | None = None
    mime: str | None = None


@dataclass
class _Incoming:
    name: str
    mime: str
    total: int
    tmp: Path
    next_index: int = 0
    size: int = 0
    started: float = field(default_factory=time.time)


class Bridge(Feature):
    name = "bridge"
    local = frozenset({"inbox"})

    def __init__(self, app) -> None:
        super().__init__(app)
        base = self.cfg.bridge.inbox_dir or str(Path.home() / "Nixin Inbox")
        self.inbox = Path(base).expanduser()
        self._incoming: dict[str, _Incoming] = {}
        self.items: list[InboxItem] = []
        for d in self.store.get_setting("inbox_items", []) or []:
            try:
                self.items.append(InboxItem(**d))
            except TypeError:
                continue
        app.phone.on_share = self.on_share
        app.phone.on_file_chunk = self.on_file_chunk

    def handlers(self):
        return {"inbox": self.handle}

    # ------------------------------------------------------------------ inbox bookkeeping
    def _ensure_dir(self) -> Path:
        self.inbox.mkdir(parents=True, exist_ok=True)
        return self.inbox

    def _add(self, item: InboxItem) -> None:
        self.items.insert(0, item)
        del self.items[60:]
        self.store.set_setting("inbox_items", [asdict(i) for i in self.items])
        self.bus.emit("inbox", item=asdict(item))

    def list_items(self, limit: int = 30) -> list[dict]:
        return [asdict(i) for i in self.items[:limit]]

    def last_image(self) -> InboxItem | None:
        for i in self.items:
            if i.kind == "file" and i.path and i.path.lower().endswith(_IMAGE_EXT) and Path(i.path).exists():
                return i
        return None

    def existing_files(self) -> list[InboxItem]:
        return [i for i in self.items if i.kind == "file" and i.path and Path(i.path).exists()]

    def save_inbox_bytes(self, data: bytes, name: str) -> str:
        p = unique_path(self._ensure_dir(), safe_name(name))
        p.write_bytes(data)
        return str(p)

    async def _pc_notify(self, title: str, text: str) -> None:
        pcf = getattr(self.app, "pc", None)
        if pcf is not None and self.cfg.notifications.toast_on_pc:
            await pcf.pc.notify(title, text)

    # ------------------------------------------------------------------ phone -> PC
    async def on_share(self, msg: dict) -> None:
        text = str(msg.get("text") or "").strip()
        if not text:
            return
        m = _URL_ANY.search(text) if len(text) < 400 else None
        kind = "url" if m else "text"
        self._add(InboxItem(kind=kind, text=text[:20000], name=str(msg.get("subject") or "")[:200] or None))
        pcf = getattr(self.app, "pc", None)
        if self.cfg.bridge.clipboard_on_share and pcf is not None:
            try:
                await pcf.pc.clipboard_set(text)
            except Exception as e:  # noqa: BLE001
                self.bus.emit("log", level="warning", msg=f"Clipboard copy failed: {e}")
        if kind == "url" and self.cfg.bridge.open_links:
            await asyncio.to_thread(webbrowser.open, m.group(0))
        await self._pc_notify("Phone se aaya", text[:200])
        await self.phone.send_message({"t": "say", "speak": False,
                                       "text": "PC pe bhej diya ✓" + (" (clipboard mein bhi)" if self.cfg.bridge.clipboard_on_share else "")})

    async def on_file_chunk(self, msg: dict) -> None:
        tid = re.sub(r"[^\w-]", "", str(msg.get("transferId") or ""))[:64]
        if not tid:
            return

        async def fail(err: str) -> None:
            inc = self._incoming.pop(tid, None)
            if inc:
                inc.tmp.unlink(missing_ok=True)
            await self.phone.send_message({"t": "file_ack", "transferId": tid, "ok": False, "error": err})
            self.bus.emit("log", level="warning", msg=f"File from phone failed: {err}")

        try:
            index, total = int(msg.get("index", -1)), int(msg.get("total", 0))
            data = base64.b64decode(str(msg.get("data") or ""), validate=False)
        except (TypeError, ValueError):
            await fail("bad chunk")
            return
        inc = self._incoming.get(tid)
        if inc is None:
            if index != 0 or not (1 <= total <= 2000):
                await fail("transfer must start at chunk 0")
                return
            name = safe_name(str(msg.get("name") or "file"))
            tmp = self._ensure_dir() / f".{tid}.part"
            tmp.write_bytes(b"")
            inc = _Incoming(name, str(msg.get("mime") or "application/octet-stream")[:100], total, tmp)
            self._incoming[tid] = inc
        if index != inc.next_index or total != inc.total:
            await fail(f"chunk {index} out of order (expected {inc.next_index})")
            return
        inc.size += len(data)
        if inc.size > MAX_INCOMING_BYTES:
            await fail("file too large")
            return
        with inc.tmp.open("ab") as f:
            f.write(data)
        inc.next_index += 1
        if inc.next_index < inc.total:
            return
        self._incoming.pop(tid, None)
        final = unique_path(self.inbox, inc.name)
        inc.tmp.replace(final)
        self._add(InboxItem(kind="file", name=final.name, path=str(final), size=inc.size, mime=inc.mime))
        await self.phone.send_message({"t": "file_ack", "transferId": tid, "ok": True, "name": final.name})
        await self._pc_notify("Phone se file aayi", final.name)

    # ------------------------------------------------------------------ PC -> phone
    async def push_bytes(self, data: bytes, name: str, mime: str = "application/octet-stream", *,
                         ctx: TaskContext | None = None) -> dict:
        name = safe_name(name)
        tid = uuid.uuid4().hex
        total = max(1, -(-len(data) // CHUNK_BYTES))
        res: dict = {}
        for i in range(total):
            chunk = data[i * CHUNK_BYTES:(i + 1) * CHUNK_BYTES]
            res = await self.phone.call("file.push", {
                "transferId": tid, "name": name, "mime": mime[:100], "index": i, "total": total,
                "data": base64.b64encode(chunk).decode("ascii")},
                timeout=40, task_id=ctx.task_id if ctx else None, origin="bridge")
            self.bus.emit("transfer", transferId=tid, name=name, index=i + 1, total=total, direction="to_phone")
        return res

    async def push_file(self, path: str | Path, ctx: TaskContext | None = None) -> dict:
        p = Path(path)
        mime = _guess_mime(p.name)
        return await self.push_bytes(await asyncio.to_thread(p.read_bytes), p.name, mime, ctx=ctx)

    async def set_wallpaper(self, data: bytes, target: str = "both", ctx: TaskContext | None = None) -> dict:
        data = _shrink_image(data)
        b64 = base64.b64encode(data).decode("ascii")
        if len(b64) > 12_000_000:
            raise ValueError("image too large for a wallpaper (max ~9 MB)")
        return await self.phone.call("device.wallpaper", {"data": b64, "target": target}, timeout=40,
                                     task_id=ctx.task_id if ctx else None, origin="bridge")

    # ------------------------------------------------------------------ intents
    async def handle(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        action = intent.params.get("action", "list")
        if action == "open":
            pcf = getattr(self.app, "pc", None)
            self._ensure_dir()
            if pcf is not None:
                await pcf.pc.open(str(self.inbox))
            return Outcome(True, tr(ctx, f"Inbox folder khol diya: {self.inbox}", f"Opened the inbox folder: {self.inbox}"))
        if action == "wallpaper":
            if (o := self.offline(ctx)) is not None:
                return o
            img = self.last_image()
            if img is None:
                return Outcome(False, tr(ctx, "Koi photo nahi mili. Pehle phone se photo Share → Nixin karo.",
                                         "No image found. Share a photo to Nixin first."))
            data = await asyncio.to_thread(Path(img.path or "").read_bytes)
            await self.set_wallpaper(data, intent.params.get("target") or "both", ctx)
            return Outcome(True, tr(ctx, f"'{img.name}' wallpaper laga diya.", f"Set '{img.name}' as your wallpaper."))
        if action == "push_last":
            if (o := self.offline(ctx)) is not None:
                return o
            files = self.existing_files()
            if not files:
                return Outcome(False, tr(ctx, "Inbox mein koi file nahi hai.", "There's no file in the inbox."))
            await self.push_file(files[0].path or "", ctx)
            return Outcome(True, tr(ctx, f"'{files[0].name}' phone pe bhej di.", f"Sent '{files[0].name}' to the phone."))
        items = self.items[:5]
        if not items:
            return Outcome(True, tr(ctx, "Phone se abhi kuch nahi aaya.", "Nothing has been shared from the phone yet."))
        parts = []
        for i in items:
            if i.kind == "file":
                parts.append(f"📄 {i.name}")
            else:
                parts.append(("🔗 " if i.kind == "url" else "📝 ") + (i.text or "")[:60])
        return Outcome(True, tr(ctx, "Phone se aaya: ", "From your phone: ") + " | ".join(parts), {"items": self.list_items(5)})


def _guess_mime(name: str) -> str:
    import mimetypes

    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _shrink_image(data: bytes, max_side: int = 2560) -> bytes:
    """Downscale huge photos before sending them as a wallpaper (needs Pillow; otherwise unchanged)."""
    if len(data) < 3_000_000:
        return data
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return data
