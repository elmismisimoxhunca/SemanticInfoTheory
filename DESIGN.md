# Block 01: exact external-memory KT design and mathematical audit

## 0. Status, scope, and immutable inputs

This is the storage/mathematics role's completed design and resource audit, **not a completed experiment or an implemented KT engine**. No generator was run and no corpus was created. The executed work was host inspection, compilation/execution of a storage-only probe, compilation of a PRNG header without drawing from it, and deterministic analytical checks. No agents were spawned; no deployments, restarts, credentials, generator kernels, thresholds, or protocol text were changed.

`PROTOCOL.md` was read completely before this work. Source and origin-artifact copies both have SHA256:

`4191447aa5255363f454125746ea9a551539f9b5cca81ebccc39f7572897ae0f`

Workspace: `/home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/personal-workspaces/env_sveaeeem4z`

Origin artifacts: `/home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/thread-storage/thr_363jypygh6`

Deliverables are `DESIGN.md` and `design/` in both locations. The PRNG reference was hashed and copied to origin storage before any PRNG draw; there have been no such draws in this role. The production owner must bind this exact reference, or another already-frozen implementation, into the **actual** pre-sampling implementation/constants manifest. A design hash alone does not certify a different generator executable.

## 1. Recommendation

Implement a **page-backed, path-compressed radix trie of reversed histories**, with exact next-symbol histograms, a small dense depth-0..3 frontend, and an explicitly fixed-size page cache. This is a viable bounded-RAM design, not an excuse to retain a growing in-memory dictionary. Trie nodes, histogram extensions, child arrays, allocator metadata, and free-list links live on disk. Cache replacement writes dirty data back; it never discards counts. Full keys are compared; there is no probabilistic identity test.

Start with one worker and a fixed **2 GiB** page cache. This budget does not depend on N. It is intended to make N=10,000,000 practical while permitting exact spill past the cache at larger N. Keep the cache configurable internally for spill tests, but fixed throughout each run. Do not allocate a table with an arbitrary maximum N, abort when that table fills, and call it bounded-memory streaming.

Why this representation:

* Reverse histories make all suffix contexts prefix-related, so one traversal covers every order.
* Path compression makes a newly seen length-16 history one leaf rather than up to 13 separate high-order context records.
* A compressed edge's intermediate orders have exactly the same histogram. They can share one probability evaluation and one histogram update, while retaining seventeen independent, input-ordered binary64 L accumulators.
* One on-disk store, no per-symbol/per-order SQL transaction, no sorting/rereading corpus, no information eviction, and no unbounded host-language objects.
* The design remains exact when the state outgrows RAM. At that point random I/O can dominate; bounded memory is not a claim of bounded disk or fast execution at every N.

## 2. Exact sufficient statistics and startup

For a prefix ending just before symbol i, let the key for order k be the previous k symbols in **most-recent-first** order. Its histogram is

\[
 C_c(a)=\#\{j<i:j\ge k,\ (x_{j-1},\ldots,x_{j-k})=c,\ x_j=a\},\qquad T_c=\sum_a C_c(a).
\]

These are exactly the full-order statistics needed by order k. Distinct depths remain distinct contexts. No counts from one order are combined numerically with another; identical sufficient statistics are merely represented once where the equivalence is provable.

The order-k startup events i<k are special. Their context lengths are i, each occurs only once **in that order**, and thus each costs exactly 5 bits. They do not use or mutate the global full-order row for depth i on behalf of order k. On every event:

1. Score k<=min(i,K) from their depth-k full-context histograms.
2. Score every k>i by adding exactly `5.0` to its own L[k].
3. Update each represented full-context histogram for depths 0..min(i,K) once, after all scores.

This preserves the frozen startup convention while avoiding seventeen independent copies of identical state. Blindly feeding every startup order into a shared depth-i row would be a bug.

Maintain a rolling 80-bit history in two uint64 limbs (or an unsigned 128-bit temporary). Its low five bits are most recent. After processing x, set `history=((history<<5)|x) & ((1<<80)-1)` using a sufficiently wide unsigned type. Depth k is the low 5k bits; depth is explicitly stored. Do not shift a 64-bit operand by 80. K may be lower than 16.

For each score, use one fixed implementation of

\[
 p=(C_c(x_i)+1/2)/(T_c+16),\qquad \ell=-\log_2 p.
\]

Proposed binary64 expression: `-std::log2((double(n)+0.5)/(double(total)+16.0))`. For an empty row return exactly `5.0`. Use the same expression in the reference and production engine; do not mix quotient-log and difference-of-logs paths and then promise bit-identical arithmetic. Add each score to L[k] in corpus order. No parallel reductions, batch multiplication of repeated losses, Kahan replacement, or post-hoc gamma-function summation for production L. An analytical gamma formula can independently check mathematical totals within a stated floating tolerance. Avoid `-ffast-math`; use `-ffp-contract=off` and hash the executable/platform/libm provenance. Independent corpus workers may run concurrently after resource checks, but a corpus's floating accumulation stays ordered.

## 3. Compressed-trie invariant and update algorithm

### 3.1 Logical tree

Insert the key consisting of the available reversed history of length min(i,K), with payload x_i. Every logical prefix node contains the histogram of all inserted payloads below that prefix, including payloads terminating at that node. An uncompressed trie would be exact but too large. Compress every unary path with **no terminal history ending inside it**.

For an edge u->v, every implicit depth d with depth(u)<d<=depth(v) has exactly histogram(v). The reason is set equality: no branch and no endpoint separates those prefixes, so precisely the same past events pass all of them. Empty/new portions of a query path have all-zero histograms. Keep all short-history endpoints explicit (at most K of them); otherwise early events could be incorrectly counted at deeper orders.

The implicit row at depth d is still logically a separate order. Its shared storage is not backoff: if two rows cease to be identical after a branch, they are separated immediately.

### 3.2 Per-symbol operation

1. Read/validate the next byte. Preserve the pre-update history and symbol index.
2. Obtain frontend rows at depths 0..min(3,i,K).
3. If min(i,K)>=4, look up the exact depth-4 directory slot and follow compressed edges, comparing actual 5-bit digits. Record in a **fixed, at-most-17-entry scratch array** the depth intervals and their pre-update histograms.
4. When the key diverges inside u->v after l matching digits, create branch w at depth l and copy v's pre-update histogram into w. The old v remains attached for its old suffix. The new suffix is a new zero-count leaf. Depths through l use the inherited histogram; deeper new-path depths use zero. If the key ends inside an edge, split at that endpoint and preserve a terminal node. A missing edge has zero rows for its entire new suffix.
5. Compute losses from the recorded pre-update rows and add them individually to the relevant L[k]. One log evaluation may be reused for all depths on the same compressed edge because its integer inputs and expression are identical. Startup orders add 5 separately.
6. Increment every distinct node on the **new key's** route once. Do not increment the old child below a divergence. The new branch inherits old history plus this event; the new leaf contains only this event. A histogram copy on splitting must be a real copy/copy-on-write with independent future mutation, not an alias of a mutable child buffer.
7. Append x to the rolling history and increment the processed-symbol count. Flush dirty pages on cache replacement. Continue reading the corpus once.

Allocations and structural changes may occur during lookup, but they must not change statistics before scoring. Existing exact-key hits need no new nodes. A histogram is an integer vector even if stored sparsely.

### 3.3 Correctness argument

Induct on events. Initially all rows are empty. The trie invariant equates each explicit/implicit row with the event set defining C above. Splitting copies exactly the old shared event set, new branches start empty, and endpoint preservation prevents overcounting unavailable history. Scoring therefore uses the frozen KT counts. Adding the current event to its matching prefixes preserves the invariant. Startup events cost 5 because their per-order length-tagged context has never occurred. Hence the returned L and A equal an exact independent-order reference with the same floating expression and input order.

## 4. Concrete bounded-memory layout

### 4.1 Fixed frontend

Dense rows for depths 0..min(3,K): at K>=3 there are

\[
 1+32+32^2+32^3=33,825
\]

rows. Store 32 uint64 counts and a uint64 total per row: **33,825 * 264 = 8,929,800 bytes**. Index each depth separately with its low-5k-bit history. This practical ~8.52 MiB fixed array is acceptable; a 32^16 table is not.

For K>=4, a direct array of 32^4 uint64 tail pointers costs 8,388,608 bytes (8 MiB). Slot identity incorporates the depth-4 prefix. Null means no tail row has been observed. Frontend and directory memory are fixed, and their checkpoints can be fixed-size files. No tail node is retained in an unbounded side map.

### 4.2 Disk records

An implementable initial layout:

* 64-byte node header: full 80-bit prefix key in a 16-byte field, depth, flags/terminal marker, total count, inline singleton symbol, histogram reference, children reference, and capacities/degree. Define the actual serialized offsets and `static_assert` the packed record sizes; do not dump compiler-dependent structs.
* Histogram with support one: use the header's symbol and total. Empty rows have total zero. For support 2, 3..4, 5..8 use sorted `(symbol,count)` blocks of capacity 2, 4, 8; each pair can be padded to 16 bytes. At support >=9, use a dense 32*8=256-byte vector. All counters remain uint64.
* Child references use the same small sorted-array capacities and switch to 32*8=256-byte dense pointers at degree >=9. Endpoint unary nodes may use capacity one. Child tags are exact alphabet symbols. Internal compressed nodes normally have degree at least two.
* Separate page/slab size classes for 16,32,64,128,256-byte blocks; headers are 64-byte slabs. Size-class free-list heads are fixed-size memory, with free-record links on disk. Growing free lists, page tables, per-node wrappers, or allocator vectors in RAM are forbidden. Prefix locality is an optional later storage optimization, not a statistical change.
* Offset zero is null; offset arithmetic, node totals, and individual counts are checked for overflow. Counts up to the frozen N and 1e9 extrapolation are exact. Uint64/file-offset representational limits are explicit API errors, not a false claim of mathematically unlimited streams.

These capacities bound per-record work, not maximum N. Expand files as needed. A full disk or allocation/write error stops with `resource_infeasible`/incomplete output; never fall back to dropping records, truncating the corpus, capping frequencies, or resetting counts.

### 4.3 Cache and I/O

Use explicit `pread`/`pwrite` pages with a fixed CLOCK/LRU cache and a fixed-capacity page-ID index. A hash table may index cached **page IDs** only if collisions are resolved by exact ID comparison and its capacity is fixed. Cache data is disposable only after dirty pages are persisted. Pin at most a fixed path's pages while splitting; validate a minimum cache size and release pins promptly.

Suggested budget: 2 GiB page data + fixed index/CLOCK metadata + frontend/directory (~16.52 MiB) + <=a few MiB input/output buffers and fixed traversal scratch. Report the actual summed allocations and peak RSS; metadata must not be omitted from the budget. A smaller cache must still be correct, merely slower. A fixed 2 GiB cache is not a max-N table because its misses are resolved from the exact growing disk store.

Do not `mmap` the entire growing store and declare success because the virtual mapping is cheap. Explicit paging bounds process-resident working buffers. Buffered pread/pwrite can additionally occupy kernel page cache; disclose this separately from RSS. If a hard total host-memory accounting boundary is required, use aligned O_DIRECT pages where supported, or bounded periodic writeback/advice with observed OS cache accounting. `madvise` alone is not a proof of bounded RSS. The storage probe confirms O_DIRECT works for a 4 KiB-aligned scratch file on this mount, not that the engine has implemented it.

No fsync per context or symbol. Treat the store as one sequential processing job, coalesce dirty page writes, and fsync before publishing a successful result. Crash safety options: mark an in-progress store invalid and require a clean restart, or add bounded-batch WAL/checkpoints with exact replay. Do not promise resumability unless tested. WAL bytes and retained segments are disk costs. The prototype can choose invalid-on-crash; this avoids billions of transactions without compromising exactness in successful runs.

## 5. Space/work estimates and measured host costs

### 5.1 Host inspection, 2026-09-14 UTC

* Linux/WSL virtual block device, Intel i7-9700K, 8 logical CPUs, no SMT indicated.
* `free -h`: 15 GiB RAM, about 13 GiB available at inspection; 4 GiB swap, unused. These are snapshots, not reserved resources.
* Workspace filesystem reports ext-family, 4096-byte blocks. `df -B1`: total 1,081,101,176,832 bytes; available 769,854,152,704 bytes (~717 GiB).
* `/dev/sdd` reports rotational=1, but this virtualized flag does not establish underlying physical media.
* No conventional root cgroup v2 memory/cpu limit files or inspected v1 quota candidates were accessible. No claim that a host-visible RAM figure is an enforced per-worker allocation.
* g++ 13.3.0, CMake, Python 3.12.3 available; clang++/ninja/fio were not found on PATH by this inspection.

Executed storage-only probe (`design/storage_probe.cpp`, `design/storage_probe.json`): a private 64 MiB zero-filled scratch file, removed on completion; **not a generator corpus**. Sequential 1 MiB writes including fsync took 0.048724 s (~1,314 MiB/s). A deterministic permutation of 4 KiB aligned O_DIRECT reads, queue depth one, 4,096 requests took 0.275710 s: 14,856 IOPS. 1,024 O_DIRECT writes plus fsync took 0.072208 s: 14,181 IOPS.

These are **small, freshly written, virtualized-device measurements**, not a cold-storage sustained-I/O promise. O_DIRECT bypasses the guest page cache, not all host/controller caches. Zero-filled scratch can also benefit from backing-store optimizations. They do establish executable toolchain and direct-I/O availability and provide a measured cautionary scale for serial random requests. No KT throughput, production RSS, production disk footprint, or full-size execution was measured by this role.

### 5.2 State size

Let D be distinct full-length histories. Excluding the fixed frontend, the compressed forest has O(D+K) leaves/endpoints and at most O(D+K) branch nodes: nonterminal unary nodes have been removed. Each node's alphabet-bounded histogram and child array is at most 256 bytes each, plus a 64-byte header. Thus a deliberately loose live-record bound is about **1,152N bytes**, plus page slack, size-class fragmentation, fixed arrays, and free space retained by the allocator. This is a disk-growth bound, not a RAM allocation. At N=1e7 it is 11.52 GB of live payload; at N=1e9 it is 1.152 TB, exceeding current free disk. It is not a worst-case on-disk bound without accounting for allocator/page/WAL overhead; allocator growth must be instrumented.

A better **illustrative, not measured** estimate for independent uniform length-16 history keys is in `design/math_audit.json`. For prefix depth d and Poisson occupancy lambda=N/32^d, the expected branching probability is

\[
 b_d=1+31e^{-\lambda}-32e^{-31\lambda/32}.
\]

Sum 32^d b_d over d=4..15. Assuming essentially distinct length-16 keys and singleton next-symbol leaf histograms:

| N | Tail branches | 64-byte node headers | Headers + dense maximum branch histograms/children |
|---:|---:|---:|---:|
| 10,000,000 | 2,283,948 | 0.786 GB | 1.956 GB |
| 1,000,000,000 | 299,719,038 | 83.182 GB | 236.638 GB |

The last column is a conservative branch-payload estimate **conditional on this random-key model**, not an unconditional storage guarantee. Sparse branch arrays reduce it; slab slack, free blocks, and metadata increase it. Overlapping G4 windows are not independent keys, and this occupancy model is especially inappropriate for lag-copy and G3. A 2 GiB cache may hold much of a 1e7 uniform-key store, but must spill correctly if it does not. At 1e9, the cache is much smaller than the estimated state. The illustrative single-store estimate can fit on the currently available disk, but thirty retained stores at that estimate would total about 7.1 TB and would not. Conversely, an upper bound exceeding free disk does not prove every actual corpus will exhaust it. Retention policy and measured source-specific occupancy are essential.

Thirty raw N=1e7 byte corpora total 300 MB, separately from count stores. Retaining thirty stores can dominate disk; report per-run live/allocated/peak bytes and overall retained disk. Keep required origin artifacts and source-local results without silently doubling giant stores; an explicit index to origin-resident stores is preferable to unnecessary copies. Do not remove completed corpus/store artifacts without the execution owner's retention decision. Check free space before and during execution; do not confuse disk exhaustion with experimental no-go.

### 5.3 Throughput and extrapolation

Naive independent tables require 17N order scores and potentially 17N random lookups/updates: 170 million per corpus, **5.1 billion** across the thirty runs. Even one 4 KiB serial device request per such operation would take ~95 hours at the measured read IOPS, before writes, logging, or CPU work; transaction-per-context SQLite would usually amplify this further.

The compressed engine still performs seventeen ordered double additions per steady-state symbol. However, empty suffixes all score exactly 5, shared compressed-edge probabilities are evaluated once, and only explicit route nodes are updated. Prefix traversal is bounded by K=16; splitting copies at most 32 counters and 32 links. Arithmetic is O(NK) at fixed alphabet/K. Expected explicit-node depth grows approximately with log_32(D) until capped by K. Cache-miss fraction and storage/index costs change as the working set grows; do **not** extrapolate elapsed time as exactly 100 times a small in-cache run.

Report actual per-symbol page reads and page writes. With r reads/symbol and w writes/symbol, a rough serial device component is

\[
 T_{IO}(N)\approx N\left(r/14856+w/14181\right)\ \text{seconds}.
\]

One read per symbol alone means ~11.2 minutes at N=1e7 and ~18.7 hours at N=1e9 **per corpus**; CPU, writes, contention, and different sustained device performance are additional. At fixed cache size r/w will often increase with N. Show this model alongside measured CPU/log-call counts, cache hits/misses, disk growth, and multiple-k timings, not instead of measurements.

No empirical feasibility decision for thirty full-size curves is justified yet. The design offers a practical route worth implementing; it does not establish that full execution fits an unspecified runtime budget.

## 6. PRNG specification and pre-sampling freeze

Reference implementation: `design/prng_reference.hpp`.

SHA256: `a38ce3bd9dbf751f40b92c5ebea85c191e60c71d935b134068944651582b7542`.

Use SplitMix64, with `state=uint64(seed)` initially, no warm-up, unsigned wraparound:

1. `z = (state += 0x9e3779b97f4a7c15)`.
2. `z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9`.
3. `z = (z ^ (z >> 27)) * 0x94d049bb133111eb`.
4. Return `z ^ (z >> 31)`.

For uniform bound b>0, compute `threshold=(uint64(0)-b)%b`; draw u until u>=threshold, then return u%b. This removes modulo bias under uniform 64-bit draws. The actual bounds 4,8,16,32 divide 2^64, so there are no rejections and low-bit modulo selection is intentional. This is a reproducible finite-state pseudorandom sampler, not a claim of literal IID physical randomness or a cryptographic generator. The analytical source entropy concerns the ideal stochastic kernels, as is conventional; a completely specified deterministic seed alone has no positive information-theoretic entropy.

Each registered (generator,seed) starts a fresh state directly from 101,202,303,404,505. No generator-name mixing, seed search, library RNG, or parallel interleaving of a shared PRNG.

* G1/G2/G5/G6: initialize d positions with d consecutive `uniform(32)` draws. Thereafter consume **first `uniform(4)` for the coin, then `uniform(32)` for innovation, even when copying**. Coin 0,1,2 copies x[i-d]; coin 3 emits the innovation. Initialization consumes no copy coins. d remains 1,5,2,8 respectively.
* G3: at each block position 0 draw `16+uniform(8)`; at positions 1..7 draw `uniform(16)` once each; at position 8 emit controller+8 without a draw. Stop at N without generating unneeded trailing symbols.
* G4: one `uniform(32)` per emitted symbol.

Before first generator output, freeze/hash the **used** PRNG, generator sources, machine-readable constants, protocol, and initial built executable/toolchain manifest. Hash corpus bytes while writing. Preserve this manifest. If another role has already frozen a different permitted PRNG, do not replace it after sampling; record the actual prior freeze and resolve the design/reference difference transparently. The current role observed no generator implementation in the workspace when designing this reference.

## 7. Mathematical audit

### 7.1 Lag-copy entropy and minimal order: verified

At a non-initial position, copying has probability 3/4 and an independent innovation has probability 1/4. Therefore the old lagged symbol is emitted with probability

\[
 q=3/4+(1/4)(1/32)=97/128,
\]

and each of the other 31 symbols with probability r=1/128. The transition matrix is positive and doubly stochastic; a uniform initial state is stationary, irreducible, and aperiodic.

The d residue classes modulo d are independent stationary first-order chains. Initializing the first d symbols independently uniformly therefore gives the stationary lag-d process (equivalently restrict its two-sided stationary construction). A window shorter than d omits the current residue class, and is independent of the current symbol. Thus

\[
 H(X_i\mid X_{i-k:i-1})=5\quad(k<d),\qquad
 H(X_i\mid X_{i-k:i-1})=h\quad(k\ge d),
\]

where

\[
 h=-q\log_2q-31r\log_2r=1.9985035492800673.
\]

Since q!=r, the lag-d symbol genuinely affects the conditional law; no order below d suffices. G5 and G6 have exactly equal analytical entropy rates, not merely a small measured mismatch. G2's marginal is exactly uniform, and G4 matches this analytical marginal, not each finite sample's histogram. None of these facts promises the finite-N KT step tests will pass: for example G2's five-symbol stationary context distribution has 32^5=33,554,432 possibilities, already larger than N. Do not apply IID occupancy formulas to its temporally dependent visits.

### 7.2 G3 phase confound: real and quantifiable

Fixed block alignment makes G3 cyclostationary/nonstationary under one-symbol shifts, not a stationary IID sequence or a pure distance-eight-only phenomenon. Its independent block entropy is 3+7*4=31 bits, so the asymptotic entropy rate is 31/9 bits/symbol. Startup/truncation gives an O(1) block-boundary entropy correction, not a different rate.

The KT API does not receive phase as a side channel. Consider long-run **phase-pooled oracle** conditional entropies, and let H_b be binary entropy. The type frequencies are 7/9 fillers, 1/9 controllers, 1/9 agreeing symbols. Then

\[
 H_0=34/9+H(7/9,1/9,1/9)=4.764204506508620,
\]

\[
 H_k=34/9+\frac{8-k}{9}H_b\!\left(\frac1{8-k}\right),\quad1\le k\le7,
\]

\[
 H_k=31/9,\quad k\ge8.
\]

For k<=7, the only type-phase ambiguity is a suffix of k fillers; the (8-k) compatible phases include one next-agreement phase. The controller value itself remains unknown at the agreeing position until k=8. All other phase identities can be determined once a controller/agreeing symbol appears in the context. At k=7, seven preceding fillers fix the agreeing phase but not its value.

Consequently the oracle k=8 gain is 1/3 bit; the largest k=2..7 gain is **2/9 at k=7**, itself a phase effect. The k=1 gain is ~0.526237, larger than the agreement gain but explicitly excluded from the registered dominance comparison. This explains the phase confound without invalidating the frozen k=2..7 oracle comparison. Numeric arrays and analytical assertions are saved in `design/math_audit.json`.

These are not measured availability curves. At the agreeing position the k=7 support is 16^7=268,435,456 filler contexts, and k=8 support is 8*16^7=2,147,483,648 controller/filler contexts. Only about N/9 agreeing positions occur in a run. Most such contexts cannot accumulate meaningful KT evidence at N=1e7. The generic predictor does not know that controller+8 is the correct output. Sparse-context failure is compatible with correct code and a real eight-step dependency. Do not modify fillers, alphabet, block length, or kernel to fix it.

### 7.3 Global permutation test: across-class drop impossible

For any global bijection pi, the map `(context,a)->(pi(context),pi(a))` bijects every observed count at every step. Length tags and startup behavior are preserved. Symmetric KT's 32 half-counts and total+16 denominator are unchanged. Hence every per-symbol probability, every L[k], and every A[k] is invariant for **all k, all corpora, all N**.

With the prescribed same-expression, input-ordered implementation, matching arithmetic should also be bit-identical on the same executable/platform. Cache paths and timings may differ; predicted losses may not. A nonzero relabeling difference is a correctness/provenance issue, not semantic separability.

Both the frozen within-class rotation and the cross-class exchange are global bijections. Within-class differences are zero; across-class drops are also zero. If Go is reached, execute the conditional tests as specified and report the requested across-class drop as impossible/failed. Do not execute those production permutations early, introduce non-bijective corruption, or invent a post-hoc numerical threshold for “measurably.” Mathematical proof can be reported before Go. No compliant implementation can make this across-class drop positive.

### 7.4 Negative normalization and strict tests

Finite-N KT availability is not guaranteed nonnegative or monotone in k. A richer context model incurs sample-sparsity/estimation costs, and L[k] can exceed L[0]. Never clip A or take an absolute value of its normalization denominator.

For each eligible generator, form the registered seed-mean curve first and then divide by **that mean curve's own A[16]**. Do not average per-seed normalized curves. Preserve negative signs. If a denominator is exactly +0 or -0, the normalization is undefined and prediction 6 cannot pass. If a denominator is tiny but nonzero, perform the registered division and report instability/magnification; do not replace exact zero with a tuned epsilon. JSON must represent undefined results explicitly, not invalid NaN tokens.

A negative denominator reverses signs, yet the normalized endpoint is always 1 and the zero-order endpoint 0. Pairwise L-infinity distance can therefore reflect sign reversal and small-denominator amplification, not a scale-free measure of intrinsic information. Report denominators and this limitation even if prediction 6 passes. Keep all strict inequalities strict. For G4, the registered upper bound A[k]<0.01 is one-sided: a strongly negative curve can pass it, so it does not establish “all gains approximately zero.”

## 8. API, build, and test contract for the implementer

These interfaces are specified here; **they do not exist yet in this workspace**.

Public downstream Python facade only:

```
availability(corpus_path, k_max=16) -> list[float]   # length k_max+1
```

It returns A, with A[0]=0.0. Empty input returns k_max+1 zeros (seventeen at the registered K). Reject nonintegral/out-of-range k_max, unreadable paths, and any byte outside 0..31. A NUL byte is symbol zero, not a terminator. Process a file incrementally; do not materialize corpus bytes. Keep configuration/state management and L/metrics export internal. Per-call counters start empty. Use the repository's binding/build primitives if the implementation owner adds a Python wrapper; do not expose a growing menu of public estimator alternatives.

Suggested build/verification interfaces:

```
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 2
ctest --test-dir build --output-on-failure
python3 -m pytest -q tests/test_availability.py
# Internal only; paths/flags may follow the owner's existing conventions:
build/kt_stream --corpus PATH --k-max 16 --cache-mib 2048 --store DIR --metrics JSON
```

Do not claim these commands passed until targets exist. Avoid adding a new package dependency solely for the design. C++20 plus POSIX I/O suffices for the engine.

Required tests before production sampling/curves (the owner may run deterministic fixtures without changing the frozen protocol):

1. Empty, one-symbol, two-symbol, constant, alternating, boundary symbol 31, invalid byte 32, every k=0..16, files shorter than k, and chunk-boundary continuity. Hand-check order-0 two repeated symbols: first probability 1/32, second probability 1.5/17; order-1 startup followed by a new context remains 5+5 bits.
2. Independent naive per-order, length-tagged exact reference **only for bounded test fixtures**. Compare every pre-update `(n,total)` and final L/A, including startup, against the trie. A test reference's map must not be relabeled as a compliant production backend.
3. Structural cases: branch at first/last tail digit; existing exact leaf with a second next symbol; inherited-histogram split; terminal endpoint; wide nodes; sparse-to-dense promotion; counts exceeding uint32; valid 80-bit keys with equal low 64 bits and different high bits; no mutable histogram aliasing.
4. Deterministic small versus large fixed caches on identical fixtures, forcing dirty eviction/reload repeatedly; compare L bit patterns. Corrupt/read/write/ENOSPC injection must fail loudly. Cache metadata cardinality must remain at its fixed cap. Check integer/file-offset overflow guards.
5. Verify global bijection invariance on small **coder fixtures**, distinct from the Go-gated G3 production permutation experiment. Do not treat tiny smoke data as experimental curves.
6. RSS and explicit allocation accounting at increasing state sizes past cache capacity; disk bytes/page counts/cache hits/misses/bytes-read/bytes-written/log-call counts. The cache must not silently grow. Verify one corpus pass by instrumenting actual file reads, not just a function name.
7. Benchmarks at clearly labeled smaller N (e.g. 1e4,1e5,1e6) and k=0,4,8,16, then N=1e7 when feasible; use separate smoke/benchmark provenance and unchanged registered generators/PRNG. Benchmark owner, not this design role, generates these. Make at least one storage stress test spill even if N=1e7 fits a 2 GiB cache. Compare actual projected thirty-curve wall time and disk requirements before launching concurrency.

Internal raw JSON per production curve must include all 17 A and L, N, alphabet, seed, generator, protocol/implementation/PRNG/constants hashes, executable/platform identity, wall time, peak RSS, storage method and cache budget. Include count-store logical/allocated/peak bytes, I/O counters, and completion status. Atomic publication follows fsync; incomplete output cannot masquerade as a curve. Persist all thirty full-size curves before computing registered seed means/spread and strict prediction checks from saved results. Benchmarks cannot substitute for missing curves.

Actual commands executed by this role:

```
g++ -std=c++20 -O2 -Wall -Wextra -Werror design/storage_probe.cpp -o /tmp/block01-storage-probe
/tmp/block01-storage-probe . > design/storage_probe.json
python3 design/math_audit.py
# Header syntax-only compilation; no PRNG construction/draw:
printf '#include "design/prng_reference.hpp"\nint main() { return 0; }\n' | \
  g++ -std=c++20 -O2 -Wall -Wextra -Werror -I. -x c++ -fsyntax-only -
sha256sum -c design/PRNG.sha256
sha256sum PROTOCOL.md
```

All succeeded; six mathematical assertions passed. Probe binary and its private scratch file were removed. No KT test or production curve was claimed.

## 9. Honest remaining requirements and contradictions

* **Remaining implementation:** on-disk trie/cache, exact reference tests, public wrapper, machine-readable frozen constants, actual generator integration/build manifest, metrics collection, full executions, prediction analysis, and Go-gated empirical permutation execution. This design and its audit do not fulfill those other roles' work.
* **Unavoidable experimental contradiction:** symmetric KT cannot distinguish any two globally bijectively relabeled corpora. The cross-class requested drop is mathematically impossible. Retain this failure; do not redesign the estimator or permutation.
* **Not a contradiction:** exact one-pass all-k scoring and fixed practical RAM can coexist when exact state grows on disk. Time/disk may still be infeasible at particular N/resources. No completed evidence currently establishes full-run feasibility.
* **Strict machine-memory caveat:** an indefinitely unbounded N also requires indefinitely wide counters and offsets. The proposed uint64 implementation is exact throughout the registered and extrapolated range, rejects representational overflow, and does not pretend to implement arbitrary-precision unlimited streams. A mathematically unlimited API would require disk-backed variable-width counters as well.
* **Rejected compliant labels:** a growing map; finite 32^16 address-space rhetoric; mmap without a resident bound; fixed max-N hash tables that fail at capacity; sketches; collision-only keys; count eviction; offline external-sort/gamma totals that violate online ordered binary64 scoring. An exact map fallback, if used for production, must be prominently marked **memory noncompliant**, not silently substituted. No fallback is needed in this design.
* **Reporting:** failure to execute thirty full-size curves is resource/incomplete evidence, not a six-test experimental no-go. Only actual saved curves determine the six registered checks. No block-02 work, no tuning, no reader-independent intrinsic-information claim.

## 10. Minimal implementation sequence

1. Bind/hash the PRNG and frozen constants before any sampling; retain the protocol hash.
2. Implement exact dense frontend + reversed-history compressed trie with the startup rule and test against tiny independent-order fixtures.
3. Put all tail state and allocator metadata behind a real fixed-capacity page cache; prove dirty-spill equivalence with very small caches before production.
4. Add ordered L accumulation, the single public API, internal provenance/metrics export, and explicit failures for exhausted resources.
5. Measure small/full-N costs with unchanged generators; produce thirty full curves only if feasible; analyze saved curves without altering any test.
6. Preserve the phase/sparsity/negative-normalization qualifications and report global-permutation impossibility regardless of desired narrative.
