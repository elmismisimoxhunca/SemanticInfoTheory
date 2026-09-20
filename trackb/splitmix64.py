MASK64 = (1 << 64) - 1

class SplitMix64:
    def __init__(self, seed):
        self.state = seed & MASK64

    def next_u64(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def uniform(self, bound):
        if bound <= 0:
            raise ValueError("uniform bound must be positive")
        threshold = ((1 << 64) - bound) % bound
        while True:
            value = self.next_u64()
            if value >= threshold:
                return value % bound

def fisher_yates(seq, seed):
    rng = SplitMix64(seed)
    a = list(seq)
    for i in range(len(a) - 1, 0, -1):
        j = rng.uniform(i + 1)
        a[i], a[j] = a[j], a[i]
    return a
