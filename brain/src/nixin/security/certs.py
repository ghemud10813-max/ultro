"""PC identity: a stable pcId plus a self-signed TLS certificate.

The phone pins the SHA-256 fingerprint of this certificate (delivered inside the
pairing QR), so no certificate authority or domain is needed and a LAN attacker
cannot impersonate the PC.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


@dataclass(frozen=True)
class PcIdentity:
    pc_id: str
    pc_name: str
    cert_path: Path
    key_path: Path
    fingerprint: str  # lowercase hex sha256 of the DER certificate


def _is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version != 4 or addr.is_loopback or addr.is_link_local:
        return False
    return addr.is_private or addr in ipaddress.ip_network("100.64.0.0/10")  # CGNAT = Tailscale


def local_ips() -> list[str]:
    """Private IPv4 addresses of this machine, primary route first."""
    found: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("10.255.255.255", 1))  # no packet is sent for UDP connect
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out: list[str] = []
    for ip in found:
        if _is_private(ip) and ip not in out:
            out.append(ip)
    return out


def cert_fingerprint(cert_path: Path) -> str:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def _generate_cert(cert_path: Path, key_path: Path, pc_name: str) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"Nixin PC {pc_name}"[:64]),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Nixin"),
    ])
    sans: list[x509.GeneralName] = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    for ip in local_ips():
        sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def ensure_identity(data_path: Path, pc_name: str) -> PcIdentity:
    tls = data_path / "tls"
    tls.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = tls / "nixin-cert.pem", tls / "nixin-key.pem"
    ident_file = data_path / "identity.json"

    if ident_file.exists():
        pc_id = json.loads(ident_file.read_text())["pcId"]
    else:
        pc_id = str(uuid.uuid4())
        ident_file.write_text(json.dumps({"pcId": pc_id}))

    if not (cert_path.exists() and key_path.exists()):
        _generate_cert(cert_path, key_path, pc_name)

    return PcIdentity(pc_id, pc_name, cert_path, key_path, cert_fingerprint(cert_path))


def rotate_certificate(data_path: Path, pc_name: str) -> PcIdentity:
    """Replace the TLS certificate. Every phone must re-pair afterwards."""
    tls = data_path / "tls"
    for f in ("nixin-cert.pem", "nixin-key.pem"):
        p = tls / f
        if p.exists():
            p.unlink()
    return ensure_identity(data_path, pc_name)
