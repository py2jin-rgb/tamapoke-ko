#pragma once
#include <atomic>
#include <cassert>
#include <mutex>
#include "driver/i2s_std.h"
namespace Mock {
inline std::mutex busMutex;
inline uint8_t registers[256] = {};
inline std::atomic<int> failRegister{-1};
inline std::atomic<unsigned> suspendEnds{0};
}
inline esp_err_t i2cWrite(uint8_t bus, uint16_t address, const uint8_t *data, size_t count, uint32_t) {
  std::lock_guard<std::mutex> lock(Mock::busMutex);
  assert(bus == 0 && address == 0x18);
  if (!count) return ESP_OK;
  assert(count == 2);
  if (Mock::failRegister.load() == data[0]) { Mock::failRegister = -1; return ESP_FAIL; }
  Mock::registers[data[0]] = data[1];
  if (data[0] == 0x0D && data[1] == 0xFC) ++Mock::suspendEnds;
  return ESP_OK;
}
inline esp_err_t i2cWriteReadNonStop(uint8_t bus, uint16_t address, const uint8_t *w, size_t wn, uint8_t *r, size_t rn, uint32_t, size_t *count) {
  std::lock_guard<std::mutex> lock(Mock::busMutex);
  assert(bus == 0 && address == 0x18 && wn == 1 && rn == 1);
  *r = Mock::registers[*w]; *count = 1; return ESP_OK;
}
