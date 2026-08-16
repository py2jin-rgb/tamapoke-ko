from pathlib import Path
import re, sys

root = Path(sys.argv[1])
ino_p=root/'TamaPoke.ino'; ah_p=root/'audio.h'; ac_p=root/'audio.cpp'; ph_p=root/'pet.h'; pc_p=root/'pet.cpp'

def one(s, old, new, label):
    if old not in s:
        raise SystemExit(f'marker not found: {label}')
    return s.replace(old,new,1)

# ---------------- audio.h ----------------
s=ah_p.read_text(encoding='utf-8')
s=one(s,
'''  SFX_ALARM,    // alarma diaria (se repite hasta detener/snooze)\n  SFX_COUNT''',
'''  SFX_ALARM,    // alarma diaria (se repite hasta detener/snooze)\n  // Minigames: original synthesized 8-bit cues (no sampled game audio).\n  SFX_GAME_OPEN,\n  SFX_GAME_START,\n  SFX_MOLE_HIT1,\n  SFX_MOLE_HIT2,\n  SFX_MOLE_HIT3,\n  SFX_MOLE_MISS,\n  SFX_GAME_TICK,\n  SFX_RPS_SELECT,\n  SFX_RPS_WIN,\n  SFX_RPS_LOSE,\n  SFX_RPS_DRAW,\n  SFX_GAME_OVER,\n  SFX_COUNT''','audio enum')
ah_p.write_text(s,encoding='utf-8')

# ---------------- audio.cpp ----------------
s=ac_p.read_text(encoding='utf-8')
s=one(s,
'''static const Note N_ALARM[]  = {{880, 180}, {0, 80}, {1175, 180}, {0, 80}, {880, 180}, {0, 320}};''',
'''static const Note N_ALARM[]  = {{880, 180}, {0, 80}, {1175, 180}, {0, 80}, {880, 180}, {0, 320}};\n\n// Minigame sound pack: short original square-wave cues. Kept intentionally\n// compact so rapid touch games stay responsive and do not fill the audio queue.\nstatic const Note N_GAME_OPEN[]  = {{523, 35}, {659, 35}, {784, 55}};\nstatic const Note N_GAME_START[] = {{523, 55}, {659, 55}, {784, 55}, {1047, 90}};\nstatic const Note N_MOLE_H1[]    = {{740, 28}, {988, 35}};\nstatic const Note N_MOLE_H2[]    = {{831, 28}, {1109, 35}};\nstatic const Note N_MOLE_H3[]    = {{932, 28}, {1245, 38}};\nstatic const Note N_MOLE_MISS[]  = {{220, 55}, {165, 65}};\nstatic const Note N_GAME_TICK[]  = {{1320, 32}};\nstatic const Note N_RPS_SELECT[] = {{620, 28}};\nstatic const Note N_RPS_WIN[]    = {{659, 45}, {831, 45}, {1047, 85}};\nstatic const Note N_RPS_LOSE[]   = {{392, 55}, {330, 55}, {262, 90}};\nstatic const Note N_RPS_DRAW[]   = {{523, 45}, {0, 18}, {523, 60}};\nstatic const Note N_GAME_OVER[]  = {{784, 45}, {659, 45}, {523, 100}};''','audio notes')
s=one(s,
'''  {N_ALARM, 6},\n};''',
'''  {N_ALARM, 6},\n  {N_GAME_OPEN, 3}, {N_GAME_START, 4},\n  {N_MOLE_H1, 2}, {N_MOLE_H2, 2}, {N_MOLE_H3, 2}, {N_MOLE_MISS, 2},\n  {N_GAME_TICK, 1}, {N_RPS_SELECT, 1}, {N_RPS_WIN, 3}, {N_RPS_LOSE, 3},\n  {N_RPS_DRAW, 3}, {N_GAME_OVER, 3},\n};''','audio table')
s=one(s,'gQ = xQueueCreate(8, sizeof(uint8_t));','gQ = xQueueCreate(12, sizeof(uint8_t));','audio queue')
s=one(s,
'''void sfxPlay(uint8_t id) {\n  if (gReady && gOn && gQ) xQueueSend(gQ, &id, 0);  // descarta si la cola esta llena\n}''',
'''void sfxPlay(uint8_t id) {\n  // Alarm owns the speaker while ringing; do not leave game sounds queued behind it.\n  if (gAlarmActive) return;\n  if (gReady && gOn && gQ) xQueueSend(gQ, &id, 0);  // descarta si la cola esta llena\n}''','alarm sound priority')
ac_p.write_text(s,encoding='utf-8')

# ---------------- pet.h ----------------
s=ph_p.read_text(encoding='utf-8')
s=one(s,
'''  uint16_t gameHi = 0;     // record del minijuego (del jugador)\n  uint16_t strHi = 0;      // record de golpes al saco''',
'''  uint16_t gameHi = 0;     // record del minijuego de pelota\n  uint16_t strHi = 0;      // record de golpes al saco\n  uint16_t moleHi = 0;     // record de topos\n  uint16_t rpsHi = 0;      // mejor numero de victorias en una partida de 5 rondas''','pet score fields')
s=one(s,
'''  void playResult(uint8_t score);  // recompensa del minijuego (entrena VEL)\n  uint8_t trainStrength(uint16_t hits);  // saco de entrenamiento (entrena FUE)''',
'''  void playResult(uint8_t score);  // recompensa del minijuego de pelota (entrena VEL)\n  void minigameReward(uint16_t score); // recompensa suave para juegos nuevos\n  uint8_t trainStrength(uint16_t hits);  // saco de entrenamiento (entrena FUE)''','pet reward declaration')
ph_p.write_text(s,encoding='utf-8')

# ---------------- pet.cpp ----------------
s=pc_p.read_text(encoding='utf-8')
insert='''\nvoid Pet::minigameReward(uint16_t score) {\n  if (ceremony != CER_NONE || isEgg() || sleeping) return;\n  uint8_t joyGain = 6 + (score > 28 ? 14 : score / 2);\n  joy = clamp100(joy + joyGain);\n  energy = dropTo(energy, 6 + score / 8, 5);\n  fullness = dropTo(fullness, 3, 5);\n  if (score >= 8) heartUntil = millis() + HEART_MS;\n  addBond(1);\n  registerCare();\n  save();\n}\n\n'''
s=one(s,'// saco de entrenamiento: los golpes entrenan la fuerza. Devuelve la subida.\nuint8_t Pet::trainStrength',insert+'// saco de entrenamiento: los golpes entrenan la fuerza. Devuelve la subida.\nuint8_t Pet::trainStrength','pet reward implementation')
s=one(s,
'''  prefs.putUShort("ghi", gameHi);\n  prefs.putUShort("shi", strHi);''',
'''  prefs.putUShort("ghi", gameHi);\n  prefs.putUShort("shi", strHi);\n  prefs.putUShort("mhi", moleHi);\n  prefs.putUShort("rhi", rpsHi);''','pet save scores')
s=one(s,
'''  gameHi = prefs.getUShort("ghi", 0);\n  strHi = prefs.getUShort("shi", 0);''',
'''  gameHi = prefs.getUShort("ghi", 0);\n  strHi = prefs.getUShort("shi", 0);\n  moleHi = prefs.getUShort("mhi", 0);\n  rpsHi = prefs.getUShort("rhi", 0);''','pet load scores')
pc_p.write_text(s,encoding='utf-8')

# ---------------- TamaPoke.ino ----------------
s=ino_p.read_text(encoding='utf-8')
s=re.sub(r'#define FW_VERSION "[^"]+"', '#define FW_VERSION "1.7-ko-combo-games1"', s, count=1)

s=one(s,
'''PmdMon galleryPmd;  // sprite grande de la vista detalle de la galeria (PMD/TPK2, legal)''',
'''PmdMon galleryPmd;  // sprite grande de la vista detalle de la galeria (PMD/TPK2, legal)\nPmdMon miniOpponentPmd; // rival temporal del minijuego de 가위바위보''','opponent pmd')

s=one(s,
'''bool sackNewHi = false;''',
'''bool sackNewHi = false;\n\n// Hub de minijuegos. Se mantiene separado del juego de pelota para poder\n// seguir agregando juegos sin tocar las coordenadas del UI principal.\nbool gameMenuOpen = false;\nbool moleOpen = false;\nbool rpsOpen = false;\n\nuint16_t moleScore = 0;\nint8_t moleHole = -1;\nuint32_t moleEndAt = 0, moleNextAt = 0, moleResultUntil = 0;\nbool moleNewHi = false;\nuint8_t moleLastSecond = 255;\n\nuint8_t rpsRound = 0, rpsWins = 0, rpsLosses = 0, rpsDraws = 0;\nint8_t rpsPlayer = -1, rpsCpu = -1;\nuint32_t rpsRevealUntil = 0, rpsResultUntil = 0;\nbool rpsNewHi = false;\nint16_t rpsOpponentDex = 0;''','minigame globals')

s=one(s,
'''void openClock();\nbool standbyClockActive();\nvoid renderStandbyClock();''',
'''void openClock();\nbool standbyClockActive();\nvoid renderStandbyClock();\nstatic const char *koOr(const char *ko, const char *other);\nvoid openGameMenu();\nvoid gameMenuTap(int16_t x, int16_t y);\nvoid renderGameMenu();\nvoid startMole();\nvoid moleTap(int16_t x, int16_t y);\nvoid renderMole();\nvoid startRps();\nvoid rpsTap(int16_t x, int16_t y);\nvoid renderRps();''','prototypes')

s=one(s,
'''    gameOpen=false; sackOpen=false; galleryOpen=false; kbOpen=false;\n    clockOpen=false; cardOpen=false; feedMenuUntil=0; confirmUntil=0; choiceKind=0;\n    galleryPmd.unload();''',
'''    gameOpen=false; sackOpen=false; gameMenuOpen=false; moleOpen=false; rpsOpen=false;\n    galleryOpen=false; kbOpen=false; clockOpen=false; cardOpen=false;\n    feedMenuUntil=0; confirmUntil=0; choiceKind=0;\n    galleryPmd.unload(); miniOpponentPmd.unload();''','alarm closes minigames')

s=one(s,
'''        const bool modalOpen = alarmNotice || clockOpen || gameOpen || sackOpen ||\n          galleryOpen || kbOpen || cardOpen || pet.awaitingStarter() || pet.ceremony ||''',
'''        const bool modalOpen = alarmNotice || clockOpen || gameOpen || sackOpen ||\n          gameMenuOpen || moleOpen || rpsOpen || galleryOpen || kbOpen || cardOpen ||\n          pet.awaitingStarter() || pet.ceremony ||''','pwr modal')

s=one(s,
'''  if (now - lastRender >= (uint32_t)((gameOpen || sackOpen) ? 85 : 100)) {''',
'''  if (now - lastRender >= (uint32_t)((gameOpen || sackOpen || moleOpen || rpsOpen) ? 85 : 100)) {''','render rate')

s=one(s,
'''  if (screenOff || alarmRinging() || alarmNotice || clockOpen || gameOpen || sackOpen ||\n      galleryOpen || kbOpen || cardOpen || pet.awaitingStarter() || pet.ceremony ||''',
'''  if (screenOff || alarmRinging() || alarmNotice || clockOpen || gameOpen || sackOpen ||\n      gameMenuOpen || moleOpen || rpsOpen || galleryOpen || kbOpen || cardOpen ||\n      pet.awaitingStarter() || pet.ceremony ||''','standby modal')

s=one(s,
'''  // saco de entrenamiento: cada toque cuenta al instante (aporrear rapido)\n  if (sackOpen) {''',
'''  // 두더지 잡기: 반응속도가 중요한 게임이라 touch-down 즉시 판정.\n  if (moleOpen) {\n    if (pressed && !wasPressed) {\n      lastInteract = millis();\n      moleTap(x, y);\n    }\n    wasPressed = pressed;\n    return;\n  }\n\n  // saco de entrenamiento: cada toque cuenta al instante (aporrear rapido)\n  if (sackOpen) {''','mole immediate touch')

s=one(s,
'''    if (!holdFired && !swallowGesture && !alarmRinging() && !galleryOpen && !cardOpen && !kbOpen && !clockOpen && millis() - tStart > 3000 &&''',
'''    if (!holdFired && !swallowGesture && !alarmRinging() && !galleryOpen && !cardOpen && !kbOpen && !clockOpen &&\n        !gameMenuOpen && !moleOpen && !rpsOpen && millis() - tStart > 3000 &&''','long press block')

s=one(s,
'''  if (gameOpen || galleryOpen || kbOpen || sackOpen || pet.ceremony) return;''',
'''  if (gameOpen || gameMenuOpen || moleOpen || rpsOpen || galleryOpen || kbOpen || sackOpen || pet.ceremony) return;''','vertical swipe block')
s=one(s,
'''  if (gameOpen || kbOpen || clockOpen) return;''',
'''  if (gameOpen || gameMenuOpen || moleOpen || rpsOpen || kbOpen || clockOpen) return;''','horizontal swipe block')

s=one(s,
'''  if (galleryOpen) {\n    galleryTap(x, y);\n    return;\n  }''',
'''  if (gameMenuOpen) { gameMenuTap(x, y); return; }\n  if (rpsOpen) { rpsTap(x, y); return; }\n  if (galleryOpen) {\n    galleryTap(x, y);\n    return;\n  }''','onTap game states')

s=one(s,
'''    } else if (hitBtn == 1) {\n      startGame();''',
'''    } else if (hitBtn == 1) {\n      openGameMenu();''','play opens menu')

s=one(s,
'''  if (galleryOpen) {\n    renderGallery();\n    return;\n  }\n  if (gameOpen) {''',
'''  if (gameMenuOpen) { renderGameMenu(); return; }\n  if (moleOpen) { renderMole(); return; }\n  if (rpsOpen) { renderRps(); return; }\n  if (galleryOpen) {\n    renderGallery();\n    return;\n  }\n  if (gameOpen) {''','render dispatch')

marker='// ---------- minijuego: toques con la pokeball ----------\n'
if marker not in s: raise SystemExit('minigame insertion marker missing')
block=r'''// ---------- 놀이 선택 / 확장형 미니게임 허브 ----------

static void gameCard(int x, int y, int w, int h, uint16_t bg, const char *label, uint8_t icon) {
  gfx->fillRoundRect(x, y, w, h, 18, bg);
  gfx->drawRoundRect(x, y, w, h, 18, UI_INK);
  int cx=x+w/2, cy=y+34;
  if (icon==0) {
    gfx->fillCircle(cx,cy,18,UI_WHITE); gfx->fillRect(cx-18,cy-3,36,6,UI_INK);
    gfx->fillCircle(cx,cy,6,UI_INK); gfx->fillCircle(cx,cy,3,UI_WHITE);
  } else if (icon==1) {
    gfx->fillRoundRect(cx-27,cy+8,54,15,8,C565(0x42,0x2a,0x20));
    gfx->fillCircle(cx,cy,16,C565(0xa8,0x67,0x3f));
    gfx->fillCircle(cx-6,cy-4,2,UI_INK); gfx->fillCircle(cx+6,cy-4,2,UI_INK);
  } else if (icon==2) {
    gfx->fillCircle(cx-18,cy,8,UI_WHITE);
    gfx->drawLine(cx-1,cy+8,cx+10,cy-9,UI_WHITE); gfx->drawLine(cx+10,cy+8,cx-1,cy-9,UI_WHITE);
    gfx->fillRoundRect(cx+17,cy-10,15,20,4,UI_WHITE);
  } else {
    gfx->fillRect(cx-3,cy-16,6,32,UI_TRACK); gfx->fillRect(cx-16,cy-3,32,6,UI_TRACK);
  }
  uiPrintAt(label, x+(w-uiTextWidth(label,2))/2, y+h-30, UI_INK, 2);
}

void openGameMenu() {
  if (pet.isEgg() || pet.sleeping || pet.ceremony) return;
  gameOpen=false; moleOpen=false; rpsOpen=false; sackOpen=false;
  gameMenuOpen=true;
  sfxPlay(SFX_GAME_OPEN);
}

void gameMenuTap(int16_t x, int16_t y) {
  if (y < 82) { gameMenuOpen=false; return; }
  if (x>=58 && x<=222 && y>=112 && y<=222) {
    gameMenuOpen=false; startGame(); sfxPlay(SFX_GAME_START); return;
  }
  if (x>=244 && x<=408 && y>=112 && y<=222) {
    gameMenuOpen=false; startMole(); return;
  }
  if (x>=58 && x<=222 && y>=246 && y<=356) {
    gameMenuOpen=false; startRps(); return;
  }
  if (x>=244 && x<=408 && y>=246 && y<=356) sfxPlay(SFX_DENY);
}

void renderGameMenu() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX,CY,231,C565(0xe8,0xf4,0xf2));
  uiPrintCenter(koOr("놀이 선택","PLAY"), 54, UI_INK, 3);
  uiPrintCenter(koOr("원하는 게임을 골라줘!","Choose a game"), 88, UI_INK, 1);
  gameCard(58,112,164,110,C565(0xff,0xb0,0x67),koOr("공놀이","BALL"),0);
  gameCard(244,112,164,110,C565(0x80,0xd4,0x92),koOr("두더지 잡기","MOLE"),1);
  gameCard(58,246,164,110,C565(0x8f,0xb8,0xff),koOr("가위바위보","RPS"),2);
  gameCard(244,246,164,110,C565(0xdb,0xdf,0xe5),koOr("다음 게임","MORE"),3);
  uiPrintCenter(koOr("위쪽을 누르면 돌아가기","Tap top to close"), 404, UI_TRACK, 1);
  gfx->flush();
}

// ---------- 두더지 잡기 ----------
static const int16_t MOLE_X[9] = {120,233,346, 120,233,346, 120,233,346};
static const int16_t MOLE_Y[9] = {164,164,164, 258,258,258, 352,352,352};

void startMole() {
  moleOpen=true; moleScore=0; moleHole=random(9); moleNewHi=false;
  moleEndAt=millis()+20000UL; moleNextAt=millis()+720; moleResultUntil=0;
  moleLastSecond=255;
  sfxPlay(SFX_GAME_START);
}

void moleTap(int16_t x, int16_t y) {
  if (y < 72) { moleOpen=false; return; }
  if (moleResultUntil) { if (millis()+250 > moleResultUntil) moleOpen=false; return; }
  if (moleHole>=0) {
    int dx=x-MOLE_X[moleHole], dy=y-MOLE_Y[moleHole];
    if (dx*dx + dy*dy < 46*46) {
      moleScore++;
      uint8_t sid=(moleScore%3==1)?SFX_MOLE_HIT1:(moleScore%3==2)?SFX_MOLE_HIT2:SFX_MOLE_HIT3;
      sfxPlay(sid);
      int8_t old=moleHole; do { moleHole=random(9); } while(moleHole==old);
      uint32_t gap=690-(moleScore>20?300:moleScore*14); if(gap<360) gap=360;
      moleNextAt=millis()+gap;
      return;
    }
  }
  sfxPlay(SFX_MOLE_MISS);
}

static void drawMoleGuy(int cx,int cy) {
  gfx->fillCircle(cx,cy-6,20,C565(0xa8,0x67,0x3f));
  gfx->fillRoundRect(cx-22,cy-2,44,23,10,C565(0x8f,0x55,0x36));
  gfx->fillCircle(cx-7,cy-10,3,UI_INK); gfx->fillCircle(cx+7,cy-10,3,UI_INK);
  gfx->fillCircle(cx,cy-2,4,C565(0xf0,0xb0,0x98));
}

void renderMole() {
  uint32_t now=millis();
  if (!moleResultUntil && now>=moleEndAt) {
    moleNewHi=moleScore>pet.moleHi;
    if(moleNewHi) pet.moleHi=moleScore;
    pet.minigameReward(moleScore);
    sfxPlay(moleNewHi && moleScore ? SFX_MEDAL : SFX_GAME_OVER);
    moleResultUntil=now+3500;
  }
  if (moleResultUntil) {
    if(now>=moleResultUntil){moleOpen=false; return;}
    gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xe7,0xf5,0xe5));
    uiPrintCenter(koOr("두더지 잡기","MOLE"),80,UI_INK,3);
    char b[32]; snprintf(b,sizeof(b),koOr("점수 %u","SCORE %u"),moleScore); uiPrintCenter(b,160,UI_INK,4);
    char h[32]; snprintf(h,sizeof(h),koOr("최고 %u","BEST %u"),pet.moleHi); uiPrintCenter(h,222,UI_INK,2);
    if(moleNewHi) uiPrintCenter(koOr("신기록!","NEW RECORD!"),270,UI_BAR_WARN,2);
    uiPrintCenter(koOr("잠시 후 돌아가요","Returning..."),340,UI_TRACK,1);
    gfx->flush(); return;
  }
  if(now>=moleNextAt){ int8_t old=moleHole; do{moleHole=random(9);}while(moleHole==old); moleNextAt=now+620; }
  uint32_t left=moleEndAt-now; uint8_t sec=(left+999)/1000;
  if(sec<=3 && sec!=moleLastSecond){moleLastSecond=sec; sfxPlay(SFX_GAME_TICK);}
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xa9,0xd9,0xf2));
  gfx->fillRect(20,116,426,330,C565(0x73,0xb9,0x74));
  for(int i=0;i<9;i++){
    int cx=MOLE_X[i], cy=MOLE_Y[i];
    gfx->fillRoundRect(cx-40,cy-12,80,25,12,C565(0x50,0x35,0x28));
    gfx->drawRoundRect(cx-40,cy-12,80,25,12,C565(0x31,0x24,0x20));
    if(i==moleHole) drawMoleGuy(cx,cy-7);
  }
  char sc[24],tm[20]; snprintf(sc,sizeof(sc),koOr("점수 %u","SCORE %u"),moleScore); snprintf(tm,sizeof(tm),"%us",sec);
  uiPrintAt(sc,54,52,UI_INK,2); uiPrintAt(tm,346-uiTextWidth(tm,2),52,UI_INK,2);
  char hi[24]; snprintf(hi,sizeof(hi),koOr("최고 %u","BEST %u"),pet.moleHi); uiPrintCenter(hi,84,UI_INK,1);
  gfx->flush();
}

// ---------- 포켓몬 가위바위보 ----------
// 0=rock, 1=scissors, 2=paper
static void drawRpsIcon(int cx,int cy,uint8_t c,uint16_t col) {
  if(c==0){
    gfx->fillCircle(cx-10,cy,10,col); gfx->fillCircle(cx+3,cy-7,10,col); gfx->fillCircle(cx+14,cy+2,9,col);
    gfx->fillRoundRect(cx-14,cy+4,34,18,7,col);
  } else if(c==1){
    gfx->fillCircle(cx-12,cy+12,7,col); gfx->fillCircle(cx+12,cy+12,7,col);
    for(int o=-2;o<=2;o++){gfx->drawLine(cx-9+o,cy+6,cx+15+o,cy-22,col); gfx->drawLine(cx+9+o,cy+6,cx-15+o,cy-22,col);}
  } else {
    gfx->fillRoundRect(cx-18,cy-20,36,42,7,col); for(int i=-12;i<=12;i+=8) gfx->drawLine(cx+i,cy-14,cx+i,cy+10,UI_TRACK);
  }
}

void startRps() {
  rpsOpen=true; rpsRound=rpsWins=rpsLosses=rpsDraws=0; rpsPlayer=rpsCpu=-1;
  rpsRevealUntil=0; rpsResultUntil=0; rpsNewHi=false;
  rpsOpponentDex=1+random(151); if(rpsOpponentDex==pet.speciesId) rpsOpponentDex=(rpsOpponentDex%151)+1;
  miniOpponentPmd.unload(); miniOpponentPmd.load(rpsOpponentDex,false);
  sfxPlay(SFX_GAME_START);
}

void rpsTap(int16_t x,int16_t y) {
  if(y<72){rpsOpen=false; miniOpponentPmd.unload(); return;}
  if(rpsResultUntil || rpsRevealUntil) return;
  if(y<326 || y>418) return;
  int8_t pick=-1;
  if(x>=44 && x<=148) pick=0; else if(x>=181 && x<=285) pick=1; else if(x>=318 && x<=422) pick=2;
  if(pick<0) return;
  rpsPlayer=pick; rpsCpu=random(3); rpsRound++; sfxPlay(SFX_RPS_SELECT);
  bool win=(rpsPlayer==0&&rpsCpu==1)||(rpsPlayer==1&&rpsCpu==2)||(rpsPlayer==2&&rpsCpu==0);
  if(rpsPlayer==rpsCpu){rpsDraws++; sfxPlay(SFX_RPS_DRAW);} else if(win){rpsWins++; sfxPlay(SFX_RPS_WIN);} else {rpsLosses++; sfxPlay(SFX_RPS_LOSE);}
  rpsRevealUntil=millis()+1400;
}

void renderRps() {
  uint32_t now=millis();
  if(rpsRevealUntil && now>=rpsRevealUntil){
    rpsRevealUntil=0; rpsPlayer=rpsCpu=-1;
    if(rpsRound>=5){
      rpsNewHi=rpsWins>pet.rpsHi; if(rpsNewHi) pet.rpsHi=rpsWins;
      pet.minigameReward(rpsWins*4+rpsDraws);
      sfxPlay(rpsNewHi && rpsWins ? SFX_MEDAL : SFX_GAME_OVER);
      rpsResultUntil=now+3800;
    }
  }
  if(rpsResultUntil){
    if(now>=rpsResultUntil){rpsOpen=false; miniOpponentPmd.unload(); return;}
    gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xe9,0xef,0xff));
    uiPrintCenter(koOr("가위바위보 결과","RPS RESULT"),72,UI_INK,3);
    char a[28]; snprintf(a,sizeof(a),koOr("승 %u  무 %u  패 %u","W %u D %u L %u"),rpsWins,rpsDraws,rpsLosses); uiPrintCenter(a,150,UI_INK,2);
    char b[24]; snprintf(b,sizeof(b),koOr("최고 승리 %u/5","BEST %u/5"),pet.rpsHi); uiPrintCenter(b,208,UI_INK,2);
    if(rpsNewHi) uiPrintCenter(koOr("신기록!","NEW RECORD!"),260,UI_BAR_WARN,2);
    gfx->flush(); return;
  }
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xc9,0xe7,0xf7));
  gfx->fillRect(20,270,426,176,C565(0x7c,0xbd,0x7b));
  uiPrintCenter(koOr("가위바위보","ROCK PAPER SCISSORS"),42,UI_INK,3);
  char st[28]; snprintf(st,sizeof(st),koOr("%u라운드  승%u 패%u","ROUND %u  W%u L%u"),rpsRound+1>5?5:rpsRound+1,rpsWins,rpsLosses); uiPrintCenter(st,82,UI_INK,1);
  if(pmd.loaded) drawPmdAct(PMD_IDLE,145,278,now,true,false,3); else {gfx->fillCircle(145,220,34,UI_WHITE); uiPrintAt("?",139,211,UI_INK,3);}
  if(miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd,PMD_IDLE,321,278,now,true,false,3); else {gfx->fillCircle(321,220,34,UI_WHITE); uiPrintAt("?",315,211,UI_INK,3);}
  if(rpsRevealUntil && rpsPlayer>=0){
    drawRpsIcon(145,294,rpsPlayer,UI_WHITE); drawRpsIcon(321,294,rpsCpu,UI_WHITE);
  }
  const int bx[3]={44,181,318}; const uint16_t bc[3]={C565(0xf3,0x8b,0x67),C565(0x77,0xb8,0xf2),C565(0xf2,0xc6,0x62)};
  const char* lab[3]={koOr("바위","ROCK"),koOr("가위","SCISSORS"),koOr("보","PAPER")};
  for(int i=0;i<3;i++){gfx->fillRoundRect(bx[i],330,104,82,16,bc[i]); gfx->drawRoundRect(bx[i],330,104,82,16,UI_INK); drawRpsIcon(bx[i]+52,354,i,UI_INK); uiPrintAt(lab[i],bx[i]+(104-uiTextWidth(lab[i],1))/2,390,UI_INK,1);}
  gfx->flush();
}

'''
s=s.replace(marker, block+marker,1)
ino_p.write_text(s,encoding='utf-8')
print('minigames v1 patch applied to',root)
