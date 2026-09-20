import hashlib, json, collections
from segment import segment_units, split_words
from splitmix64 import fisher_yates

CHUNK = 2**23

B4_SEEDS = [601, 602, 603, 604, 605]
B5_SEEDS = [701, 702, 703, 704, 705]

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()

def multiset(b):
    return collections.Counter(b)

def make_b4(draw: bytes, seed: int) -> bytes:
    units = segment_units(draw)
    if len(units) <= 2:
        return draw  # nothing interior to shuffle; declared no-op
    prefix, interior, suffix = units[0], units[1:-1], units[-1]
    shuffled = fisher_yates(interior, seed)
    return prefix + b"".join(shuffled) + suffix

def make_b5(draw: bytes, seed: int) -> bytes:
    units = segment_units(draw)
    rng_seed = seed
    out_units = []
    from splitmix64 import SplitMix64
    rng = SplitMix64(rng_seed)
    for u in units:
        tokens = split_words(u)
        word_positions = [i for i, (kind, _) in enumerate(tokens) if kind == 'T']
        word_values = [tokens[i][1] for i in word_positions]
        # Fisher-Yates in place using the continuing rng stream
        a = list(word_values)
        for i in range(len(a) - 1, 0, -1):
            j = rng.uniform(i + 1)
            a[i], a[j] = a[j], a[i]
        new_tokens = list(tokens)
        for pos, val in zip(word_positions, a):
            new_tokens[pos] = ('T', val)
        out_units.append(b"".join(v for _, v in new_tokens))
    return b"".join(out_units)

def load(path):
    with open(path, 'rb') as f:
        return f.read()

def write(path, data):
    with open(path, 'wb') as f:
        f.write(data)

manifest = {"draws": {}}

for corpus in ["b1", "b2", "b3"]:
    stream = load(f"{corpus}_stream.bin")
    assert len(stream) == 5 * CHUNK, (corpus, len(stream))
    manifest["draws"].setdefault(corpus, {})
    for d in range(5):
        draw = stream[d*CHUNK:(d+1)*CHUNK]
        assert len(draw) == CHUNK
        fname = f"{corpus.upper()}_draw{d+1}.bin"
        write(fname, draw)
        manifest["draws"][corpus][f"draw{d+1}"] = {
            "file": fname,
            "bytes": len(draw),
            "sha256": sha256_bytes(draw),
        }

# B4/B5 derived from B1 draws
manifest["draws"]["b4"] = {}
manifest["draws"]["b5"] = {}
for d in range(5):
    b1_draw = load(f"B1_draw{d+1}.bin")
    seed4 = B4_SEEDS[d]
    seed5 = B5_SEEDS[d]
    b4 = make_b4(b1_draw, seed4)
    b5 = make_b5(b1_draw, seed5)
    assert len(b4) == CHUNK, ("B4 length mismatch", d+1, len(b4))
    assert len(b5) == CHUNK, ("B5 length mismatch", d+1, len(b5))
    assert multiset(b4) == multiset(b1_draw), ("B4 multiset mismatch", d+1)
    assert multiset(b5) == multiset(b1_draw), ("B5 multiset mismatch", d+1)
    write(f"B4_draw{d+1}.bin", b4)
    write(f"B5_draw{d+1}.bin", b5)
    manifest["draws"]["b4"][f"draw{d+1}"] = {
        "file": f"B4_draw{d+1}.bin", "bytes": len(b4), "sha256": sha256_bytes(b4),
        "seed": seed4, "source": f"B1_draw{d+1}.bin",
    }
    manifest["draws"]["b5"][f"draw{d+1}"] = {
        "file": f"B5_draw{d+1}.bin", "bytes": len(b5), "sha256": sha256_bytes(b5),
        "seed": seed5, "source": f"B1_draw{d+1}.bin",
    }

with open("draw_manifest.json", "w") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)

print("OK - all draws and transforms built and verified byte-length/multiset-preserving.")
print(json.dumps(manifest, indent=2, sort_keys=True)[:2000])
