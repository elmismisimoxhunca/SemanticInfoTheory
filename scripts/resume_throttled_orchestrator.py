#!/usr/bin/env python3
"""Resource-throttled resume driver for the frozen Track A / Track B launchers.

Not a frozen protocol/kernel/threshold file. It only adds per-run resource
gating and inter-run pacing around scripts/run_track_a.py and
scripts/run_track_b.py's exact same commands; it never alters the generator,
scorer, kernels, checkpoints, cache size, or execution order they use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

EXECUTION_MANIFEST_SHA256 = "892d30792592de296e8d33c68b8652f62fa2e742896f54c9f1d054f0fd5cf74a"
PROTOCOL_SHA256 = "9180c10578a1c2f15f96e97ff93893e5e4889dad417531d50b8bc97c81fd04b2"
FREEZE_SHA256 = "ec2a97849acc0d93c71d2f8af9744808950e748d6056d5e71bef764d3ae63036"
CHECKPOINTS = [2**power for power in range(12, 24)]
GIB = 1024**3
TRACK_A_MIN_FREE_BYTES = 32 * GIB
TRACK_B_MIN_FREE_BYTES = 128 * GIB


def log_line(log_path: Path, message: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"{stamp} {message}\n"
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(line)
    print(line, end="", flush=True)


def read_meminfo_available_mib() -> float:
    with open("/proc/meminfo", "r", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("MemAvailable:"):
                kib = int(line.split()[1])
                return kib / 1024.0
    raise RuntimeError("MemAvailable not found in /proc/meminfo")


def read_load1() -> float:
    with open("/proc/loadavg", "r", encoding="utf-8") as stream:
        return float(stream.read().split()[0])


def nproc() -> int:
    return os.cpu_count() or 1


def resources_available(
    *,
    load1: float,
    cores: int,
    available_mib: float,
    free_bytes: int,
    minimum_free_bytes: int,
) -> bool:
    return load1 <= cores and available_mib >= 2048.0 and free_bytes >= minimum_free_bytes


def wait_for_resources(
    log_path: Path,
    item_label: str,
    disk_path: Path,
    minimum_free_bytes: int,
) -> None:
    cores = nproc()
    while True:
        load1 = read_load1()
        available_mib = read_meminfo_available_mib()
        free_bytes = shutil.disk_usage(disk_path).free
        if resources_available(
            load1=load1,
            cores=cores,
            available_mib=available_mib,
            free_bytes=free_bytes,
            minimum_free_bytes=minimum_free_bytes,
        ):
            log_line(
                log_path,
                f"resource_check_ok item={item_label} load1={load1:.2f} cores={cores} "
                f"available_mib={available_mib:.0f} free_disk_gib={free_bytes / GIB:.1f} "
                f"required_free_disk_gib={minimum_free_bytes / GIB:.1f}",
            )
            return
        log_line(
            log_path,
            f"resource_pause item={item_label} load1={load1:.2f} cores={cores} "
            f"available_mib={available_mib:.0f} free_disk_gib={free_bytes / GIB:.1f} "
            f"required_free_disk_gib={minimum_free_bytes / GIB:.1f} action=sleep_60s",
        )
        time.sleep(60)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def valid_completed_surface_a(path: Path, run_id: str) -> bool:
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
        and result.get("metadata", {}).get("execution_manifest_sha256") == EXECUTION_MANIFEST_SHA256
        and result.get("checkpoint_count") == 12
        and [c.get("n") for c in result.get("checkpoints", [])] == CHECKPOINTS
        and result.get("N") == 2**23
        and result.get("alphabet_size") == 32
        and result.get("k_max") == 16
    )


def valid_existing_corpus_a(corpus: Path, run: dict) -> bool:
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
        and metadata.get("freeze_sha256") == FREEZE_SHA256
        and metadata.get("execution_manifest_sha256") == EXECUTION_MANIFEST_SHA256
        and metadata.get("corpus_sha256") == sha256_file(corpus)
    )


def checked_run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def finalize_completed_run(
    *,
    surface: Path,
    store: Path,
    run_id: str,
    item_label: str,
    validator: Callable[[Path, str], bool],
    log_path: Path,
) -> None:
    if not validator(surface, run_id):
        raise RuntimeError(f"completed surface validation failed for {run_id}; preserving scratch store")
    if not store.exists():
        return
    store_bytes = store.stat().st_size
    store.unlink()
    free_bytes = shutil.disk_usage(store.parent).free
    log_line(
        log_path,
        f"store_cleanup item={item_label} deleted_bytes={store_bytes} "
        f"free_disk_gib={free_bytes / GIB:.1f}",
    )


def run_track_a(workspace: Path, output_root: Path, log_path: Path) -> None:
    freeze = json.loads((workspace / "REVB_FREEZE.json").read_text(encoding="utf-8"))
    runs = freeze["track_A"]["runs"]
    if len(runs) != 90:
        raise RuntimeError(f"expected 90 frozen Track A runs, found {len(runs)}")

    generator = workspace / "build" / "generate_corpus"
    scorer = workspace / "build" / "kt_stream"
    corpus_dir = output_root / "corpora"
    surface_dir = output_root / "surfaces"
    store_dir = output_root / "stores"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    surface_dir.mkdir(parents=True, exist_ok=True)
    store_dir.mkdir(parents=True, exist_ok=True)

    for ordinal, run in enumerate(runs, start=1):
        run_id = run["run_id"]
        corpus = corpus_dir / f"{run_id}.bin"
        surface = surface_dir / f"{run_id}.json"
        store = store_dir / f"{run_id}.store"
        print(f"[A {ordinal:02d}/90] {run_id}", flush=True)
        if valid_completed_surface_a(surface, run_id):
            finalize_completed_run(
                surface=surface,
                store=store,
                run_id=run_id,
                item_label=f"track_a:{run_id}",
                validator=valid_completed_surface_a,
                log_path=log_path,
            )
            print(f"  explicit run-boundary reuse: verified completed {surface}", flush=True)
            continue

        wait_for_resources(
            log_path,
            f"track_a:{run_id}",
            store_dir,
            TRACK_A_MIN_FREE_BYTES,
        )

        if not corpus.is_file() or not Path(str(corpus) + ".meta.json").is_file():
            if corpus.exists() or Path(str(corpus) + ".meta.json").exists():
                raise RuntimeError(f"incomplete pre-existing corpus pair for {run_id}")
            checked_run([
                str(generator),
                "--configuration", run["configuration"],
                "--seed", str(run["seed"]),
                "--n", str(run["n"]),
                "--output", str(corpus),
                "--execution-manifest-sha256", EXECUTION_MANIFEST_SHA256,
            ])
        elif not valid_existing_corpus_a(corpus, run):
            raise RuntimeError(f"pre-existing corpus metadata mismatch for {run_id}")

        if store.exists():
            store.unlink()

        checked_run([
            str(scorer),
            "--corpus", str(corpus),
            "--output", str(surface),
            "--store", str(store),
            "--k-max", str(run["k_max"]),
            "--checkpoints", ",".join(str(v) for v in run["checkpoints"]),
            "--cache-mib", "2048",
        ])
        finalize_completed_run(
            surface=surface,
            store=store,
            run_id=run_id,
            item_label=f"track_a:{run_id}",
            validator=valid_completed_surface_a,
            log_path=log_path,
        )
        log_line(log_path, f"completed item=track_a:{run_id}")
        time.sleep(8)

    print("Track A: all 90 registered run identities complete.")


def expected_provenance(corpus: str, draw: int) -> str:
    if corpus in {"B1", "B2", "B3"}:
        return "frozen deterministic consecutive disjoint slice; exact policy in TRACK_B_SOURCE_MANIFEST.json"
    if corpus == "B4":
        return f"controlled transform of B1_draw{draw}.bin; frozen sentence-unit shuffle seed {600 + draw}; prefix/suffix fixed"
    return f"controlled transform of B1_draw{draw}.bin; frozen within-unit word shuffle seed {700 + draw}; whitespace tokens fixed"


def atomic_json(path: Path, value: dict) -> None:
    import tempfile
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


def validate_surface_b(path: Path, run_id: str) -> bool:
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
        and result.get("metadata", {}).get("execution_manifest_sha256") == EXECUTION_MANIFEST_SHA256
        and result.get("checkpoint_count") == len(CHECKPOINTS)
        and [c.get("n") for c in result.get("checkpoints", [])] == CHECKPOINTS
        and result.get("N") == 2**23
        and result.get("alphabet_size") == 256
        and result.get("k_max") == 16
    )


def run_track_b(workspace: Path, corpus_root: Path, output_root: Path, log_path: Path) -> None:
    source_manifest_path = workspace / "TRACK_B_SOURCE_MANIFEST.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest_sha256 = sha256_file(source_manifest_path)
    corpus_hashes = source_manifest["corpus_hashes"]
    scorer = workspace / "build" / "kt_stream"
    surface_dir = output_root / "surfaces"
    store_dir = output_root / "stores"
    surface_dir.mkdir(parents=True, exist_ok=True)
    store_dir.mkdir(parents=True, exist_ok=True)

    ordinal = 0
    for corpus_name in ["B1", "B2", "B3", "B4", "B5"]:
        for draw in range(1, 6):
            ordinal += 1
            filename = f"{corpus_name}_draw{draw}.bin"
            corpus_path = corpus_root / filename
            run_id = f"B_{corpus_name}_draw{draw}"
            result_path = surface_dir / f"{run_id}.json"
            store_path = store_dir / f"{run_id}.store"
            print(f"[B {ordinal:02d}/25] {run_id}", flush=True)
            if validate_surface_b(result_path, run_id):
                finalize_completed_run(
                    surface=result_path,
                    store=store_path,
                    run_id=run_id,
                    item_label=f"track_b:{run_id}",
                    validator=validate_surface_b,
                    log_path=log_path,
                )
                print(f"  explicit run-boundary reuse: verified completed {result_path}", flush=True)
                continue

            wait_for_resources(
                log_path,
                f"track_b:{run_id}",
                store_dir,
                TRACK_B_MIN_FREE_BYTES,
            )

            if not corpus_path.is_file() or corpus_path.stat().st_size != 2**23:
                raise RuntimeError(f"missing or wrong-length Track B corpus: {corpus_path}")
            declared_hash = corpus_hashes.get(filename)
            if not isinstance(declared_hash, str) or len(declared_hash) != 64:
                raise RuntimeError(f"missing frozen corpus hash for {filename}")
            if sha256_file(corpus_path) != declared_hash:
                raise RuntimeError(f"corpus hash mismatch for {filename}")

            sidecar_path = Path(str(corpus_path) + ".meta.json")
            sidecar = {
                "schema": "block01-corpus-v1",
                "track": "B",
                "alphabet_size": 256,
                "expected_n": 2**23,
                "run_id": run_id,
                "corpus_sha256": declared_hash,
                "protocol_sha256": PROTOCOL_SHA256,
                "freeze_sha256": FREEZE_SHA256,
                "execution_manifest_sha256": EXECUTION_MANIFEST_SHA256,
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

            if store_path.exists():
                store_path.unlink()

            checked_run([
                str(scorer),
                "--corpus", str(corpus_path),
                "--output", str(result_path),
                "--store", str(store_path),
                "--k-max", "16",
                "--checkpoints", ",".join(str(v) for v in CHECKPOINTS),
                "--cache-mib", "2048",
            ])
            finalize_completed_run(
                surface=result_path,
                store=store_path,
                run_id=run_id,
                item_label=f"track_b:{run_id}",
                validator=validate_surface_b,
                log_path=log_path,
            )
            log_line(log_path, f"completed item=track_b:{run_id}")
            time.sleep(8)

    print("Track B: all 25 registered run identities complete.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--track-a-output-root", type=Path, required=True)
    parser.add_argument("--track-b-corpus-root", type=Path, required=True)
    parser.add_argument("--track-b-output-root", type=Path, required=True)
    parser.add_argument("--resource-log", type=Path, required=True)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    actual_freeze_sha256 = sha256_file(workspace / "REVB_FREEZE.json")
    if actual_freeze_sha256 != FREEZE_SHA256:
        raise RuntimeError("REVB_FREEZE.json hash mismatch")
    actual_supplement_sha256 = sha256_file(workspace / "REVB_EXECUTION_SUPPLEMENT_V3.json")
    if actual_supplement_sha256 != EXECUTION_MANIFEST_SHA256:
        raise RuntimeError("REVB_EXECUTION_SUPPLEMENT_V3.json hash mismatch")

    args.resource_log.parent.mkdir(parents=True, exist_ok=True)
    log_line(args.resource_log, "orchestrator_start")

    run_track_a(workspace, args.track_a_output_root, args.resource_log)
    run_track_b(workspace, args.track_b_corpus_root, args.track_b_output_root, args.resource_log)

    log_line(args.resource_log, "orchestrator_complete")
    print("RESUME_ORCHESTRATOR_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
