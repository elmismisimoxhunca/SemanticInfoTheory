#!/usr/bin/env python3
"""Start the non-frozen Rev B orchestrator independently of a BB terminal PTY.

The BB terminal remains the inspection surface, but the orchestrator is placed in
its own session with file-backed output so a host-daemon/PTY disconnect does not
kill an hours-long frozen scorer. This launcher does not alter scientific inputs,
commands, ordering, cache size, or validation rules.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def is_expected_orchestrator(command: list[str], workspace: Path) -> bool:
    if len(command) < 2:
        return False
    expected = (workspace / "scripts" / "resume_throttled_orchestrator.py").resolve()
    try:
        candidate = Path(command[1]).resolve()
    except (OSError, RuntimeError):
        return False
    return candidate == expected


def process_command(pid: int) -> list[str]:
    try:
        encoded = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return []
    return [part.decode("utf-8", "surrogateescape") for part in encoded.split(b"\0") if part]


def running_orchestrators(workspace: Path) -> list[int]:
    matches: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if is_expected_orchestrator(process_command(pid), workspace):
            matches.append(pid)
    return sorted(matches)


def atomic_write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=path.name + ".tmp.",
        dir=path.parent,
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(f"{pid}\n")
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


def workspace_path(workspace: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (workspace / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--track-a-output-root", type=Path, required=True)
    parser.add_argument("--track-b-corpus-root", type=Path, required=True)
    parser.add_argument("--track-b-output-root", type=Path, required=True)
    parser.add_argument("--resource-log", type=Path, required=True)
    parser.add_argument("--pid-file", type=Path, required=True)
    parser.add_argument("--console-log", type=Path, required=True)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    orchestrator = (workspace / "scripts" / "resume_throttled_orchestrator.py").resolve()
    if not orchestrator.is_file():
        raise RuntimeError(f"missing orchestrator: {orchestrator}")

    existing = running_orchestrators(workspace)
    if existing:
        raise RuntimeError(f"refusing duplicate Rev B orchestrator; running pids={existing}")

    pid_file = workspace_path(workspace, args.pid_file)
    console_log = workspace_path(workspace, args.console_log)
    console_log.parent.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        str(orchestrator),
        "--workspace", str(workspace),
        "--track-a-output-root", str(args.track_a_output_root),
        "--track-b-corpus-root", str(args.track_b_corpus_root),
        "--track-b-output-root", str(args.track_b_output_root),
        "--resource-log", str(args.resource_log),
    ]

    with console_log.open("ab", buffering=0) as output:
        process = subprocess.Popen(
            command,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

    time.sleep(0.5)
    return_code = process.poll()
    if return_code is not None:
        raise RuntimeError(
            f"detached orchestrator exited during startup with code {return_code}; inspect {console_log}"
        )

    atomic_write_pid(pid_file, process.pid)
    print(json.dumps({"pid": process.pid, "pid_file": str(pid_file), "console_log": str(console_log)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
