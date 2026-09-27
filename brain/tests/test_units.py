"""Small units: confirmation parsing, app matching, screen rendering, toggles, protocol registry, VAD, STT."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from nixin.agent.screen import render, screen_hash
from nixin.agent.tools import check_tool
from nixin.config import NixinConfig
from nixin.core.actions import find_toggle, normalize_number
from nixin.core.confirm import ConfirmationGate, _pick_option, parse_yes_no
from nixin.core.events import EventBus
from nixin.core.memory import match_app
from nixin.link.protocol import PhoneError, method_names, registry, risk_of, validate_params
from nixin.voice.audio import EnergyVad, VadConfig, to_wav
from nixin.voice.stt import GroqWhisper

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("text,exp", [("haan", "yes"), ("haan bhej do", "yes"), ("yes", "yes"), ("theek hai", "yes"),
                                      ("ok", "yes"), ("nahi", "no"), ("no", "no"), ("mat karo", "no"), ("cancel", "no"),
                                      ("banana", None)])
def test_yes_no(text, exp):
    assert parse_yes_no(text) == exp


def test_pick_option():
    opts = ["Rahul Sharma", "Rahul Verma"]
    assert _pick_option("dusra", opts) == "Rahul Verma"
    assert _pick_option("sharma", opts) == "Rahul Sharma"
    assert _pick_option("rahul", opts) is None


async def test_gate_answer_and_timeout():
    g = ConfirmationGate(EventBus(), timeout=0.3)
    assert await g.ask("?", timeout=0.2) is None
    t = asyncio.create_task(g.ask("Send?"))
    await asyncio.sleep(0.01)
    assert g.answer(None, "maybe") is False  # not a yes/no
    assert g.answer(None, "haan") is True
    assert await t == "yes"


def test_match_app():
    apps = [{"label": "WhatsApp", "package": "com.whatsapp"}, {"label": "Samsung Notes", "package": "com.samsung.android.app.notes"},
            {"label": "YouTube Music", "package": "com.google.android.apps.youtube.music"}]
    assert match_app("whatsapp", apps).package == "com.whatsapp"
    assert match_app("notes", apps).package == "com.samsung.android.app.notes"
    assert match_app("youtube music", apps).package == "com.google.android.apps.youtube.music"
    assert match_app("zzz", apps) is None
    assert match_app("bank", apps, {"bank": "com.x"}).package == "com.x"


def test_normalize_number():
    assert normalize_number("98765 43210") == "+919876543210"
    assert normalize_number("+1 (415) 555-0100") == "+14155550100"
    assert normalize_number("09876543210") == "+919876543210"


SNAP = {"snapshotId": "s1", "package": "com.android.settings", "app": "Settings", "width": 1080, "height": 2400,
        "elements": [
            {"id": 1, "role": "text", "text": "Wi-Fi", "b": [40, 300, 700, 380], "flags": []},
            {"id": 2, "role": "switch", "desc": "Wi-Fi", "b": [900, 300, 1040, 380], "flags": ["click"], "checked": False},
            {"id": 3, "role": "input", "hint": "Password", "b": [0, 500, 900, 580], "flags": ["click", "edit", "pwd"]},
        ]}


def test_render_and_hash():
    text = render(SNAP)
    assert "[2] switch desc=\"Wi-Fi\" (off) @970,340" in text
    assert "password" in text
    s2 = json.loads(json.dumps(SNAP))
    s2["elements"][1]["checked"] = True
    assert screen_hash(SNAP) != screen_hash(s2)


def test_find_toggle():
    assert find_toggle(SNAP, ["wi-fi", "wifi"])["id"] == 2
    assert find_toggle(SNAP, ["bluetooth"]) is None


def test_check_tool():
    assert check_tool("tap", {"id": 2}, SNAP, False).ok
    assert not check_tool("tap", {"id": 9}, SNAP, False).ok
    assert not check_tool("type_text", {"id": 3, "text": "hunter2"}, SNAP, False).ok  # password field
    assert not check_tool("rm_rf", {}, SNAP, False).ok
    assert not check_tool("tap_xy", {"x": 5000, "y": 10}, SNAP, False).ok
    assert not check_tool("look", {"question": "?"}, SNAP, False).ok


def test_registry_matches_shared_file_and_validates():
    shared = json.loads((ROOT / "shared" / "protocol" / "methods.json").read_text())
    assert registry() == shared
    assert risk_of("comm.whatsapp") == "external"
    assert all(risk_of(m) in ("read", "nav", "local", "external") for m in method_names())
    validate_params("ui.tap", {"elementId": 3})
    with pytest.raises(PhoneError):
        validate_params("ui.tap", {})
    with pytest.raises(PhoneError):
        validate_params("intent.url", {"url": "javascript:alert(1)"})
    with pytest.raises(PhoneError):
        validate_params("app.open", {"package": "com.x; rm -rf"})


def test_vad():
    v = EnergyVad(VadConfig(max_seconds=5, silence_seconds=0.3, start_timeout=1))
    states = [v.push(100) for _ in range(10)]  # calibrate on noise
    states += [v.push(5000) for _ in range(20)]  # speech
    states += [v.push(100) for _ in range(15)]  # silence -> end
    assert "speech" in states and states[-1] == "end"
    v2 = EnergyVad(VadConfig(start_timeout=0.3))
    assert [v2.push(100) for _ in range(20)][-1] == "timeout"


async def test_groq_whisper_parsing(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")

    def h(req):
        assert req.url.path.endswith("/audio/transcriptions")
        return httpx.Response(200, json={"text": " volume badha do ", "language": "hi",
                                         "segments": [{"avg_logprob": -0.1, "no_speech_prob": 0.01}]})

    stt = GroqWhisper(NixinConfig(), httpx.AsyncClient(transport=httpx.MockTransport(h)))
    tr = await stt.transcribe(to_wav(b"\x00\x00" * 1600))
    assert tr.text == "volume badha do" and tr.confidence > 0.85
