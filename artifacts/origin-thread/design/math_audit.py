#!/usr/bin/env python3
"""Analytical audit only: no PRNG, corpus, KT-engine, or empirical curves."""
import decimal
import json
import math
from pathlib import Path


def hb(p):
    return 0.0 if p in (0.0, 1.0) else -p * math.log2(p) - (1-p) * math.log2(1-p)


q, r = 97/128, 1/128
h = -q * math.log2(q) - 31 * r * math.log2(r)
type_entropy = -sum(p * math.log2(p) for p in (7/9, 1/9, 1/9))
hg3 = [34/9 + type_entropy]
for k in range(1, 8):
    m = 8-k
    hg3.append(34/9 + m/9 * hb(1/m))
hg3.extend([31/9] * 9)
gains = [0.0] + [hg3[k-1] - hg3[k] for k in range(1, 17)]
assert abs(q + 31*r - 1) < 1e-15
assert len(hg3) == 17
assert abs(gains[8] - 1/3) < 1e-14
assert abs(max(gains[2:8]) - 2/9) < 1e-14
assert gains[8] > max(gains[2:8])
assert abs(hg3[7] - 34/9) < 1e-14

# Poisson occupancy estimate for INDEPENDENT uniform 80-bit history keys,
# NOT measured context occupancy and NOT a model for lag-copy/G3 sources.
def storage_estimate(n):
    decimal.getcontext().prec = 65
    D = decimal.Decimal
    by_depth = {}
    for depth in range(4, 16):
        buckets = D(32) ** depth
        lam = D(n) / buckets
        probability_branch = 1 + 31 * (-lam).exp() - 32 * (-D(31)*lam/32).exp()
        by_depth[str(depth)] = float(buckets * probability_branch)
    branches = sum(by_depth.values())
    nodes = n + branches
    return {
        'N': n,
        'assumption': 'Independent uniform length-16 history keys; Poisson approximation, not a generator sample.',
        'tail_branch_nodes_by_depth': by_depth,
        'tail_branch_nodes': branches,
        'approx_leaf_nodes': n,
        'node_headers_bytes_64_each': 64 * nodes,
        'singleton_leaves_plus_dense_branch_payload_bytes': 64*nodes + 512*branches,
        'excluded': 'page slack, startup endpoints, allocator metadata, dense frontend, filesystem overhead; repeated-key leaf histograms assumed absent',
    }

result = {
    'kind': 'analytical audit, no empirical curves',
    'lag_copy': {'q': q, 'r': r, 'entropy_rate_bits': h, 'asymptotic_available_gain_bits': 5-h},
    'G3': {
        'entropy_rate_bits': 31/9,
        'pooled_phase_conditional_entropies_k_0_to_16': hg3,
        'oracle_gains_k_0_to_16': gains,
        'largest_gain_k_2_to_7': max(gains[2:8]),
        'agreement_gain_k_8': gains[8],
        'agreeing_position_context_support_k_7': 16**7,
        'agreeing_position_context_support_k_8': 8 * 16**7,
        'warning': 'Oracle entropies are not finite-sample KT availability. Phase is pooled, not supplied as a side channel.',
    },
    'uniform_key_storage_estimates': [storage_estimate(10_000_000), storage_estimate(1_000_000_000)],
    'production_counts': {'curves': 30, 'symbols_total': 300_000_000, 'naive_order_scores': 5_100_000_000},
    'assertions_passed': 6,
}
Path(__file__).with_name('math_audit.json').write_text(json.dumps(result, indent=2) + '\n')
