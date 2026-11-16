#pragma once
#include <stdint.h>

// Hardware-independent policy. All CPU/display transitions have one owner in
// TamaPoke.ino; radio and audio only report their current requirements.
namespace TamaPower {
constexpr uint32_t DIM_AFTER_MS = 30000;
constexpr uint32_t OFF_AFTER_MS = 120000;
constexpr uint32_t SLEEP_POLL_US = 200000; // PMIC PWR is behind TCA9554, not a wake GPIO.

struct Inputs {
  uint32_t idleMs;
  uint8_t brightnessPct;
  bool manualOff;
  bool manualClock;
  bool alwaysOnClock;
  bool usb;
  bool petSleeping;
  bool alarm;
  bool criticalWork;
  bool radio;
  bool audio;
  bool touch;
  bool sleepEnabled;
};

struct Plan {
  uint8_t dimStage;
  uint8_t brightness;
  uint16_t cpuMHz;
  bool displayOff;
  bool maySleep;
};

inline Plan decide(const Inputs &in) {
  const bool forceAwake = in.alarm || in.criticalWork;
  const bool clockHeld = in.manualClock && (in.alwaysOnClock || in.usb);
  uint8_t stage = forceAwake ? 0 :
    (in.idleMs >= OFF_AFTER_MS && !clockHeld ? 2 :
     in.idleMs >= DIM_AFTER_MS ? 1 : 0);
  const bool off = !forceAwake && (in.manualOff || stage == 2);
  uint8_t pct = in.brightnessPct > 100 ? 100 : in.brightnessPct;
  uint8_t brightness = static_cast<uint16_t>(pct) * 255U / 100U;
  if (in.petSleeping && !in.alarm && brightness > 51) brightness = 51;
  if (stage == 1 && brightness > 64) brightness = 64;
  if (off) brightness = 0;
  const bool busy = in.radio || in.audio || forceAwake;
  return {stage, brightness, static_cast<uint16_t>(off && !busy ? 80 : 240), off,
          off && in.sleepEnabled && !in.usb && !busy && !in.touch};
}

inline bool reached(uint32_t now, uint32_t deadline) {
  return static_cast<int32_t>(now - deadline) >= 0;
}
inline void shiftDeadline(uint32_t &deadline, uint32_t elapsed) {
  if (deadline) deadline += elapsed;
}
} // namespace TamaPower
