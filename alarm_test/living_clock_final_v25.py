from pathlib import Path
import re, shutil, subprocess

# Alarm-only v1.9 final polish. Runs after living_clock_finish_v24.py.
# Removes the residual idle bubble completely and adds small watch-face refinements.
root = Path('source_alarm/TamaPoke')
ino = root / 'TamaPoke.ino'
src = ino.read_text(encoding='utf-8')

# Version.
src, n = re.subn(r'#define FW_VERSION "1\.8-ko-livingclock-cleanclock"',
                 '#define FW_VERSION "1.9-ko-livingclock-final"', src, count=1)
if n != 1:
    raise SystemExit('v1.9 version marker missing')

# Remove the whole residual idle-message branch left over from TEST1.
# v1.8 had converted the sleeping branch to a no-op but left the following
# `else if (...) { white rounded rect + 좋은 하루! }` alive.
pat = re.compile(
    r'\s*if \(sleeping\) \{ /\* clean clock: no floating speech text \*/ \}\s*'
    r'else if \(\(\(millis\(\)/1000UL\)%17UL\) < 3UL\) \{.*?\n\s*\}',
    re.S,
)
src, n = pat.subn('\n  // v1.9: no floating messages or white speech rectangles on the watch face.\n', src, count=1)
if n != 1:
    raise SystemExit('v1.9 residual bubble block not found')

# Slightly slimmer bottom information rail and a little more breathing room.
src = src.replace('gfx->fillRoundRect(CX-116, 418, 232, 27, 13, glass);',
                  'gfx->fillRoundRect(CX-108, 421, 216, 24, 12, glass);', 1)
src = src.replace('gfx->drawRoundRect(CX-116, 418, 232, 27, 13, soft);',
                  'gfx->drawRoundRect(CX-108, 421, 216, 24, 12, soft);', 1)
src = src.replace('const int ibx=CX-96, iby=426, ibw=24, ibh=11;',
                  'const int ibx=CX-90, iby=427, ibw=22, ibh=10;', 1)
src = src.replace('gfx->setCursor(CX-64,426);', 'gfx->setCursor(CX-61,427);', 1)
src = src.replace('drawBellMini(CX+25,423,UI_BAR_WARN);', 'drawBellMini(CX+20,424,UI_BAR_WARN);', 1)
src = src.replace('gfx->setCursor(CX+43,426);', 'gfx->setCursor(CX+38,427);', 1)
src = src.replace('gfx->setCursor(CX+36,426);', 'gfx->setCursor(CX+31,427);', 1)

# Add a refined double rim and four tiny hour marks after the existing outer circle.
needle = 'gfx->drawCircle(CX, CY, 224, soft);'
insert = '''gfx->drawCircle(CX, CY, 224, soft);\n  gfx->drawCircle(CX, CY, 218, C565(0x67,0x78,0xb8));\n  // Four restrained watch marks keep the face clock-like without clutter.\n  gfx->fillCircle(CX, 23, 2, soft);\n  gfx->fillCircle(443, CY, 2, soft);\n  gfx->fillCircle(CX, 443, 2, soft);\n  gfx->fillCircle(23, CY, 2, soft);'''
if needle not in src:
    raise SystemExit('v1.9 rim marker missing')
src = src.replace(needle, insert, 1)

# Ground line: visually anchors the roaming Pokemon without a box/card.
needle = 'livingPet(405, sleeping, (uint8_t)((millis()/5000UL)%3UL));'
replacement = '''gfx->fillRoundRect(CX-58, 397, 116, 3, 2, pod <= 2 ? C565(0x72,0xb8,0x76) : C565(0x55,0x68,0x82));\n  livingPet(405, sleeping, (uint8_t)((millis()/5000UL)%3UL));'''
if needle not in src:
    raise SystemExit('v1.9 pet marker missing')
src = src.replace(needle, replacement, 1)

ino.write_text(src, encoding='utf-8')

# Compile the final alarm-only binary.
fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_alarm')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file():
    raise SystemExit('Living Clock v1.9 binary missing')
print('Living Clock v1.9 final alarm firmware compiled successfully')

# Update only the alarm installer card/version cache key.
page=Path('site/index.html')
html=page.read_text(encoding='utf-8')
html=html.replace('🕒 LIVING CLOCK · CLEAN CLOCK','✨ LIVING CLOCK · FINAL 1.9',1)
html=html.replace('🕒 Living Clock 클린 알람시계 설치','✨ Living Clock v1.9 알람시계 설치',1)
html=html.replace('manifest-alarm.json?v=livingclock-clean18','manifest-alarm.json?v=livingclock-final19',1)
html=html.replace('✓ 말풍선 완전 제거 · 큰 시간 중심 · 날짜/요일 정렬 · 하단 배터리/알람 상태바 · 포켓몬 공간 분리',
                  '✓ 잔여 흰 박스/말풍선 완전 제거 · 이중 시계 테두리 · 큰 시간 중심 · 슬림 상태바 · 포켓몬 공간 정리',1)
page.write_text(html,encoding='utf-8')
print('Living Clock v1.9 installer card updated')
