"""Repo and data locations for scripts/s0. DATA_ROOT is the single data-location setting in config/project.toml:
an absolute path is used as is; a relative path is resolved against the repo root."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_config() -> dict:
    return tomllib.loads((ROOT / "config" / "project.toml").read_text(encoding="utf-8"))


def data_root(cfg: dict | None = None) -> Path:
    p = Path((cfg or load_config())["DATA_ROOT"])
    return p if p.is_absolute() else ROOT / p


DATA = data_root()
