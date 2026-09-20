#include "block01/kt_engine.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstring>
#include <ctime>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <utility>

namespace block01 {
namespace {

constexpr std::uint64_t kEmptyPageId = std::numeric_limits<std::uint64_t>::max();
constexpr std::uint64_t kTombstonePageId = kEmptyPageId - 1;
constexpr std::uint8_t kTerminalFlag = 1;
constexpr std::uint32_t kNodeMagic = 0x324e544bU;
constexpr std::size_t kCountsOffset = 32;
constexpr std::size_t kRouteCapacity = kMaximumOrder + 1;
constexpr std::string_view kStoreHeaderMagic = "B01KTS2\n";

std::runtime_error system_error(const std::string& operation) {
  return std::runtime_error(operation + ": " + std::strerror(errno));
}

void checked_add(std::uint64_t& value, std::uint64_t amount, const char* field_name) {
  if (amount > std::numeric_limits<std::uint64_t>::max() - value) {
    throw std::overflow_error(std::string(field_name) + " overflow");
  }
  value += amount;
}

std::uint64_t checked_multiply(std::uint64_t lhs, std::uint64_t rhs,
                               const char* field_name) {
  if (lhs != 0 && rhs > std::numeric_limits<std::uint64_t>::max() / lhs) {
    throw std::overflow_error(std::string(field_name) + " overflow");
  }
  return lhs * rhs;
}

std::uint32_t load_u32_le(const std::byte* data) {
  return static_cast<std::uint32_t>(std::to_integer<unsigned char>(data[0])) |
         (static_cast<std::uint32_t>(std::to_integer<unsigned char>(data[1])) << 8) |
         (static_cast<std::uint32_t>(std::to_integer<unsigned char>(data[2])) << 16) |
         (static_cast<std::uint32_t>(std::to_integer<unsigned char>(data[3])) << 24);
}

void store_u32_le(std::byte* data, std::uint32_t value) {
  for (unsigned i = 0; i < 4; ++i) data[i] = std::byte((value >> (8 * i)) & 0xffU);
}

std::uint64_t load_u64_le(const std::byte* data) {
  std::uint64_t value = 0;
  for (unsigned i = 0; i < 8; ++i) {
    value |= static_cast<std::uint64_t>(std::to_integer<unsigned char>(data[i])) << (8 * i);
  }
  return value;
}

void store_u64_le(std::byte* data, std::uint64_t value) {
  for (unsigned i = 0; i < 8; ++i) data[i] = std::byte((value >> (8 * i)) & 0xffU);
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

bool is_hex_digest(std::string_view value) {
  if (value.size() != 64) return false;
  for (const char c : value) {
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
          (c >= 'A' && c <= 'F'))) {
      return false;
    }
  }
  return true;
}

std::string lowercase_ascii(std::string value) {
  for (char& c : value) {
    if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
  }
  return value;
}

class JsonRootReader {
 public:
  explicit JsonRootReader(std::string text) : text_(std::move(text)) {}

  struct Field {
    enum class Type { String, Number, Other } type = Type::Other;
    std::string value;
  };

  std::map<std::string, Field> parse() {
    skip_space();
    expect('{');
    skip_space();
    std::map<std::string, Field> fields;
    if (consume('}')) {
      ensure_end();
      return fields;
    }
    for (;;) {
      const std::string key = parse_string();
      if (fields.contains(key)) throw std::runtime_error("duplicate JSON metadata key: " + key);
      skip_space();
      expect(':');
      skip_space();
      fields.emplace(key, parse_field());
      skip_space();
      if (consume('}')) break;
      expect(',');
      skip_space();
    }
    ensure_end();
    return fields;
  }

 private:
  void skip_space() {
    while (position_ < text_.size()) {
      const char c = text_[position_];
      if (c != ' ' && c != '\n' && c != '\r' && c != '\t') break;
      ++position_;
    }
  }

  void ensure_end() {
    skip_space();
    if (position_ != text_.size()) throw std::runtime_error("trailing metadata JSON content");
  }

  bool consume(char expected) {
    if (position_ < text_.size() && text_[position_] == expected) {
      ++position_;
      return true;
    }
    return false;
  }

  void expect(char expected) {
    if (!consume(expected)) {
      throw std::runtime_error(std::string("expected '") + expected + "' in metadata JSON");
    }
  }

  static unsigned hex_value(char c) {
    if (c >= '0' && c <= '9') return static_cast<unsigned>(c - '0');
    if (c >= 'a' && c <= 'f') return static_cast<unsigned>(c - 'a' + 10);
    if (c >= 'A' && c <= 'F') return static_cast<unsigned>(c - 'A' + 10);
    throw std::runtime_error("invalid JSON unicode escape");
  }

  std::string parse_string() {
    expect('"');
    std::string output;
    while (position_ < text_.size()) {
      const unsigned char c = static_cast<unsigned char>(text_[position_++]);
      if (c == '"') return output;
      if (c < 0x20) throw std::runtime_error("control byte in metadata JSON string");
      if (c != '\\') {
        output.push_back(static_cast<char>(c));
        continue;
      }
      if (position_ >= text_.size()) throw std::runtime_error("truncated JSON escape");
      const char escaped = text_[position_++];
      switch (escaped) {
        case '"': output.push_back('"'); break;
        case '\\': output.push_back('\\'); break;
        case '/': output.push_back('/'); break;
        case 'b': output.push_back('\b'); break;
        case 'f': output.push_back('\f'); break;
        case 'n': output.push_back('\n'); break;
        case 'r': output.push_back('\r'); break;
        case 't': output.push_back('\t'); break;
        case 'u': {
          if (position_ + 4 > text_.size()) throw std::runtime_error("truncated JSON unicode escape");
          unsigned code = 0;
          for (unsigned i = 0; i < 4; ++i) code = code * 16 + hex_value(text_[position_++]);
          if (code <= 0x7f) {
            output.push_back(static_cast<char>(code));
          } else {
            throw std::runtime_error("non-ASCII escaped metadata value is unsupported");
          }
          break;
        }
        default: throw std::runtime_error("invalid metadata JSON escape");
      }
    }
    throw std::runtime_error("unterminated metadata JSON string");
  }

  std::string parse_number() {
    const std::size_t start = position_;
    if (position_ < text_.size() && text_[position_] == '-') ++position_;
    if (position_ >= text_.size() || text_[position_] < '0' || text_[position_] > '9') {
      throw std::runtime_error("invalid metadata JSON number");
    }
    if (text_[position_] == '0') {
      ++position_;
    } else {
      while (position_ < text_.size() && text_[position_] >= '0' && text_[position_] <= '9') {
        ++position_;
      }
    }
    if (position_ < text_.size() &&
        (text_[position_] == '.' || text_[position_] == 'e' || text_[position_] == 'E')) {
      throw std::runtime_error("metadata numeric fields must be integers");
    }
    return text_.substr(start, position_ - start);
  }

  void skip_compound(char opening) {
    std::vector<char> closings;
    closings.push_back(opening == '{' ? '}' : ']');
    bool in_string = false;
    bool escaped = false;
    while (position_ < text_.size()) {
      const char c = text_[position_++];
      if (in_string) {
        if (escaped) {
          escaped = false;
        } else if (c == '\\') {
          escaped = true;
        } else if (c == '"') {
          in_string = false;
        }
        continue;
      }
      if (c == '"') {
        in_string = true;
      } else if (c == '{') {
        closings.push_back('}');
      } else if (c == '[') {
        closings.push_back(']');
      } else if (c == '}' || c == ']') {
        if (closings.empty() || closings.back() != c) {
          throw std::runtime_error("mismatched metadata JSON compound delimiter");
        }
        closings.pop_back();
        if (closings.empty()) return;
      }
    }
    throw std::runtime_error("unterminated metadata JSON compound value");
  }

  Field parse_field() {
    if (position_ >= text_.size()) throw std::runtime_error("missing metadata JSON value");
    if (text_[position_] == '"') return Field{Field::Type::String, parse_string()};
    if (text_[position_] == '-' || (text_[position_] >= '0' && text_[position_] <= '9')) {
      return Field{Field::Type::Number, parse_number()};
    }
    const std::size_t start = position_;
    if (text_[position_] == '{' || text_[position_] == '[') {
      const char opening = text_[position_++];
      skip_compound(opening);
    } else {
      while (position_ < text_.size()) {
        const char c = text_[position_];
        if (c == ',' || c == '}' || c == ' ' || c == '\n' || c == '\r' || c == '\t') break;
        ++position_;
      }
    }
    if (position_ == start) throw std::runtime_error("invalid metadata JSON value");
    return Field{Field::Type::Other, text_.substr(start, position_ - start)};
  }

  std::string text_;
  std::size_t position_ = 0;
};

const JsonRootReader::Field& require_field(
    const std::map<std::string, JsonRootReader::Field>& fields, const std::string& key) {
  const auto found = fields.find(key);
  if (found == fields.end()) throw std::runtime_error("missing metadata field: " + key);
  return found->second;
}

std::string require_string(const std::map<std::string, JsonRootReader::Field>& fields,
                           const std::string& key) {
  const auto& field = require_field(fields, key);
  if (field.type != JsonRootReader::Field::Type::String || field.value.empty()) {
    throw std::runtime_error("metadata field must be a nonempty string: " + key);
  }
  return field.value;
}

std::uint64_t parse_u64_text(std::string_view value, const std::string& key) {
  if (value.empty() || value.front() == '-') {
    throw std::runtime_error("metadata field must be a nonnegative integer: " + key);
  }
  std::uint64_t result = 0;
  for (const char c : value) {
    if (c < '0' || c > '9') throw std::runtime_error("invalid integer metadata field: " + key);
    const unsigned digit = static_cast<unsigned>(c - '0');
    if (result > (std::numeric_limits<std::uint64_t>::max() - digit) / 10) {
      throw std::runtime_error("integer metadata field overflows uint64: " + key);
    }
    result = result * 10 + digit;
  }
  return result;
}

std::uint64_t require_u64(const std::map<std::string, JsonRootReader::Field>& fields,
                          const std::string& key) {
  const auto& field = require_field(fields, key);
  if (field.type != JsonRootReader::Field::Type::Number) {
    throw std::runtime_error("metadata field must be an integer: " + key);
  }
  return parse_u64_text(field.value, key);
}

std::string optional_scalar(const std::map<std::string, JsonRootReader::Field>& fields,
                            const std::string& key) {
  const auto found = fields.find(key);
  if (found == fields.end()) return {};
  return found->second.value;
}

std::uint64_t next_power_of_two(std::uint64_t value) {
  if (value <= 1) return 1;
  if (value > (UINT64_C(1) << 62)) throw std::overflow_error("cache index capacity overflow");
  --value;
  for (unsigned shift = 1; shift < 64; shift <<= 1) value |= value >> shift;
  return value + 1;
}

std::uint64_t current_peak_rss_kib() {
  struct rusage usage {};
  if (::getrusage(RUSAGE_SELF, &usage) != 0) throw system_error("getrusage");
  return static_cast<std::uint64_t>(usage.ru_maxrss);
}

class Sha256 {
 public:
  Sha256() { reset(); }

  void update(const std::byte* data, std::size_t size) {
    if (size > (std::numeric_limits<std::uint64_t>::max() - total_bytes_)) {
      throw std::overflow_error("SHA256 input length overflow");
    }
    total_bytes_ += static_cast<std::uint64_t>(size);
    while (size != 0) {
      const std::size_t amount = std::min(size, block_.size() - block_size_);
      std::memcpy(block_.data() + block_size_, data, amount);
      block_size_ += amount;
      data += amount;
      size -= amount;
      if (block_size_ == block_.size()) {
        transform(block_.data());
        block_size_ = 0;
      }
    }
  }

  std::string finish_hex() {
    const std::uint64_t bit_length = checked_multiply(total_bytes_, 8, "SHA256 bit length");
    block_[block_size_++] = std::byte{0x80};
    if (block_size_ > 56) {
      std::fill(block_.begin() + static_cast<std::ptrdiff_t>(block_size_), block_.end(),
                std::byte{0});
      transform(block_.data());
      block_size_ = 0;
    }
    std::fill(block_.begin() + static_cast<std::ptrdiff_t>(block_size_), block_.begin() + 56,
              std::byte{0});
    for (unsigned i = 0; i < 8; ++i) {
      block_[63 - i] = std::byte((bit_length >> (8 * i)) & 0xffU);
    }
    transform(block_.data());
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (const std::uint32_t word : state_) out << std::setw(8) << word;
    return out.str();
  }

 private:
  static std::uint32_t rotate_right(std::uint32_t value, unsigned amount) {
    return (value >> amount) | (value << (32 - amount));
  }

  void reset() {
    state_ = {0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
              0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U};
    block_.fill(std::byte{0});
    block_size_ = 0;
    total_bytes_ = 0;
  }

  void transform(const std::byte* block) {
    static constexpr std::array<std::uint32_t, 64> constants = {
        0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU,
        0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U, 0xd807aa98U, 0x12835b01U,
        0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U,
        0xc19bf174U, 0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
        0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU, 0x983e5152U,
        0xa831c66dU, 0xb00327c8U, 0xbf597fc7U, 0xc6e00bf3U, 0xd5a79147U,
        0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU,
        0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
        0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U, 0xd192e819U,
        0xd6990624U, 0xf40e3585U, 0x106aa070U, 0x19a4c116U, 0x1e376c08U,
        0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU,
        0x682e6ff3U, 0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
        0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U};
    std::array<std::uint32_t, 64> words{};
    for (unsigned i = 0; i < 16; ++i) {
      const std::size_t offset = i * 4;
      words[i] = (static_cast<std::uint32_t>(std::to_integer<unsigned char>(block[offset])) << 24) |
                 (static_cast<std::uint32_t>(std::to_integer<unsigned char>(block[offset + 1])) << 16) |
                 (static_cast<std::uint32_t>(std::to_integer<unsigned char>(block[offset + 2])) << 8) |
                 static_cast<std::uint32_t>(std::to_integer<unsigned char>(block[offset + 3]));
    }
    for (unsigned i = 16; i < 64; ++i) {
      const std::uint32_t s0 = rotate_right(words[i - 15], 7) ^
                               rotate_right(words[i - 15], 18) ^ (words[i - 15] >> 3);
      const std::uint32_t s1 = rotate_right(words[i - 2], 17) ^
                               rotate_right(words[i - 2], 19) ^ (words[i - 2] >> 10);
      words[i] = words[i - 16] + s0 + words[i - 7] + s1;
    }
    std::uint32_t a = state_[0];
    std::uint32_t b = state_[1];
    std::uint32_t c = state_[2];
    std::uint32_t d = state_[3];
    std::uint32_t e = state_[4];
    std::uint32_t f = state_[5];
    std::uint32_t g = state_[6];
    std::uint32_t h = state_[7];
    for (unsigned i = 0; i < 64; ++i) {
      const std::uint32_t sum1 = rotate_right(e, 6) ^ rotate_right(e, 11) ^ rotate_right(e, 25);
      const std::uint32_t choose = (e & f) ^ ((~e) & g);
      const std::uint32_t temp1 = h + sum1 + choose + constants[i] + words[i];
      const std::uint32_t sum0 = rotate_right(a, 2) ^ rotate_right(a, 13) ^ rotate_right(a, 22);
      const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
      const std::uint32_t temp2 = sum0 + majority;
      h = g;
      g = f;
      f = e;
      e = d + temp1;
      d = c;
      c = b;
      b = a;
      a = temp1 + temp2;
    }
    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
    state_[5] += f;
    state_[6] += g;
    state_[7] += h;
  }

  std::array<std::uint32_t, 8> state_{};
  std::array<std::byte, 64> block_{};
  std::size_t block_size_ = 0;
  std::uint64_t total_bytes_ = 0;
};

template <std::size_t Alphabet>
struct AlphabetTraits;

template <>
struct AlphabetTraits<32> {
  static constexpr std::size_t alphabet = 32;
  static constexpr std::uint32_t digit_bits = 5;
  static constexpr std::uint32_t dense_max_depth = 3;
  static constexpr std::uint32_t tail_min_depth = 4;
  static constexpr double startup_loss = 5.0;
  static constexpr std::size_t record_bytes = 576;
  static constexpr std::size_t records_per_page = 113;
};

template <>
struct AlphabetTraits<256> {
  static constexpr std::size_t alphabet = 256;
  static constexpr std::uint32_t digit_bits = 8;
  static constexpr std::uint32_t dense_max_depth = 1;
  static constexpr std::uint32_t tail_min_depth = 2;
  static constexpr double startup_loss = 8.0;
  static constexpr std::size_t record_bytes = 4160;
  static constexpr std::size_t records_per_page = 15;
};

template <std::size_t Alphabet>
History128 canonical_mask() {
  if constexpr (Alphabet == 32) return (History128{1} << 80) - 1;
  return ~History128{0};
}

template <std::size_t Alphabet>
History128 append_history(History128 history, std::uint8_t symbol) {
  using Traits = AlphabetTraits<Alphabet>;
  if (static_cast<std::size_t>(symbol) >= Alphabet) {
    throw std::invalid_argument("history symbol outside alphabet");
  }
  const History128 appended = (history << Traits::digit_bits) | symbol;
  if constexpr (Alphabet == 32) return appended & canonical_mask<Alphabet>();
  return appended;
}

template <std::size_t Alphabet>
History128 prefix_history(History128 history, std::uint32_t depth) {
  using Traits = AlphabetTraits<Alphabet>;
  if (depth > kMaximumOrder) throw std::invalid_argument("history prefix depth exceeds 16");
  if (depth == 0) return 0;
  if constexpr (Alphabet == 256) {
    if (depth == kMaximumOrder) return history;
  }
  const unsigned bits = depth * Traits::digit_bits;
  return history & ((History128{1} << bits) - 1);
}

template <std::size_t Alphabet>
std::uint8_t digit_history(History128 history, std::uint32_t index) {
  using Traits = AlphabetTraits<Alphabet>;
  if (index >= kMaximumOrder) throw std::invalid_argument("history digit index exceeds 15");
  const History128 mask = static_cast<History128>(Alphabet - 1);
  return static_cast<std::uint8_t>((history >> (index * Traits::digit_bits)) & mask);
}

template <std::size_t Alphabet>
std::uint32_t common_history(History128 lhs, std::uint32_t lhs_depth,
                             History128 rhs, std::uint32_t rhs_depth) {
  if (lhs_depth > kMaximumOrder || rhs_depth > kMaximumOrder) {
    throw std::invalid_argument("history depth exceeds 16");
  }
  const std::uint32_t limit = std::min(lhs_depth, rhs_depth);
  std::uint32_t depth = 0;
  while (depth < limit && digit_history<Alphabet>(lhs, depth) ==
                                digit_history<Alphabet>(rhs, depth)) {
    ++depth;
  }
  return depth;
}

template <std::size_t Alphabet>
struct HistogramRow {
  std::array<std::uint64_t, Alphabet> counts{};
  std::uint64_t total = 0;
};

template <std::size_t Alphabet>
struct Node {
  History128 key = 0;
  std::uint64_t total = 0;
  std::array<std::uint64_t, Alphabet> counts{};
  std::array<std::uint64_t, Alphabet> children{};
  std::uint8_t depth = 0;
  std::uint8_t flags = 0;
};

template <std::size_t Alphabet>
std::array<std::byte, AlphabetTraits<Alphabet>::record_bytes> encode_node(
    const Node<Alphabet>& node) {
  using Traits = AlphabetTraits<Alphabet>;
  static_assert(Traits::record_bytes % 64 == 0);
  static_assert(kCountsOffset + 16 * Alphabet <= Traits::record_bytes);
  std::array<std::byte, Traits::record_bytes> bytes{};
  store_u32_le(bytes.data(), kNodeMagic);
  bytes[4] = std::byte(node.depth);
  bytes[5] = std::byte(node.flags);
  store_u64_le(bytes.data() + 8, static_cast<std::uint64_t>(node.key));
  store_u64_le(bytes.data() + 16, static_cast<std::uint64_t>(node.key >> 64));
  store_u64_le(bytes.data() + 24, node.total);
  constexpr std::size_t children_offset = kCountsOffset + 8 * Alphabet;
  for (std::size_t i = 0; i < Alphabet; ++i) {
    store_u64_le(bytes.data() + kCountsOffset + i * 8, node.counts[i]);
    store_u64_le(bytes.data() + children_offset + i * 8, node.children[i]);
  }
  return bytes;
}

template <std::size_t Alphabet>
Node<Alphabet> decode_node(const std::byte* bytes, std::uint32_t k_max,
                           std::uint64_t next_id) {
  using Traits = AlphabetTraits<Alphabet>;
  if (load_u32_le(bytes) != kNodeMagic) throw std::runtime_error("corrupt count-store node magic");
  Node<Alphabet> node;
  node.depth = std::to_integer<std::uint8_t>(bytes[4]);
  node.flags = std::to_integer<std::uint8_t>(bytes[5]);
  if ((node.flags & ~kTerminalFlag) != 0) throw std::runtime_error("corrupt node flags");
  if (node.depth < Traits::tail_min_depth || node.depth > k_max) {
    throw std::runtime_error("corrupt count-store node depth");
  }
  node.key = static_cast<History128>(load_u64_le(bytes + 8)) |
             (static_cast<History128>(load_u64_le(bytes + 16)) << 64);
  if (prefix_history<Alphabet>(node.key, node.depth) != node.key) {
    throw std::runtime_error("noncanonical count-store node key");
  }
  node.total = load_u64_le(bytes + 24);
  constexpr std::size_t children_offset = kCountsOffset + 8 * Alphabet;
  std::uint64_t sum = 0;
  for (std::size_t i = 0; i < Alphabet; ++i) {
    node.counts[i] = load_u64_le(bytes + kCountsOffset + i * 8);
    node.children[i] = load_u64_le(bytes + children_offset + i * 8);
    checked_add(sum, node.counts[i], "decoded histogram total");
    if (node.children[i] == kEmptyPageId || node.children[i] == kTombstonePageId ||
        node.children[i] >= next_id) {
      throw std::runtime_error("corrupt count-store child node id");
    }
  }
  if (sum != node.total) throw std::runtime_error("corrupt count-store histogram total");
  return node;
}

class PageCache {
 public:
  PageCache(const std::filesystem::path& path, std::uint64_t capacity_pages,
            EngineMetrics& metrics, std::string initial_header)
      : capacity_(capacity_pages), metrics_(metrics), path_(path) {
    if (capacity_ == 0) throw std::invalid_argument("cache must contain at least one page");
    if (capacity_ > std::numeric_limits<std::size_t>::max() / kStorePageBytes) {
      throw std::overflow_error("cache byte capacity overflow");
    }
    const auto parent = path.parent_path();
    if (!parent.empty() && !std::filesystem::exists(parent)) {
      throw std::invalid_argument("store parent directory does not exist: " + parent.string());
    }
    fd_ = ::open(path.c_str(), O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd_ < 0) throw system_error("open count store");
    try {
      write_header(std::move(initial_header));
      mapping_bytes_ = static_cast<std::size_t>(capacity_) * kStorePageBytes;
      pages_ = static_cast<std::byte*>(::mmap(nullptr, mapping_bytes_, PROT_READ | PROT_WRITE,
                                             MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
      if (pages_ == MAP_FAILED) {
        pages_ = nullptr;
        throw system_error("reserve page cache");
      }
      page_ids_.assign(static_cast<std::size_t>(capacity_), kEmptyPageId);
      dirty_.assign(static_cast<std::size_t>(capacity_), false);
      referenced_.assign(static_cast<std::size_t>(capacity_), false);
      if (capacity_ > std::numeric_limits<std::uint64_t>::max() / 2) {
        throw std::overflow_error("cache index doubling overflow");
      }
      const std::uint64_t hash_capacity = next_power_of_two(capacity_ * 2);
      if (hash_capacity > std::numeric_limits<std::size_t>::max()) {
        throw std::overflow_error("cache index size_t overflow");
      }
      hash_keys_.assign(static_cast<std::size_t>(hash_capacity), kEmptyPageId);
      hash_frames_.assign(static_cast<std::size_t>(hash_capacity), 0);
      hash_mask_ = hash_capacity - 1;
      metrics_.page_capacity = capacity_;
      metrics_.allocated_store_bytes = file_size_;
      metrics_.fixed_cache_data_bytes = mapping_bytes_;
      const std::uint64_t dirty_bytes = (dirty_.capacity() + 7) / 8;
      const std::uint64_t referenced_bytes = (referenced_.capacity() + 7) / 8;
      metrics_.fixed_cache_metadata_bytes = checked_multiply(
          page_ids_.capacity(), sizeof(std::uint64_t), "cache page-id metadata");
      checked_add(metrics_.fixed_cache_metadata_bytes, dirty_bytes, "cache dirty metadata");
      checked_add(metrics_.fixed_cache_metadata_bytes, referenced_bytes,
                  "cache referenced metadata");
      checked_add(metrics_.fixed_cache_metadata_bytes,
                  checked_multiply(hash_keys_.capacity(), sizeof(std::uint64_t),
                                   "cache hash-key metadata"),
                  "cache metadata total");
      checked_add(metrics_.fixed_cache_metadata_bytes,
                  checked_multiply(hash_frames_.capacity(), sizeof(std::uint64_t),
                                   "cache hash-frame metadata"),
                  "cache metadata total");
    } catch (...) {
      cleanup();
      throw;
    }
  }

  PageCache(const PageCache&) = delete;
  PageCache& operator=(const PageCache&) = delete;

  ~PageCache() {
    if (fd_ >= 0) {
      try { flush_pages(); } catch (...) {}
    }
    cleanup();
  }

  std::byte* access(std::uint64_t page_id, bool writing) {
    if (page_id == 0 || page_id == kEmptyPageId || page_id == kTombstonePageId) {
      throw std::out_of_range("reserved count-store page id");
    }
    const std::uint64_t found = find(page_id);
    if (found != kEmptyPageId) {
      const auto frame = static_cast<std::size_t>(found);
      if (frame >= used_frames_ || page_ids_[frame] != page_id) {
        throw std::runtime_error("corrupt cache index frame");
      }
      referenced_[frame] = true;
      if (writing) dirty_[frame] = true;
      checked_increment(metrics_.page_hits, "page hit count");
      return frame_data(frame);
    }
    checked_increment(metrics_.page_misses, "page miss count");
    const std::size_t frame = acquire_frame();
    load_page(frame, page_id);
    insert(page_id, frame);
    if (writing) dirty_[frame] = true;
    return frame_data(frame);
  }

  void flush_pages() {
    for (std::size_t frame = 0; frame < used_frames_; ++frame) {
      if (page_ids_[frame] != kEmptyPageId && dirty_[frame]) write_page(frame);
    }
    if (::fsync(fd_) != 0) throw system_error("fsync count store");
  }

  void finalize_header(const std::string& header) {
    flush_pages();
    write_header(header);
    if (::fsync(fd_) != 0) throw system_error("fsync finalized count store");
  }

  std::uint64_t file_size() const { return file_size_; }

 private:
  void cleanup() noexcept {
    if (pages_ != nullptr) {
      ::munmap(pages_, mapping_bytes_);
      pages_ = nullptr;
    }
    if (fd_ >= 0) {
      ::close(fd_);
      fd_ = -1;
    }
  }

  void write_header(const std::string& header) {
    if (header.size() + kStoreHeaderMagic.size() > kStorePageBytes) {
      throw std::runtime_error("count-store header exceeds one page");
    }
    std::array<std::byte, kStorePageBytes> page{};
    std::memcpy(page.data(), kStoreHeaderMagic.data(), kStoreHeaderMagic.size());
    std::memcpy(page.data() + static_cast<std::ptrdiff_t>(kStoreHeaderMagic.size()),
                header.data(), header.size());
    write_exact(0, page.data(), page.size(), "pwrite count-store header");
    file_size_ = std::max<std::uint64_t>(file_size_, kStorePageBytes);
  }

  void write_exact(std::uint64_t offset, const std::byte* data, std::size_t size,
                   const char* operation) {
    if (offset > static_cast<std::uint64_t>(std::numeric_limits<off_t>::max()) ||
        size > static_cast<std::uint64_t>(std::numeric_limits<off_t>::max()) - offset) {
      throw std::overflow_error("count-store write end offset overflow");
    }
    std::size_t done = 0;
    while (done < size) {
      const ssize_t count = ::pwrite(fd_, data + done, size - done,
                                     static_cast<off_t>(offset + done));
      if (count < 0) {
        if (errno == EINTR) continue;
        throw system_error(operation);
      }
      if (count == 0) throw std::runtime_error("zero-byte count-store pwrite");
      done += static_cast<std::size_t>(count);
    }
  }

  std::byte* frame_data(std::size_t frame) { return pages_ + frame * kStorePageBytes; }

  std::uint64_t hash(std::uint64_t page_id) const {
    page_id ^= page_id >> 30;
    page_id *= UINT64_C(0xbf58476d1ce4e5b9);
    page_id ^= page_id >> 27;
    return page_id & hash_mask_;
  }

  std::uint64_t find(std::uint64_t page_id) const {
    std::uint64_t slot = hash(page_id);
    for (std::size_t probes = 0; probes < hash_keys_.size(); ++probes) {
      const std::uint64_t key = hash_keys_[static_cast<std::size_t>(slot)];
      if (key == kEmptyPageId) return kEmptyPageId;
      if (key == page_id) return hash_frames_[static_cast<std::size_t>(slot)];
      slot = (slot + 1) & hash_mask_;
    }
    return kEmptyPageId;
  }

  void insert(std::uint64_t page_id, std::size_t frame) {
    std::uint64_t slot = hash(page_id);
    std::uint64_t first_tombstone = kEmptyPageId;
    for (std::size_t probes = 0; probes < hash_keys_.size(); ++probes) {
      const std::uint64_t key = hash_keys_[static_cast<std::size_t>(slot)];
      if (key == page_id) throw std::logic_error("duplicate cache page insertion");
      if (key == kTombstonePageId && first_tombstone == kEmptyPageId) first_tombstone = slot;
      if (key == kEmptyPageId) {
        const std::uint64_t destination =
            first_tombstone == kEmptyPageId ? slot : first_tombstone;
        if (first_tombstone != kEmptyPageId) --tombstones_;
        hash_keys_[static_cast<std::size_t>(destination)] = page_id;
        hash_frames_[static_cast<std::size_t>(destination)] = frame;
        return;
      }
      slot = (slot + 1) & hash_mask_;
    }
    if (first_tombstone != kEmptyPageId) {
      --tombstones_;
      hash_keys_[static_cast<std::size_t>(first_tombstone)] = page_id;
      hash_frames_[static_cast<std::size_t>(first_tombstone)] = frame;
      return;
    }
    throw std::runtime_error("fixed cache index unexpectedly full");
  }

  void erase(std::uint64_t page_id) {
    std::uint64_t slot = hash(page_id);
    for (std::size_t probes = 0; probes < hash_keys_.size(); ++probes) {
      const std::uint64_t key = hash_keys_[static_cast<std::size_t>(slot)];
      if (key == kEmptyPageId) throw std::logic_error("missing cache page erasure");
      if (key == page_id) {
        hash_keys_[static_cast<std::size_t>(slot)] = kTombstonePageId;
        ++tombstones_;
        return;
      }
      slot = (slot + 1) & hash_mask_;
    }
    throw std::logic_error("cache page erasure probe exhausted");
  }

  void rebuild_index() {
    std::fill(hash_keys_.begin(), hash_keys_.end(), kEmptyPageId);
    std::fill(hash_frames_.begin(), hash_frames_.end(), 0);
    tombstones_ = 0;
    for (std::size_t frame = 0; frame < used_frames_; ++frame) {
      if (page_ids_[frame] == kEmptyPageId) continue;
      insert(page_ids_[frame], frame);
    }
    checked_increment(metrics_.cache_index_rebuilds, "cache index rebuild count");
  }

  std::size_t acquire_frame() {
    if (used_frames_ < capacity_) return static_cast<std::size_t>(used_frames_++);
    for (;;) {
      const std::size_t frame = static_cast<std::size_t>(clock_hand_);
      clock_hand_ = (clock_hand_ + 1) % capacity_;
      if (referenced_[frame]) {
        referenced_[frame] = false;
        continue;
      }
      if (dirty_[frame]) write_page(frame);
      erase(page_ids_[frame]);
      page_ids_[frame] = kEmptyPageId;
      const std::size_t rebuild_threshold =
          std::max<std::size_t>(1, hash_keys_.size() / 4);
      if (tombstones_ >= rebuild_threshold) rebuild_index();
      checked_increment(metrics_.page_evictions, "page eviction count");
      return frame;
    }
  }

  std::uint64_t page_offset(std::uint64_t page_id) const {
    if (page_id > std::numeric_limits<std::uint64_t>::max() / kStorePageBytes) {
      throw std::overflow_error("count-store page offset overflow");
    }
    const std::uint64_t offset = page_id * kStorePageBytes;
    if (offset > static_cast<std::uint64_t>(std::numeric_limits<off_t>::max()) ||
        kStorePageBytes > static_cast<std::uint64_t>(std::numeric_limits<off_t>::max()) - offset) {
      throw std::overflow_error("count-store page end offset overflow");
    }
    return offset;
  }

  void load_page(std::size_t frame, std::uint64_t page_id) {
    std::byte* destination = frame_data(frame);
    const std::uint64_t offset = page_offset(page_id);
    const bool newly_allocated = page_id == highest_logical_page_ + 1;
    if (page_id > highest_logical_page_ + 1) {
      throw std::runtime_error("nonsequential new count-store page allocation");
    }
    if (newly_allocated) highest_logical_page_ = page_id;
    if (!newly_allocated) {
      if (offset >= file_size_) {
        throw std::runtime_error("allocated count-store page was never persisted");
      }
      if (file_size_ - offset < kStorePageBytes) {
        throw std::runtime_error("truncated allocated count-store page");
      }
      std::size_t done = 0;
      while (done < kStorePageBytes) {
        const ssize_t count = ::pread(fd_, destination + done, kStorePageBytes - done,
                                      static_cast<off_t>(offset + done));
        if (count < 0) {
          if (errno == EINTR) continue;
          throw system_error("pread count store");
        }
        if (count == 0) throw std::runtime_error("short pread of allocated count-store page");
        done += static_cast<std::size_t>(count);
      }
      checked_add(metrics_.bytes_read, done, "count-store bytes read");
      checked_increment(metrics_.page_reads, "count-store page read count");
    } else {
      std::memset(destination, 0, kStorePageBytes);
    }
    page_ids_[frame] = page_id;
    dirty_[frame] = false;
    referenced_[frame] = true;
  }

  void write_page(std::size_t frame) {
    const std::uint64_t page_id = page_ids_[frame];
    if (page_id == kEmptyPageId) throw std::logic_error("write of unused cache frame");
    const std::uint64_t offset = page_offset(page_id);
    write_exact(offset, frame_data(frame), kStorePageBytes, "pwrite count store");
    checked_add(metrics_.bytes_written, kStorePageBytes, "count-store bytes written");
    checked_increment(metrics_.page_writes, "count-store page write count");
    checked_increment(metrics_.dirty_writebacks, "dirty writeback count");
    dirty_[frame] = false;
    file_size_ = std::max(file_size_, offset + kStorePageBytes);
    metrics_.allocated_store_bytes = file_size_;
  }

  int fd_ = -1;
  std::uint64_t capacity_ = 0;
  EngineMetrics& metrics_;
  std::filesystem::path path_;
  std::byte* pages_ = nullptr;
  std::size_t mapping_bytes_ = 0;
  std::vector<std::uint64_t> page_ids_;
  std::vector<bool> dirty_;
  std::vector<bool> referenced_;
  std::vector<std::uint64_t> hash_keys_;
  std::vector<std::uint64_t> hash_frames_;
  std::uint64_t hash_mask_ = 0;
  std::uint64_t used_frames_ = 0;
  std::uint64_t clock_hand_ = 0;
  std::uint64_t file_size_ = 0;
  std::uint64_t highest_logical_page_ = 0;
  std::size_t tombstones_ = 0;
};

template <std::size_t Alphabet>
std::string store_header_json(const CorpusMetadata& metadata, std::uint32_t k_max,
                              std::string_view status, std::uint64_t next_id,
                              std::uint64_t node_count) {
  using Traits = AlphabetTraits<Alphabet>;
  std::ostringstream out;
  out << "{\"schema\":\"block01-count-store-v2\",\"status\":\""
      << json_escape(status) << "\",\"alphabet_size\":" << Alphabet
      << ",\"digit_bits\":" << Traits::digit_bits
      << ",\"dense_max_depth\":" << Traits::dense_max_depth
      << ",\"tail_min_depth\":" << Traits::tail_min_depth
      << ",\"k_max\":" << k_max
      << ",\"page_bytes\":" << kStorePageBytes
      << ",\"record_bytes\":" << Traits::record_bytes
      << ",\"records_per_page\":" << Traits::records_per_page
      << ",\"run_id\":\"" << json_escape(metadata.run_id)
      << "\",\"freeze_sha256\":\"" << metadata.freeze_sha256
      << "\",\"execution_manifest_sha256\":\"" << metadata.execution_manifest_sha256
      << "\",\"next_node_id\":" << next_id << ",\"node_count\":" << node_count
      << ",\"resume_supported\":false,\"fixed_frontend_persisted\":false}";
  return out.str();
}

template <std::size_t Alphabet>
class NodeStore {
 public:
  NodeStore(const std::filesystem::path& path, std::uint64_t cache_pages,
            EngineMetrics& metrics, std::uint32_t k_max, const CorpusMetadata& metadata)
      : cache_(path, cache_pages, metrics,
               store_header_json<Alphabet>(metadata, k_max, "in_progress_invalid_on_crash", 1, 0)),
        metrics_(metrics), k_max_(k_max), metadata_(metadata) {
    using Traits = AlphabetTraits<Alphabet>;
    static_assert(Traits::records_per_page * Traits::record_bytes <= kStorePageBytes);
    static_assert((Traits::records_per_page + 1) * Traits::record_bytes > kStorePageBytes);
  }

  std::uint64_t create(const Node<Alphabet>& node) {
    if (next_id_ >= kTombstonePageId) throw std::overflow_error("count-store node identifier overflow");
    const std::uint64_t id = next_id_;
    ++next_id_;
    write(id, node);
    metrics_.nodes = id;
    metrics_.logical_store_bytes = checked_multiply(
        metrics_.nodes, AlphabetTraits<Alphabet>::record_bytes, "logical store bytes");
    return id;
  }

  Node<Alphabet> read(std::uint64_t id) {
    validate_id(id);
    const auto [page, offset] = locate(id);
    return decode_node<Alphabet>(cache_.access(page, false) + offset, k_max_, next_id_);
  }

  void write(std::uint64_t id, const Node<Alphabet>& node) {
    validate_id(id);
    if (node.depth < AlphabetTraits<Alphabet>::tail_min_depth || node.depth > k_max_ ||
        prefix_history<Alphabet>(node.key, node.depth) != node.key) {
      throw std::invalid_argument("invalid node serialization request");
    }
    const auto [page, offset] = locate(id);
    const auto encoded = encode_node<Alphabet>(node);
    std::memcpy(cache_.access(page, true) + offset, encoded.data(), encoded.size());
  }

  void finalize() {
    cache_.flush_pages();
    metrics_.logical_store_bytes = checked_multiply(metrics_.nodes,
                                                     AlphabetTraits<Alphabet>::record_bytes,
                                                     "logical store bytes");
    metrics_.allocated_store_bytes = cache_.file_size();
    cache_.finalize_header(store_header_json<Alphabet>(
        metadata_, k_max_, "complete_ephemeral_tail_only_no_resume", next_id_, metrics_.nodes));
    metrics_.allocated_store_bytes = cache_.file_size();
  }

 private:
  void validate_id(std::uint64_t id) const {
    if (id == 0 || id >= next_id_ || id == kEmptyPageId || id == kTombstonePageId) {
      throw std::out_of_range("invalid count-store node id");
    }
  }

  static std::pair<std::uint64_t, std::size_t> locate(std::uint64_t id) {
    using Traits = AlphabetTraits<Alphabet>;
    if (id == 0) throw std::out_of_range("node id zero is null");
    const std::uint64_t zero_based = id - 1;
    const std::uint64_t node_page = zero_based / Traits::records_per_page;
    if (node_page >= kTombstonePageId - 1) throw std::overflow_error("node page id overflow");
    const std::uint64_t physical_page = node_page + 1;
    const std::uint64_t slot = zero_based % Traits::records_per_page;
    const std::uint64_t offset_u64 = checked_multiply(slot, Traits::record_bytes,
                                                      "node page record offset");
    if (offset_u64 > std::numeric_limits<std::size_t>::max()) {
      throw std::overflow_error("node page record size_t overflow");
    }
    if (offset_u64 + Traits::record_bytes > kStorePageBytes) {
      throw std::overflow_error("node record crosses store page");
    }
    return {physical_page, static_cast<std::size_t>(offset_u64)};
  }

  PageCache cache_;
  EngineMetrics& metrics_;
  std::uint32_t k_max_;
  CorpusMetadata metadata_;
  std::uint64_t next_id_ = 1;
};

struct RouteEntry {
  std::uint64_t node_id = 0;
  std::uint8_t first_depth = 0;
  std::uint8_t last_depth = 0;
};

template <std::size_t Alphabet>
class TailTrie {
 public:
  TailTrie(const EngineOptions& options, EngineMetrics& metrics,
           const CorpusMetadata& metadata)
      : directory_(directory_size(), 0),
        store_(options.store_path, cache_pages(options), metrics, options.k_max, metadata),
        metrics_(metrics), k_max_(options.k_max) {
    metrics_.directory_bytes = checked_multiply(directory_.size(), sizeof(std::uint64_t),
                                                "directory bytes");
  }

  std::array<RouteEntry, kRouteCapacity> ensure_and_route(History128 key, std::uint8_t depth,
                                                          std::size_t& route_size) {
    using Traits = AlphabetTraits<Alphabet>;
    if (depth < Traits::tail_min_depth || depth > k_max_) {
      throw std::invalid_argument("invalid tail depth");
    }
    key = prefix_history<Alphabet>(key, depth);
    const std::size_t directory_index = static_cast<std::size_t>(
        prefix_history<Alphabet>(key, Traits::tail_min_depth));
    if (directory_index >= directory_.size()) throw std::runtime_error("tail directory index overflow");
    std::uint64_t root = directory_[directory_index];
    if (root == 0) {
      Node<Alphabet> leaf;
      leaf.key = key;
      leaf.depth = depth;
      leaf.flags = kTerminalFlag;
      root = store_.create(leaf);
      directory_[directory_index] = root;
      checked_increment(metrics_.leaves_created, "leaf count");
      return collect_route(key, depth, root, route_size);
    }

    std::uint64_t parent_id = 0;
    std::uint8_t parent_depth = static_cast<std::uint8_t>(Traits::dense_max_depth);
    std::uint8_t parent_digit = 0;
    std::uint64_t node_id = root;

    for (;;) {
      Node<Alphabet> node = store_.read(node_id);
      const std::uint32_t common = common_history<Alphabet>(key, depth, node.key, node.depth);
      if (common < node.depth) {
        if (common < Traits::tail_min_depth || common <= parent_depth) {
          throw std::runtime_error("corrupt trie parent/child prefix relation");
        }
        if (common == depth) {
          Node<Alphabet> endpoint;
          endpoint.key = prefix_history<Alphabet>(key, common);
          endpoint.depth = static_cast<std::uint8_t>(common);
          endpoint.flags = kTerminalFlag;
          endpoint.total = node.total;
          endpoint.counts = node.counts;
          const std::uint8_t old_digit = digit_history<Alphabet>(node.key, common);
          endpoint.children[old_digit] = node_id;
          const std::uint64_t endpoint_id = store_.create(endpoint);
          replace_link(directory_index, parent_id, parent_digit, endpoint_id);
          checked_increment(metrics_.endpoint_splits, "endpoint split count");
          return collect_route(key, depth, directory_[directory_index], route_size);
        }

        Node<Alphabet> branch;
        branch.key = prefix_history<Alphabet>(key, common);
        branch.depth = static_cast<std::uint8_t>(common);
        branch.total = node.total;
        branch.counts = node.counts;
        const std::uint8_t old_digit = digit_history<Alphabet>(node.key, common);
        const std::uint8_t new_digit = digit_history<Alphabet>(key, common);
        if (old_digit == new_digit) throw std::runtime_error("invalid divergence split digit");
        branch.children[old_digit] = node_id;

        Node<Alphabet> leaf;
        leaf.key = key;
        leaf.depth = depth;
        leaf.flags = kTerminalFlag;
        const std::uint64_t leaf_id = store_.create(leaf);
        branch.children[new_digit] = leaf_id;
        const std::uint64_t branch_id = store_.create(branch);
        replace_link(directory_index, parent_id, parent_digit, branch_id);
        checked_increment(metrics_.leaves_created, "leaf count");
        checked_increment(metrics_.divergence_splits, "divergence split count");
        return collect_route(key, depth, directory_[directory_index], route_size);
      }

      if (node.depth == depth) {
        if ((node.flags & kTerminalFlag) == 0) {
          node.flags |= kTerminalFlag;
          store_.write(node_id, node);
        }
        return collect_route(key, depth, directory_[directory_index], route_size);
      }
      if (node.depth > depth) throw std::runtime_error("trie endpoint split was not applied");

      const std::uint8_t digit = digit_history<Alphabet>(key, node.depth);
      const std::uint64_t child = node.children[digit];
      if (child == 0) {
        Node<Alphabet> leaf;
        leaf.key = key;
        leaf.depth = depth;
        leaf.flags = kTerminalFlag;
        const std::uint64_t leaf_id = store_.create(leaf);
        node.children[digit] = leaf_id;
        store_.write(node_id, node);
        checked_increment(metrics_.leaves_created, "leaf count");
        return collect_route(key, depth, directory_[directory_index], route_size);
      }
      parent_id = node_id;
      parent_depth = node.depth;
      parent_digit = digit;
      node_id = child;
    }
  }

  Node<Alphabet> read(std::uint64_t id) { return store_.read(id); }
  void write(std::uint64_t id, const Node<Alphabet>& node) { store_.write(id, node); }
  void finalize() { store_.finalize(); }

 private:
  static std::uint64_t cache_pages(const EngineOptions& options) {
    if (options.cache_pages_override != 0) return options.cache_pages_override;
    if (options.cache_bytes == 0 || options.cache_bytes % kStorePageBytes != 0) {
      throw std::invalid_argument("cache_bytes must be a positive multiple of 65536");
    }
    return options.cache_bytes / kStorePageBytes;
  }

  static std::size_t directory_size() {
    using Traits = AlphabetTraits<Alphabet>;
    std::uint64_t size = 1;
    for (std::uint32_t depth = 0; depth < Traits::tail_min_depth; ++depth) {
      size = checked_multiply(size, Alphabet, "tail directory size");
    }
    if (size > std::numeric_limits<std::size_t>::max()) {
      throw std::overflow_error("tail directory size_t overflow");
    }
    return static_cast<std::size_t>(size);
  }

  void replace_link(std::size_t directory_index, std::uint64_t parent_id,
                    std::uint8_t parent_digit, std::uint64_t replacement) {
    if (parent_id == 0) {
      directory_[directory_index] = replacement;
      return;
    }
    Node<Alphabet> parent = store_.read(parent_id);
    parent.children[parent_digit] = replacement;
    store_.write(parent_id, parent);
  }

  std::array<RouteEntry, kRouteCapacity> collect_route(History128 key, std::uint8_t depth,
                                                       std::uint64_t root,
                                                       std::size_t& route_size) {
    using Traits = AlphabetTraits<Alphabet>;
    std::array<RouteEntry, kRouteCapacity> route{};
    route_size = 0;
    std::uint8_t parent_depth = static_cast<std::uint8_t>(Traits::dense_max_depth);
    std::uint64_t node_id = root;
    while (true) {
      if (route_size >= route.size()) throw std::runtime_error("tail route exceeds order bound");
      const Node<Alphabet> node = store_.read(node_id);
      if (node.depth <= parent_depth || node.depth > depth ||
          common_history<Alphabet>(key, depth, node.key, node.depth) != node.depth) {
        throw std::runtime_error("corrupt trie route");
      }
      route[route_size++] = RouteEntry{node_id, static_cast<std::uint8_t>(parent_depth + 1),
                                       node.depth};
      if (node.depth == depth) return route;
      parent_depth = node.depth;
      node_id = node.children[digit_history<Alphabet>(key, node.depth)];
      if (node_id == 0) throw std::runtime_error("missing trie route child");
    }
  }

  std::vector<std::uint64_t> directory_;
  NodeStore<Alphabet> store_;
  EngineMetrics& metrics_;
  std::uint32_t k_max_;
};

template <std::size_t Alphabet>
std::vector<std::size_t> dense_offsets(std::uint32_t maximum_depth) {
  std::vector<std::size_t> offsets(maximum_depth + 1, 0);
  std::uint64_t rows = 0;
  std::uint64_t power = 1;
  for (std::uint32_t depth = 0; depth <= maximum_depth; ++depth) {
    if (rows > std::numeric_limits<std::size_t>::max()) {
      throw std::overflow_error("dense frontend offset overflow");
    }
    offsets[depth] = static_cast<std::size_t>(rows);
    rows += power;
    if (depth != maximum_depth) power = checked_multiply(power, Alphabet, "dense frontend rows");
  }
  return offsets;
}

template <std::size_t Alphabet>
std::size_t dense_row_count(std::uint32_t maximum_depth) {
  const auto offsets = dense_offsets<Alphabet>(maximum_depth);
  std::uint64_t power = 1;
  for (std::uint32_t depth = 0; depth < maximum_depth; ++depth) {
    power = checked_multiply(power, Alphabet, "dense final depth rows");
  }
  const std::uint64_t count = static_cast<std::uint64_t>(offsets.back()) + power;
  if (count > std::numeric_limits<std::size_t>::max()) {
    throw std::overflow_error("dense row count size_t overflow");
  }
  return static_cast<std::size_t>(count);
}

template <std::size_t Alphabet>
std::size_t dense_index(History128 history, std::uint32_t depth,
                        const std::vector<std::size_t>& offsets) {
  const History128 prefix = prefix_history<Alphabet>(history, depth);
  if (prefix > std::numeric_limits<std::size_t>::max()) {
    throw std::overflow_error("dense history index overflow");
  }
  const std::size_t index = offsets.at(depth) + static_cast<std::size_t>(prefix);
  return index;
}

double ml_f(std::uint64_t value, EngineMetrics& metrics) {
  if (value <= 1) return 0.0;
  checked_increment(metrics.annex_log2_calls, "Annex log2 call count");
  return static_cast<double>(value) * std::log2(static_cast<double>(value));
}

double ml_g(std::uint64_t value, EngineMetrics& metrics) {
  if (value == std::numeric_limits<std::uint64_t>::max()) {
    throw std::overflow_error("ML recurrence counter overflow");
  }
  return ml_f(value + 1, metrics) - ml_f(value, metrics);
}

double ml_increment(std::uint64_t total, std::uint64_t count, EngineMetrics& metrics) {
  return ml_g(total, metrics) - ml_g(count, metrics);
}

template <std::size_t Alphabet>
double kt_loss(std::uint64_t count, std::uint64_t total, EngineMetrics& metrics) {
  using Traits = AlphabetTraits<Alphabet>;
  if (total == 0) return Traits::startup_loss;
  checked_increment(metrics.kt_log2_calls, "KT log2 call count");
  return -std::log2((static_cast<double>(count) + 0.5) /
                    (static_cast<double>(total) + static_cast<double>(Alphabet) / 2.0));
}

void checked_decrement(std::uint64_t& value, std::uint64_t amount, const char* field_name) {
  if (amount > value) throw std::runtime_error(std::string(field_name) + " underflow");
  value -= amount;
}

void update_occupancy(OccupancySnapshot& occupancy, std::uint64_t old_total) {
  checked_increment(occupancy.visits, "occupancy visits");
  if (old_total == 0) {
    checked_increment(occupancy.distinct_contexts, "distinct contexts");
    checked_increment(occupancy.singleton_contexts, "singleton contexts");
    checked_increment(occupancy.rare_contexts_lt5, "rare contexts");
    checked_increment(occupancy.singleton_visitation_numerator, "singleton visitation");
    checked_increment(occupancy.rare_visitation_numerator, "rare visitation");
  } else if (old_total == 1) {
    checked_decrement(occupancy.singleton_contexts, 1, "singleton contexts");
    checked_decrement(occupancy.singleton_visitation_numerator, 1, "singleton visitation");
    checked_increment(occupancy.rare_visitation_numerator, "rare visitation");
  } else if (old_total == 2 || old_total == 3) {
    checked_increment(occupancy.rare_visitation_numerator, "rare visitation");
  } else if (old_total == 4) {
    checked_decrement(occupancy.rare_contexts_lt5, 1, "rare contexts");
    checked_decrement(occupancy.rare_visitation_numerator, 4, "rare visitation");
  }
}

bool is_ascii_whitespace(std::uint8_t symbol) {
  return symbol == 9 || symbol == 10 || symbol == 11 || symbol == 12 || symbol == 13 ||
         symbol == 32;
}

EngineMetrics checkpoint_metrics(const EngineMetrics& metrics,
                                 const std::chrono::steady_clock::time_point& wall_start,
                                 std::clock_t cpu_start) {
  EngineMetrics snapshot = metrics;
  snapshot.wall_seconds = std::chrono::duration<double>(
      std::chrono::steady_clock::now() - wall_start).count();
  snapshot.process_cpu_seconds = static_cast<double>(std::clock() - cpu_start) /
                                 static_cast<double>(CLOCKS_PER_SEC);
  snapshot.peak_rss_kib = current_peak_rss_kib();
  return snapshot;
}

void validate_checkpoints(const std::vector<std::uint64_t>& checkpoints,
                          std::uint64_t expected_n) {
  std::uint64_t previous = 0;
  for (const std::uint64_t checkpoint : checkpoints) {
    if (checkpoint == 0 || checkpoint <= previous) {
      throw std::invalid_argument("checkpoints must be positive, unique, and strictly increasing");
    }
    if (checkpoint > expected_n) {
      throw std::invalid_argument("checkpoint exceeds sidecar expected_n");
    }
    previous = checkpoint;
  }
  if (expected_n != 0 && checkpoints.empty()) {
    throw std::invalid_argument("nonempty corpus metadata requires at least one checkpoint");
  }
}

template <std::size_t Alphabet>
CheckpointRecord make_checkpoint(
    std::uint64_t n, const std::vector<double>& losses, const std::vector<double>& ml_losses,
    const std::vector<OccupancySnapshot>& occupancy,
    const std::vector<std::uint64_t>& symbol_counts,
    const std::vector<double>& symbol_losses,
    const std::array<std::uint64_t, 3>& whitespace_counts,
    const std::vector<double>& whitespace_losses, bool has_aligned_prefix,
    std::uint64_t aligned_offset, const std::vector<double>& aligned_losses,
    const EngineMetrics& metrics, const std::chrono::steady_clock::time_point& wall_start,
    std::clock_t cpu_start) {
  CheckpointRecord record;
  record.n = n;
  record.losses = losses;
  record.ml_losses = ml_losses;
  record.availability.assign(losses.size(), 0.0);
  record.kt_minus_ml.assign(losses.size(), 0.0);
  record.kt_minus_ml_per_symbol.assign(losses.size(), 0.0);
  for (std::size_t k = 0; k < losses.size(); ++k) {
    record.availability[k] = k == 0 ? 0.0 : (losses[0] - losses[k]) / static_cast<double>(n);
    record.kt_minus_ml[k] = losses[k] - ml_losses[k];
    record.kt_minus_ml_per_symbol[k] = record.kt_minus_ml[k] / static_cast<double>(n);
  }
  record.occupancy = occupancy;
  if constexpr (Alphabet == 32) {
    record.predicted_symbol_counts = symbol_counts;
    record.predicted_symbol_losses = symbol_losses;
  } else {
    record.whitespace.counts = whitespace_counts;
    record.whitespace.losses = whitespace_losses;
    record.whitespace.has_aligned_prefix = has_aligned_prefix;
    record.whitespace.aligned_offset = aligned_offset;
    record.whitespace.aligned_losses = aligned_losses;
  }
  record.metrics = checkpoint_metrics(metrics, wall_start, cpu_start);
  return record;
}

template <std::size_t Alphabet>
AvailabilityResult compute_typed(const std::filesystem::path& corpus_path,
                                 const EngineOptions& options,
                                 const CorpusMetadata& metadata) {
  using Traits = AlphabetTraits<Alphabet>;
  if (options.k_max > kMaximumOrder) throw std::invalid_argument("k_max must be in 0..16");
  validate_checkpoints(options.checkpoints, metadata.expected_n);
  if (options.k_max >= Traits::tail_min_depth && options.store_path.empty()) {
    throw std::invalid_argument("store_path is required for orders using external tail state");
  }

  std::ifstream input(corpus_path, std::ios::binary);
  if (!input) throw std::runtime_error("cannot open corpus: " + corpus_path.string());

  AvailabilityResult result;
  result.k_max = options.k_max;
  result.alphabet = Alphabet;
  result.metadata = metadata;
  result.checkpoints.reserve(options.checkpoints.size());

  const std::uint32_t dense_depth = std::min<std::uint32_t>(Traits::dense_max_depth,
                                                            options.k_max);
  const std::vector<std::size_t> offsets = dense_offsets<Alphabet>(dense_depth);
  std::vector<HistogramRow<Alphabet>> dense(dense_row_count<Alphabet>(dense_depth));
  result.metrics.dense_frontend_bytes = checked_multiply(
      dense.size(), sizeof(HistogramRow<Alphabet>), "dense frontend bytes");

  std::unique_ptr<TailTrie<Alphabet>> tail;
  if (options.k_max >= Traits::tail_min_depth) {
    tail = std::make_unique<TailTrie<Alphabet>>(options, result.metrics, metadata);
  }

  std::vector<double> losses(options.k_max + 1, 0.0);
  std::vector<double> ml_losses(options.k_max + 1, 0.0);
  std::vector<OccupancySnapshot> occupancy(options.k_max + 1);
  std::vector<std::uint64_t> symbol_counts(Alphabet == 32 ? Alphabet : 0, 0);
  std::vector<double> symbol_losses(Alphabet == 32 ? (options.k_max + 1) * Alphabet : 0, 0.0);
  std::array<std::uint64_t, 3> whitespace_counts{};
  std::vector<double> whitespace_losses(Alphabet == 256 ? (options.k_max + 1) * 3 : 0, 0.0);
  bool has_aligned_prefix = false;
  std::uint64_t aligned_offset = 0;
  std::vector<double> aligned_losses(options.k_max + 1, 0.0);
  bool has_previous = false;
  bool previous_whitespace = false;

  History128 history = 0;
  Sha256 hasher;
  std::size_t next_checkpoint = 0;
  std::array<char, kInputChunkBytes> buffer{};
  const auto wall_start = std::chrono::steady_clock::now();
  const std::clock_t cpu_start = std::clock();

  while (input) {
    input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    const std::streamsize obtained = input.gcount();
    if (obtained < 0) throw std::runtime_error("negative corpus read size");
    if (obtained > 0) {
      checked_increment(result.metrics.input_read_calls, "input read call count");
      hasher.update(reinterpret_cast<const std::byte*>(buffer.data()),
                    static_cast<std::size_t>(obtained));
    }
    for (std::streamsize index = 0; index < obtained; ++index) {
      if (result.n >= metadata.expected_n) {
        throw std::runtime_error("corpus contains bytes beyond sidecar expected_n");
      }
      const std::uint8_t symbol = static_cast<std::uint8_t>(
          static_cast<unsigned char>(buffer[static_cast<std::size_t>(index)]));
      if (static_cast<std::size_t>(symbol) >= Alphabet) {
        throw std::runtime_error("invalid corpus symbol " + std::to_string(symbol) +
                                 " at byte offset " + std::to_string(result.n));
      }
      const std::uint32_t available_depth = static_cast<std::uint32_t>(
          std::min<std::uint64_t>(result.n, options.k_max));
      std::array<double, kMaximumOrder + 1> event_losses{};
      std::array<double, kMaximumOrder + 1> event_ml{};

      const std::uint32_t event_dense_max = std::min(dense_depth, available_depth);
      for (std::uint32_t depth = 0; depth <= event_dense_max; ++depth) {
        const HistogramRow<Alphabet>& row = dense[dense_index<Alphabet>(history, depth, offsets)];
        event_losses[depth] = kt_loss<Alphabet>(row.counts[symbol], row.total, result.metrics);
        event_ml[depth] = ml_increment(row.total, row.counts[symbol], result.metrics);
      }

      std::array<RouteEntry, kRouteCapacity> route{};
      std::size_t route_size = 0;
      if (available_depth >= Traits::tail_min_depth) {
        route = tail->ensure_and_route(prefix_history<Alphabet>(history, available_depth),
                                       static_cast<std::uint8_t>(available_depth), route_size);
        for (std::size_t route_index = 0; route_index < route_size; ++route_index) {
          const RouteEntry& entry = route[route_index];
          const Node<Alphabet> node = tail->read(entry.node_id);
          const double loss = kt_loss<Alphabet>(node.counts[symbol], node.total, result.metrics);
          const double ml = ml_increment(node.total, node.counts[symbol], result.metrics);
          for (std::uint32_t depth = entry.first_depth; depth <= entry.last_depth; ++depth) {
            event_losses[depth] = loss;
            event_ml[depth] = ml;
          }
        }
      }

      for (std::uint32_t depth = available_depth + 1; depth <= options.k_max; ++depth) {
        event_losses[depth] = Traits::startup_loss;
        event_ml[depth] = Traits::startup_loss;
      }

      unsigned whitespace_bucket = 0;
      if constexpr (Alphabet == 256) {
        const bool current_whitespace = is_ascii_whitespace(symbol);
        whitespace_bucket = current_whitespace ? 0U : ((!has_previous || previous_whitespace) ? 1U : 2U);
        checked_increment(whitespace_counts[whitespace_bucket], "whitespace bucket count");
      }
      if constexpr (Alphabet == 32) {
        checked_increment(symbol_counts[symbol], "predicted symbol count");
      }

      for (std::uint32_t depth = 0; depth <= options.k_max; ++depth) {
        losses[depth] += event_losses[depth];
        ml_losses[depth] += event_ml[depth];
        checked_increment(result.metrics.logical_scores, "logical score count");
        checked_increment(result.metrics.scores_by_depth[depth], "depth score count");
        if constexpr (Alphabet == 32) {
          symbol_losses[static_cast<std::size_t>(depth) * Alphabet + symbol] += event_losses[depth];
        } else {
          whitespace_losses[static_cast<std::size_t>(depth) * 3 + whitespace_bucket] +=
              event_losses[depth];
        }
      }

      for (std::uint32_t depth = 0; depth <= event_dense_max; ++depth) {
        HistogramRow<Alphabet>& row = dense[dense_index<Alphabet>(history, depth, offsets)];
        update_occupancy(occupancy[depth], row.total);
        checked_increment(row.total, "dense histogram total");
        checked_increment(row.counts[symbol], "dense symbol count");
        checked_increment(result.metrics.logical_updates, "logical update count");
        checked_increment(result.metrics.updates_by_depth[depth], "depth update count");
      }
      for (std::size_t route_index = 0; route_index < route_size; ++route_index) {
        Node<Alphabet> node = tail->read(route[route_index].node_id);
        for (std::uint32_t depth = route[route_index].first_depth;
             depth <= route[route_index].last_depth; ++depth) {
          update_occupancy(occupancy[depth], node.total);
          checked_increment(result.metrics.logical_updates, "logical update count");
          checked_increment(result.metrics.updates_by_depth[depth], "depth update count");
        }
        checked_increment(node.total, "tail histogram total");
        checked_increment(node.counts[symbol], "tail symbol count");
        tail->write(route[route_index].node_id, node);
      }

      history = append_history<Alphabet>(history, symbol);
      checked_increment(result.n, "corpus length");
      checked_increment(result.metrics.input_bytes, "input byte count");

      if constexpr (Alphabet == 256) {
        previous_whitespace = is_ascii_whitespace(symbol);
        has_previous = true;
        if (previous_whitespace) {
          has_aligned_prefix = true;
          aligned_offset = result.n;
          aligned_losses = losses;
        }
      }

      if (next_checkpoint < options.checkpoints.size() &&
          result.n == options.checkpoints[next_checkpoint]) {
        for (std::uint32_t depth = 0; depth <= options.k_max; ++depth) {
          const std::uint64_t expected_visits = result.n > depth ? result.n - depth : 0;
          if (occupancy[depth].visits != expected_visits) {
            throw std::runtime_error("occupancy visitation invariant failed at depth " +
                                     std::to_string(depth));
          }
        }
        result.checkpoints.push_back(make_checkpoint<Alphabet>(
            result.n, losses, ml_losses, occupancy, symbol_counts, symbol_losses,
            whitespace_counts, whitespace_losses, has_aligned_prefix, aligned_offset,
            aligned_losses, result.metrics, wall_start, cpu_start));
        ++next_checkpoint;
      }
    }
  }
  if (input.bad()) throw std::runtime_error("I/O failure while reading corpus");
  if (result.n != metadata.expected_n) {
    throw std::runtime_error("corpus length " + std::to_string(result.n) +
                             " does not match sidecar expected_n " +
                             std::to_string(metadata.expected_n));
  }
  if (next_checkpoint != options.checkpoints.size()) {
    throw std::runtime_error("not all requested checkpoints were reached");
  }

  result.computed_corpus_sha256 = hasher.finish_hex();
  if (lowercase_ascii(result.computed_corpus_sha256) !=
      lowercase_ascii(metadata.corpus_sha256)) {
    throw std::runtime_error("corpus SHA256 does not match sidecar");
  }

  if (tail) tail->finalize();
  result.metrics = checkpoint_metrics(result.metrics, wall_start, cpu_start);
  if (!result.checkpoints.empty()) result.checkpoints.back().metrics = result.metrics;
  return result;
}

void append_double_array(std::ostringstream& out, const std::vector<double>& values) {
  out << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i) out << ',';
    out << values[i];
  }
  out << ']';
}

void append_double_bits_array(std::ostringstream& out, const std::vector<double>& values) {
  out << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i) out << ',';
    out << '"' << double_bits_hex(values[i]) << '"';
  }
  out << ']';
}

void append_u64_array(std::ostringstream& out, const std::vector<std::uint64_t>& values) {
  out << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i) out << ',';
    out << values[i];
  }
  out << ']';
}

void append_metrics(std::ostringstream& out, const EngineMetrics& m) {
  out << "{\"input_bytes\":" << m.input_bytes
      << ",\"input_read_calls\":" << m.input_read_calls
      << ",\"nodes\":" << m.nodes
      << ",\"leaves_created\":" << m.leaves_created
      << ",\"divergence_splits\":" << m.divergence_splits
      << ",\"endpoint_splits\":" << m.endpoint_splits
      << ",\"page_capacity\":" << m.page_capacity
      << ",\"page_hits\":" << m.page_hits
      << ",\"page_misses\":" << m.page_misses
      << ",\"page_evictions\":" << m.page_evictions
      << ",\"dirty_writebacks\":" << m.dirty_writebacks
      << ",\"cache_index_rebuilds\":" << m.cache_index_rebuilds
      << ",\"page_reads\":" << m.page_reads
      << ",\"page_writes\":" << m.page_writes
      << ",\"bytes_read\":" << m.bytes_read
      << ",\"bytes_written\":" << m.bytes_written
      << ",\"kt_log2_calls\":" << m.kt_log2_calls
      << ",\"annex_log2_calls\":" << m.annex_log2_calls
      << ",\"logical_store_bytes\":" << m.logical_store_bytes
      << ",\"allocated_store_bytes\":" << m.allocated_store_bytes
      << ",\"dense_frontend_bytes\":" << m.dense_frontend_bytes
      << ",\"directory_bytes\":" << m.directory_bytes
      << ",\"fixed_cache_data_bytes\":" << m.fixed_cache_data_bytes
      << ",\"fixed_cache_metadata_bytes\":" << m.fixed_cache_metadata_bytes
      << ",\"peak_rss_kib\":" << m.peak_rss_kib
      << ",\"logical_scores\":" << m.logical_scores
      << ",\"logical_updates\":" << m.logical_updates
      << ",\"scores_by_depth\":[";
  for (std::size_t i = 0; i < m.scores_by_depth.size(); ++i) {
    if (i) out << ',';
    out << m.scores_by_depth[i];
  }
  out << "],\"updates_by_depth\":[";
  for (std::size_t i = 0; i < m.updates_by_depth.size(); ++i) {
    if (i) out << ',';
    out << m.updates_by_depth[i];
  }
  out << "],\"wall_seconds\":" << m.wall_seconds
      << ",\"process_cpu_seconds\":" << m.process_cpu_seconds << '}';
}

}  // namespace

struct StreamingSha256::Impl {
  Sha256 hash;
  bool finished = false;
};

StreamingSha256::StreamingSha256() : impl_(std::make_unique<Impl>()) {}
StreamingSha256::~StreamingSha256() = default;
StreamingSha256::StreamingSha256(StreamingSha256&&) noexcept = default;
StreamingSha256& StreamingSha256::operator=(StreamingSha256&&) noexcept = default;

void StreamingSha256::update(std::span<const std::byte> data) {
  if (!impl_ || impl_->finished) throw std::logic_error("SHA256 stream already finished");
  impl_->hash.update(data.data(), data.size());
}

std::string StreamingSha256::finish_hex() {
  if (!impl_ || impl_->finished) throw std::logic_error("SHA256 stream already finished");
  impl_->finished = true;
  return impl_->hash.finish_hex();
}

CorpusMetadata read_corpus_metadata(const std::filesystem::path& metadata_path) {
  std::ifstream input(metadata_path, std::ios::binary);
  if (!input) throw std::runtime_error("cannot open corpus metadata: " + metadata_path.string());
  std::ostringstream text;
  text << input.rdbuf();
  if (input.bad()) throw std::runtime_error("I/O failure reading corpus metadata");
  const auto fields = JsonRootReader(text.str()).parse();

  CorpusMetadata metadata;
  metadata.schema = require_string(fields, "schema");
  metadata.track = require_string(fields, "track");
  const std::uint64_t alphabet = require_u64(fields, "alphabet_size");
  if (alphabet > std::numeric_limits<std::uint32_t>::max()) {
    throw std::runtime_error("alphabet_size overflows uint32");
  }
  metadata.alphabet_size = static_cast<std::uint32_t>(alphabet);
  metadata.expected_n = require_u64(fields, "expected_n");
  metadata.run_id = require_string(fields, "run_id");
  metadata.corpus_sha256 = lowercase_ascii(require_string(fields, "corpus_sha256"));
  metadata.protocol_sha256 = lowercase_ascii(require_string(fields, "protocol_sha256"));
  metadata.freeze_sha256 = lowercase_ascii(require_string(fields, "freeze_sha256"));
  metadata.execution_manifest_sha256 = lowercase_ascii(
      require_string(fields, "execution_manifest_sha256"));

  if (metadata.schema != kCorpusSchema) throw std::runtime_error("unsupported corpus metadata schema");
  if ((metadata.track == "A" && metadata.alphabet_size != 32) ||
      (metadata.track == "B" && metadata.alphabet_size != 256) ||
      (metadata.track != "A" && metadata.track != "B")) {
    throw std::runtime_error("invalid track/alphabet metadata pair");
  }
  for (const auto& [name, digest] : std::array<std::pair<const char*, const std::string*>, 4>{
           std::pair{"corpus_sha256", &metadata.corpus_sha256},
           std::pair{"protocol_sha256", &metadata.protocol_sha256},
           std::pair{"freeze_sha256", &metadata.freeze_sha256},
           std::pair{"execution_manifest_sha256", &metadata.execution_manifest_sha256}}) {
    if (!is_hex_digest(*digest)) throw std::runtime_error(std::string("invalid SHA256 field: ") + name);
  }
  if (metadata.protocol_sha256 != kExpectedProtocolSha256) {
    throw std::runtime_error("sidecar protocol_sha256 does not match compiled Rev B protocol");
  }
  if (metadata.freeze_sha256 != kExpectedFreezeSha256) {
    throw std::runtime_error("sidecar freeze_sha256 does not match compiled Rev B freeze");
  }

  if (metadata.track == "A") {
    metadata.configuration = require_string(fields, "configuration");
    metadata.seed = require_u64(fields, "seed");
    metadata.has_seed = true;
  } else {
    metadata.source_manifest_sha256 = lowercase_ascii(require_string(fields, "source_manifest_sha256"));
    if (!is_hex_digest(metadata.source_manifest_sha256)) {
      throw std::runtime_error("invalid SHA256 field: source_manifest_sha256");
    }
    metadata.corpus = require_string(fields, "corpus");
    metadata.draw_id = optional_scalar(fields, "draw_id");
    metadata.transformation_provenance = optional_scalar(fields, "transformation_provenance");
    if (metadata.draw_id.empty()) throw std::runtime_error("missing metadata field: draw_id");
    if (metadata.transformation_provenance.empty()) {
      throw std::runtime_error("missing metadata field: transformation_provenance");
    }
  }
  return metadata;
}

AvailabilityResult availability(const std::filesystem::path& corpus_path,
                                std::uint32_t k_max,
                                const std::vector<std::uint64_t>& checkpoints,
                                const EngineOptions& base_options) {
  EngineOptions options = base_options;
  options.k_max = k_max;
  options.checkpoints = checkpoints;
  return compute_availability(corpus_path, options);
}

AvailabilityResult compute_availability(const std::filesystem::path& corpus_path,
                                        const EngineOptions& options) {
  const std::filesystem::path metadata_path = options.metadata_path.empty()
      ? std::filesystem::path(corpus_path.string() + ".meta.json")
      : options.metadata_path;
  const CorpusMetadata metadata = read_corpus_metadata(metadata_path);
  if (metadata.alphabet_size == 32) return compute_typed<32>(corpus_path, options, metadata);
  if (metadata.alphabet_size == 256) return compute_typed<256>(corpus_path, options, metadata);
  throw std::runtime_error("unsupported alphabet metadata");
}

History128 history_append(History128 history, std::uint8_t symbol,
                          std::uint32_t alphabet_size) {
  if (alphabet_size == 32) return append_history<32>(history, symbol);
  if (alphabet_size == 256) return append_history<256>(history, symbol);
  throw std::invalid_argument("alphabet_size must be 32 or 256");
}

History128 history_prefix(History128 history, std::uint32_t depth,
                          std::uint32_t alphabet_size) {
  if (alphabet_size == 32) return prefix_history<32>(history, depth);
  if (alphabet_size == 256) return prefix_history<256>(history, depth);
  throw std::invalid_argument("alphabet_size must be 32 or 256");
}

std::uint8_t history_digit(History128 history, std::uint32_t index,
                           std::uint32_t alphabet_size) {
  if (alphabet_size == 32) return digit_history<32>(history, index);
  if (alphabet_size == 256) return digit_history<256>(history, index);
  throw std::invalid_argument("alphabet_size must be 32 or 256");
}

std::uint32_t common_prefix_depth(History128 lhs, std::uint32_t lhs_depth,
                                  History128 rhs, std::uint32_t rhs_depth,
                                  std::uint32_t alphabet_size) {
  if (alphabet_size == 32) return common_history<32>(lhs, lhs_depth, rhs, rhs_depth);
  if (alphabet_size == 256) return common_history<256>(lhs, lhs_depth, rhs, rhs_depth);
  throw std::invalid_argument("alphabet_size must be 32 or 256");
}

void checked_increment(std::uint64_t& value, const char* field_name) {
  if (value == std::numeric_limits<std::uint64_t>::max()) {
    throw std::overflow_error(std::string(field_name) + " overflow");
  }
  ++value;
}

std::string double_bits_hex(double value) {
  const std::uint64_t bits = std::bit_cast<std::uint64_t>(value);
  std::ostringstream out;
  out << "0x" << std::hex << std::setw(16) << std::setfill('0') << bits;
  return out.str();
}

std::string sha256_hex(std::span<const std::byte> data) {
  Sha256 hash;
  hash.update(data.data(), data.size());
  return hash.finish_hex();
}

std::string sha256_file(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  if (!input) throw std::runtime_error("cannot open file for SHA256: " + path.string());
  Sha256 hash;
  std::array<char, kInputChunkBytes> buffer{};
  while (input) {
    input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    const std::streamsize obtained = input.gcount();
    if (obtained < 0) throw std::runtime_error("negative SHA256 file read size");
    if (obtained > 0) {
      hash.update(reinterpret_cast<const std::byte*>(buffer.data()),
                  static_cast<std::size_t>(obtained));
    }
  }
  if (input.bad()) throw std::runtime_error("I/O failure hashing file");
  return hash.finish_hex();
}

std::string result_to_json(const AvailabilityResult& result,
                           const std::filesystem::path& corpus_path,
                           const std::string& storage_method,
                           bool store_retained) {
  std::ostringstream out;
  out << std::setprecision(17);
  out << "{\"schema\":\"" << kResultSchema << "\",\"status\":\""
      << json_escape(result.status) << "\",\"corpus_path\":\""
      << json_escape(corpus_path.string()) << "\",\"N\":" << result.n
      << ",\"alphabet_size\":" << result.alphabet << ",\"k_max\":" << result.k_max
      << ",\"surface_axes\":[\"checkpoint\",\"order\"]"
      << ",\"storage_method\":\"" << json_escape(storage_method)
      << "\",\"store_retained\":" << (store_retained ? "true" : "false")
      << ",\"metadata\":{\"schema\":\"" << json_escape(result.metadata.schema)
      << "\",\"track\":\"" << json_escape(result.metadata.track)
      << "\",\"run_id\":\"" << json_escape(result.metadata.run_id)
      << "\",\"expected_n\":" << result.metadata.expected_n
      << ",\"corpus_sha256\":\"" << result.metadata.corpus_sha256
      << "\",\"computed_corpus_sha256\":\"" << result.computed_corpus_sha256
      << "\",\"protocol_sha256\":\"" << result.metadata.protocol_sha256
      << "\",\"freeze_sha256\":\"" << result.metadata.freeze_sha256
      << "\",\"execution_manifest_sha256\":\""
      << result.metadata.execution_manifest_sha256 << '"';
  if (result.metadata.track == "A") {
    out << ",\"configuration\":\"" << json_escape(result.metadata.configuration)
        << "\",\"seed\":" << result.metadata.seed;
  } else {
    out << ",\"source_manifest_sha256\":\"" << result.metadata.source_manifest_sha256
        << "\",\"corpus\":\"" << json_escape(result.metadata.corpus)
        << "\",\"draw_id\":\"" << json_escape(result.metadata.draw_id)
        << "\",\"transformation_provenance\":\""
        << json_escape(result.metadata.transformation_provenance) << '"';
  }
  out << "},\"checkpoint_count\":" << result.checkpoints.size() << ",\"checkpoints\":[";
  for (std::size_t checkpoint_index = 0; checkpoint_index < result.checkpoints.size();
       ++checkpoint_index) {
    if (checkpoint_index) out << ',';
    const CheckpointRecord& checkpoint = result.checkpoints[checkpoint_index];
    out << "{\"n\":" << checkpoint.n << ",\"L\":";
    append_double_array(out, checkpoint.losses);
    out << ",\"L_bits\":";
    append_double_bits_array(out, checkpoint.losses);
    out << ",\"A\":";
    append_double_array(out, checkpoint.availability);
    out << ",\"A_bits\":";
    append_double_bits_array(out, checkpoint.availability);
    out << ",\"L_ML\":";
    append_double_array(out, checkpoint.ml_losses);
    out << ",\"L_ML_bits\":";
    append_double_bits_array(out, checkpoint.ml_losses);
    out << ",\"KT_minus_ML\":";
    append_double_array(out, checkpoint.kt_minus_ml);
    out << ",\"KT_minus_ML_per_symbol\":";
    append_double_array(out, checkpoint.kt_minus_ml_per_symbol);
    out << ",\"occupancy\":[";
    for (std::size_t k = 0; k < checkpoint.occupancy.size(); ++k) {
      if (k) out << ',';
      const auto& occupancy = checkpoint.occupancy[k];
      out << "{\"k\":" << k << ",\"visits\":" << occupancy.visits
          << ",\"distinct_contexts\":" << occupancy.distinct_contexts
          << ",\"singleton_contexts\":" << occupancy.singleton_contexts
          << ",\"contexts_total_lt5\":" << occupancy.rare_contexts_lt5
          << ",\"singleton_visitation_numerator\":"
          << occupancy.singleton_visitation_numerator
          << ",\"rare_visitation_numerator\":" << occupancy.rare_visitation_numerator
          << ",\"singleton_visitation_mass\":";
      if (occupancy.visits == 0) {
        out << "null,\"rare_visitation_mass\":null,\"mass_undefined_reason\":\"zero_visits\"";
      } else {
        out << static_cast<double>(occupancy.singleton_visitation_numerator) /
                   static_cast<double>(occupancy.visits)
            << ",\"rare_visitation_mass\":"
            << static_cast<double>(occupancy.rare_visitation_numerator) /
                   static_cast<double>(occupancy.visits);
      }
      out << '}';
    }
    out << ']';

    if (result.alphabet == 32) {
      out << ",\"predicted_symbol_attribution\":{\"counts\":";
      append_u64_array(out, checkpoint.predicted_symbol_counts);
      out << ",\"L_order_major\":";
      append_double_array(out, checkpoint.predicted_symbol_losses);
      out << ",\"A_contribution_order_major\":[";
      for (std::size_t k = 0; k <= result.k_max; ++k) {
        for (std::size_t symbol = 0; symbol < 32; ++symbol) {
          if (k != 0 || symbol != 0) out << ',';
          const double contribution =
              (checkpoint.predicted_symbol_losses[symbol] -
               checkpoint.predicted_symbol_losses[k * 32 + symbol]) /
              static_cast<double>(checkpoint.n);
          out << contribution;
        }
      }
      out << "],\"contribution_sum_residual\":[";
      for (std::size_t k = 0; k <= result.k_max; ++k) {
        if (k) out << ',';
        double contribution_sum = 0.0;
        for (std::size_t symbol = 0; symbol < 32; ++symbol) {
          contribution_sum +=
              (checkpoint.predicted_symbol_losses[symbol] -
               checkpoint.predicted_symbol_losses[k * 32 + symbol]) /
              static_cast<double>(checkpoint.n);
        }
        out << contribution_sum - checkpoint.availability[k];
      }
      out << ']';
      if (result.metadata.configuration.rfind("G3(", 0) == 0) {
        std::array<std::uint64_t, 3> type_counts{};
        for (std::size_t symbol = 0; symbol < 32; ++symbol) {
          const std::size_t type = symbol < 16 ? 0 : (symbol < 24 ? 1 : 2);
          type_counts[type] += checkpoint.predicted_symbol_counts[symbol];
        }
        out << ",\"g3_type_totals\":{\"type_names\":[\"filler\",\"controller\","
               "\"agreement\"],\"counts\":["
            << type_counts[0] << ',' << type_counts[1] << ',' << type_counts[2]
            << "],\"L_order_major\":[";
        for (std::size_t k = 0; k <= result.k_max; ++k) {
          for (std::size_t type = 0; type < 3; ++type) {
            if (k != 0 || type != 0) out << ',';
            double type_loss = 0.0;
            const std::size_t begin = type == 0 ? 0 : (type == 1 ? 16 : 24);
            const std::size_t end = type == 0 ? 16 : (type == 1 ? 24 : 32);
            for (std::size_t symbol = begin; symbol < end; ++symbol) {
              type_loss += checkpoint.predicted_symbol_losses[k * 32 + symbol];
            }
            out << type_loss;
          }
        }
        out << "]}";
      }
      out << '}';
    } else {
      static constexpr std::array<const char*, 3> names = {
          "whitespace", "token_first", "token_continuation"};
      out << ",\"whitespace_attribution\":{\"bucket_names\":[\"whitespace\","
             "\"token_first\",\"token_continuation\"],\"counts\":["
          << checkpoint.whitespace.counts[0] << ',' << checkpoint.whitespace.counts[1] << ','
          << checkpoint.whitespace.counts[2] << "],\"L_order_major\":";
      append_double_array(out, checkpoint.whitespace.losses);
      out << ",\"A_contribution_order_major\":[";
      for (std::size_t k = 0; k <= result.k_max; ++k) {
        for (std::size_t bucket = 0; bucket < names.size(); ++bucket) {
          if (k != 0 || bucket != 0) out << ',';
          out << (checkpoint.whitespace.losses[bucket] -
                  checkpoint.whitespace.losses[k * 3 + bucket]) /
                     static_cast<double>(checkpoint.n);
        }
      }
      out << "],\"contribution_sum_residual\":[";
      for (std::size_t k = 0; k <= result.k_max; ++k) {
        if (k) out << ',';
        double contribution_sum = 0.0;
        for (std::size_t bucket = 0; bucket < names.size(); ++bucket) {
          contribution_sum +=
              (checkpoint.whitespace.losses[bucket] -
               checkpoint.whitespace.losses[k * 3 + bucket]) /
              static_cast<double>(checkpoint.n);
        }
        out << contribution_sum - checkpoint.availability[k];
      }
      out << "],\"aligned_offset\":";
      if (!checkpoint.whitespace.has_aligned_prefix) {
        out << "null,\"aligned_A\":null,\"aligned_undefined_reason\":\"no_ascii_whitespace\"";
      } else {
        out << checkpoint.whitespace.aligned_offset << ",\"aligned_L\":";
        append_double_array(out, checkpoint.whitespace.aligned_losses);
        out << ",\"aligned_A\":[";
        for (std::size_t k = 0; k < checkpoint.whitespace.aligned_losses.size(); ++k) {
          if (k) out << ',';
          const double value = k == 0 ? 0.0 :
              (checkpoint.whitespace.aligned_losses[0] -
               checkpoint.whitespace.aligned_losses[k]) /
                  static_cast<double>(checkpoint.whitespace.aligned_offset);
          out << value;
        }
        out << ']';
      }
      out << '}';
    }
    out << ",\"metrics\":";
    append_metrics(out, checkpoint.metrics);
    out << '}';
  }
  out << "],\"metrics\":";
  append_metrics(out, result.metrics);
  out << "}\n";
  return out.str();
}

}  // namespace block01
