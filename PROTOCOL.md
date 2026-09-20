# Block 01 — frozen execution protocol

This is an implementation of the supplied Block 01, not a tuned replacement. Written before any synthetic generator is executed. Named generator families in the request do not specify transition kernels; the following explicit kernels complete those definitions before observation. No revisions to kernels, estimator, constants, seeds or thresholds after sampling.

## Constants and representation
Alphabet 0..31 (one unsigned byte per symbol); N=10,000,000; k=0..16; KT add-1/2 with denominator count(context)+16. Five seeds per generator: 101,202,303,404,505. No trained models, held-out selection, smoothing alternatives or context backoff.
For i<k, use the available prefix of length i as a distinct shorter context (context length is part of the key). Score every symbol including startup; update only after scoring. Each order has its own counts. L accumulated in input order using binary64; A[k]=(L[0]-L[k])/N, A[0]=0. Empty corpus returns seventeen zeros for k_max=16, documented as an API convention rather than an experiment. Validate symbol range and k_max 0..16.
Determinism is bit-identical on the same executable/platform, not an unsupported cross-libm guarantee.

## Frozen generators
All random sampling uses a documented deterministic PRNG with its implementation frozen and hashed before first sample. Uniform draws must be unbiased. Seed applies independently for each generator; no seed searching. Stream directly to byte files, never hold entire production corpus in RAM.

G1, G2, G5, G6: lag-copy Markov sources with lag d=1,5,2,8 respectively. Initialize d symbols independently uniformly over all 32 symbols. Thereafter with probability 3/4 copy x[i-d], otherwise emit an independent uniform symbol 0..31. The copy-versus-innovation draw and the innovation draw (even when copying) are consumed in a fixed documented order. These are stationary interleavings of identical ergodic Markov chains; minimal order d, uniform marginal. Conditional probabilities are q=97/128 for the copied symbol and r=1/128 for each of the 31 others. Entropy rate h= -q log2(q)-31 r log2(r). G5/G6 analytical mismatch exactly zero. G2's theoretical unigram distribution is uniform.

G3: independent blocks of nine positions. Position 0 controller chosen uniformly from 16..23; positions 1..7 independent fillers uniform 0..15; position 8 agreeing symbol = controller+8 (24..31). Repeat, truncate at N. Types declared a priori: fillers 0..15, controllers 16..23, agreeing 24..31. The nontrivial agreement dependency is exactly distance 8; deterministic type phase creates additional short-range structure and must not be concealed. Known entropy rate (3+7*4)/9=31/9 bits/symbol.

G4: independent uniform 0..31, matching G2's analytical (not empirical output) unigram distribution. Entropy rate 5.

These valid family instantiations can fail the registered steps due to context sparsity. That result is not permission to redesign them.

## Predictions, unchanged
Evaluate on seed-mean curves, also report individual-seed checks and spread (sample standard deviation, min, max). Strict inequalities remain strict.
1. G1 A2-A1 <0.01.
2. G2 A6-A5 <0.01 AND A5-A4 >0.05.
3. G3 A8-A7 >0.05 AND A8-A7 strictly greater than every A[k]-A[k-1] for k=2..7.
4. G4 A[k]<0.01 for every k=1..16.
5. max_k abs(mean_G5[k]-mean_G6[k])>0.1.
6. For G1,G2,G3,G5,G6 divide each mean curve by its own A16. Maximum pairwise L-infinity distance >0.15. Preserve negative denominators. If any denominator equals zero, report undefined and do not call this a pass. Report denominator values and the interpretability limitation.

Go only if all six pass. If 1..4 fail, classify diagnostic failure, independently verify coder on trivial fixtures/G1/G4, retain measured results, and distinguish correct-code finite-sample failure from implementation bugs. If 6 fails report no-go/collapse; if only 5 fails report no-go (load-bearing claim failed). Never proceed to Block 02. Do not claim separation proves reader-independent intrinsic information; the reader is explicitly fixed.

## Conditional separability
Only execute on Go. Frozen G3 permutations: within-class rotate each class by one; cross-class exchange 0..7 with 16..23 and leave other symbols fixed. Apply a single global bijection to the entire corpus. Within-class max_k abs(delta A)<0.01. Across-class requested drop at every k>=8: report actual drops ("measurably" has no supplied numerical threshold; do not invent one post hoc).
Mathematical warning fixed before execution: symmetric KT coding is exactly invariant to all global bijective relabelings, including the across-class map. Therefore the requested across-class drop is impossible for this API. Report failure if reached, rather than silently replacing the operation with a non-bijective/context-dependent corruption.

## Engineering and provenance
Expose only availability(corpus_path,k_max)->array as the downstream API. Internal CLI/generation/analysis machinery is allowed. Exact counts only: no hashing collisions, eviction, approximate sketches, frequency caps or reset windows that change KT probabilities. Streaming one corpus pass, score all requested budgets online. Memory independent of N is a requirement to audit, not a label to give a growing dictionary. Disk-backed exact counts with fixed RAM cache are permitted; report disk growth and I/O as well as RAM. Alphabet/k finite-state ceilings are not evidence of practical bounded memory.
Freeze PRNG implementation, this protocol, and machine-readable constants using SHA256 before sampling. Preserve this text and manifests thereafter. Implementation correctness fixes may occur with logged rationale; never reinterpret generator tuning as a bug fix. Production raw curve JSON includes all 17 A and L values, N, alphabet, seed, generator, protocol and implementation hashes, wall time, peak RSS, storage method. Persist mean/spread arrays and machine-readable prediction results derived from saved curves, not a rerun.
Measure costs at explicitly identified smaller N and multiple k, and full N when feasible. Extrapolate to 1e9 with assumptions and distinguish linear arithmetic work from superlinear storage/index/I/O. Smoke/benchmark data is not a replacement for 30 full-size curves. Resource infeasibility must be reported plainly, not as an experimental no-go.
