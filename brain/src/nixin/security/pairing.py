"""Pairing tokens, QR payloads and phone signature verification.

Flow (see docs/PROTOCOL.md):
  1. PC creates a single-use token (5 min) and shows a QR: nixin://pair?d=<base64url json>
  2. Phone scans it, pins the certificate fingerprint, creates an Android Keystore
     P-256 key and connects. The PC sends a random nonce in ``hello``.
  3. Phone sends ``pair`` with its public key and an ECDSA signature over
     "nixin-pair\\n<pcId>\\n<nonce>\\n<token>\\n<deviceId>".
  4. Later connections send ``auth`` with a signature over
     "nixin-auth\\n<pcId>\\n<nonce>\\n<deviceId>" — the private key never leaves the phone.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64decode_any(s: str) -> bytes:
    """Accept standard or url-safe base64, with or without padding."""
    s = s.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4))


def new_nonce() -> str:
    return b64url(secrets.token_bytes(32))


def pair_message(pc_id: str, nonce: str, token: str, device_id: str) -> bytes:
    return f"nixin-pair\n{pc_id}\n{nonce}\n{token}\n{device_id}".encode()


def auth_message(pc_id: str, nonce: str, device_id: str) -> bytes:
    return f"nixin-auth\n{pc_id}\n{nonce}\n{device_id}".encode()


def verify_signature(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    try:
        pub = load_der_public_key(b64decode_any(public_key_b64))
        if not isinstance(pub, ec.EllipticCurvePublicKey) or pub.curve.name != "secp256r1":
            return False
        pub.verify(b64decode_any(signature_b64), message, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


@dataclass
class PairingOffer:
    token: str
    expires_at: float
    payload: dict
    uri: str
    used: bool = False

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at


@dataclass
class PairingManager:
    pc_id: str
    pc_name: str
    fingerprint: str
    ttl_seconds: int = 300
    _offers: dict[str, PairingOffer] = field(default_factory=dict)

    def create(self, endpoints: list[str]) -> PairingOffer:
        self._gc()
        token = b64url(secrets.token_bytes(32))
        expires = time.time() + self.ttl_seconds
        payload = {
            "v": 1,
            "pcId": self.pc_id,
            "pcName": self.pc_name,
            "endpoints": endpoints,
            "fp": self.fingerprint,
            "token": token,
            "exp": int(expires),
        }
        uri = "nixin://pair?d=" + b64url(json.dumps(payload, separators=(",", ":")).encode())
        offer = PairingOffer(token, expires, payload, uri)
        self._offers[token] = offer
        return offer

    def is_valid(self, token: str) -> bool:
        o = self._offers.get(token)
        return bool(o and not o.used and not o.expired)

    def consume(self, token: str) -> bool:
        """Mark a token used. Returns False if it was unknown, used or expired."""
        o = self._offers.get(token)
        if not o or o.used or o.expired:
            return False
        o.used = True
        return True

    def active(self) -> PairingOffer | None:
        self._gc()
        live = [o for o in self._offers.values() if not o.used and not o.expired]
        return max(live, key=lambda o: o.expires_at) if live else None

    def _gc(self) -> None:
        now = time.time()
        for t in [t for t, o in self._offers.items() if now > o.expires_at + 600]:
            del self._offers[t]
