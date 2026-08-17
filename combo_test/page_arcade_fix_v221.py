from pathlib import Path
import re, shutil, subprocess

# Real-device UI fix for the ③ Cheonjiin + minigame combo only.
# Runs after page_arcade_v22.py. Alarm-only Living Clock is intentionally untouched.
root = Path('source_combo/TamaPoke')
ino = root / 'TamaPoke.ino'
src = ino.read_text(encoding='utf-8')


def once(old: str, new: str, label: str):
    global src
    if old not in src:
        raise SystemExit(f'v2.2.1 marker not found: {label}')
    src = src.replace(old, new, 1)

# Keep the v2.2 workflow marker while distinguishing the real-device 2.2.1 fix.
src, n = re.subn(r'#define FW_VERSION "2\.2-ko-combo-arcade"',
                 '#define FW_VERSION "2.2-ko-combo-arcade-fix221"', src, count=1)
if n != 1:
    raise SystemExit('v2.2.1 firmware version marker not found')

# uiPrintCenter() always centers on the whole 466px screen. The arcade cards/buttons
# are local rectangles, so using it there made left/right Korean labels overlap.
# Center UTF-8 Korean inside each local rectangle using the existing Korean width renderer.
old = '''static void arcCard(int x,int y,int w,int h,uint16_t c,const char* title,const char* sub) {
  gfx->fillRoundRect(x,y,w,h,18,c); gfx->drawRoundRect(x,y,w,h,18,UI_INK);
  uiPrintCenter(title,y+18,UI_INK,2);
  uiPrintCenter(sub,y+52,UI_INK,1);
}'''
new = '''static void arcPrintCenterIn(const char* text,int x,int y,int w,uint16_t color,uint8_t size) {
  int tw = uiTextWidth(text, size);
  uiPrintAt(text, x + (w - tw) / 2, y, color, size);
}
static void arcCard(int x,int y,int w,int h,uint16_t c,const char* title,const char* sub) {
  gfx->fillRoundRect(x,y,w,h,18,c); gfx->drawRoundRect(x,y,w,h,18,UI_INK);
  arcPrintCenterIn(title,x,y+18,w,UI_INK,2);
  arcPrintCenterIn(sub,x+6,y+54,w-12,UI_INK,1);
}'''
once(old,new,'arcade card local centering')

# Tetris: each control label belongs to its own button rather than the screen center.
once('''gfx->fillRoundRect(22,390,94,48,12,C565(0x5c,0x72,0xa8)); uiPrintCenter("<",400,UI_WHITE,3);
  gfx->fillRoundRect(126,390,94,48,12,C565(0x7e,0x62,0xb8)); uiPrintCenter(koOr("회전","ROT"),402,UI_WHITE,1);
  gfx->fillRoundRect(230,390,94,48,12,C565(0x5c,0x72,0xa8)); uiPrintCenter(">",400,UI_WHITE,3);
  gfx->fillRoundRect(334,390,110,48,12,C565(0x4f,0xa8,0x73)); uiPrintCenter(koOr("내리기","DROP"),402,UI_WHITE,1); gfx->flush();''',
'''gfx->fillRoundRect(22,390,94,48,12,C565(0x5c,0x72,0xa8)); arcPrintCenterIn("<",22,400,94,UI_WHITE,3);
  gfx->fillRoundRect(126,390,94,48,12,C565(0x7e,0x62,0xb8)); arcPrintCenterIn(koOr("회전","ROT"),126,402,94,UI_WHITE,1);
  gfx->fillRoundRect(230,390,94,48,12,C565(0x5c,0x72,0xa8)); arcPrintCenterIn(">",230,400,94,UI_WHITE,3);
  gfx->fillRoundRect(334,390,110,48,12,C565(0x4f,0xa8,0x73)); arcPrintCenterIn(koOr("내리기","DROP"),334,402,110,UI_WHITE,1); gfx->flush();''',
'Tetris control labels')

# Minesweeper: mode label must stay inside the blue/orange mode button. Avoid an emoji
# glyph too, because the embedded Korean font does not guarantee emoji coverage.
once('''gfx->fillRoundRect(150,66,166,38,12,arcMFlagMode?C565(0xff,0x9a,0x64):C565(0x83,0xb7,0xe6));uiPrintCenter(arcMFlagMode?koOr("🚩 깃발 모드","FLAG MODE"):koOr("칸 열기 모드","OPEN MODE"),76,UI_INK,1);''',
'''gfx->fillRoundRect(150,66,166,38,12,arcMFlagMode?C565(0xff,0x9a,0x64):C565(0x83,0xb7,0xe6));arcPrintCenterIn(arcMFlagMode?koOr("깃발 모드","FLAG MODE"):koOr("칸 열기 모드","OPEN MODE"),150,76,166,UI_INK,1);''',
'Minesweeper mode label')

ino.write_text(src, encoding='utf-8')

# Compile the corrected final combo firmware.
fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_combo')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file():
    raise SystemExit('v2.2.1 combo firmware missing')
print('v2.2.1 arcade real-device UI fix compiled successfully')

# Update only the third installer card/version.
p=Path('site/index.html')
html=p.read_text(encoding='utf-8')
html=html.replace('🎮 COMBO · ARCADE 2.2','🎮 COMBO · ARCADE 2.2.1 FIX',1)
html=html.replace('🎮 천지인 한방팩 v2.2 설치','🎮 천지인 한방팩 v2.2.1 설치',1)
html=html.replace('manifest-combo.json?v=arcade22','manifest-combo.json?v=arcade221fix',1)
anchor='✓ v2.2: 테트리스 · 아보 지렁이 · 찌리리공 지뢰찾기 추가</p>'
if anchor in html and '카드/버튼 한글 겹침 수정' not in html:
    html=html.replace(anchor,anchor+'\n    <p class="ok">✓ v2.2.1: 아케이드 카드/버튼 한글 겹침 수정 · 각 영역 정확한 중앙정렬</p>',1)
p.write_text(html,encoding='utf-8')
print('v2.2.1 third installer card updated')
