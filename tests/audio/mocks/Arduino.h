#pragma once
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <thread>
#include "freertos/FreeRTOS.h"
namespace Mock {
inline const auto boot = std::chrono::steady_clock::now();
inline std::atomic<bool> pa{false};
inline std::atomic<unsigned> paStarts{0};
}
inline uint32_t millis() { return (uint32_t)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - Mock::boot).count(); }
inline void delay(uint32_t ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
static constexpr int HIGH = 1, LOW = 0, OUTPUT = 1;
inline void pinMode(int, int) {}
inline void digitalWrite(int, int v) { bool old = Mock::pa.exchange(v != 0); if (!old && v) ++Mock::paStarts; }
struct MockSerial {
  void println(const char *s) { std::fprintf(stderr, "%s\n", s); }
  void printf(const char *fmt, ...) { va_list ap; va_start(ap, fmt); std::vfprintf(stderr, fmt, ap); va_end(ap); }
};
inline MockSerial Serial;
