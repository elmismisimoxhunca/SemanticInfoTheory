#!/usr/bin/env python3
"""Independent Track B audit: inventory, hashes, disjointness, and B4/B5
control preservation, including regenerating B4/B5 from the published B1
draws with an independent implementation of the frozen transform spec."""

from __future__ import annotations

import collections
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ref_gen  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ART = Path(os.environ.get("BLOCK01_TRACKB_CORPUS_ROOT", ROOT / "data" / "trackb_corpora"))
CHUNK = 2**23
B4_SEEDS = [601, 602, 603, 604, 605]
B5_SEEDS = [701, 702, 703, 704, 705]

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append({"test": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""),
          flush=True)
    if not ok:
        raise SystemExit(f"AUDIT FAILURE: {name}: {detail}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    # 1. Inventory + hashes vs SHA256SUMS.txt and draw_manifest.json
    sums = {}
    for line in (ART / "SHA256SUMS.txt").read_text().splitlines():
        digest, fname = line.split(None, 1)
        sums[fname.strip()] = digest
    manifest = json.loads((ART / "draw_manifest.json").read_text())
    files = sorted(p.name for p in ART.glob("B*_draw*.bin"))
    record("inventory/25-files", len(files) == 25, f"{len(files)} draw files")
    all_ok = True
    for f in files:
        p = ART / f
        all_ok &= p.stat().st_size == CHUNK
        all_ok &= sha256(p) == sums.get(f)
    record("inventory/sizes+sha256sums", all_ok, "25 x 2^23 bytes, all digests match")
    m_ok = True
    for corpus in ("b1", "b2", "b3", "b4", "b5"):
        for d in range(1, 6):
            entry = manifest["draws"][corpus][f"draw{d}"]
            m_ok &= entry["sha256"] == sums[entry["file"]] and entry["bytes"] == CHUNK
    record("inventory/manifest-consistency", m_ok)

    draws = {}
    for corpus in ("B1", "B2", "B3"):
        draws[corpus] = [(ART / f"{corpus}_draw{d}.bin").read_bytes() for d in range(1, 6)]

    # 2. Disjointness scope: distinct slices, pairwise non-identical
    for corpus in ("B1", "B2", "B3"):
        dset = draws[corpus]
        record(f"disjoint/{corpus}-pairwise-distinct",
               len({hashlib.sha256(x).hexdigest() for x in dset}) == 5,
               "draws are consecutive non-overlapping 2^23 slices by frozen construction "
               "(build_draws_transforms.py: stream[d*CHUNK:(d+1)*CHUNK]); verified pairwise distinct")

    # 3. B4/B5: independent regeneration from published B1 draws
    for d in range(1, 6):
        b1 = draws["B1"][d - 1]
        b4_pub = (ART / f"B4_draw{d}.bin").read_bytes()
        b5_pub = (ART / f"B5_draw{d}.bin").read_bytes()
        b4_mine = ref_gen.b4_transform(b1, B4_SEEDS[d - 1])
        b5_mine = ref_gen.b5_transform(b1, B5_SEEDS[d - 1])
        record(f"transform/B4_draw{d}-regeneration", b4_mine == b4_pub,
               "independent segmentation+SplitMix64 Fisher-Yates reproduces published bytes")
        record(f"transform/B5_draw{d}-regeneration", b5_mine == b5_pub,
               "independent segmentation+continuing-stream word shuffle reproduces published bytes")

        # 4. Control preservation on the published files themselves
        record(f"control/B4_draw{d}-length-multiset",
               len(b4_pub) == CHUNK and collections.Counter(b4_pub) == collections.Counter(b1)
               and b4_pub != b1)
        record(f"control/B5_draw{d}-length-multiset",
               len(b5_pub) == CHUNK and collections.Counter(b5_pub) == collections.Counter(b1)
               and b5_pub != b1)

        # 5. B4 structure: prefix/suffix fixed, interior a unit permutation
        u1, u4 = ref_gen.segment_units(b1), ref_gen.segment_units(b4_pub)
        record(f"control/B4_draw{d}-prefix-suffix-fixed",
               len(u1) == len(u4) and u1[0] == u4[0] and u1[-1] == u4[-1]
               and collections.Counter(u1[1:-1]) == collections.Counter(u4[1:-1]),
               f"{len(u1)} units")

        # 6. B5 structure: the frozen rule segments B1 once and shuffles T tokens
        # within those units; W runs stay fixed so unit byte lengths are preserved.
        # Slice the published B5 at the B1 unit boundaries (re-segmenting B5 itself
        # would be wrong: moved terminator bytes change its raw boundaries).
        offsets = [0]
        for u in u1:
            offsets.append(offsets[-1] + len(u))
        ok = offsets[-1] == len(b5_pub)
        if ok:
            u5 = [b5_pub[offsets[i]:offsets[i + 1]] for i in range(len(u1))]
            for ua, ub in zip(u1, u5):
                ta, tb = tokenize(ua), tokenize(ub)
                if len(ta) != len(tb):
                    ok = False
                    break
                wa = [t for k, t in ta if k == "W"]
                wb = [t for k, t in tb if k == "W"]
                ka = [k for k, _ in ta]
                kb = [k for k, _ in tb]
                if ka != kb or wa != wb:
                    ok = False
                    break
                if collections.Counter(t for k, t in ta if k == "T") != \
                   collections.Counter(t for k, t in tb if k == "T"):
                    ok = False
                    break
        record(f"control/B5_draw{d}-whitespace-fixed", ok,
               "token kind pattern and W bytes identical per unit; T multiset preserved")

    # 7. Seed hygiene: B seeds disjoint from Track A [101..505]
    record("seeds/disjoint-from-track-A",
           not (set(B4_SEEDS) | set(B5_SEEDS)) & {101, 202, 303, 404, 505})

    ok = all(r["ok"] for r in RESULTS)
    print(f"\nTRACK B AUDIT: {sum(r['ok'] for r in RESULTS)}/{len(RESULTS)} checks passed")
    out = Path("/tmp/trackb_audit_results.json")
    out.write_text(json.dumps(RESULTS, indent=1))
    print(f"results: {out}")
    return 0 if ok else 1


def tokenize(unit: bytes):
    tokens = []
    i, n = 0, len(unit)
    while i < n:
        is_ws = unit[i] in ref_gen.WS
        j = i + 1
        while j < n and (unit[j] in ref_gen.WS) == is_ws:
            j += 1
        tokens.append(("W" if is_ws else "T", unit[i:j]))
        i = j
    return tokens


if __name__ == "__main__":
    raise SystemExit(main())
