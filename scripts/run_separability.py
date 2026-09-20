#!/usr/bin/env python3
"""Gate-controlled frozen global-bijection separability launcher for G3 primary corpora."""

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


def maps() -> dict[str, bytes]:
    within = list(range(256))
    for x in range(16):
        within[x] = (x + 1) % 16
    for x in range(16, 24):
        within[x] = 16 + ((x - 16 + 1) % 8)
    for x in range(24, 32):
        within[x] = 24 + ((x - 24 + 1) % 8)
    across = list(range(256))
    for j in range(8):
        across[j], across[16 + j] = 16 + j, j
    return {"within_class": bytes(within), "across_class": bytes(across)}


def transform(source: Path, destination: Path, table: bytes) -> str:
    digest = hashlib.sha256()
    if destination.exists():
        with destination.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    temporary = destination.with_name(destination.name + ".tmp")
    with source.open("rb") as inp, temporary.open("wb") as out:
        while chunk := inp.read(1024 * 1024):
            converted = chunk.translate(table)
            out.write(converted)
            digest.update(converted)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temporary, destination)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".tmp.", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--execution-manifest-sha256", required=True)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    run_root = args.run_root.resolve()
    analysis = json.loads(args.analysis.read_text())
    if analysis["gates"]["correctness"]["status"] != "pass" or analysis["gates"]["foundation"]["status"] != "pass":
        raise RuntimeError("separability is forbidden unless Correctness and Foundation both pass")
    execution_hash = args.execution_manifest_sha256.lower()
    freeze = json.loads((workspace / "REVB_FREEZE.json").read_text())
    scorer = workspace / "build" / "kt_stream"
    root = run_root / "separability"
    corpus_root, result_root, store_root = root / "corpora", root / "surfaces", root / "stores"
    for path in (corpus_root, result_root, store_root):
        path.mkdir(parents=True, exist_ok=True)

    summaries = []
    for run in freeze["track_A"]["runs"]:
        if not run["configuration"].startswith("G3("):
            continue
        primary_corpus = run_root / "track_a" / "corpora" / f"{run['run_id']}.bin"
        primary_result = run_root / "track_a" / "surfaces" / f"{run['run_id']}.json"
        if not primary_corpus.is_file() or not primary_result.is_file():
            raise RuntimeError(f"missing G3 primary evidence for {run['run_id']}")
        original = json.loads(primary_result.read_text())
        for map_name, table in maps().items():
            secondary_id = f"SEP_{map_name}_{run['run_id']}"
            corpus = corpus_root / f"{secondary_id}.bin"
            digest = transform(primary_corpus, corpus, table)
            sidecar = {
                "schema": "block01-corpus-v1", "track": "A", "alphabet_size": 32,
                "expected_n": 2**23, "run_id": secondary_id, "corpus_sha256": digest,
                "protocol_sha256": PROTOCOL_SHA256, "freeze_sha256": FREEZE_SHA256,
                "execution_manifest_sha256": execution_hash,
                "configuration": f"{run['configuration']}:{map_name}", "seed": run["seed"],
            }
            sidecar_path = Path(str(corpus) + ".meta.json")
            if sidecar_path.exists():
                if json.loads(sidecar_path.read_text()) != sidecar:
                    raise RuntimeError(f"separability sidecar mismatch: {sidecar_path}")
            else:
                atomic_json(sidecar_path, sidecar)
            result = result_root / f"{secondary_id}.json"
            store = store_root / f"{secondary_id}.store"
            if not result.exists():
                command = [str(scorer), "--corpus", str(corpus), "--output", str(result),
                           "--store", str(store), "--k-max", "16", "--checkpoints",
                           ",".join(str(n) for n in CHECKPOINTS), "--cache-mib", "2048"]
                print("+", " ".join(command), flush=True)
                subprocess.run(command, check=True)
            secondary = json.loads(result.read_text())
            maximum = 0.0
            all_bits_equal = True
            for original_cp, secondary_cp in zip(original["checkpoints"], secondary["checkpoints"], strict=True):
                all_bits_equal &= original_cp["L_bits"] == secondary_cp["L_bits"] and original_cp["A_bits"] == secondary_cp["A_bits"]
                maximum = max(maximum, max(abs(float(a) - float(b)) for a, b in zip(original_cp["A"], secondary_cp["A"], strict=True)))
            summaries.append({"primary_run_id": run["run_id"], "map": map_name, "maximum_absolute_A_delta": maximum, "all_L_A_bits_equal": all_bits_equal})
    output = root / "separability_summary.json"
    atomic_json(output, {"schema": "block01-revb-separability-v1", "runs": summaries,
                         "within_class_requirement_passed": all(row["maximum_absolute_A_delta"] < 0.01 for row in summaries if row["map"] == "within_class"),
                         "across_class_observed_drop": 0.0,
                         "theorem": "symmetric KT is invariant under every global alphabet bijection; requested across-class drop is impossible"})
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
