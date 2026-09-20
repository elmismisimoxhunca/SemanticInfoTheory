#!/usr/bin/env python3
"""Sequential one-worker launcher for the 25 frozen Track B primary surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

PROTOCOL_SHA256 = "9180c10578a1c2f15f96e97ff93893e5e4889dad417531d50b8bc97c81fd04b2"
FREEZE_SHA256 = "ec2a97849acc0d93c71d2f8af9744808950e748d6056d5e71bef764d3ae63036"
CHECKPOINTS = [2**power for power in range(12, 24)]
EXPECTED_N = 2**23
CORPORA = ["B1", "B2", "B3", "B4", "B5"]


def checked_run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(prefix=path.name + ".tmp.", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def expected_provenance(corpus: str, draw: int) -> str:
    if corpus in {"B1", "B2", "B3"}:
        return "frozen deterministic consecutive disjoint slice; exact policy in TRACK_B_SOURCE_MANIFEST.json"
    if corpus == "B4":
        return f"controlled transform of B1_draw{draw}.bin; frozen sentence-unit shuffle seed {600 + draw}; prefix/suffix fixed"
    return f"controlled transform of B1_draw{draw}.bin; frozen within-unit word shuffle seed {700 + draw}; whitespace tokens fixed"


def validate_surface(path: Path, run_id: str, execution_hash: str) -> bool:
    if not path.is_file():
        return False
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        result.get("schema") == "block01-availability-surface-v1"
        and result.get("status") == "complete"
        and result.get("metadata", {}).get("run_id") == run_id
        and result.get("metadata", {}).get("freeze_sha256") == FREEZE_SHA256
        and result.get("metadata", {}).get("execution_manifest_sha256") == execution_hash
        and result.get("checkpoint_count") == len(CHECKPOINTS)
        and [checkpoint.get("n") for checkpoint in result.get("checkpoints", [])] == CHECKPOINTS
        and result.get("N") == EXPECTED_N
        and result.get("alphabet_size") == 256
        and result.get("k_max") == 16
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--execution-manifest-sha256", required=True)
    parser.add_argument("--keep-stores", action="store_true")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    corpus_root = args.corpus_root.resolve()
    output_root = args.output_root.resolve()
    execution_hash = args.execution_manifest_sha256.lower()
    if len(execution_hash) != 64 or any(c not in "0123456789abcdef" for c in execution_hash):
        raise ValueError("execution manifest SHA256 must have 64 lowercase hexadecimal digits")

    source_manifest_path = workspace / "TRACK_B_SOURCE_MANIFEST.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest_sha256 = sha256_file(source_manifest_path)
    corpus_hashes = source_manifest["corpus_hashes"]
    scorer = workspace / "build" / "kt_stream"
    if not scorer.is_file():
        raise RuntimeError("build/kt_stream is required")

    surface_dir = output_root / "surfaces"
    store_dir = output_root / "stores"
    surface_dir.mkdir(parents=True, exist_ok=True)
    store_dir.mkdir(parents=True, exist_ok=True)

    ordinal = 0
    for corpus_name in CORPORA:
        for draw in range(1, 6):
            ordinal += 1
            filename = f"{corpus_name}_draw{draw}.bin"
            corpus_path = corpus_root / filename
            run_id = f"B_{corpus_name}_draw{draw}"
            result_path = surface_dir / f"{run_id}.json"
            store_path = store_dir / f"{run_id}.store"
            print(f"[{ordinal:02d}/25] {run_id}", flush=True)
            if validate_surface(result_path, run_id, execution_hash):
                print(f"  explicit run-boundary reuse: verified completed {result_path}", flush=True)
                continue
            if not corpus_path.is_file() or corpus_path.stat().st_size != EXPECTED_N:
                raise RuntimeError(f"missing or wrong-length Track B corpus: {corpus_path}")
            declared_hash = corpus_hashes.get(filename)
            if not isinstance(declared_hash, str) or len(declared_hash) != 64:
                raise RuntimeError(f"missing frozen corpus hash for {filename}")

            sidecar_path = Path(str(corpus_path) + ".meta.json")
            sidecar = {
                "schema": "block01-corpus-v1",
                "track": "B",
                "alphabet_size": 256,
                "expected_n": EXPECTED_N,
                "run_id": run_id,
                "corpus_sha256": declared_hash,
                "protocol_sha256": PROTOCOL_SHA256,
                "freeze_sha256": FREEZE_SHA256,
                "execution_manifest_sha256": execution_hash,
                "source_manifest_sha256": source_manifest_sha256,
                "corpus": corpus_name,
                "draw_id": draw,
                "transformation_provenance": expected_provenance(corpus_name, draw),
            }
            if sidecar_path.exists():
                existing = json.loads(sidecar_path.read_text(encoding="utf-8"))
                if existing != sidecar:
                    raise RuntimeError(f"pre-existing Track B sidecar mismatch: {sidecar_path}")
            else:
                atomic_json(sidecar_path, sidecar)

            command = [
                str(scorer),
                "--corpus", str(corpus_path),
                "--output", str(result_path),
                "--store", str(store_path),
                "--k-max", "16",
                "--checkpoints", ",".join(str(value) for value in CHECKPOINTS),
                "--cache-mib", "2048",
            ]
            if args.keep_stores:
                command.append("--keep-store")
            checked_run(command)

    print("Track B launcher completed all 25 registered run identities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
