# Rev B execution resume status

Snapshot time: 2026-09-16T22:19Z (UTC), during run wfr_10cda26f-205c-427f-a3b2-ed8d846e0e62.

## What this turn verified before touching anything

- cwd confirmed: `/home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/personal-workspaces/env_sveaeeem4z`.
- `REVB_FREEZE.json` sha256 `ec2a97849acc0d93c71d2f8af9744808950e748d6056d5e71bef764d3ae63036` matches every binding.
- `REVB_PROTOCOL.md` sha256 `9180c10578a1c2f15f96e97ff93893e5e4889dad417531d50b8bc97c81fd04b2` matches.
- The **current** frozen execution manifest is `REVB_EXECUTION_SUPPLEMENT_V3.json`
  (sha256 `892d30792592de296e8d33c68b8652f62fa2e742896f54c9f1d054f0fd5cf74a`), which supersedes
  V2 (`01ae4eb0...`, the one named in CORE_HANDOFF.md and the last independent audit).
  V3 additionally binds the Track B source manifest and authorizes Track B measurement, so the
  "Track B blocked on provenance" note from the earlier audit is resolved by V3, not by this turn.
- All 24 existing Track A surfaces (`revb_run/track_a/surfaces/*.json`) were individually re-verified
  against the **V3** execution-manifest hash (my first check used the stale V2 hash and incorrectly
  flagged all 24 as mismatched; re-checking against V3 confirms all 24 are schema/status/hash/checkpoint/N/K
  correct and none were touched or regenerated).
- Release binaries on disk match V3's `release_binary_sha256` exactly (`build/generate_corpus`,
  `build/kt_stream`, `build/core_tests`, `build/libblock01_kt.a`).
- Frozen scripts on disk match V3's `source_sha256` exactly: `scripts/run_track_a.py`,
  `scripts/run_track_b.py`, `scripts/analyze_revb.py`, `scripts/run_cost_benchmarks.py`,
  `scripts/run_separability.py`.
- All 25 Track B corpus files under
  `/home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/thread-storage/thr_363jypygh6/trackb_corpora/`
  pass `sha256sum -c SHA256SUMS.txt`, and `TRACK_B_SOURCE_MANIFEST.json` sha256 matches V3's bound
  `source_manifest.sha256` (`ffd70d8b0ba5777f216382db9cdd66908fb710a6ee87bb343050ab81ece816d1`).
- `A_G3_d4_s505`'s corpus + sidecar were valid (recomputed sha256 matches the sidecar's declared
  `corpus_sha256` and all V3/freeze/protocol bindings). Its leftover store
  (`revb_run/track_a/stores/A_G3_d4_s505.store`, 6.48 GB, mtime before the prior disconnect) was the
  crash artifact: per protocol, an interrupted store is `in_progress_invalid_on_crash` with no resume
  claim, so it was deleted before rescoring rather than reused.

## What changed

Added one new, non-frozen file: `scripts/resume_throttled_orchestrator.py`. It does not alter any
kernel, threshold, checkpoint grid, cache size, or execution order — it calls the exact same
`build/generate_corpus` / `build/kt_stream` commands the frozen launchers use, in the same frozen
order, and only adds:

- a resource gate before every generate+score pair (`nproc`, `/proc/loadavg` 1-minute value,
  `/proc/meminfo MemAvailable`), waiting 60 s and re-logging if load1 > cores or available < 2 GiB;
- an 8 s pause between finishing one surface and starting the next;
- deletion of a leftover store file before rescoring (never reuses a partial store);
- run-boundary reuse validation identical to `scripts/run_track_a.py` / `run_track_b.py` so a
  hash-matching completed surface is never regenerated.

Every resource pause is appended to `revb-resource-log.txt` in this directory with a timestamp and
the load/available-memory readings that triggered it.

## Current run state

Launched in persistent bb terminal `term_yvxkuqid35` (thread `thr_72jywcvgsq`) at 2026-09-16T22:10:46Z:

```
cd /home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/personal-workspaces/env_sveaeeem4z && \
python3 scripts/resume_throttled_orchestrator.py \
  --workspace . \
  --track-a-output-root revb_run/track_a \
  --track-b-corpus-root /home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/thread-storage/thr_363jypygh6/trackb_corpora \
  --track-b-output-root revb_run/track_b \
  --resource-log /home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/thread-storage/thr_363jypygh6/revb-resource-log.txt
```

It correctly skipped all 24 verified-complete Track A identities (items 1-24) and, at 22:10:46Z, began
item 25/90 (`A_G3_d4_s505`) after a passing resource check (load1=1.69, cores=8, available=13.4 GiB).
As of this snapshot (22:19Z, ~8.5 minutes into that run) `kt_stream` is alive, I/O-bound (state `D`),
RSS at the frozen 2 GiB cache ceiling, and its store has grown to 4.1 GB, consistent with the four
already-completed `G3(d=4)` runs (which finished between 1470 s and 2314 s wall time). This is expected,
ordinary behavior, not a hang.

This terminal is a persistent bb PTY: it keeps running independently of this reply and will continue
through the remaining Track A identities and then all 25 Track B identities, in frozen order, with the
resource gate re-checked before every item.

## Remaining scope (exact, in frozen order)

Track A (66 of 90 remaining), items 25-90 of `REVB_FREEZE.json["track_A"]["runs"]`:
`A_G3_d4_s505`, all of `G3(5)`, `G3(6)`, `G3(8)`, `G3(10)`, `G3(12)`, `G3(14)` (5 seeds each),
all of `G4` (5 seeds), then `G5(4)`, `G6(4)`, `G5(8)`, `G6(8)`, `G5(12)`, `G6(12)` (5 seeds each).

Track B (25 of 25 remaining, none started yet): `B1`..`B5` x draws 1-5, in that order.

## Real cost/resource evidence gathered so far (not extrapolated, not fabricated)

From the 24 already-complete, hash-verified Track A surfaces' persisted `metrics` at their final
checkpoint (n=2^23, k_max=16, alphabet=32, frozen 2 GiB cache):

| run family | wall_seconds range | process_cpu_seconds range | bytes_read range | bytes_written range | allocated_store_bytes range |
|---|---|---|---|---|---|
| G1 (lag-copy) | 610-1013 | 113-359 | ~119.2-119.7 GB | ~113.7-114.2 GB | ~6.32-6.32 GB |
| G2 | 771-962 | 65-71 | ~108.0-108.4 GB | ~107.7-108.1 GB | ~6.84 GB |
| G3(d=2) | 714-1652 | 94-123 | ~131.4-131.8 GB | ~112.9-113.2 GB | ~6.79 GB |
| G3(d=3) | 854-1168 | 91-105 | ~146.7-147.0 GB | ~131.2-131.3 GB | ~6.59 GB |
| G3(d=4) | 1470-2314 | 90-97 | ~163.8-164.0 GB | ~152.4-152.6 GB | ~6.54 GB |

Key honest finding: at n up to roughly 2×10^6, wall time tracks CPU time almost exactly (no I/O);
past that point the frozen 2 GiB cache is exhausted and wall time explodes relative to CPU time
(process_cpu_seconds stays in double digits to ~120 s, but wall_seconds reaches 600-2300+ s) because
each further checkpoint interval spends 85-95% of wall time in disk I/O wait (single-run example:
`A_G3_d4_s404` read 164.0 GB and wrote 152.6 GB total against an 8 MB corpus — a read amplification of
about 19,500x and write amplification about 18,200x relative to input size, from repeated page
eviction/reload under the fixed 2 GiB page-data cache once distinct order-16 contexts exceed cache
capacity). `G3(d)` for larger `d` produces still more distinct high-order contexts (agreement blocks of
length d+1), which is why `G3(d=4)` already needs 2.4-3.3x the wall time of `G1`/`G2` despite the same N,
k_max, alphabet, and cache. Higher `d` values (5,6,8,10,12,14) are expected to increase this further.

This is real Track-A/alphabet-32 evidence only. No Track-B/alphabet-256 corpus has been scored yet in
this environment; alphabet-256 records are 4160 bytes each (vs 576 bytes for alphabet-32) with fewer
records per page (15 vs 113), so the same 2 GiB cache holds a much smaller working set. The prior core
handoff's loose estimate of ~73.3 GB of allocated page payload for one Track-B run at 2^23 is still
unmeasured; this run will produce the first real Track-B disk/I-O numbers.

## 2^30 extrapolation (disk/I/O assumptions, explicitly conditional on the above, not yet validated at scale)

2^30 is 128x the current N=2^23. Two different regimes are visible in the real data and the honest
extrapolation must state both, rather than pick one and hide the other:

1. If the number of distinct high-order (k=16) contexts grows sub-linearly enough to keep fitting in the
   fixed 2 GiB cache even at N=2^30, wall time would scale close to linearly with N (as it does below
   ~2x10^6 symbols today), i.e. roughly 128x today's pre-spill per-symbol cost.
2. If distinct contexts continue to grow closer to linearly in N (plausible for these generators, since
   G1-G6 are designed to keep producing new order-16 histories), the *disk-bound* regime dominates
   almost the entire run, and total bytes moved scales at least with the *number of evictions*, which in
   the measured data already grows faster than N in the disk-bound region (e.g. G3(d=4)'s 2.57M
   evictions in the last 2^23-2^22=4,194,304-symbol interval alone). Naively scaling the already-measured
   164-192 GB of read+write traffic per 2^23-symbol run by 128x gives on the order of 2-2.5x10^13 bytes
   (~20-25 TB) of cumulative disk read+write traffic for one Track-A run at 2^30, even before accounting
   for the likely super-linear growth of eviction count with N. The final `allocated_store_bytes` at 2^23
   is only ~6.3-6.9 GB (because most pages are eventually reused/compacted), so *ephemeral peak disk
   space* would likely stay in the tens-of-GB range even at 2^30 for alphabet 32 — the blocker at 2^30 is
   I/O *volume/time* (potentially many hours to days per run at the current fixed 1-worker, 2 GiB-cache,
   64 KiB-page design), not disk *capacity*, for Track A. For Track B (alphabet 256, larger records,
   fewer records/page) both the I/O-time and the disk-capacity risk are larger and currently unmeasured;
   the first completed Track B run in the currently executing batch will give real numbers to replace
   this loose bound.

This section will be replaced with a fitted model (not this qualitative bound) once enough of the
remaining 66+25 runs (spanning more k, more distinct-context growth profiles, and the first Track B
alphabet-256 data) are actually measured, per the "never tune from results, only fit from real data"
convention — this bound itself was derived only from already-measured checkpoints, not from any
production run this turn triggered.

## Not done / explicitly deferred, not fabricated

- 66/90 Track A and 25/25 Track B production surfaces are not yet measured. They are running,
  unattended, in the persistent terminal above; this reply does not claim they are finished.
- The 10 strict predictions, 3 gates + conditional interpretation, Annex A aggregate diagnostics
  (increments, finite differences, ridge/saturation, means/sample-std across the 5 seeds), and the
  final fitted 2^30 cost model all require the full 90+25 grid and are intentionally not computed from
  a partial grid.
- Separability (`scripts/run_separability.py`) is gated on Correctness + Foundation passing over the
  full grid and has not been run.
- Injected ENOSPC/short-write fault-path tests remain unverified (unchanged from the prior audit).

## Resumable command if this terminal is lost again

```
cd /home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/personal-workspaces/env_sveaeeem4z && \
python3 scripts/resume_throttled_orchestrator.py \
  --workspace . \
  --track-a-output-root revb_run/track_a \
  --track-b-corpus-root /home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/thread-storage/thr_363jypygh6/trackb_corpora \
  --track-b-output-root revb_run/track_b \
  --resource-log /home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/thread-storage/thr_363jypygh6/revb-resource-log.txt
```

It is idempotent: rerunning it re-verifies every existing surface against the V3 execution-manifest
hash and the frozen checkpoint grid before skipping it, deletes any stale/partial store for the next
unfinished item, and resumes strictly in frozen order. It never touches a verified, hash-matching
completed surface.
