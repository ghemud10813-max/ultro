from __future__ import annotations

import pytest

from nixin.config import NixinConfig, PcConfig
from nixin.core.events import EventBus
from nixin.core.store import Store


@pytest.fixture
def cfg(tmp_path) -> NixinConfig:
    c = NixinConfig(pc=PcConfig(name="Test-PC", data_dir=str(tmp_path / "data")))
    c.voice.enabled = False
    c.dashboard.enabled = False
    return c


@pytest.fixture
def store() -> Store:
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()
