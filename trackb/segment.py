WS = frozenset([9, 10, 11, 12, 13, 32])
TERMINATORS = frozenset([0x2E, 0x21, 0x3F])  # . ! ?

def segment_units(data: bytes):
    """Split data into ordered units: [prefix, sentence*, suffix] (suffix may equal
    the last sentence if data ends exactly on whitespace after a terminator).
    Each unit is a contiguous byte slice; concatenation of all units == data exactly.
    A unit boundary falls right after a terminator byte plus its immediately
    following maximal whitespace-mask run (or at end of data if no whitespace follows)."""
    n = len(data)
    boundaries = []
    i = 0
    while i < n:
        if data[i] in TERMINATORS:
            j = i + 1
            while j < n and data[j] in WS:
                j += 1
            boundaries.append(j)
            i = j
        else:
            i += 1
    units = []
    start = 0
    for b in boundaries:
        units.append(data[start:b])
        start = b
    if start < n:
        units.append(data[start:n])
    return units

def split_words(unit: bytes):
    """Return alternating list of tokens tagged ('W', bytes) for whitespace-mask runs
    and ('T', bytes) for non-whitespace runs, in original order."""
    n = len(unit)
    tokens = []
    i = 0
    while i < n:
        is_ws = unit[i] in WS
        j = i + 1
        while j < n and (unit[j] in WS) == is_ws:
            j += 1
        tokens.append(('W' if is_ws else 'T', unit[i:j]))
        i = j
    return tokens
