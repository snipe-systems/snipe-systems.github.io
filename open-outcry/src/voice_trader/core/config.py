"""Configuration loading (.yaml + .env) with sane defaults."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "config.yaml"


def find_config_path() -> Path:
    env = os.environ.get("VOICE_TRADER_CONFIG")
    if env:
        return Path(env)
    cwd = Path.cwd() / "config" / "config.yaml"
    if cwd.exists():
        return cwd
    return DEFAULT_CONFIG


def load_config(path: str | Path | None = None, apply_env: bool = True) -> dict:
    p = Path(path) if path else find_config_path()
    if not p.exists():
        raise FileNotFoundError(f"config not found at {p}")
    with open(p) as f:
        config = yaml.safe_load(f) or {}
    if apply_env:
        apply_env_overrides(config)
    return config


def apply_env_overrides(config: dict) -> dict:
    """Overlay `VOICE_TRADER_*` environment variables onto the config dict.

    Two conventions are supported:
      - top-level shorthands:  VOICE_TRADER_MODE, VOICE_TRADER_ACTIVE_BROKER
      - nested paths:          VOICE_TRADER__RISK__MAX_ORDER_VALUE  -> risk.max_order_value
                               VOICE_TRADER__BROKER__ALPACA__BASE_URL -> broker.alpaca.base_url

    Values are coerced to int/float/bool when possible, so Docker/CI can set
    numeric and boolean limits as env vars.
    """
    for key, val in os.environ.items():
        if key == "VOICE_TRADER_MODE":
            config["mode"] = val
        elif key == "VOICE_TRADER_ACTIVE_BROKER":
            config["active_broker"] = val
        elif key == "VOICE_TRADER_CONFIG":
            continue  # handled by find_config_path
        elif key.startswith("VOICE_TRADER__"):
            parts = key[len("VOICE_TRADER__"):].lower().split("__")
            _set_nested(config, parts, _coerce(val))
    return config


def _coerce(value: str):
    v = value.strip()
    low = v.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return value


def _set_nested(mapping: dict, keys: list[str], value) -> None:
    if not keys:
        return
    key = keys[0]
    if len(keys) == 1:
        mapping[key] = value
        return
    child = mapping.get(key)
    if not isinstance(child, dict):
        child = {}
        mapping[key] = child
    _set_nested(child, keys[1:], value)


def load_env(path: str | Path | None = None) -> None:
    """Load .env into os.environ (never overwriting existing vars)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    p = Path(path) if path else Path.cwd() / ".env"
    if p.exists():
        load_dotenv(p, override=False)
