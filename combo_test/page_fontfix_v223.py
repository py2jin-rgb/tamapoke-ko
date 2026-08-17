from pathlib import Path
import re, shutil, subprocess

# ③ combo-only Korean typography pass after arcade v2.2.2 real-device polish.
# Robust against small coordinate/layout changes made by earlier quality patches.
root = Path('source_combo/TamaPoke')
ino = root / 'TamaPoke.ino'
src = ino.read_text(encoding='utf-8')


def once(old: str, new: str, label: str, required=True):
    global src
    if old not in src:
        if required:
            raise SystemExit(f'v2.2.3 font marker not found: {label}')
        print(f'v2.2.3 font optional marker already changed/skipped: {label}')
        return False
    src = src.replace(old, new, 1)
    return True

# Version marker while retaining the workflow's 2.2 family grep.
src, n = re.subn(r'#define FW_VERSION "2\.2-ko-combo-arcade-fix222"',
                 '#define FW_VERSION "2.2-ko-combo-arcade-fix223"', src, count=1)
if n != 1:
    raise SystemExit('v2.2.3 version marker missing')

# ---------------------------------------------------------------------------
# Legacy game cards. Earlier quality patches may have shifted the baseline, so
# match the semantic uiPrintAt(label, ...) call rather than one exact coordinate.
# ---------------------------------------------------------------------------
legacy_pat = re.compile(
    r'uiPrintAt\(label,\s*x\+\(w-uiTextWidth\(label,\s*2\)\)/2,\s*y\+h-\d+,\s*UI_INK,\s*2\);'
)
legacy_repl = '''uint8_t labelSize = (uiTextWidth(label,2) <= w-16) ? 2 : 1;
  int labelY = y + h - (labelSize==2 ? 31 : 24);
  uiPrintAt(label, x+(w-uiTextWidth(label,labelSize))/2, labelY, UI_INK, labelSize);'''
src, legacy_n = legacy_pat.subn(legacy_repl, src, count=1)
if legacy_n != 1:
    # If an earlier patch already made this adaptive, accept it instead of failing.
    if 'labelSize = (uiTextWidth(label,2)' not in src:
        print('v2.2.3 warning: legacy game card renderer shape changed; keeping prior renderer')

# Hub title/subtitle hierarchy. Optional because quality patches can legitimately
# move these lines while retaining correct Korean rendering.
once('''uiPrintCenter(koOr("놀이 선택","PLAY"), 54, UI_INK, 3);
  uiPrintCenter(koOr("원하는 게임을 골라줘!","Choose a game"), 88, UI_INK, 1);''',
'''uiPrintCenter(koOr("놀이 선택","PLAY"), 50, UI_INK, 2);
  uiPrintCenter(koOr("원하는 게임을 골라줘!","Choose a game"), 80, UI_TRACK, 1);''',
'legacy hub title typography', required=False)

# New arcade cards: measured local centering + automatic font size.
once('''static void arcCard(int x,int y,int w,int h,uint16_t c,const char* title,const char* sub) {
  gfx->fillRoundRect(x,y,w,h,18,c); gfx->drawRoundRect(x,y,w,h,18,UI_INK);
  arcPrintCenterIn(title,x,y+18,w,UI_INK,2);
  arcPrintCenterIn(sub,x+6,y+55,w-12,UI_INK,1);
}''',
'''static void arcCard(int x,int y,int w,int h,uint16_t c,const char* title,const char* sub) {
  gfx->fillRoundRect(x,y,w,h,18,c); gfx->drawRoundRect(x,y,w,h,18,UI_INK);
  uint8_t ts = (uiTextWidth(title,2) <= w-16) ? 2 : 1;
  arcPrintCenterIn(title,x,y+(ts==2?18:23),w,UI_INK,ts);
  arcPrintCenterIn(sub,x+8,y+57,w-16,UI_INK,1);
}''','arcade adaptive Korean font')

# Avoid mixed Latin/Korean baselines on status rows in Korean mode.
once('''char h[42]; snprintf(h,sizeof(h),koOr("STAGE %u  줄 %u/%u","STAGE %u  LINES %u/%u"),arcTStage,arcTStageLines,arcTGoal()); uiPrintCenter(h,57,UI_WHITE,1);''',
'''char h[42]; snprintf(h,sizeof(h),koOr("단계 %u  줄 %u/%u","STAGE %u  LINES %u/%u"),arcTStage,arcTStageLines,arcTGoal()); uiPrintCenter(h,57,UI_WHITE,1);''','Tetris Korean status font')
once('''char h[42];snprintf(h,sizeof(h),koOr("STAGE %u  먹이 %u/%u","STAGE %u  FOOD %u/%u"),arcSStage,arcSEaten,arcSGoal());uiPrintCenter(h,57,UI_INK,1);''',
'''char h[42];snprintf(h,sizeof(h),koOr("단계 %u  먹이 %u/%u","STAGE %u  FOOD %u/%u"),arcSStage,arcSEaten,arcSGoal());uiPrintCenter(h,57,UI_INK,1);''','Snake Korean status font')
once('''char h[36];snprintf(h,sizeof(h),koOr("STAGE %u  %ux%u  지뢰 %u","STAGE %u  %ux%u  MINES %u"),arcMStage,arcMN,arcMN,arcMMines);uiPrintCenter(h,50,UI_INK,1);''',
'''char h[36];snprintf(h,sizeof(h),koOr("단계 %u  %ux%u  지뢰 %u","STAGE %u  %ux%u  MINES %u"),arcMStage,arcMN,arcMN,arcMMines);uiPrintCenter(h,50,UI_INK,1);''','Mine Korean status font')

# RPS choice cards: adaptive font when the old exact renderer is still present.
once('''for(int i=0;i<3;i++){gfx->fillRoundRect(bx[i],330,104,82,16,bc[i]); gfx->drawRoundRect(bx[i],330,104,82,16,UI_INK); drawRpsIcon(bx[i]+52,354,i,UI_INK); uiPrintAt(lab[i],bx[i]+(104-uiTextWidth(lab[i],1))/2,390,UI_INK,1);}''',
'''for(int i=0;i<3;i++){gfx->fillRoundRect(bx[i],330,104,82,16,bc[i]); gfx->drawRoundRect(bx[i],330,104,82,16,UI_INK); drawRpsIcon(bx[i]+52,354,i,UI_INK); uint8_t ls=(uiTextWidth(lab[i],2)<=92)?2:1; uiPrintAt(lab[i],bx[i]+(104-uiTextWidth(lab[i],ls))/2,ls==2?382:390,UI_INK,ls);}''','RPS label typography', required=False)

ino.write_text(src, encoding='utf-8')

# Compile again so the published combo binary is guaranteed to contain typography fixes.
fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_combo')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file():
    raise SystemExit('v2.2.3 combo firmware missing')
print('v2.2.3 Korean typography pass compiled successfully')

p=Path('site/index.html'); html=p.read_text(encoding='utf-8')
html=html.replace('🎮 COMBO · ARCADE 2.2.2 FIX','🎮 COMBO · ARCADE 2.2.3 FINAL FIX',1)
html=html.replace('🎮 천지인 한방팩 v2.2.2 설치','🎮 천지인 한방팩 v2.2.3 설치',1)
html=html.replace('manifest-combo.json?v=arcade222fix','manifest-combo.json?v=arcade223fix',1)
if '✓ v2.2.3: 한글 폰트 자동 크기/중앙정렬 보정' not in html:
    anchor='✓ v2.2.2: 실기 UI 전면 수정 · 테트리스 보드/조작 개선 · 지렁이 충돌/장애물 수정 · 지뢰찾기 판/연쇄열기 수정</p>'
    if anchor in html:
        html=html.replace(anchor,anchor+'\n    <p class="ok">✓ v2.2.3: 한글 폰트 자동 크기/중앙정렬 보정 · 카드별 기준선 통일</p>',1)
p.write_text(html,encoding='utf-8')
