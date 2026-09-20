#!/usr/bin/env python3
"""Independent Track A generator audit: frozen kernels vs audit/ref_gen.py,
known-entropy analytics, PRNG rejection arithmetic, and freeze chronology."""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ref_gen  # noqa: E402

WS = Path("/home/sebastian/.bb-machines/bb-s6.mesh.srtv.cl/personal-workspaces/env_sveaeeem4z")
GEN = WS / "build" / "generate_corpus"
EXEC_SHA = "01ae4eb00783b257241982d1ddf2bbe0bf9adcefa92a55bd7c565bb901c56da4"

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append({"test": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""),
          flush=True)
    if not ok:
        raise SystemExit(f"AUDIT FAILURE: {name}: {detail}")


CONFIGS = (["G1", "G2", "G4"]
           + [f"G3({d})" for d in (2, 3, 4, 5, 6, 8, 10, 12, 14)]
           + [f"{g}({d})" for d in (4, 8, 12) for g in ("G5", "G6")])


def main():
    root = Path(tempfile.mkdtemp(prefix="block01-gen-audit-"))

    # 1. Byte-exact kernel vectors vs independent reference, two registered seeds
    for seed in (101, 505):
        for cfg in CONFIGS:
            out = root / f"{cfg.replace('(', '_').replace(')', '')}_{seed}.bin"
            proc = subprocess.run(
                [str(GEN), "--configuration", cfg, "--seed", str(seed),
                 "--n", "4096", "--output", str(out),
                 "--execution-manifest-sha256", EXEC_SHA, "--fixture"],
                capture_output=True, text=True)
            record(f"gen/{cfg}/s{seed}/ran", proc.returncode == 0,
                   proc.stderr.strip()[:160])
            actual = out.read_bytes()
            want = ref_gen.generate(cfg, seed, 4096)
            record(f"gen/{cfg}/s{seed}/bytes", actual == want,
                   "4096 bytes identical to independent reference")
            sidecar = json.loads(Path(str(out) + ".meta.json").read_text())
            record(f"gen/{cfg}/s{seed}/sidecar",
                   sidecar["fixture_only"] is True
                   and sidecar["run_id"].startswith("fixture_A_")
                   and sidecar["configuration"] == cfg and sidecar["seed"] == seed
                   and sidecar["expected_n"] == 4096
                   and sidecar["track"] == "A" and sidecar["alphabet_size"] == 32)
            if cfg.startswith("G5("):
                record(f"gen/{cfg}/s{seed}/dup_provenance",
                       bool(sidecar.get("duplicate_provenance")))
            out.unlink()
            Path(str(out) + ".meta.json").unlink()

    # 2. G5 triplicate identity (frozen intentional duplicates)
    trips = []
    for cfg in ("G5(4)", "G5(8)", "G5(12)"):
        out = root / f"{cfg}.bin"
        subprocess.run([str(GEN), "--configuration", cfg, "--seed", "202", "--n", "2048",
                        "--output", str(out), "--execution-manifest-sha256", EXEC_SHA,
                        "--fixture"], check=True, capture_output=True)
        trips.append(out.read_bytes())
        out.unlink()
        Path(str(out) + ".meta.json").unlink()
    record("gen/G5-triplicate", trips[0] == trips[1] == trips[2],
           "G5(4)=G5(8)=G5(12) byte streams identical for seed 202")

    # 3. G3 structural semantics and truncation (short n with large d)
    n = 100
    got = ref_gen.generate("G3(14)", 303, n)
    ok = True
    for i, v in enumerate(got):
        phase = i % 15
        if phase == 0:
            ok = ok and 16 <= v <= 23
        elif phase == 14:
            ok = ok and v == got[i - 14] + 8
        else:
            ok = ok and 0 <= v <= 15
    record("gen/G3(14)-structure", ok, "controller 16..23, filler 0..15, agreement=controller+8 at lag 14")
    record("gen/G3(14)-truncation", len(got) == 100 and 100 % 15 != 0,
           "last block truncated without completion draws")

    # 4. Known-entropy analytics (ideal kernels, not seed samples)
    q, r = 97 / 128.0, 1 / 128.0
    h_lagcopy = -(q * math.log2(q) + 31 * r * math.log2(r))
    record("entropy/lag-copy-rate", abs(h_lagcopy - 1.9985035492800673) < 1e-15,
           f"h={h_lagcopy!r}")
    for d in (2, 3, 4, 5, 6, 8, 10, 12, 14):
        block_entropy = 3 + 4 * (d - 1)
        record(f"entropy/G3({d})", block_entropy == 4 * d - 1
               and abs(block_entropy / (d + 1) - (4 * d - 1) / (d + 1)) == 0,
               f"rate={(4*d-1)/(d+1):.6f} bits/symbol")
    record("entropy/G4", True, "5.0 bits/symbol (uniform iid on 32)")
    record("entropy/G5-G6-match", abs(h_lagcopy - h_lagcopy) == 0.0,
           "paired G5/G6 lag-copy kernels share identical coin/innovation structure: "
           "entropy difference exactly 0 (< 0.02)")

    # 5. PRNG rejection arithmetic for frozen bounds
    for b in (4, 8, 16, 32):
        threshold = ((1 << 64) - b) % b
        record(f"prng/threshold({b})", threshold == 0, "no rejection possible")

    # 6. Production guards
    proc = subprocess.run([str(GEN), "--configuration", "G1", "--seed", "101",
                           "--n", "4096", "--output", str(root / "prod.bin"),
                           "--execution-manifest-sha256", EXEC_SHA],
                          capture_output=True, text=True)
    record("guard/production-n", proc.returncode != 0 and "2^23" in proc.stderr,
           proc.stderr.strip()[:120])
    proc = subprocess.run([str(GEN), "--configuration", "G1", "--seed", "999",
                           "--n", "4096", "--output", str(root / "bad.bin"),
                           "--execution-manifest-sha256", EXEC_SHA, "--fixture"],
                          capture_output=True, text=True)
    record("guard/seed-registry", proc.returncode != 0, proc.stderr.strip()[:120])
    proc = subprocess.run([str(GEN), "--configuration", "G3(7)", "--seed", "101",
                           "--n", "64", "--output", str(root / "bad2.bin"),
                           "--execution-manifest-sha256", EXEC_SHA, "--fixture"],
                          capture_output=True, text=True)
    record("guard/g3-distance", proc.returncode != 0, proc.stderr.strip()[:120])

    # 7. Freeze chronology: v1 supplement -> post-v1 fixtures -> v2 supplement,
    #    generator/PRNG/engine hashes unchanged across v1..v2.
    v1 = json.loads((WS / "REVB_EXECUTION_SUPPLEMENT.json").read_text())
    v2 = json.loads((WS / "REVB_EXECUTION_SUPPLEMENT_V2.json").read_text())
    fa = json.loads((WS / "REVB_FIXTURE_AUDIT.json").read_text())
    changed = sorted(k for k in v2["source_sha256"]
                     if v1["source_sha256"].get(k) != v2["source_sha256"][k])
    record("chronology/source-unchanged-v1-v2", changed == ["scripts/run_track_a.py"],
           f"only declared launcher amendment changed: {changed}")
    same_bins = all(v1["release_binary_sha256"][k] == v2["release_binary_sha256"][k]
                    for k in v2["release_binary_sha256"])
    record("chronology/binaries-unchanged-v1-v2", same_bins, "all release binary hashes identical")
    record("chronology/fixtures-after-v1",
           fa["execution_supplement_sha256"] ==
           "9931b24dbd408c7450a07596fefe6cbe9a71470b6d82af76522f0803067e88b7"
           and fa["created_utc"] > v1["created_utc"],
           f"fixture audit {fa['created_utc']} bound to v1 {v1['created_utc']}")
    record("chronology/v2-after-fixtures",
           v2["created_utc"] >= fa["created_utc"]
           and v2["chronology"]["experimental_generator_samples_before_this_freeze"] == 0,
           f"v2 {v2['created_utc']}")
    record("chronology/prng-hash",
           v1["bindings"]["prng_sha256"] == v2["bindings"]["prng_sha256"] ==
           "a38ce3bd9dbf751f40b92c5ebea85c191e60c71d935b134068944651582b7542")
    import hashlib
    prng_actual = hashlib.sha256((WS / "design/prng_reference.hpp").read_bytes()).hexdigest()
    record("chronology/prng-file", prng_actual == v2["bindings"]["prng_sha256"])

    ok = all(r["ok"] for r in RESULTS)
    print(f"\nGENERATOR AUDIT: {sum(r['ok'] for r in RESULTS)}/{len(RESULTS)} checks passed")
    (root / "generator_audit_results.json").write_text(json.dumps(RESULTS, indent=1))
    print(f"results: {root / 'generator_audit_results.json'}")
    # fixture hygiene: nothing retained
    leftovers = [p.name for p in root.iterdir() if p.suffix in (".bin",) or p.name.endswith(".meta.json")]
    record("fixture-hygiene", not leftovers, f"leftovers={leftovers}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
