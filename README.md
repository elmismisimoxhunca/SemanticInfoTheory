# SemanticInfoTheory

## Block 01 — The Availability Surface

This repository contains a preregistered experiment for measuring where predictive information becomes available in a symbol sequence as two reader budgets increase:

\[
A(k,n)=\frac{L_0(n)-L_k(n)}{n},
\]

where `k` is context length, `n` is sample exposure, and each reader is a fixed online Krichevsky–Trofimov predictor. The experiment tests whether the resulting surface is determined by corpus structure or mainly by the reader.

## Scientific status

The experiment is **incomplete**. No Go/No-Go verdict has been reached.

- Track A: **27/90** frozen synthetic surfaces complete.
- Track B: **0/25** natural-corpus surfaces complete; all 25 input draws are locally preserved and hash-verified.
- Independent implementation audit: **219/219 checks passed**, with no core-engine bug found.
- Partial G3 results expose the preregistered phase-confound risk: the largest measured increment occurs at `k=1`, not consistently at the planted distance. This is a frozen experimental result, not permission to redesign the generator mid-run.

See `MIGRATION.md`, `REVB_PROTOCOL.md`, `REVB_FREEZE.json`, and `REVB_AUDIT.md` for the exact state and integrity boundaries.

## Repository layout

- `src/`, `include/`, `tests/` — exact C++ KT engine, CLI, generators, and tests.
- `block01.py` — Python availability entry point.
- `scripts/` — frozen execution, analysis, cost, separability, and throttled-resume scripts.
- `audit/`, `design/` — independent references, audit scripts, and design evidence.
- `trackb/` — deterministic Track B acquisition and transformation code.
- `revb_run/track_a/surfaces/` — the 27 completed production surfaces.
- `artifacts/` — published audit evidence, status logs, provenance, and handoff material.
- `data/` — machine-local corpora; intentionally ignored by Git.

## Build and focused verification

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j2
ctest --test-dir build --output-on-failure
python3 audit/run_engine_audit.py
python3 audit/run_generator_audit.py
python3 audit/run_trackb_audit.py
```

The audit commands expect the local Track B corpus snapshot described in `data/README.md`.

## Resume the frozen run

Run exactly one scoring pipeline at a time:

```bash
python3 scripts/resume_throttled_orchestrator.py \
  --workspace . \
  --track-a-output-root revb_run/track_a \
  --track-b-corpus-root data/trackb_corpora \
  --track-b-output-root revb_run/track_b \
  --resource-log revb_run/reports/revb-resource-log.txt
```

The orchestrator validates and reuses complete surfaces, deletes stale per-item stores, and resumes in frozen order. Long execution should run in a persistent BB terminal.

## Data policy

Raw/generated corpora and multi-gigabyte exact-count stores are not committed. They are machine-local because they are reproducible or redistribution-sensitive, and because stores are disposable execution state. Hashes, manifests, source provenance, sidecars, completed surfaces, and all analysis code are committed.

No cross-track numerical comparison is valid: Track A uses alphabet 32 and Track B uses byte alphabet 256.
