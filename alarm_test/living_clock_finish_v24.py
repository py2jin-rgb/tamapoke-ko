from pathlib import Path
import re
import shutil
import subprocess

# Final visual polish for the alarm-only Living Clock.
# Runs after living_clock_v23.py. Combo/arcade source is intentionally untouched.
root = Path('source_alarm/TamaPoke')
ino = root / 'TamaPoke.ino'
src = ino.read_text(encoding='utf-8')


def must(old: str, new: str, label: str):
    global src
    if old not in src:
        raise SystemExit(f'Living Clock v2 marker missing: {label}')
    src = src.replace(old, new, 1)

# Distinct firmware marker.
src, n = re.subn(r'#define FW_VERSION "1\.6-ko-livingclock-test1"',
                 '#define FW_VERSION "1.7-ko-livingclock-cute-final"', src, count=1)
if n != 1:
    raise SystemExit('Living Clock v2 FW_VERSION marker missing')

# Add a proper rounded speech bubble renderer right before livingPet().
needle = 'static void livingPet(int groundY, bool sleeping, uint8_t mood) {'
bubble = r'''static void livingBubble(const char *msg, uint16_t ink, uint16_t paper, uint16_t edge) {
  const int w = 214;
  const int h = 46;
  const int x = CX - w/2;
  const int y = 260;
  // soft shadow
  gfx->fillRoundRect(x+3, y+4, w, h, 18, C565(0x24,0x24,0x3c));
  // bubble body + two-line friendly border
  gfx->fillRoundRect(x, y, w, h, 18, paper);
  gfx->drawRoundRect(x, y, w, h, 18, edge);
  gfx->drawRoundRect(x+2, y+2, w-4, h-4, 16, C565(0xff,0xff,0xff));
  // bubble tail points toward the Pokemon below
  gfx->fillTriangle(CX-12, y+h-1, CX+8, y+h-1, CX-3, y+h+13, paper);
  gfx->drawLine(CX-12, y+h-1, CX-3, y+h+13, edge);
  gfx->drawLine(CX-3, y+h+13, CX+8, y+h-1, edge);
  uiPrintCenter(msg, y+14, ink, 2);
}

static const char* livingMessage(uint8_t pod, bool sleeping) {
  if (sleeping || pod == 4) return koOr("잘자~ 좋은 꿈!", "SWEET DREAMS!");
  if (pod == 0) return koOr("좋은 아침!", "GOOD MORNING!");
  if (pod == 1) return koOr("오늘도 힘내!", "HAVE A NICE DAY!");
  if (pod == 2) return koOr("노을이 예뻐!", "PRETTY SUNSET!");
  return koOr("오늘도 수고했어!", "GOOD EVENING!");
}

static void livingPet(int groundY, bool sleeping, uint8_t mood) {'''
if needle not in src:
    raise SystemExit('Living Clock v2 livingPet marker missing')
src = src.replace(needle, bubble, 1)

# Make the lower landscape less dominant so the clock typography and bubble breathe.
must('gfx->fillCircle(CX, 428, 180, horizon);',
     'gfx->fillCircle(CX, 446, 168, horizon);', 'main landscape')
must('gfx->fillCircle(112, 421, 74, pod <= 2 ? C565(0x48,0x86,0x5a) : C565(0x25,0x3a,0x46));',
     'gfx->fillCircle(104, 440, 64, pod <= 2 ? C565(0x48,0x86,0x5a) : C565(0x25,0x3a,0x46));', 'left hill')
must('gfx->fillCircle(365, 427, 78, pod <= 2 ? C565(0x4f,0x8f,0x61) : C565(0x29,0x3d,0x4b));',
     'gfx->fillCircle(372, 442, 68, pod <= 2 ? C565(0x4f,0x8f,0x61) : C565(0x29,0x3d,0x4b));', 'right hill')

# Battery pill a little slimmer/higher; alarm pill becomes a compact chip under it.
must('gfx->fillRoundRect(CX - 75, 22, 150, 34, 17, glass);',
     'gfx->fillRoundRect(CX - 72, 17, 144, 32, 16, glass);', 'battery body')
must('gfx->drawRoundRect(CX - 75, 22, 150, 34, 17, soft);',
     'gfx->drawRoundRect(CX - 72, 17, 144, 32, 16, soft);', 'battery border')
must('const int ibx = CX - 59, iby = 31, ibw = 29, ibh = 15;',
     'const int ibx = CX - 56, iby = 25, ibw = 29, ibh = 15;', 'battery icon position')
must('gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(CX - 16, 32); gfx->print(bp);',
     'gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(CX - 13, 26); gfx->print(bp);', 'battery text')
must('if (plugged) { gfx->setTextSize(1); gfx->setCursor(CX+36, 35); gfx->print(charging ? "CHG" : "USB"); }',
     'if (plugged) { gfx->setTextSize(1); gfx->setCursor(CX+38, 30); gfx->print(charging ? "CHG" : "USB"); }', 'charge text')
must('gfx->fillRoundRect(CX-60, 65, 120, 26, 13, glass);',
     'gfx->fillRoundRect(CX-55, 57, 110, 24, 12, glass);', 'alarm pill')
must('drawBellMini(CX-41, 68, UI_BAR_WARN);',
     'drawBellMini(CX-38, 59, UI_BAR_WARN);', 'alarm bell')
must('gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(CX-16, 71); gfx->print(ab);',
     'gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(CX-13, 62); gfx->print(ab);', 'alarm time')

# Re-space time/date/weekday. The Korean weekday no longer collides with date or Pokemon.
must('gfx->setCursor(CX - (int)strlen(tb)*24, 112); gfx->print(tb);',
     'gfx->setCursor(CX - (int)strlen(tb)*24, 94); gfx->print(tb);', 'main time')
must('gfx->setCursor(CX - (int)strlen(db)*9, 205); gfx->print(db);',
     'gfx->setCursor(CX - (int)strlen(db)*9, 181); gfx->print(db);', 'date')
must('if (gLang == LANG_KO) uiPrintCenter(weekdayKo(tmv.tm_wday), 239, UI_WHITE, 3);',
     'if (gLang == LANG_KO) uiPrintCenter(weekdayKo(tmv.tm_wday), 218, UI_WHITE, 2);', 'weekday')

# Hourly and wake overlays move slightly down and use the same cute bubble language.
must('uiPrintCenter(koOr("정각!","HOURLY!"), 278, UI_WHITE, 2);',
     'livingBubble(koOr("정각이야!", "HOURLY!"), UI_INK, C565(0xff,0xf2,0xf7), C565(0xff,0x8f,0xb5));', 'hourly bubble')
must('uiPrintCenter(hb, 311, UI_WHITE, 3);',
     'uiPrintCenter(hb, 326, UI_WHITE, 3);', 'hourly time')
must('livingPet(406, false, 2);',
     'livingPet(416, false, 2);', 'hourly pet')
must('uiPrintCenter(koOr("일어날 시간!","WAKE UP!"), 274, UI_INK, 3);',
     'livingBubble(koOr("일어날 시간이야!", "WAKE UP!"), UI_INK, C565(0xff,0xf4,0xdf), C565(0xff,0xb4,0x4d));', 'wake bubble')
must('livingPet(409 - (int)((millis()/160UL)&1UL)*8, false, 2);',
     'livingPet(418 - (int)((millis()/160UL)&1UL)*8, false, 2);', 'wake pet')

# Normal scene: always show a real speech bubble above the Pokemon. Keep Pokemon lower and centered.
must('livingPet(404, sleeping, (uint8_t)((millis()/5000UL)%3UL));',
     'livingBubble(livingMessage(pod, sleeping), UI_INK, C565(0xff,0xf5,0xfa), C565(0xff,0x91,0xba));\n  livingPet(420, sleeping, (uint8_t)((millis()/5000UL)%3UL));', 'normal bubble + pet')

# Remove legacy floating sleep text now that the speech bubble owns the Korean message.
src = re.sub(r'\n\s*if \(sleeping\) \{\s*gfx->setTextColor\(soft\);.*?\n\s*\}', '\n', src, count=1, flags=re.S)

ino.write_text(src, encoding='utf-8')

# Recompile ONLY the alarm source after visual polish.
fqbn = 'esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build = Path('build_alarm')
if build.exists():
    shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)], check=True)
if not (build / 'TamaPoke.ino.bin').is_file():
    raise SystemExit('Living Clock v2 alarm binary missing')
print('Living Clock cute final alarm firmware compiled successfully')

# Installer wording: second card only. Do not touch combo card/version.
page = Path('site/index.html')
html = page.read_text(encoding='utf-8')
html = html.replace('🌅 LIVING CLOCK · TEST 1', '💗 LIVING CLOCK · CUTE FINAL', 1)
html = html.replace('🌅 Living Clock 알람 테스트 설치', '💗 Living Clock 귀여운 알람시계 설치', 1)
html = html.replace('manifest-alarm.json?v=livingclock1', 'manifest-alarm.json?v=livingclock-cute-final', 1)
# Add a concise v2 note if the existing feature marker is present.
anchor = '✓ 정각 4초 이벤트 + 짧은 효과음 · 알람 시간 기상 연출'
if anchor in html and '말풍선' not in html:
    html = html.replace(anchor, anchor + '</p><p class="ok">✓ 한글 위치 재정렬 · 둥근 말풍선 · 시간대별 귀여운 멘트 · 포켓몬/배경 간격 개선', 1)
page.write_text(html, encoding='utf-8')
print('Living Clock cute final installer page updated')
