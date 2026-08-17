from pathlib import Path
import re
import shutil
import subprocess

# Alarm-only clean desk-clock redesign.
# Runs after living_clock_v23.py. The combo/arcade build is intentionally untouched.
root = Path('source_alarm/TamaPoke')
ino = root / 'TamaPoke.ino'
src = ino.read_text(encoding='utf-8')


def must(old: str, new: str, label: str):
    global src
    if old not in src:
        raise SystemExit(f'Living Clock clean marker missing: {label}')
    src = src.replace(old, new, 1)

# New alarm-only version marker. NVS/save layout is unchanged.
src, n = re.subn(r'#define FW_VERSION "1\.6-ko-livingclock-test1"',
                 '#define FW_VERSION "1.8-ko-livingclock-cleanclock"', src, count=1)
if n != 1:
    raise SystemExit('Living Clock clean FW_VERSION marker missing')

# ---------------------------------------------------------------------------
# Scene geometry: quieter and more watch-like. Keep the Pokemon in the lower
# landscape with generous empty space around the clock typography.
# ---------------------------------------------------------------------------
must('gfx->fillCircle(CX, 428, 180, horizon);', 'gfx->fillCircle(CX, 454, 156, horizon);', 'main landscape')
must('gfx->fillCircle(112, 421, 74, pod <= 2 ? C565(0x48,0x86,0x5a) : C565(0x25,0x3a,0x46));',
     'gfx->fillCircle(103, 456, 58, pod <= 2 ? C565(0x48,0x86,0x5a) : C565(0x25,0x3a,0x46));', 'left hill')
must('gfx->fillCircle(365, 427, 78, pod <= 2 ? C565(0x4f,0x8f,0x61) : C565(0x29,0x3d,0x4b));',
     'gfx->fillCircle(374, 458, 61, pod <= 2 ? C565(0x4f,0x8f,0x61) : C565(0x29,0x3d,0x4b));', 'right hill')

# ---------------------------------------------------------------------------
# Remove the top battery/alarm pills entirely. They made the face feel like an
# app screen. A single slim glass status bar is drawn near the bottom instead.
# ---------------------------------------------------------------------------
old_status = r'''  // Centered battery + USB/charging pill.
  const int pct = batPercent();
  const bool hasBat = pct >= 0;
  const bool plugged = hasBat && usbPresent();
  const bool charging = hasBat && batCharging();
  const uint16_t glass = C565(0x18,0x25,0x42);
  gfx->fillRoundRect(CX - 75, 22, 150, 34, 17, glass);
  gfx->drawRoundRect(CX - 75, 22, 150, 34, 17, soft);
  const int ibx = CX - 59, iby = 31, ibw = 29, ibh = 15;
  const uint16_t batCol = charging ? UI_BAR_OK : UI_WHITE;
  gfx->drawRoundRect(ibx, iby, ibw, ibh, 3, batCol);
  gfx->fillRect(ibx + ibw, iby + 5, 3, 6, batCol);
  if (hasBat && !plugged) {
    int fw = (ibw - 4) * (pct > 100 ? 100 : pct) / 100;
    if (fw > 0) gfx->fillRect(ibx + 2, iby + 2, fw, ibh - 4, batCol);
  }
  if (plugged) {
    const uint16_t bolt = charging ? UI_BAR_OK : C565(0xff,0xd9,0x4a);
    gfx->fillTriangle(ibx+17, iby, ibx+10, iby+8, ibx+15, iby+8, bolt);
    gfx->fillTriangle(ibx+13, iby+7, ibx+19, iby+7, ibx+11, iby+15, bolt);
  }
  char bp[10]; snprintf(bp, sizeof(bp), hasBat ? "%d%%" : "--%%", hasBat ? (pct>100?100:pct) : 0);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(CX - 16, 32); gfx->print(bp);
  if (plugged) { gfx->setTextSize(1); gfx->setCursor(CX+36, 35); gfx->print(charging ? "CHG" : "USB"); }

  if (alarmEnabled()) {
    char ab[8]; snprintf(ab, sizeof(ab), "%02u:%02u", alarmHour(), alarmMinute());
    gfx->fillRoundRect(CX-60, 65, 120, 26, 13, glass);
    drawBellMini(CX-41, 68, UI_BAR_WARN);
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(CX-16, 71); gfx->print(ab);
  }
'''
new_status = r'''  // Slim information rail: battery on the left, alarm on the right.
  const int pct = batPercent();
  const bool hasBat = pct >= 0;
  const bool plugged = hasBat && usbPresent();
  const bool charging = hasBat && batCharging();
  const uint16_t glass = C565(0x16,0x20,0x39);
  const uint16_t batCol = charging ? UI_BAR_OK : UI_WHITE;
  gfx->fillRoundRect(CX-116, 418, 232, 27, 13, glass);
  gfx->drawRoundRect(CX-116, 418, 232, 27, 13, soft);

  const int ibx=CX-96, iby=426, ibw=24, ibh=11;
  gfx->drawRoundRect(ibx,iby,ibw,ibh,2,batCol);
  gfx->fillRect(ibx+ibw,iby+3,3,5,batCol);
  if (hasBat && !plugged) {
    int fw=(ibw-4)*(pct>100?100:pct)/100;
    if (fw>0) gfx->fillRect(ibx+2,iby+2,fw,ibh-4,batCol);
  }
  if (plugged) {
    gfx->fillTriangle(ibx+14,iby,ibx+9,iby+6,ibx+13,iby+6,UI_BAR_OK);
    gfx->fillTriangle(ibx+11,iby+5,ibx+16,iby+5,ibx+9,iby+11,UI_BAR_OK);
  }
  char bp[10]; snprintf(bp,sizeof(bp),hasBat?"%d%%":"--%%",hasBat?(pct>100?100:pct):0);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(1); gfx->setCursor(CX-64,426); gfx->print(bp);

  if (alarmEnabled()) {
    char ab[8]; snprintf(ab,sizeof(ab),"%02u:%02u",alarmHour(),alarmMinute());
    drawBellMini(CX+25,423,UI_BAR_WARN);
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(1); gfx->setCursor(CX+43,426); gfx->print(ab);
  } else {
    gfx->setTextColor(soft); gfx->setTextSize(1); gfx->setCursor(CX+36,426); gfx->print("ALARM --:--");
  }
'''
must(old_status, new_status, 'status rail')

# ---------------------------------------------------------------------------
# Strong clock hierarchy: large time, then date and weekday. No speech bubble,
# no text floating over the Pokemon.
# ---------------------------------------------------------------------------
must('gfx->setCursor(CX - (int)strlen(tb)*24, 112); gfx->print(tb);',
     'gfx->setCursor(CX - (int)strlen(tb)*24, 82); gfx->print(tb);', 'main time')
must('gfx->setCursor(CX - (int)strlen(db)*9, 205); gfx->print(db);',
     'gfx->setCursor(CX - (int)strlen(db)*9, 177); gfx->print(db);', 'date')
must('if (gLang == LANG_KO) uiPrintCenter(weekdayKo(tmv.tm_wday), 239, UI_WHITE, 3);',
     'if (gLang == LANG_KO) uiPrintCenter(weekdayKo(tmv.tm_wday), 214, soft, 2);', 'weekday')

# ---------------------------------------------------------------------------
# Hourly event: no bubble. A small medallion briefly appears behind plain text.
# ---------------------------------------------------------------------------
must('''    const int pulse = 58 + (int)((millis()/90UL)%8UL);
    gfx->fillCircle(CX, 325, pulse, C565(0xff,0xd4,0x55));
    gfx->fillCircle(CX, 325, pulse-8, C565(0xf4,0x78,0x65));
    char hb[12]; snprintf(hb, sizeof(hb), "%02d:00", tmv.tm_hour);
    uiPrintCenter(koOr("정각!","HOURLY!"), 278, UI_WHITE, 2);
    uiPrintCenter(hb, 311, UI_WHITE, 3);
    livingPet(406, false, 2);''',
'''    const int pulse = 43 + (int)((millis()/90UL)%6UL);
    gfx->fillCircle(CX, 292, pulse, C565(0xff,0xd4,0x55));
    gfx->fillCircle(CX, 292, pulse-7, C565(0xf4,0x78,0x65));
    char hb[12]; snprintf(hb, sizeof(hb), "%02d:00", tmv.tm_hour);
    uiPrintCenter(hb, 279, UI_WHITE, 2);
    livingPet(408, false, 2);''', 'hourly clean event')

# Alarm visual: plain wake text, no box/bubble.
must('''    gfx->fillCircle(CX, 330, 72 + (int)p, C565(0xff,0xc1,0x4f));
    gfx->fillCircle(CX, 330, 58 + (int)p/2, C565(0xff,0xea,0x9e));
    uiPrintCenter(koOr("일어날 시간!","WAKE UP!"), 274, UI_INK, 3);
    livingPet(409 - (int)((millis()/160UL)&1UL)*8, false, 2);''',
'''    gfx->fillCircle(CX, 300, 62 + (int)p/2, C565(0xff,0xc1,0x4f));
    gfx->fillCircle(CX, 300, 50 + (int)p/3, C565(0xff,0xea,0x9e));
    uiPrintCenter(koOr("일어나자!","WAKE UP!"), 286, UI_INK, 2);
    livingPet(408 - (int)((millis()/160UL)&1UL)*7, false, 2);''', 'wake clean event')

# Main Pokemon: lower and clear of all clock text.
must('livingPet(404, sleeping, (uint8_t)((millis()/5000UL)%3UL));',
     'livingPet(405, sleeping, (uint8_t)((millis()/5000UL)%3UL));', 'normal pet')

# Remove the old floating night text entirely. Night mode should be visually calm.
src, n = re.subn(r'''  if \(sleeping\) \{\n    gfx->setTextColor\(soft\);.*?\n  \}''',
                 '  if (sleeping) { /* clean clock: no floating speech text */ }',
                 src, count=1, flags=re.S)
if n != 1:
    raise SystemExit('Living Clock clean sleeping-text marker missing')

ino.write_text(src, encoding='utf-8')

# Compile the actual alarm-only firmware after all UI changes.
fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_alarm')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file():
    raise SystemExit('Living Clock clean alarm binary missing')
print('Living Clock clean desk-clock alarm firmware compiled successfully')

# Installer card: alarm-only. Combo page/card is intentionally untouched.
page=Path('site/index.html')
html=page.read_text(encoding='utf-8')
html=html.replace('🌅 LIVING CLOCK · TEST 1','🕒 LIVING CLOCK · CLEAN CLOCK',1)
html=html.replace('🌅 Living Clock 알람 테스트 설치','🕒 Living Clock 클린 알람시계 설치',1)
html=html.replace('manifest-alarm.json?v=livingclock1','manifest-alarm.json?v=livingclock-clean18',1)
# In case an older cute-final label is present after another page patch.
html=html.replace('💗 LIVING CLOCK · CUTE FINAL','🕒 LIVING CLOCK · CLEAN CLOCK',1)
html=html.replace('💗 Living Clock 귀여운 알람시계 설치','🕒 Living Clock 클린 알람시계 설치',1)
html=html.replace('manifest-alarm.json?v=livingclock-cute-final','manifest-alarm.json?v=livingclock-clean18',1)
html=html.replace('✓ 한글 위치 재정렬 · 둥근 말풍선 · 시간대별 귀여운 멘트 · 포켓몬/배경 간격 개선',
                  '✓ 말풍선 완전 제거 · 큰 시간 중심 · 날짜/요일 정렬 · 하단 배터리/알람 상태바 · 포켓몬 공간 분리',1)
page.write_text(html,encoding='utf-8')
print('Living Clock clean desk-clock installer page updated')
