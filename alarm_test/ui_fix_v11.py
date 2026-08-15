from pathlib import Path

p = Path('source_alarm/TamaPoke/TamaPoke.ino')
s = p.read_text(encoding='utf-8')

# Bump only the alarm-test firmware version.
old_ver = '#define FW_VERSION "1.5-ko-alarm1.0"'
new_ver = '#define FW_VERSION "1.5-ko-alarm1.1"'
if old_ver not in s:
    raise SystemExit('alarm FW version marker not found')
s = s.replace(old_ver, new_ver, 1)

# The round AMOLED clips x=70 at y=42. Move the whole battery cluster
# inside the real circular visible area.
old_bat = '''  drawBatteryMini(70, 42, pct, UI_WHITE);
  char bp[8]; snprintf(bp, sizeof(bp), "%d%%", pct < 0 ? 0 : pct);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(108, 43); gfx->print(bp);'''
new_bat = '''  drawBatteryMini(112, 42, pct, UI_WHITE);
  char bp[8]; snprintf(bp, sizeof(bp), "%d%%", pct < 0 ? 0 : pct);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(151, 43); gfx->print(bp);'''
if old_bat not in s:
    raise SystemExit('standby battery block not found')
s = s.replace(old_bat, new_bat, 1)

# Do not render an ASCII date + Korean weekday as one mixed string.
# Draw the numeric date with the native GFX font and only the weekday through
# the Korean renderer, while keeping the whole line centered.
old_date = '''  char db[48];
  if (gLang == LANG_KO) {
    snprintf(db, sizeof(db), "%04d/%02d/%02d %s",
             tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday, weekdayKo(tmv.tm_wday));
    uiPrintCenter(db, 184, UI_WHITE, 2);
  } else {
    snprintf(db, sizeof(db), "%04d/%02d/%02d",
             tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday);
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(2);
    gfx->setCursor(CX - (int)strlen(db) * 6, 184); gfx->print(db);
  }'''
new_date = '''  char db[24];
  snprintf(db, sizeof(db), "%04d/%02d/%02d",
           tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday);
  if (gLang == LANG_KO) {
    const char *wd = weekdayKo(tmv.tm_wday);
    const int dateW = (int)strlen(db) * 12;  // native GFX textSize(2): 6 px * 2
    const int gap = 8;
    const int totalW = dateW + gap + uiTextWidth(wd, 2);
    const int x0 = CX - totalW / 2;
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(2);
    gfx->setCursor(x0, 184); gfx->print(db);
    uiPrintAt(wd, x0 + dateW + gap, 184, UI_WHITE, 2);
  } else {
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(2);
    gfx->setCursor(CX - (int)strlen(db) * 6, 184); gfx->print(db);
  }'''
if old_date not in s:
    raise SystemExit('standby date block not found')
s = s.replace(old_date, new_date, 1)

# The alarm build must inherit all stable Korean record fixes too.
required = (
    'uiPrintCenter(rec, 214, ink, 2);',
    'uiPrintCenter(rec, 76, ink, 2);',
    'uiPrintCenter(r, 256, ink, 2);',
)
for marker in required:
    if marker not in s:
        raise SystemExit(f'missing stable Korean renderer fix: {marker}')

p.write_text(s, encoding='utf-8')
print('alarm v1.1 UI fix applied: stable text fixes + battery position + split date/weekday')
