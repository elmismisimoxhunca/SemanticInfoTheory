"""Independent SplitMix64 + frozen Track A kernel reference (audit).

Written from REVB_PROTOCOL.md kernel/consumption text and the SplitMix64
definition (state=seed, add-gamma, Stafford variant 13 mix, rejection
uniform). Used to check build/generate_corpus byte-for-byte and to
re-derive Track B B4/B5 transforms independently.
"""

from __future__ import annotations

M64 = (1 << 64) - 1


class SplitMix64:
    def __init__(self, seed: int):
        self.state = seed & M64

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & M64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
        return z ^ (z >> 31)

    def uniform(self, bound: int) -> int:
        if bound <= 0:
            raise ValueError("bound must be positive")
        threshold = ((1 << 64) - bound) % bound
        while True:
            value = self.next_u64()
            if value >= threshold:
                return value % bound


def gen_lag_copy(seed: int, lag: int, n: int) -> bytes:
    """Frozen lag-copy: i<lag consume one uniform(32); later consume
    uniform(4) then uniform(32) ALWAYS; coin 0,1,2 copy x[i-lag], coin 3
    emits the innovation draw."""
    rng = SplitMix64(seed)
    ring = [0] * lag
    out = bytearray(n)
    for i in range(n):
        if i < lag:
            v = rng.uniform(32)
            ring[i % lag] = v
            out[i] = v
            continue
        coin = rng.uniform(4)
        innovation = rng.uniform(32)
        slot = i % lag
        v = ring[slot] if coin < 3 else innovation
        ring[slot] = v
        out[i] = v
    return bytes(out)


def gen_g3(seed: int, d: int, n: int) -> bytes:
    """Frozen G3(d): fixed blocks length d+1 from i=0; phase 0 controller
    16+uniform(8); phases 1..d-1 filler uniform(16); phase d emits
    controller+8 with no draw."""
    rng = SplitMix64(seed)
    out = bytearray(n)
    controller = 0
    for i in range(n):
        phase = i % (d + 1)
        if phase == 0:
            controller = 16 + rng.uniform(8)
            out[i] = controller
        elif phase == d:
            out[i] = controller + 8
        else:
            out[i] = rng.uniform(16)
    return bytes(out)


def gen_g4(seed: int, n: int) -> bytes:
    rng = SplitMix64(seed)
    return bytes(rng.uniform(32) for _ in range(n))


def generate(configuration: str, seed: int, n: int) -> bytes:
    if configuration == "G1":
        return gen_lag_copy(seed, 1, n)
    if configuration == "G2":
        return gen_lag_copy(seed, 5, n)
    if configuration == "G4":
        return gen_g4(seed, n)
    if configuration.startswith("G3("):
        return gen_g3(seed, int(configuration[3:-1]), n)
    if configuration.startswith("G5("):
        return gen_lag_copy(seed, 2, n)  # frozen: short lag 2 for every paired d
    if configuration.startswith("G6("):
        return gen_lag_copy(seed, int(configuration[3:-1]), n)
    raise ValueError(configuration)


# ---- Track B segmentation/transforms, independent reimplementation ----

WS = frozenset({9, 10, 11, 12, 13, 32})
TERMINATORS = frozenset({0x2E, 0x21, 0x3F})


def segment_units(data: bytes) -> list[bytes]:
    """Unit boundary after a terminator byte plus its maximal trailing W run."""
    units = []
    start = 0
    i = 0
    nd = len(data)
    while i < nd:
        if data[i] in TERMINATORS:
            j = i + 1
            while j < nd and data[j] in WS:
                j += 1
            units.append(data[start:j])
            start = j
            i = j
        else:
            i += 1
    if start < nd:
        units.append(data[start:])
    return units


def b4_transform(b1: bytes, seed: int) -> bytes:
    units = segment_units(b1)
    if len(units) <= 2:
        return b1
    prefix, suffix = units[0], units[-1]
    interior = list(units[1:-1])
    rng = SplitMix64(seed)
    for i in range(len(interior) - 1, 0, -1):
        j = rng.uniform(i + 1)
        interior[i], interior[j] = interior[j], interior[i]
    return prefix + b"".join(interior) + suffix


def b5_transform(b1: bytes, seed: int) -> bytes:
    units = segment_units(b1)
    rng = SplitMix64(seed)  # one continuing stream across all units
    out = []
    for unit in units:
        tokens = []  # (is_word, bytes)
        i = 0
        nu = len(unit)
        while i < nu:
            j = i
            if unit[i] in WS:
                while j < nu and unit[j] in WS:
                    j += 1
                tokens.append((False, unit[i:j]))
            else:
                while j < nu and unit[j] not in WS:
                    j += 1
                tokens.append((True, unit[i:j]))
            i = j
        words = [t for (is_w, t) in tokens if is_w]
        for i in range(len(words) - 1, 0, -1):
            j = rng.uniform(i + 1)
            words[i], words[j] = words[j], words[i]
        it = iter(words)
        out.append(b"".join(next(it) if is_w else t for (is_w, t) in tokens))
    return b"".join(out)
