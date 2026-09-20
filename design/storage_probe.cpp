// Deterministic storage-only probe; no PRNG, generator, or corpus.
// Creates/removes its own scratch file; never drops caches or changes host settings.
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <stdexcept>
#include <string>
#include <unistd.h>

static double now() {
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
static void check(bool ok, const char* what) {
  if (!ok) throw std::runtime_error(std::string(what) + ": " + std::strerror(errno));
}
int main(int argc, char** argv) {
  std::string filename = std::string(argc > 1 ? argv[1] : ".") + "/.storage-probe-XXXXXX";
  int fd = mkstemp(filename.data());
  if (fd < 0) return 2;
  void* memory = nullptr;
  try {
    check(posix_memalign(&memory, 4096, 1 << 20) == 0, "aligned allocation");
    std::memset(memory, 0, 1 << 20);
    double t = now();
    for (int i = 0; i < 64; ++i) check(pwrite(fd, memory, 1 << 20, off_t(i) << 20) == (1 << 20), "sequential pwrite");
    check(fsync(fd) == 0, "fsync");
    double seq = now() - t;
    close(fd); fd = -1;
    fd = open(filename.c_str(), O_RDWR | O_DIRECT);
    if (fd < 0) {
      std::printf("{\"scratch_bytes\":67108864,\"sequential_write_fsync_seconds\":%.9f,\"direct_supported\":false,\"errno\":%d}\n", seq, errno);
    } else {
      t = now();
      for (unsigned i = 0; i < 4096; ++i) {
        off_t offset = off_t((i * 4051u) % 16384u) * 4096;
        check(pread(fd, memory, 4096, offset) == 4096, "direct pread");
      }
      double rd = now() - t;
      t = now();
      for (unsigned i = 0; i < 1024; ++i) {
        off_t offset = off_t((i * 4051u) % 16384u) * 4096;
        check(pwrite(fd, memory, 4096, offset) == 4096, "direct pwrite");
      }
      check(fsync(fd) == 0, "direct fsync");
      double wr = now() - t;
      std::printf("{\"scratch_bytes\":67108864,\"sequential_write_fsync_seconds\":%.9f,\"direct_supported\":true,\"read_requests\":4096,\"read_bytes\":16777216,\"direct_permuted_read_seconds\":%.9f,\"direct_permuted_read_iops\":%.3f,\"write_requests\":1024,\"write_bytes\":4194304,\"direct_permuted_write_fsync_seconds\":%.9f,\"direct_permuted_write_iops\":%.3f,\"queue_depth\":1,\"pattern\":\"page=(i*4051) mod 16384; 4KiB pages; zero-filled scratch\"}\n", seq, rd, 4096/rd, wr, 1024/wr);
    }
    if (fd >= 0) close(fd);
    unlink(filename.c_str());
    std::free(memory);
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "%s\n", error.what());
    if (fd >= 0) close(fd);
    unlink(filename.c_str());
    std::free(memory);
    return 1;
  }
}
