#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <span>
#include <string>
#include <vector>

namespace block01 {

inline constexpr std::uint32_t kMaximumOrder = 16;
inline constexpr std::size_t kInputChunkBytes = 65536;
inline constexpr std::size_t kStorePageBytes = 65536;
inline constexpr const char* kCorpusSchema = "block01-corpus-v1";
inline constexpr const char* kResultSchema = "block01-availability-surface-v1";
inline constexpr const char* kExpectedProtocolSha256 =
    "9180c10578a1c2f15f96e97ff93893e5e4889dad417531d50b8bc97c81fd04b2";
inline constexpr const char* kExpectedFreezeSha256 =
    "ec2a97849acc0d93c71d2f8af9744808950e748d6056d5e71bef764d3ae63036";

struct CorpusMetadata {
  std::string schema;
  std::string track;
  std::uint32_t alphabet_size = 0;
  std::uint64_t expected_n = 0;
  std::string run_id;
  std::string corpus_sha256;
  std::string protocol_sha256;
  std::string freeze_sha256;
  std::string execution_manifest_sha256;
  std::string configuration;
  std::uint64_t seed = 0;
  bool has_seed = false;
  std::string source_manifest_sha256;
  std::string corpus;
  std::string draw_id;
  std::string transformation_provenance;
};

struct EngineOptions {
  std::uint32_t k_max = kMaximumOrder;
  std::vector<std::uint64_t> checkpoints;
  std::uint64_t cache_bytes = UINT64_C(2) * 1024 * 1024 * 1024;
  std::uint64_t cache_pages_override = 0;
  std::filesystem::path store_path;
  std::filesystem::path metadata_path;
};

struct EngineMetrics {
  std::uint64_t input_bytes = 0;
  std::uint64_t input_read_calls = 0;
  std::uint64_t nodes = 0;
  std::uint64_t leaves_created = 0;
  std::uint64_t divergence_splits = 0;
  std::uint64_t endpoint_splits = 0;
  std::uint64_t page_capacity = 0;
  std::uint64_t page_hits = 0;
  std::uint64_t page_misses = 0;
  std::uint64_t page_evictions = 0;
  std::uint64_t dirty_writebacks = 0;
  std::uint64_t cache_index_rebuilds = 0;
  std::uint64_t page_reads = 0;
  std::uint64_t page_writes = 0;
  std::uint64_t bytes_read = 0;
  std::uint64_t bytes_written = 0;
  std::uint64_t kt_log2_calls = 0;
  std::uint64_t annex_log2_calls = 0;
  std::uint64_t logical_store_bytes = 0;
  std::uint64_t allocated_store_bytes = 0;
  std::uint64_t dense_frontend_bytes = 0;
  std::uint64_t directory_bytes = 0;
  std::uint64_t fixed_cache_data_bytes = 0;
  std::uint64_t fixed_cache_metadata_bytes = 0;
  std::uint64_t peak_rss_kib = 0;
  std::uint64_t logical_scores = 0;
  std::uint64_t logical_updates = 0;
  std::array<std::uint64_t, kMaximumOrder + 1> scores_by_depth{};
  std::array<std::uint64_t, kMaximumOrder + 1> updates_by_depth{};
  double wall_seconds = 0.0;
  double process_cpu_seconds = 0.0;
};

struct OccupancySnapshot {
  std::uint64_t visits = 0;
  std::uint64_t distinct_contexts = 0;
  std::uint64_t singleton_contexts = 0;
  std::uint64_t rare_contexts_lt5 = 0;
  std::uint64_t singleton_visitation_numerator = 0;
  std::uint64_t rare_visitation_numerator = 0;
};

struct WhitespaceSnapshot {
  std::array<std::uint64_t, 3> counts{};
  std::vector<double> losses;  // order-major [k][bucket]
  bool has_aligned_prefix = false;
  std::uint64_t aligned_offset = 0;
  std::vector<double> aligned_losses;
};

struct CheckpointRecord {
  std::uint64_t n = 0;
  std::vector<double> losses;
  std::vector<double> availability;
  std::vector<double> ml_losses;
  std::vector<double> kt_minus_ml;
  std::vector<double> kt_minus_ml_per_symbol;
  std::vector<OccupancySnapshot> occupancy;
  std::vector<std::uint64_t> predicted_symbol_counts;
  std::vector<double> predicted_symbol_losses;  // order-major [k][symbol]
  WhitespaceSnapshot whitespace;
  EngineMetrics metrics;
};

struct AvailabilityResult {
  std::string status = "complete";
  std::uint64_t n = 0;
  std::uint32_t alphabet = 0;
  std::uint32_t k_max = 0;
  CorpusMetadata metadata;
  std::string computed_corpus_sha256;
  std::vector<CheckpointRecord> checkpoints;
  EngineMetrics metrics;
};

AvailabilityResult availability(const std::filesystem::path& corpus_path,
                                std::uint32_t k_max,
                                const std::vector<std::uint64_t>& checkpoints,
                                const EngineOptions& base_options = {});

AvailabilityResult compute_availability(const std::filesystem::path& corpus_path,
                                        const EngineOptions& options);

CorpusMetadata read_corpus_metadata(const std::filesystem::path& metadata_path);
std::string result_to_json(const AvailabilityResult& result,
                           const std::filesystem::path& corpus_path,
                           const std::string& storage_method,
                           bool store_retained);

using History128 = unsigned __int128;
History128 history_append(History128 history, std::uint8_t symbol,
                          std::uint32_t alphabet_size);
History128 history_prefix(History128 history, std::uint32_t depth,
                          std::uint32_t alphabet_size);
std::uint8_t history_digit(History128 history, std::uint32_t index,
                           std::uint32_t alphabet_size);
std::uint32_t common_prefix_depth(History128 lhs, std::uint32_t lhs_depth,
                                  History128 rhs, std::uint32_t rhs_depth,
                                  std::uint32_t alphabet_size);
void checked_increment(std::uint64_t& value, const char* field_name);
std::string double_bits_hex(double value);

class StreamingSha256 {
 public:
  StreamingSha256();
  ~StreamingSha256();
  StreamingSha256(StreamingSha256&&) noexcept;
  StreamingSha256& operator=(StreamingSha256&&) noexcept;
  StreamingSha256(const StreamingSha256&) = delete;
  StreamingSha256& operator=(const StreamingSha256&) = delete;
  void update(std::span<const std::byte> data);
  std::string finish_hex();

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

std::string sha256_hex(std::span<const std::byte> data);
std::string sha256_file(const std::filesystem::path& path);

}  // namespace block01
