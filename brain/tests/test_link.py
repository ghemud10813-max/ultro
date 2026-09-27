"""Pairing, authentication and request/response over a real TLS WebSocket."""

from __future__ import annotations

import asyncio

import pytest

from nixin.core.serve import EmbeddedServer
from nixin.link.phone import PhoneLink
from nixin.link.protocol import PhoneError
from nixin.link.server import LinkServer
from nixin.security.certs import ensure_identity
from nixin.security.pairing import PairingManager
from nixin.sim.client import DeviceIdentity, PhoneClient, SimError, parse_pairing_uri


async def _handler(method, params, meta):
    if method == "device.status":
        return {"battery": {"level": 77, "charging": False}, "stopped": False}
    if method == "app.list":
        return {"apps": [{"label": "WhatsApp", "package": "com.whatsapp"}]}
    if method == "device.torch":
        return {"on": params["on"]}
    if method == "comm.sms":
        if not meta.get("confirmed"):
            raise SimError("policy.confirmation_required")
        return {"number": params["number"], "mode": "sent"}
    if method == "ui.wait":
        await asyncio.sleep(30)
    raise SimError("unknown_method", method)


@pytest.fixture
async def env(cfg, store, bus):
    ident = ensure_identity(cfg.data_path, "Test-PC")
    pairing = PairingManager(ident.pc_id, ident.pc_name, ident.fingerprint)
    phone = PhoneLink(bus, store)
    link = LinkServer(ident, pairing, phone, store, bus, heartbeat_seconds=15)
    server = EmbeddedServer(link.app, "127.0.0.1", 0, str(ident.cert_path), str(ident.key_path))
    await server.start()
    endpoint = f"wss://127.0.0.1:{server.port}/link"
    yield ident, pairing, phone, endpoint
    await server.stop()


async def _paired_client(pairing, endpoint):
    offer = pairing.create([endpoint])
    payload = parse_pairing_uri(offer.uri)
    client = PhoneClient(DeviceIdentity.new(), _handler)
    welcome = await client.pair(payload)
    return client, welcome, offer


async def test_pair_then_call(env, store):
    ident, pairing, phone, endpoint = env
    client, welcome, _ = await _paired_client(pairing, endpoint)
    assert welcome["paired"] is True
    serve = asyncio.create_task(client.serve())
    assert await phone.wait_connected(5)
    res = await phone.call("device.torch", {"on": True})
    assert res == {"on": True}
    assert store.get_device(client.identity.device_id)["name"] == "Nixin Simulator"
    # audit log written for the local action
    assert any(a["method"] == "device.torch" and a["ok"] == 1 for a in store.list_audit())
    await client.close()
    serve.cancel()


async def test_token_is_single_use(env):
    ident, pairing, phone, endpoint = env
    client, _, offer = await _paired_client(pairing, endpoint)
    await client.close()
    other = PhoneClient(DeviceIdentity.new(), _handler)
    with pytest.raises(SimError) as e:
        await other.pair(offer.payload)
    assert e.value.code == "auth.invalid_token"


async def test_reconnect_with_auth_and_reject_unknown(env):
    ident, pairing, phone, endpoint = env
    client, _, _ = await _paired_client(pairing, endpoint)
    await client.close()
    again = PhoneClient(client.identity, _handler)
    welcome = await again.connect()
    assert welcome["paired"] is False
    await again.close()

    stranger = DeviceIdentity.new()
    stranger.endpoints, stranger.fingerprint = [endpoint], ident.fingerprint
    with pytest.raises(SimError) as e:
        await PhoneClient(stranger, _handler).connect()
    assert e.value.code == "auth.unknown_device"


async def test_wrong_key_rejected(env):
    ident, pairing, phone, endpoint = env
    client, _, _ = await _paired_client(pairing, endpoint)
    await client.close()
    impostor = DeviceIdentity.new()
    impostor.device_id = client.identity.device_id  # same id, different key
    impostor.endpoints, impostor.fingerprint = [endpoint], ident.fingerprint
    with pytest.raises(SimError) as e:
        await PhoneClient(impostor, _handler).connect()
    assert e.value.code == "auth.bad_signature"


async def test_pinned_certificate_mismatch(env):
    ident, pairing, phone, endpoint = env
    offer = pairing.create([endpoint])
    payload = dict(offer.payload, fp="00" * 32)
    with pytest.raises(SimError) as e:
        await PhoneClient(DeviceIdentity.new(), _handler).pair(payload)
    assert "certificate" in e.value.code or "offline" in e.value.code


async def test_errors_and_validation(env):
    ident, pairing, phone, endpoint = env
    client, _, _ = await _paired_client(pairing, endpoint)
    serve = asyncio.create_task(client.serve())
    await phone.wait_connected(5)
    with pytest.raises(PhoneError) as e:
        await phone.call("device.volume", {"action": "sideways"})
    assert e.value.code == "bad_request"
    with pytest.raises(PhoneError) as e:
        await phone.call("comm.sms", {"number": "+911234567890", "text": "hi"})
    assert e.value.code == "policy.confirmation_required"
    res = await phone.call("comm.sms", {"number": "+911234567890", "text": "hi"}, confirmed=True)
    assert res["mode"] == "sent"
    await client.close()
    serve.cancel()


async def test_disconnect_fails_pending(env):
    ident, pairing, phone, endpoint = env
    client, _, _ = await _paired_client(pairing, endpoint)
    serve = asyncio.create_task(client.serve())
    await phone.wait_connected(5)
    call = asyncio.create_task(phone.call("ui.wait", {"text": "x"}, timeout=20))
    await asyncio.sleep(0.2)
    await client.close()
    with pytest.raises(PhoneError) as e:
        await call
    assert e.value.code == "device.offline"
    serve.cancel()


async def test_phone_command_reaches_brain(env):
    ident, pairing, phone, endpoint = env
    got: asyncio.Queue = asyncio.Queue()

    async def on_command(text, source, _id):
        await got.put((text, source))

    phone.on_command = on_command
    client, _, _ = await _paired_client(pairing, endpoint)
    serve = asyncio.create_task(client.serve())
    await phone.wait_connected(5)
    await client.send_command("torch on karo", "phone_voice")
    assert await asyncio.wait_for(got.get(), 5) == ("torch on karo", "phone_voice")
    await phone.say("Torch on kar diya")
    msg = await asyncio.wait_for(client.inbox.get(), 5)
    assert msg["t"] == "say" and msg["text"] == "Torch on kar diya"
    await client.close()
    serve.cancel()
