"""Project configuration (config/project.toml) and data locations."""
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "project.toml"
ENV_DATA_ROOT = "ORE_FLOW_DATA_ROOT"


def load_config(path: Path = CONFIG_PATH) -> dict:
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def data_root(cfg: dict) -> Path:
    """DATA_ROOT: $ORE_FLOW_DATA_ROOT if set, else config. Absolute path as is; relative path resolved against the
    repo root."""
    p = Path(os.environ.get(ENV_DATA_ROOT) or cfg["DATA_ROOT"])
    return p if p.is_absolute() else ROOT / p
