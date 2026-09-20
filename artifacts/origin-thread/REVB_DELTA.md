# Rev B minimal engine delta and implementation handoff

This is an additive implementation map for `DESIGN.md`, not a replacement architecture. Read `REVB_PROTOCOL.md` and `REVB_FREEZE.json` for operative statistics; Rev A N, six-generator scope, old API, and old Annex scope warning are superseded. This role inspected the partial C++ sources, PRNG, existing analytical/probe evidence, and CMake declarations. It did not build/run an engine, draw PRNG samples, generate/read experimental corpora, spawn agents, or measure A.

## 1. Actual starting state

- `include/block01/kt_engine.hpp`: alphabet constant 32, maximum order 16, 64 KiB pages/input, 576-byte fixed node records, 113 records/page; final-only result/API; `History80` already uses `unsigned __int128`.
- `src/kt_engine.cpp`: real compressed reversed-history tail, fixed anonymous page-cache allocation (not mmap of a growing file), exact-ID cache index, explicit pread/pwrite, copied histograms on splitting, full-order startup separation, ordered double scores. Reuse these. The prototype currently uses **dense fixed node histograms and children**, not DESIGN.md's proposed sparse slab classes. Do not claim sparse storage exists.
- Hard-coded alphabet affects digit width, history masks, validation, KT denominator/startup, node serialization offsets, dense frontend offsets/size, depth-4 directory, minimum tail depth, and route capacity. Merely changing `kAlphabetSize` to 256 is wrong.
- CMake names `src/kt_stream.cpp`, `src/generate_corpus.cpp`, and `tests/core_tests.cpp`; those files were absent at this inspection. No existing complete build/test evidence or measured bounded-RAM engine is claimed.
- `design/AUDIT_STATUS.json` reports analytical checks and a storage-only probe, zero generated corpora and zero production curves. The retained `reva-implementation-chronology.txt` in the artifact directory shows partial source work followed by the stop-before-Rev-A-execution instruction; `reva-worker-state.json` records the implementation worker idle with zero active background agents. Workspace inspection found the partial engine and design artifacts, not production outputs. These retained records support the supplied no-Rev-A-production history; they are not a universal audit of every host/session log.

## 2. Specialize the existing engine for S=32 or 256

Use one implementation with compile-time traits `AlphabetTraits<32>` / `<256>` and runtime dispatch **only from the validated mandatory corpus sidecar**. Keep the public signature without an alphabet argument; the internal options/result must record S and sidecar provenance. No observed-symbol inference. A template specialization keeps `std::array` sizes and serialized layouts compile-time while preserving common algorithms.

| Property | Track A | Track B |
|---|---:|---:|
| Alphabet S; bits/digit | 32; 5 | 256; 8 |
| Maximum packed history | 80 bits | 128 bits |
| Dense maximum depth D (when K permits) | 3 | 1 |
| Tail minimum/directory depth D+1 | 4 | 2 |
| Dense rows at full K | 33,825 | 257 |
| Dense bytes: rows × (S+1) × 8 | 8,929,800 | 528,392 |
| Directory slots | 32^4=1,048,576 | 256^2=65,536 |
| Directory bytes | 8,388,608 | 524,288 |
| Fixed serialized node bytes | 576 (existing) | 4,160 |
| Records/64 KiB page | 113 | 15 |
| Empty-row/startup loss; half-count denominator offset | 5; 16 | 8; 128 |

B uses dense depths 0..1 deliberately: blindly allocating all 256^3 dense context rows with 256 counters would consume tens of GiB. A B depth-2 dense frontend would already cost roughly 129 MiB; the selected depth-1 frontend and depth-2 directory total only 1,052,680 bytes. No broad architecture rewrite is needed. With K<D, allocate only depths 0..K and no tail/directory; calculate offsets with geometric sums over S, not the switch `[0,1,33,1057]`.

Rename the generic history type to `History128` (an alias may ease transition). Keep A's 5-bit packing and B's 8-bit packing; low digit is most recent. For B, append is unsigned-128 `(history<<8)|symbol`, natural modulo 2^128. **Never form `1<<128` or shift by 128.** `prefix(0)=0`; `prefix(16)` returns full B history; other B prefixes mask `(History128{1}<<(8*depth))-1`. A keeps its safe 80-bit mask. Digit shifts go only through 120 for B. Serialize both full uint64 limbs little-endian; no high-16-bit-only shortcuts. Validate the key is canonical for its stored depth, depths fall in `[D+1,K]`, and parent/child prefix/degree/terminal relationships remain valid. Distinct contexts differing only in the high bits must remain distinct.

Parameterize all tail entry points, directory lookup depth, parent starting depth, split minimum, route collection, decoder validation, and caller available-depth checks by D. Replace `array<RouteEntry,13>` with fixed `array<RouteEntry,17>` (or compile-time K-D capacity); no n-dependent allocation. K<=D must not require a disk path. Startup still updates a genuine depth only once.

## 3. Reuse exact disk state; disclose the dense-node cost

Keep append-only fixed node records and the bounded CLOCK cache for the minimal implementation. A header offsets remain: magic at 0, depth at 4, flags at 5, two little-endian key limbs at 8 and 16, total at 24, counts at 32, children at `32+8*S`, then zero padding to a 64-byte multiple. B needs `align64(32+16*256)=4160` bytes, **not** 576 or 4096. Recompute page packing statically and assert records fit without crossing pages. Use a new versioned store magic/metadata containing S, digit width, D, K, record/page size, run/freeze identity and invalid-on-crash status; never interpret historical A records as B. A fresh store per run, no silent format migration.

Node IDs, uint64 counts, child references, allocator position, and exact two-limb keys stay lossless. All growing nodes live on disk; fixed dense frontend/directory arrays are the only non-cache count state. Persist fixed frontend/directory and allocator metadata at successful finalization if retaining a supposedly complete count store; the current tail-only file is not by itself a restorable whole model. Do not claim resume support; interrupted stores are invalid. Results may be published only after explicit successful flush/fsync, not a destructor that swallows errors.

At most about `2*(N+K)` tail nodes yields a loose dense live-record bound of `2*(N+K)*record_bytes`, before fixed arrays/page slack. B is approximately 69.8 GB live payload at N=2^23, approximately 73.3 GB with 15-record page packing, and approximately 8.93 TB live payload at N=2^30. These are deliberately loose **bounds**, not measured corpus forecasts or guaranteed feasibility. A live bound is about 9.66 GB at 2^23. Twenty-five B stores at a loose per-store bound plainly can exceed historical free disk; retention must be explicit. Sparsity/path compression can reduce actual node counts, not the dense record width. Do not present DESIGN.md's sparse 64-byte singleton estimate as this engine's footprint.

A fixed 2 GiB cache is 32,768 × 64 KiB frames; its fixed hash/clock/page-ID metadata, frontends, input buffers, route/node scratch, and fixed Annex arrays are additional. Anonymous mmap of **this fixed cache** is permissible. Buffered I/O may occupy OS page cache separately; report host/RSS/cache accounting honestly. No growing RAM row map, per-node wrapper vector, full-store mmap, approximate count, eviction loss, or hidden max-N capacity fallback. ENOSPC and representational overflow are explicit resource errors. Sparse slab adaptation remains a possible future preregistered engineering revision, not a required wholesale rewrite or an option selected after comparing measured surfaces.

### Existing correctness hazards to fix before forced-spill tests

1. Cache `find`, `insert`, and `erase` currently probe forever until an empty bucket. Repeated evictions leave tombstones; eventually every bucket can be live/tombstone and an absent lookup can hang despite low live occupancy. Bound probing by the fixed table capacity, reuse first tombstone even after a full cycle, and rebuild the existing fixed index from resident page IDs when tombstones reach one quarter of index capacity. Rebuild without growing memory. Test many more unique page IDs than index slots under a one/few-page cache.
2. Short pread of an already allocated page must fail rather than quietly zero-fill corrupt/truncated existing state. Distinguish genuinely new pages from expected persisted bytes; handle EINTR but require expected bytes. Check child/node ID range and reserved page-ID sentinel collisions.
3. Check **end** file offsets, not only starting page multiplication (`offset+page_bytes`), next-ID arithmetic, logical-store-byte multiplication, cache-index doubling, and size_t conversions. Preserve loud counter overflow checks.
4. Compare full-order counts before updating; copies on divergence must not alias mutable descendants. Copying `Node` by value is currently the right simple behavior. No page pointer may survive a later cache access that can evict it.

## 4. Twelve checkpoints in the same pass

Extend `EngineOptions` with validated checkpoints and sidecar-selected traits, result with 12 checkpoint records `[n][k]`, provenance and completion/error status. Keep only fixed-length accumulators plus the requested fixed production grid; never retain input symbols. In the inner loop, after all scores/updates/history advance and incrementing n, snapshot when n equals the next requested checkpoint. No estimator restart, replay, independent per-checkpoint stores, or reordering L additions. Hash bytes from the same input buffer and verify length/digest at EOF before complete publication. Compute raw A from saved cumulative L. Preserve 17-digit values and double bits, constants/seeds/hashes, and checkpoint resource counters. A checkpoint timestamp does not certify a complete corpus.

Track B history is byte history across UTF-8 multibyte sequences and all extraction/shuffle boundaries, without decoding or reset. Track A accepts NUL and 31 but rejects 32; B accepts all 256 byte values. Sidecar mismatch is an error even when every observed byte would fit both alphabets.

## 5. Annex can be added with fixed RAM and no count-store scans

Reuse each represented row's **pre-update** T and C_x from scoring. Run per-depth Annex updates separately across each edge's depth interval so compressed representation does not undercount logical contexts. All counters/arrays below are bounded by K, S, and the 12 checkpoints, not n.

- **Occupancy:** for each genuine full-order event, D increases iff T=0. Singleton-context count change is `1[T+1=1]-1[T=1]`. Rare-context count change is `1[1<=T+1<5]-1[1<=T<5]`. Visitation numerators change by `(T+1)*1[T+1=1]-T*1[T=1]` and `(T+1)*1[1<=T+1<5]-T*1[1<=T<5]`. Perform checked increments/decrements rather than unsigned underflow. Splitting a physical node itself changes **none** of these counters: the old logical contexts already existed; account only the new event at each depth. Startup contributes no full-row occupancy. These recurrence statistics are exact integers. Assert total visits per order equal max(n-k,0) in fixture snapshots.
- **Empirical conditional ML:** before updating each full row compute the frozen `g(T)-g(C_x)` and add to the per-k ML accumulator; reuse the scalar for shared rows, not a batch multiplication. Startup adds 5 or 8 to each applicable ML order. Snapshot L_ML and descriptive KT-minus-ML redundancy alongside L. Extra libm calls can materially affect throughput: separately count/time instrumentation where feasible, never disable silently mid-run. The recurrence computes the declared ML checkpoint functional in real arithmetic; assess floating error against a direct-count fixture reference, not against a gate threshold. No growing g(t) lookup table; optional fixed shortcuts for f(0),f(1) are part of the declared expression.
- **A attribution:** fixed `[17][32]` loss arrays and 32 symbol counts for Track A; classify the currently predicted byte, including startup, before next history update. Snapshot the small arrays at each checkpoint.
- **B whitespace:** fixed three-bucket per-order L arrays/counts, one previous-byte whitespace flag, and one latest-whitespace cumulative L snapshot/offset. Use protocol's ASCII mask and event buckets; no lookahead, token buffer, Unicode decoder, or sentence parser in the coder. Snapshot after the whitespace byte's loss/update so b is inclusive. Aligned-prefix and bucket arrays are descriptive only.
- **Derived arrays:** evaluation computes increments, linear-n mixed finite differences, mean surfaces, sample std, strict uniqueness and ordinal first-below ridge from persisted results; these need no input reread. Preserve per-seed diagnostics as well as diagnostics of the mean.

## 6. Minimal verification and release order (instructions, not claimed executions)

1. Preserve protocol/freeze checksums now. Add parameterized traits, history, serialization, dense/tail depths and cache fixes; finish the missing CLI/generator/tests using existing CMake conventions. Reuse the exact frozen PRNG; do not create a new sampler architecture.
2. Add checkpoint and Annex instrumentation plus sidecar validation/provenance. Emit a complete execution supplement only when actual source/build hashes exist; no placeholder hashes in a runnable release. A's generator schedule is the 90 manifest run records. B's ingestion owner supplies its own prior source freeze; do not wait for or fabricate B sources in this role.
3. Run deterministic fixtures, not experimental generators: empty/short/startup, constant/alternating, all byte values, K=0..16, chunk/checkpoint boundaries, A invalid 32/B valid 255, absent/mismatched sidecars, keys differing only in bits 64..127, prefix depth16, full support256, endpoint/divergence split with inherited histogram. Compare every pre-update count and loss to a bounded naive independent-order reference. Same-expression KT raw L should be bit-identical on the same executable; ML/attribution closed-form identities get explicit roundoff tolerances in tests only.
4. Compare one/few-page and large fixed caches on deterministic fixtures with state much larger than cache, enough churn to exhaust naive tombstone empties. Require dirty evictions, equal counts, bit-identical KT L, equal exact occupancy, and equal ordered Annex accumulators. Inject truncated-store/read/write/ENOSPC/overflow failures. Use sanitizers for undefined shifts/out-of-bounds. Deterministic small global permutation fixtures test KT invariance without running the gated production separability experiment.
5. Verify metadata cardinality is fixed, observed allocation/RSS behavior, one actual corpus input pass per API call, checkpoint timing, fsync/error publication, and output schema. Hash used binaries/toolchain after successful fixtures and before any experimental sample. Resource probes without corpus generation are not measured availability evidence.
6. The execution owner may then generate/score registered A runs unchanged; source-ready B runs require Sonnet's frozen provenance too. Preserve missing/incomplete scope and disk/time blocks. This design handoff does not certify 115 surfaces, any prediction, a successful build, or measured production feasibility.

## Files delivered by this role

- `REVB_PROTOCOL.md`: all Track A kernels/startup, ten strict predicates, means/std/ties/undefined handling, operational first-increment ridge/saturation, gates, bijections, Annex/cost conventions.
- `REVB_FREEZE.json`: machine-readable constants, explicit 90 runs, evaluator/Annex definitions, engineering settings, reference hashes, B owner/dependency status; operational freeze, not a built execution manifest.
- `REVB_DELTA.md`: this minimal change map and actual unresolved implementation/resource risks.
- `REVB_FREEZE.sha256`: hashes for the three immutable handoff artifacts; mirrored byte-for-byte to the requested final-artifact directory.
