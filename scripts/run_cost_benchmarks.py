#!/usr/bin/env python3
"""Frozen supplementary n/K/alphabet timing matrix, executed only after primary passes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

PROTOCOL_SHA256 = "9180c10578a1c2f15f96e97ff93893e5e4889dad417531d50b8bc97c81fd04b2"
FREEZE_SHA256 = "ec2a97849acc0d93c71d2f8af9744808950e748d6056d5e71bef764d3ae63036"
NS = [2**12, 2**16, 2**20, 2**23]
KS = [0, 4, 8, 16]


def atomic_json(path: Path, value: dict) -> None:
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".tmp.", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def make_prefix(source: Path, destination: Path, n: int) -> str:
    if not destination.exists():
        temporary = destination.with_name(destination.name + ".tmp")
        with source.open("rb") as inp, temporary.open("wb") as out:
            remaining = n
            while remaining:
                chunk = inp.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError(f"early EOF in {source}")
                out.write(chunk)
                remaining -= len(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
    if destination.stat().st_size != n:
        raise RuntimeError(f"wrong benchmark prefix size: {destination}")
    return hash_file(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--track-b-corpus-root", type=Path, required=True)
    parser.add_argument("--execution-manifest-sha256", required=True)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    run_root = args.run_root.resolve()
    execution_hash = args.execution_manifest_sha256.lower()
    scorer = workspace / "build" / "kt_stream"
    source_manifest = workspace / "TRACK_B_SOURCE_MANIFEST.json"
    source_manifest_hash = hash_file(source_manifest)
    sources = {
        "A": run_root / "track_a" / "corpora" / "A_G4_s101.bin",
        "B": args.track_b_corpus_root.resolve() / "B1_draw1.bin",
    }
    benchmark_root = run_root / "cost_benchmarks"
    corpus_root = benchmark_root / "corpora"
    result_root = benchmark_root / "surfaces"
    store_root = benchmark_root / "stores"
    for path in (corpus_root, result_root, store_root):
        path.mkdir(parents=True, exist_ok=True)

    for track in ("A", "B"):
        source = sources[track]
        if not source.is_file() or source.stat().st_size != 2**23:
            raise RuntimeError(f"required post-primary benchmark source missing: {source}")
        for n in NS:
            corpus = corpus_root / f"cost_{track}_n{n}.bin"
            digest = make_prefix(source, corpus, n)
            run_id = f"COST_{track}_n{n}"
            sidecar = {
                "schema": "block01-corpus-v1", "track": track,
                "alphabet_size": 32 if track == "A" else 256,
                "expected_n": n, "run_id": run_id, "corpus_sha256": digest,
                "protocol_sha256": PROTOCOL_SHA256, "freeze_sha256": FREEZE_SHA256,
                "execution_manifest_sha256": execution_hash,
            }
            if track == "A":
                sidecar.update({"configuration": "G4", "seed": 101})
            else:
                sidecar.update({
                    "source_manifest_sha256": source_manifest_hash, "corpus": "B1",
                    "draw_id": 1,
                    "transformation_provenance": f"supplementary frozen prefix benchmark of B1_draw1.bin at n={n}",
                })
            sidecar_path = Path(str(corpus) + ".meta.json")
            if sidecar_path.exists():
                if json.loads(sidecar_path.read_text()) != sidecar:
                    raise RuntimeError(f"benchmark sidecar mismatch: {sidecar_path}")
            else:
                atomic_json(sidecar_path, sidecar)
            for k in KS:
                result = result_root / f"cost_{track}_n{n}_k{k}.json"
                store = store_root / f"cost_{track}_n{n}_k{k}.store"
                if result.exists():
                    value = json.loads(result.read_text())
                    if (value.get("status") == "complete" and value.get("N") == n and value.get("k_max") == k
                            and value.get("metadata", {}).get("execution_manifest_sha256") == execution_hash):
                        print(f"reuse {result}", flush=True)
                        continue
                    raise RuntimeError(f"invalid existing benchmark result: {result}")
                command = [str(scorer), "--corpus", str(corpus), "--output", str(result),
                           "--store", str(store), "--k-max", str(k), "--checkpoints", str(n),
                           "--cache-mib", "2048"]
                print("+", " ".join(command), flush=True)
                subprocess.run(command, check=True)
    print("Supplementary cost benchmark matrix complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
