#!/usr/bin/env python3
"""Sequential one-worker launcher for the 90 frozen Track A primary surfaces.

This script does not alter kernels, checkpoints, cache settings, or run order. It is
provided for the post-audit production phase and is not executed by the core handoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def checked_run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def valid_completed_surface(
    path: Path, run_id: str, freeze_sha256: str, execution_manifest_sha256: str
) -> bool:
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
        and result.get("metadata", {}).get("freeze_sha256") == freeze_sha256
        and result.get("metadata", {}).get("execution_manifest_sha256")
        == execution_manifest_sha256
        and result.get("checkpoint_count") == 12
        and [checkpoint.get("n") for checkpoint in result.get("checkpoints", [])]
        == [2**power for power in range(12, 24)]
        and result.get("N") == 2**23
        and result.get("alphabet_size") == 32
        and result.get("k_max") == 16
    )


def valid_existing_corpus(
    corpus: Path, run: dict, freeze_sha256: str, execution_manifest_sha256: str
) -> bool:
    sidecar = Path(str(corpus) + ".meta.json")
    if not corpus.is_file() or not sidecar.is_file():
        return False
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        metadata.get("schema") == "block01-corpus-v1"
        and metadata.get("track") == "A"
        and metadata.get("alphabet_size") == 32
        and metadata.get("expected_n") == run["n"]
        and metadata.get("run_id") == run["run_id"]
        and metadata.get("configuration") == run["configuration"]
        and metadata.get("seed") == run["seed"]
        and metadata.get("freeze_sha256") == freeze_sha256
        and metadata.get("execution_manifest_sha256") == execution_manifest_sha256
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--execution-manifest-sha256", required=True)
    parser.add_argument("--keep-stores", action="store_true")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    freeze_path = workspace / "REVB_FREEZE.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    runs = freeze["track_A"]["runs"]
    if len(runs) != 90:
        raise RuntimeError(f"expected 90 frozen Track A runs, found {len(runs)}")
    if len(args.execution_manifest_sha256) != 64 or any(
        character not in "0123456789abcdefABCDEF"
        for character in args.execution_manifest_sha256
    ):
        raise ValueError("execution manifest SHA256 must have 64 hexadecimal digits")

    generator = workspace / "build" / "generate_corpus"
    scorer = workspace / "build" / "kt_stream"
    if not generator.is_file() or not scorer.is_file():
        raise RuntimeError("build/generate_corpus and build/kt_stream are required")

    corpus_dir = args.output_root.resolve() / "corpora"
    surface_dir = args.output_root.resolve() / "surfaces"
    store_dir = args.output_root.resolve() / "stores"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    surface_dir.mkdir(parents=True, exist_ok=True)
    store_dir.mkdir(parents=True, exist_ok=True)

    actual_freeze_sha256 = "ec2a97849acc0d93c71d2f8af9744808950e748d6056d5e71bef764d3ae63036"
    if hashlib.sha256(freeze_path.read_bytes()).hexdigest() != actual_freeze_sha256:
        raise RuntimeError("REVB_FREEZE.json hash mismatch")
    if freeze["protocol"]["sha256"] != "9180c10578a1c2f15f96e97ff93893e5e4889dad417531d50b8bc97c81fd04b2":
        raise RuntimeError("unexpected frozen protocol hash")

    for ordinal, run in enumerate(runs, start=1):
        run_id = run["run_id"]
        corpus = corpus_dir / f"{run_id}.bin"
        surface = surface_dir / f"{run_id}.json"
        store = store_dir / f"{run_id}.store"
        print(f"[{ordinal:02d}/90] {run_id}", flush=True)
        if valid_completed_surface(
            surface, run_id, actual_freeze_sha256, args.execution_manifest_sha256
        ):
            print(f"  explicit run-boundary reuse: verified completed {surface}", flush=True)
            continue
        if not corpus.is_file() or not Path(str(corpus) + ".meta.json").is_file():
            if corpus.exists() or Path(str(corpus) + ".meta.json").exists():
                raise RuntimeError(f"incomplete pre-existing corpus pair for {run_id}")
            checked_run([
                str(generator),
                "--configuration", run["configuration"],
                "--seed", str(run["seed"]),
                "--n", str(run["n"]),
                "--output", str(corpus),
                "--execution-manifest-sha256", args.execution_manifest_sha256,
            ])
        elif not valid_existing_corpus(
            corpus, run, actual_freeze_sha256, args.execution_manifest_sha256
        ):
            raise RuntimeError(f"pre-existing corpus metadata mismatch for {run_id}")
        command = [
            str(scorer),
            "--corpus", str(corpus),
            "--output", str(surface),
            "--store", str(store),
            "--k-max", str(run["k_max"]),
            "--checkpoints", ",".join(str(value) for value in run["checkpoints"]),
            "--cache-mib", "2048",
        ]
        if args.keep_stores:
            command.append("--keep-store")
        checked_run(command)

    print("Track A launcher completed all 90 registered run identities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
