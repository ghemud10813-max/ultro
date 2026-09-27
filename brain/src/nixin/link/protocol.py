"""Nixin Link protocol: method registry (from shared/protocol/methods.json) and errors."""

from __future__ import annotations

import json
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

RISKS = ("read", "nav", "local", "external")


def _methods_file() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent / "methods.json",  # wheel install (force-included)
        here.parents[4] / "shared" / "protocol" / "methods.json",  # repo checkout / editable install
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("methods.json not found; expected shared/protocol/methods.json")


@lru_cache(maxsize=1)
def registry() -> dict[str, Any]:
    return json.loads(_methods_file().read_text(encoding="utf-8"))


@cache
def _validator(method: str) -> Draft202012Validator:
    return Draft202012Validator(registry()["methods"][method]["params"])


def method_names() -> list[str]:
    return sorted(registry()["methods"])


def risk_of(method: str) -> str:
    return registry()["methods"][method]["risk"]


def validate_params(method: str, params: dict) -> None:
    """Raise PhoneError(bad_request) if params do not match the registry schema."""
    if method not in registry()["methods"]:
        raise PhoneError("unknown_method", f"Unknown method {method}")
    errors = sorted(_validator(method).iter_errors(params), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        where = ".".join(str(p) for p in e.path) or "params"
        raise PhoneError("bad_request", f"{method}: {where}: {e.message}")


def error_text(code: str) -> str:
    return registry()["errors"].get(code, code)


class PhoneError(Exception):
    """An error reported by (or about) the phone. ``code`` is a stable protocol error code."""

    def __init__(self, code: str, message: str = "", details: dict | None = None) -> None:
        self.code = code
        self.message = message or error_text(code)
        self.details = details or {}
        super().__init__(f"{code}: {self.message}")

    @property
    def uncertain(self) -> bool:
        return self.code in ("action.uncertain",)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **({"details": self.details} if self.details else {})}
