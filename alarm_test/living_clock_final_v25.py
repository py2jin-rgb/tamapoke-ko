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
pat = re.compile(
    r'\s*if \(sleeping\) \{ /\* clean clock: no floating speech text \*/ \}\s*'
    r'else if \(\(\(millis\(\)/1000UL\)%17UL\) < 3UL\) \{.*?\n\s*\}',
    re.S,
)
src, n = pat.subn('\n  // v1.9: no floating messages or white speech rectangles on the watch face.\n', src, count=1)
if n != 1:
    raise SystemExit('v1.9 residual bubble block not found')

src = src.replace('좋은 하루!', '')
src = src.replace('HI!', '')
src = src.replace('gfx->fillRoundRect(CX-116, 418, 232, 27, 13, glass);','gfx->fillRoundRect(CX-108, 421, 216, 24, 12, glass);', 1)
src = src.replace('gfx->drawRoundRect(CX-116, 418, 232, 27, 13, soft);','gfx->drawRoundRect(CX-108, 421, 216, 24, 12, soft);', 1)
src = src.replace('const int ibx=CX-96, iby=426, ibw=24, ibh=11;','const int ibx=CX-90, iby=427, ibw=22, ibh=10;', 1)
src = src.replace('gfx->setCursor(CX-64,426);', 'gfx->setCursor(CX-61,427);', 1)
src = src.replace('drawBellMini(CX+25,423,UI_BAR_WARN);', 'drawBellMini(CX+20,424,UI_BAR_WARN);', 1)
src = src.replace('gfx->setCursor(CX+43,426);', 'gfx->setCursor(CX+38,427);', 1)
src = src.replace('gfx->setCursor(CX+36,426);', 'gfx->setCursor(CX+31,427);', 1)
needle = 'gfx->drawCircle(CX, CY, 224, soft);'
insert = '''gfx->drawCircle(CX, CY, 224, soft);\n  gfx->drawCircle(CX, CY, 218, C565(0x67,0x78,0xb8));\n  gfx->fillCircle(CX, 23, 2, soft);\n  gfx->fillCircle(443, CY, 2, soft);\n  gfx->fillCircle(CX, 443, 2, soft);\n  gfx->fillCircle(23, CY, 2, soft);'''
if needle not in src: raise SystemExit('v1.9 rim marker missing')
src = src.replace(needle, insert, 1)
needle = 'livingPet(405, sleeping, (uint8_t)((millis()/5000UL)%3UL));'
replacement = '''gfx->fillRoundRect(CX-58, 397, 116, 3, 2, pod <= 2 ? C565(0x72,0xb8,0x76) : C565(0x55,0x68,0x82));\n  livingPet(405, sleeping, (uint8_t)((millis()/5000UL)%3UL));'''
if needle not in src: raise SystemExit('v1.9 pet marker missing')
src = src.replace(needle, replacement, 1)
if 'fillRoundRect(300, 307, 74, 31' in src: raise SystemExit('v1.9 white idle rectangle still present')
if re.search(r'else if \(\(\(millis\(\)/1000UL\)%17UL\) < 3UL\)', src): raise SystemExit('v1.9 residual timed idle bubble branch still present')
ino.write_text(src, encoding='utf-8')

fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_alarm')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file(): raise SystemExit('Living Clock v1.9 binary missing')
print('Living Clock v1.9 final alarm firmware compiled successfully')

page=Path('site/index.html')
html=page.read_text(encoding='utf-8')
html=html.replace('🕒 LIVING CLOCK · CLEAN CLOCK','✨ LIVING CLOCK · FINAL 1.9',1)
html=html.replace('🕒 Living Clock 클린 알람시계 설치','✨ Living Clock v1.9 알람시계 설치',1)
html=html.replace('manifest-alarm.json?v=livingclock-clean18','manifest-alarm.json?v=livingclock-final19',1)
html=html.replace('✓ 말풍선 완전 제거 · 큰 시간 중심 · 날짜/요일 정렬 · 하단 배터리/알람 상태바 · 포켓몬 공간 분리','✓ 잔여 흰 박스/말풍선 완전 제거 · 이중 시계 테두리 · 큰 시간 중심 · 슬림 상태바 · 포켓몬 공간 정리',1)

# Global flashing warning: applies to every Korean-patch installer on this page.
# Keep it visually dominant and explicit because selecting Erase wipes saved data.
if 'id="erase-global-warning"' not in html:
    warning = '''\n<div id="erase-global-warning" style="margin:18px 0 24px;padding:18px 16px;border:3px solid #ff3b3b;border-radius:14px;background:#2b0b0b;color:#ff4d4d;text-align:center;font-size:24px;line-height:1.45;font-weight:900;text-decoration:underline;text-decoration-thickness:3px;text-underline-offset:5px;box-shadow:0 0 0 2px rgba(255,59,59,.18)">⚠️ 한글패치 설치 시 ERASE / 초기화는 절대 체크하지 마세요! ⚠️<br><span style="font-size:18px">기존 포켓몬·설정·저장 데이터를 유지하려면 ERASE 체크 없이 설치하세요.</span></div>\n'''
    anchor = '<div class="notice">'
    if anchor not in html: raise SystemExit('global erase warning anchor missing')
    html = html.replace(anchor, warning + anchor, 1)
page.write_text(html,encoding='utf-8')
print('Living Clock v1.9 installer card updated + global ERASE warning added')

# The main workflow already executes this script after Battle 2.4 is built and
# after site/index.html exists. Publish ⑤ here so the existing workflow deploys
# OTA + real five-step volume control without changing ①~④.
subprocess.run(['python3','combo_test/ota_pipeline_v25.py'],check=True)
if not Path('site/manifest-ota.json').is_file(): raise SystemExit('⑤ OTA volume manifest missing')
if not Path('build_ota/TamaPoke.ino.bin').is_file(): raise SystemExit('⑤ OTA volume binary missing')
print('⑤ OTA + Volume 2.6 ready for Pages deployment')
