#pragma once
#include <cstdint>
#include <stdexcept>

// Frozen candidate PRNG implementation for Block 01. No corpus is generated here.
// State and arithmetic are unsigned 64-bit; overflow is reduction modulo 2^64.
// Instantiate afresh with the registered seed for each generator/corpus.
namespace block01 {
class SplitMix64 {
 public:
  explicit SplitMix64(std::uint64_t seed) : state_(seed) {}
  std::uint64_t next_u64() {
    std::uint64_t z = (state_ += UINT64_C(0x9e3779b97f4a7c15));
    z = (z ^ (z >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94d049bb133111eb);
    return z ^ (z >> 31);
  }
  std::uint64_t uniform(std::uint64_t bound) {
    if (bound == 0) throw std::invalid_argument("uniform bound must be positive");
    const std::uint64_t threshold = (std::uint64_t{0} - bound) % bound;
    for (;;) {
      const std::uint64_t value = next_u64();
      if (value >= threshold) return value % bound;
    }
  }
 private:
  std::uint64_t state_;
};
}  // namespace block01
