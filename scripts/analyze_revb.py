#!/usr/bin/env python3
"""Analyze only persisted Rev B surface JSON; never regenerate or rescore corpora."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path
import shutil
import statistics
from typing import Any

CHECKPOINTS = [2**power for power in range(12, 24)]
ORDERS = list(range(17))
SEEDS = [101, 202, 303, 404, 505]
B_CORPORA = ["B1", "B2", "B3", "B4", "B5"]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_surface(path: Path, expected_run_id: str, track: str, execution_hash: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = read_json(path)
    expected_alphabet = 32 if track == "A" else 256
    checks = [
        (value.get("schema") == "block01-availability-surface-v1", "schema"),
        (value.get("status") == "complete", "status"),
        (value.get("metadata", {}).get("run_id") == expected_run_id, "run_id"),
        (value.get("metadata", {}).get("track") == track, "track"),
        (value.get("metadata", {}).get("execution_manifest_sha256") == execution_hash, "execution manifest"),
        (value.get("N") == 2**23, "N"),
        (value.get("alphabet_size") == expected_alphabet, "alphabet"),
        (value.get("k_max") == 16, "k_max"),
        (value.get("checkpoint_count") == 12, "checkpoint count"),
        ([cp.get("n") for cp in value.get("checkpoints", [])] == CHECKPOINTS, "checkpoint grid"),
    ]
    failed = [name for passed, name in checks if not passed]
    if failed:
        raise RuntimeError(f"invalid persisted surface {path}: {', '.join(failed)}")
    for cp in value["checkpoints"]:
        for name in ("L", "A", "L_ML", "KT_minus_ML", "KT_minus_ML_per_symbol", "occupancy"):
            if len(cp[name]) != 17:
                raise RuntimeError(f"invalid {name} length in {path} at n={cp['n']}")
    return value


def grid(result: dict[str, Any], field: str = "A") -> list[list[float]]:
    return [[float(value) for value in checkpoint[field]] for checkpoint in result["checkpoints"]]


def mean_grid(results: list[dict[str, Any]], field: str = "A") -> list[list[float]]:
    return [
        [sum(grid(result, field)[j][k] for result in results) / len(results) for k in ORDERS]
        for j in range(len(CHECKPOINTS))
    ]


def sample_std_grid(results: list[dict[str, Any]], mean: list[list[float]], field: str = "A") -> list[list[float]]:
    if len(results) < 2:
        return [[0.0 for _ in ORDERS] for _ in CHECKPOINTS]
    return [
        [
            math.sqrt(sum((grid(result, field)[j][k] - mean[j][k]) ** 2 for result in results) / (len(results) - 1))
            for k in ORDERS
        ]
        for j in range(len(CHECKPOINTS))
    ]


def increments(surface: list[list[float]]) -> list[list[float]]:
    return [[row[k] - row[k - 1] for k in range(1, 17)] for row in surface]


def mixed_n(increment_grid: list[list[float]]) -> list[list[float]]:
    return [
        [
            (increment_grid[j + 1][k] - increment_grid[j][k]) / (CHECKPOINTS[j + 1] - CHECKPOINTS[j])
            for k in range(16)
        ]
        for j in range(11)
    ]


def ridge(increment_grid: list[list[float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for j, values in enumerate(increment_grid):
        found = next((k for k, value in enumerate(values, start=1) if value < 0.01), None)
        rows.append({
            "n": CHECKPOINTS[j],
            "k": found if found is not None else 17,
            "right_censored_above_16": found is None,
        })
    return rows


def linf(left: list[list[float]], right: list[list[float]]) -> dict[str, Any]:
    best = -1.0
    best_j = 0
    best_k = 0
    for j in range(len(left)):
        for k in ORDERS:
            value = abs(left[j][k] - right[j][k])
            if value > best:
                best, best_j, best_k = value, j, k
    return {"value": best, "n": CHECKPOINTS[best_j], "k": best_k}


def full_curve_distance(left: list[list[float]], right: list[list[float]]) -> dict[str, Any]:
    j = len(CHECKPOINTS) - 1
    values = [abs(left[j][k] - right[j][k]) for k in ORDERS]
    best_k = max(range(17), key=lambda k: values[k])
    return {"value": values[best_k], "n": CHECKPOINTS[-1], "k": best_k}


def predicate(status: str, passed: bool | None, **witness: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"status": status}
    if passed is not None:
        value["passed"] = passed
    value.update(witness)
    return value


def metric_mean(results: list[dict[str, Any]], checkpoint_index: int, name: str) -> float:
    values = [float(result["checkpoints"][checkpoint_index]["metrics"][name]) for result in results]
    return sum(values) / len(values)


def summarize_cost(track_results: list[dict[str, Any]], alphabet: int) -> dict[str, Any]:
    if not track_results:
        return {"status": "incomplete", "alphabet_size": alphabet, "completed_surfaces": 0}
    metric_names = [
        "wall_seconds", "process_cpu_seconds", "peak_rss_kib", "nodes", "page_hits", "page_misses",
        "page_reads", "page_writes", "bytes_read", "bytes_written", "logical_store_bytes",
        "allocated_store_bytes", "kt_log2_calls", "annex_log2_calls", "logical_scores", "logical_updates",
    ]
    rows = []
    for j, n in enumerate(CHECKPOINTS):
        row: dict[str, Any] = {"n": n}
        for name in metric_names:
            row[f"mean_{name}"] = metric_mean(track_results, j, name)
        row["mean_page_reads_per_symbol"] = row["mean_page_reads"] / n
        row["mean_page_writes_per_symbol"] = row["mean_page_writes"] / n
        row["mean_allocated_store_bytes_per_symbol"] = row["mean_allocated_store_bytes"] / n
        rows.append(row)
    full_metrics = [result["metrics"] for result in track_results]
    median_wall = statistics.median(float(m["wall_seconds"]) for m in full_metrics)
    median_reads_per_symbol = statistics.median(float(m["page_reads"]) / (2**23) for m in full_metrics)
    median_writes_per_symbol = statistics.median(float(m["page_writes"]) / (2**23) for m in full_metrics)
    median_allocated_per_symbol = statistics.median(float(m["allocated_store_bytes"]) / (2**23) for m in full_metrics)
    target_n = 2**30
    records_per_page = 113 if alphabet == 32 else 15
    loose_pages = math.ceil((2 * (target_n + 16)) / records_per_page)
    return {
        "status": "complete" if len(track_results) in (90, 25) else "partial",
        "alphabet_size": alphabet,
        "completed_surfaces": len(track_results),
        "checkpoint_means": rows,
        "full_run_wall_seconds": {
            "minimum": min(float(m["wall_seconds"]) for m in full_metrics),
            "median": median_wall,
            "maximum": max(float(m["wall_seconds"]) for m in full_metrics),
        },
        "full_run_peak_rss_kib": {
            "minimum": min(int(m["peak_rss_kib"]) for m in full_metrics),
            "median": statistics.median(int(m["peak_rss_kib"]) for m in full_metrics),
            "maximum": max(int(m["peak_rss_kib"]) for m in full_metrics),
        },
        "work_by_order_final": {
            "mean_scores_by_depth": [sum(float(m["scores_by_depth"][k]) for m in full_metrics) / len(full_metrics) for k in ORDERS],
            "mean_updates_by_depth": [sum(float(m["updates_by_depth"][k]) for m in full_metrics) / len(full_metrics) for k in ORDERS],
        },
        "extrapolation_2^30": {
            "target_n": target_n,
            "arithmetic_ratio_from_2^23": 128,
            "naive_128x_median_wall_seconds_sensitivity_only": median_wall * 128,
            "observed_median_page_reads_per_symbol": median_reads_per_symbol,
            "observed_median_page_writes_per_symbol": median_writes_per_symbol,
            "historical_4KiB_probe_iops_model_seconds_mismatched_to_64KiB_engine_pages": target_n * (median_reads_per_symbol / 14856.0 + median_writes_per_symbol / 14181.0),
            "observed_allocated_bytes_per_symbol_linear_sensitivity": median_allocated_per_symbol * target_n,
            "dense_record_loose_allocated_page_bound_bytes": loose_pages * 65536,
            "limitations": [
                "elapsed time is not claimed linear; fixed-cache miss rates can rise with n",
                "historical IOPS were queue-depth-one 4KiB O_DIRECT probe operations, not calibrated 64KiB engine I/O",
                "observed bytes-per-symbol extrapolation is a sensitivity calculation, not a storage guarantee",
                "dense-record bound is deliberately loose and excludes some fixed/runtime overheads",
            ],
        },
    }


def group_annex(results: list[dict[str, Any]], track: str) -> dict[str, Any]:
    if not results:
        return {}
    endpoint = [result["checkpoints"][-1] for result in results]
    occupancy = []
    for k in ORDERS:
        keys = [
            "visits", "distinct_contexts", "singleton_contexts", "contexts_total_lt5",
            "singleton_visitation_numerator", "rare_visitation_numerator",
        ]
        row: dict[str, Any] = {"k": k}
        for key in keys:
            row[f"mean_{key}"] = sum(float(cp["occupancy"][k][key]) for cp in endpoint) / len(endpoint)
        for key in ("singleton_visitation_mass", "rare_visitation_mass"):
            values = [cp["occupancy"][k][key] for cp in endpoint if cp["occupancy"][k][key] is not None]
            row[f"mean_{key}"] = sum(float(value) for value in values) / len(values) if values else None
        occupancy.append(row)
    summary: dict[str, Any] = {
        "endpoint_mean_occupancy": occupancy,
        "endpoint_mean_L": [sum(float(cp["L"][k]) for cp in endpoint) / len(endpoint) for k in ORDERS],
        "endpoint_mean_L_ML": [sum(float(cp["L_ML"][k]) for cp in endpoint) / len(endpoint) for k in ORDERS],
        "endpoint_mean_KT_minus_ML_per_symbol": [sum(float(cp["KT_minus_ML_per_symbol"][k]) for cp in endpoint) / len(endpoint) for k in ORDERS],
    }
    if track == "A":
        summary["endpoint_mean_predicted_symbol_counts"] = [
            sum(float(cp["predicted_symbol_attribution"]["counts"][a]) for cp in endpoint) / len(endpoint)
            for a in range(32)
        ]
        summary["endpoint_mean_predicted_symbol_A_contribution_order_major"] = [
            sum(float(cp["predicted_symbol_attribution"]["A_contribution_order_major"][i]) for cp in endpoint) / len(endpoint)
            for i in range(17 * 32)
        ]
        summary["maximum_absolute_contribution_sum_residual"] = max(
            abs(float(value))
            for cp in endpoint
            for value in cp["predicted_symbol_attribution"]["contribution_sum_residual"]
        )
    else:
        summary["endpoint_mean_whitespace_bucket_counts"] = [
            sum(float(cp["whitespace_attribution"]["counts"][b]) for cp in endpoint) / len(endpoint)
            for b in range(3)
        ]
        summary["endpoint_mean_whitespace_A_contribution_order_major"] = [
            sum(float(cp["whitespace_attribution"]["A_contribution_order_major"][i]) for cp in endpoint) / len(endpoint)
            for i in range(17 * 3)
        ]
        summary["endpoint_aligned_offsets"] = [cp["whitespace_attribution"].get("aligned_offset") for cp in endpoint]
        summary["endpoint_mean_aligned_A"] = [
            sum(float(cp["whitespace_attribution"]["aligned_A"][k]) for cp in endpoint if cp["whitespace_attribution"].get("aligned_A") is not None)
            / sum(1 for cp in endpoint if cp["whitespace_attribution"].get("aligned_A") is not None)
            if any(cp["whitespace_attribution"].get("aligned_A") is not None for cp in endpoint) else None
            for k in ORDERS
        ]
        summary["maximum_absolute_contribution_sum_residual"] = max(
            abs(float(value))
            for cp in endpoint
            for value in cp["whitespace_attribution"]["contribution_sum_residual"]
        )
    return summary


def markdown_report(analysis: dict[str, Any]) -> str:
    inventory = analysis["inventory"]
    predictions = analysis["predictions"]
    gates = analysis["gates"]
    lines = [
        "# Block 01 Availability Surface — Rev B results",
        "",
        f"Generated UTC: `{analysis['generated_utc']}`",
        "",
        "## Completion and provenance",
        "",
        f"- Track A primary surfaces: **{inventory['track_A_completed']}/90**.",
        f"- Track B primary surfaces: **{inventory['track_B_completed']}/25**.",
        f"- Execution supplement SHA256: `{analysis['execution_manifest_sha256']}`.",
        f"- Evidence status: **{analysis['evidence_status']}**.",
        "- All scientific arithmetic below is computed from persisted result JSON; no corpus was rescored by the reporting harness.",
        "",
        "## Frozen predictions",
        "",
        "| # | Status | Result |",
        "|---:|:---:|---|",
    ]
    for number in range(1, 11):
        item = predictions[str(number)]
        detail = json.dumps({k: v for k, v in item.items() if k not in {"status", "passed"}}, sort_keys=True)
        if len(detail) > 360:
            detail = detail[:357] + "..."
        lines.append(f"| {number} | {item['status']} | `{detail}` |")
    lines += [
        "",
        "## Independent gates and conditional interpretation",
        "",
        f"- Correctness gate (1–4,6–7): **{gates['correctness']['status']}**.",
        f"- Foundation gate (5,8): **{gates['foundation']['status']}**.",
        f"- Usefulness gate (9,10): **{gates['usefulness']['status']}**.",
        f"- Conditional outcome: **{analysis['conditional_interpretation']}**.",
        "",
        "A failed correctness gate makes the scientific verdict Void even if foundation/usefulness arithmetic is numerically available. A failed foundation gate makes usefulness non-evidential. Prediction 5 and prediction 8 are reported separately; failure of 5 is not relabeled normalized collapse when 8 passes.",
        "",
        "## Annex A diagnostics",
        "",
        "Persisted raw files contain checkpoint cumulative `L`, `A`, `L_ML`, KT-minus-ML descriptive redundancy, occupancy integer numerators/denominators, predicted-symbol attribution (Track A), ASCII-whitespace buckets/aligned prefixes (Track B), resource metrics, and binary64 bit patterns. The analysis JSON adds per-run increments, linear-`n` mixed finite differences, first-below-0.01 ridge/censor values, five-run mean surfaces, and sample standard deviations.",
        "",
        "Occupancy masses are empirical visitation masses, not generator probability mass. `L_KT-L_ML` is reference-dependent descriptive redundancy, not uniquely identifiable pure estimation cost. Track B alignment is an inclusive prefix ending at the latest ASCII whitespace byte and is not word-level availability.",
        "",
        "## Cost and 2^30 extrapolation",
        "",
    ]
    for track in ("A", "B"):
        cost = analysis["cost_characterization"][track]
        lines.append(f"### Track {track} (alphabet {cost.get('alphabet_size')})")
        lines.append("")
        if cost.get("completed_surfaces", 0):
            wall = cost["full_run_wall_seconds"]
            rss = cost["full_run_peak_rss_kib"]
            ext = cost["extrapolation_2^30"]
            lines += [
                f"- Full-run wall seconds min/median/max: `{wall['minimum']:.6g}` / `{wall['median']:.6g}` / `{wall['maximum']:.6g}`.",
                f"- Peak RSS KiB min/median/max: `{rss['minimum']}` / `{rss['median']}` / `{rss['maximum']}`.",
                f"- Arithmetic input ratio from `2^23` to `2^30`: `{ext['arithmetic_ratio_from_2^23']}`.",
                f"- Naive 128× median-wall sensitivity only: `{ext['naive_128x_median_wall_seconds_sensitivity_only']:.6g}` seconds.",
                f"- Historical mismatched 4 KiB IOPS model: `{ext['historical_4KiB_probe_iops_model_seconds_mismatched_to_64KiB_engine_pages']:.6g}` seconds per surface.",
                f"- Dense-record loose allocated-page bound: `{ext['dense_record_loose_allocated_page_bound_bytes']}` bytes per surface.",
                "- These are sensitivities/bounds, not a feasibility claim: cache misses and I/O locality can worsen as exact state exceeds the fixed 2 GiB cache.",
            ]
        else:
            lines.append("- No completed surfaces; cost unavailable.")
        lines.append("")
    lines += [
        "## Separability",
        "",
        f"Status: **{analysis['separability']['status']}**. {analysis['separability']['reason']}",
        "",
        "Symmetric KT with a uniform half-count is invariant under every global alphabet bijection. The frozen within-class and across-class maps therefore preserve all losses and availability values; an across-class drop is mathematically impossible. No corruption or context-dependent replacement map is introduced.",
        "",
        "## Limitations",
        "",
        "- Surface separation does not establish cognition, intrinsic reader independence, sufficiency, or claims about English/code/child-directed speech.",
        "- Strict finite-sample prediction failure is reported as observed and is not repaired by tuning frozen kernels, gates, or thresholds.",
        "- Missing surfaces are incomplete production evidence, not a scientific no-go.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--execution-manifest-sha256", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    run_root = args.run_root.resolve()
    execution_hash = args.execution_manifest_sha256.lower()
    freeze = read_json(workspace / "REVB_FREEZE.json")

    a_results: dict[str, dict[str, Any]] = {}
    a_missing: list[str] = []
    for run in freeze["track_A"]["runs"]:
        run_id = run["run_id"]
        result = load_surface(run_root / "track_a" / "surfaces" / f"{run_id}.json", run_id, "A", execution_hash)
        if result is None:
            a_missing.append(run_id)
        else:
            a_results[run_id] = result

    b_results: dict[str, dict[str, Any]] = {}
    b_missing: list[str] = []
    for corpus in B_CORPORA:
        for draw in range(1, 6):
            run_id = f"B_{corpus}_draw{draw}"
            result = load_surface(run_root / "track_b" / "surfaces" / f"{run_id}.json", run_id, "B", execution_hash)
            if result is None:
                b_missing.append(run_id)
            else:
                b_results[run_id] = result

    a_groups: dict[str, list[dict[str, Any]]] = {}
    for configuration in [item["id"] for item in freeze["track_A"]["configurations"]]:
        ordered = []
        for seed in SEEDS:
            match = next((run for run in freeze["track_A"]["runs"] if run["configuration"] == configuration and run["seed"] == seed), None)
            if match and match["run_id"] in a_results:
                ordered.append(a_results[match["run_id"]])
        a_groups[configuration] = ordered
    b_groups = {corpus: [b_results[f"B_{corpus}_draw{draw}"] for draw in range(1, 6) if f"B_{corpus}_draw{draw}" in b_results] for corpus in B_CORPORA}

    group_stats: dict[str, Any] = {"track_A": {}, "track_B": {}}
    a_means: dict[str, list[list[float]]] = {}
    for name, results in a_groups.items():
        if len(results) == 5:
            mean_a = mean_grid(results)
            a_means[name] = mean_a
            group_stats["track_A"][name] = {
                "run_ids": [result["metadata"]["run_id"] for result in results],
                "mean_A": mean_a,
                "sample_std_A": sample_std_grid(results, mean_a),
                "mean_L": mean_grid(results, "L"),
                "annex_endpoint": group_annex(results, "A"),
            }
    b_means: dict[str, list[list[float]]] = {}
    for name, results in b_groups.items():
        if len(results) == 5:
            mean_a = mean_grid(results)
            b_means[name] = mean_a
            group_stats["track_B"][name] = {
                "run_ids": [result["metadata"]["run_id"] for result in results],
                "mean_A": mean_a,
                "sample_std_A": sample_std_grid(results, mean_a),
                "mean_L": mean_grid(results, "L"),
                "annex_endpoint": group_annex(results, "B"),
            }

    derived_runs: dict[str, Any] = {}
    for run_id, result in itertools.chain(a_results.items(), b_results.items()):
        inc = increments(grid(result))
        derived_runs[run_id] = {"increments": inc, "mixed_finite_difference_linear_n": mixed_n(inc), "ridge": ridge(inc)}

    predictions: dict[str, Any] = {}
    if "G1" in a_means:
        value = increments(a_means["G1"])[-1][1]
        predictions["1"] = predicate("pass" if value < 0.01 else "fail", value < 0.01, delta_2=value, threshold="<0.01")
    else:
        predictions["1"] = predicate("incomplete", None, missing="G1 five-run mean")

    if "G2" in a_means:
        inc = increments(a_means["G2"])[-1]
        passed = inc[5] < 0.01 and inc[4] > 0.05
        predictions["2"] = predicate("pass" if passed else "fail", passed, delta_6=inc[5], delta_5=inc[4], requirements=["delta_6<0.01", "delta_5>0.05"])
    else:
        predictions["2"] = predicate("incomplete", None, missing="G2 five-run mean")

    p3_rows = []
    p3_complete = True
    for d in [2, 3, 4, 5, 6, 8, 10, 12, 14]:
        name = f"G3({d})"
        if name not in a_means:
            p3_complete = False
            p3_rows.append({"configuration": name, "status": "incomplete"})
            continue
        inc = increments(a_means[name])[-1]
        d_value = inc[d - 1]
        other_max = max(inc[k - 1] for k in range(1, 17) if k != d)
        other_argmax = next(k for k in range(1, 17) if k != d and inc[k - 1] == other_max)
        passed = d_value > 0.05 and all(d_value > inc[k - 1] for k in range(1, 17) if k != d)
        p3_rows.append({"configuration": name, "status": "pass" if passed else "fail", "passed": passed, "delta_d": d_value, "largest_other_delta": other_max, "largest_other_k": other_argmax})
    if not p3_complete:
        predictions["3"] = predicate("incomplete", None, configurations=p3_rows)
    else:
        passed = all(row["passed"] for row in p3_rows)
        predictions["3"] = predicate("pass" if passed else "fail", passed, configurations=p3_rows)

    if "G4" in a_means:
        values = [(a_means["G4"][-1][k], k) for k in range(1, 17)]
        maximum, maximum_k = max(values)
        passed = all(value < 0.01 for value, _ in values)
        predictions["4"] = predicate("pass" if passed else "fail", passed, maximum_A=maximum, maximum_k=maximum_k, threshold="every k>=1 <0.01")
    else:
        predictions["4"] = predicate("incomplete", None, missing="G4 five-run mean")

    p5_rows = []
    for d in [4, 8, 12]:
        left, right = f"G5({d})", f"G6({d})"
        if left not in a_means or right not in a_means:
            p5_rows.append({"d": d, "status": "incomplete"})
        else:
            witness = full_curve_distance(a_means[left], a_means[right])
            passed = witness["value"] > 0.1
            p5_rows.append({"d": d, "status": "pass" if passed else "fail", "passed": passed, **witness})
    if any(row["status"] == "incomplete" for row in p5_rows):
        predictions["5"] = predicate("incomplete", None, pairs=p5_rows)
    else:
        passed = all(row["passed"] for row in p5_rows)
        predictions["5"] = predicate("pass" if passed else "fail", passed, pairs=p5_rows)

    if "G2" in a_means:
        ridge_rows = ridge(increments(a_means["G2"]))
        categories = [row["k"] for row in ridge_rows]
        nondecreasing = all(categories[i] <= categories[i + 1] for i in range(11))
        strict = categories[2] < categories[-1]
        passed = nondecreasing and strict
        predictions["6"] = predicate("pass" if passed else "fail", passed, ridge=ridge_rows, nondecreasing=nondecreasing, R_2_14=categories[2], R_2_23=categories[-1], strict_smaller=strict)
    else:
        predictions["6"] = predicate("incomplete", None, missing="G2 five-run mean")

    if "G6(12)" in a_means:
        tested = [(a_means["G6(12)"][j][k], CHECKPOINTS[j], k) for j in range(5) for k in ORDERS]
        maximum, maximum_n, maximum_k = max(tested)
        passed = all(value < 0.3 for value, _, _ in tested)
        predictions["7"] = predicate("pass" if passed else "fail", passed, maximum_A=maximum, maximum_n=maximum_n, maximum_k=maximum_k, threshold="every k and n<=2^16 <0.3")
    else:
        predictions["7"] = predicate("incomplete", None, missing="G6(12) five-run mean")

    eligible = ["G1", "G2", "G3(8)", "G5(8)", "G6(8)"]
    if all(name in a_means for name in eligible):
        denominators = {name: a_means[name][-1][16] for name in eligible}
        zero = [name for name, value in denominators.items() if value == 0.0]
        if zero:
            predictions["8"] = predicate("undefined", False, denominators=denominators, zero_denominators=zero, reason="exact zero normalization denominator")
        else:
            normalized = {name: [[value / denominators[name] for value in row] for row in a_means[name]] for name in eligible}
            pairs = []
            for left, right in itertools.combinations(eligible, 2):
                pairs.append({"left": left, "right": right, **linf(normalized[left], normalized[right])})
            witness = max(pairs, key=lambda row: row["value"])
            passed = witness["value"] > 0.15
            predictions["8"] = predicate("pass" if passed else "fail", passed, denominators=denominators, maximum_pair=witness, all_pairs=pairs)
    else:
        predictions["8"] = predicate("incomplete", None, missing=[name for name in eligible if name not in a_means])

    if all(name in b_means for name in B_CORPORA) and all(len(b_groups[name]) == 5 for name in B_CORPORA):
        between = []
        for left, right in itertools.combinations(B_CORPORA, 2):
            between.append({"left": left, "right": right, **linf(b_means[left], b_means[right])})
        numerator_witness = max(between, key=lambda row: row["value"])
        within = []
        for corpus in B_CORPORA:
            for left_i, right_i in itertools.combinations(range(5), 2):
                witness = linf(grid(b_groups[corpus][left_i]), grid(b_groups[corpus][right_i]))
                within.append({"corpus": corpus, "left_draw": left_i + 1, "right_draw": right_i + 1, **witness})
        denominator_witness = max(within, key=lambda row: row["value"])
        if denominator_witness["value"] == 0.0:
            predictions["9"] = predicate("undefined", False, numerator=numerator_witness, denominator=denominator_witness, reason="zero within-corpus denominator")
        else:
            ratio = numerator_witness["value"] / denominator_witness["value"]
            passed = ratio > 3.0
            predictions["9"] = predicate("pass" if passed else "fail", passed, ratio=ratio, numerator=numerator_witness, denominator=denominator_witness, threshold=">3")
    else:
        predictions["9"] = predicate("incomplete", None, missing=[name for name in B_CORPORA if name not in b_means])

    if all(name in b_means for name in ("B1", "B4", "B5")):
        cells = []
        for k in range(4, 17):
            b1, b4, b5 = b_means["B1"][-1][k], b_means["B4"][-1][k], b_means["B5"][-1][k]
            cells.append({"k": k, "B1": b1, "B4": b4, "B5": b5, "passed": b1 > b4 > b5})
        passed = all(row["passed"] for row in cells)
        predictions["10"] = predicate("pass" if passed else "fail", passed, cells=cells, requirement="B1>B4>B5 for k=4..16 at full n")
    else:
        predictions["10"] = predicate("incomplete", None, missing=[name for name in ("B1", "B4", "B5") if name not in b_means])

    def gate(numbers: list[int]) -> dict[str, Any]:
        statuses = {str(number): predictions[str(number)]["status"] for number in numbers}
        if any(status == "incomplete" for status in statuses.values()):
            status = "incomplete"
        elif all(status == "pass" for status in statuses.values()):
            status = "pass"
        else:
            status = "fail"
        return {"status": status, "constituents": statuses}

    gates = {"correctness": gate([1, 2, 3, 4, 6, 7]), "foundation": gate([5, 8]), "usefulness": gate([9, 10])}
    if any(value["status"] == "incomplete" for value in gates.values()):
        interpretation = "incomplete"
    elif gates["correctness"]["status"] != "pass":
        interpretation = "Void"
    elif gates["foundation"]["status"] != "pass":
        interpretation = "Foundation dead"
    elif gates["usefulness"]["status"] != "pass":
        interpretation = "Valid but blunt"
    else:
        interpretation = "Go"

    separability = {
        "status": "required_not_yet_analyzed" if gates["correctness"]["status"] == "pass" and gates["foundation"]["status"] == "pass" else "not_run_gate_condition_false",
        "reason": "Correctness and Foundation must both pass before production separability scoring." if not (gates["correctness"]["status"] == "pass" and gates["foundation"]["status"] == "pass") else "Run frozen separability launcher, then extend this report with persisted secondary surfaces.",
        "global_bijection_theorem": "symmetric KT is exactly invariant under both frozen maps; across-class drop is impossible",
    }

    all_a = list(a_results.values())
    all_b = list(b_results.values())
    disk = shutil.disk_usage(run_root)
    complete = len(all_a) == 90 and len(all_b) == 25
    analysis: dict[str, Any] = {
        "schema": "block01-revb-analysis-v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "execution_manifest_sha256": execution_hash,
        "evidence_status": "complete_primary_scope" if complete else "incomplete_primary_scope",
        "inventory": {
            "track_A_completed": len(all_a), "track_A_expected": 90, "track_A_missing": a_missing,
            "track_B_completed": len(all_b), "track_B_expected": 25, "track_B_missing": b_missing,
        },
        "aggregation": "arithmetic mean in frozen seed/draw order before comparisons; pointwise sample std denominator 4",
        "group_statistics": group_stats,
        "per_run_annex_derived": derived_runs,
        "predictions": predictions,
        "gates": gates,
        "conditional_interpretation": interpretation,
        "separability": separability,
        "annex_definitions_and_limitations": {
            "mixed_finite_difference": "forward adjacent-checkpoint difference of delta-k increments divided by linear n difference",
            "ridge": "first k with increment<0.01; sentinel 17 right-censored above order16",
            "occupancy": "empirical full-context visitation mass after update; startup excluded; not true generator mass",
            "ML_reference": "retrospective unsmoothed conditional ML with frozen uniform startup; KT-minus-ML is descriptive redundancy",
            "predicted_symbol": "Track A attribution by currently predicted byte; contribution arrays divide by total n",
            "whitespace": "Track B ASCII bytes {9,10,11,12,13,32}; inclusive latest-whitespace aligned prefix; no reset",
        },
        "cost_characterization": {
            "A": summarize_cost(all_a, 32),
            "B": summarize_cost(all_b, 256),
            "host_disk_at_report": {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free},
            "complexity": "ordered scoring/addition O(N*K); exact alphabet-dependent state and random I/O can dominate; fixed RAM does not imply fixed disk/time",
        },
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_report.write_text(markdown_report(analysis), encoding="utf-8")
    print(json.dumps({"analysis": str(args.output_json), "report": str(args.output_report), "evidence_status": analysis["evidence_status"], "conditional_interpretation": interpretation}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
