from pathlib import Path
import re, shutil, subprocess

root = Path('source_combo/TamaPoke')
ino = root / 'TamaPoke.ino'
src = ino.read_text(encoding='utf-8')


def once(old: str, new: str, label: str):
    global src
    if old not in src:
        raise SystemExit(f'v2.2 marker not found: {label}')
    src = src.replace(old, new, 1)

# Firmware version.
src, n = re.subn(r'#define FW_VERSION "2\.1-ko-combo-userfix"', '#define FW_VERSION "2.2-ko-combo-arcade"', src, count=1)
if n != 1:
    raise SystemExit('v2.2 version marker not found')

# New state flags beside the existing game hub state.
once('bool gameMenuOpen = false;', '''bool gameMenuOpen = false;
bool arcMenuOpen = false;
bool arcTetrisOpen = false;
bool arcSnakeOpen = false;
bool arcMineOpen = false;''', 'arcade state flags')

# Prototypes are needed because touch/render dispatch lives above the minigame implementations.
once('void renderRps();', '''void renderRps();
void arcGameMenuTap(int16_t x, int16_t y);
void arcRenderMenu();
void arcTetrisTap(int16_t x, int16_t y);
void arcRenderTetris();
void arcSnakeTap(int16_t x, int16_t y);
void arcRenderSnake();
void arcMineTap(int16_t x, int16_t y);
void arcRenderMine();''', 'arcade prototypes')

# Keep all new games modal for standby, swipes and long-press handling.
src = src.replace('gameMenuOpen ||', 'gameMenuOpen || arcMenuOpen || arcTetrisOpen || arcSnakeOpen || arcMineOpen ||')
src = src.replace('!gameMenuOpen &&', '!gameMenuOpen && !arcMenuOpen && !arcTetrisOpen && !arcSnakeOpen && !arcMineOpen &&')

# Alarm closes the arcade too.
once('gameOpen=false; sackOpen=false; gameMenuOpen=false;', 'gameOpen=false; sackOpen=false; gameMenuOpen=false; arcMenuOpen=false; arcTetrisOpen=false; arcSnakeOpen=false; arcMineOpen=false;', 'alarm closes arcade')

# Dispatch touches before the legacy menu.
once('if (gameMenuOpen) { gameMenuTap(x, y); return; }', '''if (arcTetrisOpen) { arcTetrisTap(x, y); return; }
  if (arcSnakeOpen) { arcSnakeTap(x, y); return; }
  if (arcMineOpen) { arcMineTap(x, y); return; }
  if (arcMenuOpen) { arcGameMenuTap(x, y); return; }
  if (gameMenuOpen) { gameMenuTap(x, y); return; }''', 'arcade tap dispatch')

# Dispatch renders before the legacy menu.
once('if (gameMenuOpen) { renderGameMenu(); return; }', '''if (arcTetrisOpen) { arcRenderTetris(); return; }
  if (arcSnakeOpen) { arcRenderSnake(); return; }
  if (arcMineOpen) { arcRenderMine(); return; }
  if (arcMenuOpen) { arcRenderMenu(); return; }
  if (gameMenuOpen) { renderGameMenu(); return; }''', 'arcade render dispatch')

# Wrap the existing game menu instead of replacing it: all old games remain untouched,
# and a compact NEW GAMES button opens the second page.
src, n1 = re.subn(r'void gameMenuTap\(int16_t x, int16_t y\)\s*\{', 'void gameMenuTapLegacy(int16_t x, int16_t y) {', src, count=1)
src, n2 = re.subn(r'void renderGameMenu\(\)\s*\{', 'void renderGameMenuLegacy() {', src, count=1)
if n1 != 1 or n2 != 1:
    raise SystemExit('legacy game menu functions not found')

arcade = r'''
// ============================================================================
// 2.2 ARCADE PACK: Tetris / Snake / Minesweeper
// Progressive difficulty is stage-based in all three games.
// ============================================================================

static void arcCloseAll() {
  arcMenuOpen=arcTetrisOpen=arcSnakeOpen=arcMineOpen=false;
}

void gameMenuTap(int16_t x, int16_t y) {
  if (x >= 116 && x <= 350 && y >= 378 && y <= 438) {
    gameMenuOpen=false; arcMenuOpen=true; sfxPlay(SFX_GAME_OPEN); return;
  }
  gameMenuTapLegacy(x,y);
}

void renderGameMenu() {
  renderGameMenuLegacy();
  gfx->fillRoundRect(116,378,234,54,16,C565(0x58,0x49,0xa7));
  gfx->drawRoundRect(116,378,234,54,16,UI_WHITE);
  uiPrintCenter(koOr("새 미니게임 3종","3 NEW GAMES"),392,UI_WHITE,2);
  gfx->flush();
}

static void arcCard(int x,int y,int w,int h,uint16_t c,const char* title,const char* sub) {
  gfx->fillRoundRect(x,y,w,h,18,c); gfx->drawRoundRect(x,y,w,h,18,UI_INK);
  uiPrintCenter(title,y+18,UI_INK,2);
  uiPrintCenter(sub,y+52,UI_INK,1);
}

static void arcStartTetris();
static void arcStartSnake();
static void arcStartMine(uint8_t stage);

void arcGameMenuTap(int16_t x,int16_t y) {
  lastInteract=millis();
  if (y<70 || y>388) { arcMenuOpen=false; gameMenuOpen=true; return; }
  if (x>=46 && x<=222 && y>=112 && y<=226) { arcStartTetris(); return; }
  if (x>=244 && x<=420 && y>=112 && y<=226) { arcStartSnake(); return; }
  if (x>=72 && x<=394 && y>=246 && y<=356) { arcStartMine(1); return; }
}

void arcRenderMenu() {
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xe9,0xed,0xff));
  uiPrintCenter(koOr("포켓 아케이드","POCKET ARCADE"),42,UI_INK,3);
  uiPrintCenter(koOr("클리어할수록 더 어려워져요!","CLEAR = HARDER!"),82,UI_TRACK,1);
  arcCard(46,112,176,114,C565(0x9f,0xd2,0xff),koOr("테트리스","TETRIS"),koOr("줄 클리어 → 속도 UP","LINES → SPEED UP"));
  arcCard(244,112,176,114,C565(0xa9,0xe3,0xa6),koOr("지렁이","SNAKE"),koOr("먹기 → 속도/장애물 UP","FOOD → HARDER"));
  arcCard(72,246,322,110,C565(0xff,0xd2,0x8b),koOr("지뢰찾기","MINESWEEPER"),koOr("클리어 → 판/지뢰 증가","CLEAR → MORE MINES"));
  uiPrintCenter(koOr("위/아래를 누르면 뒤로","TOP/BOTTOM: BACK"),404,UI_TRACK,1);
  gfx->flush();
}

// ------------------------------ TETRIS --------------------------------------
static uint8_t arcTB[16][10];
static uint8_t arcTType=0, arcTRot=0, arcTStage=1;
static int8_t arcTX=3, arcTY=0;
static uint16_t arcTScore=0, arcTStageLines=0, arcTTotalLines=0;
static uint32_t arcTNext=0, arcTBanner=0;
static bool arcTOver=false;

static const uint16_t ARC_SHAPE[7][4] = {
  {0x0F00,0x2222,0x00F0,0x4444}, // I
  {0x6600,0x6600,0x6600,0x6600}, // O
  {0x0E40,0x4C40,0x4E00,0x4640}, // T
  {0x06C0,0x8C40,0x06C0,0x8C40}, // S
  {0x0C60,0x4C80,0x0C60,0x4C80}, // Z
  {0x08E0,0x44C0,0x0E20,0xC880}, // J
  {0x02E0,0xC440,0x0E80,0x88C0}  // L
};

static bool arcTBit(uint8_t t,uint8_t r,int x,int y){ return (ARC_SHAPE[t][r] & (0x8000u >> (y*4+x))) != 0; }
static bool arcTFits(int nx,int ny,uint8_t nr){
  for(int y=0;y<4;y++) for(int x=0;x<4;x++) if(arcTBit(arcTType,nr,x,y)){
    int bx=nx+x, by=ny+y; if(bx<0||bx>=10||by>=16) return false; if(by>=0 && arcTB[by][bx]) return false;
  } return true;
}
static void arcTSpawn(){ arcTType=random(7); arcTRot=random(4); arcTX=3; arcTY=-1; if(!arcTFits(arcTX,arcTY,arcTRot)) arcTOver=true; }
static void arcTResetBoard(){ memset(arcTB,0,sizeof(arcTB)); arcTStageLines=0; arcTSpawn(); }
static uint16_t arcTDelay(){ int d=650-(int)(arcTStage-1)*55; return d<120?120:d; }
static uint8_t arcTGoal(){ uint8_t g=6+(arcTStage-1)*2; return g>16?16:g; }
static void arcTLock(){
  for(int y=0;y<4;y++) for(int x=0;x<4;x++) if(arcTBit(arcTType,arcTRot,x,y)){ int bx=arcTX+x,by=arcTY+y; if(by>=0&&by<16&&bx>=0&&bx<10) arcTB[by][bx]=arcTType+1; }
  uint8_t cleared=0;
  for(int y=15;y>=0;y--){ bool full=true; for(int x=0;x<10;x++) if(!arcTB[y][x]){full=false;break;} if(full){ cleared++; for(int yy=y;yy>0;yy--) memcpy(arcTB[yy],arcTB[yy-1],10); memset(arcTB[0],0,10); y++; } }
  if(cleared){ arcTStageLines+=cleared; arcTTotalLines+=cleared; arcTScore += cleared*cleared*100*arcTStage; sfxPlay(SFX_RPS_WIN); }
  if(arcTStageLines>=arcTGoal()){ arcTStage++; arcTBanner=millis()+1200; sfxPlay(SFX_MEDAL); arcTResetBoard(); }
  else arcTSpawn();
}
static void arcTDrop(){ if(arcTFits(arcTX,arcTY+1,arcTRot)) arcTY++; else arcTLock(); }
static void arcStartTetris(){ arcCloseAll(); arcTetrisOpen=true; arcTStage=1; arcTScore=arcTStageLines=arcTTotalLines=0; arcTOver=false; arcTBanner=0; memset(arcTB,0,sizeof(arcTB)); arcTSpawn(); arcTNext=millis()+arcTDelay(); sfxPlay(SFX_GAME_START); }
void arcTetrisTap(int16_t x,int16_t y){
  lastInteract=millis(); if(y<62){arcTetrisOpen=false;arcMenuOpen=true;return;} if(arcTOver){arcStartTetris();return;}
  if(y<338) return;
  if(x<118){ if(arcTFits(arcTX-1,arcTY,arcTRot)) arcTX--; }
  else if(x<232){ uint8_t nr=(arcTRot+1)&3; if(arcTFits(arcTX,arcTY,nr)) arcTRot=nr; }
  else if(x<346){ if(arcTFits(arcTX+1,arcTY,arcTRot)) arcTX++; }
  else { arcTDrop(); arcTScore+=2; }
  sfxPlay(SFX_TAP);
}
void arcRenderTetris(){
  uint32_t now=millis(); if(!arcTOver && now>=arcTNext){arcTDrop();arcTNext=now+arcTDelay();}
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0x20,0x2d,0x50));
  uiPrintCenter(koOr("포켓 테트리스","POCKET TETRIS"),28,UI_WHITE,2);
  char h[42]; snprintf(h,sizeof(h),koOr("STAGE %u  줄 %u/%u","STAGE %u  LINES %u/%u"),arcTStage,arcTStageLines,arcTGoal()); uiPrintCenter(h,57,UI_WHITE,1);
  const int ox=123,oy=82,cs=22; gfx->fillRect(ox-2,oy-2,224,356,C565(0x0d,0x13,0x25));
  static const uint16_t cc[8]={0,C565(0x55,0xd8,0xff),C565(0xff,0xd0,0x55),C565(0xc0,0x76,0xff),C565(0x6d,0xdd,0x78),C565(0xff,0x72,0x72),C565(0x74,0x8c,0xff),C565(0xff,0x9b,0x55)};
  for(int y=0;y<16;y++) for(int x=0;x<10;x++){ if(arcTB[y][x]) gfx->fillRoundRect(ox+x*cs+1,oy+y*cs+1,cs-2,cs-2,3,cc[arcTB[y][x]]); else gfx->drawRect(ox+x*cs,oy+y*cs,cs,cs,C565(0x28,0x35,0x55)); }
  if(!arcTOver) for(int y=0;y<4;y++) for(int x=0;x<4;x++) if(arcTBit(arcTType,arcTRot,x,y)){int by=arcTY+y;if(by>=0)gfx->fillRoundRect(ox+(arcTX+x)*cs+1,oy+by*cs+1,cs-2,cs-2,3,cc[arcTType+1]);}
  if(arcTOver){gfx->fillRoundRect(82,184,302,90,18,C565(0x8d,0x2e,0x3d));uiPrintCenter(koOr("게임 오버","GAME OVER"),202,UI_WHITE,3);uiPrintCenter(koOr("아무 곳이나 눌러 재시작","TAP TO RESTART"),244,UI_WHITE,1);}
  if(arcTBanner>now){uiPrintCenter(koOr("스테이지 클리어! 난이도 UP","STAGE CLEAR! HARDER"),300,UI_BAR_WARN,2);}
  gfx->fillRoundRect(22,390,94,48,12,C565(0x5c,0x72,0xa8)); uiPrintCenter("<",400,UI_WHITE,3);
  gfx->fillRoundRect(126,390,94,48,12,C565(0x7e,0x62,0xb8)); uiPrintCenter(koOr("회전","ROT"),402,UI_WHITE,1);
  gfx->fillRoundRect(230,390,94,48,12,C565(0x5c,0x72,0xa8)); uiPrintCenter(">",400,UI_WHITE,3);
  gfx->fillRoundRect(334,390,110,48,12,C565(0x4f,0xa8,0x73)); uiPrintCenter(koOr("내리기","DROP"),402,UI_WHITE,1); gfx->flush();
}

// ------------------------------- SNAKE --------------------------------------
static int8_t arcSX[96],arcSY[96],arcSFoodX=10,arcSFoodY=10,arcSDX=1,arcSDY=0;
static int8_t arcSRX[12],arcSRY[12];
static uint8_t arcSLen=4,arcSStage=1,arcSEaten=0,arcSRocks=0;
static uint16_t arcSScore=0; static uint32_t arcSNext=0,arcSBanner=0; static bool arcSOver=false;
static uint16_t arcSSpeed(){int d=280-(arcSStage-1)*24;return d<82?82:d;}
static uint8_t arcSGoal(){uint8_t g=5+(arcSStage-1)*2;return g>15?15:g;}
static bool arcSOnSnake(int x,int y){for(int i=0;i<arcSLen;i++)if(arcSX[i]==x&&arcSY[i]==y)return true;return false;}
static bool arcSOnRock(int x,int y){for(int i=0;i<arcSRocks;i++)if(arcSRX[i]==x&&arcSRY[i]==y)return true;return false;}
static void arcSFood(){do{arcSFoodX=random(14);arcSFoodY=random(14);}while(arcSOnSnake(arcSFoodX,arcSFoodY)||arcSOnRock(arcSFoodX,arcSFoodY));}
static void arcSResetStage(){
  arcSLen=4;arcSDX=1;arcSDY=0; for(int i=0;i<4;i++){arcSX[i]=6-i;arcSY[i]=7;} arcSEaten=0;
  arcSRocks=arcSStage>1?arcSStage-1:0;if(arcSRocks>10)arcSRocks=10;
  for(int i=0;i<arcSRocks;i++){do{arcSRX[i]=random(14);arcSRY[i]=random(14);}while(arcSOnSnake(arcSRX[i],arcSRY[i])||(arcSRX[i]==6&&arcSRY[i]==7));}
  arcSFood(); arcSNext=millis()+arcSSpeed();
}
static void arcStartSnake(){arcCloseAll();arcSnakeOpen=true;arcSStage=1;arcSScore=0;arcSOver=false;arcSBanner=0;arcSResetStage();sfxPlay(SFX_GAME_START);}
static void arcSMove(){
  int nx=arcSX[0]+arcSDX,ny=arcSY[0]+arcSDY; if(nx<0||nx>=14||ny<0||ny>=14||arcSOnSnake(nx,ny)||arcSOnRock(nx,ny)){arcSOver=true;sfxPlay(SFX_GAME_OVER);return;}
  bool eat=(nx==arcSFoodX&&ny==arcSFoodY); if(eat&&arcSLen<95)arcSLen++;
  for(int i=arcSLen-1;i>0;i--){arcSX[i]=arcSX[i-1];arcSY[i]=arcSY[i-1];}arcSX[0]=nx;arcSY[0]=ny;
  if(eat){arcSEaten++;arcSScore+=10*arcSStage;sfxPlay(SFX_MOLE_HIT2);if(arcSEaten>=arcSGoal()){arcSStage++;arcSBanner=millis()+1100;sfxPlay(SFX_MEDAL);arcSResetStage();}else arcSFood();}
}
void arcSnakeTap(int16_t x,int16_t y){
  lastInteract=millis();if(y<62){arcSnakeOpen=false;arcMenuOpen=true;return;}if(arcSOver){arcStartSnake();return;}
  int dx=x-CX,dy=y-CY;if(abs(dx)>abs(dy)){if(dx>0&&arcSDX!=-1){arcSDX=1;arcSDY=0;}else if(dx<0&&arcSDX!=1){arcSDX=-1;arcSDY=0;}}else{if(dy>0&&arcSDY!=-1){arcSDX=0;arcSDY=1;}else if(dy<0&&arcSDY!=1){arcSDX=0;arcSDY=-1;}}sfxPlay(SFX_TAP);
}
void arcRenderSnake(){
  uint32_t now=millis();if(!arcSOver&&now>=arcSNext){arcSMove();arcSNext=now+arcSSpeed();}
  gfx->fillScreen(RGB565_BLACK);gfx->fillCircle(CX,CY,231,C565(0xd9,0xf1,0xd2));uiPrintCenter(koOr("아보 지렁이","SNAKE"),28,UI_INK,2);
  char h[42];snprintf(h,sizeof(h),koOr("STAGE %u  먹이 %u/%u","STAGE %u  FOOD %u/%u"),arcSStage,arcSEaten,arcSGoal());uiPrintCenter(h,57,UI_INK,1);
  const int cs=23,ox=72,oy=92;gfx->fillRoundRect(ox-6,oy-6,334,334,14,C565(0x76,0xb7,0x68));
  for(int i=0;i<arcSRocks;i++){int px=ox+arcSRX[i]*cs+cs/2,py=oy+arcSRY[i]*cs+cs/2;gfx->fillRoundRect(px-8,py-8,16,16,4,C565(0x59,0x55,0x55));}
  int fx=ox+arcSFoodX*cs+cs/2,fy=oy+arcSFoodY*cs+cs/2;gfx->fillCircle(fx,fy,8,C565(0xf0,0x42,0x55));gfx->fillRect(fx-1,fy-12,3,5,C565(0x42,0x7d,0x38));
  for(int i=arcSLen-1;i>=0;i--){int px=ox+arcSX[i]*cs+cs/2,py=oy+arcSY[i]*cs+cs/2;uint16_t c=i?C565(0x91,0x55,0xb8):C565(0x6a,0x35,0x95);gfx->fillCircle(px,py,i?8:10,c);if(i==0){gfx->fillCircle(px-3,py-2,2,UI_WHITE);gfx->fillCircle(px+3,py-2,2,UI_WHITE);}}
  if(arcSOver){gfx->fillRoundRect(92,190,282,84,18,C565(0x92,0x38,0x4a));uiPrintCenter(koOr("쾅! 게임 오버","CRASH! GAME OVER"),208,UI_WHITE,2);uiPrintCenter(koOr("눌러서 재시작","TAP TO RESTART"),244,UI_WHITE,1);}
  if(arcSBanner>now)uiPrintCenter(koOr("클리어! 속도+장애물 UP","CLEAR! HARDER"),390,UI_BAR_WARN,2);else uiPrintCenter(koOr("가고 싶은 방향을 터치","TAP DIRECTION"),400,UI_INK,1);gfx->flush();
}

// ---------------------------- MINESWEEPER -----------------------------------
static bool arcMMine[81],arcMOpen[81],arcMFlag[81];
static uint8_t arcMStage=1,arcMN=6,arcMMines=6;static bool arcMGenerated=false,arcMFlagMode=false;static uint32_t arcMClearUntil=0;static bool arcMDead=false;
static uint8_t arcMCount(int id){int x=id%arcMN,y=id/arcMN,c=0;for(int yy=y-1;yy<=y+1;yy++)for(int xx=x-1;xx<=x+1;xx++)if(xx>=0&&yy>=0&&xx<arcMN&&yy<arcMN&&arcMMine[yy*arcMN+xx])c++;return c;}
static void arcMSetupStage(uint8_t st){arcMStage=st;arcMN=5+st;if(arcMN>9)arcMN=9;arcMMines=4+st*3;if(arcMMines>20)arcMMines=20;if(arcMMines>arcMN*arcMN-9)arcMMines=arcMN*arcMN-9;memset(arcMMine,0,sizeof(arcMMine));memset(arcMOpen,0,sizeof(arcMOpen));memset(arcMFlag,0,sizeof(arcMFlag));arcMGenerated=false;arcMFlagMode=false;arcMDead=false;arcMClearUntil=0;}
static void arcStartMine(uint8_t st){arcCloseAll();arcMineOpen=true;arcMSetupStage(st);sfxPlay(SFX_GAME_START);}
static void arcMGenerate(int safe){int sx=safe%arcMN,sy=safe/arcMN,put=0;while(put<arcMMines){int id=random(arcMN*arcMN),x=id%arcMN,y=id/arcMN;if(arcMMine[id]||abs(x-sx)<=1&&abs(y-sy)<=1)continue;arcMMine[id]=true;put++;}arcMGenerated=true;}
static void arcMFlood(int start){int q[81],qh=0,qt=0;q[qt++]=start;while(qh<qt){int id=q[qh++];if(arcMOpen[id]||arcMFlag[id])continue;arcMOpen[id]=true;if(arcMCount(id))continue;int x=id%arcMN,y=id/arcMN;for(int yy=y-1;yy<=y+1;yy++)for(int xx=x-1;xx<=x+1;xx++)if(xx>=0&&yy>=0&&xx<arcMN&&yy<arcMN){int ni=yy*arcMN+xx;if(!arcMOpen[ni]&&!arcMMine[ni]&&qt<81)q[qt++]=ni;}}}
static bool arcMCleared(){int open=0;for(int i=0;i<arcMN*arcMN;i++)if(arcMOpen[i])open++;return open==arcMN*arcMN-arcMMines;}
void arcMineTap(int16_t x,int16_t y){
  lastInteract=millis();if(y<60){arcMineOpen=false;arcMenuOpen=true;return;}if(arcMDead){arcMSetupStage(arcMStage);return;}if(arcMClearUntil)return;
  if(y>=66&&y<=104&&x>=150&&x<=316){arcMFlagMode=!arcMFlagMode;sfxPlay(SFX_TAP);return;}
  int cs=34,gw=arcMN*cs,ox=CX-gw/2,oy=116;if(x<ox||x>=ox+gw||y<oy||y>=oy+gw)return;int cx=(x-ox)/cs,cy=(y-oy)/cs,id=cy*arcMN+cx;
  if(arcMFlagMode){if(!arcMOpen[id])arcMFlag[id]=!arcMFlag[id];sfxPlay(SFX_TAP);return;}if(arcMFlag[id])return;if(!arcMGenerated)arcMGenerate(id);
  if(arcMMine[id]){arcMDead=true;for(int i=0;i<arcMN*arcMN;i++)if(arcMMine[i])arcMOpen[i]=true;sfxPlay(SFX_GAME_OVER);return;}arcMFlood(id);sfxPlay(SFX_GAME_TICK);if(arcMCleared()){arcMClearUntil=millis()+1300;sfxPlay(SFX_MEDAL);}
}
void arcRenderMine(){
  uint32_t now=millis();if(arcMClearUntil&&now>=arcMClearUntil){arcMSetupStage(arcMStage+1);sfxPlay(SFX_GAME_START);}
  gfx->fillScreen(RGB565_BLACK);gfx->fillCircle(CX,CY,231,C565(0xf5,0xe6,0xc8));uiPrintCenter(koOr("찌리리공 지뢰찾기","MINESWEEPER"),24,UI_INK,2);
  char h[36];snprintf(h,sizeof(h),koOr("STAGE %u  %ux%u  지뢰 %u","STAGE %u  %ux%u  MINES %u"),arcMStage,arcMN,arcMN,arcMMines);uiPrintCenter(h,50,UI_INK,1);
  gfx->fillRoundRect(150,66,166,38,12,arcMFlagMode?C565(0xff,0x9a,0x64):C565(0x83,0xb7,0xe6));uiPrintCenter(arcMFlagMode?koOr("🚩 깃발 모드","FLAG MODE"):koOr("칸 열기 모드","OPEN MODE"),76,UI_INK,1);
  int cs=34,gw=arcMN*cs,ox=CX-gw/2,oy=116;static const uint16_t nc[9]={UI_TRACK,C565(0x28,0x5d,0xc0),C565(0x2d,0x8d,0x54),C565(0xc2,0x3e,0x3e),C565(0x6f,0x43,0xa3),C565(0xa0,0x54,0x24),C565(0x2a,0x82,0x86),UI_INK,UI_INK};
  for(int y=0;y<arcMN;y++)for(int x=0;x<arcMN;x++){int id=y*arcMN+x,px=ox+x*cs,py=oy+y*cs;if(!arcMOpen[id]){gfx->fillRoundRect(px+1,py+1,cs-2,cs-2,5,C565(0xc8,0xae,0x79));if(arcMFlag[id]){gfx->fillTriangle(px+9,py+8,px+24,py+13,px+9,py+18,C565(0xe7,0x45,0x45));gfx->drawLine(px+9,py+8,px+9,py+26,UI_INK);}}else if(arcMMine[id]){gfx->fillRoundRect(px+1,py+1,cs-2,cs-2,5,C565(0xf0,0x7b,0x62));gfx->fillCircle(px+17,py+17,10,C565(0xd9,0x31,0x31));gfx->fillRect(px+14,py+11,6,12,UI_WHITE);}else{gfx->fillRect(px+1,py+1,cs-2,cs-2,C565(0xf8,0xf0,0xdc));uint8_t c=arcMCount(id);if(c){char b[2]={(char)('0'+c),0};gfx->setTextColor(nc[c]);gfx->setTextSize(2);gfx->setCursor(px+11,py+9);gfx->print(b);}}}
  if(arcMDead){uiPrintCenter(koOr("펑! 눌러서 재도전","BOOM! TAP TO RETRY"),430,UI_BAR_WARN,2);}else if(arcMClearUntil){uiPrintCenter(koOr("클리어! 다음 판은 더 어려워요","CLEAR! NEXT IS HARDER"),430,UI_BAR_OK,2);}else uiPrintCenter(koOr("모드 버튼으로 열기/깃발 전환","BUTTON: OPEN / FLAG"),430,UI_INK,1);gfx->flush();
}

'''

marker = '// ---------- minijuego: toques con la pokeball ----------\n'
if marker not in src:
    raise SystemExit('arcade insertion marker missing')
src = src.replace(marker, arcade + marker, 1)
ino.write_text(src, encoding='utf-8')

# Recompile final combo firmware.
fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_combo')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file(): raise SystemExit('v2.2 firmware missing')

# Installer copy.
p=Path('site/index.html'); html=p.read_text(encoding='utf-8')
repls=[
 ('✨ COMBO · USER FIX 2.1','🎮 COMBO · ARCADE 2.2'),
 ('✨ 천지인 한방팩 v2.1 설치','🎮 천지인 한방팩 v2.2 설치'),
 ('manifest-combo.json?v=userfix21','manifest-combo.json?v=arcade22'),
 ('<b>2.1 USER FIX:</b>','<b>2.2 ARCADE:</b>'),
]
for a,b in repls:
    if a not in html: raise SystemExit('page marker missing: '+a)
    html=html.replace(a,b,1)
anchor='<p class="ok">✓ v2.1: 성공 타격음 강화 · 시계 포켓몬 배경박스 제거 · 151퀴즈 포켓몬 확대/매번 랜덤</p>'
extra=anchor+'\n    <p class="ok">✓ v2.2: 테트리스 · 아보 지렁이 · 찌리리공 지뢰찾기 추가</p>\n    <p class="ok">✓ 3종 모두 스테이지 클리어마다 속도/목표/장애물/지뢰 수가 단계적으로 증가</p>'
if anchor not in html: raise SystemExit('v2.1 feature anchor missing')
html=html.replace(anchor,extra,1)
p.write_text(html,encoding='utf-8')
print('v2.2 arcade patch + firmware compile complete')
