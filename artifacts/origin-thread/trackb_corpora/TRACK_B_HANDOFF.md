# Track B Handoff — Sonnet → Core

Status: **Track B provenance freeze complete. 25 corpus draw files produced,
verified, and checksummed. No scoring has been run or is authorized by this
document** (per `REVB_PROTOCOL.md`: "No corpus generation, corpus scoring,
or experimental benchmark is authorized by the completion of these
documents alone"). Corpus draw file *generation* (not scoring) is this
role's explicit deliverable and is complete.

Read `SOURCES.md` first for exact upstream sources, licenses, hashes, and
per-corpus extraction policy. This file freezes the parts that are shared
across corpora: the disjoint-draw algorithm, the B4/B5 transform algorithm,
tokenizer/whitespace policy, and seeds — all fixed **before** any B
measurement, as required.

## Eligibility outcome: no blocker

All three source corpora clear the 5×2^23 = 41,943,040-byte requirement
with the following measured margins under the exact declared policy in
`SOURCES.md` (not an estimate):

| Corpus | Eligible pool measured | Required | Margin |
|---|---|---|---|
| B1 Wikipedia prose | 43,985,214 B (before truncation) | 41,943,040 | 4.9% before exact truncation |
| B2 Linux kernel `.c` | 638,636,912 B | 41,943,040 | 15.2× |
| B3 CHILDES adult CDS | 49,535,765 B | 41,943,040 | 18.1% |

CHILDES (B3), the source flagged in the operating instructions as the most
likely blocker, was checked concretely: it is public (no login required for
this bulk archive), and the declared adult-role extraction policy yields
enough clean bytes with an 18.1% margin from the Eng-NA region alone — no
substitute/padding/duplicate draws were needed and no child utterances were
included to inflate volume. If a future re-run of the frozen script against
a re-verified copy of the same hashed zip yields fewer bytes than expected,
that is a **concrete blocker to report immediately**, not a cue to loosen
ADULT_ROLES or draw from additional regions after the fact.

## Disjoint draw algorithm (B1, B2, B3 — identical rule)

1. Build one deterministic ordered byte stream per corpus per the
   extraction policy in `SOURCES.md` (fixed traversal order, no
   content-based selection).
2. Stop building the stream as soon as its length ≥ 5×2^23 bytes, then
   truncate to **exactly** 5×2^23 = 41,943,040 bytes (truncation may fall
   mid-unit; declared, no padding, no resampling).
3. Draw `d` (1-indexed, 1..5) = bytes `[(d-1)×2^23, d×2^23)` of that exact
   41,943,040-byte stream. This is a deterministic partition, not a random
   sample — disjointness is by construction, requiring no RNG.
4. Draw order 1..5 for aggregation purposes is this construction order
   (matches `REVB_PROTOCOL.md`'s "registered ... B draw order 1..5").

This rule is identical for B1, B2, and B3; no corpus received special
treatment in how draws were carved from its stream.

## Tokenizer / whitespace policy (for B4/B5 segmentation only)

Reuses the same ASCII whitespace-mask byte set already frozen for the core
engine's Annex A instrumentation, for consistency: `W = {9, 10, 11, 12, 13,
32}` (tab, LF, VT, FF, CR, space). No Unicode-aware whitespace or
tokenization is used; segmentation operates purely on raw bytes, which is
safe for UTF-8 because multi-byte continuation/lead bytes are always ≥0x80
and therefore never members of `W` — a "word" run (see below) can never be
split inside a multi-byte character.

**Sentence/unit segmentation** (`segment.py`, frozen SHA256
`b12a9323fe0a6917376c731933b8778334f8b99288f75789bd9581cc3c41e3e2`):
scan the draw's bytes; whenever a byte in `{0x2E '.', 0x21 '!', 0x3F '?'}`
is found, its unit boundary is placed immediately after that byte plus the
maximal immediately-following run of `W` bytes (i.e. the terminator "owns"
its trailing whitespace). The concatenation of all units reconstructs the
draw exactly. The first unit (before the first terminator, if any) and the
last unit (after the last terminator's trailing whitespace, if any) are
called the **prefix** and **suffix** — they are typically incomplete
sentences because draws 2–5 start/end at arbitrary interior byte offsets of
the source stream; this is a declared artifact of fixed-size byte-window
draws, not a data quality issue.

**Word segmentation** (within a unit): a unit is split into a strictly
alternating sequence of whitespace-mask runs (`W`) and non-whitespace runs
(`T`, "words"), in original order, via the same byte-level rule.

## B4 — sentence order shuffled (derived from the matching B1 draw)

For B1 draw `d`, segment into `[prefix, sentence_1, ..., sentence_k,
suffix]`. If there are ≤2 units total (no interior sentence to shuffle),
B4 draw `d` equals B1 draw `d` unchanged (declared no-op, not an error).
Otherwise, apply a Fisher–Yates shuffle to the interior `[sentence_1, ...,
sentence_k]` list only; `prefix` and `suffix` stay fixed in place at the
start and end. Concatenating `prefix + shuffled interior + suffix`
reproduces the original byte length and byte multiset exactly by
construction (units are reordered wholesale, never edited).

## B5 — word order shuffled within sentences (derived from the matching B1 draw)

For B1 draw `d`, use the **same** unit segmentation as B4 (prefix,
sentences, suffix — all units, none excluded this time). Within each unit
independently, in unit order, apply Fisher–Yates to only the `T` ("word")
tokens of that unit; `W` (whitespace) tokens keep their original bytes and
sequence positions untouched. Reassembling all units in original order
reproduces the original byte length and byte multiset exactly.

## Shuffle RNG (reused Track A component, not reinvented)

Both B4 and B5 reuse the frozen `design/prng_reference.hpp` SplitMix64
generator verbatim (ported to Python bit-for-bit in `splitmix64.py`, frozen
SHA256 `e0287cfaba9b36a7ad7bd73aa1732a64a334de94a014539f40c175aef7329711`):
64-bit unsigned state, `next_u64()` exactly as specified, and a generic
`uniform(bound)` using the same rejection-sampling method as the frozen
reference (generalized to arbitrary `bound`, since Fisher–Yates needs
`uniform(i+1)` for shrinking `i`, not just the fixed `{4,8,16,32}` bounds
used by Track A generators).

- **B4 Fisher–Yates**: one fresh `SplitMix64` instance per draw, seeded
  once; standard for `i = len-1 downto 1: j = uniform(i+1); swap(a[i],
  a[j])` applied to the interior sentence list.
- **B5 Fisher–Yates**: one fresh `SplitMix64` instance per draw, seeded
  once, and **not** reset between units — the same continuing stream is
  consumed unit-by-unit in unit order, each unit's word list shuffled with
  the same algorithm.

**Frozen seeds** (declared now, disjoint from the Track A seed list
`[101,202,303,404,505]` to avoid any cross-track seed reuse ambiguity):

| Draw | B4 seed | B5 seed |
|---|---|---|
| 1 | 601 | 701 |
| 2 | 602 | 702 |
| 3 | 603 | 703 |
| 4 | 604 | 704 |
| 5 | 605 | 705 |

## Verification performed (this session, not sampling)

For every one of the 5 B1 draws: `len(B4) == len(B1) == 2^23`,
`len(B5) == len(B1) == 2^23`, `Counter(B4) == Counter(B1)` (byte multiset
equality), `Counter(B5) == Counter(B1)`, and `B4 != B1`, `B5 != B1` (the
shuffle is not an accidental no-op). All assertions passed
(`build_draws_transforms.py` raises on any violation; it did not raise).

## Files delivered

**Source (this workspace, `trackb/`):** `wiki_extract.py`, `clean_chat.py`,
`splitmix64.py`, `segment.py`, `build_draws_transforms.py`, `SOURCES.md`,
`TRACK_B_HANDOFF.md`.

**Final artifacts (thread-storage, `trackb_corpora/`):**
`B{1,2,3,4,5}_draw{1..5}.bin` (25 files × 8,388,608 bytes = 200 MiB total),
`draw_manifest.json` (per-file SHA256, seeds, source draw for B4/B5),
`SHA256SUMS.txt`, plus copies of `SOURCES.md` / `TRACK_B_HANDOFF.md`.

## Runnable ingestion commands (full reproduction from scratch)

```bash
# B1 — Wikipedia
curl -sO https://dumps.wikimedia.org/enwiki/20260901/enwiki-20260901-pages-articles-multistream1.xml-p1p41242.bz2
sha1sum enwiki-20260901-pages-articles-multistream1.xml-p1p41242.bz2  # expect a97f62049996fd3d3ba03e6fc9593b2695b5b441
python3 wiki_extract.py enwiki-20260901-pages-articles-multistream1.xml-p1p41242.bz2 wiki_prose_full.txt $((5*2**23+2000000))
head -c $((5*2**23)) wiki_prose_full.txt > b1_stream.bin

# B2 — Linux kernel C sources
curl -sO https://www.kernel.org/pub/linux/kernel/v6.x/linux-6.6.tar.xz
sha256sum linux-6.6.tar.xz  # expect d926a06c63dd8ac7df3f86ee1ffc2ce2a3b81a2d168484e76b5b389aba8e56d0
tar xf linux-6.6.tar.xz
# see build_draws_transforms.py-adjacent snippet: sort **/*.c by relative path,
# concatenate with single \n separators, truncate to exactly 5*2^23 bytes -> b2_stream.bin

# B3 — CHILDES Eng-NA adult tiers
curl -sO https://talkbank.org/childes/access/Eng-NA/0-Eng-NA-MOR.zip
sha256sum 0-Eng-NA-MOR.zip  # expect b7ad9046e5fbab91f5aec3bd15f82c6a98ce9abf19699f8c76d84d7196d3eeb2
unzip -q 0-Eng-NA-MOR.zip -d eng-na-extracted
python3 -c "
import glob
from clean_chat import extract_file
files = sorted(glob.glob('eng-na-extracted/**/*.cha', recursive=True))
target = 5*2**23
with open('b3_stream.bin','wb') as out:
    total = 0
    for fp in files:
        for u in extract_file(fp):
            chunk = u.encode('utf-8') + b'\n'
            if total + len(chunk) > target:
                out.write(chunk[:target-total]); raise SystemExit
            out.write(chunk); total += len(chunk)
"

# Draws + B4/B5 transforms (all three streams must be exactly 5*2^23 bytes first)
python3 build_draws_transforms.py
sha256sum -c SHA256SUMS.txt   # verify byte-identical reproduction
```

## Open items for Core / execution owner (not blockers, just handoff notes)

- These 25 files are raw byte corpora, not yet bound to an
  `execution_manifest_sha256` or per-corpus `.meta.json` sidecar
  (`block01-corpus-v1` schema) — `REVB_PROTOCOL.md` assigns sidecar
  binding to whoever runs the actual scoring pass, since it must include
  `execution_manifest_sha256`, which does not exist yet. This role does
  not fabricate that binding preemptively.
- No KT scoring, no availability surfaces, no Annex instrumentation has
  been computed for any of these 25 files. `samples_generated` in the
  sense of scored surfaces remains 0; corpus **draw files** (inputs to
  future scoring) are what this handoff delivers.
