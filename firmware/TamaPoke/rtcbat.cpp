#include "rtcbat.h"
#include "pin_config.h"  // define XPOWERS_CHIP_AXP2101
#include <Wire.h>
#include <time.h>
#include <SensorPCF85063.hpp>
#include <XPowersLib.h>

static SensorPCF85063 rtc;
static XPowersPMU pmu;
static bool rtcOk = false;
static bool pmuOk = false;
static uint32_t rtcCacheEpoch = 0;
static uint32_t rtcCacheAt = 0;
static bool rtcCacheValid = false;

bool rtcBegin() {
  rtcCacheValid = false;
  rtcOk = rtc.begin(Wire, IIC_SDA, IIC_SCL);
  if (!rtcOk) Serial.println("PCF85063 no detectado");
  return rtcOk;
}

uint32_t rtcEpoch() {
  if (!rtcOk) return 0;
  // A frame can ask for the clock several times. Read the shared I2C bus at
  // most once per second; millis continues across light-sleep. Never cache a
  // failed/invalid reading, and invalidate immediately when the user sets time.
  const uint32_t now = millis();
  if (rtcCacheValid && now - rtcCacheAt < 1000UL) return rtcCacheEpoch;
  RTC_DateTime t = rtc.getDateTime();
  if (t.getYear() < 2025 || t.getYear() > 2105) {
    rtcCacheValid = false;
    return 0;
  }
  struct tm tmv = {};
  tmv.tm_year = t.getYear() - 1900;
  tmv.tm_mon = t.getMonth() - 1;
  tmv.tm_mday = t.getDay();
  tmv.tm_hour = t.getHour();
  tmv.tm_min = t.getMinute();
  tmv.tm_sec = t.getSecond();
  time_t e = mktime(&tmv);  // TZ por defecto = UTC, consistente con gmtime_r
  rtcCacheEpoch = e > 0 ? (uint32_t)e : 0;
  rtcCacheAt = now;
  rtcCacheValid = rtcCacheEpoch != 0;
  return rtcCacheEpoch;
}

void rtcSetEpoch(uint32_t e) {
  if (!rtcOk) return;
  rtcCacheValid = false;
  time_t tt = e;
  struct tm tmv;
  gmtime_r(&tt, &tmv);
  rtc.setDateTime(RTC_DateTime(tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday,
                               tmv.tm_hour, tmv.tm_min, tmv.tm_sec));
}

bool batBegin() {
  pmuOk = pmu.begin(Wire, AXP2101_SLAVE_ADDRESS, IIC_SDA, IIC_SCL);
  if (!pmuOk) Serial.println("AXP2101 no detectado");
  return pmuOk;
}

// Preserve the previous startup rail setup for existing units. On the official
// standard 1.75 schematic the panel/touch share DCDC1 VCC3V3 with the MCU, and
// BLDO1 is unconnected. Do NOT use this historical BLDO1 setup to power-cycle
// the display or turn off the shared rail; sleep uses CO5300 commands instead.
void pmuEnablePanel() {
  if (!pmu.begin(Wire, AXP2101_SLAVE_ADDRESS, IIC_SDA, IIC_SCL)) {
    Serial.println("AXP2101 no detectado (pmuEnablePanel)");
    return;
  }
  pmu.setBLDO1Voltage(3300);   // Legacy startup compatibility, not a display sleep rail.
  pmu.enableBLDO1();
}

// el estado de energia (I2C) se cachea ~2 s: leerlo en cada frame del loop
// metia trafico I2C inutil y podia oscilar (parpadeo de brillo)
static uint32_t powerCacheT = 0;
static int cachedPct = -1;
static bool cachedCharging = false, cachedUsb = true;

static void refreshPower() {
  uint32_t now = millis();
  if (powerCacheT && now - powerCacheT < 2000) return;
  powerCacheT = now ? now : 1;
  if (!pmuOk) { cachedPct = -1; cachedCharging = false; cachedUsb = true; return; }
  cachedPct = pmu.isBatteryConnect() ? pmu.getBatteryPercent() : -1;
  cachedCharging = pmu.isCharging();
  cachedUsb = pmu.isVbusIn();
}

int batPercent() { refreshPower(); return cachedPct; }
bool batCharging() { refreshPower(); return cachedCharging; }
bool usbPresent() { refreshPower(); return cachedUsb; }
bool usbPresentNow() {
  if (!pmuOk) return true; // Unknown power source: keep USB/CPU awake.
  cachedUsb = pmu.isVbusIn();
  return cachedUsb;
}

void pwrSetup() {
  if (!pmuOk) return;
  pmu.setPowerKeyPressOffTime(XPOWERS_POWEROFF_4S);
  pmu.disableIRQ(XPOWERS_AXP2101_ALL_IRQ);
  pmu.enableIRQ(XPOWERS_AXP2101_PKEY_SHORT_IRQ);
  pmu.clearIrqStatus();
}

bool pwrShortPressed() {
  if (!pmuOk) return false;
  pmu.getIrqStatus();
  bool hit = pmu.isPekeyShortPressIrq();
  if (hit) pmu.clearIrqStatus();
  return hit;
}
