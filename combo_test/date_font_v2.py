from pathlib import Path
import re, sys

root = Path(sys.argv[1])
p = root / 'TamaPoke.ino'
s = p.read_text(encoding='utf-8')

def one(old, new, label):
    global s
    if old not in s:
        raise SystemExit(f'marker not found: {label}')
    s = s.replace(old, new, 1)

s = re.sub(r'#define FW_VERSION "[^"]+"', '#define FW_VERSION "1.8-ko-combo-games1-datefont"', s, count=1)

one(
'''int clockH = 12, clockM = 0;  // hora en edicion
uint8_t clockPage = 0;        // 0 menu, 1 hora, 2 alarma, 3 alarm-h, 4 alarm-min''',
'''int clockH = 12, clockM = 0;  // hora en edicion
int clockY = 2026, clockMo = 1, clockD = 1; // fecha RTC en edicion
uint8_t clockPage = 0;        // 0 menu, 1 hora/fecha, 2 alarma, 3 alarm-h, 4 alarm-min, 5 fecha''',
'clock date fields')

one(
'''void openClock() {
  uint32_t e = pet.lastSeenEpoch ? pet.lastSeenEpoch : rtcEpoch();
  clockH = (e / 3600) % 24;
  clockM = (e / 60) % 60;
  alarmEditH = alarmHour();
  alarmEditM = alarmMinute();
  clockPage = 0;
  clockOpen = true;
}

void applyClock() {
  uint32_t base = pet.lastSeenEpoch ? pet.lastSeenEpoch : rtcEpoch();
  uint32_t e = (base / 86400) * 86400 + (uint32_t)clockH * 3600 + (uint32_t)clockM * 60;
  rtcSetEpoch(e);
  pet.setClock(e);
  clockPage = 0;
}''',
'''static int daysInMonth(int y, int m) {
  static const uint8_t D[12] = {31,28,31,30,31,30,31,31,30,31,30,31};
  int d = D[(m < 1 ? 1 : m > 12 ? 12 : m) - 1];
  if (m == 2 && ((y % 4 == 0 && y % 100 != 0) || (y % 400 == 0))) d = 29;
  return d;
}

static void clampClockDate() {
  if (clockY < 2025) clockY = 2120;
  if (clockY > 2120) clockY = 2025;
  if (clockMo < 1) clockMo = 12;
  if (clockMo > 12) clockMo = 1;
  int md = daysInMonth(clockY, clockMo);
  if (clockD < 1) clockD = md;
  if (clockD > md) clockD = 1;
}

void openClock() {
  uint32_t e = pet.lastSeenEpoch ? pet.lastSeenEpoch : rtcEpoch();
  if (!e) e = 1767225600UL;
  time_t tt = (time_t)e;
  struct tm tmv = {};
  gmtime_r(&tt, &tmv);
  clockY = tmv.tm_year + 1900;
  clockMo = tmv.tm_mon + 1;
  clockD = tmv.tm_mday;
  clockH = tmv.tm_hour;
  clockM = tmv.tm_min;
  alarmEditH = alarmHour();
  alarmEditM = alarmMinute();
  clockPage = 0;
  clockOpen = true;
}

void applyClock() {
  clampClockDate();
  struct tm tmv = {};
  tmv.tm_year = clockY - 1900;
  tmv.tm_mon = clockMo - 1;
  tmv.tm_mday = clockD;
  tmv.tm_hour = clockH;
  tmv.tm_min = clockM;
  tmv.tm_sec = 0;
  time_t tt = mktime(&tmv);
  if (tt <= 0) return;
  uint32_t e = (uint32_t)tt;
  rtcSetEpoch(e);
  pet.setClock(e);
  clockPage = 0;
}''',
'open/apply clock date support')

one(
'''  uiPrintAt(label, 82, y + 12, UI_INK, 2);''',
'''  uiPrintAt(label, 82, y + 9, UI_INK, gLang == LANG_KO ? 3 : 2);''',
'larger settings rows')

one(
'''static void renderTimeAdjust() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, UI_BG_DAY);
  uiPrintCenter(T(S_SET_TIME), 38, UI_INK, 3);

  char t[8]; snprintf(t, sizeof(t), "%02d:%02d", clockH, clockM);
  gfx->setTextColor(UI_INK); gfx->setTextSize(7); gfx->setCursor(CX - 105, 108); gfx->print(t);

  drawClockBtn(104, 190, "-"); drawClockBtn(170, 190, "+");
  drawClockBtn(252, 190, "-"); drawClockBtn(318, 190, "+");
  uiPrintAt(T(S_HOUR), 118, 252, UI_INK, 2);
  uiPrintAt(T(S_MIN), 274, 252, UI_INK, 2);

  gfx->fillRoundRect(133, 330, 200, 48, 14, UI_BAR_OK);
  uiPrintCenter(koOr("확인","OK"), 340, UI_BG_DAY, 2);
  uiPrintCenter(koOr("뒤로가기","BACK"), 400, UI_INK, 1);
}''',
'''static void renderTimeAdjust() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, UI_BG_DAY);
  uiPrintCenter(koOr("시간 / 날짜","TIME / DATE"), 34, UI_INK, 3);

  char t[8]; snprintf(t, sizeof(t), "%02d:%02d", clockH, clockM);
  gfx->setTextColor(UI_INK); gfx->setTextSize(7); gfx->setCursor(CX - 105, 96); gfx->print(t);

  drawClockBtn(104, 178, "-"); drawClockBtn(170, 178, "+");
  drawClockBtn(252, 178, "-"); drawClockBtn(318, 178, "+");
  uiPrintAt(T(S_HOUR), 118, 241, UI_INK, gLang == LANG_KO ? 3 : 2);
  uiPrintAt(T(S_MIN), 274, 241, UI_INK, gLang == LANG_KO ? 3 : 2);

  gfx->fillRoundRect(76, 282, 314, 42, 12, UI_WHITE);
  gfx->drawRoundRect(76, 282, 314, 42, 12, UI_TRACK);
  uiPrintAt(koOr("날짜","DATE"), 92, 291, UI_INK, gLang == LANG_KO ? 3 : 2);
  char db[16]; snprintf(db, sizeof(db), "%04d-%02d-%02d", clockY, clockMo, clockD);
  gfx->setTextColor(UI_INK); gfx->setTextSize(2); gfx->setCursor(218, 294); gfx->print(db);

  gfx->fillRoundRect(133, 340, 200, 46, 14, UI_BAR_OK);
  uiPrintCenter(koOr("확인","OK"), 350, UI_BG_DAY, 2);
  uiPrintCenter(koOr("뒤로가기","BACK"), 404, UI_INK, 1);
}''',
'time/date entry page')

marker = 'static void renderAlarmSettings() {'
if marker not in s:
    raise SystemExit('date page insertion marker missing')
date_block = r'''static void renderDateAdjust() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, UI_BG_DAY);
  uiPrintCenter(koOr("날짜 설정","SET DATE"), 36, UI_INK, 3);

  char db[16]; snprintf(db, sizeof(db), "%04d-%02d-%02d", clockY, clockMo, clockD);
  gfx->setTextColor(UI_INK); gfx->setTextSize(4);
  gfx->setCursor(CX - (int)strlen(db) * 12, 92); gfx->print(db);

  uiPrintAt(koOr("년","YEAR"), 66, 154, UI_INK, 2);
  uiPrintAt(koOr("월","MONTH"), 202, 154, UI_INK, 2);
  uiPrintAt(koOr("일","DAY"), 344, 154, UI_INK, 2);

  drawClockBtn(36, 196, "-");   drawClockBtn(98, 196, "+");
  drawClockBtn(174, 196, "-");  drawClockBtn(236, 196, "+");
  drawClockBtn(312, 196, "-");  drawClockBtn(374, 196, "+");

  char yb[8], mb[4], dd[4];
  snprintf(yb, sizeof(yb), "%d", clockY);
  snprintf(mb, sizeof(mb), "%02d", clockMo);
  snprintf(dd, sizeof(dd), "%02d", clockD);
  gfx->setTextColor(UI_INK); gfx->setTextSize(2);
  gfx->setCursor(57, 270); gfx->print(yb);
  gfx->setCursor(207, 270); gfx->print(mb);
  gfx->setCursor(345, 270); gfx->print(dd);

  gfx->fillRoundRect(133, 330, 200, 48, 14, UI_BAR_OK);
  uiPrintCenter(koOr("확인","OK"), 340, UI_BG_DAY, 2);
  uiPrintCenter(koOr("뒤로가기","BACK"), 402, UI_INK, 1);
}

'''
s = s.replace(marker, date_block + marker, 1)

one(
'''  uiPrintAt(koOr("알람","ALARM"), 76, 102, UI_INK, 2);''',
'''  uiPrintAt(koOr("알람","ALARM"), 76, 98, UI_INK, gLang == LANG_KO ? 3 : 2);''',
'larger alarm label')
one(
'''  uiPrintAt(koOr("시간","TIME"), 78, 177, UI_INK, 2);''',
'''  uiPrintAt(koOr("시간","TIME"), 78, 172, UI_INK, gLang == LANG_KO ? 3 : 2);''',
'larger alarm time label')

one(
'''  else if (clockPage == 3) renderAlarmNumber(true);
  else renderAlarmNumber(false);''',
'''  else if (clockPage == 3) renderAlarmNumber(true);
  else if (clockPage == 4) renderAlarmNumber(false);
  else renderDateAdjust();''',
'clock page dispatch')

one(
'''  if (clockPage == 1) {
    if (y >= 190 && y <= 248) {
      if (x >= 104 && x < 162) clockH = (clockH + 23) % 24;
      else if (x >= 170 && x < 228) clockH = (clockH + 1) % 24;
      else if (x >= 252 && x < 310) clockM = (clockM + 59) % 60;
      else if (x >= 318 && x < 376) clockM = (clockM + 1) % 60;
      sfxPlay(SFX_TAP); return;
    }
    if (y >= 330 && y <= 378 && x >= 133 && x <= 333) { applyClock(); sfxPlay(SFX_TAP); return; }
    if (y >= 390) { clockPage=0; return; }
    return;
  }''',
'''  if (clockPage == 1) {
    if (y >= 178 && y <= 236) {
      if (x >= 104 && x < 162) clockH = (clockH + 23) % 24;
      else if (x >= 170 && x < 228) clockH = (clockH + 1) % 24;
      else if (x >= 252 && x < 310) clockM = (clockM + 59) % 60;
      else if (x >= 318 && x < 376) clockM = (clockM + 1) % 60;
      sfxPlay(SFX_TAP); return;
    }
    if (y >= 278 && y <= 328 && x >= 70 && x <= 396) { clockPage=5; sfxPlay(SFX_TAP); return; }
    if (y >= 336 && y <= 390 && x >= 125 && x <= 341) { applyClock(); sfxPlay(SFX_TAP); return; }
    if (y >= 394) { clockPage=0; return; }
    return;
  }''',
'time page touch')

one(
'''  if (clockPage == 3 || clockPage == 4) {
    bool hp = clockPage == 3;''',
'''  if (clockPage == 5) {
    if (y >= 190 && y <= 262) {
      if      (x >= 30  && x < 94)  clockY--;
      else if (x >= 94  && x < 166) clockY++;
      else if (x >= 168 && x < 232) clockMo--;
      else if (x >= 232 && x < 304) clockMo++;
      else if (x >= 306 && x < 370) clockD--;
      else if (x >= 370 && x <= 438) clockD++;
      clampClockDate();
      sfxPlay(SFX_TAP); return;
    }
    if (y >= 326 && y <= 386 && x >= 125 && x <= 341) { applyClock(); sfxPlay(SFX_TAP); return; }
    if (y >= 390) { clockPage=1; return; }
    return;
  }

  if (clockPage == 3 || clockPage == 4) {
    bool hp = clockPage == 3;''',
'date touch handler')

one(
'''    const int dateW = (int)strlen(db) * 12;  // native GFX textSize(2): 6 px * 2
    const int gap = 8;
    const int totalW = dateW + gap + uiTextWidth(wd, 2);
    const int x0 = CX - totalW / 2;
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(2);
    gfx->setCursor(x0, 184); gfx->print(db);
    uiPrintAt(wd, x0 + dateW + gap, 184, UI_WHITE, 2);''',
'''    const int dateW = (int)strlen(db) * 18;
    const int gap = 10;
    const int totalW = dateW + gap + uiTextWidth(wd, 3);
    const int x0 = CX - totalW / 2;
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(3);
    gfx->setCursor(x0, 178); gfx->print(db);
    uiPrintAt(wd, x0 + dateW + gap, 178, UI_WHITE, 3);''',
'larger standby date')

one(
'''void drawBar(int x, int y, const char *label, uint8_t val) {
  uiPrintAt(label, x, y-2, inkColor(), 2);
  int bx = x + (gLang == LANG_KO ? 58 : 48);
  int bw = (gLang == LANG_KO ? 90 : 100), bh = (gLang == LANG_KO ? 12 : 15);
  uint16_t fill = (val >= 50) ? UI_BAR_OK : (val >= 25) ? UI_BAR_WARN : UI_BAR_BAD;
  gfx->fillRoundRect(bx, y+1, bw, bh, 4, UI_TRACK);
  int fw = (bw - 4) * val / 100;
  if (fw > 0) gfx->fillRoundRect(bx + 2, y + 3, fw, bh - 4, 3, fill);
}''',
'''void drawBar(int x, int y, const char *label, uint8_t val) {
  const uint8_t fs = (gLang == LANG_KO ? 3 : 2);
  uiPrintAt(label, x, y-5, inkColor(), fs);
  int bx, bw, bh;
  if (gLang == LANG_KO) {
    bx = x + uiTextWidth(label, fs) + 6;
    int right = (x < 200) ? 230 : 438;
    bw = right - bx;
    if (bw < 46) bw = 46;
    bh = 12;
  } else {
    bx = x + 48; bw = 100; bh = 15;
  }
  uint16_t fill = (val >= 50) ? UI_BAR_OK : (val >= 25) ? UI_BAR_WARN : UI_BAR_BAD;
  gfx->fillRoundRect(bx, y+1, bw, bh, 4, UI_TRACK);
  int fw = (bw - 4) * val / 100;
  if (fw > 0) gfx->fillRoundRect(bx + 2, y + 3, fw, bh - 4, 3, fill);
}''',
'larger Korean status labels')

one(
'''  uiPrintAt(label, x+(w-uiTextWidth(label,2))/2, y+h-30, UI_INK, 2);''',
'''  uint8_t lfs = (gLang == LANG_KO ? 3 : 2);
  uiPrintAt(label, x+(w-uiTextWidth(label,lfs))/2, y+h-34, UI_INK, lfs);''',
'larger game card labels')
one(
'''  uiPrintCenter(koOr("원하는 게임을 골라줘!","Choose a game"), 88, UI_INK, 1);''',
'''  uiPrintCenter(koOr("원하는 게임을 골라줘!","Choose a game"), 86, UI_INK, gLang == LANG_KO ? 2 : 1);''',
'larger game menu subtitle')
one(
'''uiPrintAt(lab[i],bx[i]+(104-uiTextWidth(lab[i],1))/2,390,UI_INK,1);''',
'''uiPrintAt(lab[i],bx[i]+(104-uiTextWidth(lab[i],gLang==LANG_KO?2:1))/2,386,UI_INK,gLang==LANG_KO?2:1);''',
'larger rps labels')

p.write_text(s, encoding='utf-8')
print('combo date/font v2 patch applied to', root)
