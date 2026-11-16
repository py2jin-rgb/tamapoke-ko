#pragma once
#include <cstdint>
class Preferences {
 public:
  bool begin(const char *, bool) { return true; }
  bool getBool(const char *, bool fallback) { return fallback; }
  uint8_t getUChar(const char *, uint8_t fallback) { return fallback; }
  void putBool(const char *, bool) {}
  void putUChar(const char *, uint8_t) {}
  void end() {}
};
