#include "block01/kt_engine.hpp"
#include "design/prng_reference.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unistd.h>

namespace {

struct GeneratorSpec {
  enum class Family { LagCopy, AgreementBlock, IidUniform } family;
  std::string configuration;
  std::uint32_t parameter = 0;
  std::string run_fragment;
  std::string duplicate_provenance;
};

std::uint64_t parse_u64(std::string_view text, const char* option) {
  if (text.empty()) throw std::invalid_argument(std::string(option) + " requires a value");
  std::uint64_t value = 0;
  for (const char c : text) {
    if (c < '0' || c > '9') throw std::invalid_argument(std::string("invalid ") + option);
    const unsigned digit = static_cast<unsigned>(c - '0');
    if (value > (std::numeric_limits<std::uint64_t>::max() - digit) / 10) {
      throw std::overflow_error(std::string(option) + " overflows uint64");
    }
    value = value * 10 + digit;
  }
  return value;
}

bool valid_sha256(std::string_view value) {
  if (value.size() != 64) return false;
  for (const char c : value) {
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
          (c >= 'A' && c <= 'F'))) return false;
  }
  return true;
}

std::string json_escape(std::string_view input) {
  std::ostringstream out;
  for (const unsigned char c : input) {
    switch (c) {
      case '\\': out << "\\\\"; break;
      case '"': out << "\\\""; break;
      case '\n': out << "\\n"; break;
      case '\r': out << "\\r"; break;
      case '\t': out << "\\t"; break;
      default:
        if (c < 0x20) {
          out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
              << static_cast<unsigned>(c) << std::dec;
        } else {
          out << static_cast<char>(c);
        }
    }
  }
  return out.str();
}

std::optional<std::uint32_t> parenthesized_value(std::string_view configuration,
                                                  std::string_view prefix) {
  if (!configuration.starts_with(prefix) || configuration.size() < prefix.size() + 3 ||
      configuration[prefix.size()] != '(' || configuration.back() != ')') return std::nullopt;
  const std::string_view digits = configuration.substr(
      prefix.size() + 1, configuration.size() - prefix.size() - 2);
  const std::uint64_t parsed = parse_u64(digits, "configuration distance");
  if (parsed > std::numeric_limits<std::uint32_t>::max()) return std::nullopt;
  return static_cast<std::uint32_t>(parsed);
}

GeneratorSpec parse_configuration(const std::string& configuration, std::uint64_t seed) {
  if (configuration == "G1") {
    return {GeneratorSpec::Family::LagCopy, configuration, 1, "G1", {}};
  }
  if (configuration == "G2") {
    return {GeneratorSpec::Family::LagCopy, configuration, 5, "G2", {}};
  }
  if (configuration == "G4") {
    return {GeneratorSpec::Family::IidUniform, configuration, 0, "G4", {}};
  }
  if (const auto distance = parenthesized_value(configuration, "G3")) {
    constexpr std::array<std::uint32_t, 9> allowed = {2, 3, 4, 5, 6, 8, 10, 12, 14};
    if (std::find(allowed.begin(), allowed.end(), *distance) == allowed.end()) {
      throw std::invalid_argument("unregistered G3 distance");
    }
    return {GeneratorSpec::Family::AgreementBlock, configuration, *distance,
            "G3_d" + std::to_string(*distance), {}};
  }
  if (const auto distance = parenthesized_value(configuration, "G5")) {
    if (*distance != 4 && *distance != 8 && *distance != 12) {
      throw std::invalid_argument("unregistered G5 pair distance");
    }
    std::string provenance = "identical_by_frozen_kernel_to_G5(4)_seed_" +
                             std::to_string(seed) + "; independently_generated_lag2_stream";
    return {GeneratorSpec::Family::LagCopy, configuration, 2,
            "G5_d" + std::to_string(*distance), provenance};
  }
  if (const auto distance = parenthesized_value(configuration, "G6")) {
    if (*distance != 4 && *distance != 8 && *distance != 12) {
      throw std::invalid_argument("unregistered G6 pair distance");
    }
    return {GeneratorSpec::Family::LagCopy, configuration, *distance,
            "G6_d" + std::to_string(*distance), {}};
  }
  throw std::invalid_argument("unknown Track A configuration: " + configuration);
}

void fsync_path(const std::filesystem::path& path, bool directory) {
  const int flags = O_RDONLY | O_CLOEXEC | (directory ? O_DIRECTORY : 0);
  const int fd = ::open(path.c_str(), flags);
  if (fd < 0) throw std::runtime_error("open for fsync: " + std::string(std::strerror(errno)));
  if (::fsync(fd) != 0) {
    const int saved = errno;
    ::close(fd);
    throw std::runtime_error("fsync: " + std::string(std::strerror(saved)));
  }
  if (::close(fd) != 0) throw std::runtime_error("close after fsync failed");
}

void atomic_text_write(const std::filesystem::path& path, const std::string& content) {
  const std::filesystem::path temporary =
      path.string() + ".tmp." + std::to_string(static_cast<long long>(::getpid()));
  if (std::filesystem::exists(path) || std::filesystem::exists(temporary)) {
    throw std::runtime_error("refusing to overwrite metadata path: " + path.string());
  }
  try {
    {
      std::ofstream output(temporary, std::ios::binary | std::ios::out | std::ios::trunc);
      if (!output) throw std::runtime_error("cannot create metadata temporary file");
      output.write(content.data(), static_cast<std::streamsize>(content.size()));
      output.flush();
      if (!output) throw std::runtime_error("failed writing metadata temporary file");
    }
    fsync_path(temporary, false);
    std::filesystem::rename(temporary, path);
    fsync_path(path.parent_path().empty() ? std::filesystem::path(".") : path.parent_path(), true);
  } catch (...) {
    std::error_code ignored;
    std::filesystem::remove(temporary, ignored);
    throw;
  }
}

std::uint8_t next_symbol(const GeneratorSpec& spec, block01::SplitMix64& random,
                         std::array<std::uint8_t, 16>& lag_ring, std::uint64_t position,
                         std::uint8_t& controller) {
  switch (spec.family) {
    case GeneratorSpec::Family::IidUniform:
      return static_cast<std::uint8_t>(random.uniform(32));
    case GeneratorSpec::Family::LagCopy: {
      const std::uint32_t lag = spec.parameter;
      if (position < lag) {
        const std::uint8_t value = static_cast<std::uint8_t>(random.uniform(32));
        lag_ring[static_cast<std::size_t>(position % lag)] = value;
        return value;
      }
      const std::uint64_t coin = random.uniform(4);
      const std::uint8_t innovation = static_cast<std::uint8_t>(random.uniform(32));
      const std::size_t slot = static_cast<std::size_t>(position % lag);
      const std::uint8_t value = coin < 3 ? lag_ring[slot] : innovation;
      lag_ring[slot] = value;
      return value;
    }
    case GeneratorSpec::Family::AgreementBlock: {
      const std::uint32_t distance = spec.parameter;
      const std::uint32_t phase = static_cast<std::uint32_t>(position % (distance + 1));
      if (phase == 0) {
        controller = static_cast<std::uint8_t>(16 + random.uniform(8));
        return controller;
      }
      if (phase == distance) return static_cast<std::uint8_t>(controller + 8);
      return static_cast<std::uint8_t>(random.uniform(16));
    }
  }
  throw std::logic_error("unreachable generator family");
}

void usage(std::ostream& out) {
  out << "Usage: generate_corpus --configuration ID --seed N --n N --output PATH "
         "--execution-manifest-sha256 HEX [--fixture]\n";
}

}  // namespace

int main(int argc, char** argv) {
  try {
    std::string configuration;
    std::uint64_t seed = 0;
    std::uint64_t n = 0;
    std::filesystem::path output_path;
    std::string execution_manifest_sha256;
    bool have_seed = false;
    bool have_n = false;
    bool fixture_only = false;

    for (int index = 1; index < argc; ++index) {
      const std::string_view argument(argv[index]);
      const auto value = [&](const char* option) -> std::string_view {
        if (index + 1 >= argc) throw std::invalid_argument(std::string(option) + " requires a value");
        return argv[++index];
      };
      if (argument == "--configuration") {
        configuration = value("--configuration");
      } else if (argument == "--seed") {
        seed = parse_u64(value("--seed"), "--seed");
        have_seed = true;
      } else if (argument == "--n") {
        n = parse_u64(value("--n"), "--n");
        have_n = true;
      } else if (argument == "--output") {
        output_path = value("--output");
      } else if (argument == "--execution-manifest-sha256") {
        execution_manifest_sha256 = value("--execution-manifest-sha256");
      } else if (argument == "--fixture") {
        fixture_only = true;
      } else if (argument == "--help" || argument == "-h") {
        usage(std::cout);
        return 0;
      } else {
        throw std::invalid_argument("unknown argument: " + std::string(argument));
      }
    }

    if (configuration.empty()) throw std::invalid_argument("--configuration is required");
    if (!have_seed) throw std::invalid_argument("--seed is required");
    if (!have_n) throw std::invalid_argument("--n is required");
    if (output_path.empty()) throw std::invalid_argument("--output is required");
    if (!valid_sha256(execution_manifest_sha256)) {
      throw std::invalid_argument("--execution-manifest-sha256 must be 64 hexadecimal digits");
    }
    constexpr std::array<std::uint64_t, 5> registered_seeds = {101, 202, 303, 404, 505};
    if (std::find(registered_seeds.begin(), registered_seeds.end(), seed) ==
        registered_seeds.end()) {
      throw std::invalid_argument("seed is not registered in Rev B");
    }
    if (!fixture_only && n != (UINT64_C(1) << 23)) {
      throw std::invalid_argument("production Track A corpus length must equal 2^23; use --fixture only for deterministic implementation fixtures");
    }
    const std::filesystem::path metadata_path(output_path.string() + ".meta.json");
    const auto parent = output_path.parent_path();
    if (!parent.empty() && !std::filesystem::exists(parent)) {
      throw std::invalid_argument("output parent directory does not exist");
    }
    if (std::filesystem::exists(output_path) || std::filesystem::exists(metadata_path)) {
      throw std::runtime_error("refusing to overwrite corpus or sidecar");
    }

    const GeneratorSpec spec = parse_configuration(configuration, seed);
    const std::filesystem::path temporary =
        output_path.string() + ".tmp." + std::to_string(static_cast<long long>(::getpid()));
    if (std::filesystem::exists(temporary)) throw std::runtime_error("temporary corpus already exists");

    block01::SplitMix64 random(seed);
    block01::StreamingSha256 hasher;
    std::array<std::uint8_t, 16> lag_ring{};
    std::uint8_t controller = 0;
    std::array<std::byte, block01::kInputChunkBytes> buffer{};
    std::size_t buffered = 0;
    try {
      std::ofstream output(temporary, std::ios::binary | std::ios::out | std::ios::trunc);
      if (!output) throw std::runtime_error("cannot create temporary corpus");
      for (std::uint64_t position = 0; position < n; ++position) {
        const std::uint8_t symbol = next_symbol(spec, random, lag_ring, position, controller);
        buffer[buffered++] = std::byte(symbol);
        if (buffered == buffer.size()) {
          output.write(reinterpret_cast<const char*>(buffer.data()),
                       static_cast<std::streamsize>(buffered));
          if (!output) throw std::runtime_error("failed writing corpus");
          hasher.update(std::span<const std::byte>(buffer.data(), buffered));
          buffered = 0;
        }
      }
      if (buffered != 0) {
        output.write(reinterpret_cast<const char*>(buffer.data()),
                     static_cast<std::streamsize>(buffered));
        if (!output) throw std::runtime_error("failed writing final corpus chunk");
        hasher.update(std::span<const std::byte>(buffer.data(), buffered));
      }
      output.flush();
      if (!output) throw std::runtime_error("failed flushing corpus");
      output.close();
      if (!output) throw std::runtime_error("failed closing corpus");
      fsync_path(temporary, false);
      std::filesystem::rename(temporary, output_path);
      fsync_path(parent.empty() ? std::filesystem::path(".") : parent, true);
    } catch (...) {
      std::error_code ignored;
      std::filesystem::remove(temporary, ignored);
      throw;
    }

    const std::string corpus_sha256 = hasher.finish_hex();
    const std::string run_id = (fixture_only ? "fixture_" : "") +
                               std::string("A_") + spec.run_fragment + "_s" +
                               std::to_string(seed);
    std::ostringstream sidecar;
    sidecar << "{\n"
            << "  \"schema\": \"" << block01::kCorpusSchema << "\",\n"
            << "  \"track\": \"A\",\n"
            << "  \"alphabet_size\": 32,\n"
            << "  \"expected_n\": " << n << ",\n"
            << "  \"run_id\": \"" << json_escape(run_id) << "\",\n"
            << "  \"corpus_sha256\": \"" << corpus_sha256 << "\",\n"
            << "  \"protocol_sha256\": \"" << block01::kExpectedProtocolSha256 << "\",\n"
            << "  \"freeze_sha256\": \"" << block01::kExpectedFreezeSha256 << "\",\n"
            << "  \"execution_manifest_sha256\": \""
            << execution_manifest_sha256 << "\",\n"
            << "  \"configuration\": \"" << json_escape(configuration) << "\",\n"
            << "  \"seed\": " << seed << ",\n"
            << "  \"generator_family\": \""
            << (spec.family == GeneratorSpec::Family::LagCopy ? "lag_copy" :
                spec.family == GeneratorSpec::Family::AgreementBlock ? "agreement_block" :
                                                                      "iid_uniform")
            << "\",\n"
            << "  \"generator_parameter\": " << spec.parameter << ",\n"
            << "  \"prng_sha256\": \"a38ce3bd9dbf751f40b92c5ebea85c191e60c71d935b134068944651582b7542\",\n"
            << "  \"duplicate_provenance\": \"" << json_escape(spec.duplicate_provenance)
            << "\",\n"
            << "  \"fixture_only\": " << (fixture_only ? "true" : "false") << "\n}\n";
    try {
      atomic_text_write(metadata_path, sidecar.str());
    } catch (...) {
      std::error_code ignored;
      std::filesystem::remove(output_path, ignored);
      throw;
    }

    std::cout << output_path.string() << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "generate_corpus: " << error.what() << '\n';
    return 1;
  }
}
