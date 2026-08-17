from pathlib import Path
import re, shutil, subprocess

root = Path('source_combo/TamaPoke')
ino = root / 'TamaPoke.ino'
src = ino.read_text(encoding='utf-8')


def replace_function(text: str, signature: str, new_func: str) -> str:
    m = re.search(re.escape(signature) + r'\s*\{', text)
    if not m:
        raise SystemExit(f'v2.2.4 function not found: {signature}')
    start = m.start()
    brace = text.find('{', m.start(), m.end())
    depth = 0
    end = None
    for i in range(brace, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise SystemExit(f'v2.2.4 closing brace not found: {signature}')
    return text[:start] + new_func + text[end:]


# Version marker: this patch runs after v2.2.3 typography.
src, n = re.subn(r'#define FW_VERSION "2\.2-ko-combo-arcade-fix223"',
                 '#define FW_VERSION "2.2-ko-combo-arcade-fix224"', src, count=1)
if n != 1:
    raise SystemExit('v2.2.4 firmware version marker missing')

# Helpers for stable, locally centered card labels.  Long Korean names drop to
# size 1 automatically instead of spilling into neighboring cards.
helper_marker = 'void gameMenuTap(int16_t x, int16_t y) {'
helper = r'''static void comboFinalTextIn(const char *text, int x, int y, int w, uint16_t color, uint8_t preferred) {
  uint8_t sz = preferred;
  if (sz > 1 && uiTextWidth(text, sz) > w - 14) sz = 1;
  int tw = uiTextWidth(text, sz);
  uiPrintAt(text, x + (w - tw) / 2, y, color, sz);
}

static void comboFinalCard(int x, int y, int w, int h, uint16_t bg, const char *title, uint8_t icon) {
  gfx->fillRoundRect(x, y, w, h, 16, bg);
  gfx->drawRoundRect(x, y, w, h, 16, C565(0x53,0x5b,0x6b));
  const int cx = x + w / 2;
  const int iy = y + 29;
  if (icon == 0) {
    gfx->fillCircle(cx, iy, 15, UI_WHITE); gfx->fillRect(cx-15,iy-2,30,5,UI_INK);
    gfx->fillCircle(cx,iy,5,UI_INK); gfx->fillCircle(cx,iy,2,UI_WHITE);
  } else if (icon == 1) {
    gfx->fillCircle(cx,iy-2,14,C565(0xa8,0x67,0x3f));
    gfx->fillCircle(cx-5,iy-5,2,UI_INK); gfx->fillCircle(cx+5,iy-5,2,UI_INK);
  } else if (icon == 2) {
    gfx->drawLine(cx-15,iy+9,cx+15,iy-12,UI_INK); gfx->drawLine(cx+15,iy+9,cx-15,iy-12,UI_INK);
    gfx->fillCircle(cx-12,iy+8,5,UI_INK); gfx->fillCircle(cx+12,iy+8,5,UI_INK);
  } else {
    gfx->fillCircle(cx,iy,15,C565(0xf4,0xf4,0xf4));
    gfx->setTextColor(UI_INK); gfx->setTextSize(2); gfx->setCursor(cx-6,iy-8); gfx->print("?");
  }
  comboFinalTextIn(title, x+5, y+h-25, w-10, UI_INK, 2);
}

void gameMenuTap(int16_t x, int16_t y) {'''
if helper_marker not in src:
    raise SystemExit('v2.2.4 game menu insertion marker missing')
src = src.replace(helper_marker, helper, 1)

# Restore every proven legacy game explicitly.  Do not delegate to a later
# quality-patch menu renderer, because that is what caused older games to vanish.
src = replace_function(src, 'void gameMenuTap(int16_t x, int16_t y)', r'''void gameMenuTap(int16_t x, int16_t y) {
  lastInteract = millis();
  if (y < 78) { gameMenuOpen = false; return; }
  if (x >= 42 && x <= 222 && y >= 104 && y <= 198) { gameMenuOpen=false; startGame(); sfxPlay(SFX_GAME_START); return; }
  if (x >= 244 && x <= 424 && y >= 104 && y <= 198) { gameMenuOpen=false; startMole(); return; }
  if (x >= 42 && x <= 222 && y >= 210 && y <= 304) { gameMenuOpen=false; startRps(); return; }
  if (x >= 244 && x <= 424 && y >= 210 && y <= 304) { gameMenuOpen=false; startQuiz151(); return; }
  if (x >= 68 && x <= 398 && y >= 316 && y <= 360) { gameMenuOpen=false; startMonsterCatch(); return; }
  if (x >= 68 && x <= 398 && y >= 370 && y <= 418) { gameMenuOpen=false; arcMenuOpen=true; sfxPlay(SFX_GAME_OPEN); return; }
}''')

src = replace_function(src, 'void renderGameMenu()', r'''void renderGameMenu() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, C565(0xf3,0xf6,0xf8));
  uiPrintCenter(koOr("놀이 선택","PLAY"), 42, UI_INK, 2);
  uiPrintCenter(koOr("원하는 게임을 골라줘!","CHOOSE A GAME"), 72, UI_TRACK, 1);

  comboFinalCard(42,104,180,94,C565(0xff,0xb4,0x72),koOr("공놀이","BALL"),0);
  comboFinalCard(244,104,180,94,C565(0xff,0xd2,0x64),koOr("피카츄 잡기","MOLE"),1);
  comboFinalCard(42,210,180,94,C565(0x79,0xbd,0xf4),koOr("가위바위보","RPS"),2);
  comboFinalCard(244,210,180,94,C565(0xd7,0xc1,0xf6),koOr("151 퀴즈","151 QUIZ"),3);

  gfx->fillRoundRect(68,316,330,44,13,C565(0x48,0xc8,0xb1));
  gfx->drawRoundRect(68,316,330,44,13,C565(0x36,0x78,0x72));
  comboFinalTextIn(koOr("몬스터볼 캐치","MONSTER BALL CATCH"),68,329,330,UI_INK,2);

  gfx->fillRoundRect(68,370,330,44,13,C565(0x67,0x54,0xc5));
  gfx->drawRoundRect(68,370,330,44,13,UI_WHITE);
  comboFinalTextIn(koOr("새 미니게임 3종","3 NEW GAMES"),68,383,330,UI_WHITE,2);
  gfx->flush();
}''')

# Critical anti-flicker fix: the old arcade page treated the BOTTOM edge as
# BACK.  The same finger that opened the page could immediately close it, then
# reopen it, producing the user's visible button/page shaking.  Back is now
# top-edge only and the rest of the empty page is inert.
src = replace_function(src, 'void arcGameMenuTap(int16_t x,int16_t y)', r'''void arcGameMenuTap(int16_t x,int16_t y) {
  lastInteract=millis();
  if (y < 78) { arcMenuOpen=false; gameMenuOpen=true; return; }
  if (x>=46 && x<=222 && y>=112 && y<=226) { arcStartTetris(); return; }
  if (x>=244 && x<=420 && y>=112 && y<=226) { arcStartSnake(); return; }
  if (x>=72 && x<=394 && y>=246 && y<=356) { arcStartMine(1); return; }
}''')

src = replace_function(src, 'void arcRenderMenu()', r'''void arcRenderMenu() {
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xf1,0xf4,0xfb));
  uiPrintCenter(koOr("포켓 아케이드","POCKET ARCADE"),40,UI_INK,2);
  uiPrintCenter(koOr("클리어할수록 어려워져요!","CLEAR = HARDER"),70,UI_TRACK,1);
  arcCard(46,106,176,116,C565(0x9f,0xd2,0xff),koOr("테트리스","TETRIS"),koOr("줄을 지우면 빨라져!","LINES = FASTER"));
  arcCard(244,106,176,116,C565(0xa9,0xe3,0xa6),koOr("지렁이","SNAKE"),koOr("먹으면 더 빨라져!","FOOD = FASTER"));
  arcCard(72,244,322,110,C565(0xff,0xd2,0x8b),koOr("지뢰찾기","MINESWEEPER"),koOr("깨면 지뢰가 늘어!","MORE MINES"));
  uiPrintCenter(koOr("맨 위를 누르면 돌아가기","TAP TOP TO GO BACK"),400,UI_TRACK,1);
  gfx->flush();
}''')

# Tetris control scheme requested from the real-device photo:
# huge LEFT/RIGHT touch zones beside the board; bottom has ROTATE and DROP only.
src = replace_function(src, 'void arcTetrisTap(int16_t x,int16_t y)', r'''void arcTetrisTap(int16_t x,int16_t y) {
  lastInteract=millis();
  if (y < 64) { arcTetrisOpen=false; arcMenuOpen=true; return; }
  if (arcTOver) { arcStartTetris(); return; }

  // Side touch zones are deliberately tall and away from the falling board.
  if (y >= 105 && y <= 366 && x <= 106) {
    if (arcTFits(arcTX-1,arcTY,arcTRot)) arcTX--;
    sfxPlay(SFX_TAP); return;
  }
  if (y >= 105 && y <= 366 && x >= 360) {
    if (arcTFits(arcTX+1,arcTY,arcTRot)) arcTX++;
    sfxPlay(SFX_TAP); return;
  }

  // Bottom row: only ROTATE / HARD DROP.
  if (y >= 378 && y <= 438 && x >= 116 && x <= 226) {
    uint8_t nr=(arcTRot+1)&3;
    if(arcTFits(arcTX,arcTY,nr)) arcTRot=nr;
    else if(arcTFits(arcTX-1,arcTY,nr)){arcTX--;arcTRot=nr;}
    else if(arcTFits(arcTX+1,arcTY,nr)){arcTX++;arcTRot=nr;}
    sfxPlay(SFX_TAP); return;
  }
  if (y >= 378 && y <= 438 && x >= 240 && x <= 350) {
    uint16_t bonus=0;
    while(arcTFits(arcTX,arcTY+1,arcTRot)){arcTY++;bonus++;}
    arcTScore += bonus*2; arcTLock(); arcTNext=millis()+arcTDelay();
    sfxPlay(SFX_TAP); return;
  }
}''')

src = replace_function(src, 'void arcRenderTetris()', r'''void arcRenderTetris() {
  uint32_t now=millis(); if(!arcTOver && now>=arcTNext){arcTDrop();arcTNext=now+arcTDelay();}
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0x2b,0x49,0x86));
  uiPrintCenter(koOr("포켓 테트리스","POCKET TETRIS"),24,UI_WHITE,2);
  char h[42]; snprintf(h,sizeof(h),koOr("단계 %u  줄 %u/%u","STAGE %u  LINES %u/%u"),arcTStage,arcTStageLines,arcTGoal()); uiPrintCenter(h,52,UI_WHITE,1);

  const int cs=18, ox=CX-(10*cs)/2, oy=76;
  gfx->fillRoundRect(ox-5,oy-5,10*cs+10,16*cs+10,10,C565(0x0d,0x13,0x25));
  static const uint16_t cc[8]={0,C565(0x55,0xd8,0xff),C565(0xff,0xd0,0x55),C565(0xc0,0x76,0xff),C565(0x6d,0xdd,0x78),C565(0xff,0x72,0x72),C565(0x74,0x8c,0xff),C565(0xff,0x9b,0x55)};
  for(int yy=0;yy<16;yy++) for(int xx=0;xx<10;xx++){
    if(arcTB[yy][xx]) gfx->fillRoundRect(ox+xx*cs+1,oy+yy*cs+1,cs-2,cs-2,3,cc[arcTB[yy][xx]]);
    else gfx->drawRect(ox+xx*cs,oy+yy*cs,cs,cs,C565(0x42,0x58,0x83));
  }
  if(!arcTOver){
    int ghostY=arcTY; while(arcTFits(arcTX,ghostY+1,arcTRot)) ghostY++;
    for(int yy=0;yy<4;yy++) for(int xx=0;xx<4;xx++) if(arcTBit(arcTType,arcTRot,xx,yy)){
      int by=ghostY+yy; if(by>=0) gfx->drawRoundRect(ox+(arcTX+xx)*cs+3,oy+by*cs+3,cs-6,cs-6,3,C565(0x75,0x8a,0xb0));
    }
    for(int yy=0;yy<4;yy++) for(int xx=0;xx<4;xx++) if(arcTBit(arcTType,arcTRot,xx,yy)){
      int by=arcTY+yy; if(by>=0) gfx->fillRoundRect(ox+(arcTX+xx)*cs+1,oy+by*cs+1,cs-2,cs-2,3,cc[arcTType+1]);
    }
  }

  // Side movement pads exactly where they are easy to hit around the round bezel.
  gfx->fillRoundRect(18,135,78,172,20,C565(0x3d,0x65,0xa8));
  gfx->drawRoundRect(18,135,78,172,20,C565(0x88,0xb0,0xff));
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(5); gfx->setCursor(44,195); gfx->print("<");
  gfx->fillRoundRect(370,135,78,172,20,C565(0x3d,0x65,0xa8));
  gfx->drawRoundRect(370,135,78,172,20,C565(0x88,0xb0,0xff));
  gfx->setCursor(395,195); gfx->print(">");

  gfx->fillRoundRect(116,382,110,48,14,C565(0x80,0x62,0xbb));
  comboFinalTextIn(koOr("회전","ROTATE"),116,396,110,UI_WHITE,2);
  gfx->fillRoundRect(240,382,110,48,14,C565(0x4f,0xa8,0x73));
  comboFinalTextIn(koOr("낙하","DROP"),240,396,110,UI_WHITE,2);

  if(arcTOver){
    gfx->fillRoundRect(92,174,282,92,18,C565(0x8d,0x2e,0x3d));
    uiPrintCenter(koOr("게임 오버","GAME OVER"),192,UI_WHITE,2);
    uiPrintCenter(koOr("화면을 눌러 재시작","TAP TO RESTART"),232,UI_WHITE,1);
  }
  if(arcTBanner>now) uiPrintCenter(koOr("단계 상승!","STAGE UP!"),326,UI_BAR_WARN,2);
  gfx->flush();
}''')

ino.write_text(src, encoding='utf-8')

# Recompile the exact published combo firmware.
fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_combo')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file():
    raise SystemExit('v2.2.4 combo firmware missing')
print('v2.2.4 combo final real-device fix compiled successfully')

# Installer card/version text.
p=Path('site/index.html')
html=p.read_text(encoding='utf-8')
html=html.replace('🎮 COMBO · ARCADE 2.2.3 FINAL FIX','🎮 COMBO · ARCADE 2.2.4 REAL FINAL',1)
html=html.replace('🎮 천지인 한방팩 v2.2.3 설치','🎮 천지인 한방팩 v2.2.4 설치',1)
html=html.replace('manifest-combo.json?v=arcade223fix','manifest-combo.json?v=arcade224final',1)
anchor='✓ v2.2.3: 한글 폰트 자동 크기/중앙정렬 보정 · 카드별 기준선 통일</p>'
if anchor in html and 'v2.2.4' not in html:
    html=html.replace(anchor,anchor+'\n    <p class="ok">✓ v2.2.4: 기존 게임 5종 복구 · 메뉴 떨림 제거 · 테트리스 좌우 측면키 + 하단 회전/낙하 전용 · 제목 폰트 통일</p>',1)
p.write_text(html,encoding='utf-8')
