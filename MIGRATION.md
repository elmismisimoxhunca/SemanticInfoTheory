# Migration state

Date: 2026-09-20

The authoritative working copy moved from DESKTOP-9BKM69O (`host_hkr9k292wz`, former BB environment `env_sveaeeem4z`) to LAPTOP-ADALY (`host_8vdze4nahg`). New execution and analysis must use the laptop checkout of this repository.

## Preserved

- Frozen protocols, manifests, execution supplements, and hashes.
- Exact C++ engine and Python interface.
- Generator, analysis, audit, and Track B ingestion sources.
- Independent audit evidence and published handoffs.
- All 27 complete Track A surface JSON files and their metadata.
- All generated Track A corpora and all 25 Track B draws in the laptop's ignored local data tree.
- Original thread-storage snapshot, logs, and workflow status material.

## Deliberately not migrated as live state

`revb_run/track_a/stores/A_G3_d5_s303.store` was an interrupted approximately 4 GB store. The protocol defines an interrupted store as invalid and non-resumable, so it was excluded. Build directories, Python bytecode, and other reproducible caches were also excluded.

## Exact continuation point

Complete Track A identities:

- G1: 5/5
- G2: 5/5
- G3(2): 5/5
- G3(3): 5/5
- G3(4): 5/5
- G3(5): 2/5

The next frozen identity is `A_G3_d5_s303` (item 28/90). Track B remains 0/25.

The old execution terminal `term_yvxkuqid35` exited after a daemon disconnect. It is not an active computation.

## Integrity rule

Do not edit the frozen protocol, generator definitions, thresholds, predictions, corpus choices, or execution hashes in response to observed results. Finish the registered grid, then compute all ten predictions and the three independent gates from persisted surfaces.
