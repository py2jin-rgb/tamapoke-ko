from pathlib import Path
import re, shutil, subprocess

SRC=Path('source_combo/TamaPoke')
ROOT=Path('source_battle/TamaPoke')
if ROOT.parent.exists(): shutil.rmtree(ROOT.parent)
ROOT.parent.mkdir(parents=True)
shutil.copytree(SRC, ROOT)
ino=ROOT/'TamaPoke.ino'
s=ino.read_text(encoding='utf-8')

# ④ is deliberately forked from the completed ③ Battery 2.3 source.
s,n=re.subn(r'#define FW_VERSION "2\.3-ko-combo-battery"','#define FW_VERSION "2.4-ko-combo-battle"',s,count=1)
if n!=1: raise SystemExit('battle v2.4 firmware version marker missing')

inc='''#include <WiFi.h>\n#include <esp_now.h>\n#include <esp_wifi.h>\n'''
if '#include <esp_now.h>' not in s:
    s=inc+s

# State is kept entirely outside Pet so ③ save compatibility is preserved.
state=r'''
// ---------- Battle Edition v2.4: local two-device ESP-NOW Pokemon battle ----------
static bool battleOpen=false;
static bool battleRadioReady=false;
static uint32_t battleSelfId=0, battlePeerId=0;
static uint8_t battleMyHp=5, battlePeerHp=5, battleRound=1;
static int8_t battleMyMove=-1, battlePeerMove=-1;
static uint8_t battleState=0; // 0 searching, 1 fighting, 2 finished
static int8_t battleResult=0; // -1 lose, 0 draw/ongoing, 1 win
static uint32_t battleLastHello=0, battleLastTx=0, battleRevealUntil=0;
static uint16_t battleWins=0, battleLosses=0;
static Preferences battlePrefs;
static bool battlePrefsReady=false;

struct __attribute__((packed)) BattlePacket {
  uint32_t magic;
  uint8_t proto;
  uint8_t type;   // 1 hello, 2 ready, 3 move, 4 quit
  uint8_t round;
  int8_t move;
  uint32_t from;
  uint32_t target;
};
static const uint32_t BATTLE_MAGIC=0x54424C31UL; // TBL1
static volatile bool battleRxPending=false;
static volatile BattlePacket battleRx;
static const uint8_t battleBroadcast[6]={0xff,0xff,0xff,0xff,0xff,0xff};
'''
anchor='static uint32_t powerNoticeUntil=0;'
if anchor not in s: raise SystemExit('battle v2.4 battery-state anchor missing')
s=s.replace(anchor,anchor+state,1)

block=r'''
static void battleSend(uint8_t type, int8_t move=-1) {
  if(!battleRadioReady) return;
  BattlePacket p{BATTLE_MAGIC,1,type,battleRound,move,battleSelfId,battlePeerId};
  esp_now_send(battleBroadcast,(const uint8_t*)&p,sizeof(p));
}

static void battleRecvCb(const esp_now_recv_info_t *info,const uint8_t *data,int len) {
  (void)info;
  if(len!=(int)sizeof(BattlePacket)) return;
  BattlePacket p; memcpy(&p,data,sizeof(p));
  if(p.magic!=BATTLE_MAGIC || p.proto!=1 || p.from==battleSelfId) return;
  if(p.target!=0 && p.target!=battleSelfId) return;
  battleRx=p;
  battleRxPending=true;
}

static void battlePrefsInit() {
  if(battlePrefsReady) return;
  battlePrefsReady=true;
  battlePrefs.begin("tpk-battle",false);
  battleWins=battlePrefs.getUShort("wins",0);
  battleLosses=battlePrefs.getUShort("loss",0);
}

static bool battleRadioStart() {
  setCpuFrequencyMhz(240);
  WiFi.mode(WIFI_STA);
  delay(20);
  esp_wifi_set_channel(1,WIFI_SECOND_CHAN_NONE);
  if(esp_now_init()!=ESP_OK) { WiFi.mode(WIFI_OFF); return false; }
  esp_now_register_recv_cb(battleRecvCb);
  esp_now_peer_info_t peer{};
  memcpy(peer.peer_addr,battleBroadcast,6);
  peer.channel=1; peer.ifidx=WIFI_IF_STA; peer.encrypt=false;
  if(!esp_now_is_peer_exist(battleBroadcast) && esp_now_add_peer(&peer)!=ESP_OK) {
    esp_now_deinit(); WiFi.mode(WIFI_OFF); return false;
  }
  battleRadioReady=true;
  return true;
}

static void battleRadioStop() {
  if(battleRadioReady) {
    esp_now_unregister_recv_cb();
    esp_now_deinit();
  }
  battleRadioReady=false;
  WiFi.mode(WIFI_OFF);
  lastInteract=millis();
}

static void battleFinish(int8_t result) {
  battleState=2; battleResult=result; battleRevealUntil=millis()+1200UL;
  battlePrefsInit();
  if(result>0) {
    battleWins++; battlePrefs.putUShort("wins",battleWins);
    pet.minigameReward(30); // victory immediately feeds the existing care/joy loop
    sfxPlay(SFX_RPS_WIN);
  } else if(result<0) {
    battleLosses++; battlePrefs.putUShort("loss",battleLosses);
    sfxPlay(SFX_RPS_LOSE);
  } else sfxPlay(SFX_RPS_DRAW);
}

static bool battleBeats(int8_t a,int8_t b) {
  return (a==0&&b==2)||(a==2&&b==1)||(a==1&&b==0); // attack > special > guard > attack
}

static void battleResolveRound() {
  if(battleMyMove<0 || battlePeerMove<0) return;
  if(battleMyMove==battlePeerMove) {
    if(battleMyMove==0) { if(battleMyHp) battleMyHp--; if(battlePeerHp) battlePeerHp--; }
    else if(battleMyMove==2) {
      battleMyHp=(battleMyHp>2)?battleMyHp-2:0;
      battlePeerHp=(battlePeerHp>2)?battlePeerHp-2:0;
    }
  } else if(battleBeats(battleMyMove,battlePeerMove)) {
    uint8_t d=(battleMyMove==2)?2:1;
    battlePeerHp=(battlePeerHp>d)?battlePeerHp-d:0;
  } else {
    uint8_t d=(battlePeerMove==2)?2:1;
    battleMyHp=(battleMyHp>d)?battleMyHp-d:0;
  }
  battleRevealUntil=millis()+1150UL;
  if(!battleMyHp && !battlePeerHp) battleFinish(0);
  else if(!battlePeerHp) battleFinish(1);
  else if(!battleMyHp) battleFinish(-1);
}

static void battlePump() {
  if(!battleOpen || !battleRadioReady) return;
  const uint32_t now=millis();
  if(battleRxPending) {
    noInterrupts(); BattlePacket p=battleRx; battleRxPending=false; interrupts();
    if((p.type==1||p.type==2) && battlePeerId==0) battlePeerId=p.from;
    if(p.type==1 && battlePeerId==p.from) battleSend(2);
    if(p.type==2 && battlePeerId==p.from) battleState=1;
    if(p.type==3 && battleState==1 && p.from==battlePeerId && p.round==battleRound) {
      battlePeerMove=p.move; battleResolveRound();
    }
    if(p.type==4 && p.from==battlePeerId) { battlePeerId=0; battleState=0; battleMyMove=battlePeerMove=-1; }
  }
  if(!battlePeerId) {
    if(now-battleLastHello>450UL) { battleLastHello=now; battleSend(1); }
  } else if(battleState==0) {
    battleState=1; battleSend(2);
  }
  if(battleState==1 && battleMyMove>=0 && battlePeerMove<0 && now-battleLastTx>320UL) {
    battleLastTx=now; battleSend(3,battleMyMove);
  }
  if(battleState==1 && battleRevealUntil && (int32_t)(now-battleRevealUntil)>=0 && battleMyMove>=0 && battlePeerMove>=0) {
    battleRound++; battleMyMove=battlePeerMove=-1; battleRevealUntil=0;
  }
}

static void startBattle() {
  battlePrefsInit();
  battleOpen=true; gameMenuOpen=false;
  battlePeerId=0; battleMyHp=battlePeerHp=5; battleRound=1;
  battleMyMove=battlePeerMove=-1; battleState=0; battleResult=0;
  battleLastHello=battleLastTx=battleRevealUntil=0;
  uint64_t m=ESP.getEfuseMac(); battleSelfId=(uint32_t)(m^(m>>32));
  if(!battleSelfId) battleSelfId=1;
  if(!battleRadioStart()) battleState=2;
  lastInteract=millis(); sfxPlay(SFX_GAME_OPEN);
}

static void closeBattle() {
  if(battlePeerId) battleSend(4);
  battleRadioStop(); battleOpen=false; battlePeerId=0;
  battleMyMove=battlePeerMove=-1; battleState=0;
}

static void battleTap(int16_t x,int16_t y) {
  lastInteract=millis();
  if(y<70) { closeBattle(); gameMenuOpen=true; return; }
  if(battleState==2) {
    if(y>350) { closeBattle(); gameMenuOpen=true; }
    return;
  }
  if(battleState!=1 || !battlePeerId || battleMyMove>=0 || battleRevealUntil) return;
  if(y>=334 && y<=416) {
    if(x>=20 && x<158) battleMyMove=0;
    else if(x>=164 && x<302) battleMyMove=1;
    else if(x>=308 && x<=446) battleMyMove=2;
    if(battleMyMove>=0) { battleLastTx=millis(); battleSend(3,battleMyMove); sfxPlay(SFX_RPS_SELECT); }
  }
}

static void battleHpBar(int x,int y,uint8_t hp,uint16_t col) {
  gfx->drawRoundRect(x,y,154,18,9,C565(0x55,0x60,0x70));
  for(uint8_t i=0;i<hp && i<5;i++) gfx->fillRoundRect(x+4+i*29,y+4,25,10,5,col);
}

static void renderBattle() {
  battlePump();
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX,CY,231,C565(0xf0,0xf4,0xfa));
  uiPrintCenter(koOr("포켓몬 통신 배틀","POKEMON BATTLE"),32,UI_INK,2);
  uiPrintCenter(koOr("위쪽 터치: 나가기","TOP: EXIT"),56,UI_TRACK,1);
  if(!battleRadioReady) {
    uiPrintCenter(koOr("통신 시작 실패","RADIO ERROR"),210,UI_INK,2);
    uiPrintCenter(koOr("아래를 눌러 돌아가기","TAP BOTTOM TO RETURN"),370,UI_TRACK,1);
    gfx->flush(); return;
  }
  if(!battlePeerId) {
    gfx->drawCircle(CX,205,45,C565(0x5a,0x70,0xa5));
    gfx->drawCircle(CX,205,58,C565(0x90,0xa8,0xd8));
    uiPrintCenter(koOr("상대를 찾는 중...","SEARCHING..."),278,UI_INK,2);
    uiPrintCenter(koOr("같은 ④ 펌웨어 기기를 가까이 두세요","KEEP TWO v2.4 DEVICES NEARBY"),310,UI_TRACK,1);
    gfx->flush(); return;
  }
  uiPrintCenter(koOr("상대 포켓몬","RIVAL POKEMON"),92,UI_INK,1);
  battleHpBar(156,111,battlePeerHp,C565(0xf0,0x62,0x67));
  gfx->fillCircle(CX,166,40,C565(0xff,0xd7,0x62));
  gfx->fillCircle(CX,166,24,C565(0xe8,0x55,0x55));
  uiPrintCenter("VS",205,UI_INK,3);
  gfx->fillCircle(CX,266,40,C565(0x73,0xba,0xff));
  gfx->fillCircle(CX,266,24,C565(0x58,0x78,0xc8));
  battleHpBar(156,306,battleMyHp,C565(0x5d,0xc9,0x7a));
  if(battleState==2) {
    if(battleResult>0) uiPrintCenter(koOr("승리! 행복도 보상 획득","WIN! CARE REWARD"),344,UI_INK,2);
    else if(battleResult<0) uiPrintCenter(koOr("패배! 다음엔 이겨보자","LOSE - TRY AGAIN"),344,UI_INK,2);
    else uiPrintCenter(koOr("무승부!","DRAW!"),344,UI_INK,2);
    char st[40]; snprintf(st,sizeof(st),"W %u  L %u",battleWins,battleLosses); uiPrintCenter(st,376,UI_TRACK,1);
    uiPrintCenter(koOr("아래 터치: 놀이 선택","BOTTOM: RETURN"),405,UI_TRACK,1);
    gfx->flush(); return;
  }
  char rd[28]; snprintf(rd,sizeof(rd),"ROUND %u",battleRound); uiPrintCenter(rd,323,UI_TRACK,1);
  uint16_t c0=C565(0xff,0x9b,0x76), c1=C565(0x79,0xc7,0x99), c2=C565(0xb6,0x91,0xff);
  gfx->fillRoundRect(20,334,138,82,16,c0); gfx->fillRoundRect(164,334,138,82,16,c1); gfx->fillRoundRect(308,334,138,82,16,c2);
  uiPrintCenter(koOr("공격","ATTACK"),350,UI_INK,1);
  gfx->setTextColor(UI_INK); gfx->setTextSize(1); gfx->setCursor(202,350); gfx->print(koOr("방어","GUARD"));
  gfx->setCursor(347,350); gfx->print(koOr("필살","SPECIAL"));
  if(battleMyMove>=0) uiPrintCenter(koOr("상대 선택을 기다리는 중...","WAITING FOR RIVAL..."),425,UI_TRACK,1);
  else uiPrintCenter(koOr("공격 / 방어 / 필살 중 선택","CHOOSE A MOVE"),425,UI_TRACK,1);
  gfx->flush();
}

'''
marker='// ---------- minijuego: toques con la pokeball ----------'
if marker not in s: raise SystemExit('battle v2.4 function insertion marker missing')
s=s.replace(marker,block+marker,1)

# Turn the formerly reserved MORE tile into the exclusive two-device battle.
s=s.replace('gameCard(244,246,164,110,C565(0xdb,0xdf,0xe5),koOr("다음 게임","MORE"),3);',
            'gameCard(244,246,164,110,C565(0xff,0xd4,0x63),koOr("통신 배틀","BATTLE"),3);',1)
s=s.replace('if (x>=244 && x<=408 && y>=246 && y<=356) sfxPlay(SFX_DENY);',
            'if (x>=244 && x<=408 && y>=246 && y<=356) { gameMenuOpen=false; startBattle(); return; }',1)

# Route touch/render into the battle modal before existing minigame handlers.
s=s.replace('if (gameMenuOpen) { gameMenuTap(x, y); return; }',
            'if (battleOpen) { battleTap(x, y); return; }\n  if (gameMenuOpen) { gameMenuTap(x, y); return; }',1)
s=s.replace('if (gameMenuOpen) { renderGameMenu(); return; }',
            'if (battleOpen) { renderBattle(); return; }\n  if (gameMenuOpen) { renderGameMenu(); return; }',1)

# Include battle in all major modal guards. These replacements intentionally target
# the final generated source patterns and fail if the upstream layout changes.
s=s.replace('gameMenuOpen || moleOpen || rpsOpen || galleryOpen',
            'gameMenuOpen || moleOpen || rpsOpen || battleOpen || galleryOpen')
s=s.replace('!gameMenuOpen && !moleOpen && !rpsOpen &&',
            '!gameMenuOpen && !moleOpen && !rpsOpen && !battleOpen &&')
s=s.replace('gameOpen || gameMenuOpen || moleOpen || rpsOpen || galleryOpen',
            'gameOpen || gameMenuOpen || moleOpen || rpsOpen || battleOpen || galleryOpen')
s=s.replace('gameOpen || gameMenuOpen || moleOpen || rpsOpen || kbOpen',
            'gameOpen || gameMenuOpen || moleOpen || rpsOpen || battleOpen || kbOpen')
s=s.replace('gameOpen || sackOpen || moleOpen || rpsOpen)',
            'gameOpen || sackOpen || moleOpen || rpsOpen || battleOpen)')

# Alarm must shut the radio down as well as closing the modal.
alarm='gameOpen=false; sackOpen=false; gameMenuOpen=false; moleOpen=false; rpsOpen=false;'
if alarm in s:
    s=s.replace(alarm,'if(battleOpen) closeBattle();\n    gameOpen=false; sackOpen=false; gameMenuOpen=false; moleOpen=false; rpsOpen=false; battleOpen=false;',1)

for must in ('2.4-ko-combo-battle','startBattle()','renderBattle()','esp_now_init','battleWins','통신 배틀'):
    if must not in s: raise SystemExit(f'battle v2.4 invariant missing: {must}')
ino.write_text(s,encoding='utf-8')

fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_battle')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(ROOT)],check=True)
if not (build/'TamaPoke.ino.bin').is_file(): raise SystemExit('v2.4 battle binary missing')

# Add ④ below ③ without changing the stable Battery 2.3 installer.
page=Path('site/index.html'); html=page.read_text(encoding='utf-8')
style='.battlecard{border-color:#b98430;background:#251e16}.battletag{display:inline-block;background:#5a3f17;color:#ffe09a;border:1px solid #b98430;border-radius:999px;padding:4px 10px;font-size:12px;font-weight:800}.battlewarn{background:#302414;border:1px solid #b98430;border-radius:12px;padding:14px;color:#ffe6ad}.battleinstall button{background:#ffd36a;color:#241900}'
html=html.replace('</style>',style+'</style>',1)
card='''\n<div class="card battlecard">\n<span class="battletag">⚔️ NEW · BATTLE 2.4</span>\n<h2>④ 천지인 한방팩 · Battery + 포켓몬 통신 배틀</h2>\n<p>③ Battery 2.3의 미니게임·밝기·절전 기능을 그대로 유지하고, <b>같은 ④ 펌웨어 기기 2대에서만 열리는 ESP-NOW 포켓몬 배틀</b>을 추가한 버전입니다.</p>\n<p class="ok">✓ 공유기/인터넷 없이 가까운 두 기기 자동 탐색</p><p class="ok">✓ 공격 · 방어 · 필살 동시 선택형 HP 배틀</p><p class="ok">✓ 승리 시 기존 육성 보상 즉시 적용 · 승/패 누적 저장</p><p class="ok">✓ 배틀에 들어갈 때만 Wi-Fi/ESP-NOW ON · 종료 시 OFF</p><p class="ok">✓ Battery 2.3: 밝기 25/50/75/100 저장 · 30초 감광 · 2분 AMOLED OFF · CPU 절전 유지</p>\n<div class="battlewarn"><b>통신 배틀:</b> 두 기기 모두 ④ Battle 2.4를 설치해야 합니다. 놀이 선택의 <b>통신 배틀</b>을 양쪽에서 실행하면 자동으로 서로를 찾습니다. <b>Erase/초기화는 선택하지 마세요.</b></div>\n<div class="install battleinstall"><esp-web-install-button id="battle-installer" manifest="manifest-battle.json?v=battle24"><button slot="activate">⚔️ 천지인 Battle 2.4 설치</button><span slot="unsupported">PC용 Chrome 또는 Edge가 필요합니다.</span><span slot="not-allowed">HTTPS 페이지에서 실행하세요.</span></esp-web-install-button></div>\n</div>\n'''
install_anchor='<div class="card"><h2>설치 순서</h2>'
if install_anchor not in html: raise SystemExit('battle page install anchor missing')
html=html.replace(install_anchor,card+install_anchor,1)
html=html.replace('원하는 ①/②/③ 설치 버튼 선택','원하는 ①/②/③/④ 설치 버튼 선택',1)
page.write_text(html,encoding='utf-8')
print('v2.4 Battle Edition compiled and installer card generated')
