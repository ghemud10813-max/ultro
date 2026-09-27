"""Command line: `nixin run | demo | sim | doctor | models | send | init | keys | devices | unpair`."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import platform
import shutil
import sys
import threading
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.table import Table

from nixin import __version__
from nixin.config import NixinConfig, get_secret_pool, load_config

console = Console(highlight=False)

BANNER = r"""[bold magenta]
   _   _ _      _
  | \ | (_)_  _(_)_ __
  |  \| | \ \/ / | '_ \
  | |\  | |>  <| | | | |
  |_| \_|_/_/\_\_|_| |_|[/]  [dim]v{v} — your phone, by voice[/]
"""

HELP = """[bold]Type a command[/] (Hinglish or English), e.g. [cyan]volume badha do[/], [cyan]WhatsApp pe Rahul ko bol main late hoon[/]
[bold]Console commands:[/] /pair  /status  /models  /devices  /cancel  /mute  /help  /quit
[bold]Hotkeys:[/] push-to-talk {ptt} · kill switch {kill}"""


# ---------------------------------------------------------------------------- helpers
def _print_event(ev: dict) -> None:
    t = ev["type"]
    if t == "user" and not ev.get("answer") and ev.get("source") not in ("typed",):
        console.print(f"[dim]{ev.get('source')}[/] [bold cyan]›[/] {ev['text']}")
    elif t == "say":
        console.print(f"[bold magenta]Nixin[/] {ev['text']}")
    elif t == "ask":
        opts = " / ".join(ev.get("options") or []) or ("haan / nahi" if ev["kind"] == "confirm" else "")
        console.print(f"[bold yellow]?[/] {ev['text']} [dim]{opts}[/]")
    elif t == "heard":
        console.print(f"[dim]🎙 heard:[/] {ev['text']}")
    elif t == "agent":
        k = ev.get("kind")
        if k == "start":
            console.print(f"[magenta]🤖 agent:[/] {ev['goal']}")
        elif k == "plan":
            args = ", ".join(f"{a}={v!r}" for a, v in (ev.get("args") or {}).items())
            mark = "" if ev.get("valid") else f" [red]✗ {ev.get('error')}[/]"
            console.print(f"   [dim]💭 {ev['tool']}({args})[/]{mark}")
        elif k == "act":
            console.print(f"   [{'green' if ev.get('ok') else 'red'}]👉 {ev['tool']} → {ev.get('result')}[/]")
        elif k == "verify":
            console.print(f"   [dim]✔ verifier: {'done' if ev.get('done') is not False else 'not done'} — {ev.get('reason')}[/]")
    elif t == "classified":
        console.print(f"[dim]🧠 {ev.get('model')}: {', '.join(i['kind'] for i in ev.get('intents', []))}[/]")
    elif t == "log" and ev.get("level") in ("warning", "error"):
        console.print(f"[yellow]! {ev['msg']}[/]")
    elif t == "log":
        console.print(f"[dim]· {ev['msg']}[/]")
    elif t == "phone":
        if ev.get("connected"):
            console.print(f"[green]📱 phone connected:[/] {(ev.get('device') or {}).get('name')}")
        else:
            console.print(f"[red]📱 phone disconnected[/] [dim]{ev.get('reason', '')}[/]")
    elif t == "paired":
        console.print(f"[green]🔗 paired {ev['device']['name']}[/]")


def _show_pairing(app) -> None:
    import segno

    offer = app.new_pairing()
    console.print("\n[bold]Scan with the Nixin app → Pair with PC[/] (single use, expires in "
                  f"{app.cfg.link.pairing_minutes} min):")
    qr = segno.make(offer.uri, error="m")
    with contextlib.suppress(Exception):
        qr.terminal(compact=True)
    console.print(f"[dim]Endpoints: {', '.join(offer.payload['endpoints'])}[/]")
    console.print(f"[dim]Or paste this link in the app:[/] {offer.uri}\n")


def _status_table(app) -> Table:
    tbl = Table(show_header=False, box=None)
    d = app.phone.describe()
    st = d["status"] or {}
    tbl.add_row("Phone", f"[green]{d['device']['name']}[/]" if d["connected"] else "[red]not connected[/]")
    if d["connected"]:
        tbl.add_row("Battery", f"{(st.get('battery') or {}).get('level', '?')}%")
        tbl.add_row("Foreground", str((st.get("foreground") or {}).get("label")))
        tbl.add_row("Stopped", str(st.get("stopped")))
        perms = st.get("permissions") or {}
        tbl.add_row("Permissions", ", ".join(f"{k}{'✓' if v else '✗'}" for k, v in perms.items()))
    tbl.add_row("LLM", "ready" if app.gateway.any_ready() else "[red]no key[/] (add GROQ_API_KEY to .env)")
    tbl.add_row("Voice", "on" if app.voice else "off")
    if app.dashboard_token:
        tbl.add_row("Dashboard", app.dashboard_url())
    return tbl


def _models_table(gateway) -> Table:
    tbl = Table(title="Model roles (first usable candidate wins)")
    for c in ("role", "candidate", "key", "status", "today"):
        tbl.add_column(c)
    for role, cands in gateway.status()["roles"].items():
        for i, c in enumerate(cands):
            status = "unavailable" if c["available"] is False else ("ok" if c["available"] else "untested")
            tbl.add_row(role if i == 0 else "", c["spec"], "✓" if c["configured"] else "–",
                        f"[red]{status}[/]" if status == "unavailable" else status,
                        f"{c['today']['requests']} req / {c['today']['tokens']} tok")
    return tbl


# ---------------------------------------------------------------------------- run
async def _run(cfg: NixinConfig, *, repl: bool, sim: bool, open_browser: bool) -> None:
    from nixin.app import NixinApp

    app = NixinApp(cfg)
    q = app.bus.subscribe()
    try:
        await app.start()
    except RuntimeError as e:
        console.print(f"[red]Could not start:[/] {e}\nIs another Nixin already running on port {cfg.link.port}?")
        return
    token_file = cfg.data_path / "dashboard.token"
    if app.dashboard_token:
        token_file.write_text(json.dumps({"url": app.dashboard_url(), "token": app.dashboard_token,
                                          "port": cfg.dashboard.port}))
        with contextlib.suppress(OSError):
            os.chmod(token_file, 0o600)

    async def printer():
        while True:
            _print_event(await q.get())

    printer_task = asyncio.create_task(printer())
    console.print(BANNER.format(v=__version__))
    console.print(_status_table(app))
    console.print(HELP.format(ptt=cfg.voice.push_to_talk, kill=cfg.voice.kill_switch))

    sim_task = None
    if sim:
        sim_task = asyncio.create_task(_embedded_sim(app))
    elif not app.store.list_devices():
        _show_pairing(app)
    if open_browser and app.dashboard_token and cfg.dashboard.open_browser:
        with contextlib.suppress(Exception):
            webbrowser.open(app.dashboard_url())

    stop = asyncio.Event()
    if repl and sys.stdin and sys.stdin.isatty():
        loop = asyncio.get_running_loop()
        lines: asyncio.Queue[str | None] = asyncio.Queue()

        def reader():
            while True:
                try:
                    line = input()
                except (EOFError, KeyboardInterrupt):
                    loop.call_soon_threadsafe(lines.put_nowait, None)
                    return
                loop.call_soon_threadsafe(lines.put_nowait, line)

        threading.Thread(target=reader, daemon=True).start()

        async def repl_loop():
            while True:
                line = await lines.get()
                if line is None:
                    stop.set()
                    return
                line = line.strip()
                if not line:
                    continue
                cmd = line.lower()
                if cmd in ("/quit", "/exit", "/q"):
                    stop.set()
                    return
                if cmd == "/help":
                    console.print(HELP.format(ptt=cfg.voice.push_to_talk, kill=cfg.voice.kill_switch))
                elif cmd == "/pair":
                    _show_pairing(app)
                elif cmd == "/status":
                    if app.phone.connected:
                        with contextlib.suppress(Exception):
                            await app.phone.refresh_status()
                    console.print(_status_table(app))
                elif cmd == "/models":
                    console.print(_models_table(app.gateway))
                elif cmd == "/devices":
                    for d in app.store.list_devices():
                        console.print(f"{d['device_id']}  {d['name']}  {'(removed)' if d['revoked'] else ''}")
                elif cmd == "/cancel":
                    console.print(app.brain.cancel_current())
                elif cmd == "/mute":
                    if app.voice:
                        app.voice.speaker.muted = not app.voice.speaker.muted
                        console.print(f"TTS {'muted' if app.voice.speaker.muted else 'unmuted'}")
                else:
                    asyncio.create_task(app.brain.handle(line, source="typed"))

        asyncio.create_task(repl_loop())
    try:
        await stop.wait()
    except asyncio.CancelledError:
        pass
    finally:
        printer_task.cancel()
        if sim_task:
            sim_task.cancel()
        with contextlib.suppress(OSError):
            token_file.unlink()
        await app.stop()


async def _embedded_sim(app) -> None:
    from nixin.sim.client import DeviceIdentity, PhoneClient, parse_pairing_uri
    from nixin.sim.phone_sim import SimPhone

    sim = SimPhone()
    endpoint = f"wss://127.0.0.1:{app.link_server.port}/link"
    ident_file = app.cfg.data_path / "sim_device.json"
    if ident_file.exists() and app.store.get_device(DeviceIdentity.load(ident_file).device_id):
        ident = DeviceIdentity.load(ident_file)
        ident.endpoints = [endpoint]
        client = PhoneClient(ident, sim.handle)
        await client.connect()
    else:
        ident = DeviceIdentity.new()
        client = PhoneClient(ident, sim.handle)
        await client.pair(parse_pairing_uri(app.pairing.create([endpoint]).uri))
        ident.save(ident_file)
    app.bus.emit("log", level="info", msg="Simulated phone connected (demo mode). Try: WhatsApp pe Mummy ko bol main aa raha hoon")
    await client.serve()


# ---------------------------------------------------------------------------- sim (standalone)
async def _sim(cfg: NixinConfig, pair_uri: str | None) -> None:
    from nixin.sim.client import DeviceIdentity, PhoneClient, parse_pairing_uri
    from nixin.sim.phone_sim import SimPhone

    ident_file = cfg.data_path / "sim_device.json"
    sim = SimPhone()
    if pair_uri:
        ident = DeviceIdentity.new()
        client = PhoneClient(ident, sim.handle)
        await client.pair(parse_pairing_uri(pair_uri))
        ident.save(ident_file)
    elif ident_file.exists():
        client = PhoneClient(DeviceIdentity.load(ident_file), sim.handle)
        await client.connect()
    else:
        console.print("[red]First run needs --pair \"nixin://pair?...\"[/] (type /pair in `nixin run` to get one)")
        return
    console.print("[green]Simulated phone connected.[/] Ctrl+C to stop.")

    async def show():
        while True:
            m = await client.inbox.get()
            if m["t"] == "say":
                console.print(f"[magenta]📱 phone shows:[/] {m['text']}")
            elif m["t"] == "ask":
                console.print(f"[yellow]📱 phone asks:[/] {m['text']} — answering 'yes' in 2s")
                await asyncio.sleep(2)
                await client.answer(m["id"], "yes")

    t = asyncio.create_task(show())
    try:
        await client.serve()
    finally:
        t.cancel()


# ---------------------------------------------------------------------------- doctor / models / send
async def _doctor(cfg: NixinConfig) -> None:
    from nixin.llm.gateway import Gateway
    from nixin.security.certs import local_ips

    ok = "[green]✓[/]"
    bad = "[red]✗[/]"
    warn = "[yellow]![/]"
    console.print(f"[bold]Nixin doctor[/] v{__version__} · Python {platform.python_version()} · {platform.system()} {platform.release()}")
    console.print(f"{ok} config: {cfg.source_path or '(defaults — run `nixin init` to create nixin.toml)'}")
    console.print(f"{ok} data dir: {cfg.data_path}")
    ips = local_ips()
    console.print(f"{ok if ips else bad} LAN addresses: {', '.join(ips) or 'none found — connect to Wi-Fi'}")
    for name, p in cfg.providers.items():
        keys = get_secret_pool(p.key_env) if p.key_env else []
        mark = ok if keys else (warn if name != "groq" else bad)
        console.print(f"{mark} {name}: {len(keys)} key(s)" + ("" if keys or not p.key_env else f"  (set {p.key_env} in .env)"))
    for mod, extra in (("sounddevice", "voice"), ("pynput", "voice"), ("edge_tts", "voice"), ("miniaudio", "voice"),
                       ("pyttsx3", "voice"), ("faster_whisper", "local-stt"), ("openwakeword", "wakeword"), ("keyring", "keyring")):
        try:
            __import__(mod)
            console.print(f"{ok} {mod}")
        except Exception:
            console.print(f"{warn} {mod} not installed (pip install \"nixin[{extra}]\")")
    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="input")
        console.print(f"{ok} microphone: {dev['name']}")
    except Exception as e:  # noqa: BLE001
        console.print(f"{warn} microphone: {e}")
    console.print(f"{ok if shutil.which('adb') else warn} adb: {shutil.which('adb') or 'not on PATH (only needed for ADB power mode)'}")
    gw = Gateway(cfg)
    report = await gw.probe()
    for name, r in report.items():
        mark = ok if r["status"] == "ok" else (warn if r["status"] in ("no key", "disabled") else bad)
        console.print(f"{mark} provider {name}: {r['status']}" + (f" ({r['models']} models)" if r.get("models") else ""))
    console.print(_models_table(gw))
    await gw.aclose()
    if platform.system() == "Windows":
        console.print(f"\n{warn} Windows firewall: allow inbound TCP {cfg.link.port} on [b]Private[/] networks, e.g. (admin PowerShell):\n"
                      f"  New-NetFirewallRule -DisplayName 'Nixin link' -Direction Inbound -Protocol TCP "
                      f"-LocalPort {cfg.link.port} -Profile Private -Action Allow")


async def _models(cfg: NixinConfig) -> None:
    from nixin.llm.gateway import Gateway

    gw = Gateway(cfg)
    await gw.probe()
    console.print(_models_table(gw))
    await gw.aclose()


def _send(cfg: NixinConfig, text: str) -> None:
    import httpx

    token_file = cfg.data_path / "dashboard.token"
    if not token_file.exists():
        console.print("[red]Nixin is not running (start it with `nixin run`).[/]")
        sys.exit(1)
    info = json.loads(token_file.read_text())
    r = httpx.post(f"http://127.0.0.1:{info['port']}/api/command", json={"text": text, "wait": True},
                   headers={"x-nixin-token": info["token"]}, timeout=300)
    r.raise_for_status()
    console.print(r.json().get("reply", ""))


EXAMPLE_TOML = (Path(__file__).resolve().parents[2] / "nixin.example.toml")
EXAMPLE_ENV = (Path(__file__).resolve().parents[2] / ".env.example")


def _init() -> None:
    for src, dst in ((EXAMPLE_TOML, Path("nixin.toml")), (EXAMPLE_ENV, Path(".env"))):
        if dst.exists():
            console.print(f"[yellow]{dst} exists — left unchanged[/]")
        elif src.exists():
            shutil.copy(src, dst)
            console.print(f"[green]created {dst}[/]")
        else:
            console.print(f"[red]template {src.name} not found[/]")
    console.print("Next: put your free Groq key in .env (https://console.groq.com/keys), then `nixin run`.")


def _keys(provider: str) -> None:
    from getpass import getpass

    from nixin.config import _default_providers

    envs = {n: p.key_env for n, p in _default_providers().items() if p.key_env}
    if provider not in envs:
        console.print(f"Unknown provider. Choose: {', '.join(envs)}")
        return
    try:
        import keyring
    except ImportError:
        console.print(f"keyring not installed. Put {envs[provider]}=... in .env instead (or pip install \"nixin[keyring]\").")
        return
    key = getpass(f"{envs[provider]}: ").strip()
    if key:
        keyring.set_password("nixin", envs[provider], key)
        console.print(f"[green]Saved {envs[provider]} to the OS keyring.[/]")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="nixin", description="Nixin — voice-controlled AI agent for your Android phone")
    p.add_argument("--config", help="path to nixin.toml")
    p.add_argument("--version", action="version", version=f"nixin {__version__}")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="start the brain (default)")
    r.add_argument("--no-voice", action="store_true")
    r.add_argument("--no-dashboard", action="store_true")
    r.add_argument("--no-browser", action="store_true")
    sub.add_parser("demo", help="run with a simulated phone (no phone needed)")
    s = sub.add_parser("sim", help="run a simulated phone that connects to a running brain")
    s.add_argument("--pair", help="pairing link nixin://pair?... (first run)")
    sub.add_parser("doctor", help="check setup: keys, providers, audio, network")
    sub.add_parser("models", help="show model roles and availability")
    snd = sub.add_parser("send", help="send one command to the running brain")
    snd.add_argument("text", nargs="+")
    sub.add_parser("init", help="create nixin.toml and .env in the current folder")
    k = sub.add_parser("keys", help="store an API key in the OS keyring")
    k.add_argument("provider")
    sub.add_parser("devices", help="list paired phones")
    u = sub.add_parser("unpair", help="remove a paired phone")
    u.add_argument("device_id")
    args = p.parse_args(argv)

    if args.cmd == "init":
        _init()
        return
    if args.cmd == "keys":
        _keys(args.provider)
        return
    cfg = load_config(args.config)
    cmd = args.cmd or "run"
    try:
        if cmd == "run":
            if args.no_voice:
                cfg.voice.enabled = False
            if args.no_dashboard:
                cfg.dashboard.enabled = False
            asyncio.run(_run(cfg, repl=True, sim=False, open_browser=not args.no_browser))
        elif cmd == "demo":
            cfg.voice.enabled = False
            cfg.pc.data_dir = str(cfg.data_path / "demo")
            asyncio.run(_run(cfg, repl=True, sim=True, open_browser=True))
        elif cmd == "sim":
            asyncio.run(_sim(cfg, args.pair))
        elif cmd == "doctor":
            asyncio.run(_doctor(cfg))
        elif cmd == "models":
            asyncio.run(_models(cfg))
        elif cmd == "send":
            _send(cfg, " ".join(args.text))
        elif cmd == "devices":
            from nixin.core.store import Store

            for d in Store(cfg.data_path / "nixin.db").list_devices():
                console.print(f"{d['device_id']}  {d['name']}  {d['model'] or ''}  {'(removed)' if d['revoked'] else ''}")
        elif cmd == "unpair":
            from nixin.core.store import Store

            ok = Store(cfg.data_path / "nixin.db").revoke_device(args.device_id)
            console.print("removed" if ok else "not found")
    except KeyboardInterrupt:
        console.print("\nbye 👋")

