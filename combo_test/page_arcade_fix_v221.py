from pathlib import Path
import re, shutil, subprocess

# Real-device polish for the ③ Cheonjiin + minigame combo only.
# Runs after page_arcade_v22.py. Alarm-only Living Clock is intentionally untouched.
root = Path('source_combo/TamaPoke')
ino = root / 'TamaPoke.ino'
src = ino.read_text(encoding='utf-8')


def once(old: str, new: str, label: str):
    global src
    if old not in src:
        raise SystemExit(f'v2.2.2 marker not found: {label}')
    src = src.replace(old, new, 1)

# Keep the workflow's v2.2 family marker, with a real-device fix suffix.
src, n = re.subn(r'#define FW_VERSION "2\.2-ko-combo-arcade"',
                 '#define FW_VERSION "2.2-ko-combo-arcade-fix222"', src, count=1)
if n != 1:
    raise SystemExit('v2.2.2 firmware version marker not found')

# ---------------------------------------------------------------------------
# HUB: the original arcade cards used uiPrintCenter(), which centers against the
# entire 466px screen. That is why left/right Korean labels piled up in the middle.
# ---------------------------------------------------------------------------
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
  arcPrintCenterIn(sub,x+6,y+55,w-12,UI_INK,1);
}'''
once(old,new,'arcade card local centering')

# Move the entry button upward so it is comfortably inside the round display.
once('''if (x >= 116 && x <= 350 && y >= 378 && y <= 438) {''',
     '''if (x >= 116 && x <= 350 && y >= 356 && y <= 414) {''','legacy arcade button touch')
once('''gfx->fillRoundRect(116,378,234,54,16,C565(0x58,0x49,0xa7));
  gfx->drawRoundRect(116,378,234,54,16,UI_WHITE);
  uiPrintCenter(koOr("새 미니게임 3종","3 NEW GAMES"),392,UI_WHITE,2);''',
'''gfx->fillRoundRect(116,360,234,48,16,C565(0x58,0x49,0xa7));
  gfx->drawRoundRect(116,360,234,48,16,UI_WHITE);
  uiPrintCenter(koOr("새 미니게임 3종","3 NEW GAMES"),373,UI_WHITE,2);''','legacy arcade button position')

# Short, glyph-safe Korean copy: no unsupported arrow/emoji characters.
once('''arcCard(46,112,176,114,C565(0x9f,0xd2,0xff),koOr("테트리스","TETRIS"),koOr("줄 클리어 → 속도 UP","LINES → SPEED UP"));
  arcCard(244,112,176,114,C565(0xa9,0xe3,0xa6),koOr("지렁이","SNAKE"),koOr("먹기 → 속도/장애물 UP","FOOD → HARDER"));
  arcCard(72,246,322,110,C565(0xff,0xd2,0x8b),koOr("지뢰찾기","MINESWEEPER"),koOr("클리어 → 판/지뢰 증가","CLEAR → MORE MINES"));''',
'''arcCard(46,112,176,114,C565(0x9f,0xd2,0xff),koOr("테트리스","TETRIS"),koOr("줄 지우면 빨라져!","LINES = FASTER"));
  arcCard(244,112,176,114,C565(0xa9,0xe3,0xa6),koOr("지렁이","SNAKE"),koOr("먹으면 더 빨라져!","FOOD = FASTER"));
  arcCard(72,246,322,110,C565(0xff,0xd2,0x8b),koOr("지뢰찾기","MINESWEEPER"),koOr("깨면 지뢰가 늘어!","CLEAR = MORE MINES"));''','arcade safe copy')

# ---------------------------------------------------------------------------
# TETRIS: board was 220x352 from y=82..434 while controls started at y=390,
# so the controls literally covered the last rows. Shrink/center the board and
# make DROP a true hard-drop. Add a ghost outline and simple wall-kick rotation.
# ---------------------------------------------------------------------------
once('''lastInteract=millis(); if(y<62){arcTetrisOpen=false;arcMenuOpen=true;return;} if(arcTOver){arcStartTetris();return;}
  if(y<338) return;
  if(x<118){ if(arcTFits(arcTX-1,arcTY,arcTRot)) arcTX--; }
  else if(x<232){ uint8_t nr=(arcTRot+1)&3; if(arcTFits(arcTX,arcTY,nr)) arcTRot=nr; }
  else if(x<346){ if(arcTFits(arcTX+1,arcTY,arcTRot)) arcTX++; }
  else { arcTDrop(); arcTScore+=2; }
  sfxPlay(SFX_TAP);''',
'''lastInteract=millis(); if(y<62){arcTetrisOpen=false;arcMenuOpen=true;return;} if(arcTOver){arcStartTetris();return;}
  if(y<374) return;
  if(x<165){ if(arcTFits(arcTX-1,arcTY,arcTRot)) arcTX--; }
  else if(x<230){
    uint8_t nr=(arcTRot+1)&3;
    if(arcTFits(arcTX,arcTY,nr)) arcTRot=nr;
    else if(arcTFits(arcTX-1,arcTY,nr)){arcTX--;arcTRot=nr;}
    else if(arcTFits(arcTX+1,arcTY,nr)){arcTX++;arcTRot=nr;}
  }
  else if(x<295){ if(arcTFits(arcTX+1,arcTY,arcTRot)) arcTX++; }
  else {
    uint16_t bonus=0;
    while(arcTFits(arcTX,arcTY+1,arcTRot)){arcTY++;bonus++;}
    arcTScore += bonus*2; arcTLock(); arcTNext=millis()+arcTDelay();
  }
  sfxPlay(SFX_TAP);''','Tetris touch and hard drop')

once('''const int ox=123,oy=82,cs=22; gfx->fillRect(ox-2,oy-2,224,356,C565(0x0d,0x13,0x25));''',
'''const int cs=18,ox=CX-(10*cs)/2,oy=80; gfx->fillRoundRect(ox-5,oy-5,10*cs+10,16*cs+10,10,C565(0x0d,0x13,0x25));''','Tetris board geometry')

# Insert ghost drawing immediately before the live piece.
once('''if(!arcTOver) for(int y=0;y<4;y++) for(int x=0;x<4;x++) if(arcTBit(arcTType,arcTRot,x,y)){int by=arcTY+y;if(by>=0)gfx->fillRoundRect(ox+(arcTX+x)*cs+1,oy+by*cs+1,cs-2,cs-2,3,cc[arcTType+1]);}''',
'''if(!arcTOver){
    int ghostY=arcTY; while(arcTFits(arcTX,ghostY+1,arcTRot)) ghostY++;
    for(int y=0;y<4;y++) for(int x=0;x<4;x++) if(arcTBit(arcTType,arcTRot,x,y)){
      int by=ghostY+y; if(by>=0) gfx->drawRoundRect(ox+(arcTX+x)*cs+3,oy+by*cs+3,cs-6,cs-6,3,C565(0x68,0x7a,0x9a));
    }
    for(int y=0;y<4;y++) for(int x=0;x<4;x++) if(arcTBit(arcTType,arcTRot,x,y)){
      int by=arcTY+y;if(by>=0)gfx->fillRoundRect(ox+(arcTX+x)*cs+1,oy+by*cs+1,cs-2,cs-2,3,cc[arcTType+1]);
    }
  }''','Tetris ghost piece')

once('''gfx->fillRoundRect(22,390,94,48,12,C565(0x5c,0x72,0xa8)); uiPrintCenter("<",400,UI_WHITE,3);
  gfx->fillRoundRect(126,390,94,48,12,C565(0x7e,0x62,0xb8)); uiPrintCenter(koOr("회전","ROT"),402,UI_WHITE,1);
  gfx->fillRoundRect(230,390,94,48,12,C565(0x5c,0x72,0xa8)); uiPrintCenter(">",400,UI_WHITE,3);
  gfx->fillRoundRect(334,390,110,48,12,C565(0x4f,0xa8,0x73)); uiPrintCenter(koOr("내리기","DROP"),402,UI_WHITE,1); gfx->flush();''',
'''gfx->fillRoundRect(103,382,62,42,10,C565(0x5c,0x72,0xa8)); arcPrintCenterIn("<",103,389,62,UI_WHITE,2);
  gfx->fillRoundRect(168,382,62,42,10,C565(0x7e,0x62,0xb8)); arcPrintCenterIn(koOr("회전","ROT"),168,395,62,UI_WHITE,1);
  gfx->fillRoundRect(233,382,62,42,10,C565(0x5c,0x72,0xa8)); arcPrintCenterIn(">",233,389,62,UI_WHITE,2);
  gfx->fillRoundRect(298,382,62,42,10,C565(0x4f,0xa8,0x73)); arcPrintCenterIn(koOr("낙하","DROP"),298,395,62,UI_WHITE,1); gfx->flush();''','Tetris control layout')

# ---------------------------------------------------------------------------
# SNAKE: fit the entire 14x14 play field inside the round screen and fix two
# gameplay bugs (tail-cell false collision and stale obstacle duplicate checks).
# ---------------------------------------------------------------------------
once('''static void arcSResetStage(){
  arcSLen=4;arcSDX=1;arcSDY=0; for(int i=0;i<4;i++){arcSX[i]=6-i;arcSY[i]=7;} arcSEaten=0;
  arcSRocks=arcSStage>1?arcSStage-1:0;if(arcSRocks>10)arcSRocks=10;
  for(int i=0;i<arcSRocks;i++){do{arcSRX[i]=random(14);arcSRY[i]=random(14);}while(arcSOnSnake(arcSRX[i],arcSRY[i])||(arcSRX[i]==6&&arcSRY[i]==7));}
  arcSFood(); arcSNext=millis()+arcSSpeed();
}''',
'''static void arcSResetStage(){
  arcSLen=4;arcSDX=1;arcSDY=0; for(int i=0;i<4;i++){arcSX[i]=6-i;arcSY[i]=7;} arcSEaten=0;
  memset(arcSRX,0xff,sizeof(arcSRX)); memset(arcSRY,0xff,sizeof(arcSRY));
  arcSRocks=arcSStage>1?arcSStage-1:0;if(arcSRocks>10)arcSRocks=10;
  for(int i=0;i<arcSRocks;i++){
    bool bad; do{
      arcSRX[i]=random(14);arcSRY[i]=random(14); bad=arcSOnSnake(arcSRX[i],arcSRY[i]);
      for(int j=0;j<i;j++) if(arcSRX[j]==arcSRX[i]&&arcSRY[j]==arcSRY[i]) bad=true;
      if(abs((int)arcSRX[i]-6)<=1 && abs((int)arcSRY[i]-7)<=1) bad=true;
    }while(bad);
  }
  arcSFood(); arcSNext=millis()+arcSSpeed();
}''','Snake obstacle reset')

once('''static void arcSMove(){
  int nx=arcSX[0]+arcSDX,ny=arcSY[0]+arcSDY; if(nx<0||nx>=14||ny<0||ny>=14||arcSOnSnake(nx,ny)||arcSOnRock(nx,ny)){arcSOver=true;sfxPlay(SFX_GAME_OVER);return;}
  bool eat=(nx==arcSFoodX&&ny==arcSFoodY); if(eat&&arcSLen<95)arcSLen++;
  for(int i=arcSLen-1;i>0;i--){arcSX[i]=arcSX[i-1];arcSY[i]=arcSY[i-1];}arcSX[0]=nx;arcSY[0]=ny;
  if(eat){arcSEaten++;arcSScore+=10*arcSStage;sfxPlay(SFX_MOLE_HIT2);if(arcSEaten>=arcSGoal()){arcSStage++;arcSBanner=millis()+1100;sfxPlay(SFX_MEDAL);arcSResetStage();}else arcSFood();}
}''',
'''static void arcSMove(){
  int nx=arcSX[0]+arcSDX,ny=arcSY[0]+arcSDY;
  bool eat=(nx==arcSFoodX&&ny==arcSFoodY),hitSelf=false;
  int bodyCheck=arcSLen-(eat?0:1); for(int i=0;i<bodyCheck;i++) if(arcSX[i]==nx&&arcSY[i]==ny){hitSelf=true;break;}
  if(nx<0||nx>=14||ny<0||ny>=14||hitSelf||arcSOnRock(nx,ny)){arcSOver=true;sfxPlay(SFX_GAME_OVER);return;}
  if(eat&&arcSLen<95)arcSLen++;
  for(int i=arcSLen-1;i>0;i--){arcSX[i]=arcSX[i-1];arcSY[i]=arcSY[i-1];}arcSX[0]=nx;arcSY[0]=ny;
  if(eat){arcSEaten++;arcSScore+=10*arcSStage;sfxPlay(SFX_MOLE_HIT2);if(arcSEaten>=arcSGoal()){arcSStage++;arcSBanner=millis()+1100;sfxPlay(SFX_MEDAL);arcSResetStage();}else arcSFood();}
}''','Snake collision correctness')

once('''const int cs=23,ox=72,oy=92;gfx->fillRoundRect(ox-6,oy-6,334,334,14,C565(0x76,0xb7,0x68));''',
'''const int cs=20,ox=CX-(14*cs)/2,oy=94;gfx->fillRoundRect(ox-6,oy-6,14*cs+12,14*cs+12,14,C565(0x76,0xb7,0x68));''','Snake board geometry')
once('''gfx->fillRoundRect(px-8,py-8,16,16,4,C565(0x59,0x55,0x55));''',
     '''gfx->fillRoundRect(px-7,py-7,14,14,4,C565(0x59,0x55,0x55));''','Snake rock size')
once('''gfx->fillCircle(fx,fy,8,C565(0xf0,0x42,0x55));gfx->fillRect(fx-1,fy-12,3,5,C565(0x42,0x7d,0x38));''',
     '''gfx->fillCircle(fx,fy,7,C565(0xf0,0x42,0x55));gfx->fillRect(fx-1,fy-10,3,4,C565(0x42,0x7d,0x38));''','Snake food size')
once('''gfx->fillCircle(px,py,i?8:10,c);''','''gfx->fillCircle(px,py,i?7:9,c);''','Snake body size')

# ---------------------------------------------------------------------------
# MINESWEEPER: adaptive cell size keeps 6x6..9x9 inside the circular screen.
# Flood fill now marks queued cells so duplicate queue entries cannot prematurely
# fill the fixed 81-cell queue and leave blank islands unopened.
# ---------------------------------------------------------------------------
once('''static void arcMFlood(int start){int q[81],qh=0,qt=0;q[qt++]=start;while(qh<qt){int id=q[qh++];if(arcMOpen[id]||arcMFlag[id])continue;arcMOpen[id]=true;if(arcMCount(id))continue;int x=id%arcMN,y=id/arcMN;for(int yy=y-1;yy<=y+1;yy++)for(int xx=x-1;xx<=x+1;xx++)if(xx>=0&&yy>=0&&xx<arcMN&&yy<arcMN){int ni=yy*arcMN+xx;if(!arcMOpen[ni]&&!arcMMine[ni]&&qt<81)q[qt++]=ni;}}}''',
'''static void arcMFlood(int start){int q[81],qh=0,qt=0;bool queued[81]={0};q[qt++]=start;queued[start]=true;while(qh<qt){int id=q[qh++];if(arcMOpen[id]||arcMFlag[id])continue;arcMOpen[id]=true;if(arcMCount(id))continue;int x=id%arcMN,y=id/arcMN;for(int yy=y-1;yy<=y+1;yy++)for(int xx=x-1;xx<=x+1;xx++)if(xx>=0&&yy>=0&&xx<arcMN&&yy<arcMN){int ni=yy*arcMN+xx;if(!arcMOpen[ni]&&!arcMMine[ni]&&!queued[ni]&&qt<81){queued[ni]=true;q[qt++]=ni;}}}}''','Minesweeper flood fill')

# Same geometry expression in touch and render.
src = src.replace('int cs=34,gw=arcMN*cs,ox=CX-gw/2,oy=116;',
                  'int cs=(arcMN<=6?38:(arcMN==7?35:(arcMN==8?32:30))),gw=arcMN*cs,ox=CX-gw/2,oy=112;',2)
if src.count('int cs=34,gw=arcMN*cs,ox=CX-gw/2,oy=116;'):
    raise SystemExit('Minesweeper old geometry still present')

once('''gfx->fillRoundRect(150,66,166,38,12,arcMFlagMode?C565(0xff,0x9a,0x64):C565(0x83,0xb7,0xe6));uiPrintCenter(arcMFlagMode?koOr("🚩 깃발 모드","FLAG MODE"):koOr("칸 열기 모드","OPEN MODE"),76,UI_INK,1);''',
'''gfx->fillRoundRect(150,66,166,38,12,arcMFlagMode?C565(0xff,0x9a,0x64):C565(0x83,0xb7,0xe6));arcPrintCenterIn(arcMFlagMode?koOr("깃발 모드","FLAG MODE"):koOr("칸 열기 모드","OPEN MODE"),150,76,166,UI_INK,1);''','Minesweeper mode label')

ino.write_text(src, encoding='utf-8')

# Compile the corrected final combo firmware.
fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_combo')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file():
    raise SystemExit('v2.2.2 combo firmware missing')
print('v2.2.2 arcade real-device polish compiled successfully')

# Update only the third installer card/version.
p=Path('site/index.html')
html=p.read_text(encoding='utf-8')
html=html.replace('🎮 COMBO · ARCADE 2.2','🎮 COMBO · ARCADE 2.2.2 FIX',1)
html=html.replace('🎮 천지인 한방팩 v2.2 설치','🎮 천지인 한방팩 v2.2.2 설치',1)
html=html.replace('manifest-combo.json?v=arcade22','manifest-combo.json?v=arcade222fix',1)
anchor='✓ v2.2: 테트리스 · 아보 지렁이 · 찌리리공 지뢰찾기 추가</p>'
if anchor in html:
    html=html.replace(anchor,anchor+'\n    <p class="ok">✓ v2.2.2: 실기 UI 전면 수정 · 테트리스 보드/조작 개선 · 지렁이 충돌/장애물 수정 · 지뢰찾기 판/연쇄열기 수정</p>',1)
p.write_text(html,encoding='utf-8')
print('v2.2.2 third installer card updated')
