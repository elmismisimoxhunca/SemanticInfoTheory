# SemanticInfoTheory agent guidance

Treat `REVB_PROTOCOL.md`, `REVB_FREEZE.json`, and `REVB_EXECUTION_SUPPLEMENT_V3.json` as frozen experimental inputs. Before production work, verify their recorded SHA-256 bindings. Never change kernels, predictions, thresholds, corpus choices, ordering, cache size, or checkpoint grid in response to results.

For execution work:

1. Read `MIGRATION.md` and `REVB_EXECUTION_RESUME_STATUS.md`.
2. Build and run focused tests before scoring.
3. Use `scripts/resume_throttled_orchestrator.py`; run one generate-and-score pipeline at a time in a persistent BB terminal.
4. Reuse a surface only when the script's full validation passes. Delete interrupted `.store` files; they are invalid execution state.
5. Complete only after persisted files show 90/90 Track A and 25/25 Track B surfaces, analysis reports all ten predictions and three gates, and required audits pass.

Keep raw corpora and stores out of Git. Commit code, manifests, sidecars, completed surfaces, audit evidence, and reports. Track A and Track B use different alphabets; never compare their surface values directly. Report partial execution as incomplete rather than as a scientific verdict.
