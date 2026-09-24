"""The on-disk cache of raw API responses under data/raw/.

Each response is stored byte for byte, gzip-compressed: play-by-play is about 440 KB per game
uncompressed and about 37 KB gzipped, so a regular season takes about 45 MB instead of 540 MB.
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile
from pathlib import Path

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def pbp_path(data_dir: Path, source: str, game_id: str) -> Path:
    """Where a game's raw play-by-play is cached: data/raw/{source}/{GAME_ID}.json.gz."""
    return Path(data_dir) / "raw" / source / f"{game_id}.json.gz"


def gamelog_path(data_dir: Path, season: str, season_type: str) -> Path:
    """Where a season's game list is cached, e.g. data/raw/gamelog/2025-26_playoffs.json.gz."""
    slug = season_type.lower().replace(" ", "_")
    return Path(data_dir) / "raw" / "gamelog" / f"{season}_{slug}.json.gz"


def save(path: Path, content: bytes) -> None:
    """Gzip a raw response and write it atomically, so an interrupted run never leaves a
    half-written cache file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(gzip.compress(content, mtime=0))
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def read_json(path: Path) -> dict:
    """Read a cached response back as JSON."""
    with gzip.open(path, "rb") as f:
        return json.load(f)
