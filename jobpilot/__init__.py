from pathlib import Path

import yaml
from pydantic import BaseModel

_CONFIG: dict | None = None
_ROOT = Path(__file__).resolve().parent.parent


def get_root() -> Path:
    return _ROOT


def load_config(path: Path | None = None) -> dict:
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    cfg_path = path or _ROOT / "config" / "settings.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Config not found at {cfg_path}. Copy config/settings.example.yaml to config/settings.yaml"
        )
    with open(cfg_path, encoding="utf-8") as f:
        _CONFIG = yaml.safe_load(f)
    return _CONFIG


def get(key: str, default=None):
    """Dot-notation config access: get('profile.salary_floor_usd')"""
    cfg = load_config()
    keys = key.split(".")
    val = cfg
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return default
        if val is None:
            return default
    return val
