# Annex A — integration status (post-start, non-confirmatory)

User supplied Annex A after workflow execution began. This note DOES NOT amend PROTOCOL.md, its hash, any generators, sample sizes, estimators, seeds, predictions or gate verdicts.

## Scope mismatch requiring clarification
The supplied annex attaches to `block-01-availability-surface-revB.md`, which has not been supplied and is not present in this workspace. The running protocol is the original one-axis Block 01: six generators, five seeds, fixed N=10^7, six predictions, synthetic only. It does not define an exposure checkpoint grid, G3(d) sweep, Track A/B, real-text corpora, predictions7–9, or three Rev B gates. Do not invent those or import real corpora. Parent has requested the missing Rev B from user. Until clarified, preserve original gates and continue original authorized run.

## Safe handling now
All annex outputs are explicitly post-start exploratory/non-confirmatory, with no power to change any gate, justify retuning, or authorize re-running existing corpora. At the existing final N, persist increment arrays A[k]-A[k-1], sample standard deviation over seeds, and original cumulative L arrays (already required). Keep these in a separate annex artifact namespace. Preserve available native checkpoint data if the implementation already emits it; do not call a final-N curve a measured two-axis surface.

Missing-data items must be marked unavailable with reasons, never fabricated or retroactively reconstructed by silently rerunning the reader. Cumulative total L alone cannot recover context occupancies or per-symbol attribution. Exact KT 'learning cost' requires a declared reference/oracle and is not a uniquely defined subtraction from total L. Probability mass over rare contexts needs an explicit choice of empirical visitation mass versus true generator probability. Cross-derivative needs a declared n grid and finite-difference convention (n vs log n cannot be silently interchanged). Ridge's 0.01 is a descriptive cutoff, never a new gate; first-below can occur before a later dependency peak and is not evidence of saturation.

No Outcome1–4 verdict from this annex can be evaluated against absent Rev B predictions. Do not relabel original empirical results using unprovided thresholds. G4 small positive A is not automatically an implementation bug: the original frozen gate is A[k]<0.01, not A[k]<=0, and finite-sample stochastic fluctuations are possible. Likewise sparse-context failure need not be a code bug; independent fixtures separate implementation faults from reader/regime mismatch. Report conflicts, do not silently reconcile them.

## Worker action
Read this note before final reporting. Core worker: mention this note in handoff so subsequent workflow workers read it; no frozen file changes. Reporting worker: add supported final-N annex arrays using already persisted results; list unavailable observables and missing Rev B. Never treat this note as permission to expand scope or tune outcomes.
