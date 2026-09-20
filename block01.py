"""Public Python facade for the frozen Block 01 Rev B availability surface."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Iterable


def _executable() -> Path:
    configured = os.environ.get("BLOCK01_KT_STREAM")
    if configured:
        path = Path(configured)
    else:
        path = Path(__file__).resolve().parent / "build" / "kt_stream"
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(
            f"kt_stream executable not found or not executable: {path}; "
            "set BLOCK01_KT_STREAM or build the project"
        )
    return path


def _validated_checkpoints(checkpoints: Iterable[int]) -> list[int]:
    values = list(checkpoints)
    previous = 0
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("checkpoints must contain integers")
        if value <= previous:
            raise ValueError("checkpoints must be positive, unique, and strictly increasing")
        previous = value
    return values


def availability(corpus_path: str | os.PathLike[str], k_max: int, checkpoints: Iterable[int]) -> dict:
    """Return the complete one-pass surface and frozen checkpoint diagnostics.

    The required metadata is read by the C++ engine from ``str(corpus_path) +
    '.meta.json'``. Alphabet selection is never inferred from corpus bytes.
    """

    if isinstance(k_max, bool) or not isinstance(k_max, int):
        raise TypeError("k_max must be an integer")
    if not 0 <= k_max <= 16:
        raise ValueError("k_max must be in 0..16")
    checkpoint_values = _validated_checkpoints(checkpoints)
    corpus = Path(corpus_path).resolve()
    if not corpus.is_file():
        raise FileNotFoundError(corpus)

    with tempfile.TemporaryDirectory(prefix="block01-availability-") as temporary:
        root = Path(temporary)
        result_path = root / "surface.json"
        store_path = root / "counts.store"
        command = [
            str(_executable()),
            "--corpus",
            str(corpus),
            "--output",
            str(result_path),
            "--store",
            str(store_path),
            "--k-max",
            str(k_max),
            "--checkpoints",
            ",".join(str(value) for value in checkpoint_values),
            "--cache-mib",
            "2048",
        ]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"kt_stream failed ({completed.returncode}): {detail}")
        with result_path.open("r", encoding="utf-8") as stream:
            result = json.load(stream)
    if result.get("schema") != "block01-availability-surface-v1":
        raise RuntimeError("unexpected kt_stream output schema")
    return result


__all__ = ["availability"]
