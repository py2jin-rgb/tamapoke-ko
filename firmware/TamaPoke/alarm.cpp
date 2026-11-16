#include "alarm.h"
#include <Preferences.h>

static bool gEnabled = false;
static uint8_t gHour = 7;
static uint8_t gMinute = 30;
static bool gRinging = false;
static uint32_t gSnoozeEpoch = 0;
static uint32_t gLastTriggeredMinute = 0;

static void saveSettings() {
  Preferences p;
  p.begin("tamapoke", false);
  p.putBool("alm_on", gEnabled);
  p.putUChar("alm_h", gHour);
  p.putUChar("alm_m", gMinute);
  p.end();
}

static void saveLastTrigger() {
  Preferences p;
  p.begin("tamapoke", false);
  p.putULong("alm_last", gLastTriggeredMinute);
  p.end();
}

void alarmBegin() {
  Preferences p;
  p.begin("tamapoke", true);
  gEnabled = p.getBool("alm_on", false);
  gHour = p.getUChar("alm_h", 7);
  gMinute = p.getUChar("alm_m", 30);
  gLastTriggeredMinute = p.getULong("alm_last", 0);
  p.end();
  if (gHour > 23) gHour = 7;
  if (gMinute > 59) gMinute = 30;
  gRinging = false;
  gSnoozeEpoch = 0;
}

void alarmUpdate(uint32_t epoch) {
  if (!epoch || gRinging) return;

  // One-shot snooze has priority over the normal daily alarm.
  if (gSnoozeEpoch) {
    if ((int32_t)(epoch - gSnoozeEpoch) >= 0) {
      gSnoozeEpoch = 0;
      gRinging = true;
    }
    return;
  }

  if (!gEnabled) return;
  uint8_t h = (epoch / 3600UL) % 24;
  uint8_t m = (epoch / 60UL) % 60;
  if (h != gHour || m != gMinute) return;

  uint32_t minuteKey = epoch / 60UL;
  if (minuteKey == gLastTriggeredMinute) return;
  gLastTriggeredMinute = minuteKey;
  saveLastTrigger();
  gRinging = true;
}

bool alarmEnabled() { return gEnabled; }
uint8_t alarmHour() { return gHour; }
uint8_t alarmMinute() { return gMinute; }

void alarmSetEnabled(bool on) {
  gEnabled = on;
  if (!on) {
    gRinging = false;
    gSnoozeEpoch = 0;
  }
  saveSettings();
}

void alarmSetTime(uint8_t hour, uint8_t minute) {
  gHour = hour % 24;
  gMinute = minute % 60;
  saveSettings();
}

bool alarmRinging() { return gRinging; }
bool alarmSnoozing() { return gSnoozeEpoch != 0; }
uint32_t alarmSnoozeUntil() { return gSnoozeEpoch; }

void alarmStop() {
  gRinging = false;
  gSnoozeEpoch = 0;
}

void alarmSnooze(uint32_t epoch, uint16_t minutes) {
  gRinging = false;
  if (!epoch) {
    gSnoozeEpoch = 0;
    return;
  }
  gSnoozeEpoch = epoch + (uint32_t)minutes * 60UL;
}
