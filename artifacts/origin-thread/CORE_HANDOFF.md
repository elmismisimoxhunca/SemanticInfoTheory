# Block 01 Rev B core handoff

## Status

The existing compressed reversed-history trie was completed rather than replaced. The core now builds and passes deterministic exact-reference and forced-spill tests for both explicit alphabets. No production Track A or Track B corpus was generated or scored, and no availability surface was measured. The next workflow step is an independent audit before any full run.

Frozen implementation supplement:

- Current: `REVB_EXECUTION_SUPPLEMENT_V2.json`
- SHA256: `01ae4eb00783b257241982d1ddf2bbe0bf9adcefa92a55bd7c565bb901c56da4`
- Superseded immutable v1: `REVB_EXECUTION_SUPPLEMENT.json`, SHA256 `9931b24dbd408c7450a07596fefe6cbe9a71470b6d82af76522f0803067e88b7`
- Post-v1 fixture evidence: `REVB_FIXTURE_AUDIT.json`

V2 changes only pre-measurement launcher validation: it hashes the actual freeze file and rejects reuse bound to another execution manifest. Engine, generator, PRNG, release binaries, statistical definitions, and resource settings are unchanged. The supplements bind Rev B protocol/freeze, source, executables, compiler flags, platform/libm, result schema, and fixed one-worker/2 GiB-cache settings. Generator fixture draws occurred after v1 bound the unchanged generator/PRNG/binary. No fixture files were retained.

## Implemented files

- `include/block01/kt_engine.hpp`: public C++ API, result/checkpoint/Annex structures, metadata and internal test hooks.
- `src/kt_engine.cpp`: runtime sidecar validation and compile-time `AlphabetTraits<32>/<256>` dispatch; exact KT, external compressed trie, bounded CLOCK cache, checkpoints, same-pass SHA256, Annex instrumentation, and JSON output.
- `src/kt_stream.cpp`: atomic/fsynced scoring CLI.
- `src/generate_corpus.cpp`: frozen Track A G1/G2/G3/G4/G5/G6 generator using `design/prng_reference.hpp`; atomic corpus and sidecar publication.
- `block01.py`: public Python facade `availability(corpus_path,k_max,checkpoints)`.
- `scripts/run_track_a.py`: sequential frozen-order launcher for all 90 registered Track A run identities; not executed here.
- `tests/core_tests.cpp`: bounded independent per-order reference and forced-spill tests.

`DESIGN.md` was not rewritten. Track B source acquisition, extraction, normalization, draw selection, and transformation files are not owned or fabricated here.

## Build and verification

Release:

```bash
cd /home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/personal-workspaces/env_sveaeeem4z
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 2
ctest --test-dir build --output-on-failure
```

Observed: build passed; `core_tests` 1/1 passed.

ASan/UBSan:

```bash
cmake -S . -B build-sanitize \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' \
  -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined'
cmake --build build-sanitize -j 2
ASAN_OPTIONS=detect_leaks=1 ctest --test-dir build-sanitize --output-on-failure
```

Observed: 1/1 passed.

The tests cover:

- independent exact full-order KT scoring for S=32 and S=256, including startup and multiple checkpoints;
- bit-identical raw KT L versus the reference and between one-page and larger caches;
- forced dirty spills, many page IDs, bounded tombstone probing and fixed-index rebuilds;
- exact occupancy recurrence and visitation invariant `E_k=max(n-k,0)`;
- incremental declared conditional-ML reference versus direct fixture counts;
- 128-bit byte histories through depth 16, including keys differing above bit 64;
- every byte value 0..255, Track A rejection of byte 32, and missing sidecars;
- Track A predicted-symbol losses and attribution residuals;
- Track B ASCII-whitespace buckets and latest inclusive aligned prefix;
- deterministic global-bijection KT invariance fixtures;
- release CLI JSON and Python facade smoke checks.

Not completed as part of the focused suite: injected ENOSPC/short-write failures or reopening/resuming stores. The engine has explicit overflow, short-read, short-write, child-ID, offset-end, and metadata guards. Resume is deliberately unsupported.

## Mandatory corpus sidecar

The engine reads `str(corpus_path) + '.meta.json'` unless the internal C++/CLI metadata override is supplied. Alphabet is selected only from this validated sidecar, never from observed bytes, extension, UTF-8 decoding, or file name.

Common schema:

```json
{
  "schema": "block01-corpus-v1",
  "track": "A",
  "alphabet_size": 32,
  "expected_n": 8388608,
  "run_id": "A_G1_s101",
  "corpus_sha256": "<64 hex>",
  "protocol_sha256": "9180c10578a1c2f15f96e97ff93893e5e4889dad417531d50b8bc97c81fd04b2",
  "freeze_sha256": "ec2a97849acc0d93c71d2f8af9744808950e748d6056d5e71bef764d3ae63036",
  "execution_manifest_sha256": "01ae4eb00783b257241982d1ddf2bbe0bf9adcefa92a55bd7c565bb901c56da4",
  "configuration": "G1",
  "seed": 101
}
```

Track B uses `track:"B"`, `alphabet_size:256`, and additionally requires:

```json
{
  "source_manifest_sha256": "<64 hex>",
  "corpus": "B1",
  "draw_id": 1,
  "transformation_provenance": {"owner": "Track B frozen manifest"}
}
```

Track/alphabet mismatch, invalid/missing hashes, wrong frozen protocol/freeze hashes, missing track-specific fields, invalid A symbols, length mismatch, extra bytes, missing checkpoints, or corpus-digest mismatch are errors and cannot publish a successful result.

## Track A generator

One production corpus:

```bash
build/generate_corpus \
  --configuration 'G3(8)' \
  --seed 101 \
  --n 8388608 \
  --output /absolute/output/A_G3_d8_s101.bin \
  --execution-manifest-sha256 01ae4eb00783b257241982d1ddf2bbe0bf9adcefa92a55bd7c565bb901c56da4
```

Production mode accepts only registered seeds `[101,202,303,404,505]` and exactly `2^23` symbols. `--fixture` explicitly permits a non-production deterministic implementation fixture. The generator hashes bytes while writing, fsyncs and atomically publishes the corpus, then publishes its sidecar.

Frozen configurations accepted:

- `G1`, `G2`, `G4`
- `G3(2)`, `G3(3)`, `G3(4)`, `G3(5)`, `G3(6)`, `G3(8)`, `G3(10)`, `G3(12)`, `G3(14)`
- `G5(4)`, `G6(4)`, `G5(8)`, `G6(8)`, `G5(12)`, `G6(12)`

G5(4), G5(8), and G5(12) deliberately use the same lag-2 kernel. Each registered identity is independently generated by the launcher, and every G5 sidecar contains nonempty `duplicate_provenance`; these outputs are not presented as independent replications.

All 90 Track A run identities, frozen order, one worker:

```bash
python3 scripts/run_track_a.py \
  --workspace /home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/personal-workspaces/env_sveaeeem4z \
  --output-root /absolute/production-output \
  --execution-manifest-sha256 01ae4eb00783b257241982d1ddf2bbe0bf9adcefa92a55bd7c565bb901c56da4
```

This command was **not** run. It checks that the freeze contains 90 records and processes them sequentially in manifest order. A completed run-boundary result is reused only after explicit schema/run/freeze/N/K/checkpoint validation and is logged as reuse.

## Scoring CLI

Registered production scoring command:

```bash
build/kt_stream \
  --corpus /absolute/input/A_G3_d8_s101.bin \
  --output /absolute/results/A_G3_d8_s101.json \
  --store /absolute/scratch/A_G3_d8_s101.store \
  --k-max 16 \
  --checkpoints 4096,8192,16384,32768,65536,131072,262144,524288,1048576,2097152,4194304,8388608 \
  --cache-mib 2048
```

Default behavior removes the ephemeral exact spill store only after successful flush/finalization and before atomic result publication. The JSON retains exact logical node payload and allocated file-byte metrics. `--keep-store` explicitly retains the versioned tail store; its header labels it `complete_ephemeral_tail_only_no_resume`, because the fixed dense frontend is intentionally not persisted and no resume claim is made. Interrupted stores remain `in_progress_invalid_on_crash` and are invalid.

Small fixed cache sizes are available only for implementation tests through `--cache-pages`; production is frozen at 32,768 × 64 KiB = 2 GiB page data.

## Python API

```bash
export BLOCK01_KT_STREAM=/home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/personal-workspaces/env_sveaeeem4z/build/kt_stream
export PYTHONPATH=/home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/personal-workspaces/env_sveaeeem4z
python3 - <<'PY'
from block01 import availability
surface = availability(
    "/absolute/input/A_G3_d8_s101.bin",
    16,
    [2**power for power in range(12, 24)],
)
print(surface["schema"], surface["checkpoint_count"])
PY
```

Signature:

```python
availability(corpus_path, k_max, checkpoints) -> dict
```

The facade invokes the same release CLI with the frozen 2 GiB cache and returns the parsed complete result. It does not expose an alphabet argument or an estimator alternative.

## Result JSON schema

Top level (`block01-availability-surface-v1`):

```text
schema, status, corpus_path, N, alphabet_size, k_max,
surface_axes=["checkpoint","order"], storage_method, store_retained,
metadata, checkpoint_count, checkpoints[], metrics
```

`metadata` preserves the validated run/track/protocol/freeze/execution/source identities and both declared and computed corpus SHA256.

Each `checkpoints[j]` is after scoring/updating the nth symbol and contains:

```text
n
L[k], L_bits[k]
A[k], A_bits[k]
L_ML[k], L_ML_bits[k]
KT_minus_ML[k]
KT_minus_ML_per_symbol[k]
occupancy[k]
predicted_symbol_attribution (Track A only)
whitespace_attribution (Track B only)
metrics
```

All order arrays have length `k_max+1`. L/A/ML values are JSON binary64 decimals with round-trip precision; raw L/A/ML bit patterns are also persisted. `A[0]` is positive zero. Negative A is retained.

`occupancy[k]`:

```text
k, visits, distinct_contexts, singleton_contexts, contexts_total_lt5,
singleton_visitation_numerator, rare_visitation_numerator,
singleton_visitation_mass, rare_visitation_mass
```

Masses are JSON `null` with `mass_undefined_reason:"zero_visits"` when the denominator is zero. These are empirical visitation masses after n updates, not true generator probability mass. Startup contexts are excluded.

Track A `predicted_symbol_attribution`:

```text
counts[a]                                      length 32
L_order_major[k*32+a]                         length (k_max+1)*32
A_contribution_order_major[k*32+a]            length (k_max+1)*32
contribution_sum_residual[k]                  length k_max+1
g3_type_totals                                present for G3 configurations
```

Track B `whitespace_attribution`:

```text
bucket_names=[whitespace,token_first,token_continuation]
counts[b]                                     length 3
L_order_major[k*3+b]                          length (k_max+1)*3
A_contribution_order_major[k*3+b]             length (k_max+1)*3
contribution_sum_residual[k]                  length k_max+1
aligned_offset
aligned_L[k]
aligned_A[k]
```

`aligned_offset`/values are null when no ASCII whitespace byte in `{9,10,11,12,13,32}` has occurred. Otherwise the offset is the latest whitespace byte at or before n, inclusive. Models never reset at whitespace.

`metrics`, both cumulative at checkpoints and final:

```text
input_bytes, input_read_calls
nodes, leaves_created, divergence_splits, endpoint_splits
page_capacity, page_hits, page_misses, page_evictions
cache_index_rebuilds, page_reads, page_writes, dirty_writebacks
bytes_read, bytes_written
kt_log2_calls, annex_log2_calls
logical_store_bytes, allocated_store_bytes
dense_frontend_bytes, directory_bytes
fixed_cache_data_bytes, fixed_cache_metadata_bytes
peak_rss_kib
logical_scores, logical_updates
scores_by_depth[17], updates_by_depth[17]
wall_seconds, process_cpu_seconds
```

The ML reference is exactly the preregistered retrospective unsmoothed checkpoint functional, updated in input order through `g(T)-g(C_x)` with fixed uniform startup. `KT_minus_ML` is only descriptive reference-dependent redundancy, not uniquely identifiable pure learning cost.

The persisted checkpoint arrays are sufficient for later computation without rescoring of:

- per-run increments `A(k,n)-A(k-1,n)`;
- linear-n adjacent-checkpoint finite differences;
- first increment below 0.01 ridge/censor category;
- five-run means/sample standard deviations;
- ten predictions and three gates.

Those aggregate/evaluator computations are outside this core handoff and were not run.

## Engine/storage details frozen by implementation

- S=32: 5-bit digits, dense depths 0..3, depth-4 directory, 576-byte records, 113 records/page.
- S=256: 8-bit digits, dense depths 0..1, depth-2 directory, 4,160-byte records, 15 records/page.
- Full byte order-16 history returns the natural full unsigned 128-bit value; no shift by 128 is formed.
- Cache lookup/insert/erase probes are bounded by fixed index capacity. Tombstones trigger a fixed-memory resident-index rebuild at one-quarter index capacity.
- Existing allocated pages require complete 64 KiB reads; short reads fail. Page-end offsets, IDs, sizes and counters are checked.
- One log probability can be reused across a compressed edge, but every logical order receives one separately ordered binary64 addition and one occupancy/ML logical update.
- Corpus SHA256 and input bytes share the scoring read pass.

## Honest remaining scope and resource blocks

- **Production scope:** 0/90 Track A surfaces and 0/25 Track B surfaces. No prediction or gate has been evaluated.
- **Track B:** core byte scoring is ready, but exact public source/provenance, ingestion, disjoint draws, CHILDES adequacy, and B1/B4/B5 transformations remain external blockers owned by the Track B role.
- **Audit:** independent source/result-schema audit is still required before using the frozen launcher.
- **Disk/time:** exact dense B records are 4,160 bytes. The loose bound in `REVB_DELTA.md` remains about 73.3 GB allocated page payload for one B run at `2^23`, and substantially larger at `2^30`; actual state may be lower but has not been measured. Default ephemeral stores limit retained disk but do not reduce peak per-run storage or I/O.
- **RAM:** production uses one fixed 2 GiB page-data mapping plus fixed cache index/CLOCK metadata, dense frontend/directory, 64 KiB input buffer, fixed route/Annex arrays, executable/runtime, and OS page cache. Result metrics itemize engine allocations and peak RSS; no full production evidence exists yet.
- **Separability:** the engine preserves the theorem that symmetric KT is invariant under every global alphabet bijection. It cannot create the requested across-class drop; production gated tests must report the contradiction rather than alter the estimator or map.

No deployments, restarts, agents, Track B source files, production corpora, or production measurements were performed by this role.
