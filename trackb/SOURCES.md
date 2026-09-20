# Track B Sources — Frozen Provenance (Sonnet-owned)

Frozen: 2026-09-14T05:07:06Z. This document plus `TRACK_B_HANDOFF.md` and
`draw_manifest.json` constitute the Track B provenance freeze required by
`REVB_PROTOCOL.md` before any B sampling/measurement. All hashes below were
computed locally against the actual downloaded bytes, not copied from search
results. No corpus was scored; only acquisition, extraction, and disjoint
byte-draw construction were performed, which `REVB_REQUIREMENTS.md`
explicitly permits before freeze ("corpus metadata research, source
availability/size checks... are allowed before freeze").

## B1 — English Wikipedia prose

- Source: Wikimedia English Wikipedia XML dump, snapshot **20260901**,
  multistream chunk covering page IDs 1–41242 (smallest official chunk,
  sufficient for the required volume; no larger chunk was touched).
- URL: `https://dumps.wikimedia.org/enwiki/20260901/enwiki-20260901-pages-articles-multistream1.xml-p1p41242.bz2`
- Dump status at retrieval: `dumpstatus.json` → `articlesmultistreamdump` = `done`.
- Official SHA1 (from `enwiki-20260901-sha1sums.txt`, matched locally):
  `a97f62049996fd3d3ba03e6fc9593b2695b5b441`
- Locally computed SHA1: `a97f62049996fd3d3ba03e6fc9593b2695b5b441` (match)
- Locally computed SHA256: `d3b45c375e70edf4e155777a42603c774e31cfb5319f26e00ee3d542501fd6c4`
- Compressed size: 299,727,245 bytes.
- License: Wikipedia article text is dual-licensed CC BY-SA 4.0 and GFDL.
- Retrieved: 2026-09-14 (this session).
- **Rejected alternative (documented for audit):** `wikitext-103-raw-v1`
  (Salesforce/Merity, CC BY-SA 3.0, SHA256
  `91c00ae287f0d699e18605c84afc9e45c192bc6b7797ff8837e5474655a33794`,
  locally verified). Rejected because it is Moses-pretokenized (hyphens
  split into ` @-@ `, forced spacing around punctuation), which is not
  verbatim public Wikipedia prose and would distort byte/whitespace-level
  availability statistics. Not used for any draw.

### Extraction (script: `wiki_extract.py`, frozen SHA256 `62758a6bf06cb06ba11154abb16ca25fef457b8586f2d7ab27a04a5e50344636`)

1. Stream-parse the bz2 XML with `xml.etree.ElementTree.iterparse`.
2. Include a page iff `ns == '0'` (main/article namespace), it is **not**
   a redirect, and `<text>` is non-empty. Pages are visited in ascending
   page-ID (dump file) order — no reordering, no selection by content.
3. Convert wikitext to plain prose deterministically, in this exact order:
   strip balanced `{{...}}` templates and `{|...|}` tables (brace-counting,
   not regex, so nesting is handled correctly); remove `<!-- -->` comments;
   remove `<ref>...</ref>` blocks; remove `[[File:...]]`/`[[Image:...]]`
   links; replace `[external-link text]` with `text` and drop bare external
   links; resolve `[[target|display]]` → `display` and `[[target]]` →
   `target`; strip remaining HTML tags; strip `'''`/`''` emphasis markers;
   replace `== Heading ==` markup with the heading text alone; strip
   magic words (`__TOC__` etc.); resolve 6 basic HTML entities
   (`&amp; &lt; &gt; &quot; &nbsp; &apos;`); drop list/table-remnant lines
   whose first non-space character is one of `* # ; : | !`; collapse 3+
   consecutive newlines to exactly 2.
4. Each accepted page's cleaned prose is followed by exactly two `\n`
   (0x0A) bytes as a page separator; pages are concatenated in traversal
   order into one byte stream.
5. **Known limitation (disclosed, not corrected):** inline templates that
   render numeric/currency values (e.g. `{{Inflation}}`) are stripped
   entirely rather than evaluated, leaving occasional small gaps
   (observed: "...or about $ now,..."). This is a standard limitation
   shared by comparable wikitext extractors (e.g. WikiExtractor) and is
   left uncorrected to keep the extraction policy simple and auditable.
6. Processing stopped as soon as the cumulative stream reached
   5×2^23 = 41,943,040 bytes; the stream was then truncated to **exactly**
   that length (truncation may fall inside a page's prose — declared, no
   padding). 2,159 eligible articles were consumed out of 41,242 available
   in the chunk (pages_seen 2,866 including skipped redirects/non-article
   pages); the untouched remainder of the chunk was not processed at all.
- Locally measured pool before truncation: 43,985,214 bytes ≥ required
  41,943,040 (headroom before truncation only; final pool is exactly
  41,943,040 by construction).

## B2 — Source code (single language: C)

- Source: Linux kernel release tarball, version **v6.6**.
- URL: `https://www.kernel.org/pub/linux/kernel/v6.x/linux-6.6.tar.xz`
- Official SHA256 (from `sha256sums.asc`, matched locally):
  `d926a06c63dd8ac7df3f86ee1ffc2ce2a3b81a2d168484e76b5b389aba8e56d0`
- Locally computed SHA256: `d926a06c63dd8ac7df3f86ee1ffc2ce2a3b81a2d168484e76b5b389aba8e56d0` (match)
- Compressed size: 140,064,536 bytes. Published 2023-10-30.
- License: GPL-2.0 (kernel `COPYING`).
- Retrieved: 2026-09-14 (this session).

### Extraction (deterministic, no template stripping needed)

1. Extract the tarball; enumerate every file matching `**/*.c` under the
   `linux-6.6/` root (C language only — no `.h`, `.S`, Kconfig, Makefiles,
   `.dts`, Python/Perl build scripts, or documentation).
2. Sort the relative paths lexicographically (plain Python string sort,
   byte-order on UTF-8 path bytes) — this is the sole ordering rule; file
   contents are otherwise untouched (no comment stripping, no
   normalization).
3. Concatenate raw file bytes in that sorted order, inserting exactly one
   `\n` (0x0A) byte between files (none after the final file) to avoid
   token-gluing across file boundaries.
4. Truncate the concatenation to **exactly** 5×2^23 = 41,943,040 bytes
   (4,435 files were consumed to reach that length; truncation falls
   inside the 4,435th file — declared, no padding). 32,977 `.c` files
   totalling 638,636,912 bytes were available (15.2× the required volume),
   so only a small lexicographic prefix of the kernel tree was used.

## B3 — English CHILDES adult child-directed speech

- Source: TalkBank CHILDES **English-North-American** bulk transcript
  archive (older MOR-tier CHAT format), the only bulk zip advertised on the
  Eng-NA index page.
- URL: `https://talkbank.org/childes/access/Eng-NA/0-Eng-NA-MOR.zip`
- Locally computed SHA256 of the downloaded archive:
  `b7ad9046e5fbab91f5aec3bd15f82c6a98ce9abf19699f8c76d84d7196d3eeb2`
- Archive size: 95,278,057 bytes; contains 7,825 `.cha` transcript files
  plus incidental PDFs/spreadsheets/`.DS_Store` (not used).
- License: TalkBank Ground Rules — content governed by **CC BY-NC-SA 3.0**;
  non-commercial research/teaching/clinical use only; explicitly precludes
  incorporation into commercial products or LLM training. This Track B use
  is experimental/academic KT-availability measurement, not model
  training, and stays within those terms. No child-identifying transcript
  text is reproduced anywhere in this freeze or in any report; only
  aggregate byte counts, hashes, and category labels are disclosed.
- Access: this bulk zip downloaded successfully with **no login/account**
  required (verified directly), despite the top-level CHILDES page stating
  that "materials" access requires a TalkBank account — that requirement
  evidently applies to protected/media corpora, not this public bulk
  transcript archive. Recorded as observed fact, not assumed.
- Retrieved: 2026-09-14 (this session). TalkBank does not date-version this
  bulk zip; the frozen SHA256 above is the sole snapshot identity.

### Adult vs. child-directed eligibility (declared BEFORE extraction)

CHAT `@ID` header lines carry a `role` field (8th `|`-delimited field).
Observed role vocabulary across all 7,825 files: `Adult, Brother,
Caretaker, Child, Father, Friend, Girl, Grandfather, Grandmother,
Investigator, Male, Media, Mother, Narrator, Participant, Playmate,
Relative, Sibling, Sister, Target_Child, Teacher, Teenager, Uncertain,
Unidentified, Visitor`.

**Frozen ADULT_ROLES set** (main-tier lines from these speaker codes are
eligible; all other roles, including `Target_Child`, `Child`, `Sibling`,
`Brother`, `Sister`, `Playmate`, `Girl`, `Friend`, `Teenager`, ambiguous
`Male`/`Participant`/`Narrator`/`Media`/`Uncertain`/`Unidentified`, are
excluded):

```
Mother, Father, Grandmother, Grandfather, Investigator, Teacher, Adult,
Caretaker, Visitor, Relative
```

**Declared limitation (disclosed honestly):** eligibility is determined by
the `@ID` role field and the fact that every CHILDES session is by design
a child-language-acquisition recording — it is **not** verified per
utterance that the addressee is the target child (e.g. an Investigator may
sometimes address another adult in the room). This is the same limitation
any corpus-level CDS/adult-speech split faces without per-utterance
addressee coding, and is reported rather than silently resolved.

### Extraction (script: `clean_chat.py`, frozen SHA256 `408f2404bc0d330379c2539a991c0b33eeeddc5b0f11b470119337c96bfdd950`)

1. Files processed in sorted relative-path order (`sorted(glob(...))`).
2. Per file, parse all `@ID:` lines to build code→role; adult codes = codes
   whose role ∈ ADULT_ROLES above (skip file entirely if none).
3. Main-tier lines `*CODE:\t...` are extracted for adult codes only,
   joined with any following tab-prefixed continuation lines (CHAT's
   multi-line-utterance convention) before cleaning.
4. Deterministic cleaning, applied in this exact order: remove bracketed
   annotation groups `[...]` (retracing, error/postcodes, comments);
   remove parenthetical pause/timing markers `(.)  (..)  (...)  (n.n)`;
   strip disfluency prefixes `&-`, `&+`, `&=` (token text kept, e.g.
   `&-um` → `um`); normalize compound CHAT terminators (`+...`, `+/.`,
   `+//.`, `+"/.`, `+,`) to a plain `.`; collapse runs of space/tab/CR/FF/
   VT to a single ASCII space (0x20); trim leading/trailing whitespace.
   Non-speech placeholders `xxx`/`yyy`/`www` are kept as-is (declared: not
   stripped, since they are genuine transcription-convention tokens for
   unintelligible/untranscribed speech events).
5. Each cleaned utterance is followed by exactly one `\n` (0x0A) byte;
   utterances are concatenated in file order, files in the sorted order
   above.
6. Processing stopped once the cumulative stream reached exactly
   5×2^23 = 41,943,040 bytes (reached inside file 7,014 of 7,825,
   `Eng-NA/Rollins/jw12a.cha`); truncated to exactly that length (declared,
   no padding, no substitution). Full-corpus clean-byte pool before
   truncation, measured for eligibility, was **49,535,765 bytes** — an
   18.1% margin over the 41,943,040-byte requirement — so Eng-NA alone was
   sufficient and no additional English regional corpora (Eng-UK, Eng-AAE)
   were needed or touched.

## Retention decision (disclosed per protocol, not silent)

The raw upstream downloads (enwiki bz2 chunk ~300 MB, kernel tarball
~140 MB, CHILDES zip ~95 MB) and their extracted intermediate trees are
**not** copied into persistent storage. All three are exactly
re-fetchable and re-verifiable from the URLs and hashes recorded above,
and re-running the frozen scripts against those exact bytes reproduces the
`_stream.bin` files and, deterministically, every draw file bit-for-bit.
Persisted instead: the frozen scripts, this document, `TRACK_B_HANDOFF.md`,
`draw_manifest.json`, `SHA256SUMS.txt`, and the 25 final 2^23-byte draw
files (B1–B5 × 5 draws = 200 MiB total) under the thread-storage artifact
directory.
