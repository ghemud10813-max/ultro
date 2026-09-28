"""Nixin 2.0 feature modules. ``install_features(app)`` builds them and registers their intent handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nixin.app import NixinApp
    from nixin.features.base import Feature


def install_features(app: NixinApp) -> list[Feature]:
    from nixin.features.bridge import Bridge
    from nixin.features.briefing import WeatherFeature
    from nixin.features.notifications import NotificationCenter
    from nixin.features.pc import PcFeature
    from nixin.features.phone_extras import PhoneExtras
    from nixin.features.plugins import PluginManager
    from nixin.features.routines import RoutineEngine
    from nixin.features.screen import ScreenReader
    from nixin.features.skills import Skills

    app.pc = PcFeature(app)
    app.bridge = Bridge(app)
    app.notifications = NotificationCenter(app)
    app.weather = WeatherFeature(app)
    app.extras = PhoneExtras(app)
    app.screen = ScreenReader(app)
    app.skills = Skills(app)
    app.routines = RoutineEngine(app)
    app.plugins = PluginManager(app)
    features: list[Feature] = [app.pc, app.bridge, app.notifications, app.weather, app.extras, app.screen, app.skills,
                               app.routines, app.plugins]
    for f in features:
        f.install()
    return features
