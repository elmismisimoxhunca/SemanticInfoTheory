#!/usr/bin/env python3
"""Independent engine audit driver (Rev B). Runs the frozen release CLI on
self-made fixtures and compares against audit/ref_kt.py bit-for-bit."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ref_kt import reference_surface  # noqa: E402

WS = Path(os.environ.get("BLOCK01_WORKSPACE", Path(__file__).resolve().parents[1]))
KT_STREAM = WS / "build" / "kt_stream"
PROTOCOL_SHA = "9180c10578a1c2f15f96e97ff93893e5e4889dad417531d50b8bc97c81fd04b2"
FREEZE_SHA = "ec2a97849acc0d93c71d2f8af9744808950e748d6056d5e71bef764d3ae63036"
EXEC_SHA = "01ae4eb00783b257241982d1ddf2bbe0bf9adcefa92a55bd7c565bb901c56da4"

RESULTS: list[dict] = []


def record(name: str, ok: bool, detail: str = ""):
    RESULTS.append({"test": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""), flush=True)
    if not ok:
        raise SystemExit(f"AUDIT FAILURE: {name}: {detail}")


def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_fixture(root: Path, name: str, data: bytes, alphabet: int,
                  overrides: dict | None = None) -> Path:
    corpus = root / f"{name}.bin"
    corpus.write_bytes(data)
    sidecar = {
        "schema": "block01-corpus-v1",
        "track": "A" if alphabet == 32 else "B",
        "alphabet_size": alphabet,
        "expected_n": len(data),
        "run_id": f"audit_{name}",
        "corpus_sha256": sha256_file(corpus),
        "protocol_sha256": PROTOCOL_SHA,
        "freeze_sha256": FREEZE_SHA,
        "execution_manifest_sha256": EXEC_SHA,
    }
    if alphabet == 32:
        sidecar["configuration"] = "audit_fixture"
        sidecar["seed"] = 0
    else:
        sidecar["source_manifest_sha256"] = "ab" * 32
        sidecar["corpus"] = "audit"
        sidecar["draw_id"] = 1
        sidecar["transformation_provenance"] = "audit fixture"
    if overrides:
        sidecar.update(overrides)
    Path(str(corpus) + ".meta.json").write_text(json.dumps(sidecar, indent=1))
    return corpus


def run_cli(corpus: Path, root: Path, tag: str, k_max: int, checkpoints: list[int],
            cache_pages: int | None = None, expect_fail: bool = False) -> dict | None:
    out = root / f"{corpus.stem}.{tag}.json"
    store = root / f"{corpus.stem}.{tag}.store"
    cmd = [str(KT_STREAM), "--corpus", str(corpus), "--output", str(out),
           "--store", str(store), "--k-max", str(k_max),
           "--checkpoints", ",".join(str(c) for c in checkpoints)]
    if cache_pages is not None:
        cmd += ["--cache-pages", str(cache_pages)]
    else:
        cmd += ["--cache-mib", "2048"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if expect_fail:
        record(f"{corpus.stem}/{tag} rejected", proc.returncode != 0,
               proc.stderr.strip()[:160])
        return None
    if proc.returncode != 0:
        raise SystemExit(f"CLI failed for {corpus}: {proc.stderr}")
    return json.loads(out.read_text())


def bits(x: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", float(x)))[0]


def hexbits(x: float) -> str:
    return f"0x{bits(x):016x}"


def compare_surface(name: str, result: dict, ref: list[dict], alphabet: int, k_max: int):
    record(f"{name}/schema", result["schema"] == "block01-availability-surface-v1"
           and result["status"] == "complete" and result["alphabet_size"] == alphabet)
    record(f"{name}/checkpoint_count", len(result["checkpoints"]) == len(ref))
    for idx, (ck, exp) in enumerate(zip(result["checkpoints"], ref)):
        tag = f"{name}/ck{idx}@n={exp['n']}"
        if ck["n"] != exp["n"]:
            record(tag + "/n", False, f"{ck['n']} != {exp['n']}")
        for k in range(k_max + 1):
            if ck["L_bits"][k] != hexbits(exp["L"][k]):
                record(tag + f"/L[{k}]", False,
                       f"{ck['L_bits'][k]} != {hexbits(exp['L'][k])}")
            want_a = 0.0 if k == 0 else (exp["L"][0] - exp["L"][k]) / float(exp["n"])
            if ck["A_bits"][k] != hexbits(want_a):
                record(tag + f"/A[{k}]", False,
                       f"{ck['A_bits'][k]} != {hexbits(want_a)}")
            if ck["L_ML_bits"][k] != hexbits(exp["L_ML"][k]):
                record(tag + f"/L_ML[{k}]", False,
                       f"{ck['L_ML_bits'][k]} != {hexbits(exp['L_ML'][k])}")
            eo, ao = exp["occupancy"][k], ck["occupancy"][k]
            for field in ("visits", "distinct_contexts", "singleton_contexts",
                          "contexts_total_lt5", "singleton_visitation_numerator",
                          "rare_visitation_numerator"):
                if ao[field] != eo[field]:
                    record(tag + f"/occupancy[{k}].{field}", False,
                           f"{ao[field]} != {eo[field]}")
            exp_visits = max(exp["n"] - k, 0)
            if ao["visits"] != exp_visits:
                record(tag + f"/occupancy[{k}].E_k", False,
                       f"{ao['visits']} != {exp_visits}")
            if ao["visits"] == 0:
                if ao["singleton_visitation_mass"] is not None:
                    record(tag + f"/occupancy[{k}].mass_null", False)
            else:
                sm = eo["singleton_visitation_numerator"] / eo["visits"]
                rm = eo["rare_visitation_numerator"] / eo["visits"]
                if bits(ao["singleton_visitation_mass"]) != bits(sm):
                    record(tag + f"/occupancy[{k}].singleton_mass", False)
                if bits(ao["rare_visitation_mass"]) != bits(rm):
                    record(tag + f"/occupancy[{k}].rare_mass", False)
        if alphabet == 32:
            attr = ck["predicted_symbol_attribution"]
            if attr["counts"] != exp["sym_counts"]:
                record(tag + "/attr_counts", False)
            for i, v in enumerate(exp["sym_losses"]):
                if bits(attr["L_order_major"][i]) != bits(v):
                    record(tag + f"/attr_L[{i}]", False)
            for k in range(k_max + 1):
                for a in range(32):
                    want = (exp["sym_losses"][a] - exp["sym_losses"][k * 32 + a]) / exp["n"]
                    got = attr["A_contribution_order_major"][k * 32 + a]
                    if bits(got) != bits(want):
                        record(tag + f"/attr_A[{k}][{a}]", False)
                csum = 0.0
                for a in range(32):
                    csum += (exp["sym_losses"][a] - exp["sym_losses"][k * 32 + a]) / exp["n"]
                want_resid = csum - (0.0 if k == 0 else (exp["L"][0] - exp["L"][k]) / exp["n"])
                if bits(attr["contribution_sum_residual"][k]) != bits(want_resid):
                    record(tag + f"/attr_residual[{k}]", False)
        else:
            attr = ck["whitespace_attribution"]
            if attr["counts"] != exp["ws_counts"]:
                record(tag + "/ws_counts", False)
            for i, v in enumerate(exp["ws_losses"]):
                if bits(attr["L_order_major"][i]) != bits(v):
                    record(tag + f"/ws_L[{i}]", False)
            if not exp["has_aligned"]:
                if attr["aligned_offset"] is not None or attr["aligned_A"] is not None:
                    record(tag + "/aligned_null", False)
            else:
                if attr["aligned_offset"] != exp["aligned_offset"]:
                    record(tag + "/aligned_offset", False,
                           f"{attr['aligned_offset']} != {exp['aligned_offset']}")
                for k in range(k_max + 1):
                    if bits(attr["aligned_L"][k]) != bits(exp["aligned_losses"][k]):
                        record(tag + f"/aligned_L[{k}]", False)
                    want = 0.0 if k == 0 else (
                        (exp["aligned_losses"][0] - exp["aligned_losses"][k])
                        / float(exp["aligned_offset"]))
                    if bits(attr["aligned_A"][k]) != bits(want):
                        record(tag + f"/aligned_A[{k}]", False)
    record(name, True, f"{len(ref)} checkpoints x {k_max + 1} orders bit-exact "
           f"(L, A, L_ML, occupancy, attribution)")


def xorshift_fixture(size: int, alphabet: int, seed: int = 0x123456789ABCDEF0) -> bytes:
    state = seed
    out = bytearray(size)
    for i in range(size):
        state ^= state >> 12
        state ^= (state << 25) & 0xFFFFFFFFFFFFFFFF
        state ^= state >> 27
        out[i] = (state * 0x2545F4914F6CDD1D & 0xFFFFFFFFFFFFFFFF) % alphabet
    return bytes(out)


def main():
    root = Path(tempfile.mkdtemp(prefix="block01-audit-"))
    print(f"audit scratch: {root}", flush=True)

    # 1. Tiny hand fixtures, both alphabets: startup + all orders + checkpoints
    a_tiny = bytes([0, 0, 1, 31, 1, 0, 31, 31, 2, 2, 2, 0])
    ck_a = [1, 2, 3, 5, 12]
    c = write_fixture(root, "a-tiny", a_tiny, 32)
    res = run_cli(c, root, "run", 16, ck_a, cache_pages=2)
    compare_surface("a-tiny", res, reference_surface(a_tiny, 32, 16, ck_a), 32, 16)

    b_tiny = bytes(list(range(256)) + [32, 65, 66, 9, 255, 10, 67, 32, 32, 13, 65])
    ck_b = [1, 2, 17, 32, 256, len(b_tiny)]
    c = write_fixture(root, "b-tiny", b_tiny, 256)
    res = run_cli(c, root, "run", 16, ck_b, cache_pages=2)
    compare_surface("b-tiny", res, reference_surface(b_tiny, 256, 16, ck_b), 256, 16)

    # 1b. Startup-focused: n smaller than k_max in every regime
    a_n1 = bytes([7])
    c = write_fixture(root, "a-n1", a_n1, 32)
    res = run_cli(c, root, "run", 16, [1], cache_pages=1)
    compare_surface("a-n1", res, reference_surface(a_n1, 32, 16, [1]), 32, 16)
    ck = res["checkpoints"][0]
    record("a-n1/startup-exact",
           all(ck["L"][k] == 5.0 for k in range(17)) and ck["A"] == [0.0] * 17,
           "L[k]=5.0 for all k at n=1")

    # 2. Chunk-boundary fixture: n straddles 65536, checkpoints on the boundary
    a_big = xorshift_fixture(70000, 32)
    ck_big = [1, 63, 4096, 65535, 65536, 65537, 70000]
    c = write_fixture(root, "a-chunk", a_big, 32)
    res_small = run_cli(c, root, "p3", 16, ck_big, cache_pages=3)
    res_large = run_cli(c, root, "p512", 16, ck_big, cache_pages=512)
    ref_big = reference_surface(a_big, 32, 16, ck_big)
    compare_surface("a-chunk", res_small, ref_big, 32, 16)
    record("a-chunk/spilled", res_small["metrics"]["page_evictions"] > 0,
           f"evictions={res_small['metrics']['page_evictions']}")
    same = all(a["L_bits"] == b["L_bits"] and a["A_bits"] == b["A_bits"]
               for a, b in zip(res_small["checkpoints"], res_large["checkpoints"]))
    record("a-chunk/spill-equivalence", same, "3-page vs 512-page cache bit-identical")
    record("a-chunk/read-calls",
           res_small["metrics"]["input_read_calls"] == math.ceil(len(a_big) / 65536),
           f"read_calls={res_small['metrics']['input_read_calls']}")

    # 3. Track B large spill fixture (denser tail: 8-bit digits, 15 records/page)
    b_big = xorshift_fixture(50000, 256, seed=0xABCDEF0123456789)
    ck_bbig = [100, 4096, 32768, 50000]
    c = write_fixture(root, "b-chunk", b_big, 256)
    res_b_small = run_cli(c, root, "p2", 16, ck_bbig, cache_pages=2)
    res_b_large = run_cli(c, root, "p256", 16, ck_bbig, cache_pages=256)
    compare_surface("b-chunk", res_b_small, reference_surface(b_big, 256, 16, ck_bbig), 256, 16)
    record("b-chunk/spilled", res_b_small["metrics"]["page_evictions"] > 0,
           f"evictions={res_b_small['metrics']['page_evictions']}")
    same = all(a["L_bits"] == b["L_bits"] for a, b in
               zip(res_b_small["checkpoints"], res_b_large["checkpoints"]))
    record("b-chunk/spill-equivalence", same, "2-page vs 256-page cache bit-identical")

    # 4. 128-bit contexts: histories that differ only above bit 64 (S=256).
    # Two 16-byte contexts with identical most-recent 8 bytes (low 64 bits)
    # but different older 8 bytes, each with a distinct continuation bias.
    suffix = bytes([200, 201, 202, 203, 204, 205, 206, 207])
    older1 = bytes([1, 2, 3, 4, 5, 6, 7, 8])
    older2 = bytes([8, 7, 6, 5, 4, 3, 2, 1])
    seq = bytearray()
    for rep in range(40):
        seq += older1 + suffix + bytes([11])
        seq += older2 + suffix + bytes([250, 250])
    b_128 = bytes(seq)
    ck_128 = [len(b_128)]
    c = write_fixture(root, "b-128bit", b_128, 256)
    res = run_cli(c, root, "run", 16, ck_128, cache_pages=4)
    compare_surface("b-128bit", res, reference_surface(b_128, 256, 16, ck_128), 256, 16)
    # If the engine truncated contexts to 64 bits, order-16 rows for the two
    # families would merge and L[16] would differ from the exact reference;
    # the bit-exact comparison above is the proof. Additional direct probe:
    ref = reference_surface(b_128, 256, 16, ck_128)[0]
    merged = reference_surface(b_128, 256, 8, ck_128)[0]  # 64-bit truncation analogue
    record("b-128bit/discriminates", ref["L"][16] != merged["L"][8],
           "depth-16 loss differs from 64-bit-truncated analogue as designed")

    # 5. Checkpoint order/validation rejections through the CLI
    c = write_fixture(root, "a-validate", xorshift_fixture(128, 32), 32)
    run_cli(c, root, "badorder", 4, [64, 32], cache_pages=2, expect_fail=True)
    run_cli(c, root, "beyondn", 4, [256], cache_pages=2, expect_fail=True)
    run_cli(c, root, "unreached", 4, [64, 96], cache_pages=2, expect_fail=False)
    run_cli(c, root, "dup", 4, [64, 64], cache_pages=2, expect_fail=True)
    run_cli(c, root, "zero", 4, [0, 64], cache_pages=2, expect_fail=True)

    # 6. Metadata / alphabet dispatch rejections
    c = write_fixture(root, "a-badbyte", bytes([0, 1, 32, 2]), 32)  # byte 32 invalid for A
    run_cli(c, root, "run", 2, [4], cache_pages=1, expect_fail=True)
    c = write_fixture(root, "b-mismatch", bytes([0, 1, 2, 3]), 256,
                      overrides={"alphabet_size": 32})  # track B with alphabet 32
    run_cli(c, root, "run", 2, [4], cache_pages=1, expect_fail=True)
    c = write_fixture(root, "a-badhash", bytes([0, 1, 2, 3]), 32,
                      overrides={"corpus_sha256": "00" * 32})
    run_cli(c, root, "run", 2, [4], cache_pages=1, expect_fail=True)
    c = write_fixture(root, "a-extrabyte", bytes([0, 1, 2, 3]), 32,
                      overrides={"expected_n": 3})
    run_cli(c, root, "run", 2, [3], cache_pages=1, expect_fail=True)
    c = write_fixture(root, "a-short", bytes([0, 1, 2]), 32, overrides={"expected_n": 4})
    run_cli(c, root, "run", 2, [4], cache_pages=1, expect_fail=True)
    # alphabet inferred from bytes would accept this; sidecar must drive dispatch:
    c = write_fixture(root, "a-looks-b", bytes([0, 1, 2, 3, 250, 251]), 32)
    run_cli(c, root, "run", 2, [6], cache_pages=1, expect_fail=True)

    # 7. No-whitespace Track B fixture: aligned values must be null
    b_nowhitespace = bytes([65, 66, 67, 200, 201, 202])
    c = write_fixture(root, "b-nows", b_nowhitespace, 256)
    res = run_cli(c, root, "run", 3, [6], cache_pages=1)
    compare_surface("b-nows", res, reference_surface(b_nowhitespace, 256, 3, [6]), 256, 3)

    # 8. Global bijection invariance (separability theorem spot check)
    base = xorshift_fixture(2048, 32)
    permuted = bytes((v + 7) % 32 for v in base)
    ckp = [512, 2048]
    c1 = write_fixture(root, "bij-base", base, 32)
    c2 = write_fixture(root, "bij-perm", permuted, 32)
    r1 = run_cli(c1, root, "run", 16, ckp, cache_pages=8)
    r2 = run_cli(c2, root, "run", 16, ckp, cache_pages=8)
    same = all(a["L_bits"] == b["L_bits"] for a, b in
               zip(r1["checkpoints"], r2["checkpoints"]))
    record("bijection-invariance", same,
           "symmetric KT bit-identical under global +7 mod 32 bijection")

    # 9. Python facade smoke check
    env = dict(os.environ)
    env["BLOCK01_KT_STREAM"] = str(KT_STREAM)
    env["PYTHONPATH"] = str(WS)
    code = (
        "from block01 import availability\n"
        f"r = availability({str(c1)!r}, 16, [512, 2048])\n"
        "assert r['schema'] == 'block01-availability-surface-v1'\n"
        "assert r['checkpoint_count'] == 2 and r['alphabet_size'] == 32\n"
        "assert r['checkpoints'][1]['L_bits'] == " + repr(r1["checkpoints"][1]["L_bits"]) + "\n"
        "print('python-api ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    record("python-api", proc.returncode == 0 and "python-api ok" in proc.stdout,
           proc.stderr.strip()[:160])

    ok = all(r["ok"] for r in RESULTS)
    print(f"\nENGINE AUDIT: {sum(r['ok'] for r in RESULTS)}/{len(RESULTS)} checks passed")
    (root / "engine_audit_results.json").write_text(json.dumps(RESULTS, indent=1))
    print(f"results: {root / 'engine_audit_results.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
