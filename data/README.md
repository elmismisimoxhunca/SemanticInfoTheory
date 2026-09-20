# Local data

This directory is populated on the authoritative laptop but raw corpora are intentionally ignored by Git.

Expected local files:

- `trackb_corpora/B1_draw1.bin` … `B5_draw5.bin`: 25 files, each exactly `2^23` bytes.
- `trackb_corpora/SHA256SUMS.txt`
- `trackb_corpora/draw_manifest.json`
- `trackb_corpora/SOURCES.md`
- `trackb_corpora/TRACK_B_HANDOFF.md`

Verify before use:

```bash
cd data/trackb_corpora
sha256sum -c SHA256SUMS.txt
```

Track A corpora are generated deterministically under `revb_run/track_a/corpora/` and validated against their sidecars. Neither Track A nor Track B corpus bytes should be committed. The manifests and extraction/transformation code are the public reproducibility record.
