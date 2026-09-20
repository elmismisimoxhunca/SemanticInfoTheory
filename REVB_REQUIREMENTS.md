# Block 01 Availability Surface — Rev B requirements

User supplied Rev B superseding Rev A, followed by Annex A (non-confirmatory observables and outcome map). This file records the operative requirements for implementation. Original PROTOCOL.md and its hash remain historical Rev A evidence, NOT the operative protocol. No Rev A production results are available. Existing work consists of storage/math design, PRNG reference, host storage probe, and incomplete core implementation. Audit actual logs before claiming no samples ran. Do not execute any synthetic generator, corpus reader, or experimental benchmark until a complete Rev B execution manifest is frozen. Mathematical calculations, corpus metadata research, source availability/size checks and engine development are allowed before freeze; do not examine A values.

## Measure and constants
API availability(corpus_path,k_max,checkpoints)->surface. A(k,n)=(L0(n)-Lk(n))/n. Prequential KT add-half, exact counts, one online pass, score before updating, no training/tuning/backoff/estimator alternatives. k0..16, n=2^12..2^23 inclusive powers of2, corpus length2^23. Track A alphabet32, five seeds per generator. Track B alphabet256 UTF8 bytes, five disjoint draws per corpus. Never compare surfaces across tracks. Declare and freeze startup semantics and seeds before samples; existing Rev A seeds101,202,303,404,505 and kernels may be reused explicitly before results, not tacitly assumed.

## Track A
G1 order1 Markov; G2 order5 Markov; G4 iid matched to G2 theoretical unigram. G3(d) d=[2,3,4,5,6,8,10,12,14], agreement at lag d, uniform filler between, declared disjoint controller/filler/agreeing types. G5(d)/G6(d) d=[4,8,12], short-range versus lag-d dependency, entropy rates analytically matched within0.02. Eighteen named generator configurations, five seeds each =90 surfaces. Explicit kernels, types, randomness consumption, initial states and entropy proofs must be frozen before samples.

## Track B
B1 English Wikipedia prose. B2 source code in one declared language. B3 English CHILDES child-directed speech. B4 B1 with sentence order shuffled. B5 B1 with word order shuffled within sentences. Five disjoint draws, each2^23 bytes, per corpus =25 surfaces. Declare public exact sources/snapshots/licenses/hashes, normalization/extraction (especially CHILDES adult speech directed to children versus child speech), language, sample draw algorithm, disjointness scope, sentence/word segmentation, shuffle seeds, boundary/truncation and whitespace policy BEFORE measuring. B4/B5 should be controlled transformations of corresponding B1 draws; preserve byte length/multiset with declared whitespace handling. Do not silently duplicate, pad, include non-child-directed material or replace corpora if source insufficient. Report input blockers. No claim about English, code or child-directed speech: discriminating power only.

## Frozen predictions (strict inequalities)
Evaluate full n unless specified. Declare seed aggregation and tie policy before results. Persist raw and individual-seed diagnostics.
1 G1 A2-A1<0.01.
2 G2 A6-A5<0.01 AND A5-A4>0.05.
3 Every G3(d): largest single k increment occurs at k=d and exceeds0.05. All nine distances must pass; ties require predeclared treatment.
4 G4 every k>=1: A(k)<0.01. Small negatives allowed.
5 Every paired d: max_k |A_G5-A_G6|>0.1.
6 G2 context budget of saturation nondecreasing in n and strictly smaller at n2^14 than n2^23. Operational saturation was not defined in Rev B; resolve explicitly BEFORE runs. Annex's first dA<0.01 is a possible literal convention but must not be conflated with sustained saturation.
7 G6(12) A(k,n)<0.3 for every k and n<=2^16.
8 Normalize each entire surface by own A(16,2^23), for G1,G2,G3(8),G5(8),G6(8). Maximum pairwise Linf distance>0.15. Declare zero/negative denominator treatment before results, no denominator replacement.
9 Track B maximum pairwise between-corpus surface Linf separation divided by maximum within-corpus five-draw pairwise Linf variation >3. Declare between-corpus aggregation before results. Ratio3 exactly fails; zero denominator must have explicit convention. No cross-track distances.
10 B1>B4>B5 for every k>=4 at full n. Strict ordering, with aggregation declared before results.

## Gates and interpretation
Report three independently computed gate checks, with numbers, regardless of outcomes: Correctness predictions1–4,6–7; Foundation5,8; Usefulness9,10. Annex limits interpretation: if correctness fails, outcome Void, foundation/usefulness arithmetic may be shown but no valid scientific verdict; if correctness passes and foundation fails, Foundation dead, usefulness not evidential; if correctness/foundation pass and usefulness fails, Valid but blunt; all pass Go. Prediction5 failure is NOT automatically mathematical evidence of normalized collapse if8 passes; report actual pattern honestly. Original spec assertions that every failed correctness prediction necessarily implies a code bug are claims to test, not permission to retune a valid KT implementation. Debug independently against trivial fixtures/G1/G4 first. No sampler changes to pass. G4 gate remains0.01, not a new zero cutoff from Annex prose. No Block02 implementation.

## Separability
Runs only if correctness and foundation pass; Track A. Within-class bijection invariance within0.01 everywhere, across-class bijection should drop measurably at/above d. Declare maps before runs, preserve requested bijective meaning. Symmetric KT is provably invariant to ALL global bijections; report contradiction/failure, never substitute context-dependent corruption. 'Measurably' undefined: report raw deltas and theorem, no post-result invented threshold.

## Engineering
Streaming bounded RAM independent of n, exact external state may grow but must be disclosed. All k/checkpoints one pass. Cost measured versus n,k,alphabet, extrapolate2^30 with assumptions/I/O complexity. Deterministic input-ordered binary64 accumulation, parallel only across corpora/generators (respect15GiB host memory). API metadata must distinguish alphabet even though public signature has no alphabet argument: choose documented corpus metadata/sidecar, NEVER infer alphabet from symbols observed. Preserve raw A and L arrays with constants/parameters/seeds/hashes. Later reporting reads these, does not rerun. Bounded-cache correctness must be independently tested via forced spills.

## Annex A, non-confirmatory
Persist increments dA(k,n), mixed finite difference dk/dn with declared n-grid scaling; ridge first k whose dA<0.01 (descriptive cutoff only, no new gate); context occupancy (#distinct, empirical visitation mass in count1 and count<5 contexts, if choosing empirical interpretation state it is not true generator mass); KT estimation cost relative to an explicitly declared reference (not identifiable uniquely from total L); per-predicted-symbol A decomposition Track A only; sample std across5 seeds; raw checkpoint cumulative L; Track B whitespace-aligned availability with declared boundary semantics. These diagnostics require instrumentation before run; aggregate L alone cannot recover all of them. Never alter gates based on annex. No claims of intrinsic reader independence, sufficiency or cognition from surface separation.

## Deliverables
Reusable implementation and ingestion,90 Track A and25 Track B persisted surfaces/spreads,10 numeric prediction checks,3 independent gate checks plus conditional interpretation, gated separability, cost report/extrapolation2^30, all available Annex observables with definitions/limitations. A complete preregistration and provenance manifest must precede every experimental run. If definitions or source adequacy require user input, block BEFORE sampling and ask precise questions, rather than making hidden choices.
