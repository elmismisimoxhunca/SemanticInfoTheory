#include "block01/kt_engine.hpp"

#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <span>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unistd.h>
#include <utility>
#include <vector>

namespace {

struct TestFailure : std::runtime_error {
  using std::runtime_error::runtime_error;
};

void require(bool condition, const std::string& message) {
  if (!condition) throw TestFailure(message);
}

void require_near(double actual, double expected, double tolerance, const std::string& message) {
  if (std::abs(actual - expected) > tolerance) {
    std::ostringstream detail;
    detail.precision(17);
    detail << message << ": actual=" << actual << " expected=" << expected
           << " tolerance=" << tolerance;
    throw TestFailure(detail.str());
  }
}

void write_bytes(const std::filesystem::path& path, const std::vector<std::uint8_t>& bytes) {
  std::ofstream output(path, std::ios::binary | std::ios::out | std::ios::trunc);
  if (!output) throw TestFailure("cannot create fixture");
  output.write(reinterpret_cast<const char*>(bytes.data()),
               static_cast<std::streamsize>(bytes.size()));
  if (!output) throw TestFailure("cannot write fixture");
}

void write_sidecar(const std::filesystem::path& corpus, std::uint32_t alphabet,
                   std::uint64_t expected_n) {
  const std::string digest = block01::sha256_file(corpus);
  std::ofstream output(corpus.string() + ".meta.json", std::ios::binary | std::ios::out |
                                                         std::ios::trunc);
  if (!output) throw TestFailure("cannot create fixture sidecar");
  output << "{\n"
         << "\"schema\":\"" << block01::kCorpusSchema << "\",\n"
         << "\"track\":\"" << (alphabet == 32 ? "A" : "B") << "\",\n"
         << "\"alphabet_size\":" << alphabet << ",\n"
         << "\"expected_n\":" << expected_n << ",\n"
         << "\"run_id\":\"fixture\",\n"
         << "\"corpus_sha256\":\"" << digest << "\",\n"
         << "\"protocol_sha256\":\"" << block01::kExpectedProtocolSha256 << "\",\n"
         << "\"freeze_sha256\":\"" << block01::kExpectedFreezeSha256 << "\",\n"
         << "\"execution_manifest_sha256\":\""
         << std::string(64, '1') << "\",\n";
  if (alphabet == 32) {
    output << "\"configuration\":\"fixture\",\n\"seed\":0\n";
  } else {
    output << "\"source_manifest_sha256\":\"" << std::string(64, '2') << "\",\n"
           << "\"corpus\":\"fixture\",\n\"draw_id\":1,\n"
           << "\"transformation_provenance\":\"fixture-only\"\n";
  }
  output << "}\n";
  if (!output) throw TestFailure("cannot write fixture sidecar");
}

struct NaiveRow {
  std::vector<std::uint64_t> counts;
  std::uint64_t total = 0;
};

struct NaiveCheckpoint {
  std::uint64_t n = 0;
  std::vector<double> losses;
  std::vector<double> ml_losses;
  std::vector<block01::OccupancySnapshot> occupancy;
  std::vector<std::uint64_t> symbol_counts;
  std::vector<double> symbol_losses;
  std::array<std::uint64_t, 3> whitespace_counts{};
  std::vector<double> whitespace_losses;
  bool has_aligned = false;
  std::uint64_t aligned_offset = 0;
  std::vector<double> aligned_losses;
};

double direct_loss(std::uint64_t count, std::uint64_t total, std::uint32_t alphabet) {
  if (total == 0) return std::log2(static_cast<double>(alphabet));
  return -std::log2((static_cast<double>(count) + 0.5) /
                    (static_cast<double>(total) + static_cast<double>(alphabet) / 2.0));
}

double direct_f(std::uint64_t value) {
  return value <= 1 ? 0.0 : static_cast<double>(value) * std::log2(static_cast<double>(value));
}

double direct_ml_increment(std::uint64_t total, std::uint64_t count) {
  return (direct_f(total + 1) - direct_f(total)) -
         (direct_f(count + 1) - direct_f(count));
}

bool whitespace(std::uint8_t value) {
  return value == 9 || value == 10 || value == 11 || value == 12 || value == 13 || value == 32;
}

std::string context_key(const std::vector<std::uint8_t>& bytes, std::size_t position,
                        std::uint32_t order) {
  std::string key;
  key.reserve(order);
  for (std::uint32_t offset = 0; offset < order; ++offset) {
    key.push_back(static_cast<char>(bytes[position - 1 - offset]));
  }
  return key;
}

std::vector<NaiveCheckpoint> naive_reference(const std::vector<std::uint8_t>& bytes,
                                             std::uint32_t alphabet, std::uint32_t k_max,
                                             const std::vector<std::uint64_t>& checkpoints) {
  std::vector<std::map<std::string, NaiveRow>> tables(k_max + 1);
  std::vector<double> losses(k_max + 1, 0.0);
  std::vector<double> ml_losses(k_max + 1, 0.0);
  std::vector<std::uint64_t> symbol_counts(alphabet == 32 ? alphabet : 0, 0);
  std::vector<double> symbol_losses(alphabet == 32 ? (k_max + 1) * alphabet : 0, 0.0);
  std::array<std::uint64_t, 3> whitespace_counts{};
  std::vector<double> whitespace_losses(alphabet == 256 ? (k_max + 1) * 3 : 0, 0.0);
  bool has_previous = false;
  bool previous_whitespace = false;
  bool has_aligned = false;
  std::uint64_t aligned_offset = 0;
  std::vector<double> aligned_losses(k_max + 1, 0.0);
  std::vector<NaiveCheckpoint> result;
  std::size_t next_checkpoint = 0;

  for (std::size_t position = 0; position < bytes.size(); ++position) {
    const std::uint8_t symbol = bytes[position];
    std::vector<double> event_losses(k_max + 1, 0.0);
    std::vector<double> event_ml(k_max + 1, 0.0);
    for (std::uint32_t order = 0; order <= k_max; ++order) {
      if (position < order) {
        event_losses[order] = std::log2(static_cast<double>(alphabet));
        event_ml[order] = event_losses[order];
      } else {
        const std::string key = context_key(bytes, position, order);
        auto [iterator, inserted] = tables[order].try_emplace(key);
        if (inserted) iterator->second.counts.assign(alphabet, 0);
        const NaiveRow& row = iterator->second;
        event_losses[order] = direct_loss(row.counts[symbol], row.total, alphabet);
        event_ml[order] = direct_ml_increment(row.total, row.counts[symbol]);
      }
    }

    unsigned bucket = 0;
    if (alphabet == 256) {
      bucket = whitespace(symbol) ? 0U : ((!has_previous || previous_whitespace) ? 1U : 2U);
      ++whitespace_counts[bucket];
    } else {
      ++symbol_counts[symbol];
    }
    for (std::uint32_t order = 0; order <= k_max; ++order) {
      losses[order] += event_losses[order];
      ml_losses[order] += event_ml[order];
      if (alphabet == 32) {
        symbol_losses[static_cast<std::size_t>(order) * alphabet + symbol] += event_losses[order];
      } else {
        whitespace_losses[static_cast<std::size_t>(order) * 3 + bucket] += event_losses[order];
      }
    }

    for (std::uint32_t order = 0; order <= k_max && order <= position; ++order) {
      const std::string key = context_key(bytes, position, order);
      NaiveRow& row = tables[order].at(key);
      ++row.total;
      ++row.counts[symbol];
    }

    if (alphabet == 256) {
      previous_whitespace = whitespace(symbol);
      has_previous = true;
      if (previous_whitespace) {
        has_aligned = true;
        aligned_offset = position + 1;
        aligned_losses = losses;
      }
    }

    const std::uint64_t n = position + 1;
    if (next_checkpoint < checkpoints.size() && n == checkpoints[next_checkpoint]) {
      NaiveCheckpoint checkpoint;
      checkpoint.n = n;
      checkpoint.losses = losses;
      checkpoint.ml_losses = ml_losses;
      checkpoint.symbol_counts = symbol_counts;
      checkpoint.symbol_losses = symbol_losses;
      checkpoint.whitespace_counts = whitespace_counts;
      checkpoint.whitespace_losses = whitespace_losses;
      checkpoint.has_aligned = has_aligned;
      checkpoint.aligned_offset = aligned_offset;
      checkpoint.aligned_losses = aligned_losses;
      checkpoint.occupancy.resize(k_max + 1);
      for (std::uint32_t order = 0; order <= k_max; ++order) {
        auto& occupancy = checkpoint.occupancy[order];
        for (const auto& [key, row] : tables[order]) {
          static_cast<void>(key);
          if (row.total == 0) continue;
          ++occupancy.distinct_contexts;
          occupancy.visits += row.total;
          if (row.total == 1) {
            ++occupancy.singleton_contexts;
            occupancy.singleton_visitation_numerator += row.total;
          }
          if (row.total < 5) {
            ++occupancy.rare_contexts_lt5;
            occupancy.rare_visitation_numerator += row.total;
          }
        }
      }
      result.push_back(std::move(checkpoint));
      ++next_checkpoint;
    }
  }
  return result;
}

block01::AvailabilityResult run_engine(const std::filesystem::path& root,
                                       std::string_view name,
                                       const std::vector<std::uint8_t>& bytes,
                                       std::uint32_t alphabet,
                                       std::uint32_t k_max,
                                       const std::vector<std::uint64_t>& checkpoints,
                                       std::uint64_t cache_pages) {
  const std::filesystem::path corpus = root / (std::string(name) + ".bin");
  write_bytes(corpus, bytes);
  write_sidecar(corpus, alphabet, bytes.size());
  block01::EngineOptions options;
  options.k_max = k_max;
  options.checkpoints = checkpoints;
  options.cache_pages_override = cache_pages;
  options.store_path = root / (std::string(name) + ".store");
  return block01::compute_availability(corpus, options);
}

void compare_reference(const block01::AvailabilityResult& actual,
                       const std::vector<NaiveCheckpoint>& expected,
                       std::uint32_t alphabet) {
  require(actual.checkpoints.size() == expected.size(), "checkpoint count mismatch");
  for (std::size_t checkpoint_index = 0; checkpoint_index < expected.size(); ++checkpoint_index) {
    const auto& a = actual.checkpoints[checkpoint_index];
    const auto& e = expected[checkpoint_index];
    require(a.n == e.n, "checkpoint n mismatch");
    require(a.losses.size() == e.losses.size(), "loss order count mismatch");
    for (std::size_t k = 0; k < e.losses.size(); ++k) {
      require(std::bit_cast<std::uint64_t>(a.losses[k]) ==
                  std::bit_cast<std::uint64_t>(e.losses[k]),
              "KT loss bit mismatch at checkpoint/order");
      require_near(a.ml_losses[k], e.ml_losses[k], 1e-11,
                   "ML recurrence mismatch at checkpoint/order");
      const auto& ao = a.occupancy[k];
      const auto& eo = e.occupancy[k];
      require(ao.visits == eo.visits && ao.distinct_contexts == eo.distinct_contexts &&
                  ao.singleton_contexts == eo.singleton_contexts &&
                  ao.rare_contexts_lt5 == eo.rare_contexts_lt5 &&
                  ao.singleton_visitation_numerator == eo.singleton_visitation_numerator &&
                  ao.rare_visitation_numerator == eo.rare_visitation_numerator,
              "occupancy mismatch at checkpoint/order");
    }
    if (alphabet == 32) {
      require(a.predicted_symbol_counts == e.symbol_counts, "symbol counts mismatch");
      require(a.predicted_symbol_losses.size() == e.symbol_losses.size(),
              "symbol attribution shape mismatch");
      for (std::size_t i = 0; i < e.symbol_losses.size(); ++i) {
        require(std::bit_cast<std::uint64_t>(a.predicted_symbol_losses[i]) ==
                    std::bit_cast<std::uint64_t>(e.symbol_losses[i]),
                "symbol attribution loss mismatch");
      }
      for (std::size_t k = 0; k < a.losses.size(); ++k) {
        double sum = 0.0;
        for (std::size_t symbol = 0; symbol < alphabet; ++symbol) {
          sum += a.predicted_symbol_losses[k * alphabet + symbol];
        }
        require_near(sum, a.losses[k], 1e-9, "symbol attribution sum residual too large");
      }
    } else {
      require(a.whitespace.counts == e.whitespace_counts, "whitespace counts mismatch");
      for (std::size_t i = 0; i < e.whitespace_losses.size(); ++i) {
        require(std::bit_cast<std::uint64_t>(a.whitespace.losses[i]) ==
                    std::bit_cast<std::uint64_t>(e.whitespace_losses[i]),
                "whitespace attribution loss mismatch");
      }
      require(a.whitespace.has_aligned_prefix == e.has_aligned, "aligned presence mismatch");
      require(a.whitespace.aligned_offset == e.aligned_offset, "aligned offset mismatch");
      for (std::size_t k = 0; k < e.aligned_losses.size(); ++k) {
        require(std::bit_cast<std::uint64_t>(a.whitespace.aligned_losses[k]) ==
                    std::bit_cast<std::uint64_t>(e.aligned_losses[k]),
                "aligned loss mismatch");
      }
    }
  }
}

std::vector<std::uint8_t> deterministic_fixture(std::size_t size, std::uint32_t alphabet) {
  std::vector<std::uint8_t> bytes;
  bytes.reserve(size);
  std::uint64_t state = UINT64_C(0x123456789abcdef0);
  for (std::size_t i = 0; i < size; ++i) {
    state ^= state >> 12;
    state ^= state << 25;
    state ^= state >> 27;
    const std::uint64_t value = state * UINT64_C(0x2545f4914f6cdd1d);
    bytes.push_back(static_cast<std::uint8_t>(value % alphabet));
  }
  return bytes;
}

void test_sha256() {
  const std::array<std::byte, 3> abc = {std::byte{'a'}, std::byte{'b'}, std::byte{'c'}};
  require(block01::sha256_hex(abc) ==
              "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
          "SHA256 abc vector mismatch");
  block01::StreamingSha256 stream;
  stream.update(std::span<const std::byte>(abc.data(), 1));
  stream.update(std::span<const std::byte>(abc.data() + 1, 2));
  require(stream.finish_hex() ==
              "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
          "streaming SHA256 mismatch");
}

void test_history128() {
  block01::History128 history = 0;
  for (std::uint32_t value = 0; value < 16; ++value) {
    history = block01::history_append(history, static_cast<std::uint8_t>(value + 1), 256);
  }
  require(block01::history_prefix(history, 16, 256) == history,
          "B depth-16 prefix lost high bits");
  require(block01::history_digit(history, 0, 256) == 16,
          "B most recent digit mismatch");
  require(block01::history_digit(history, 15, 256) == 1,
          "B oldest digit mismatch");
  const block01::History128 changed_high = history ^ (block01::History128{1} << 120);
  require(block01::history_prefix(history, 16, 256) !=
              block01::history_prefix(changed_high, 16, 256),
          "B full histories differing above bit 64 collided");
}

void test_reference_fixtures(const std::filesystem::path& root) {
  const std::vector<std::uint8_t> a = {0, 0, 1, 31, 1, 0, 31, 31, 2, 2, 2, 0};
  const std::vector<std::uint64_t> checkpoints_a = {1, 2, 5, 12};
  const auto expected_a = naive_reference(a, 32, 16, checkpoints_a);
  const auto actual_a = run_engine(root, "reference-a", a, 32, 16, checkpoints_a, 2);
  compare_reference(actual_a, expected_a, 32);

  std::vector<std::uint8_t> b;
  for (std::uint32_t value = 0; value < 256; ++value) b.push_back(static_cast<std::uint8_t>(value));
  b.insert(b.end(), {32, 65, 66, 9, 255, 10, 67});
  const std::vector<std::uint64_t> checkpoints_b = {1, 32, 256, b.size()};
  const auto expected_b = naive_reference(b, 256, 16, checkpoints_b);
  const auto actual_b = run_engine(root, "reference-b", b, 256, 16, checkpoints_b, 2);
  compare_reference(actual_b, expected_b, 256);
  require(actual_b.metrics.page_evictions > 0, "small B cache did not spill");
}

void test_forced_spill_equivalence(const std::filesystem::path& root) {
  const std::vector<std::uint8_t> bytes = deterministic_fixture(4096, 32);
  const std::vector<std::uint64_t> checkpoints = {64, 257, 1024, 4096};
  const auto expected = naive_reference(bytes, 32, 16, checkpoints);
  const auto tiny = run_engine(root, "spill-tiny", bytes, 32, 16, checkpoints, 1);
  const auto larger = run_engine(root, "spill-large", bytes, 32, 16, checkpoints, 128);
  compare_reference(tiny, expected, 32);
  compare_reference(larger, expected, 32);
  require(tiny.metrics.page_evictions > 20, "forced-spill fixture did not churn pages");
  require(tiny.metrics.cache_index_rebuilds > 0, "cache tombstone index never rebuilt");
  for (std::size_t checkpoint = 0; checkpoint < tiny.checkpoints.size(); ++checkpoint) {
    for (std::size_t k = 0; k < tiny.checkpoints[checkpoint].losses.size(); ++k) {
      require(std::bit_cast<std::uint64_t>(tiny.checkpoints[checkpoint].losses[k]) ==
                  std::bit_cast<std::uint64_t>(larger.checkpoints[checkpoint].losses[k]),
              "cache-size KT loss mismatch");
    }
  }
}

void test_global_bijection_invariance(const std::filesystem::path& root) {
  const std::vector<std::uint8_t> original = deterministic_fixture(768, 32);
  std::vector<std::uint8_t> permuted = original;
  for (std::uint8_t& value : permuted) value = static_cast<std::uint8_t>((value + 7) % 32);
  const std::vector<std::uint64_t> checkpoints = {128, 768};
  const auto first = run_engine(root, "bijection-original", original, 32, 12, checkpoints, 4);
  const auto second = run_engine(root, "bijection-permuted", permuted, 32, 12, checkpoints, 4);
  for (std::size_t checkpoint = 0; checkpoint < first.checkpoints.size(); ++checkpoint) {
    for (std::size_t k = 0; k < first.checkpoints[checkpoint].losses.size(); ++k) {
      require(std::bit_cast<std::uint64_t>(first.checkpoints[checkpoint].losses[k]) ==
                  std::bit_cast<std::uint64_t>(second.checkpoints[checkpoint].losses[k]),
              "global bijection changed symmetric KT loss");
    }
  }
}

void test_metadata_rejections(const std::filesystem::path& root) {
  const std::filesystem::path corpus = root / "invalid-a.bin";
  write_bytes(corpus, {0, 32});
  write_sidecar(corpus, 32, 2);
  block01::EngineOptions options;
  options.k_max = 1;
  options.checkpoints = {2};
  bool rejected = false;
  try {
    static_cast<void>(block01::compute_availability(corpus, options));
  } catch (const std::runtime_error&) {
    rejected = true;
  }
  require(rejected, "Track A byte 32 was not rejected");

  const std::filesystem::path missing = root / "missing-sidecar.bin";
  write_bytes(missing, {0});
  rejected = false;
  try {
    static_cast<void>(block01::compute_availability(missing, options));
  } catch (const std::runtime_error&) {
    rejected = true;
  }
  require(rejected, "missing sidecar was not rejected");
}

}  // namespace

int main() {
  const std::filesystem::path root = std::filesystem::temp_directory_path() /
      ("block01-core-tests-" + std::to_string(static_cast<long long>(::getpid())));
  try {
    if (!std::filesystem::create_directory(root)) throw TestFailure("cannot create test directory");
    test_sha256();
    test_history128();
    test_reference_fixtures(root);
    test_forced_spill_equivalence(root);
    test_global_bijection_invariance(root);
    test_metadata_rejections(root);
    std::filesystem::remove_all(root);
    std::cout << "core_tests: all checks passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "core_tests: " << error.what() << '\n';
    std::error_code ignored;
    std::filesystem::remove_all(root, ignored);
    return 1;
  }
}
