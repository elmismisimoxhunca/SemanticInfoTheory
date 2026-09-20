"""Independent exact KT availability reference for the Rev B audit.

Written from REVB_PROTOCOL.md semantics only (not from src/kt_engine.cpp):
  - order-k context = previous k bytes; score before update;
  - empty row costs exactly log2(S); events with i<k cost exactly log2(S)
    and update nothing;
  - per-order input-ordered binary64 accumulation;
  - checkpoint snapshot after scoring/updating the nth symbol;
  - ML reference: min(k,n)*log2(S) + sum_c[T log2 T - sum_a C log2 C]
    via g(T)-g(C_x) recurrence, g(t)=f(t+1)-f(t), f(t)=t*log2(t), f(0)=f(1)=0;
  - occupancy from a direct table scan at each checkpoint;
  - Track A predicted-symbol and Track B whitespace attribution.
"""

from __future__ import annotations

import math

WS = frozenset({9, 10, 11, 12, 13, 32})


def f_ml(t: int) -> float:
    if t <= 1:
        return 0.0
    return float(t) * math.log2(float(t))


def g_ml(t: int) -> float:
    return f_ml(t + 1) - f_ml(t)


def reference_surface(data: bytes, alphabet: int, k_max: int, checkpoints: list[int]):
    """Return per-checkpoint dicts with bit-exact intended arithmetic."""
    log2s = math.log2(float(alphabet))  # 5.0 or 8.0 exactly
    tables = [dict() for _ in range(k_max + 1)]  # per order: ctx -> [total, counts]
    losses = [0.0] * (k_max + 1)
    ml_losses = [0.0] * (k_max + 1)
    sym_counts = [0] * alphabet if alphabet == 32 else None
    sym_losses = [0.0] * ((k_max + 1) * alphabet) if alphabet == 32 else None
    ws_counts = [0, 0, 0]
    ws_losses = [0.0] * ((k_max + 1) * 3) if alphabet == 256 else None
    has_prev = False
    prev_ws = False
    has_aligned = False
    aligned_offset = 0
    aligned_losses = [0.0] * (k_max + 1)
    ck_set = list(checkpoints)
    out = []
    n = 0
    for i, x in enumerate(data):
        event_l = [0.0] * (k_max + 1)
        event_m = [0.0] * (k_max + 1)
        for k in range(k_max + 1):
            if i < k:
                event_l[k] = log2s
                event_m[k] = log2s
            else:
                ctx = data[i - k:i] if k else b""
                row = tables[k].get(ctx)
                if row is None or row[0] == 0:
                    event_l[k] = log2s
                    event_m[k] = g_ml(0) - g_ml(0)
                else:
                    total, counts = row
                    c = counts[x]
                    event_l[k] = -math.log2((float(c) + 0.5) /
                                            (float(total) + float(alphabet) / 2.0))
                    event_m[k] = g_ml(total) - g_ml(c)
        bucket = 0
        if alphabet == 256:
            cur_ws = x in WS
            bucket = 0 if cur_ws else (1 if (not has_prev or prev_ws) else 2)
            ws_counts[bucket] += 1
        else:
            sym_counts[x] += 1
        for k in range(k_max + 1):
            losses[k] += event_l[k]
            ml_losses[k] += event_m[k]
            if alphabet == 32:
                sym_losses[k * alphabet + x] += event_l[k]
            else:
                ws_losses[k * 3 + bucket] += event_l[k]
        # update after all orders scored
        for k in range(0, min(i, k_max) + 1):
            ctx = data[i - k:i] if k else b""
            row = tables[k].get(ctx)
            if row is None:
                row = [0, [0] * alphabet]
                tables[k][ctx] = row
            row[0] += 1
            row[1][x] += 1
        n = i + 1
        if alphabet == 256:
            prev_ws = x in WS
            has_prev = True
            if prev_ws:
                has_aligned = True
                aligned_offset = n
                aligned_losses = list(losses)
        if ck_set and n == ck_set[0]:
            ck_set.pop(0)
            occupancy = []
            for k in range(k_max + 1):
                occ = dict(visits=0, distinct_contexts=0, singleton_contexts=0,
                           contexts_total_lt5=0, singleton_visitation_numerator=0,
                           rare_visitation_numerator=0)
                for total, _counts in tables[k].values():
                    if total == 0:
                        continue
                    occ["visits"] += total
                    occ["distinct_contexts"] += 1
                    if total == 1:
                        occ["singleton_contexts"] += 1
                        occ["singleton_visitation_numerator"] += total
                    if total < 5:
                        occ["contexts_total_lt5"] += 1
                        occ["rare_visitation_numerator"] += total
                occupancy.append(occ)
            out.append(dict(
                n=n,
                L=list(losses),
                L_ML=list(ml_losses),
                occupancy=occupancy,
                sym_counts=list(sym_counts) if sym_counts is not None else None,
                sym_losses=list(sym_losses) if sym_losses is not None else None,
                ws_counts=list(ws_counts) if alphabet == 256 else None,
                ws_losses=list(ws_losses) if ws_losses is not None else None,
                has_aligned=has_aligned,
                aligned_offset=aligned_offset,
                aligned_losses=list(aligned_losses),
            ))
    if ck_set:
        raise AssertionError("reference: not all checkpoints reached")
    return out
