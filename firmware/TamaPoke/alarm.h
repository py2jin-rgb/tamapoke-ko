#pragma once
#include <Arduino.h>

// Persistent daily alarm settings. Time is interpreted in the same local RTC
// convention already used by TamaPoke (rtcEpoch()).
void alarmBegin();
void alarmUpdate(uint32_t epoch);

bool alarmEnabled();
uint8_t alarmHour();
uint8_t alarmMinute();
void alarmSetEnabled(bool on);
void alarmSetTime(uint8_t hour, uint8_t minute);

bool alarmRinging();
bool alarmSnoozing();
uint32_t alarmSnoozeUntil();

void alarmStop();
void alarmSnooze(uint32_t epoch, uint16_t minutes = 5);
