#include "block01/kt_engine.hpp"

#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unistd.h>
#include <vector>

namespace {

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

std::vector<std::uint64_t> parse_checkpoints(std::string_view text) {
  std::vector<std::uint64_t> checkpoints;
  if (text.empty()) return checkpoints;
  std::size_t start = 0;
  while (start <= text.size()) {
    const std::size_t comma = text.find(',', start);
    const std::size_t end = comma == std::string_view::npos ? text.size() : comma;
    checkpoints.push_back(parse_u64(text.substr(start, end - start), "--checkpoints"));
    if (comma == std::string_view::npos) break;
    start = comma + 1;
  }
  return checkpoints;
}

void fsync_file(const std::filesystem::path& path) {
  const int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
  if (fd < 0) throw std::runtime_error("open output for fsync: " + std::string(std::strerror(errno)));
  if (::fsync(fd) != 0) {
    const int saved = errno;
    ::close(fd);
    throw std::runtime_error("fsync output: " + std::string(std::strerror(saved)));
  }
  if (::close(fd) != 0) throw std::runtime_error("close output after fsync failed");
}

void fsync_directory(const std::filesystem::path& path) {
  const std::filesystem::path directory = path.parent_path().empty() ? "." : path.parent_path();
  const int fd = ::open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  if (fd < 0) throw std::runtime_error("open output directory for fsync: " +
                                       std::string(std::strerror(errno)));
  if (::fsync(fd) != 0) {
    const int saved = errno;
    ::close(fd);
    throw std::runtime_error("fsync output directory: " + std::string(std::strerror(saved)));
  }
  if (::close(fd) != 0) throw std::runtime_error("close output directory after fsync failed");
}

void atomic_write(const std::filesystem::path& output, const std::string& content) {
  const auto parent = output.parent_path();
  if (!parent.empty() && !std::filesystem::exists(parent)) {
    throw std::invalid_argument("output parent directory does not exist: " + parent.string());
  }
  const std::filesystem::path temporary =
      output.string() + ".tmp." + std::to_string(static_cast<long long>(::getpid()));
  if (std::filesystem::exists(temporary)) {
    throw std::runtime_error("temporary output already exists: " + temporary.string());
  }
  try {
    {
      std::ofstream stream(temporary, std::ios::binary | std::ios::out | std::ios::trunc);
      if (!stream) throw std::runtime_error("cannot create temporary output");
      stream.write(content.data(), static_cast<std::streamsize>(content.size()));
      stream.flush();
      if (!stream) throw std::runtime_error("failed writing temporary output");
    }
    fsync_file(temporary);
    std::filesystem::rename(temporary, output);
    fsync_directory(output);
  } catch (...) {
    std::error_code ignored;
    std::filesystem::remove(temporary, ignored);
    throw;
  }
}

void usage(std::ostream& out) {
  out << "Usage: kt_stream --corpus PATH --output JSON --store PATH --k-max K "
         "--checkpoints n1,n2,... [--metadata PATH] [--cache-mib M|--cache-pages P] "
         "[--keep-store]\n";
}

}  // namespace

int main(int argc, char** argv) {
  try {
    std::filesystem::path corpus;
    std::filesystem::path output;
    block01::EngineOptions options;
    bool keep_store = false;
    bool have_checkpoints = false;

    for (int index = 1; index < argc; ++index) {
      const std::string_view argument(argv[index]);
      const auto value = [&](const char* option) -> std::string_view {
        if (index + 1 >= argc) throw std::invalid_argument(std::string(option) + " requires a value");
        return argv[++index];
      };
      if (argument == "--corpus") {
        corpus = value("--corpus");
      } else if (argument == "--output") {
        output = value("--output");
      } else if (argument == "--store") {
        options.store_path = value("--store");
      } else if (argument == "--metadata") {
        options.metadata_path = value("--metadata");
      } else if (argument == "--k-max") {
        const std::uint64_t parsed = parse_u64(value("--k-max"), "--k-max");
        if (parsed > std::numeric_limits<std::uint32_t>::max()) {
          throw std::overflow_error("--k-max overflows uint32");
        }
        options.k_max = static_cast<std::uint32_t>(parsed);
      } else if (argument == "--checkpoints") {
        options.checkpoints = parse_checkpoints(value("--checkpoints"));
        have_checkpoints = true;
      } else if (argument == "--cache-mib") {
        const std::uint64_t mib = parse_u64(value("--cache-mib"), "--cache-mib");
        if (mib > std::numeric_limits<std::uint64_t>::max() / (1024 * 1024)) {
          throw std::overflow_error("--cache-mib byte conversion overflow");
        }
        options.cache_bytes = mib * 1024 * 1024;
        options.cache_pages_override = 0;
      } else if (argument == "--cache-pages") {
        options.cache_pages_override = parse_u64(value("--cache-pages"), "--cache-pages");
      } else if (argument == "--keep-store") {
        keep_store = true;
      } else if (argument == "--help" || argument == "-h") {
        usage(std::cout);
        return 0;
      } else {
        throw std::invalid_argument("unknown argument: " + std::string(argument));
      }
    }

    if (corpus.empty()) throw std::invalid_argument("--corpus is required");
    if (output.empty()) throw std::invalid_argument("--output is required");
    if (!have_checkpoints) throw std::invalid_argument("--checkpoints is required");

    block01::AvailabilityResult result = block01::compute_availability(corpus, options);
    if (!keep_store && !options.store_path.empty() && std::filesystem::exists(options.store_path)) {
      if (!std::filesystem::remove(options.store_path)) {
        throw std::runtime_error("failed to remove ephemeral count store");
      }
    }
    const std::string json = block01::result_to_json(
        result, corpus, "bounded_CLOCK_cache_exact_fixed_record_disk_trie", keep_store);
    atomic_write(output, json);
    std::cout << output.string() << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "kt_stream: " << error.what() << '\n';
    return 1;
  }
}
