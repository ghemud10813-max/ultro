"""A Python implementation of the phone side of the Nixin Link protocol.

Used by the phone simulator (``nixin sim``) and by the test-suite. It performs the
exact same handshake as the Android app: certificate pinning, ECDSA P-256 device key,
pair/auth signatures, then serves ``req`` messages through a handler.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from nixin.security.pairing import auth_message, b64decode_any, b64url, pair_message

Handler = Callable[[str, dict, dict], Awaitable[dict]]  # method, params, meta -> result (raise SimError)


class SimError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code, self.message = code, message or code
        super().__init__(f"{code}: {message}")


@dataclass
class DeviceIdentity:
    device_id: str
    private_key: ec.EllipticCurvePrivateKey
    pc_id: str | None = None
    fingerprint: str | None = None
    endpoints: list[str] = field(default_factory=list)

    @property
    def public_key_b64(self) -> str:
        der = self.private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return b64url(der)

    def sign(self, data: bytes) -> str:
        return b64url(self.private_key.sign(data, ec.ECDSA(hashes.SHA256())))

    @classmethod
    def new(cls) -> DeviceIdentity:
        return cls(str(uuid.uuid4()), ec.generate_private_key(ec.SECP256R1()))

    def save(self, path: Path) -> None:
        pem = self.private_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        path.write_text(json.dumps({"deviceId": self.device_id, "key": pem, "pcId": self.pc_id,
                                    "fp": self.fingerprint, "endpoints": self.endpoints}))

    @classmethod
    def load(cls, path: Path) -> DeviceIdentity:
        d = json.loads(path.read_text())
        key = serialization.load_pem_private_key(d["key"].encode(), password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        return cls(d["deviceId"], key, d.get("pcId"), d.get("fp"), d.get("endpoints") or [])


def parse_pairing_uri(uri: str) -> dict:
    """nixin://pair?d=<base64url json> -> payload dict."""
    if "d=" not in uri:
        return json.loads(uri)  # raw JSON pasted
    data = uri.split("d=", 1)[1].split("&", 1)[0]
    return json.loads(b64decode_any(data))


def _pinned_ssl() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # we verify the pinned fingerprint ourselves right after connect
    return ctx


class PhoneClient:
    def __init__(self, identity: DeviceIdentity, handler: Handler, *, name: str = "Nixin Simulator",
                 model: str = "sim", sdk: int = 34) -> None:
        self.identity = identity
        self.handler = handler
        self.name, self.model, self.sdk = name, model, sdk
        self.ws = None
        self.welcome: dict | None = None
        self.inbox: asyncio.Queue[dict] = asyncio.Queue()  # say / ask / cancel / task messages
        self._tasks: set[asyncio.Task] = set()

    async def _open(self, endpoint: str):
        ws = await websockets.connect(endpoint, ssl=_pinned_ssl(), max_size=8 * 1024 * 1024, open_timeout=10)
        der = ws.transport.get_extra_info("ssl_object").getpeercert(binary_form=True)
        fp = hashlib.sha256(der).hexdigest()
        if self.identity.fingerprint and fp != self.identity.fingerprint:
            await ws.close()
            raise SimError("auth.certificate_mismatch", "PC certificate does not match the pinned fingerprint")
        return ws

    async def pair(self, pairing: dict) -> dict:
        self.identity.pc_id = pairing["pcId"]
        self.identity.fingerprint = pairing["fp"]
        self.identity.endpoints = pairing["endpoints"]
        last: Exception | None = None
        for ep in pairing["endpoints"]:
            try:
                ws = await self._open(ep)
            except Exception as e:  # try next endpoint
                last = e
                continue
            hello = json.loads(await ws.recv())
            msg = {
                "t": "pair", "v": 1, "deviceId": self.identity.device_id, "token": pairing["token"],
                "publicKey": self.identity.public_key_b64, "deviceName": self.name, "model": self.model,
                "sdk": self.sdk, "appVersion": "sim",
                "sig": self.identity.sign(pair_message(hello["pcId"], hello["nonce"], pairing["token"],
                                                       self.identity.device_id)),
            }
            return await self._finish_handshake(ws, msg)
        raise SimError("device.offline", f"No endpoint reachable: {last}")

    async def connect(self) -> dict:
        last: Exception | None = None
        for ep in self.identity.endpoints:
            try:
                ws = await self._open(ep)
            except Exception as e:
                last = e
                continue
            hello = json.loads(await ws.recv())
            msg = {
                "t": "auth", "v": 1, "deviceId": self.identity.device_id, "sdk": self.sdk, "appVersion": "sim",
                "sig": self.identity.sign(auth_message(hello["pcId"], hello["nonce"], self.identity.device_id)),
            }
            return await self._finish_handshake(ws, msg)
        raise SimError("device.offline", f"No endpoint reachable: {last}")

    async def _finish_handshake(self, ws, msg: dict) -> dict:
        await ws.send(json.dumps(msg))
        reply = json.loads(await ws.recv())
        if reply.get("t") != "welcome":
            await ws.close()
            raise SimError(reply.get("code", "auth.failed"), reply.get("message", ""))
        self.ws = ws
        self.welcome = reply
        return reply

    async def send(self, msg: dict) -> None:
        assert self.ws is not None
        await self.ws.send(json.dumps(msg))

    async def send_command(self, text: str, source: str = "phone_text") -> None:
        await self.send({"t": "cmd", "id": str(uuid.uuid4()), "text": text, "source": source})

    async def send_event(self, name: str, data: dict) -> None:
        await self.send({"t": "event", "name": name, "data": data})

    async def share(self, text: str, subject: str | None = None) -> None:
        await self.send({"t": "share", "text": text, **({"subject": subject} if subject else {})})

    async def send_file(self, name: str, data: bytes, mime: str = "application/octet-stream", chunk: int = 300_000) -> str:
        import base64

        tid = uuid.uuid4().hex
        total = max(1, -(-len(data) // chunk))
        for i in range(total):
            await self.send({"t": "file", "transferId": tid, "name": name, "mime": mime, "index": i, "total": total,
                             "data": base64.b64encode(data[i * chunk:(i + 1) * chunk]).decode("ascii")})
        return tid

    async def answer(self, ask_id: str, value: str) -> None:
        await self.send({"t": "answer", "id": ask_id, "value": value})

    async def serve(self) -> None:
        """Process incoming messages until the socket closes."""
        assert self.ws is not None
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                t = msg.get("t")
                if t == "req":
                    task = asyncio.create_task(self._handle_req(msg))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
                elif t == "ping":
                    await self.send({"t": "pong", "ts": msg.get("ts")})
                else:
                    await self.inbox.put(msg)
        except websockets.ConnectionClosed:
            pass

    async def _handle_req(self, msg: dict) -> None:
        try:
            result = await self.handler(msg["method"], msg.get("params") or {}, msg.get("meta") or {})
            await self.send({"t": "res", "id": msg["id"], "ok": True, "result": result})
        except SimError as e:
            await self.send({"t": "res", "id": msg["id"], "ok": False, "error": {"code": e.code, "message": e.message}})
        except Exception as e:  # noqa: BLE001
            await self.send({"t": "res", "id": msg["id"], "ok": False, "error": {"code": "internal", "message": repr(e)}})

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
