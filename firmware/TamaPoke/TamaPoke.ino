#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <WebServer.h>
#include <Update.h>
#include <esp_ota_ops.h>
#include <esp_sntp.h>
#include <mbedtls/sha256.h>
#include <sdkconfig.h>
#if !defined(CONFIG_MBEDTLS_CERTIFICATE_BUNDLE) || !CONFIG_MBEDTLS_CERTIFICATE_BUNDLE
#error "TamaPoke OTA requires the ESP-IDF trusted certificate bundle"
#endif
extern const uint8_t otaCaBundleStart[] asm("_binary_x509_crt_bundle_start");
extern const uint8_t otaCaBundleEnd[] asm("_binary_x509_crt_bundle_end");
static bool otaOpen=false;
// The main loop owns CPU frequency and sleep. Wireless never changes either.
static bool radioBusy();
static bool otaBusy();
static bool otaFlashBusy();
static void serviceWireless(uint32_t now);
static void radioOnAlarm();
static void closeOta();
static void closeBattle();
void serviceCriticalTasks(); // pet/alarm/audio only; must not call wireless/render/input
#include <Preferences.h>
// TamaPoke - tamagotchi pixel art inspirado en la gen 1
// para Waveshare ESP32-S3-Touch-AMOLED-1.75
//
// Librerias (Library Manager o repo de Waveshare):
//   - "GFX Library for Arduino" (moononournation), con soporte CO5300 QSPI
//   - "SensorLib" (Lewis He), driver tactil CST9217
//
// Placa: ESP32S3 Dev Module | Flash 16MB | PSRAM: OPI PSRAM | USB CDC On Boot: Enabled
//
// Los sprites y la tabla de especies se generan con tools/sprites.py (emit).

#include <Arduino.h>
#include <Wire.h>
#include <time.h>
#include "Arduino_GFX_Library.h"
#include "TouchDrvCSTXXX.hpp"
#include "pin_config.h"
#include "species.h"
#include "dex.h"
#include "pet.h"
#include "sdmon.h"
#include "rtcbat.h"
#include "i18n.h"
#include "audio.h"
#include "power_policy.h"
#include <esp_sleep.h>
#include <esp_timer.h>
#include <esp_ota_ops.h>
#include <driver/gpio.h>
#include "alarm.h"
#include "ko_names.h"
#include "ko_font.h"
#include "alarm_font.h"
#include "hangul_full16.h"
#include "hangul_cheonjiin.h"

// Version del firmware. Subir este numero en cada release (y manifest.json para
// el instalador web). Se muestra en la pantalla de ajustes y por serie al arrancar.
#define FW_VERSION "2.8-ko-combo-battery"

#define CX 233  // centro de la pantalla redonda
#define CY 233
#define PET_CY 202  // centro vertical del sprite

Arduino_DataBus *bus = new Arduino_ESP32QSPI(
  LCD_CS, LCD_SCLK, LCD_SDIO0, LCD_SDIO1, LCD_SDIO2, LCD_SDIO3);
Arduino_CO5300 *panel = new Arduino_CO5300(
  bus, LCD_RESET, 0 /*rotation*/, LCD_WIDTH, LCD_HEIGHT, 6, 0, 0, 0);
// Framebuffer completo en PSRAM: dibujamos todo y hacemos flush() (sin parpadeo)
Arduino_Canvas *gfx = new Arduino_Canvas(LCD_WIDTH, LCD_HEIGHT, panel);


// ---------- Korean UI renderer ----------
// Uses compact bitmap glyphs generated into ko_font.h. It does not touch NVS/save data.
static uint32_t koNextCp(const char *&p) {
  const uint8_t *u = (const uint8_t *)p;
  if (!*u) return 0;
  if (*u < 0x80) { uint32_t c = *u; p += 1; return c; }
  if ((*u & 0xE0) == 0xC0) { uint32_t c=((*u&0x1F)<<6)|(u[1]&0x3F); p+=2; return c; }
  if ((*u & 0xF0) == 0xE0) { uint32_t c=((*u&0x0F)<<12)|((u[1]&0x3F)<<6)|(u[2]&0x3F); p+=3; return c; }
  if ((*u & 0xF8) == 0xF0) { uint32_t c=((*u&7)<<18)|((u[1]&0x3F)<<12)|((u[2]&0x3F)<<6)|(u[3]&0x3F); p+=4; return c; }
  p += 1; return '?';
}

static KoFontRef koFontFor(uint8_t requested) {
  if (requested <= 1) return { KO_14_GLYPHS, KO_14_ROWS, KO_14_COUNT, KO_14_H };
  if (requested == 2) return { KO_18_GLYPHS, KO_18_ROWS, KO_18_COUNT, KO_18_H };
  return { KO_22_GLYPHS, KO_22_ROWS, KO_22_COUNT, KO_22_H };
}
static const KoGlyph *koFind(const KoFontRef &f, uint32_t cp) {
  int lo=0, hi=(int)f.count-1;
  while (lo<=hi) { int m=(lo+hi)/2; uint16_t v=f.g[m].cp; if (v==cp) return &f.g[m]; if (v<cp) lo=m+1; else hi=m-1; }
  return nullptr;
}

// Supplemental glyph table for alarm-clock Korean strings. This leaves the
// proven CLEAN v1.2 font bitmaps untouched and only fills previously-missing
// Hangul codepoints using the same NanumBarunGothicBold raster settings.
static const KoGlyph *koFindAlarm(uint8_t requested, uint32_t cp,
                                  const uint32_t *&rows, uint8_t &h) {
  const KoGlyph *g=nullptr; uint16_t count=0;
  if (requested <= 1) {
    g=ALARM_KO_14_GLYPHS; rows=ALARM_KO_14_ROWS; h=ALARM_KO_14_H; count=ALARM_KO_14_COUNT;
  } else if (requested == 2) {
    g=ALARM_KO_18_GLYPHS; rows=ALARM_KO_18_ROWS; h=ALARM_KO_18_H; count=ALARM_KO_18_COUNT;
  } else {
    g=ALARM_KO_22_GLYPHS; rows=ALARM_KO_22_ROWS; h=ALARM_KO_22_H; count=ALARM_KO_22_COUNT;
  }
  int lo=0, hi=(int)count-1;
  while (lo<=hi) {
    int m=(lo+hi)/2; uint16_t v=g[m].cp;
    if (v==cp) return &g[m];
    if (v<cp) lo=m+1; else hi=m-1;
  }
  return nullptr;
}


// Complete modern-Hangul fallback used only when a syllable/Jamo is not in
// the compact UI font tables. The 16x16 bitmap is scaled to the same visual
// cell sizes as CLEAN v1.2 (14/18/22 UI sizes), allowing arbitrary nicknames.
static const uint16_t *hangul16Rows(uint32_t cp) {
  if (cp >= HANGUL16_FIRST && cp < HANGUL16_FIRST + HANGUL16_COUNT) {
    return &HANGUL16_SYLLABLES[(cp - HANGUL16_FIRST) * 16u];
  }
  for (uint16_t i=0; i<HANGUL16_EXTRA_COUNT; i++) {
    if (HANGUL16_EXTRA[i].cp == cp) return HANGUL16_EXTRA[i].row;
  }
  return nullptr;
}
static void hangul16Metrics(uint8_t requested, uint8_t &w, uint8_t &h, uint8_t &adv) {
  if (requested <= 1) { w=15; h=19; adv=14; }
  else if (requested == 2) { w=19; h=24; adv=18; }
  else { w=22; h=28; adv=21; }
}
static bool hangul16Supported(uint32_t cp) { return hangul16Rows(cp) != nullptr; }
static void hangul16DrawGlyph(uint32_t cp, int x, int y, uint16_t color, uint8_t requested) {
  const uint16_t *src=hangul16Rows(cp); if(!src) return;
  uint8_t tw,th,adv; hangul16Metrics(requested,tw,th,adv);
  for(uint8_t yy=0; yy<th; yy++) {
    uint8_t sy=(uint8_t)((uint16_t)yy*16u/th);
    uint16_t bits=src[sy];
    int xx=0;
    while(xx<tw) {
      while(xx<tw) {
        uint8_t sx=(uint8_t)((uint16_t)xx*16u/tw);
        if(bits & (1u << (15-sx))) break;
        xx++;
      }
      int st=xx;
      while(xx<tw) {
        uint8_t sx=(uint8_t)((uint16_t)xx*16u/tw);
        if(!(bits & (1u << (15-sx)))) break;
        xx++;
      }
      if(xx>st) gfx->fillRect(x+st,y+yy,xx-st,1,color);
    }
  }
}

static int koWidth(const char *s, uint8_t requested) {
  KoFontRef f=koFontFor(requested); int w=0; const char *p=s;
  while (*p) {
    uint32_t cp=koNextCp(p);
    const KoGlyph *g=koFind(f,cp);
    if (!g) {
      const uint32_t *er=nullptr; uint8_t eh=0;
      g=koFindAlarm(requested,cp,er,eh);
    }
    if (g) { w+=g->adv; continue; }
    if (hangul16Supported(cp)) {
      uint8_t fw,fh,fa; hangul16Metrics(requested,fw,fh,fa); w+=fa; continue;
    }
    g=koFind(f,'?');
    if (g) w+=g->adv;
  }
  return w;
}
static void koDraw(const char *s, int x, int y, uint16_t color, uint8_t requested) {
  KoFontRef f=koFontFor(requested); const char *p=s; int pen=x;
  while (*p) {
    uint32_t cp=koNextCp(p);
    const KoGlyph *g=koFind(f,cp);
    const uint32_t *rows=f.rows; uint8_t gh=f.h;
    if (!g) g=koFindAlarm(requested,cp,rows,gh);
    if (!g && hangul16Supported(cp)) {
      uint8_t fw,fh,fa; hangul16Metrics(requested,fw,fh,fa);
      hangul16DrawGlyph(cp,pen,y,color,requested); pen+=fa; continue;
    }
    if (!g) { g=koFind(f,'?'); rows=f.rows; gh=f.h; }
    if (!g) continue;
    for (uint8_t yy=0; yy<gh; yy++) {
      uint32_t bits=rows[g->off+yy]; int xx=0;
      while (xx<g->w) {
        while (xx<g->w && !(bits & (1u << (g->w-1-xx)))) xx++;
        int st=xx;
        while (xx<g->w &&  (bits & (1u << (g->w-1-xx)))) xx++;
        if (xx>st) gfx->fillRect(pen+st, y+yy, xx-st, 1, color);
      }
    }
    pen += g->adv;
  }
}
static bool uiHasNonAscii(const char *s) { while (*s) { if ((uint8_t)*s >= 0x80) return true; ++s; } return false; }
static int uiTextWidth(const char *s, uint8_t requested) {
  if (gLang == LANG_KO && (uiHasNonAscii(s) || requested <= 3)) return koWidth(s, requested);
  return (int)strlen(s) * 6 * requested;
}
static void uiPrintAt(const char *s, int x, int y, uint16_t color, uint8_t requested) {
  if (gLang == LANG_KO && (uiHasNonAscii(s) || requested <= 3)) { koDraw(s, x, y, color, requested); return; }
  gfx->setTextColor(color); gfx->setTextSize(requested); gfx->setCursor(x,y); gfx->print(s);
}
static void uiPrintCenter(const char *s, int y, uint16_t color, uint8_t requested) {
  uiPrintAt(s, CX-uiTextWidth(s,requested)/2, y, color, requested);
}
static const char *localizedPokeName(int16_t dex) {
  if (gLang == LANG_KO && dex>=1 && dex<=151) return KO_POKE_NAMES[dex];
  if (dex>=0 && dex<=151) return DEX_TBL[dex].name;
  return "?";
}

TouchDrvCST92xx touch;
Pet pet;

// sprite animado de la SD para la especie actual (si existe el archivo)
SdMon mon;          // sprite B/N (respaldo y minijuego si no hay PMD)
PmdMon pmd;         // sprite PMD multi-accion (pantalla principal)
PmdMon evoPmd;      // forma anterior, solo durante el parpadeo de evolucion
int16_t monFor = -2;
bool monShinyFor = false;

// comportamiento del bicho en pantalla
struct {
  uint8_t mode = 0;     // 0 idle, 1 paseo, 2 gesto one-shot
  uint8_t act = PMD_IDLE;
  uint32_t t0 = 0;      // inicio de la animacion en curso
  uint32_t until = 0;   // fin del estado actual
  float x = 233, targetX = 233;
} beh;
#define PET_GROUND 304  // linea de suelo de la mascota
PmdMon galleryPmd;  // sprite grande de la vista detalle de la galeria (PMD/TPK2, legal)
PmdMon miniOpponentPmd; // rival temporal del minijuego de 가위바위보

// galeria pokedex
bool galleryOpen = false;
bool galleryDirty = false;
int galleryPage = 0;        // 10 paginas de 16
int16_t galleryDetail = 0;  // dex en vista detalle, 0 = rejilla

bool screenOff = false;       // pulsacion corta del boton PWR
bool cardOpen = false;        // ficha del bicho (deslizar vertical)
bool kbOpen = false;          // teclado para renombrar al bicho
char nameBuf[40] = "";
uint8_t nameLen = 0;
HangulComposer kbIme;
bool kbHangulMode = true;
uint8_t cardPage = 0;         // 0 perfil, 1 stats+medallas
bool clockOpen = false;       // ajustes de reloj/alarma (deslizar abajo)
int clockH = 12, clockM = 0;  // hora en edicion
int clockY = 2026, clockMo = 1, clockD = 1; // fecha RTC en edicion
uint8_t clockPage = 0;        // 0 menu, 1 hora/fecha, 2 alarma, 3 alarm-h, 4 alarm-min, 5 fecha
int alarmEditH = 7, alarmEditM = 30;
uint8_t alarmNotice = 0;      // 1 snooze, 2 detenido
uint32_t alarmNoticeUntil = 0;
bool gestureFromStandby = false;
bool manualClockView = false;  // PWR short press toggles game <-> clock view

// escena de bano: espuma sobre el bicho y limpieza al reventar
uint32_t bathUntil = 0;
bool bathPending = false;
struct { int16_t x, y; uint8_t r, ph; } bubbles[14];
uint32_t feedMenuUntil = 0;   // selector de comida abierto hasta este millis

// minijuego "toques": mantener la pokeball en el aire
bool gameOpen = false;
uint32_t gameOverUntil = 0;
float ballX, ballY, ballVX, ballVY, gamePetX;
uint8_t gameScore, gameMisses;
float hitX, hitY;             // ultimo golpe (anillo de impacto)
uint32_t hitTime = 0;
bool gameNewHi = false;

// Ball game only: remember the ball position at touch-down.
// The normal release-based gesture state machine stays unchanged.
float gameTouchBallX = 0, gameTouchBallY = 0;
bool gameTouchBallValid = false;

// saco de entrenamiento (entrena la fuerza)
bool sackOpen = false;
uint32_t sackUntil = 0, sackOverUntil = 0;
uint16_t sackHits = 0;
float sackShake = 0;
uint8_t sackGain = 0;
bool sackNewHi = false;

// Hub de minijuegos. Se mantiene separado del juego de pelota para poder
// seguir agregando juegos sin tocar las coordenadas del UI principal.
bool gameMenuOpen = false;
bool arcMenuOpen = false;
bool arcTetrisOpen = false;
bool arcSnakeOpen = false;
bool arcMineOpen = false;
uint8_t gameMenuPage = 0;
bool moleOpen = false;
bool rpsOpen = false;
bool quizOpen = false;
bool catchOpen = false;

uint16_t moleScore = 0;
int8_t moleHole = -1;
uint8_t moleStage = 1, moleStageHits = 0;
uint32_t moleNextAt = 0, moleResultUntil = 0, moleStageBannerUntil = 0;
bool moleNewHi = false;

uint8_t rpsRound = 0, rpsWins = 0, rpsLosses = 0, rpsDraws = 0;
int8_t rpsPlayer = -1, rpsCpu = -1;
uint32_t rpsRevealUntil = 0, rpsResultUntil = 0;
bool rpsNewHi = false;
int16_t rpsOpponentDex = 0;

uint16_t quizLevel = 1;
uint16_t quizTargetDex = 4;
uint16_t quizChoices[3] = {4, 7, 1};
uint8_t quizCorrectSlot = 0;
uint32_t quizCountdownEnd = 0;
uint32_t quizFeedbackUntil = 0;
bool quizWasCorrect = false;
bool quizCompleted = false;

// Monster Ball Catch: move the current pet along the bottom and collect items.
int16_t catchPetX = CX, catchItemX = CX, catchItemY = 86;
uint8_t catchItemType = 0, catchLives = 3;
uint16_t catchScore = 0;
uint32_t catchEndAt = 0, catchResultUntil = 0, catchLastStep = 0;
bool catchNewHi = false;

// las 9 especies con sprite propio en flash (respaldo sin SD): dex -> indice
int flashIdxForDex(int16_t dex) {
  static const int8_t IDX[10] = { -1, 3, 4, 5, 0, 1, 2, 6, 7, 8 };
  return (dex >= 1 && dex <= 9) ? IDX[dex] : -1;
}


static const uint16_t INK_K = 0x18C4;  // spriteColor('k')

// botones de icono siguiendo el arco inferior de la pantalla redonda
// (los exteriores van mas altos para no salirse del circulo)
struct Btn {
  int16_t cx, cy;
  const char *const *icon;
};
Btn buttons[4] = {
  { 140, 390, SPR_ICON_FOOD },   // comer
  { 202, 404, SPR_ICON_PLAY },   // jugar
  { 264, 404, SPR_ICON_LIGHT },  // luz
  { 326, 390, SPR_ICON_CLEAN },  // bano
};
#define BTN_HALF 26  // boton de 52x52
#define BTN_HIT 36   // radio tactil (un poco mas generoso)

// grietas del huevo (pixeles 'k' sobre el sprite)
static const uint8_t CRACK1[][2] = { {15,8},{16,9},{15,10} };
static const uint8_t CRACK2[][2] = { {11,13},{12,14},{11,15},{20,12},{19,13},{20,14} };
// estrellas del modo noche
static const uint16_t STARS[][2] = { {120,140},{330,120},{370,210},{95,230},{280,90},{160,95} };

bool wasPressed = false;
// eleccion de inicial (primera partida): Bulbasaur / Charmander / Squirtle, 3 filas
static const int16_t STARTER_DEX[3] = { 1, 4, 7 };
#define STARTER_ROW_Y 110
#define STARTER_ROW_H 70
#define STARTER_ROW_GAP 8
// boton-CTA de evolucion (centrado, mitad de pantalla)
#define EVO_BTN_W 256
#define EVO_BTN_H 64
#define EVO_BTN_X (CX - EVO_BTN_W / 2)
#define EVO_BTN_Y 172
// boton-CTA de despedida (mas ancho: lleva el nombre + frase)
#define FAR_BTN_W 408
#define FAR_BTN_H 58
#define FAR_BTN_X (CX - FAR_BTN_W / 2)
#define FAR_BTN_Y 176
// el CST9217 avisa por el pin INT cuando hay datos tactiles; lo usamos para no
// leer el bus I2C mientras el chip esta dormido (esa lectura se colgaba ~1s)
volatile bool gTouchIrq = false;
void IRAM_ATTR touchIsr() { gTouchIrq = true; }
uint32_t lastRender = 0;
// proteccion del AMOLED: atenuado por inactividad
uint32_t lastInteract = 0;
uint8_t dimStage = 0;

// ---------- Battery Edition v2.3 (combo only) ----------
static Preferences powerPrefs;
static bool powerPrefsReady=false;
static uint8_t powerBrightnessPct=50;  // 25/50/75/100, persisted in NVS
static bool powerAlwaysOnClock=false;
static bool powerLightSleepEnabled=true;
static bool powerPanelSleeping=false;
static bool powerRestoreBrightness=false;
static bool powerForceRender=true;
static bool powerWakeReady=false;
static uint8_t powerAppliedBrightness=255;
static uint32_t powerSleepCount=0, powerSleepErrors=0, powerClockErrors=0;
static uint32_t powerSleepRetryAt=0;
static uint64_t powerSleepUs=0;
static esp_err_t powerLastSleepError=ESP_OK;
static TamaPower::Plan powerPlan{0,127,240,false,false};
static uint32_t powerNoticeUntil=0;
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
// The ESP-NOW callback runs on the Wi-Fi task, possibly on the other core.
// A task-safe bounded queue replaces noInterrupts(), which was only local-core.
static portMUX_TYPE battleRxMux=portMUX_INITIALIZER_UNLOCKED;
static BattlePacket battleRxQueue[4];
static uint8_t battleRxHead=0, battleRxCount=0;
static bool battleAcceptRx=false;
static uint32_t battleStartedAt=0, battleProgressAt=0, battleFinishedAt=0;
static const char *battleStatus="";
static const uint32_t BATTLE_SEARCH_MS=45000UL;
static const uint32_t BATTLE_IDLE_MS=60000UL;
static const uint32_t BATTLE_RESULT_MS=30000UL;
static const uint32_t BATTLE_RESULT_RADIO_MS=1800UL;
static const uint8_t battleBroadcast[6]={0xff,0xff,0xff,0xff,0xff,0xff};


static uint8_t powerRawFromPct(uint8_t pct) {
  if(pct>100) pct=100;
  return (uint8_t)((uint16_t)pct*255U/100U);
}

static void powerInitOnce() {
  if(powerPrefsReady) return;
  powerPrefsReady=true;
  powerPrefs.begin("tpk-power",false);
  uint8_t v=powerPrefs.getUChar("bright",50);
  if(v!=25 && v!=50 && v!=75 && v!=100) v=50;
  powerBrightnessPct=v;
  powerAlwaysOnClock=powerPrefs.getBool("aod",false);
  powerLightSleepEnabled=powerPrefs.getBool("sleep",true);
}

static void powerCycleBrightness() {
  powerInitOnce();
  if(powerBrightnessPct==25) powerBrightnessPct=50;
  else if(powerBrightnessPct==50) powerBrightnessPct=75;
  else if(powerBrightnessPct==75) powerBrightnessPct=100;
  else powerBrightnessPct=25;
  powerPrefs.putUChar("bright",powerBrightnessPct);
  lastInteract=millis();
  powerNoticeUntil=millis()+1800UL;
  sfxPlay(SFX_TAP);
}
        // 0 despierto, 1 atenuado (90s), 2 casi apagado (5min)
bool swallowGesture = false; // el toque que despierta no acciona nada
uint32_t holdStart = 0;     // pulsacion larga sobre el bicho
uint32_t confirmUntil = 0;  // dialogo "soltar?" activo hasta este millis
uint8_t choiceKind = 0;     // dialogo de decision: 0 ninguno, 1 evolucion, 2 despedida
uint32_t choiceUntil = 0;   // se cierra solo a este millis
int16_t tX0, tY0, tXl, tYl; // gesto en curso (inicio y ultima posicion)
uint32_t tStart = 0;
bool holdFired = false;

void openClock();
bool standbyClockActive();
void renderStandbyClock();
static const char *koOr(const char *ko, const char *other);
void openGameMenu();
void gameMenuTap(int16_t x, int16_t y);
void renderGameMenu();
void startMole();
void moleTap(int16_t x, int16_t y);
void renderMole();
void startRps();
void rpsTap(int16_t x, int16_t y);
void renderRps();
void arcGameMenuTap(int16_t x, int16_t y);
void arcRenderMenu();
void arcTetrisTap(int16_t x, int16_t y);
void arcRenderTetris();
void arcSnakeTap(int16_t x, int16_t y);
void arcRenderSnake();
void arcMineTap(int16_t x, int16_t y);
void arcRenderMine();
void startQuiz151();
void quiz151Tap(int16_t x, int16_t y);
void renderQuiz151();
void startMonsterCatch();
void monsterCatchMove(int16_t x);
void renderMonsterCatch();
void renderAlarmRinging();
void renderAlarmNotice();
void alarmRingTap(int16_t x, int16_t y);

void updateBrightness(uint32_t now);
void powerIdle();
void powerFinishFrame();
void powerPrintStatus();
void serviceGameLogic(uint32_t now);
static void renderPowerSettings();

void setup() {
  Serial.setRxBufferSize(8192);  // la transferencia a SD llega en bloques de 2 KB
  Serial.begin(115200);
  // CRITICO: sin esto, Serial.print BLOQUEA el juego cuando no hay un
  // monitor serie abierto en el host (el bufer TX del USB CDC se llena
  // y nadie lo vacia) -> con timeout 0 los mensajes se descartan
  Serial.setTxTimeoutMs(0);
  Serial.printf("TamaPoke fw v%s\n", FW_VERSION);
  loadLang();  // idioma guardado; Korean build migrates to KO once
  Wire.begin(IIC_SDA, IIC_SCL);
  // CST9217 (tactil), AXP2101 (PMU) y PCF85063 (RTC) comparten este bus I2C.
  // Red de seguridad para PMU/RTC (SensorLib NO respeta este timeout en el
  // tactil; el cuelgue del tactil dormido se resuelve gateando por INT, ver
  // handleTouch).
  Wire.setTimeOut(50);

  // Preserve startup compatibility. The standard 1.75 panel/touch share
  // DCDC1 with the MCU; never switch that rail for display sleep.
  pmuEnablePanel();

  // QSPI a 80MHz (por defecto 40): el flush del framebuffer es el cuello de
  // botella del fps (~56ms a 40MHz). Si el panel mostrara basura, bajar a 40M.
  if (!gfx->begin(80000000)) Serial.println("gfx->begin() fallo");
  panel->setBrightness(180);

  touch.setPins(TP_RESET, TP_INT);
  bool touchOk = false;
  for (int i = 0; i < 3 && !touchOk; i++) {  // a veces falla al primer intento
    touchOk = touch.begin(Wire, 0x5A, IIC_SDA, IIC_SCL);
    if (!touchOk) delay(150);
  }
  if (!touchOk) Serial.println("CST9217 no detectado");
  // begin() deja el chip en modo comando (lee la identidad y no sale);
  // hace falta un reset por hardware para que vuelva a reportar toques
  touch.reset();
  touch.setMaxCoordinates(LCD_WIDTH, LCD_HEIGHT);
  touch.setMirrorXY(true, true);  // el panel esta montado girado 180 grados
  // INT activo-bajo: salta cuando hay datos. Gatea las lecturas I2C (ver loop)
  pinMode(TP_INT, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(TP_INT), touchIsr, FALLING);
  // Explicit light-sleep: this prebuilt SDK has no automatic PM/tickless idle.
  // GPIO11 is direct touch IRQ. PWR/RTC behind TCA9554 use bounded timer wake.
  // gpio_wakeup_enable changes the interrupt type: arm LOW_LEVEL only inside
  // powerIdle's sleep window, then restore the normal FALLING interrupt.
  powerWakeReady = esp_sleep_enable_gpio_wakeup()==ESP_OK;
  // Keep flash/PSRAM supply alive; retain live pet, snooze and framebuffer state.
  if (esp_sleep_pd_config(ESP_PD_DOMAIN_VDDSDIO,ESP_PD_OPTION_ON)!=ESP_OK) powerWakeReady=false;

  pet.begin();
  sdBegin();
  thumbs.load();

  // reloj real: aplica el tiempo que estuvo apagado
  rtcBegin();
  batBegin();
  pwrSetup();
  uint32_t e = rtcEpoch();
  if (e == 0) {
    rtcSetEpoch(1767225600UL);  // RTC virgen: semilla (la hora absoluta da igual,
    e = rtcEpoch();             // solo importan las diferencias)
    Serial.println("RTC sin hora: sembrado, sin progresion offline esta vez");
  }
  pet.syncClock(e);
  alarmBegin();  // alarma diaria persistente (hora/ON-OFF sobreviven apagado)

  audioBegin();  // ES8311 + I2S + amplificador (suena un jingle de arranque)

  lastInteract = millis();
  powerInitOnce();
  powerPrintStatus();
}

// carga/descarga el sprite de SD cuando cambia la especie
void ensureMon() {
  if (pet.speciesId == monFor && monShinyFor == pet.shiny && !sdDirty) return;
  sdDirty = false;
  monFor = pet.speciesId;
  monShinyFor = pet.shiny;
  mon.unload();
  pmd.unload();
  beh.x = beh.targetX = 233;
  beh.mode = 0;
  beh.until = 0;
  if (pet.speciesId >= 1 && pet.speciesId <= DEX_COUNT) {
    pmd.load(pet.speciesId, pet.shiny);          // principal: PMD
    if (!pmd.loaded) mon.load(pet.speciesId, pet.shiny);  // respaldo: B/N
  }
}

void loop() {
  serviceCriticalTasks();
  handleTouch();
  handleSerial();
  ensureMon();
  uint32_t now=millis();
  static uint32_t lastPwr=0;
  if (now-lastPwr>=200UL) {
    lastPwr=now;
    if (pwrShortPressed()) {
      if (alarmRinging()) {
        alarmStop();audioAlarmStop();alarmNotice=2;alarmNoticeUntil=now+3200;
        screenOff=false;manualClockView=false;lastInteract=now;
      } else if (powerPanelSleeping || screenOff || dimStage>=2) {
        // First press wakes; it must not also change brightness or leave a game.
        screenOff=false;lastInteract=now;
      } else {
        const bool modalOpen=otaOpen||battleOpen||alarmNotice||clockOpen||gameOpen||sackOpen||
          gameMenuOpen||arcMenuOpen||arcTetrisOpen||arcSnakeOpen||arcMineOpen||moleOpen||
          rpsOpen||quizOpen||catchOpen||galleryOpen||kbOpen||cardOpen||pet.awaitingStarter()||
          pet.ceremony||confirmUntil||choiceKind||feedMenuUntil||bathUntil;
        if (manualClockView && !modalOpen) powerCycleBrightness();
        else if (modalOpen) {screenOff=!screenOff;if(!screenOff)lastInteract=now;}
        else {screenOff=false;manualClockView=!manualClockView;lastInteract=now;}
      }
      powerForceRender=true;
    }
  }
  // These services must run even when zero frames are drawn.
  serviceWireless(millis());
  serviceCriticalTasks();
  now=millis();
  updateBrightness(now);
  serviceGameLogic(millis());

  if (pet.savePending() && !otaFlashBusy() && (powerPanelSleeping||dimStage>=1||pet.sleeping))
    pet.flushSave();
  static uint32_t lastClock=0;
  if (now-lastClock>=30000UL) {lastClock=now;uint32_t e=rtcEpoch();if(e)pet.lastSeenEpoch=e;}
  static uint32_t lastHealth=0;
  if(now-lastHealth>=300000UL){lastHealth=now;powerPrintStatus();}

  if (!powerPanelSleeping) {
    const bool playing=gameOpen||sackOpen||moleOpen||rpsOpen||catchOpen||arcTetrisOpen||arcSnakeOpen;
    const bool staticUi=clockOpen||kbOpen||cardOpen||gameMenuOpen||arcMenuOpen||arcMineOpen||
      (galleryOpen&&!galleryDetail);
    uint32_t interval=playing?85UL:100UL;
    if(!alarmRinging() && !alarmNotice){
      if(standbyClockActive() || dimStage==1) interval=playing?85UL:500UL;
      if(staticUi) interval=1000UL;
      if(otaOpen) interval=250UL;
    }
    static uint32_t renderedActivity=0;
    // Inputs and wake force one immediate frame; quiet menus need no 10Hz repaint.
    const uint32_t sinceFrame=millis()-lastRender;
    if((powerForceRender && powerRestoreBrightness) ||
       (sinceFrame>=85UL && (powerForceRender || renderedActivity!=lastInteract || sinceFrame>=interval))){
      lastRender=millis();renderedActivity=lastInteract;render();powerFinishFrame();
    }
  }
  powerIdle();
}

// brillo segun sueno + inactividad (proteccion del AMOLED)
// Display/CPU policy and service implementations are in power_runtime.inc.

// ---------- consola serie (provision de SD + depuracion) ----------

void handleSerial() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;
  if (sdSerialCommand(line)) return;

  if (line == "HATCH") {
    pet.eggTap(); pet.eggTap(); pet.eggTap();
    Serial.println("DONE");
  } else if (line.startsWith("SPEC ")) {
    int n = line.substring(5).toInt();
    if (n >= 1 && n <= DEX_COUNT) {
      pet.prevSpeciesId = pet.speciesId;
      pet.speciesId = n;
      Serial.printf("especie #%d %s\n", n, DEX_TBL[n].name);
    }
    Serial.println("DONE");
  } else if (line.startsWith("LVL ")) {
    pet.ageMinutes = (uint32_t)line.substring(4).toInt() * MINUTES_PER_LEVEL;
    Serial.println("DONE");
  } else if (line.startsWith("TIME ")) {
    uint32_t e = (uint32_t)line.substring(5).toInt();
    rtcSetEpoch(e);
    pet.setClock(e);
    Serial.printf("rtc=%u\n", rtcEpoch());
    Serial.println("DONE");
  } else if (line.startsWith("RTCSET ")) {  // solo RTC (simular apagados en pruebas)
    rtcSetEpoch((uint32_t)line.substring(7).toInt());
    Serial.printf("rtc=%u\n", rtcEpoch());
    Serial.println("DONE");
  } else if (line == "TIME") {
    Serial.printf("rtc=%u\n", rtcEpoch());
    Serial.println("DONE");
  } else if (line == "GAL") {
    galleryOpen = !galleryOpen;
    galleryDetail = 0;
    galleryDirty = true;
    if (!galleryOpen) galleryPmd.unload();
    Serial.println("DONE");
  } else if (line == "EGGS") {
    // simula 20 tiradas de huevo (no cambia el estado del juego)
    for (int i = 0; i < 20; i++) {
      int16_t d = pet.pickEggSpecies();
      Serial.printf("%d:%s(r%u) ", d, DEX_TBL[d].name, DEX_TBL[d].rarity);
    }
    Serial.println();
    Serial.println("DONE");
  } else if (line == "SHINY") {  // alterna shiny del actual (pruebas)
    pet.shiny = !pet.shiny;
    Serial.printf("shiny=%d\n", pet.shiny);
    Serial.println("DONE");
  } else if (line.startsWith("NICK ")) {
    pet.rename(line.substring(5).c_str());
    Serial.printf("nick=%s\n", pet.nick);
    Serial.println("DONE");
  } else if (line == "CAREDAY") {  // simula un dia nuevo cuidado (pruebas)
    pet.setClock(pet.lastSeenEpoch + 86400);
    pet.caress();
    Serial.printf("streak=%u bond=%u medals=0x%X\n", pet.streak, pet.bond, pet.medals);
    Serial.println("DONE");
  } else if (line == "BYE") {
    pet.startFarewell();
    Serial.println("DONE");
  } else if (line == "RUN") {
    pet.startRunaway();
    Serial.println("DONE");
  } else if (line == "BEEP") {
    sfxPlay(SFX_HATCH);  // prueba de audio
    Serial.println("DONE");
  } else if (line == "ALARMTEST") {
    alarmSetEnabled(true);
    uint32_t ae=rtcEpoch();
    alarmSetTime((ae/3600UL)%24, ((ae/60UL)%60 + 1)%60);
    Serial.printf("alarm test %02u:%02u\n", alarmHour(), alarmMinute());
    Serial.println("DONE");
  } else if (line == "ALARM") {
    Serial.printf("alarm on=%d %02u:%02u ring=%d snooze=%u\n",
                  alarmEnabled(), alarmHour(), alarmMinute(), alarmRinging(),
                  alarmSnoozeUntil());
    Serial.println("DONE");
  } else if (line == "ABANDON") {
    pet.dbgRunawayReady();  // fuerza el estado "lista para escaparse" (test del boton)
    Serial.println("DONE");
  } else if (line == "WIPE") {
    pet.factoryReset();     // borra NVS y reinicia -> partida nueva (eleccion de inicial)
    Serial.println("DONE");
    delay(100);
    ESP.restart();
  } else if (line == "REG") {
    Serial.printf("pokedex %u/151:", pet.registeredCount());
    for (int i = 1; i <= 151; i++)
      if (pet.isRegistered(i)) Serial.printf(" %d", i);
    Serial.println();
    Serial.println("DONE");
  } else if (line == "POWER") {
    powerPrintStatus();
    Serial.println("DONE");
  } else if (line == "HEALTH") {
    powerPrintStatus();
    Serial.printf("up=%lus heap=%u min=%u sd=%d mon=%d\n",
                  (unsigned long)(millis() / 1000), ESP.getFreeHeap(),
                  ESP.getMinFreeHeap(), sdReady, pmd.loaded || mon.loaded);
    Serial.println("DONE");
  } else if (line == "STATS") {
    Serial.printf("spec=%d nv=%u com=%u fel=%u ene=%u lim=%u desc=%u sd=%d mon=%d bat=%d usb=%d rtc=%u\n",
                  pet.speciesId, pet.level(), pet.fullness, pet.joy, pet.energy,
                  pet.hygiene, pet.careMistakes, sdReady, mon.loaded,
                  batPercent(), usbPresent(), rtcEpoch());
    Serial.printf("peso=%u fue=%u def=%u vel=%u genes=%u/%u/%u tr=%u/%u/%u baya=%d\n",
                  pet.weight, pet.atkStat(), pet.defStat(), pet.speStat(),
                  pet.geneAtk, pet.geneDef, pet.geneSpe,
                  pet.trAtk, pet.trDef, pet.trSpe, pet.berryKnown);
    Serial.printf("shiny=%d streak=%u/%u bond=%u medals=0x%X(%u) nick=%s\n",
                  pet.shiny, pet.streak, pet.bestStreak, pet.bond, pet.medals,
                  pet.totalMedals, pet.nick);
    Serial.println("DONE");
  }
}

// ---------- entrada tactil ----------

bool inPetZone(int16_t x, int16_t y) {
  return x > 110 && x < 356 && y > 95 && y < 310;
}

bool standbyClockActive() {
  if (screenOff || battleOpen || otaOpen || alarmRinging() || alarmNotice || clockOpen || gameOpen || sackOpen ||
      gameMenuOpen || arcMenuOpen || arcTetrisOpen || arcSnakeOpen || arcMineOpen || moleOpen || rpsOpen || quizOpen || catchOpen || galleryOpen || kbOpen || cardOpen ||
      pet.awaitingStarter() || pet.ceremony ||
      confirmUntil || choiceKind || feedMenuUntil || bathUntil) return false;
  return manualClockView || millis() - lastInteract >= 30000UL;
}

// el toque se resuelve al LEVANTAR el dedo para distinguir tap de deslizar
void handleTouch() {
  static uint32_t lastPoll = 0;
  if (millis() - lastPoll < 20) return;  // 50 Hz le sobra a un dedo
  lastPoll = millis();
  // solo tocamos el bus si el chip aviso por INT o si el dedo sigue abajo (hay
  // que detectar el levantamiento). Leer el CST9217 dormido se colgaba ~1s y
  // congelaba el loop entero; SensorLib no respeta el timeout de Wire.
  if (!gTouchIrq && !wasPressed) return;
  gTouchIrq = false;
  int16_t x, y;
  bool pressed = touch.getPoint(&x, &y, 1) > 0;
  // Fast touch-down games must also swallow the gesture that wakes the screen.
  static bool wakeGesture=false;
  if(pressed && (powerPanelSleeping || screenOff || dimStage>=2)){
    wakeGesture=true;screenOff=false;lastInteract=millis();wasPressed=true;return;
  }
  if(wakeGesture){
    lastInteract=millis();wasPressed=pressed;
    if(!pressed)wakeGesture=false;
    return;
  }

  // 몬스터볼 캐치: 누르고 움직이는 동안 포켓몬이 손가락을 따라간다.
  if (catchOpen) {
    if (pressed) {
      lastInteract = millis();
      if (y < 72) { if (!wasPressed) catchOpen = false; }
      else monsterCatchMove(x);
    }
    wasPressed = pressed;
    return;
  }

  // 피카츄 잡기: 반응속도가 중요한 게임이라 touch-down 즉시 판정.
  if (moleOpen) {
    if (pressed && !wasPressed) {
      lastInteract = millis();
      moleTap(x, y);
    }
    wasPressed = pressed;
    return;
  }

  // saco de entrenamiento: cada toque cuenta al instante (aporrear rapido)
  if (sackOpen) {
    if (pressed && !wasPressed) {
      lastInteract = millis();
      if (y < 72) sackOpen = false;  // tocar arriba = abandonar
      else sackTap();
    }
    wasPressed = pressed;
    return;
  }

  if (pressed && !wasPressed) {  // empieza el gesto
    gestureFromStandby = standbyClockActive();
    tX0 = tXl = x;
    tY0 = tYl = y;
    if (gameOpen) {
      gameTouchBallX = ballX;
      gameTouchBallY = ballY;
      gameTouchBallValid = true;
    }
    tStart = millis();
    holdFired = false;
    swallowGesture = (dimStage > 0) || screenOff || gestureFromStandby;
    screenOff = false;
    lastInteract = millis();
  } else if (pressed) {  // sigue apoyado
    tXl = x;
    tYl = y;
    // pulsacion larga sin moverse sobre el bicho -> dialogo de soltar
    if (!holdFired && !swallowGesture && !alarmRinging() && !galleryOpen && !cardOpen && !kbOpen && !clockOpen && !battleOpen && !otaOpen &&
        !gameMenuOpen && !arcMenuOpen && !arcTetrisOpen && !arcSnakeOpen && !arcMineOpen && !moleOpen && !rpsOpen && !quizOpen && !catchOpen && millis() - tStart > 3000 &&
        abs(tXl - tX0) < 30 && abs(tYl - tY0) < 30 && inPetZone(tX0, tY0) &&
        !pet.isEgg() && !confirmUntil && !pet.ceremony) {
      confirmUntil = millis() + 10000;
      holdFired = true;
    }
  } else if (wasPressed) {  // levanta el dedo: resolver gesto
    lastInteract = millis();
    int dx = tXl - tX0, dy = tYl - tY0;
    uint32_t dt = millis() - tStart;
    if (!holdFired && gestureFromStandby) {
      // Clock view and sleep state are independent. Exit the clock without waking.
      if (abs(dy) > 80 && abs(dx) < 70 && dt < 800 && dy > 0) openClock();
      manualClockView = false;
      gestureFromStandby = false;
      swallowGesture = false;
    } else if (!holdFired && !swallowGesture) {
      if (abs(dx) > 80 && abs(dy) < 70 && dt < 800) onSwipe(dx > 0 ? 1 : -1);
      else if (abs(dy) > 80 && abs(dx) < 70 && dt < 800) onSwipeV(dy > 0 ? 1 : -1);
      else if (dt < 1500 && abs(dx) < 40 && abs(dy) < 40) onTap(tX0, tY0);
    }
  }
  wasPressed = pressed;
}

// deslizar vertical: abre/cierra la ficha del bicho
void openClock();  // prototipo

void onSwipeV(int dir) {
  if (alarmRinging() || alarmNotice || battleOpen || otaOpen) return;
  if (pet.awaitingStarter()) return;  // bloqueado durante la eleccion de inicial
  if (gameOpen || gameMenuOpen || arcMenuOpen || arcTetrisOpen || arcSnakeOpen || arcMineOpen || moleOpen || rpsOpen || quizOpen || catchOpen || galleryOpen || kbOpen || sackOpen || pet.ceremony) return;
  if (clockOpen) { clockOpen = false; return; }
  if (cardOpen) {
    if (dir < 0) cardOpen = false;  // arriba cierra la ficha
    return;
  }
  if (dir > 0) {                    // deslizar abajo: ajustar hora
    if (!confirmUntil && !feedMenuUntil) openClock();
  } else if (!pet.isEgg() && !confirmUntil && !feedMenuUntil) {
    cardOpen = true;                // deslizar arriba: ficha
    cardPage = 0;
  }
}

// deslizar: dir +1 = hacia la derecha
void onSwipe(int dir) {
  if (alarmRinging() || alarmNotice || battleOpen || otaOpen) return;
  if (pet.awaitingStarter()) return;  // bloqueado durante la eleccion de inicial
  if (gameOpen || gameMenuOpen || arcMenuOpen || arcTetrisOpen || arcSnakeOpen || arcMineOpen || moleOpen || rpsOpen || quizOpen || catchOpen || kbOpen || clockOpen) return;
  if (cardOpen) {  // dentro de la ficha: cambiar entre las 4 paginas
    int p = (int)cardPage + (dir > 0 ? -1 : 1);  // izquierda avanza
    cardPage = p < 0 ? 0 : (p > 3 ? 3 : p);
    return;
  }
  if (!galleryOpen) {
    if (!pet.ceremony && !confirmUntil) {
      galleryOpen = true;
      galleryPage = 0;
      galleryDetail = 0;
      galleryDirty = true;
    }
    return;
  }
  if (galleryDetail) {  // en detalle: volver a la rejilla
    galleryDetail = 0;
    galleryPmd.unload();
    galleryDirty = true;
    return;
  }
  int np = galleryPage - dir;  // deslizar a la izquierda avanza pagina
  if (np < 0) {                // retroceder desde la primera = salir
    galleryOpen = false;
    galleryPmd.unload();
    return;
  }
  if (np > 9) np = 9;
  if (np != galleryPage) {
    galleryPage = np;
    galleryDirty = true;
  }
}

void onTap(int16_t x, int16_t y) {
  // Serial.printf("TOUCH %d %d\n", x, y);  // diagnostico (silenciado: satura el log)
  if (alarmRinging()) { alarmRingTap(x, y); return; }
  if (alarmNotice) {
    alarmNotice=0; alarmNoticeUntil=0; lastInteract=millis(); return;
  }
  if (pet.awaitingStarter()) {  // primera partida: elegir inicial
    for (int i = 0; i < 3; i++) {
      int ry = STARTER_ROW_Y + i * (STARTER_ROW_H + STARTER_ROW_GAP);
      if (x >= 70 && x <= 396 && y >= ry && y <= ry + STARTER_ROW_H) {
        pet.chooseStarter(STARTER_DEX[i]);
        sfxPlay(SFX_TAP);
        break;
      }
    }
    return;
  }
  if (arcTetrisOpen) { arcTetrisTap(x, y); return; }
  if (arcSnakeOpen) { arcSnakeTap(x, y); return; }
  if (arcMineOpen) { arcMineTap(x, y); return; }
  if (arcMenuOpen) { arcGameMenuTap(x, y); return; }
  if (otaOpen) { otaTap(x, y); return; }
  if (battleOpen) { battleTap(x, y); return; }
  if (gameMenuOpen) { gameMenuTap(x, y); return; }
  if (quizOpen) { quiz151Tap(x, y); return; }
  if (rpsOpen) { rpsTap(x, y); return; }
  if (galleryOpen) {
    galleryTap(x, y);
    return;
  }
  if (kbOpen) {
    keyboardTap(x, y);
    return;
  }
  if (clockOpen) {
    clockTap(x, y);
    return;
  }
  if (pet.ceremony) return;  // durante la despedida no hay botones
  if (cardOpen) {
    if (cardPage == 0 && y < 84) openKeyboard();  // tocar el nombre = renombrar
    else if (cardPage == 1 && y >= 300 && y <= 340 && x >= 96 && x <= 370) {
      cardOpen = false;            // boton ENTRENAR FUERZA
      startSack();
    } else {
      cardOpen = false;
    }
    return;
  }
  if (gameOpen) {
    gameTap(x, y);
    return;
  }
  if (choiceKind) {          // dialogo de decision: boton accion (arriba) / mantener (abajo)
    bool b1 = (x >= 93 && x <= 373 && y >= 206 && y <= 258);  // accion
    bool b2 = (x >= 93 && x <= 373 && y >= 268 && y <= 320);  // mantener / quedaros
    if (choiceKind == 1) {                 // evolucion
      if (b1) { int16_t old = pet.speciesId; pet.evolve(); evoPmd.load(old, pet.shiny); }
      else if (b2) pet.declineEvolve();
    } else if (choiceKind == 2) {          // despedida
      if (b1) pet.startFarewell();
      else if (b2) pet.declineFarewell();
    }
    choiceKind = 0;
    return;
  }
  if (confirmUntil) {        // dialogo "soltar?": SI / NO
    if (millis() < confirmUntil && x >= 118 && x <= 218 && y >= 252 && y <= 304) {
      pet.release();
    }
    confirmUntil = 0;
    return;
  }
  if (feedMenuUntil) {       // selector de comida
    if (millis() < feedMenuUntil && y >= 288 && y <= 352 && x >= 101 && x <= 365) {
      int item = (x - 101) / 66;
      if (item == 3) pet.feedCandy();
      else pet.feedBerry(item);
      sfxPlay(SFX_EAT);
    }
    feedMenuUntil = 0;
    return;
  }
  if (pet.isEgg()) {
    pet.eggTap();
    sfxPlay(SFX_TAP);
    return;
  }
  // boton de evolucion: abre el dialogo evolucionar/mantener
  if (pet.wantEvolveButton() && x >= EVO_BTN_X && x <= EVO_BTN_X + EVO_BTN_W &&
      y >= EVO_BTN_Y && y <= EVO_BTN_Y + EVO_BTN_H) {
    choiceKind = 1; choiceUntil = millis() + 12000;
    return;
  }
  // botones de final (mismo recuadro): escapada directa; despedida abre dialogo
  if (x >= FAR_BTN_X && x <= FAR_BTN_X + FAR_BTN_W &&
      y >= FAR_BTN_Y && y <= FAR_BTN_Y + FAR_BTN_H) {
    if (pet.canRunawayNow()) { pet.startRunaway(); return; }
    if (pet.wantFarewellButton()) { choiceKind = 2; choiceUntil = millis() + 12000; return; }
  }
  // Bottom edge compensation only. Pick the nearest icon in the bottom zone.
  int hitBtn = -1;
  long bestD2 = 0x7fffffffL;
  if (y >= 348 && y <= 458) {
    for (int i = 0; i < 4; i++) {
      long dx = (long)x - buttons[i].cx;
      long dy = (long)y - buttons[i].cy;
      long d2 = dx * dx + dy * dy;
      if (d2 <= 52L * 52L && d2 < bestD2) {
        bestD2 = d2;
        hitBtn = i;
      }
    }
  }
  if (hitBtn >= 0) {
    Serial.printf("BTN %d\n", hitBtn);
    sfxPlay(SFX_TAP);
    if (hitBtn == 0) {
      if (!pet.sleeping) feedMenuUntil = millis() + 6000;
    } else if (hitBtn == 1) {
      openGameMenu();
    } else if (hitBtn == 2) {
      pet.toggleLight();
    } else {
      startBath();
    }
    return;
  }
  // tocar al bicho = caricia
  if (inPetZone(x, y)) {
    Serial.println("PET");
    pet.caress();
    if (!pet.sleeping) sfxPlay(SFX_HEART);
  }
}

// ---------- render ----------

bool gNight = false;  // noche real (por hora) o durmiendo: lo fija render()
uint16_t inkColor() { return gNight ? UI_INK_NIGHT : UI_INK; }

// ---------- escena de fondo: bioma del tipo + hora real del RTC ----------

#define C565(r, g, b) ((uint16_t)((((r) >> 3) << 11) | (((g) >> 2) << 5) | ((b) >> 3)))
#define HORIZON 232  // linea donde el cielo se encuentra con el suelo

uint16_t lerp565(uint16_t a, uint16_t b, int i, int n) {
  if (n <= 0) return a;
  int ar = (a >> 11) & 31, ag = (a >> 5) & 63, ab = a & 31;
  int br = (b >> 11) & 31, bg = (b >> 5) & 63, bb = b & 31;
  return (uint16_t)((((ar + (br - ar) * i / n) << 11)) |
                    (((ag + (bg - ag) * i / n) << 5)) | (ab + (bb - ab) * i / n));
}

// hora del dia 0-23 (de la hora real cacheada cada 30s; 13 si no hay reloj)
int sceneHour() {
  uint32_t e = pet.lastSeenEpoch;
  return e ? (int)((e / 3600) % 24) : 13;
}

// suelo de cada bioma de dia (de noche se mezcla hacia el azul nocturno)
static const uint16_t BIOME_SOIL[6] = {
  C565(0x7e, 0xc0, 0x7f),  // 0 pradera
  C565(0xdc, 0xca, 0x94),  // 1 playa (arena)
  C565(0x4f, 0x8a, 0x55),  // 2 bosque
  C565(0x8a, 0x55, 0x44),  // 3 volcan
  C565(0xa8, 0x90, 0x6a),  // 4 montana
  C565(0xe6, 0xee, 0xf5),  // 5 nieve
};

void drawClouds(uint32_t now, uint16_t col) {
  for (int k = 0; k < 2; k++) {
    int cx = (int)((now / 50 + k * 250) % 560) - 40;
    int cy = 70 + k * 34;
    gfx->fillCircle(cx, cy, 16, col);
    gfx->fillCircle(cx + 18, cy + 3, 13, col);
    gfx->fillCircle(cx - 15, cy + 4, 12, col);
  }
}

void drawScene(uint8_t biome, uint32_t now, bool night) {
  int h = sceneHour();
  uint16_t top, bot;
  if (night)            { top = C565(0x0c, 0x12, 0x24); bot = C565(0x1e, 0x26, 0x46); }
  else if (h < 8)       { top = C565(0xd1, 0x6a, 0x86); bot = C565(0xf3, 0xb8, 0x7c); }  // amanecer
  else if (h < 18)      { top = C565(0x8f, 0xc8, 0xea); bot = C565(0xdc, 0xee, 0xe6); }  // dia
  else                  { top = C565(0xc7, 0x5a, 0x4a); bot = C565(0xf0, 0xae, 0x64); }  // atardecer

  // cielo en bandas
  for (int y = 0; y < HORIZON; y += 8)
    gfx->fillRect(0, y, 466, 8, lerp565(top, bot, y, HORIZON));

  // sol o luna
  if (night) {
    gfx->fillCircle(360, 78, 24, C565(0xe8, 0xee, 0xf5));
    gfx->fillCircle(370, 72, 22, lerp565(top, bot, 78, HORIZON));  // creciente
    for (auto &st : STARS) gfx->fillRect(st[0], st[1], 4, 4, UI_WHITE);
  } else if (h < 18) {
    gfx->fillCircle(360, 84, 26, h < 8 ? C565(0xff, 0xd9, 0x8a) : C565(0xff, 0xe7, 0x9f));
    drawClouds(now, C565(0xff, 0xff, 0xff));
  } else {
    gfx->fillCircle(233, HORIZON - 6, 34, C565(0xff, 0xf1, 0xc8));  // sol poniente
  }

  // mar de la playa: una franja de agua sobre la arena
  uint16_t soil = BIOME_SOIL[biome < 6 ? biome : 0];
  if (night) soil = lerp565(soil, C565(0x16, 0x1c, 0x30), 9, 16);
  if (biome == 1) {
    uint16_t sea = night ? C565(0x1c, 0x34, 0x52) : C565(0x4f, 0x96, 0xc4);
    gfx->fillRect(0, HORIZON - 26, 466, 26, sea);
    for (int i = 0; i < 3; i++) {
      int wy = HORIZON - 22 + i * 7;
      uint16_t fc = night ? C565(0x3a, 0x58, 0x78) : C565(0xbf, 0xe6, 0xf5);
      gfx->fillRect(60 + ((now / 60 + i * 30) % 60), wy, 26, 2, fc);
      gfx->fillRect(300 - ((now / 60 + i * 20) % 60), wy, 26, 2, fc);
    }
  }

  // suelo
  gfx->fillRect(0, HORIZON, 466, 466 - HORIZON, soil);
  uint16_t hill = lerp565(soil, night ? C565(0x0c, 0x12, 0x24) : C565(0xff, 0xff, 0xff), 3, 16);
  gfx->fillRoundRect(-60, HORIZON - 14, 586, 60, 30, hill);

  // detalles del bioma
  uint16_t dk = lerp565(soil, C565(0x10, 0x18, 0x20), night ? 11 : 7, 16);
  if (biome == 2) {  // bosque: coniferas en silueta
    for (int tx : { 60, 150, 360, 416 }) {
      gfx->fillTriangle(tx, HORIZON - 46, tx - 16, HORIZON, tx + 16, HORIZON, dk);
      gfx->fillTriangle(tx, HORIZON - 60, tx - 12, HORIZON - 28, tx + 12, HORIZON - 28, dk);
    }
  } else if (biome == 3) {  // volcan: rocas y brasas
    gfx->fillTriangle(70, HORIZON, 40, HORIZON + 30, 100, HORIZON + 30, dk);
    gfx->fillTriangle(400, HORIZON + 4, 372, HORIZON + 30, 430, HORIZON + 30, dk);
    if (!night)
      for (int e = 0; e < 4; e++)
        gfx->fillRect(120 + e * 70, HORIZON + 8 + (e % 2) * 6, 4, 4, C565(0xff, 0x9b, 0x3a));
  } else if (biome == 4) {  // montana: cumbres al fondo
    gfx->fillTriangle(140, HORIZON - 50, 60, HORIZON, 220, HORIZON, dk);
    gfx->fillTriangle(330, HORIZON - 38, 250, HORIZON, 410, HORIZON, dk);
  } else if (biome == 5 && !night) {  // nieve: copos cayendo
    for (int f = 0; f < 10; f++) {
      int fx = (f * 53 + now / 40) % 466;
      int fy = (f * 90 + now / 18) % HORIZON;
      gfx->fillRect(fx, fy, 3, 3, UI_WHITE);
    }
  } else if (biome == 0) {  // pradera: matas de hierba
    for (int gx : { 80, 175, 300, 395 })
      for (int b = -1; b <= 1; b++)
        gfx->fillRect(gx + b * 5, HORIZON + 6, 2, 8 + (b == 0 ? 4 : 0), dk);
  }
}

// primera partida: elige inicial entre Bulbasaur / Charmander / Squirtle
void renderStarterSelect() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, UI_BG_DAY);
  const char *t = T(S_CHOOSE_STARTER);
  uiPrintCenter(t, 62, UI_INK, 2);
  for (int i = 0; i < 3; i++) {
    int16_t d = STARTER_DEX[i];
    const DexEntry &de = DEX_TBL[d];
    int ry = STARTER_ROW_Y + i * (STARTER_ROW_H + STARTER_ROW_GAP);
    gfx->fillRoundRect(70, ry, 326, STARTER_ROW_H, 14, lerp565(de.accent, UI_WHITE, 6, 8));
    gfx->drawRoundRect(70, ry, 326, STARTER_ROW_H, 14, de.accent);
    const uint8_t *th = thumbs.get(d);     // miniatura del inicial (si la SD esta lista)
    if (th) drawThumb(th, 76, ry - 5, 3, false);
    gfx->setTextColor(UI_INK);
    gfx->setTextSize(3);
    gfx->setCursor(178, ry + 24);
    uiPrintAt(localizedPokeName(d), 178, ry + 20, UI_INK, 3);
  }
  gfx->flush();
}

void render() {
  if (alarmRinging()) {
    renderAlarmRinging();
    return;
  }
  if (alarmNotice) { renderAlarmNotice(); return; }
  if (pet.awaitingStarter()) {  // primera partida: elegir inicial (prioridad total)
    renderStarterSelect();
    return;
  }
  if (arcTetrisOpen) { arcRenderTetris(); return; }
  if (arcSnakeOpen) { arcRenderSnake(); return; }
  if (arcMineOpen) { arcRenderMine(); return; }
  if (arcMenuOpen) { arcRenderMenu(); return; }
  if (otaOpen) { renderOta(); return; }
  if (battleOpen) { renderBattle(); return; }
  if (gameMenuOpen) { renderGameMenu(); return; }
  if (moleOpen) { renderMole(); return; }
  if (rpsOpen) { renderRps(); return; }
  if (quizOpen) { renderQuiz151(); return; }
  if (catchOpen) { renderMonsterCatch(); return; }
  if (galleryOpen) {
    renderGallery();
    return;
  }
  if (gameOpen) {
    renderGame();
    return;
  }
  if (sackOpen) {
    renderSack();
    return;
  }
  if (kbOpen) {
    renderKeyboard();
    return;
  }
  if (clockOpen) {
    renderClock();
    return;
  }
  if (cardOpen) {
    renderCard();
    return;
  }
  if (standbyClockActive()) {
    renderStandbyClock();
    return;
  }
  int h = sceneHour();
  gNight = pet.sleeping || h < 6 || h >= 20;
  // drawScene cubre los 466x466 completos: sin fillScreen(NEGRO) previo para
  // que un flush DMA solapado nunca capture negro a medias (anti-parpadeo)
  drawScene(pet.isEgg() ? 0 : DEX_TBL[pet.speciesId].biome, millis(), gNight);

  if (pet.ceremony) {
    const DexEntry &d = DEX_TBL[pet.speciesId];
    const char *msg = (pet.ceremony == CER_FAREWELL) ? T(S_FAREWELL)
                      : (pet.ceremony == CER_RUNAWAY) ? T(S_RUNAWAY)
                                                      : T(S_GOODBYE);
    drawHeader(localizedPokeName(pet.speciesId), d.accent, msg);
    drawCeremony();
    gfx->flush();
    return;
  }

  if (pet.isEgg()) {
    drawHeader(T(S_EGG_HDR), inkColor(), eggMsg());
    int s = 5, x = CX - 16 * s, y = PET_CY - 16 * s;
    drawMap(SPR_EGG, SPRITE_H, x, y, s, false);
    if (pet.eggCracks() >= 1)
      for (auto &c : CRACK1) gfx->fillRect(x + c[0] * s, y + c[1] * s, s, s, INK_K);
    if (pet.eggCracks() >= 2)
      for (auto &c : CRACK2) gfx->fillRect(x + c[0] * s, y + c[1] * s, s, s, INK_K);
    if (pet.eggRarity() >= R_RARO) {
      const char *rar = (pet.eggRarity() == R_LEGENDARIO) ? T(S_EGG_LEGEND) : T(S_EGG_RARE);
      uiPrintCenter(rar, 316, pet.eggRarity() == R_LEGENDARIO ? UI_BAR_WARN : 0x4C98, 2);
    }
    char reg[24];
    snprintf(reg, sizeof(reg), T(S_POKEDEX_FMT), pet.registeredCount());
    gfx->fillRect(0, 312, 466, 154, gNight ? UI_BG_NIGHT : UI_BG_DAY);
    uiPrintCenter(reg, 348, inkColor(), 2);
  } else {
    const DexEntry &d = DEX_TBL[pet.speciesId];
    char name[64];
    const char *base = pet.nick[0] ? pet.nick : localizedPokeName(pet.speciesId);
    snprintf(name, sizeof(name), T(S_NAME_FMT), pet.shiny ? "*" : "", base, pet.level());
    drawHeader(name, gNight ? UI_INK_NIGHT : d.accent, statusMsg());
    drawStreakBadge();
    drawPet();
    drawBath();
    drawPoops();
    // panel inferior: base limpia para barras y botones sobre el paisaje
    gfx->fillRect(0, 312, 466, 154, gNight ? UI_BG_NIGHT : UI_BG_DAY);
    drawBars();
    drawButtons();
    drawCelebration();
    if (pet.wantEvolveButton()) drawEvolveButton();        // CTA rojo: evolucionar
    else if (pet.canRunawayNow()) drawRunawayButton();     // CTA sombrio: escapada (abandono)
    else if (pet.wantFarewellButton()) drawFarewellButton();  // CTA dorado: despedida
  }

  if (pet.sleeping) {
    gfx->setTextColor(UI_INK_NIGHT);
    gfx->setTextSize(2);
    gfx->setCursor(312, 132);
    gfx->print("Zzz...");
  }

  // selector de comida
  if (feedMenuUntil) {
    if (millis() > feedMenuUntil) {
      feedMenuUntil = 0;
    } else {
      gfx->fillRoundRect(101, 288, 264, 64, 14, UI_WHITE);
      gfx->drawRoundRect(101, 288, 264, 64, 14, inkColor());
      drawMap(SPR_ICON_FOOD, 16, 110, 296, 3, false);
      drawMap(SPR_ICON_BERRY_B, 16, 176, 296, 3, false);
      drawMap(SPR_ICON_BERRY_G, 16, 242, 296, 3, false);
      drawMap(SPR_ICON_CANDY, 16, 308, 296, 3, false);
    }
  }

  // dialogo "soltar?" (pulsacion larga sobre el bicho)
  if (confirmUntil) {
    if (millis() > confirmUntil) {
      confirmUntil = 0;
    } else {
      gfx->fillRoundRect(94, 168, 278, 152, 16, UI_WHITE);
      gfx->drawRoundRect(94, 168, 278, 152, 16, UI_INK);
      char q[96];
      snprintf(q, sizeof(q), T(S_RELEASE_FMT), localizedPokeName(pet.speciesId));
      uiPrintCenter(q, 192, UI_INK, 2);
      gfx->fillRoundRect(118, 252, 100, 52, 12, UI_BAR_OK);
      uiPrintAt(T(S_YES), 118 + (100-uiTextWidth(T(S_YES),2))/2, 266, UI_WHITE, 2);
      gfx->fillRoundRect(248, 252, 100, 52, 12, UI_BAR_BAD);
      uiPrintAt(T(S_NO), 248 + (100-uiTextWidth(T(S_NO),2))/2, 266, UI_WHITE, 2);
    }
  }

  // dialogo de decision (evolucionar/mantener, despedirse/quedaros)
  if (choiceKind) {
    if (millis() > choiceUntil) choiceKind = 0;
    else drawChoiceDialog();
  }

  gfx->flush();
}

// ---------- 놀이 선택 / 확장형 미니게임 허브 ----------

// Mini-game sprite helpers. Prefer PMD, then legacy SD sprite, then the nine flash species.
static bool drawFlashDexMini(int16_t dex,int cx,int groundY,uint8_t scale) {
  int fi=flashIdxForDex(dex); if(fi<0) return false;
  const Species &sp=SPECIES[fi];
  drawMap(sp.sprite,SPRITE_H,cx-16*scale,groundY-32*scale,scale,false);
  return true;
}

static bool drawCurrentPetMini(int cx,int groundY,uint32_t now,uint8_t maxS) {
  if(pmd.loaded){drawPmdAct(PMD_IDLE,cx,groundY,now,true,false,maxS); return true;}
  if(mon.loaded){
    int sc=(mon.h*2>150)?1:2; if(sc>maxS) sc=maxS; if(sc<1) sc=1;
    uint16_t fm=mon.frameMs?mon.frameMs:100; uint16_t fi=(now/fm)%mon.frames;
    const uint8_t *fr=mon.data+(uint32_t)fi*mon.w*mon.h;
    int x0=cx-(mon.w*sc)/2, y0=groundY-mon.h*sc;
    for(int r=0;r<mon.h;r++) for(int c=0;c<mon.w;c++){
      uint8_t idx=fr[r*mon.w+c]; if(idx==0xFF) continue;
      gfx->fillRect(x0+c*sc,y0+r*sc,sc,sc,mon.pal[idx]);
    }
    return true;
  }
  return drawFlashDexMini(pet.speciesId,cx,groundY,maxS>2?2:maxS);
}

static bool drawOpponentMini(int16_t dex,int cx,int groundY,uint32_t now,uint8_t maxS) {
  if(miniOpponentPmd.loaded){drawPmdActM(miniOpponentPmd,PMD_IDLE,cx,groundY,now,true,false,maxS); return true;}
  return drawFlashDexMini(dex,cx,groundY,maxS>2?2:maxS);
}

static void drawMiniBallIcon(int cx,int cy,uint16_t topCol) {
  gfx->fillCircle(cx,cy,20,UI_WHITE);
  gfx->fillCircle(cx,cy-3,18,topCol);
  gfx->fillRect(cx-18,cy,36,7,UI_INK);
  gfx->fillCircle(cx,cy+3,7,UI_INK);
  gfx->fillCircle(cx,cy+3,3,UI_WHITE);
}

static void gameCard(int x, int y, int w, int h, uint16_t bg, const char *label, uint8_t icon) {
  gfx->fillRoundRect(x+3, y+5, w, h, 18, C565(0xb6,0xc4,0xc7));
  gfx->fillRoundRect(x, y, w, h, 18, bg);
  gfx->drawRoundRect(x, y, w, h, 18, UI_INK);
  int cx=x+w/2, cy=y+34;
  if (icon==0) {
    drawMiniBallIcon(cx,cy,C565(0xef,0x53,0x4f));
  } else if (icon==1) {
    // Pikachu-like yellow face for the menu (the game uses the SD sprite when available).
    gfx->fillTriangle(cx-22,cy-8,cx-13,cy-31,cx-5,cy-7,C565(0xf7,0xd8,0x43));
    gfx->fillTriangle(cx+22,cy-8,cx+13,cy-31,cx+5,cy-7,C565(0xf7,0xd8,0x43));
    gfx->fillCircle(cx,cy,21,C565(0xf7,0xd8,0x43));
    gfx->fillCircle(cx-7,cy-4,3,UI_INK); gfx->fillCircle(cx+7,cy-4,3,UI_INK);
    gfx->fillCircle(cx-14,cy+6,4,C565(0xf1,0x52,0x52)); gfx->fillCircle(cx+14,cy+6,4,C565(0xf1,0x52,0x52));
  } else if (icon==2) {
    gfx->fillCircle(cx-18,cy,8,UI_WHITE);
    gfx->drawLine(cx-1,cy+8,cx+10,cy-9,UI_WHITE); gfx->drawLine(cx+10,cy+8,cx-1,cy-9,UI_WHITE);
    gfx->fillRoundRect(cx+17,cy-10,15,20,4,UI_WHITE);
  } else if (icon==3) {
    gfx->fillCircle(cx,cy,22,UI_WHITE); gfx->drawCircle(cx,cy,22,UI_INK);
    uiPrintAt("?",cx-uiTextWidth("?",3)/2,cy-14,UI_INK,3);
  } else {
    drawMiniBallIcon(cx-10,cy,C565(0xef,0x53,0x4f));
    gfx->fillCircle(cx+20,cy-13,5,C565(0xff,0xd6,0x54));
    gfx->drawLine(cx+20,cy-24,cx+20,cy-19,UI_INK);
    gfx->drawLine(cx+9,cy-13,cx+14,cy-13,UI_INK);
  }
  uint8_t lfs = (gLang == LANG_KO ? 3 : 2);
  if (uiTextWidth(label,lfs) > w-12) lfs = (lfs>1)?lfs-1:lfs;
  uiPrintAt(label, x+(w-uiTextWidth(label,lfs))/2, y+h-34, UI_INK, lfs);
}

void openGameMenu() {
  if (pet.isEgg() || pet.sleeping || pet.ceremony) return;
  gameOpen=false; moleOpen=false; rpsOpen=false; quizOpen=false; catchOpen=false; sackOpen=false;
  gameMenuOpen=true; gameMenuPage=0;
  miniOpponentPmd.unload();
  sfxPlay(SFX_GAME_OPEN);
}

void gameMenuTapLegacy(int16_t x, int16_t y) {
  if (y < 78) { gameMenuOpen=false; return; }
  if (gameMenuPage==0) {
    if (x>=58 && x<=222 && y>=108 && y<=218) { gameMenuOpen=false; startGame(); sfxPlay(SFX_GAME_START); return; }
    if (x>=244 && x<=408 && y>=108 && y<=218) { gameMenuOpen=false; startMole(); return; }
    if (x>=58 && x<=222 && y>=238 && y<=348) { gameMenuOpen=false; startRps(); return; }
    if (x>=244 && x<=408 && y>=238 && y<=348) { gameMenuOpen=false; startQuiz151(); return; }
    if (y>=370 && y<=432 && x>=128 && x<=338) { gameMenuPage=1; sfxPlay(SFX_TAP); return; }
  } else {
    if (x>=82 && x<=384 && y>=124 && y<=274) { gameMenuOpen=false; startMonsterCatch(); return; }
    if (y>=340 && y<=420 && x>=128 && x<=338) { gameMenuPage=0; sfxPlay(SFX_TAP); return; }
  }
}

void renderGameMenuLegacy() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX,CY,231,C565(0xe8,0xf4,0xf2));
  uiPrintCenter(koOr("놀이 선택","PLAY"), 46, UI_INK, 3);
  if (gameMenuPage==0) {
    uiPrintCenter(koOr("포켓몬과 함께 놀아봐!","Choose a game"), 80, UI_TRACK, gLang==LANG_KO?2:1);
    gameCard(58,108,164,110,C565(0xff,0xb0,0x67),koOr("공놀이","BALL"),0);
    gameCard(244,108,164,110,C565(0xff,0xdf,0x69),koOr("피카츄 잡기","PIKACHU"),1);
    gameCard(58,238,164,110,C565(0x8f,0xb8,0xff),koOr("포켓몬 VS","POKEMON VS"),2);
    gameCard(244,238,164,110,C565(0xc7,0xb5,0xff),koOr("151 퀴즈","151 QUIZ"),3);
    gfx->fillRoundRect(128,372,210,48,24,C565(0x2f,0x48,0x5a));
    uiPrintCenter(koOr("다음 게임 >","MORE >"),382,UI_WHITE,2);
  } else {
    uiPrintCenter(koOr("새로운 놀이","MORE GAMES"), 82, UI_TRACK, 2);
    gameCard(82,124,302,150,C565(0x79,0xd6,0xc4),koOr("몬스터볼 캐치","MONSTER BALL CATCH"),4);
    uiPrintCenter(koOr("볼·열매·사탕을 먹고 돌은 피해!","Catch items, avoid rocks!"),292,UI_INK,gLang==LANG_KO?2:1);
    gfx->fillRoundRect(128,350,210,52,24,C565(0x2f,0x48,0x5a));
    uiPrintCenter(koOr("< 이전 게임","< BACK"),362,UI_WHITE,2);
  }
  uiPrintCenter(koOr("위쪽 터치 = 나가기","Tap top = exit"), 430, UI_TRACK, 1);
  gfx->flush();
}

// ---------- 피카츄 잡기: 12칸 / 5단계 ----------
static const int16_t MOLE_X[12] = {88,185,281,378, 88,185,281,378, 88,185,281,378};
static const int16_t MOLE_Y[12] = {174,174,174,174, 258,258,258,258, 342,342,342,342};

static uint16_t moleStageGap() {
  static const uint16_t GAP[5] = {900,720,560,430,320};
  uint8_t st = moleStage<1?1:(moleStage>5?5:moleStage);
  return GAP[st-1];
}

static void molePickNew() {
  int8_t old=moleHole;
  do { moleHole=random(12); } while(moleHole==old);
  moleNextAt=millis()+moleStageGap();
}

void startMole() {
  moleOpen=true; catchOpen=false; moleScore=0; moleStage=1; moleStageHits=0; moleNewHi=false;
  moleHole=random(12); moleNextAt=millis()+moleStageGap(); moleResultUntil=0;
  moleStageBannerUntil=millis()+1100;
  miniOpponentPmd.unload(); miniOpponentPmd.load(25,false); // Pikachu from SD
  sfxPlay(SFX_GAME_START);
}

void moleTap(int16_t x, int16_t y) {
  if (y < 72) { moleOpen=false; miniOpponentPmd.unload(); return; }
  if (moleResultUntil || moleStageBannerUntil>millis()) return;
  if (moleHole>=0) {
    int dx=x-MOLE_X[moleHole], dy=y-MOLE_Y[moleHole];
    if (dx*dx + dy*dy < 40*40) {
      moleScore++; moleStageHits++;
      uint8_t sid=(moleScore%3==1)?SFX_MOLE_HIT1:(moleScore%3==2)?SFX_MOLE_HIT2:SFX_MOLE_HIT3;
      sfxPlay(sid);
      if (moleStageHits>=12) {
        if (moleStage>=5) {
          moleNewHi=moleScore>pet.moleHi;
          if(moleNewHi) pet.moleHi=moleScore;
          pet.minigameReward(moleScore);
          sfxPlay(SFX_MEDAL);
          moleResultUntil=millis()+4200;
          return;
        }
        moleStage++; moleStageHits=0;
        moleStageBannerUntil=millis()+1000;
        sfxPlay(SFX_LEVEL);
      }
      molePickNew();
      return;
    }
  }
  sfxPlay(SFX_MOLE_MISS);
}

static void drawPikachuFallback(int cx,int cy) {
  uint16_t yel=C565(0xf7,0xd8,0x43), red=C565(0xef,0x4d,0x4d);
  gfx->fillTriangle(cx-23,cy-18,cx-15,cy-49,cx-6,cy-17,yel);
  gfx->fillTriangle(cx+23,cy-18,cx+15,cy-49,cx+6,cy-17,yel);
  gfx->fillTriangle(cx-21,cy-34,cx-15,cy-49,cx-11,cy-30,UI_INK);
  gfx->fillTriangle(cx+21,cy-34,cx+15,cy-49,cx+11,cy-30,UI_INK);
  gfx->fillCircle(cx,cy,25,yel);
  gfx->fillCircle(cx-8,cy-5,3,UI_INK); gfx->fillCircle(cx+8,cy-5,3,UI_INK);
  gfx->fillCircle(cx-17,cy+8,5,red); gfx->fillCircle(cx+17,cy+8,5,red);
  gfx->fillTriangle(cx,cy+1,cx-3,cy+5,cx+3,cy+5,UI_INK);
}

void renderMole() {
  uint32_t now=millis();
  if (moleResultUntil) {
    gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xff,0xf4,0xc8));
    uiPrintCenter(koOr("피카츄 잡기 완료!","PIKACHU CLEAR!"),76,UI_INK,3);
    uiPrintCenter(koOr("5단계 ALL CLEAR","STAGE 5 ALL CLEAR"),132,UI_BAR_OK,2);
    char b[32]; snprintf(b,sizeof(b),koOr("총 포획 %u","TOTAL %u"),moleScore); uiPrintCenter(b,190,UI_INK,3);
    if(miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd,miniOpponentPmd.has(PMD_POSE)?PMD_POSE:PMD_IDLE,CX,360,now,true,false,3);
    else drawPikachuFallback(CX,292);
    if(moleNewHi) uiPrintCenter(koOr("신기록!","NEW RECORD!"),370,UI_BAR_WARN,2);
    gfx->flush(); return;
  }

  if(moleStageBannerUntil && now<moleStageBannerUntil) {
    gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xff,0xee,0x9b));
    char st[24]; snprintf(st,sizeof(st),koOr("STAGE %u / 5","STAGE %u / 5"),moleStage);
    uiPrintCenter(st,110,UI_INK,4);
    uiPrintCenter(moleStage==1?koOr("12마리 잡으면 다음 단계!","CATCH 12!"):koOr("속도 UP!","SPEED UP!"),185,UI_BAR_WARN,3);
    if(miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd,miniOpponentPmd.has(PMD_HOP)?PMD_HOP:PMD_IDLE,CX,365,now,true,false,3);
    else drawPikachuFallback(CX,292);
    gfx->flush(); return;
  }
  // 짧은 등장 효과음: 자동으로 새 피카츄가 나타날 때만 재생한다.
  // 타격음과 겹치지 않게 성공 터치 뒤의 molePickNew()에는 추가하지 않는다.

  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xc7,0xec,0xff));
  gfx->fillRoundRect(34,103,398,292,28,C565(0x78,0xc9,0x78));
  gfx->drawRoundRect(34,103,398,292,28,C565(0x39,0x78,0x43));
  for(int i=0;i<12;i++){
    int cx=MOLE_X[i], cy=MOLE_Y[i];
    gfx->fillRoundRect(cx-34,cy-10,68,22,11,C565(0x52,0x35,0x27));
    gfx->drawRoundRect(cx-34,cy-10,68,22,11,C565(0x2d,0x21,0x1c));
    if(i==moleHole) {
      if(miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd,PMD_IDLE,cx,cy+22,now,true,false,2);
      else drawPikachuFallback(cx,cy-20);
    }
  }
  char st[24],hit[24],sc[24];
  snprintf(st,sizeof(st),"STAGE %u/5",moleStage);
  snprintf(hit,sizeof(hit),koOr("포획 %u/12","CATCH %u/12"),moleStageHits);
  snprintf(sc,sizeof(sc),koOr("점수 %u","SCORE %u"),moleScore);
  uiPrintAt(st,50,50,UI_INK,2); uiPrintAt(hit,284,50,UI_INK,2);
  uiPrintCenter(sc,78,UI_INK,2);
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
  catchOpen=false; rpsOpen=true; rpsRound=rpsWins=rpsLosses=rpsDraws=0; rpsPlayer=rpsCpu=-1;
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
  if(rpsResultUntil){
    gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xe9,0xef,0xff));
    uiPrintCenter(koOr("포켓몬 VS 결과","POKEMON VS RESULT"),60,UI_INK,3);
    char a[32]; snprintf(a,sizeof(a),koOr("승 %u  무 %u  패 %u","W %u  D %u  L %u"),rpsWins,rpsDraws,rpsLosses); uiPrintCenter(a,118,UI_INK,2);
    char b[28]; snprintf(b,sizeof(b),koOr("최고 승리 %u/5","BEST %u/5"),pet.rpsHi); uiPrintCenter(b,158,UI_TRACK,2);
    if(pmd.loaded) drawPmdAct(pmd.has(PMD_POSE)?PMD_POSE:PMD_IDLE,135,350,now,true,false,3);
    if(miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd,miniOpponentPmd.has(PMD_POSE)?PMD_POSE:PMD_IDLE,331,350,now,true,false,3);
    gfx->fillCircle(CX,258,34,C565(0x2d,0x3b,0x54)); uiPrintCenter("VS",246,UI_WHITE,2);
    if(rpsNewHi) uiPrintCenter(koOr("신기록!","NEW RECORD!"),372,UI_BAR_WARN,2);
    gfx->flush(); return;
  }

  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xe6,0xf1,0xff));
  uiPrintCenter(koOr("포켓몬 VS","POKEMON VS"),34,UI_INK,3);
  char st[36]; snprintf(st,sizeof(st),koOr("라운드 %u/5   승%u 패%u","ROUND %u/5   W%u L%u"),rpsRound+1>5?5:rpsRound+1,rpsWins,rpsLosses);
  gfx->fillRoundRect(92,70,282,35,18,C565(0x2e,0x48,0x66));
  uiPrintCenter(st,78,UI_WHITE,gLang==LANG_KO?2:1);

  // Two clear battle cards: current raised pet on the left, one opponent on the right.
  gfx->fillRoundRect(34,116,184,190,22,UI_WHITE); gfx->drawRoundRect(34,116,184,190,22,C565(0x6b,0x92,0xc4));
  gfx->fillRoundRect(248,116,184,190,22,UI_WHITE); gfx->drawRoundRect(248,116,184,190,22,C565(0xc9,0x78,0x78));
  const char *myName=pet.nick[0]?pet.nick:localizedPokeName(pet.speciesId);
  const char *foeName=localizedPokeName(rpsOpponentDex);
  uint8_t myFs=uiTextWidth(myName,2)<164?2:1, foeFs=uiTextWidth(foeName,2)<164?2:1;
  uiPrintAt(myName,126-uiTextWidth(myName,myFs)/2,128,UI_INK,myFs);
  uiPrintAt(foeName,340-uiTextWidth(foeName,foeFs)/2,128,UI_INK,foeFs);
  uiPrintAt(koOr("내 포켓몬","MY PET"),82,158,UI_TRACK,1);
  uiPrintAt(koOr("상대","RIVAL"),315,158,UI_TRACK,1);
  if(!drawCurrentPetMini(126,286,now,3)){gfx->fillCircle(126,224,38,C565(0xee,0xf2,0xf5)); uiPrintAt("?",117,210,UI_INK,4);}
  if(!drawOpponentMini(rpsOpponentDex,340,286,now,3)){gfx->fillCircle(340,224,38,C565(0xee,0xf2,0xf5)); uiPrintAt("?",331,210,UI_INK,4); const char *miss=sdReady?koOr("이미지 없음","NO IMAGE"):koOr("SD 필요","NEED SD"); uiPrintAt(miss,340-uiTextWidth(miss,1)/2,270,UI_TRACK,1);}
  gfx->fillCircle(CX,206,31,C565(0x2e,0x3b,0x54)); uiPrintCenter("VS",195,UI_WHITE,2);

  if(rpsRevealUntil && rpsPlayer>=0){
    gfx->fillCircle(126,282,25,C565(0x3e,0x5f,0x84)); drawRpsIcon(126,277,rpsPlayer,UI_WHITE);
    gfx->fillCircle(340,282,25,C565(0x84,0x48,0x48)); drawRpsIcon(340,277,rpsCpu,UI_WHITE);
  }
  const int bx[3]={42,181,320}; const uint16_t bc[3]={C565(0xf3,0x8b,0x67),C565(0x77,0xb8,0xf2),C565(0xf2,0xc6,0x62)};
  const char* lab[3]={koOr("바위","ROCK"),koOr("가위","SCISSORS"),koOr("보","PAPER")};
  for(int i=0;i<3;i++){
    gfx->fillRoundRect(bx[i]+3,337,104,78,16,C565(0xa8,0xb4,0xbf));
    gfx->fillRoundRect(bx[i],332,104,78,16,bc[i]); gfx->drawRoundRect(bx[i],332,104,78,16,UI_INK);
    drawRpsIcon(bx[i]+52,354,i,UI_INK);
    uint8_t fs=gLang==LANG_KO?2:1; uiPrintAt(lab[i],bx[i]+(104-uiTextWidth(lab[i],fs))/2,384,UI_INK,fs);
  }
  gfx->flush();
}

// ---------- 151 포켓몬 그림 퀴즈 ----------
static const uint16_t QUIZ151_ORDER[151] = {4,25,7,1,133,52,39,54,143,10,16,19,37,58,60,74,92,129,147,151,6,9,3,26,134,135,136,131,130,149,150,105,34,97,69,36,28,18,61,84,121,138,140,14,80,101,51,46,57,20,148,70,106,5,17,79,42,89,55,41,78,102,44,112,8,66,71,50,137,11,65,67,68,96,90,62,22,75,77,125,142,141,113,116,127,94,12,47,98,124,32,144,132,119,76,82,2,123,27,128,108,100,99,115,122,63,53,30,91,114,48,13,95,49,110,38,56,111,103,120,33,88,85,43,73,145,87,117,139,81,59,31,86,118,40,104,21,24,29,45,107,35,146,83,109,72,93,64,15,23,126};
static const char *const QUIZ151_NAMES[151] = {
  "이상해씨",
  "이상해풀",
  "이상해꽃",
  "파이리",
  "리자드",
  "리자몽",
  "꼬부기",
  "어니부기",
  "거북왕",
  "캐터피",
  "단데기",
  "버터플",
  "뿔충이",
  "딱충이",
  "독침붕",
  "구구",
  "피죤",
  "피죤투",
  "꼬렛",
  "레트라",
  "깨비참",
  "깨비드릴조",
  "아보",
  "아보크",
  "피카츄",
  "라이츄",
  "모래두지",
  "고지",
  "니드런F",
  "니드리나",
  "니드퀸",
  "니드런M",
  "니드리노",
  "니드킹",
  "삐삐",
  "픽시",
  "식스테일",
  "나인테일",
  "푸린",
  "푸크린",
  "주뱃",
  "골뱃",
  "뚜벅쵸",
  "냄새꼬",
  "라플레시아",
  "파라스",
  "파라섹트",
  "콘팡",
  "도나리",
  "디그다",
  "닥트리오",
  "나옹",
  "페르시온",
  "고라파덕",
  "골덕",
  "망키",
  "성원숭",
  "가디",
  "윈디",
  "발챙이",
  "슈륙챙이",
  "강챙이",
  "캐이시",
  "윤겔라",
  "후딘",
  "알통몬",
  "근육몬",
  "괴력몬",
  "모다피",
  "우츠동",
  "우츠보트",
  "왕눈해",
  "독파리",
  "꼬마돌",
  "데구리",
  "딱구리",
  "포니타",
  "날쌩마",
  "야돈",
  "야도란",
  "코일",
  "레어코일",
  "파오리",
  "두두",
  "두트리오",
  "쥬쥬",
  "쥬레곤",
  "질퍽이",
  "질뻐기",
  "셀러",
  "파르셀",
  "고오스",
  "고우스트",
  "팬텀",
  "롱스톤",
  "슬리프",
  "슬리퍼",
  "크랩",
  "킹크랩",
  "찌리리공",
  "붐볼",
  "아라리",
  "나시",
  "탕구리",
  "텅구리",
  "시라소몬",
  "홍수몬",
  "내루미",
  "또가스",
  "또도가스",
  "뿔카노",
  "코뿌리",
  "럭키",
  "덩쿠리",
  "캥카",
  "쏘드라",
  "시드라",
  "콘치",
  "왕콘치",
  "별가사리",
  "아쿠스타",
  "마임맨",
  "스라크",
  "루주라",
  "에레브",
  "마그마",
  "쁘사이저",
  "켄타로스",
  "잉어킹",
  "갸라도스",
  "라프라스",
  "메타몽",
  "이브이",
  "샤미드",
  "쥬피썬더",
  "부스터",
  "폴리곤",
  "암나이트",
  "암스타",
  "투구",
  "투구푸스",
  "프테라",
  "잠만보",
  "프리져",
  "썬더",
  "파이어",
  "미뇽",
  "신뇽",
  "망나뇽",
  "뮤츠",
  "뮤"
};

static uint16_t quizWrapDex(int v) {
  while (v < 1) v += 151;
  while (v > 151) v -= 151;
  return (uint16_t)v;
}

static const char *quiz151Name(uint16_t dex) {
  return (dex >= 1 && dex <= 151) ? QUIZ151_NAMES[dex - 1] : "?";
}

static uint8_t quiz151CountdownSec(uint16_t level) {
  if (level <= 1) return 5;       // Lv.1: 5-4-3-2-1
  if (level <= 40) return 3;      // Lv.2~40: 3-2-1
  if (level <= 100) return 2;
  return 1;
}

static void quiz151BuildChoices() {
  uint16_t a, b;
  if (quizLevel <= 20) {
    a = quizWrapDex((int)quizTargetDex + 47);
    b = quizWrapDex((int)quizTargetDex + 89);
  } else if (quizLevel <= 80) {
    a = quizWrapDex((int)quizTargetDex + ((quizLevel & 1) ? 1 : -1));
    b = quizWrapDex((int)quizTargetDex + 53);
  } else {
    // Late game deliberately uses nearby dex entries more often, which frequently
    // places evolution-family or visually similar names together.
    a = quizWrapDex((int)quizTargetDex - 1);
    b = quizWrapDex((int)quizTargetDex + 1);
  }
  if (a == quizTargetDex) a = quizWrapDex((int)a + 7);
  if (b == quizTargetDex || b == a) b = quizWrapDex((int)b + 11);
  if (b == quizTargetDex || b == a) b = quizWrapDex((int)b + 17);

  quizCorrectSlot = (uint8_t)random(3);
  uint8_t j = 0;
  for (uint8_t i = 0; i < 3; ++i) {
    if (i == quizCorrectSlot) quizChoices[i] = quizTargetDex;
    else quizChoices[i] = (j++ == 0) ? a : b;
  }
}

static void quiz151PrepareLevel() {
  if (quizLevel < 1) quizLevel = 1;
  if (quizLevel > 151) quizLevel = 151;
  const uint16_t previousDex = quizTargetDex;
  do { quizTargetDex = (uint16_t)(1 + random(151)); } while (quizTargetDex == previousDex);
  quiz151BuildChoices();
  miniOpponentPmd.unload();
  miniOpponentPmd.load(quizTargetDex, false);
  quizFeedbackUntil = 0;
  quizWasCorrect = false;
  quizCountdownEnd = millis() + (uint32_t)quiz151CountdownSec(quizLevel) * 1000UL;
}

void startQuiz151() {
  if (pet.isEgg() || pet.sleeping || pet.ceremony) return;
  quizOpen = true;
  gameMenuOpen = gameOpen = moleOpen = rpsOpen = catchOpen = sackOpen = false;
  quizLevel = pet.quizLv;
  if (quizLevel < 1 || quizLevel > 151) quizLevel = 1;
  quizCompleted = false;
  quiz151PrepareLevel();
  sfxPlay(SFX_GAME_START);
}

void quiz151Tap(int16_t x, int16_t y) {
  if (y < 72) { quizOpen = false; miniOpponentPmd.unload(); return; }
  uint32_t now = millis();
  if (quizFeedbackUntil || now < quizCountdownEnd) return;
  if (!miniOpponentPmd.loaded) return;
  if (y < 326 || y > 418) return;

  int8_t pick = -1;
  if (x >= 28 && x <= 150) pick = 0;
  else if (x >= 172 && x <= 294) pick = 1;
  else if (x >= 316 && x <= 438) pick = 2;
  if (pick < 0) return;

  if (quizChoices[pick] == quizTargetDex) {
    quizWasCorrect = true;
    sfxPlay(SFX_RPS_WIN);
    if (quizLevel >= 151) {
      quizCompleted = true;
      pet.setQuizLevel(151);
      pet.minigameReward(20);
      quizFeedbackUntil = now + 3600;
    } else {
      ++quizLevel;
      pet.setQuizLevel(quizLevel);
      quizFeedbackUntil = now + 1100;
    }
  } else {
    quizWasCorrect = false;
    // 서바이벌 규칙: 한 문제라도 틀리면 저장 진행도까지 Lv.1로 초기화.
    // 피드백 화면에서는 방금 틀린 레벨/포켓몬을 보여주고, 종료 후 Lv.1부터 재시작한다.
    pet.setQuizLevel(1);
    sfxPlay(SFX_RPS_LOSE);
    quizFeedbackUntil = now + 1500;
  }
}

void renderQuiz151() {
  uint32_t now = millis();
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, C565(0xef,0xf4,0xff));
  uiPrintCenter(koOr("151 포켓몬 퀴즈","151 POKEMON QUIZ"), 38, UI_INK, 3);
  char hdr[28];
  snprintf(hdr, sizeof(hdr), "Lv.%u / 151", (unsigned)quizLevel);
  uiPrintCenter(hdr, 78, UI_INK, 2);

  if (quizFeedbackUntil) {
    if (quizCompleted) {
      uiPrintCenter(koOr("151마리 마스터!","151 MASTER!"), 154, UI_BAR_WARN, 3);
      uiPrintCenter(koOr("모든 레벨 완료!","ALL LEVELS CLEAR"), 214, UI_INK, 2);
      if (miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd, PMD_IDLE, CX, 360, now, true, false, 4);
    } else if (quizWasCorrect) {
      uiPrintCenter(koOr("정답! 다음 레벨!","CORRECT! NEXT!"), 150, UI_BAR_OK, 3);
      uiPrintCenter(quiz151Name(quizTargetDex), 214, UI_INK, 3);
    } else {
      uiPrintCenter(koOr("틀렸어요! 처음부터!","WRONG! BACK TO LV.1"), 150, UI_BAR_WARN, 3);
      uiPrintCenter(quiz151Name(quizTargetDex), 214, UI_INK, 3);
    }
    gfx->flush();
    return;
  }

  if (now < quizCountdownEnd) {
    uint32_t leftMs = quizCountdownEnd - now;
    uint8_t sec = (uint8_t)((leftMs + 999) / 1000);
    uiPrintCenter(koOr("그림을 잘 봐!","GET READY!"), 136, UI_INK, 2);
    char c[4]; snprintf(c, sizeof(c), "%u", sec);
    uiPrintCenter(c, 204, UI_BAR_WARN, 6);
    uiPrintCenter(koOr("위쪽을 누르면 나가기","Tap top to exit"), 382, UI_TRACK, 1);
    gfx->flush();
    return;
  }

  uiPrintCenter(koOr("이 포켓몬은 누구?","WHO IS THIS?"), 112, UI_INK, 2);
  if (miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd, PMD_IDLE, CX, 302, now, true, false, 5);
  else {
    gfx->fillCircle(CX, 212, 50, UI_WHITE); uiPrintAt("?", CX-12, 192, UI_INK, 5);
    uiPrintCenter(sdReady ? koOr("포켓몬 이미지 파일 없음","POKEMON IMAGE MISSING") : koOr("SD 카드가 필요해요","SD CARD REQUIRED"), 282, UI_BAR_WARN, 2);
    uiPrintCenter(koOr("이미지를 준비한 뒤 다시 도전해줘","Prepare images and try again"), 322, UI_TRACK, 1);
    uiPrintCenter(koOr("위쪽 터치 = 나가기","Tap top = exit"), 388, UI_TRACK, 1);
    gfx->flush(); return;
  }

  const int bx[3] = {28,172,316};
  const int bw = 122, by = 326, bh = 92;
  const uint16_t bc[3] = {C565(0xff,0xc7,0x72), C565(0x8d,0xd8,0xa0), C565(0x9e,0xc5,0xff)};
  for (uint8_t i=0; i<3; ++i) {
    gfx->fillRoundRect(bx[i], by, bw, bh, 15, bc[i]);
    gfx->drawRoundRect(bx[i], by, bw, bh, 15, UI_INK);
    const char *nm = quiz151Name(quizChoices[i]);
    uint8_t fs = uiTextWidth(nm, 2) <= bw-10 ? 2 : 1;
    uiPrintAt(nm, bx[i] + (bw-uiTextWidth(nm,fs))/2, by + (fs==2 ? 31 : 38), UI_INK, fs);
  }
  gfx->flush();
}

// ---------- 몬스터볼 캐치 / 아이템 먹기 ----------
enum : uint8_t { CATCH_BALL=0, CATCH_SUPER, CATCH_HYPER, CATCH_BERRY, CATCH_CANDY, CATCH_ROCK };

static uint8_t catchSpeed() {
  uint8_t v=5 + catchScore/10;
  return v>11?11:v;
}

static void catchSpawnItem() {
  catchItemX=random(70,397); catchItemY=88;
  int r=random(100);
  if(r<42) catchItemType=CATCH_BALL;
  else if(r<62) catchItemType=CATCH_SUPER;
  else if(r<76) catchItemType=CATCH_HYPER;
  else if(r<88) catchItemType=CATCH_BERRY;
  else if(r<95) catchItemType=CATCH_CANDY;
  else catchItemType=CATCH_ROCK;
}

void startMonsterCatch() {
  if (pet.isEgg() || pet.sleeping || pet.ceremony) return;
  catchOpen=true; gameMenuOpen=gameOpen=moleOpen=rpsOpen=quizOpen=sackOpen=false;
  miniOpponentPmd.unload();
  catchPetX=CX; catchScore=0; catchLives=3; catchResultUntil=0;
  catchEndAt=millis()+35000UL; catchLastStep=millis(); catchNewHi=false;
  catchSpawnItem();
  sfxPlay(SFX_GAME_START);
}

void monsterCatchMove(int16_t x) {
  if(x<72) x=72; if(x>394) x=394; catchPetX=x;
}

static void drawCatchBall(int x,int y,uint8_t type) {
  if(type==CATCH_BERRY){
    gfx->fillCircle(x-7,y+2,10,C565(0xb4,0x52,0xb9)); gfx->fillCircle(x+7,y+2,10,C565(0x9b,0x43,0xaa));
    gfx->fillCircle(x,y-6,9,C565(0xc4,0x62,0xc8)); gfx->fillRect(x-2,y-18,4,8,C565(0x43,0x8e,0x4e));
    return;
  }
  if(type==CATCH_CANDY){
    gfx->fillCircle(x,y,12,C565(0xff,0xb4,0x5f));
    gfx->fillTriangle(x-11,y,x-23,y-10,x-23,y+10,C565(0x78,0xc6,0xed));
    gfx->fillTriangle(x+11,y,x+23,y-10,x+23,y+10,C565(0x78,0xc6,0xed));
    gfx->fillCircle(x-4,y-4,3,UI_WHITE); return;
  }
  if(type==CATCH_ROCK){
    gfx->fillCircle(x,y,16,C565(0x75,0x7b,0x82)); gfx->drawCircle(x,y,16,UI_INK);
    gfx->drawLine(x-8,y-8,x+8,y+8,UI_INK); gfx->drawLine(x+8,y-8,x-8,y+8,UI_INK); return;
  }
  uint16_t col= type==CATCH_BALL?C565(0xee,0x4f,0x4f):(type==CATCH_SUPER?C565(0x44,0x8f,0xe6):C565(0xf0,0xc4,0x3e));
  gfx->fillCircle(x,y,17,UI_WHITE); gfx->fillCircle(x,y-3,15,col);
  gfx->fillRect(x-16,y,32,6,UI_INK); gfx->fillCircle(x,y+3,6,UI_INK); gfx->fillCircle(x,y+3,3,UI_WHITE);
  if(type==CATCH_SUPER){gfx->fillRect(x-12,y-10,5,7,C565(0xe9,0x53,0x53)); gfx->fillRect(x+7,y-10,5,7,C565(0xe9,0x53,0x53));}
  if(type==CATCH_HYPER){gfx->fillRect(x-10,y-13,5,9,UI_INK); gfx->fillRect(x+5,y-13,5,9,UI_INK);}
}

static uint8_t catchValue(uint8_t type) {
  if(type==CATCH_BALL) return 1; if(type==CATCH_SUPER) return 2; if(type==CATCH_HYPER) return 3;
  if(type==CATCH_BERRY) return 2; if(type==CATCH_CANDY) return 4; return 0;
}

static void catchFinish(uint32_t now) {
  if(catchResultUntil) return;
  catchNewHi=catchScore>pet.catchHi; if(catchNewHi) pet.catchHi=catchScore;
  pet.minigameReward(catchScore);
  sfxPlay(catchNewHi && catchScore?SFX_MEDAL:SFX_GAME_OVER);
  catchResultUntil=now+4200;
}

void renderMonsterCatch() {
  uint32_t now=millis();
  if(catchResultUntil){
    gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xe7,0xf8,0xf1));
    uiPrintCenter(koOr("몬스터볼 캐치 결과","CATCH RESULT"),70,UI_INK,3);
    char sc[28]; snprintf(sc,sizeof(sc),koOr("점수 %u","SCORE %u"),catchScore); uiPrintCenter(sc,150,UI_INK,4);
    char hi[28]; snprintf(hi,sizeof(hi),koOr("최고 %u","BEST %u"),pet.catchHi); uiPrintCenter(hi,218,UI_INK,2);
    if(catchNewHi) uiPrintCenter(koOr("신기록!","NEW RECORD!"),270,UI_BAR_WARN,2);
    if(!drawCurrentPetMini(CX,390,now,3)){gfx->fillCircle(CX,330,34,UI_WHITE); uiPrintAt("?",CX-8,316,UI_INK,4);}
    gfx->flush(); return;
  }
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xd7,0xef,0xff));
  gfx->fillRoundRect(28,103,410,300,30,C565(0xb7,0xe5,0xc2));
  // subtle lane dots make movement/speed easier to read without clutter.
  for(int xx=70;xx<=390;xx+=64) gfx->fillCircle(xx,150,3,C565(0x91,0xc9,0x9d));
  uiPrintCenter(koOr("몬스터볼 캐치","MONSTER BALL CATCH"),38,UI_INK,3);
  uint32_t left=(catchEndAt-now+999)/1000;
  char sc[20],tm[16]; snprintf(sc,sizeof(sc),koOr("점수 %u","SCORE %u"),catchScore); snprintf(tm,sizeof(tm),"%lus",(unsigned long)left);
  uiPrintAt(sc,48,76,UI_INK,2); uiPrintAt(tm,382-uiTextWidth(tm,2),76,UI_INK,2);
  for(uint8_t i=0;i<3;i++){uint16_t c=i<catchLives?C565(0xef,0x5b,0x67):C565(0xb9,0xc1,0xc8); gfx->fillCircle(202+i*29,83,8,c);}
  drawCatchBall(catchItemX,catchItemY,catchItemType);
  if(!drawCurrentPetMini(catchPetX,414,now,2)){gfx->fillCircle(catchPetX,382,28,UI_WHITE); uiPrintAt("?",catchPetX-7,370,UI_INK,3);}
  gfx->flush();
}


// ============================================================================
// 2.2 ARCADE PACK: Tetris / Snake / Minesweeper
// Progressive difficulty is stage-based in all three games.
// ============================================================================

static void arcCloseAll() {
  arcMenuOpen=arcTetrisOpen=arcSnakeOpen=arcMineOpen=false;
}

static void comboFinalTextIn(const char *text, int x, int y, int w, uint16_t color, uint8_t preferred) {
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

void gameMenuTap(int16_t x, int16_t y) {
  lastInteract = millis();
  if (y < 78) { gameMenuOpen = false; return; }
  if (x >= 42 && x <= 222 && y >= 104 && y <= 198) { gameMenuOpen=false; startGame(); sfxPlay(SFX_GAME_START); return; }
  if (x >= 244 && x <= 424 && y >= 104 && y <= 198) { gameMenuOpen=false; startMole(); return; }
  if (x >= 42 && x <= 222 && y >= 210 && y <= 304) { gameMenuOpen=false; startRps(); return; }
  if (x >= 244 && x <= 424 && y >= 210 && y <= 304) { gameMenuOpen=false; startQuiz151(); return; }
  if (x >= 68 && x <= 398 && y >= 316 && y <= 360) { gameMenuOpen=false; startMonsterCatch(); return; }
  if (y >= 370 && y <= 418 && x >= 68 && x <= 226) { gameMenuOpen=false; arcMenuOpen=true; sfxPlay(SFX_GAME_OPEN); return; }
  if (y >= 370 && y <= 418 && x >= 238 && x <= 398) { gameMenuOpen=false; startOta(); return; }
}

void renderGameMenu() {
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

  gfx->fillRoundRect(68,370,158,44,13,C565(0x67,0x54,0xc5));
  gfx->drawRoundRect(68,370,158,44,13,UI_WHITE);
  comboFinalTextIn(koOr("아케이드/배틀","ARCADE"),68,383,158,UI_WHITE,1);
  gfx->fillRoundRect(238,370,160,44,13,C565(0x47,0x9d,0x76));
  gfx->drawRoundRect(238,370,160,44,13,UI_WHITE);
  comboFinalTextIn(koOr("Wi-Fi 업데이트","WI-FI UPDATE"),238,383,160,UI_WHITE,1);
  gfx->flush();
}

static void arcPrintCenterIn(const char* text,int x,int y,int w,uint16_t color,uint8_t size) {
  int tw = uiTextWidth(text, size);
  uiPrintAt(text, x + (w - tw) / 2, y, color, size);
}
static void arcCard(int x,int y,int w,int h,uint16_t c,const char* title,const char* sub) {
  gfx->fillRoundRect(x,y,w,h,18,c); gfx->drawRoundRect(x,y,w,h,18,UI_INK);
  uint8_t ts = (uiTextWidth(title,2) <= w-16) ? 2 : 1;
  arcPrintCenterIn(title,x,y+(ts==2?18:23),w,UI_INK,ts);
  arcPrintCenterIn(sub,x+8,y+57,w-16,UI_INK,1);
}

static void arcStartTetris();
static void arcStartSnake();
static void arcStartMine(uint8_t stage);

void arcGameMenuTap(int16_t x,int16_t y) {
  lastInteract=millis();
  if (y < 78) { arcMenuOpen=false; gameMenuOpen=true; return; }
  if (x>=46 && x<=222 && y>=112 && y<=226) { arcStartTetris(); return; }
  if (x>=244 && x<=420 && y>=112 && y<=226) { arcStartSnake(); return; }
  if (x>=72 && x<=394 && y>=246 && y<=350) { arcStartMine(1); return; }
  if (x>=72 && x<=394 && y>=362 && y<=424) { arcMenuOpen=false; startBattle(); return; }
}

void arcRenderMenu() {
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xf1,0xf4,0xfb));
  uiPrintCenter(koOr("포켓 아케이드","POCKET ARCADE"),36,UI_INK,2);
  uiPrintCenter(koOr("게임 또는 통신 배틀을 골라줘!","CHOOSE GAME / BATTLE"),64,UI_TRACK,1);
  arcCard(46,94,176,116,C565(0x9f,0xd2,0xff),koOr("테트리스","TETRIS"),koOr("줄을 지우면 빨라져!","LINES = FASTER"));
  arcCard(244,94,176,116,C565(0xa9,0xe3,0xa6),koOr("지렁이","SNAKE"),koOr("먹으면 더 빨라져!","FOOD = FASTER"));
  arcCard(72,224,322,116,C565(0xff,0xd2,0x8b),koOr("지뢰찾기","MINESWEEPER"),koOr("깨면 지뢰가 늘어!","MORE MINES"));
  gfx->fillRoundRect(72,362,322,62,16,C565(0xff,0xc8,0x5a));
  gfx->drawRoundRect(72,362,322,62,16,C565(0x9a,0x6a,0x20));
  comboFinalTextIn(koOr("통신 배틀","BATTLE"),72,381,322,UI_INK,2);
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
void arcTetrisTap(int16_t x,int16_t y) {
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
}
void arcRenderTetris() {
  uint32_t now=millis();
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
}
static void arcStartSnake(){arcCloseAll();arcSnakeOpen=true;arcSStage=1;arcSScore=0;arcSOver=false;arcSBanner=0;arcSResetStage();sfxPlay(SFX_GAME_START);}
static void arcSMove(){
  int nx=arcSX[0]+arcSDX,ny=arcSY[0]+arcSDY;
  bool eat=(nx==arcSFoodX&&ny==arcSFoodY),hitSelf=false;
  int bodyCheck=arcSLen-(eat?0:1); for(int i=0;i<bodyCheck;i++) if(arcSX[i]==nx&&arcSY[i]==ny){hitSelf=true;break;}
  if(nx<0||nx>=14||ny<0||ny>=14||hitSelf||arcSOnRock(nx,ny)){arcSOver=true;sfxPlay(SFX_GAME_OVER);return;}
  if(eat&&arcSLen<95)arcSLen++;
  for(int i=arcSLen-1;i>0;i--){arcSX[i]=arcSX[i-1];arcSY[i]=arcSY[i-1];}arcSX[0]=nx;arcSY[0]=ny;
  if(eat){arcSEaten++;arcSScore+=10*arcSStage;sfxPlay(SFX_MOLE_HIT2);if(arcSEaten>=arcSGoal()){arcSStage++;arcSBanner=millis()+1100;sfxPlay(SFX_MEDAL);arcSResetStage();}else arcSFood();}
}
void arcSnakeTap(int16_t x,int16_t y){
  lastInteract=millis();if(y<62){arcSnakeOpen=false;arcMenuOpen=true;return;}if(arcSOver){arcStartSnake();return;}
  int dx=x-CX,dy=y-CY;if(abs(dx)>abs(dy)){if(dx>0&&arcSDX!=-1){arcSDX=1;arcSDY=0;}else if(dx<0&&arcSDX!=1){arcSDX=-1;arcSDY=0;}}else{if(dy>0&&arcSDY!=-1){arcSDX=0;arcSDY=1;}else if(dy<0&&arcSDY!=1){arcSDX=0;arcSDY=-1;}}sfxPlay(SFX_TAP);
}
void arcRenderSnake(){
  uint32_t now=millis();
  gfx->fillScreen(RGB565_BLACK);gfx->fillCircle(CX,CY,231,C565(0xd9,0xf1,0xd2));uiPrintCenter(koOr("아보 지렁이","SNAKE"),28,UI_INK,2);
  char h[42];snprintf(h,sizeof(h),koOr("단계 %u  먹이 %u/%u","STAGE %u  FOOD %u/%u"),arcSStage,arcSEaten,arcSGoal());uiPrintCenter(h,57,UI_INK,1);
  const int cs=20,ox=CX-(14*cs)/2,oy=94;gfx->fillRoundRect(ox-6,oy-6,14*cs+12,14*cs+12,14,C565(0x76,0xb7,0x68));
  for(int i=0;i<arcSRocks;i++){int px=ox+arcSRX[i]*cs+cs/2,py=oy+arcSRY[i]*cs+cs/2;gfx->fillRoundRect(px-7,py-7,14,14,4,C565(0x59,0x55,0x55));}
  int fx=ox+arcSFoodX*cs+cs/2,fy=oy+arcSFoodY*cs+cs/2;gfx->fillCircle(fx,fy,7,C565(0xf0,0x42,0x55));gfx->fillRect(fx-1,fy-10,3,4,C565(0x42,0x7d,0x38));
  for(int i=arcSLen-1;i>=0;i--){int px=ox+arcSX[i]*cs+cs/2,py=oy+arcSY[i]*cs+cs/2;uint16_t c=i?C565(0x91,0x55,0xb8):C565(0x6a,0x35,0x95);gfx->fillCircle(px,py,i?7:9,c);if(i==0){gfx->fillCircle(px-3,py-2,2,UI_WHITE);gfx->fillCircle(px+3,py-2,2,UI_WHITE);}}
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
static void arcMFlood(int start){int q[81],qh=0,qt=0;bool queued[81]={0};q[qt++]=start;queued[start]=true;while(qh<qt){int id=q[qh++];if(arcMOpen[id]||arcMFlag[id])continue;arcMOpen[id]=true;if(arcMCount(id))continue;int x=id%arcMN,y=id/arcMN;for(int yy=y-1;yy<=y+1;yy++)for(int xx=x-1;xx<=x+1;xx++)if(xx>=0&&yy>=0&&xx<arcMN&&yy<arcMN){int ni=yy*arcMN+xx;if(!arcMOpen[ni]&&!arcMMine[ni]&&!queued[ni]&&qt<81){queued[ni]=true;q[qt++]=ni;}}}}
static bool arcMCleared(){int open=0;for(int i=0;i<arcMN*arcMN;i++)if(arcMOpen[i])open++;return open==arcMN*arcMN-arcMMines;}
void arcMineTap(int16_t x,int16_t y){
  lastInteract=millis();if(y<60){arcMineOpen=false;arcMenuOpen=true;return;}if(arcMDead){arcMSetupStage(arcMStage);return;}if(arcMClearUntil)return;
  if(y>=66&&y<=104&&x>=150&&x<=316){arcMFlagMode=!arcMFlagMode;sfxPlay(SFX_TAP);return;}
  int cs=(arcMN<=6?38:(arcMN==7?35:(arcMN==8?32:30))),gw=arcMN*cs,ox=CX-gw/2,oy=112;if(x<ox||x>=ox+gw||y<oy||y>=oy+gw)return;int cx=(x-ox)/cs,cy=(y-oy)/cs,id=cy*arcMN+cx;
  if(arcMFlagMode){if(!arcMOpen[id])arcMFlag[id]=!arcMFlag[id];sfxPlay(SFX_TAP);return;}if(arcMFlag[id])return;if(!arcMGenerated)arcMGenerate(id);
  if(arcMMine[id]){arcMDead=true;for(int i=0;i<arcMN*arcMN;i++)if(arcMMine[i])arcMOpen[i]=true;sfxPlay(SFX_GAME_OVER);return;}arcMFlood(id);sfxPlay(SFX_GAME_TICK);if(arcMCleared()){arcMClearUntil=millis()+1300;sfxPlay(SFX_MEDAL);}
}
void arcRenderMine(){
  uint32_t now=millis();
  gfx->fillScreen(RGB565_BLACK);gfx->fillCircle(CX,CY,231,C565(0xf5,0xe6,0xc8));uiPrintCenter(koOr("찌리리공 지뢰찾기","MINESWEEPER"),24,UI_INK,2);
  char h[36];snprintf(h,sizeof(h),koOr("단계 %u  %ux%u  지뢰 %u","STAGE %u  %ux%u  MINES %u"),arcMStage,arcMN,arcMN,arcMMines);uiPrintCenter(h,50,UI_INK,1);
  gfx->fillRoundRect(150,66,166,38,12,arcMFlagMode?C565(0xff,0x9a,0x64):C565(0x83,0xb7,0xe6));arcPrintCenterIn(arcMFlagMode?koOr("깃발 모드","FLAG MODE"):koOr("칸 열기 모드","OPEN MODE"),150,76,166,UI_INK,1);
  int cs=(arcMN<=6?38:(arcMN==7?35:(arcMN==8?32:30))),gw=arcMN*cs,ox=CX-gw/2,oy=112;static const uint16_t nc[9]={UI_TRACK,C565(0x28,0x5d,0xc0),C565(0x2d,0x8d,0x54),C565(0xc2,0x3e,0x3e),C565(0x6f,0x43,0xa3),C565(0xa0,0x54,0x24),C565(0x2a,0x82,0x86),UI_INK,UI_INK};
  for(int y=0;y<arcMN;y++)for(int x=0;x<arcMN;x++){int id=y*arcMN+x,px=ox+x*cs,py=oy+y*cs;if(!arcMOpen[id]){gfx->fillRoundRect(px+1,py+1,cs-2,cs-2,5,C565(0xc8,0xae,0x79));if(arcMFlag[id]){gfx->fillTriangle(px+9,py+8,px+24,py+13,px+9,py+18,C565(0xe7,0x45,0x45));gfx->drawLine(px+9,py+8,px+9,py+26,UI_INK);}}else if(arcMMine[id]){gfx->fillRoundRect(px+1,py+1,cs-2,cs-2,5,C565(0xf0,0x7b,0x62));gfx->fillCircle(px+17,py+17,10,C565(0xd9,0x31,0x31));gfx->fillRect(px+14,py+11,6,12,UI_WHITE);}else{gfx->fillRect(px+1,py+1,cs-2,cs-2,C565(0xf8,0xf0,0xdc));uint8_t c=arcMCount(id);if(c){char b[2]={(char)('0'+c),0};gfx->setTextColor(nc[c]);gfx->setTextSize(2);gfx->setCursor(px+11,py+9);gfx->print(b);}}}
  if(arcMDead){uiPrintCenter(koOr("펑! 눌러서 재도전","BOOM! TAP TO RETRY"),430,UI_BAR_WARN,2);}else if(arcMClearUntil){uiPrintCenter(koOr("클리어! 다음 판은 더 어려워요","CLEAR! NEXT IS HARDER"),430,UI_BAR_OK,2);}else uiPrintCenter(koOr("모드 버튼으로 열기/깃발 전환","BUTTON: OPEN / FLAG"),430,UI_INK,1);gfx->flush();
}


static void battleSend(uint8_t type, int8_t move=-1) {
  if(!battleRadioReady) return;
  BattlePacket p{BATTLE_MAGIC,1,type,battleRound,move,battleSelfId,battlePeerId};
  esp_now_send(battleBroadcast,(const uint8_t*)&p,sizeof(p));
}

static void battleRecvCb(const esp_now_recv_info_t *info,const uint8_t *data,int len) {
  (void)info;
  if(!data || len!=(int)sizeof(BattlePacket)) return;
  BattlePacket p; memcpy(&p,data,sizeof(p));
  if(p.magic!=BATTLE_MAGIC || p.proto!=1 || !p.from) return;
  if(p.type<1 || p.type>4 || (p.type==3 && (p.move<0 || p.move>2))) return;
  portENTER_CRITICAL(&battleRxMux);
  if(battleAcceptRx && p.from!=battleSelfId && (p.target==0 || p.target==battleSelfId) && battleRxCount<4) {
    battleRxQueue[(battleRxHead+battleRxCount)%4]=p;
    ++battleRxCount;
  }
  portEXIT_CRITICAL(&battleRxMux);
}

static void battlePrefsInit() {
  if(battlePrefsReady) return;
  battlePrefsReady=true;
  battlePrefs.begin("tpk-battle",false);
  battleWins=battlePrefs.getUShort("wins",0);
  battleLosses=battlePrefs.getUShort("loss",0);
}

static bool battleRadioStart() {
  WiFi.persistent(false);
  WiFi.setAutoReconnect(false);
  if(!WiFi.mode(WIFI_STA)) return false;
  WiFi.disconnect(false,false);
  WiFi.setSleep(false); // ESP-NOW reception is required only during the battle.
  if(esp_wifi_set_channel(1,WIFI_SECOND_CHAN_NONE)!=ESP_OK) {
    WiFi.mode(WIFI_OFF); return false;
  }
  if(esp_now_init()!=ESP_OK) { WiFi.mode(WIFI_OFF); return false; }
  if(esp_now_register_recv_cb(battleRecvCb)!=ESP_OK) {
    esp_now_deinit(); WiFi.mode(WIFI_OFF); return false;
  }
  esp_now_peer_info_t peer{};
  memcpy(peer.peer_addr,battleBroadcast,6);
  peer.channel=1; peer.ifidx=WIFI_IF_STA; peer.encrypt=false;
  if(!esp_now_is_peer_exist(battleBroadcast) && esp_now_add_peer(&peer)!=ESP_OK) {
    esp_now_unregister_recv_cb(); esp_now_deinit(); WiFi.mode(WIFI_OFF); return false;
  }
  portENTER_CRITICAL(&battleRxMux);
  battleAcceptRx=true;
  portEXIT_CRITICAL(&battleRxMux);
  battleRadioReady=true;
  return true;
}

static void battleRadioStop() {
  portENTER_CRITICAL(&battleRxMux);
  battleAcceptRx=false;
  portEXIT_CRITICAL(&battleRxMux);
  if(battleRadioReady) {
    esp_now_unregister_recv_cb();
    esp_now_deinit();
  }
  battleRadioReady=false;
  portENTER_CRITICAL(&battleRxMux);
  battleRxHead=0; battleRxCount=0;
  portEXIT_CRITICAL(&battleRxMux);
  WiFi.mode(WIFI_OFF);
}

static void battleFinish(int8_t result) {
  if(battleState==2) return; // duplicate/retransmitted moves cannot pay twice.
  battleState=2; battleResult=result; battleRevealUntil=millis()+1200UL;
  battleFinishedAt=millis();
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
  if(battleState!=1 || battleRevealUntil || battleMyMove<0 || battlePeerMove<0) return;
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
  battleProgressAt=millis();
  if(!battleMyHp && !battlePeerHp) battleFinish(0);
  else if(!battlePeerHp) battleFinish(1);
  else if(!battleMyHp) battleFinish(-1);
}

static void battleAbort(const char *reason,uint32_t now) {
  if(battleRadioReady && battlePeerId) battleSend(4);
  battleRadioStop();
  battleState=2; battleStatus=reason; battleFinishedAt=now;
}

static void battlePump(uint32_t now) {
  if(!battleOpen) return;
  if(battleState==2) {
    // A short final-packet grace period lets the peer finish the same round.
    // The result screen itself does not keep the radio running indefinitely.
    if(battleRadioReady) {
      if(now-battleFinishedAt>=BATTLE_RESULT_RADIO_MS) battleRadioStop();
      else if(battleMyMove>=0 && now-battleLastTx>=320UL) {
        battleLastTx=now; battleSend(3,battleMyMove);
      }
    }
    if(now-battleFinishedAt>=BATTLE_RESULT_MS) {
      closeBattle(); gameMenuOpen=true;
    }
    return;
  }
  if(!battleRadioReady) { battleAbort("RADIO ERROR",now); return; }
  for(uint8_t count=0; count<4; ++count) {
    BattlePacket p{}; bool havePacket=false;
    portENTER_CRITICAL(&battleRxMux);
    if(battleRxCount) {
      p=battleRxQueue[battleRxHead]; battleRxHead=(battleRxHead+1)%4;
      --battleRxCount; havePacket=true;
    }
    portEXIT_CRITICAL(&battleRxMux);
    if(!havePacket) break;
    if((p.type==1||p.type==2) && battlePeerId==0) battlePeerId=p.from;
    if(p.type==1 && battlePeerId==p.from) battleSend(2);
    if(p.type==2 && battlePeerId==p.from && battleState==0) {
      battleState=1; battleProgressAt=now;
    }
    if(p.type==3 && battleState==1 && p.from==battlePeerId && p.round==battleRound && battlePeerMove<0) {
      battlePeerMove=p.move; battleProgressAt=now; battleResolveRound();
    }
    if(p.type==4 && p.from==battlePeerId) {
      battleAbort("RIVAL LEFT",now); return;
    }
    if(battleState==2) return;
  }
  if(!battlePeerId) {
    if(now-battleStartedAt>=BATTLE_SEARCH_MS) { battleAbort("SEARCH TIMEOUT",now); return; }
    if(now-battleLastHello>450UL) { battleLastHello=now; battleSend(1); }
  } else if(battleState==0) {
    battleState=1; battleProgressAt=now; battleSend(2);
  }
  if(battleState==1 && now-battleProgressAt>=BATTLE_IDLE_MS) {
    battleAbort("BATTLE IDLE TIMEOUT",now); return;
  }
  if(battleState==1 && battleMyMove>=0 && now-battleLastTx>320UL) {
    battleLastTx=now; battleSend(3,battleMyMove);
  }
  if(battleState==1 && battleRevealUntil && (int32_t)(now-battleRevealUntil)>=0 && battleMyMove>=0 && battlePeerMove>=0) {
    battleRound++; battleMyMove=battlePeerMove=-1; battleRevealUntil=0;
  }
}

static void startBattle() {
  if(otaBusy() || alarmRinging()) return;
  if(otaOpen) closeOta();
  battlePrefsInit();
  battleOpen=true; gameMenuOpen=false;
  battlePeerId=0; battleMyHp=battlePeerHp=5; battleRound=1;
  battleMyMove=battlePeerMove=-1; battleState=0; battleResult=0;
  battleLastHello=battleLastTx=battleRevealUntil=0;
  battleStartedAt=battleProgressAt=millis(); battleFinishedAt=0; battleStatus="";
  portENTER_CRITICAL(&battleRxMux);
  battleRxHead=0; battleRxCount=0;
  portEXIT_CRITICAL(&battleRxMux);
  uint64_t m=ESP.getEfuseMac(); battleSelfId=(uint32_t)(m^(m>>32));
  if(!battleSelfId) battleSelfId=1;
  if(!battleRadioStart()) battleAbort("RADIO ERROR",millis());
  lastInteract=millis(); sfxPlay(SFX_GAME_OPEN);
}

static void closeBattle() {
  if(battlePeerId) battleSend(4);
  battleRadioStop(); battleOpen=false; battlePeerId=0;
  battleMyMove=battlePeerMove=-1; battleState=0; battleStatus="";
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
    if(battleMyMove>=0) {
      battleLastTx=battleProgressAt=millis(); battleSend(3,battleMyMove);
      sfxPlay(SFX_RPS_SELECT); battleResolveRound();
    }
  }
}

static void battleHpBar(int x,int y,uint8_t hp,uint16_t col) {
  gfx->drawRoundRect(x,y,154,18,9,C565(0x55,0x60,0x70));
  for(uint8_t i=0;i<hp && i<5;i++) gfx->fillRoundRect(x+4+i*29,y+4,25,10,5,col);
}

static void renderBattle() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX,CY,231,C565(0xf0,0xf4,0xfa));
  uiPrintCenter(koOr("포켓몬 통신 배틀","POKEMON BATTLE"),32,UI_INK,2);
  uiPrintCenter(koOr("위쪽 터치: 나가기","TOP: EXIT"),56,UI_TRACK,1);
  if(battleStatus[0]) {
    uiPrintCenter(battleStatus,210,UI_INK,1);
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


// ---------- Battery 2.8: bounded, verified Wi-Fi OTA ----------
static const uint16_t OTA_BUILD=280;
static const char *OTA_MANIFEST_URL="https://py2jin-rgb.github.io/tamapoke-ko/ota-latest.json";
static const char *OTA_FIRMWARE_PREFIX="https://py2jin-rgb.github.io/tamapoke-ko/firmware/";
enum : uint8_t { OTA_IDLE=0, OTA_AP=1, OTA_CONNECT=2, OTA_MANIFEST=3,
  OTA_DOWNLOAD=4, OTA_DONE=5, OTA_ERROR=6, OTA_TIME=7, OTA_BINARY=8 };
static const uint32_t OTA_AP_MS=180000UL, OTA_CONNECT_MS=15000UL;
static const uint32_t OTA_RESULT_MS=30000UL, OTA_STALL_MS=12000UL, OTA_TOTAL_MS=180000UL;
static bool otaSetupAp=false, otaHandlersReady=false, otaWriting=false, otaHashReady=false;
static bool otaRestartPending=false;
static uint8_t otaState=OTA_IDLE;
static uint32_t otaStateSince=0, otaLastProgress=0, otaDownloadStarted=0, otaRestartAt=0;
static uint32_t otaApSavedAt=0, otaExpectedSize=0, otaReceived=0;
static String otaMsg="", otaSsid="", otaPass="";
static String otaExpectedSha="", otaUrl="", otaVersion="";
static Preferences otaPrefs;
static bool otaPrefsReady=false;
static WebServer otaServer(80);
static WiFiClientSecure otaBinClient;
static HTTPClient otaBinHttp;
static mbedtls_sha256_context otaHash;

static bool otaFlashBusy(){ return otaWriting; }
static bool otaBusy(){
  return otaState==OTA_CONNECT || otaState==OTA_TIME || otaState==OTA_MANIFEST ||
         otaState==OTA_BINARY || otaState==OTA_DOWNLOAD || otaWriting;
}
static bool radioBusy(){ return battleRadioReady || otaSetupAp || otaBusy(); }

static void otaSetState(uint8_t state,const String &message){
  otaState=state; otaMsg=message; otaStateSince=millis();
}

static void otaPrefsInit(){
  if(otaPrefsReady) return;
  otaPrefsReady=true;
  otaPrefs.begin("tpk-ota",false);
  otaSsid=otaPrefs.getString("ssid","");
  otaPass=otaPrefs.getString("pass","");
}

static void otaWifiOff(){
  // Alarm/navigation callbacks must never tear down an active flash transfer.
  if(otaWriting) return;
  if(otaSetupAp){ otaServer.stop(); otaSetupAp=false; }
  esp_sntp_stop();
  WiFi.softAPdisconnect(true);
  WiFi.disconnect(false,false); // credentials remain in our existing tpk-ota NVS namespace
  WiFi.mode(WIFI_OFF);
}

static void otaReleaseTransfer(bool abortWrite){
  if(abortWrite && otaWriting) Update.abort();
  otaWriting=false;
  if(otaHashReady){ mbedtls_sha256_free(&otaHash); otaHashReady=false; }
  otaBinHttp.end(); otaBinClient.stop();
}

static void otaFail(const String &message){
  // Called only by the transfer state machine, between complete write() calls.
  // An incomplete/integrity-failed inactive slot is discarded; it is never booted.
  otaReleaseTransfer(true);
  otaWifiOff();
  otaSetState(OTA_ERROR,message);
}

static void otaConfigureTls(WiFiClientSecure &client,HTTPClient &http){
  // Arduino-ESP32 3.1.0: setCACertBundle(nullptr,0) DISABLES verification.
  // These non-null symbols reference ESP-IDF's embedded Mozilla root CA bundle,
  // including ISRG Root X1. Hostname and certificate-chain checks remain enabled.
  client.setCACertBundle(otaCaBundleStart,(size_t)(otaCaBundleEnd-otaCaBundleStart));
  client.setHandshakeTimeout(4); // seconds; no unbounded TLS handshake
  http.setConnectTimeout(4000);
  http.setTimeout(2500);
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  http.setReuse(false);
}

static String otaHtml(){
  return String("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>TamaPoke Wi-Fi</title><style>body{font-family:sans-serif;background:#111;color:#fff;max-width:520px;margin:30px auto;padding:20px}input,button{box-sizing:border-box;width:100%;padding:14px;margin:8px 0;border-radius:10px;border:0;font-size:16px}button{background:#ffd36a;font-weight:800}</style></head><body><h2>TamaPoke Wi-Fi 설정</h2><p>집 Wi-Fi 정보를 저장합니다. 저장 후 TamaPoke 화면에서 업데이트 확인을 눌러주세요. 설정 연결은 3분 뒤 자동으로 꺼집니다.</p><form method='POST' action='/save'><input name='ssid' maxlength='32' placeholder='Wi-Fi 이름(SSID)' required><input name='pass' maxlength='64' type='password' placeholder='비밀번호'><button type='submit'>저장</button></form></body></html>");
}

static void otaStartSetupAp(){
  if(otaWriting || alarmRinging()) return;
  otaPrefsInit(); otaWifiOff();
  if(battleOpen) closeBattle();
  WiFi.persistent(false); WiFi.setAutoReconnect(false);
  if(!WiFi.mode(WIFI_AP) || !WiFi.softAP("TamaPoke-Update")){
    otaFail("AP START ERROR"); return;
  }
  if(!otaHandlersReady){
    otaServer.on("/",HTTP_GET,[]{ otaServer.send(200,"text/html; charset=utf-8",otaHtml()); });
    otaServer.on("/save",HTTP_POST,[]{
      String ss=otaServer.arg("ssid"), pw=otaServer.arg("pass");
      if(ss.length()<1 || ss.length()>32 || pw.length()>64){
        otaServer.send(400,"text/plain","Invalid SSID/password length"); return;
      }
      // Do not trim SSIDs: leading/trailing spaces may be legitimate network names.
      otaSsid=ss; otaPass=pw;
      otaPrefs.putString("ssid",otaSsid); otaPrefs.putString("pass",otaPass);
      otaServer.send(200,"text/html; charset=utf-8","<meta charset='utf-8'><h2>저장 완료</h2><p>TamaPoke로 돌아가 업데이트 확인을 눌러주세요. 설정 연결을 종료합니다.</p>");
      otaApSavedAt=millis(); otaMsg="WI-FI SAVED";
    });
    otaHandlersReady=true;
  }
  otaServer.begin(); otaSetupAp=true; otaApSavedAt=0;
  otaSetState(OTA_AP,"TamaPoke-Update / 192.168.4.1");
}

static void otaDoUpdate(){
  if(otaBusy() || otaRestartPending || alarmRinging()) return;
  otaPrefsInit();
  if(otaSsid.length()<1){ otaStartSetupAp(); return; }
  otaWifiOff();
  WiFi.persistent(false); WiFi.setAutoReconnect(false);
  if(!WiFi.mode(WIFI_STA)){ otaFail("WI-FI START FAIL"); return; }
  WiFi.setSleep(true);
  WiFi.begin(otaSsid.c_str(),otaPass.c_str());
  otaSetState(OTA_CONNECT,"CONNECTING...");
}

static void otaJsonSpace(const String &j,size_t &p){
  while(p<j.length() && (j[p]==' ' || j[p]=='\r' || j[p]=='\n' || j[p]=='\t')) ++p;
}
static bool otaJsonString(const String &j,size_t &p,String &out){
  otaJsonSpace(j,p); out="";
  if(p>=j.length() || j[p++]!='"') return false;
  while(p<j.length()){
    char c=j[p++];
    if(c=='"') return true;
    if((uint8_t)c<32) return false;
    if(c=='\\'){
      if(p>=j.length()) return false;
      c=j[p++];
      if(c!='"' && c!='\\' && c!='/') return false;
    }
    if(out.length()>=512) return false;
    out+=c;
  }
  return false;
}
static bool otaJsonUint(const String &j,size_t &p,uint32_t &value){
  otaJsonSpace(j,p); value=0;
  if(p>=j.length() || j[p]<'0' || j[p]>'9') return false;
  const size_t start=p;
  while(p<j.length() && j[p]>='0' && j[p]<='9'){
    uint8_t d=(uint8_t)(j[p++]-'0');
    if(value>(UINT32_MAX-d)/10U) return false;
    value=value*10U+d;
  }
  return !(p-start>1 && j[start]=='0');
}
static bool otaAllowedUrl(const String &url){
  if(!url.startsWith(OTA_FIRMWARE_PREFIX) || !url.endsWith(".bin")) return false;
  String name=url.substring(strlen(OTA_FIRMWARE_PREFIX));
  if(name.length()<5 || name.length()>160 || name.indexOf("..")>=0) return false;
  for(size_t i=0;i<name.length();++i){
    char c=name[i];
    if(!((c>='a'&&c<='z') || (c>='A'&&c<='Z') || (c>='0'&&c<='9') || c=='-' || c=='_' || c=='.')) return false;
  }
  return true;
}
static bool otaParseManifest(const String &json,uint32_t &build){
  size_t p=0; uint8_t seen=0; bool closed=false; build=0;
  otaExpectedSha=""; otaUrl=""; otaVersion=""; otaExpectedSize=0;
  otaJsonSpace(json,p);
  if(p>=json.length() || json[p++]!='{') return false;
  for(uint8_t fields=0; fields<16; ++fields){
    String key,value; uint32_t number=0; uint8_t bit=0;
    if(!otaJsonString(json,p,key)) return false;
    otaJsonSpace(json,p);
    if(p>=json.length() || json[p++]!=':') return false;
    if(key=="build" || key=="size"){
      if(!otaJsonUint(json,p,number)) return false;
      if(key=="build"){bit=1;build=number;} else {bit=2;otaExpectedSize=number;}
    } else {
      if(!otaJsonString(json,p,value)) return false;
      if(key=="version"){bit=4;otaVersion=value;}
      else if(key=="url"){bit=8;otaUrl=value;}
      else if(key=="sha256"){bit=16;otaExpectedSha=value;}
    }
    if(bit && (seen&bit)) return false;
    seen|=bit; otaJsonSpace(json,p);
    if(p>=json.length()) return false;
    char next=json[p++];
    if(next=='}'){ closed=true; break; }
    if(next!=',') return false;
  }
  otaJsonSpace(json,p);
  if(!closed || p!=json.length() || seen!=31 || build==0 || build>65535 || otaExpectedSize==0 ||
     otaVersion.length()==0 || otaVersion.length()>32 || !otaAllowedUrl(otaUrl) || otaExpectedSha.length()!=64) return false;
  for(size_t i=0;i<64;++i){
    char c=otaExpectedSha[i];
    if(c>='A' && c<='F'){ otaExpectedSha.setCharAt(i,c-'A'+'a'); continue; }
    if(!((c>='0'&&c<='9') || (c>='a'&&c<='f'))) return false;
  }
  return true;
}

static void otaReadManifest(){
  WiFiClientSecure client; HTTPClient http;
  otaConfigureTls(client,http);
  if(!http.begin(client,OTA_MANIFEST_URL)){ otaFail("MANIFEST OPEN FAIL"); return; }
  serviceCriticalTasks();
  if(!otaOpen || otaState!=OTA_MANIFEST){ http.end(); return; }
  int code=http.GET();
  serviceCriticalTasks();
  if(!otaOpen || otaState!=OTA_MANIFEST){ http.end(); return; }
  if(code!=HTTP_CODE_OK){ http.end(); otaFail(String("MANIFEST HTTP ")+code); return; }
  const int length=http.getSize();
  if(length<=0 || length>2048){ http.end(); otaFail("MANIFEST SIZE ERROR"); return; }
  String json; json.reserve(length);
  auto *stream=http.getStreamPtr();
  uint32_t started=millis(), progress=started;
  while(json.length()<(size_t)length){
    serviceCriticalTasks();
    if(!otaOpen || otaState!=OTA_MANIFEST){ http.end(); return; }
    int available=stream->available();
    if(available>0){
      char buf[128]; size_t take=(size_t)available;
      if(take>sizeof(buf)) take=sizeof(buf);
      if(take>(size_t)length-json.length()) take=(size_t)length-json.length();
      int got=stream->read((uint8_t*)buf,take);
      if(got>0){ json.concat(buf,(unsigned int)got); progress=millis(); }
    } else if(!http.connected()) break;
    if(millis()-progress>3000UL || millis()-started>10000UL) break;
    delay(1);
  }
  http.end();
  if(json.length()!=(size_t)length){ otaFail("MANIFEST INCOMPLETE"); return; }
  uint32_t build=0;
  if(!otaParseManifest(json,build)){ otaFail("BAD MANIFEST"); return; }
  if(build<=OTA_BUILD){ otaWifiOff(); otaSetState(OTA_DONE,String("LATEST ")+otaVersion); return; }
  const esp_partition_t *slot=esp_ota_get_next_update_partition(nullptr);
  if(!slot || otaExpectedSize>slot->size){ otaFail("OTA SLOT TOO SMALL"); return; }
  otaSetState(OTA_BINARY,String("DOWNLOADING ")+otaVersion);
}

static void otaBeginBinary(){
  otaConfigureTls(otaBinClient,otaBinHttp);
  if(!otaBinHttp.begin(otaBinClient,otaUrl)){ otaFail("BIN OPEN FAIL"); return; }
  serviceCriticalTasks();
  if(!otaOpen || otaState!=OTA_BINARY){ otaReleaseTransfer(false); return; }
  int code=otaBinHttp.GET();
  serviceCriticalTasks();
  if(!otaOpen || otaState!=OTA_BINARY){ otaReleaseTransfer(false); return; }
  if(code!=HTTP_CODE_OK){ otaFail(String("BIN HTTP ")+code); return; }
  int length=otaBinHttp.getSize();
  if(length<=0 || (uint32_t)length!=otaExpectedSize){ otaFail("BIN SIZE MISMATCH"); return; }
  if(!Update.begin((size_t)otaExpectedSize,U_FLASH)){ otaFail("OTA SLOT ERROR"); return; }
  otaWriting=true;
  mbedtls_sha256_init(&otaHash); otaHashReady=true;
  if(mbedtls_sha256_starts(&otaHash,0)!=0){ otaFail("HASH START ERROR"); return; }
  otaReceived=0; otaDownloadStarted=otaLastProgress=millis();
  otaSetState(OTA_DOWNLOAD,String("DOWNLOADING ")+otaVersion);
}

static void otaDownloadChunk(uint32_t now){
  if(now-otaLastProgress>OTA_STALL_MS || now-otaDownloadStarted>OTA_TOTAL_MS){
    otaFail("DOWNLOAD TIMEOUT"); return;
  }
  auto *stream=otaBinHttp.getStreamPtr();
  int available=stream->available();
  if(available>0 && otaReceived<otaExpectedSize){
    uint8_t buf[2048]; size_t take=(size_t)available;
    if(take>sizeof(buf)) take=sizeof(buf);
    if(take>otaExpectedSize-otaReceived) take=otaExpectedSize-otaReceived;
    int got=stream->read(buf,take);
    if(got>0){
      if(mbedtls_sha256_update(&otaHash,buf,(size_t)got)!=0 || Update.write(buf,(size_t)got)!=(size_t)got){
        otaFail("UPDATE WRITE FAIL"); return;
      }
      otaReceived+=(uint32_t)got; otaLastProgress=millis();
      serviceCriticalTasks(); // alarm may ring, but radioOnAlarm preserves this write session
      delay(1);
    }
  }
  if(otaReceived==otaExpectedSize){
    uint8_t digest[32]; char hex[65]; static const char digits[]="0123456789abcdef";
    if(mbedtls_sha256_finish(&otaHash,digest)!=0){ otaFail("HASH FINISH ERROR"); return; }
    for(size_t i=0;i<32;++i){ hex[2*i]=digits[digest[i]>>4]; hex[2*i+1]=digits[digest[i]&15]; }
    hex[64]=0;
    if(otaExpectedSha!=hex){ otaFail("SHA256 MISMATCH"); return; }
    // end() activates the new boot slot: it MUST follow exact-size and SHA-256 checks.
    if(!Update.end(false) || !Update.isFinished()){ otaFail("UPDATE FINALIZE FAIL"); return; }
    otaReleaseTransfer(false); otaWifiOff();
    otaRestartPending=true; otaRestartAt=millis()+1500UL;
    otaSetState(OTA_DONE,"UPDATE OK - RESTART");
  } else if(!otaBinHttp.connected() && stream->available()==0){
    otaFail("BIN INCOMPLETE");
  }
}

static void startOta(){
  if(otaBusy() || otaRestartPending || alarmRinging()) return;
  if(battleOpen) closeBattle();
  otaPrefsInit(); otaOpen=true; gameMenuOpen=false;
  otaSetState(OTA_IDLE,otaSsid.length()?String("SAVED: ")+otaSsid:String("WI-FI SETUP REQUIRED"));
  lastInteract=millis(); sfxPlay(SFX_GAME_OPEN);
}
static void closeOta(){
  if(otaWriting || otaRestartPending) return;
  otaReleaseTransfer(false); otaWifiOff(); otaOpen=false;
  otaSetState(OTA_IDLE,"");
}
static void otaPump(uint32_t now){
  if(otaRestartPending){
    // Snooze lives in RAM too: defer restart until both ringing and snooze finish.
    if(!alarmRinging() && !alarmSnoozing() && (int32_t)(now-otaRestartAt)>=0){
      if(pet.savePending()) pet.flushSave();
      ESP.restart();
    }
    return;
  }
  if(!otaOpen) return;
  if(otaSetupAp){
    otaServer.handleClient();
    now=millis(); // /save may have set otaApSavedAt after this loop's original timestamp.
    if(otaApSavedAt && now-otaApSavedAt>=1000UL){ otaWifiOff(); otaSetState(OTA_IDLE,"WI-FI SAVED"); }
    else if(now-otaStateSince>=OTA_AP_MS){ otaWifiOff(); otaSetState(OTA_ERROR,"SETUP TIMEOUT - WI-FI OFF"); }
    return;
  }
  if(otaState==OTA_CONNECT){
    if(WiFi.status()==WL_CONNECTED){
      // SNTP establishes UTC for TLS only. It never rewrites the user's local RTC/alarm.
      configTime(0,0,"time.cloudflare.com","time.google.com","pool.ntp.org");
      otaSetState(OTA_TIME,"VERIFYING NETWORK TIME...");
    } else if(now-otaStateSince>=OTA_CONNECT_MS) otaFail("WI-FI CONNECT FAIL");
  } else if(otaState==OTA_TIME){
    const time_t utc=time(nullptr);
    if(utc>=1735689600LL && utc<4102444800LL) otaSetState(OTA_MANIFEST,"CHECKING UPDATE...");
    else if(now-otaStateSince>=15000UL) otaFail("UTC TIME SYNC FAIL");
  } else if(otaState==OTA_MANIFEST) otaReadManifest();
  else if(otaState==OTA_BINARY) otaBeginBinary();
  else if(otaState==OTA_DOWNLOAD) otaDownloadChunk(now);
  else if((otaState==OTA_DONE || otaState==OTA_ERROR) && now-otaStateSince>=OTA_RESULT_MS){
    closeOta(); gameMenuOpen=true;
  }
}

static void serviceWireless(uint32_t now){
  battlePump(now);
  otaPump(now);
}
static void radioOnAlarm(){
  if(battleOpen) closeBattle();
  if(otaOpen && !otaWriting && !otaRestartPending) closeOta();
}

static void otaVolumeNext(){
  uint8_t v=audioVolume();
  uint8_t n=(v==0)?25:(v==25)?50:(v==50)?75:(v==75)?100:0;
  audioSetVolume(n); otaMsg=String("VOLUME ")+n+"%";
  if(n>0) sfxPlay(SFX_TAP);
}

static void otaTap(int16_t x,int16_t y){
  (void)x; lastInteract=millis();
  if(otaWriting || otaRestartPending) return;
  if(y<70){ closeOta(); gameMenuOpen=true; return; }
  if(otaBusy()) return;
  if(y>=220 && y<=268){ otaVolumeNext(); return; }
  if(y>=278 && y<=342){ otaStartSetupAp(); return; }
  if(y>=354 && y<=420){ otaDoUpdate(); return; }
}

static void renderOta(){
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xf0,0xf5,0xf8));
  uiPrintCenter(koOr("Wi-Fi 무선 업데이트","WI-FI UPDATE"),36,UI_INK,2);
  uiPrintCenter(otaWriting?"UPDATING - DO NOT POWER OFF":koOr("위쪽 터치: 나가기","TOP: EXIT"),62,UI_TRACK,1);
  gfx->fillCircle(CX,150,52,C565(0x68,0xa8,0xe8));
  gfx->drawCircle(CX,150,34,UI_WHITE); gfx->drawCircle(CX,150,19,UI_WHITE); gfx->fillCircle(CX,150,5,UI_WHITE);
  if(otaState==OTA_DOWNLOAD && otaExpectedSize){
    char progress[24]; snprintf(progress,sizeof(progress),"%lu%%",(unsigned long)((uint64_t)otaReceived*100U/otaExpectedSize));
    uiPrintCenter(progress,142,UI_INK,2);
  }
  if(otaState==OTA_AP){ uiPrintCenter(koOr("휴대폰 Wi-Fi에서 TamaPoke-Update 연결","CONNECT PHONE TO TamaPoke-Update"),194,UI_INK,1); uiPrintCenter("192.168.4.1 / 3 MIN",208,UI_TRACK,1); }
  else uiPrintCenter(otaMsg.c_str(),204,otaState==OTA_ERROR?UI_BAR_WARN:UI_INK,1);
  char volb[32]; snprintf(volb,sizeof(volb),"VOLUME %u%% / v2.8",audioVolume());
  gfx->fillRoundRect(98,220,270,48,14,C565(0xd7,0xe0,0xf0));
  gfx->drawRoundRect(98,220,270,48,14,C565(0x6b,0x78,0x94));
  uiPrintCenter(volb,236,UI_INK,1);
  gfx->fillRoundRect(68,278,330,64,16,C565(0x7f,0xc7,0xa0));
  gfx->drawRoundRect(68,278,330,64,16,C565(0x38,0x75,0x55));
  uiPrintCenter(koOr("Wi-Fi 설정 / 다시 설정","WI-FI SETUP"),299,UI_INK,2);
  gfx->fillRoundRect(68,354,330,66,16,C565(0xff,0xd0,0x66));
  gfx->drawRoundRect(68,354,330,66,16,C565(0x9c,0x70,0x22));
  uiPrintCenter(koOr("업데이트 확인","CHECK UPDATE"),376,UI_INK,2);
  gfx->flush();
}


// ---------- minijuego: toques con la pokeball ----------

void startGame() {
  if (pet.isEgg() || pet.sleeping || pet.ceremony) return;
  gameOpen = true;
  gameOverUntil = 0;
  gameScore = 0;
  gameMisses = 0;
  gameNewHi = false;
  hitTime = 0;
  gamePetX = 233;
  respawnBall();
}

void respawnBall() {
  ballX = 150 + random(166);
  ballY = 96;
  float sp = 1.6f + gameScore * 0.05f;  // mas viva segun avanzas
  if (sp > 4.0f) sp = 4.0f;
  ballVX = random(2) ? sp : -sp;
  ballVY = 0;
}

void gameTap(int16_t x, int16_t y) {
  if (gameOverUntil) { gameTouchBallValid = false; return; }
  if (y < 72) {  // tocar la cabecera = abandonar sin premio
    gameOpen = false;
    gameTouchBallValid = false;
    return;
  }
  float refX = gameTouchBallValid ? gameTouchBallX : ballX;
  float refY = gameTouchBallValid ? gameTouchBallY : ballY;
  gameTouchBallValid = false;
  float dx = refX - x, dy = refY - y;
  if (dx * dx + dy * dy < 82 * 82) {  // judge against touch-down ball position
    gameScore++;
    sfxPlay(SFX_PLAY);
    // golpe mas suave: impulso moderado que crece poco a poco con la puntuacion
    float lift = 6.6f + (gameScore > 16 ? 3.5f : gameScore * 0.22f);
    ballVY = -lift;
    ballVX += dx * 0.12f;
    if (ballVX > 6.5f) ballVX = 6.5f;
    if (ballVX < -6.5f) ballVX = -6.5f;
    hitX = ballX;
    hitY = ballY;
    hitTime = millis();
  }
}

void stepGame() {
  float grav = 0.40f + gameScore * 0.013f;  // cae un poco mas rapido cada vez
  if (grav > 0.80f) grav = 0.80f;
  ballVY += grav;
  ballX += ballVX;
  ballY += ballVY;
  // rebote en la pared circular
  float dx = ballX - CX, dy = ballY - CY;
  float d = sqrtf(dx * dx + dy * dy);
  if (d > 205) {
    float nx = dx / d, ny = dy / d;
    float dot = ballVX * nx + ballVY * ny;
    if (dot > 0) {
      ballVX = (ballVX - 2 * dot * nx) * 0.85f;
      ballVY = (ballVY - 2 * dot * ny) * 0.85f;
    }
    ballX = CX + nx * 205;
    ballY = CY + ny * 205;
  }
  if (ballY > 384) {  // al suelo
    if (++gameMisses >= 3) {
      gameNewHi = (gameScore > pet.gameHi);
      pet.playResult(gameScore);  // actualiza el record y da felicidad
      sfxPlay(gameNewHi && gameScore > 0 ? SFX_MEDAL : SFX_LEVEL);
      gameOverUntil = millis() + 4000;
    } else {
      respawnBall();
    }
  }
  // el bicho la sigue por abajo
  float chase = (ballX - gamePetX) * 0.12f;
  if (chase > 7) chase = 7;
  if (chase < -7) chase = -7;
  gamePetX += chase;
}

// ---------- saco de entrenamiento (entrena la fuerza) ----------

void startSack() {
  if (pet.isEgg() || pet.sleeping || pet.ceremony) return;
  sackOpen = true;
  sackUntil = millis() + 10000;
  sackOverUntil = 0;
  sackHits = 0;
  sackShake = 0;
  sackNewHi = false;
}

void sackTap() {
  if (millis() >= sackUntil) return;  // ya termino el tiempo
  sackHits++;
  sackShake = 16;  // sacude el saco
}

void drawGameScene();  // prototipo (definida mas abajo)

void renderSack() {
  uint32_t now = millis();
  drawGameScene();  // fondo del habitat
  bool night = sceneHour() < 6 || sceneHour() >= 20;
  uint16_t ink = night ? UI_INK_NIGHT : UI_INK;

  // pantalla de resultado
  if (sackOverUntil) {
    char b[20];
    snprintf(b, sizeof(b), T(S_HITS_FMT), sackHits);
    uiPrintCenter(b, 150, ink, 4);
    char g[18];
    snprintf(g, sizeof(g), T(S_STR_GAIN_FMT), sackGain);
    uiPrintCenter(g, 210, UI_BAR_BAD, 3);
    gfx->setTextSize(2);
    if (sackNewHi && sackHits > 0) {
      gfx->setTextColor(UI_BAR_WARN);
      uiPrintCenter(T(S_NEW_RECORD), 256, UI_INK, 2);
    } else {
      char r[18];
      snprintf(r, sizeof(r), T(S_RECORD_FMT), pet.strHi);
      uiPrintCenter(r, 256, ink, 2);
    }
    gfx->flush();
    return;
  }

  // aporreo activo
  int off = (int)(sackShake * sinf(now * 0.05f));
  int sx = CX + off, top = 86, sy = 150;
  gfx->fillRect(CX - 3, 56, 6, top - 56, ink);          // gancho/cuerda
  gfx->fillRect(sx - 4, top - 30, 8, 34, ink);          // cadena
  gfx->fillRoundRect(sx - 42, top, 84, 150, 26, C565(0xb5, 0x3a, 0x3a));  // saco
  gfx->fillRoundRect(sx - 42, top, 84, 22, 18, C565(0x7e, 0x28, 0x28));   // tapa
  gfx->drawRoundRect(sx - 42, top, 84, 150, 26, ink);
  gfx->fillRect(sx - 42, top + 70, 84, 4, C565(0x7e, 0x28, 0x28));        // costura

  // contador de golpes
  char buf[8];
  snprintf(buf, sizeof(buf), "%u", sackHits);
  uiPrintCenter(buf, 268, ink, 6);

  gfx->setTextSize(2);
  uiPrintCenter(T(S_HIT_FAST), 322, UI_INK, 2);

  // barra de tiempo
  uint32_t left = sackUntil - now;
  int bw = 280, fw = (int)((uint32_t)bw * left / 10000);
  gfx->fillRoundRect(CX - bw / 2, 350, bw, 16, 5, UI_TRACK);
  if (fw > 2) gfx->fillRoundRect(CX - bw / 2, 350, fw, 16, 5, UI_BAR_OK);

  gfx->flush();
}

// fondo del minijuego: hatibat del bicho (cielo por hora + suelo del bioma)
void drawGameScene() {
  int hh = sceneHour();
  bool night = hh < 6 || hh >= 20;
  uint16_t top, bot;
  if (night)       { top = C565(0x0c, 0x12, 0x24); bot = C565(0x1e, 0x26, 0x46); }
  else if (hh < 8) { top = C565(0xd1, 0x6a, 0x86); bot = C565(0xf3, 0xb8, 0x7c); }
  else if (hh < 18){ top = C565(0x8f, 0xc8, 0xea); bot = C565(0xdc, 0xee, 0xe6); }
  else             { top = C565(0xc7, 0x5a, 0x4a); bot = C565(0xf0, 0xae, 0x64); }
  int hor = 376;
  for (int y = 0; y < hor; y += 8)
    gfx->fillRect(0, y, 466, 8, lerp565(top, bot, y, hor));
  if (night)
    for (auto &st : STARS) gfx->fillRect(st[0], st[1], 4, 4, UI_WHITE);
  uint8_t bio = pet.isEgg() ? 0 : DEX_TBL[pet.speciesId].biome;
  uint16_t soil = BIOME_SOIL[bio < 6 ? bio : 0];
  if (night) soil = lerp565(soil, C565(0x16, 0x1c, 0x30), 9, 16);
  gfx->fillRect(0, hor, 466, 466 - hor, soil);
}

void renderGame() {
  // sin fillScreen(NEGRO): drawGameScene cubre los 466x466 completos. Si el
  // DMA del flush anterior aun lee el buffer, vera contenido valido (no negro
  // a medio pintar), que era el parpadeo a 25 fps.
  bool night = sceneHour() < 6 || sceneHour() >= 20;
  uint16_t ink = night ? UI_INK_NIGHT : UI_INK;

  if (gameOverUntil) {
    drawGameScene();
    char buf[22];
    snprintf(buf, sizeof(buf), T(S_SCORE_FMT), gameScore);
    uiPrintCenter(buf, 160, ink, 4);
    gfx->setTextSize(2);
    if (gameNewHi && gameScore > 0) {
      gfx->setTextColor(UI_BAR_WARN);
      uiPrintCenter(T(S_NEW_RECORD), 214, UI_INK, 2);
    } else {
      char rec[20];
      snprintf(rec, sizeof(rec), T(S_RECORD_FMT), pet.gameHi);
      uiPrintCenter(rec, 214, ink, 2);
    }
    const char *msg = gameScore >= 10 ? T(S_GREAT_JOY) : T(S_PLUS_JOY);
    uiPrintCenter(msg, 246, ink, 2);
    gfx->flush();
    return;
  }

  drawGameScene();

  // marcador, record y vidas
  char buf[8];
  snprintf(buf, sizeof(buf), "%u", gameScore);
  uiPrintCenter(buf, 30, ink, 4);
  char rec[12];
  snprintf(rec, sizeof(rec), T(S_REC_FMT), pet.gameHi);
  uiPrintCenter(rec, 76, ink, 2);
  for (int i = 0; i < 3; i++) {
    if (i < 3 - gameMisses) gfx->fillCircle(180 + i * 28, 104, 6, UI_BAR_BAD);
    else gfx->drawCircle(180 + i * 28, 104, 6, UI_TRACK);
  }

  if (pmd.loaded) {
    uint8_t act = (ballX > gamePetX + 4) ? PMD_WALKR : (ballX < gamePetX - 4) ? PMD_WALKL : PMD_IDLE;
    if (!pmd.has(act)) act = PMD_IDLE;
    drawPmdAct(act, (int)gamePetX, 394, millis(), true, false, 3);
  } else if (mon.loaded) {
    int s = (mon.h * 2 > 130) ? 1 : 2;
    int w = mon.w * s, h = mon.h * s;
    uint16_t fm = mon.frameMs ? mon.frameMs : 100;
    uint16_t fi = (millis() / fm) % mon.frames;
    const uint8_t *fr = mon.data + (uint32_t)fi * mon.w * mon.h;
    int px = (int)gamePetX - w / 2, py = 394 - h;
    for (int r = 0; r < mon.h; r++)
      for (int c = 0; c < mon.w; c++) {
        uint8_t idx = fr[r * mon.w + c];
        if (idx == 0xFF) continue;
        gfx->fillRect(px + c * s, py + r * s, s, s, mon.pal[idx]);
      }
  }

  // anillo de impacto que se expande y desvanece (feedback suave del golpe)
  uint32_t ht = millis() - hitTime;
  if (hitTime && ht < 260) {
    int rad = 22 + (int)(ht / 6);
    gfx->drawCircle((int)hitX, (int)hitY, rad, C565(0xff, 0xe7, 0x9f));
    gfx->drawCircle((int)hitX, (int)hitY, rad - 2, C565(0xff, 0xd9, 0x8a));
  }

  // la pokeball
  drawMap(SPR_ICON_PLAY, 16, (int)ballX - 24, (int)ballY - 24, 3, false);

  gfx->flush();
}

// ---------- ficha del bicho (deslizar vertical) ----------

void drawCardStat(int y, const char *label, uint16_t val, uint16_t maxBar, uint16_t color) {
  uiPrintAt(label, 78, y-3, UI_INK, 2);
  char num[8]; snprintf(num, sizeof(num), "%u", val);
  uiPrintAt(num, 338, y-3, UI_INK, 2);
  int bx=158, bw=164; int fw=(int)val*bw/maxBar; if (fw>bw) fw=bw;
  gfx->fillRoundRect(bx, y+3, bw, 12, 4, UI_TRACK);
  if (fw>2) gfx->fillRoundRect(bx+2, y+5, fw-2, 8, 3, color);
}

// ---------- reloj de espera + ajustes + alarma ----------
// La hora del PCF85063 sigue corriendo con la alimentacion de respaldo.
// La configuracion de alarma se guarda en Preferences. El apagado corto de
// pantalla mantiene el firmware vivo y la alarma puede despertar la pantalla.
// Un apagado fisico de 4 s corta MCU/audio: la configuracion se conserva, pero
// ningun firmware puede hacer sonar el altavoz mientras la placa esta sin energia.

static const char *koOr(const char *ko, const char *other) {
  return gLang == LANG_KO ? ko : other;
}
static const char *const LANG_CODES[LANG_COUNT] = { "ES", "EN", "FR", "DE", "IT", "PT", "KO" };

static void drawBatteryMini(int x, int y, int pct, uint16_t color) {
  gfx->drawRoundRect(x, y, 32, 16, 3, color);
  gfx->fillRect(x + 32, y + 5, 3, 6, color);
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  int w = (28 * pct) / 100;
  if (w > 0) gfx->fillRect(x + 2, y + 2, w, 12, color);
}

static void drawBellMini(int x, int y, uint16_t color) {
  gfx->drawCircle(x, y + 9, 7, color);
  gfx->fillRect(x - 7, y + 9, 15, 7, color);
  gfx->fillCircle(x, y + 18, 2, color);
  gfx->fillCircle(x, y + 1, 2, color);
}

static const char *weekdayKo(uint8_t wday) {
  static const char *const W[7] = {
    "일요일","월요일","화요일","수요일","목요일","금요일","토요일"
  };
  return W[wday % 7];
}

static void drawAlarmPet(int groundY, bool sleeping, uint8_t maxScale = 4) {
  if (pmd.loaded) {
    uint8_t act = sleeping && pmd.has(PMD_SLEEP) ? PMD_SLEEP : PMD_IDLE;
    drawPmdAct(act, CX, groundY, millis(), true, false, maxScale);
    return;
  }
  // Fallback keeps the same proven sprite loader; most installed packs use PMD.
  drawPet();
}

// Daytime standby pet: walk left/right across the lower part of the round screen.
// Uses the same 06:00..19:59 daytime boundary as the normal TamaPoke scene.
static void drawStandbyAwakePet(int groundY) {
  if (pmd.loaded) {
    const int leftX = 138;
    const int rightX = 328;
    const uint32_t span = (uint32_t)(rightX - leftX);
    const uint32_t phase = (millis() / 18UL) % (span * 2UL);
    const bool goingRight = phase < span;
    const int x = goingRight
      ? leftX + (int)phase
      : rightX - (int)(phase - span);

    uint8_t act = PMD_IDLE;
    if (goingRight && pmd.has(PMD_WALKR)) act = PMD_WALKR;
    else if (!goingRight && pmd.has(PMD_WALKL)) act = PMD_WALKL;
    drawPmdAct(act, x, groundY, millis(), true, false, 3);
    return;
  }
  drawPet();
}

void renderStandbyClock() {
  uint32_t e = rtcEpoch();
  if (!e) e = pet.lastSeenEpoch;
  time_t tt = (time_t)e;
  struct tm tmv = {};
  gmtime_r(&tt, &tmv);

  const bool dayMode = !pet.sleeping && (tmv.tm_hour >= 6 && tmv.tm_hour < 20);
  const uint16_t sky = dayMode ? C565(0x38,0x8f,0xd1) : C565(0x12,0x18,0x35);
  const uint16_t sky2 = dayMode ? C565(0x6d,0xb8,0xe5) : C565(0x24,0x20,0x4a);
  const uint16_t card = dayMode ? C565(0x20,0x62,0x9a) : C565(0x0b,0x10,0x27);
  const uint16_t soft = dayMode ? C565(0xd9,0xf2,0xff) : C565(0xb9,0xc8,0xff);

  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, sky);
  // Layered circles make a soft two-tone watch face without gradients.
  gfx->fillCircle(CX, CY + 142, 214, sky2);
  gfx->drawCircle(CX, CY, 224, dayMode ? C565(0x9d,0xd7,0xf4) : C565(0x39,0x3d,0x72));

  if (dayMode) {
    // Sun + a soft cloud cluster.
    const uint16_t sun = C565(0xff,0xd8,0x57);
    gfx->fillCircle(365, 102, 24, sun);
    gfx->fillCircle(96, 84, 12, soft);
    gfx->fillCircle(113, 78, 17, soft);
    gfx->fillCircle(132, 86, 11, soft);
    gfx->fillRoundRect(87, 84, 55, 13, 6, soft);
  } else {
    // Crescent moon and calm star field.
    const uint16_t moon = C565(0xff,0xf2,0xc0);
    gfx->fillCircle(363, 105, 28, moon);
    gfx->fillCircle(378, 94, 27, sky);
    static const int16_t clkStars[][2] = {
      {94,91},{126,130},{169,79},{310,94},{404,144},{79,168},{389,185},{144,238}
    };
    for (auto &st : clkStars) gfx->fillCircle(st[0], st[1], 2, UI_WHITE);
  }

  // Battery is deliberately centered. USB power is shown even when the battery
  // is already full and AXP2101 no longer reports an active charge current.
  const int pct = batPercent();
  const bool hasBat = pct >= 0;
  const bool plugged = hasBat && usbPresent();
  const bool charging = hasBat && batCharging();
  const int bx = CX - 78, by = 25, bw = 156, bh = 34;
  gfx->fillRoundRect(bx, by, bw, bh, 17, card);
  gfx->drawRoundRect(bx, by, bw, bh, 17, dayMode ? C565(0x8f,0xce,0xef) : C565(0x4c,0x52,0x86));

  const int ibx = CX - 62, iby = 34, ibw = 31, ibh = 15;
  const uint16_t batCol = charging ? UI_BAR_OK : UI_WHITE;
  gfx->drawRoundRect(ibx, iby, ibw, ibh, 3, batCol);
  gfx->fillRect(ibx + ibw, iby + 5, 3, 6, batCol);
  if (plugged) {
    const uint16_t bolt = charging ? UI_BAR_OK : C565(0xff,0xd9,0x4a);
    const int lx = ibx + 15;
    gfx->fillTriangle(lx + 3, iby + 1, lx - 4, iby + 8, lx + 1, iby + 8, bolt);
    gfx->fillTriangle(lx - 1, iby + 7, lx + 4, iby + 7, lx - 3, iby + 14, bolt);
  } else if (hasBat) {
    int pc = pct > 100 ? 100 : pct;
    int fw = (ibw - 4) * pc / 100;
    if (fw > 0) gfx->fillRect(ibx + 2, iby + 2, fw, ibh - 4, batCol);
  }

  char bp[10];
  if (hasBat) snprintf(bp, sizeof(bp), "%d%%", pct > 100 ? 100 : pct);
  else snprintf(bp, sizeof(bp), "--%%");
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(2);
  gfx->setCursor(CX - 19, 35); gfx->print(bp);
  if (plugged) {
    gfx->setTextSize(1); gfx->setTextColor(charging ? UI_BAR_OK : C565(0xff,0xd9,0x4a));
    gfx->setCursor(CX + 36, 38); gfx->print(charging ? "CHG" : "USB");
  }

  // Alarm gets its own compact centered pill so the top of the round display stays balanced.
  if (alarmEnabled()) {
    char ab[8]; snprintf(ab, sizeof(ab), "%02u:%02u", alarmHour(), alarmMinute());
    gfx->fillRoundRect(CX - 64, 68, 128, 28, 14, card);
    drawBellMini(CX - 43, 71, UI_BAR_WARN);
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(2);
    gfx->setCursor(CX - 20, 75); gfx->print(ab);
  }

  char tb[8]; snprintf(tb, sizeof(tb), "%02d:%02d", tmv.tm_hour, tmv.tm_min);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(8);
  gfx->setCursor(CX - (int)strlen(tb) * 24, 112); gfx->print(tb);

  // Date and weekday are separated so Korean stays crisp and the whole layout remains centered.
  char db[24];
  snprintf(db, sizeof(db), "%04d.%02d.%02d", tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(3);
  gfx->setCursor(CX - (int)strlen(db) * 9, 205); gfx->print(db);
  if (gLang == LANG_KO) {
    uiPrintCenter(weekdayKo(tmv.tm_wday), 239, UI_WHITE, 3);
  }

  // Pokemon now sits directly on the watch-face background: no large card/box.
  if (dayMode) {
    gfx->fillRoundRect(150, 386, 166, 5, 3, C565(0x64,0xb6,0x76));
    drawStandbyAwakePet(392);
  } else {
    gfx->fillRoundRect(150, 386, 166, 5, 3, C565(0x38,0x3d,0x65));
    drawAlarmPet(392, true, 3);
    gfx->setTextColor(soft); gfx->setTextSize(2); gfx->setCursor(319, 320); gfx->print("Zzz...");
  }

  if ((int32_t)(powerNoticeUntil-millis())>0) {
    char pb[18]; snprintf(pb,sizeof(pb),"BRIGHT %u%%",powerBrightnessPct);
    gfx->fillRoundRect(CX-76,252,152,30,15,C565(0x18,0x25,0x42));
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(1); gfx->setCursor(CX-45,262); gfx->print(pb);
  }
  gfx->flush();
}

static int daysInMonth(int y, int m) {
  static const uint8_t D[12] = {31,28,31,30,31,30,31,31,30,31,30,31};
  int d = D[(m < 1 ? 1 : m > 12 ? 12 : m) - 1];
  if (m == 2 && ((y % 4 == 0 && y % 100 != 0) || (y % 400 == 0))) d = 29;
  return d;
}

static void clampClockDate() {
  if (clockY < 2025) clockY = 2120;
  if (clockY > 2120) clockY = 2025;
  if (clockMo < 1) clockMo = 12;
  if (clockMo > 12) clockMo = 1;
  int md = daysInMonth(clockY, clockMo);
  if (clockD < 1) clockD = md;
  if (clockD > md) clockD = 1;
}

void openClock() {
  uint32_t e = pet.lastSeenEpoch ? pet.lastSeenEpoch : rtcEpoch();
  if (!e) e = 1767225600UL;
  time_t tt = (time_t)e;
  struct tm tmv = {};
  gmtime_r(&tt, &tmv);
  clockY = tmv.tm_year + 1900;
  clockMo = tmv.tm_mon + 1;
  clockD = tmv.tm_mday;
  clockH = tmv.tm_hour;
  clockM = tmv.tm_min;
  alarmEditH = alarmHour();
  alarmEditM = alarmMinute();
  clockPage = 0;
  clockOpen = true;
}

void applyClock() {
  clampClockDate();
  struct tm tmv = {};
  tmv.tm_year = clockY - 1900;
  tmv.tm_mon = clockMo - 1;
  tmv.tm_mday = clockD;
  tmv.tm_hour = clockH;
  tmv.tm_min = clockM;
  tmv.tm_sec = 0;
  time_t tt = mktime(&tmv);
  if (tt <= 0) return;
  uint32_t e = (uint32_t)tt;
  rtcSetEpoch(e);
  pet.setClock(e);
  clockPage = 0;
}

void drawClockBtn(int x, int y, const char *l) {
  gfx->fillRoundRect(x, y, 58, 58, 12, UI_WHITE);
  gfx->drawRoundRect(x, y, 58, 58, 12, UI_INK);
  gfx->setTextColor(UI_INK);
  gfx->setTextSize(4);
  gfx->setCursor(x + 17, y + 15);
  gfx->print(l);
}

static void drawMenuRow(int y, const char *label, bool accent = false) {
  gfx->fillRoundRect(62, y, 342, 48, 10, accent ? UI_BAR_WARN : UI_WHITE);
  gfx->drawRoundRect(62, y, 342, 48, 10, accent ? UI_BAR_WARN : UI_TRACK);
  uiPrintAt(label, 82, y + 9, UI_INK, gLang == LANG_KO ? 3 : 2);
}

static void renderClockMenu() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, UI_BG_DAY);
  uiPrintCenter(koOr("시간설정","SETTINGS"), 34, UI_INK, 3);

  drawMenuRow(88,  koOr("1. 시간조정","1. SET TIME"));
  drawMenuRow(144, koOr("2. 알람 설정","2. ALARM"), true);

  char snd[48];
  snprintf(snd, sizeof(snd), "%s %s", koOr("3. 소리","3. SOUND"), audioEnabled() ? "ON" : "OFF");
  drawMenuRow(200, snd);

  char lang[32];
  snprintf(lang, sizeof(lang), "%s %s", koOr("4. 언어","4. LANG"), LANG_CODES[gLang]);
  drawMenuRow(256, lang);
  drawMenuRow(312, koOr("5. 절전 설정","5. POWER"));

  if (alarmEnabled()) {
    char a[40]; snprintf(a, sizeof(a), "%s %02u:%02u", koOr("알람","ALARM"), alarmHour(), alarmMinute());
    uiPrintCenter(a, 382, UI_BAR_BAD, 2);
  }
  uiPrintCenter(koOr("아래로 밀면 뒤로","Swipe down: close"), 420, UI_TRACK, 1);
}

static void renderTimeAdjust() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, UI_BG_DAY);
  uiPrintCenter(koOr("시간 / 날짜","TIME / DATE"), 34, UI_INK, 3);

  char t[8]; snprintf(t, sizeof(t), "%02d:%02d", clockH, clockM);
  gfx->setTextColor(UI_INK); gfx->setTextSize(7); gfx->setCursor(CX - 105, 96); gfx->print(t);

  drawClockBtn(104, 178, "-"); drawClockBtn(170, 178, "+");
  drawClockBtn(252, 178, "-"); drawClockBtn(318, 178, "+");
  uiPrintAt(T(S_HOUR), 118, 241, UI_INK, gLang == LANG_KO ? 3 : 2);
  uiPrintAt(T(S_MIN), 274, 241, UI_INK, gLang == LANG_KO ? 3 : 2);

  gfx->fillRoundRect(76, 282, 314, 42, 12, UI_WHITE);
  gfx->drawRoundRect(76, 282, 314, 42, 12, UI_TRACK);
  uiPrintAt(koOr("날짜","DATE"), 92, 291, UI_INK, gLang == LANG_KO ? 3 : 2);
  char db[16]; snprintf(db, sizeof(db), "%04d-%02d-%02d", clockY, clockMo, clockD);
  gfx->setTextColor(UI_INK); gfx->setTextSize(2); gfx->setCursor(218, 294); gfx->print(db);

  gfx->fillRoundRect(133, 340, 200, 46, 14, UI_BAR_OK);
  uiPrintCenter(koOr("확인","OK"), 350, UI_BG_DAY, 2);
  uiPrintCenter(koOr("뒤로가기","BACK"), 404, UI_INK, 1);
}

static void renderDateAdjust() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, UI_BG_DAY);
  uiPrintCenter(koOr("날짜 설정","SET DATE"), 36, UI_INK, 3);

  char db[16]; snprintf(db, sizeof(db), "%04d-%02d-%02d", clockY, clockMo, clockD);
  gfx->setTextColor(UI_INK); gfx->setTextSize(4);
  gfx->setCursor(CX - (int)strlen(db) * 12, 92); gfx->print(db);

  uiPrintAt(koOr("년","YEAR"), 66, 154, UI_INK, 2);
  uiPrintAt(koOr("월","MONTH"), 202, 154, UI_INK, 2);
  uiPrintAt(koOr("일","DAY"), 344, 154, UI_INK, 2);

  drawClockBtn(36, 196, "-");   drawClockBtn(98, 196, "+");
  drawClockBtn(174, 196, "-");  drawClockBtn(236, 196, "+");
  drawClockBtn(312, 196, "-");  drawClockBtn(374, 196, "+");

  char yb[8], mb[4], dd[4];
  snprintf(yb, sizeof(yb), "%d", clockY);
  snprintf(mb, sizeof(mb), "%02d", clockMo);
  snprintf(dd, sizeof(dd), "%02d", clockD);
  gfx->setTextColor(UI_INK); gfx->setTextSize(2);
  gfx->setCursor(57, 270); gfx->print(yb);
  gfx->setCursor(207, 270); gfx->print(mb);
  gfx->setCursor(345, 270); gfx->print(dd);

  gfx->fillRoundRect(133, 330, 200, 48, 14, UI_BAR_OK);
  uiPrintCenter(koOr("확인","OK"), 340, UI_BG_DAY, 2);
  uiPrintCenter(koOr("뒤로가기","BACK"), 402, UI_INK, 1);
}

static void renderAlarmSettings() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, UI_BG_DAY);
  uiPrintCenter(koOr("알람 설정","ALARM"), 38, UI_INK, 3);

  uiPrintAt(koOr("알람","ALARM"), 76, 98, UI_INK, gLang == LANG_KO ? 3 : 2);
  bool on=alarmEnabled();
  gfx->fillRoundRect(312, 92, 90, 38, 19, on ? UI_BAR_OK : UI_TRACK);
  gfx->fillCircle(on ? 383 : 331, 111, 15, UI_WHITE);
  uiPrintAt(on ? "ON" : "OFF", on ? 322 : 355, 101, on ? UI_BG_DAY : UI_INK, 1);

  gfx->fillRoundRect(58, 158, 350, 62, 10, UI_BAR_WARN);
  uiPrintAt(koOr("시간","TIME"), 78, 172, UI_INK, gLang == LANG_KO ? 3 : 2);
  char ab[8]; snprintf(ab, sizeof(ab), "%02u:%02u", alarmHour(), alarmMinute());
  gfx->setTextColor(UI_INK); gfx->setTextSize(3); gfx->setCursor(301, 173); gfx->print(ab);

  drawMenuRow(244, koOr("뒤로가기","BACK"));
  uiPrintCenter(koOr("시간 선택: 알람 시간 변경","Tap time to change alarm"), 334, UI_TRACK, 1);
  uiPrintCenter(koOr("알람 설정은 전원 OFF 후에도 유지","Alarm settings are saved"), 360, UI_TRACK, 1);
}

static void renderAlarmNumber(bool hourPage) {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, UI_BG_DAY);
  uiPrintCenter(hourPage ? koOr("알람 시간 (시)","ALARM HOUR")
                         : koOr("알람 시간 (분)","ALARM MIN"),
                38, UI_INK, 3);

  gfx->fillTriangle(CX, 92, CX-18, 116, CX+18, 116, UI_INK);
  char n[4]; snprintf(n, sizeof(n), "%02d", hourPage ? alarmEditH : alarmEditM);
  gfx->setTextColor(UI_INK); gfx->setTextSize(8); gfx->setCursor(CX - 48, 145); gfx->print(n);
  gfx->fillTriangle(CX, 278, CX-18, 254, CX+18, 254, UI_INK);

  gfx->fillRoundRect(116, 332, 234, 48, 13, UI_BAR_WARN);
  uiPrintCenter(hourPage ? koOr("다음","NEXT") : koOr("확인","OK"), 342, UI_INK, 2);
  uiPrintCenter(koOr("뒤로가기","BACK"), 404, UI_INK, 1);
}

void renderClock() {
  if (clockPage == 6) renderPowerSettings();
  else if (clockPage == 0) renderClockMenu();
  else if (clockPage == 1) renderTimeAdjust();
  else if (clockPage == 2) renderAlarmSettings();
  else if (clockPage == 3) renderAlarmNumber(true);
  else if (clockPage == 4) renderAlarmNumber(false);
  else renderDateAdjust();
  gfx->flush();
}

void clockTap(int16_t x, int16_t y) {
  if (clockPage == 6) {
    if(x>=62 && x<=404 && y>=104 && y<152){
      powerAlwaysOnClock=!powerAlwaysOnClock;powerPrefs.putBool("aod",powerAlwaysOnClock);sfxPlay(SFX_TAP);
    } else if(x>=62 && x<=404 && y>=168 && y<216){
      powerLightSleepEnabled=!powerLightSleepEnabled;powerPrefs.putBool("sleep",powerLightSleepEnabled);sfxPlay(SFX_TAP);
    } else if(y>=340 && y<388) clockPage=0;
    return;
  }
  if (clockPage == 0) {
    if (y >= 88 && y < 136) { clockPage=1; sfxPlay(SFX_TAP); return; }
    if (y >= 144 && y < 192) {
      alarmEditH=alarmHour(); alarmEditM=alarmMinute(); clockPage=2; sfxPlay(SFX_TAP); return;
    }
    if (y >= 200 && y < 248) {
      audioSetEnabled(!audioEnabled()); if (audioEnabled()) sfxPlay(SFX_TAP); return;
    }
    if (y >= 256 && y < 304) {
      setLang((Lang)((gLang + 1) % LANG_COUNT)); sfxPlay(SFX_TAP); return;
    }
    if (y >= 312 && y < 360) { clockPage=6; return; }
    return;
  }

  if (clockPage == 1) {
    if (y >= 178 && y <= 236) {
      if (x >= 104 && x < 162) clockH = (clockH + 23) % 24;
      else if (x >= 170 && x < 228) clockH = (clockH + 1) % 24;
      else if (x >= 252 && x < 310) clockM = (clockM + 59) % 60;
      else if (x >= 318 && x < 376) clockM = (clockM + 1) % 60;
      sfxPlay(SFX_TAP); return;
    }
    if (y >= 278 && y <= 328 && x >= 70 && x <= 396) { clockPage=5; sfxPlay(SFX_TAP); return; }
    if (y >= 336 && y <= 390 && x >= 125 && x <= 341) { applyClock(); sfxPlay(SFX_TAP); return; }
    if (y >= 394) { clockPage=0; return; }
    return;
  }

  if (clockPage == 2) {
    if (y >= 88 && y <= 138) {
      alarmSetEnabled(!alarmEnabled());
      sfxPlay(SFX_TAP);
      return;
    }
    if (y >= 152 && y <= 226) {
      alarmEditH=alarmHour(); alarmEditM=alarmMinute();
      clockPage=3; sfxPlay(SFX_TAP); return;
    }
    if (y >= 238 && y <= 302) { clockPage=0; return; }
    return;
  }

  if (clockPage == 5) {
    if (y >= 190 && y <= 262) {
      if      (x >= 30  && x < 94)  clockY--;
      else if (x >= 94  && x < 166) clockY++;
      else if (x >= 168 && x < 232) clockMo--;
      else if (x >= 232 && x < 304) clockMo++;
      else if (x >= 306 && x < 370) clockD--;
      else if (x >= 370 && x <= 438) clockD++;
      clampClockDate();
      sfxPlay(SFX_TAP); return;
    }
    if (y >= 326 && y <= 386 && x >= 125 && x <= 341) { applyClock(); sfxPlay(SFX_TAP); return; }
    if (y >= 390) { clockPage=1; return; }
    return;
  }

  if (clockPage == 3 || clockPage == 4) {
    bool hp = clockPage == 3;
    if (y >= 78 && y <= 128) {
      if (hp) alarmEditH=(alarmEditH+1)%24;
      else alarmEditM=(alarmEditM+1)%60;
      sfxPlay(SFX_TAP); return;
    }
    if (y >= 242 && y <= 294) {
      if (hp) alarmEditH=(alarmEditH+23)%24;
      else alarmEditM=(alarmEditM+59)%60;
      sfxPlay(SFX_TAP); return;
    }
    if (y >= 326 && y <= 388) {
      if (hp) clockPage=4;
      else {
        alarmSetTime(alarmEditH, alarmEditM);
        clockPage=2;
      }
      sfxPlay(SFX_TAP); return;
    }
    if (y >= 392) { clockPage = hp ? 2 : 3; return; }
  }
}

void renderAlarmRinging() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, C565(0x08,0x0b,0x12));

  uiPrintCenter(koOr("알람!","ALARM!"), 42, UI_WHITE, 3);
  uiPrintCenter(koOr("일어날 시간이야!","Time to wake up!"), 82, UI_WHITE, 2);

  // Lightning marks around the pet.
  for (int i=0;i<4;i++) {
    int lx=88+i*95;
    gfx->drawLine(lx,170,lx+12,184,UI_BAR_WARN);
    gfx->drawLine(lx+12,184,lx+4,198,UI_BAR_WARN);
    gfx->drawLine(lx+4,198,lx+19,214,UI_BAR_WARN);
  }

  drawAlarmPet(292, false, 4);

  gfx->fillRoundRect(82, 304, 302, 54, 12, UI_BAR_WARN);
  uiPrintCenter(koOr("정지","STOP"), 318, UI_INK, 2);

  gfx->fillRoundRect(82, 370, 302, 54, 12, C565(0x18,0x1d,0x28));
  gfx->drawRoundRect(82, 370, 302, 54, 12, UI_WHITE);
  uiPrintCenter(koOr("5분 후","5 MIN"), 384, UI_WHITE, 2);
  gfx->flush();
}

void alarmRingTap(int16_t x, int16_t y) {
  (void)x;
  uint32_t now=millis();
  if (y >= 294 && y <= 364) {
    alarmStop();
    audioAlarmStop();
    alarmNotice=2;
    alarmNoticeUntil=now+3200;
    lastInteract=now;
    screenOff=false;
    return;
  }
  if (y >= 364 && y <= 434) {
    alarmSnooze(rtcEpoch(), 5);
    audioAlarmStop();
    alarmNotice=1;
    alarmNoticeUntil=now+3200;
    lastInteract=now;
    screenOff=false;
    return;
  }
}

void renderAlarmNotice() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, C565(0x08,0x0b,0x12));

  if (alarmNotice == 1) {
    uiPrintCenter(koOr("스누즈","SNOOZE"), 48, UI_WHITE, 3);
    uiPrintCenter(koOr("5분 후 다시","Alarm again in 5 min"), 96, UI_WHITE, 2);
    uiPrintCenter(koOr("알람이 울려요",""), 126, UI_WHITE, 2);
    drawAlarmPet(330, true, 4);
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(3); gfx->setCursor(318, 240); gfx->print("Zzz...");
  } else {
    uiPrintCenter(koOr("알람 정지","ALARM OFF"), 54, UI_WHITE, 3);
    uiPrintCenter(koOr("좋은 하루 보내!","Have a good day!"), 100, UI_WHITE, 2);
    drawAlarmPet(330, false, 4);
    gfx->fillCircle(350, 214, 10, UI_BAR_WARN);
    gfx->fillRect(358, 170, 5, 48, UI_BAR_WARN);
    gfx->drawLine(361,170,382,178,UI_BAR_WARN);
  }
  gfx->flush();
}

// llama + numero de racha arriba a la izquierda
void drawStreakBadge() {
  if (pet.streak < 1) return;
  int x = 26, y = 16;
  gfx->fillTriangle(x + 8, y, x + 1, y + 17, x + 15, y + 17, UI_BAR_BAD);
  gfx->fillTriangle(x + 8, y + 7, x + 4, y + 17, x + 12, y + 17, UI_BAR_WARN);
  char s[6];
  snprintf(s, sizeof(s), "%u", pet.streak);
  gfx->setTextColor(inkColor());
  gfx->setTextSize(2);
  gfx->setCursor(x + 22, y + 2);
  gfx->print(s);
}

// banner temporal: medalla nueva o hito de racha
void drawCelebration() {
  const char *l1 = nullptr, *l2 = nullptr;
  char buf[20];
  if (pet.showMedal()) {
    for (int i = 0; i < MED_COUNT; i++)
      if (pet.newMedal & (1 << i)) { l2 = medalName(i); break; }
    l1 = T(S_MEDAL_BANNER);
  } else if (pet.showMilestone()) {
    snprintf(buf, sizeof(buf), T(S_STREAK_DAYS_FMT), pet.streak);
    l1 = T(S_GREAT);
    l2 = buf;
  }
  if (!l1) return;
  gfx->fillRoundRect(73, 150, 320, 96, 16, UI_BAR_WARN);
  gfx->drawRoundRect(73, 150, 320, 96, 16, UI_INK);
  uiPrintCenter(l1, 172, UI_INK, 3);
  uiPrintCenter(l2, 208, UI_INK, 2);
}

// medallas en la ficha: badge con etiqueta, color si conseguida
void drawMedalBadge(int x, int y, int i) {
  bool got = pet.hasMedal(1 << i);
  gfx->fillRoundRect(x, y, 100, 24, 6, got ? UI_BAR_OK : UI_TRACK);
  if (!got) gfx->drawRoundRect(x, y, 100, 24, 6, UI_TRACK);
  const char *ml = medalLabel(i);
  uiPrintAt(ml, x + (100 - uiTextWidth(ml, 2)) / 2, y + 3,
            got ? UI_BG_DAY : 0x9492, 2);
}

// pagina 0: perfil (retrato grande, identidad, racha, vinculo, baya)
void renderCardProfile() {
  const DexEntry &d = DEX_TBL[pet.speciesId];
  const char *nm = pet.nick[0] ? pet.nick : localizedPokeName(pet.speciesId);
  char head[64]; snprintf(head, sizeof(head), T(S_NAME_FMT), pet.shiny ? "*" : "", nm, pet.level());
  uint8_t hts = (uiTextWidth(head,3) <= 360) ? 3 : 2;
  uiPrintCenter(head, hts==3 ? 28 : 34, d.accent, hts);
  if (pet.nick[0]) {
    char spn[48]; snprintf(spn,sizeof(spn),"(%s)",localizedPokeName(pet.speciesId));
    uiPrintCenter(spn, 60, UI_TRACK, 1);
  }
  if (pmd.loaded) drawPmdAct(PMD_IDLE, CX, 206, millis(), true, false, 4);

  int sx=122, sy=224;
  gfx->fillTriangle(sx+8,sy,sx+1,sy+18,sx+15,sy+18,UI_BAR_BAD);
  gfx->fillTriangle(sx+8,sy+7,sx+4,sy+18,sx+12,sy+18,UI_BAR_WARN);
  char rl[48]; snprintf(rl,sizeof(rl),T(S_STREAK_FMT),pet.streak,pet.bestStreak);
  uiPrintAt(rl,sx+24,sy-1,UI_INK,1);

  drawCardStat(258,T(S_VIN),pet.bond,100,C565(0xd4,0x52,0x7e));
  const char *berry=!pet.berryKnown?T(S_BERRY_UNK):pet.lovesBerry(0)?T(S_BERRY_RED):pet.lovesBerry(1)?T(S_BERRY_BLUE):T(S_BERRY_GREEN);
  char info[64]; snprintf(info,sizeof(info),T(S_INFO_FMT),berry,(unsigned long)(pet.ageMinutes/1440));
  uiPrintCenter(info, 292, UI_INK, 1);
  uiPrintCenter(T(S_RENAME_HINT), 326, UI_INK, 1);
}

// pagina 1: combate (4 barras + boton de entrenar)
void renderCardStats() {
  uiPrintCenter(T(S_BATTLE), 38, UI_INK, 3);
  drawCardStat(112, T(S_STAT_ATK), pet.atkStat(), 260, UI_BAR_BAD);
  drawCardStat(154, T(S_STAT_DEF), pet.defStat(), 260, 0x4C98);
  drawCardStat(196, T(S_STAT_SPE), pet.speStat(), 260, UI_BAR_WARN);
  drawCardStat(238, T(S_STAT_WGT), pet.weight, 100, 0xB3C8);
  gfx->fillRoundRect(96, 296, 274, 44, 12, UI_BAR_BAD);
  uiPrintCenter(T(S_TRAIN_STR), 305, UI_BG_DAY, 2);
}

// pagina 2: medallas con etiqueta descriptiva
void renderCardMedals() {
  int got=0; for(int i=0;i<MED_COUNT;i++) if(pet.hasMedal(1<<i)) got++;
  char head[32]; snprintf(head,sizeof(head),T(S_MEDALS_FMT),got,MED_COUNT);
  uiPrintCenter(head, 38, UI_INK, 3);
  for(int i=0;i<MED_COUNT;i++) {
    int x=28+(i%2)*206, y=100+(i/2)*54; bool g=pet.hasMedal(1<<i);
    gfx->fillRoundRect(x,y,196,44,10,g?UI_BAR_OK:UI_WHITE);
    gfx->drawRoundRect(x,y,196,44,10,g?UI_BAR_OK:UI_TRACK);
    if(g){ gfx->fillCircle(x+22,y+22,11,UI_BG_DAY); uiPrintAt("V",x+17,y+12,UI_BAR_OK,1); }
    uiPrintAt(medalDesc(i), x+(g?44:14), y+10, g?UI_BG_DAY:UI_INK, 1);
  }
}

// pagina 3: progreso (nivel, evolucion, descuidos) — saca a la luz mecanicas
// que antes eran invisibles (cuanto falta para subir/evolucionar y por que)
void renderCardProgress() {
  const DexEntry &d=DEX_TBL[pet.speciesId];
  uiPrintCenter(T(S_PROGRESS), 36, UI_INK, 3);
  char lv[16]; snprintf(lv,sizeof(lv),T(S_LVL_FMT),pet.level());
  uiPrintCenter(lv, 82, UI_INK, 3);
  uint8_t into=pet.ageMinutes%MINUTES_PER_LEVEL;
  int bx=93,bw=280,by=152,bh=22; gfx->fillRoundRect(bx,by,bw,bh,6,UI_TRACK);
  int fw=(bw-4)*into/MINUTES_PER_LEVEL; if(fw>0) gfx->fillRoundRect(bx+2,by+2,fw,bh-4,5,UI_BAR_OK);
  char nx[48]; snprintf(nx,sizeof(nx),T(S_NEXT_LVL_FMT),MINUTES_PER_LEVEL-into,pet.level()+1);
  uiPrintCenter(nx, by+30, UI_INK, 1);
  uiPrintCenter(T(S_EVO_LABEL), 220, UI_INK, 2);
  char evoBuf[64]; const char *evo; uint16_t evoCol=UI_INK;
  if(d.evolvesTo==0) evo=T(S_FINAL_FORM); else { int needed=d.evolveLevel+pet.careMistakes; if(pet.level()>=needed){ if(pet.lowestStat()>=40){evo=T(S_EVO_READY);evoCol=UI_BAR_OK;} else {evo=T(S_EVO_BLOCKED);evoCol=UI_BAR_BAD;} } else {snprintf(evoBuf,sizeof(evoBuf),T(S_EVO_IN_FMT),needed-pet.level());evo=evoBuf;} }
  uiPrintCenter(evo, 252, evoCol, 1);
  char ms[32]; snprintf(ms,sizeof(ms),T(S_MISTAKES_FMT),pet.careMistakes);
  uiPrintCenter(ms, 304, pet.careMistakes>0?UI_BAR_BAD:UI_INK, 1);
}

void renderCard() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, UI_BG_DAY);
  if (cardPage == 0) renderCardProfile();
  else if (cardPage == 1) renderCardStats();
  else if (cardPage == 2) renderCardMedals();
  else renderCardProgress();

  // indicador de 4 paginas + ayuda
  for (int i = 0; i < 4; i++) {
    if (i == cardPage) gfx->fillCircle(194 + i * 26, 374, 5, UI_INK);
    else gfx->drawCircle(194 + i * 26, 374, 4, UI_INK);
  }
  uiPrintCenter(T(S_BACK), 394, UI_INK, 1);
  gfx->flush();
}

// ---------- teclado para renombrar ----------
// Combined test build: Korean UI opens a compact 3-column Cheonjiin keyboard.
// Latin mode remains available with the ABC/한글 toggle.

static const char KB_LATIN[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ."; // 27 chars
#define KB_COLS 6
#define KB_X 40
#define KB_Y 150
#define KB_W 64
#define KB_H 52

#define KKO_X 74
#define KKO_Y 136
#define KKO_W 106
#define KKO_H 58

static void kbSyncLen() { nameLen=(uint8_t)strlen(nameBuf); }

static void drawKeyBox(int x,int y,int w,int h,const char *lab,bool warn=false,uint8_t ts=1) {
  gfx->fillRoundRect(x,y,w,h,8,warn?UI_BAR_WARN:UI_WHITE);
  gfx->drawRoundRect(x,y,w,h,8,UI_INK);
  if(lab && *lab) uiPrintAt(lab,x+(w-uiTextWidth(lab,ts))/2,y+(h-(ts<=1?19:24))/2,UI_INK,ts);
}

void openKeyboard() {
  kbOpen = true;
  strncpy(nameBuf, pet.nick, sizeof(nameBuf) - 1);
  nameBuf[sizeof(nameBuf) - 1] = 0;
  kbSyncLen();
  kbIme.resetCompose();
  kbHangulMode = (gLang == LANG_KO);
}

static void renderNameBuffer() {
  char pv[64]; kbIme.preview(nameBuf,pv,sizeof(pv));
  const char *show = pv[0] ? pv : "_";
  gfx->fillRoundRect(83, 82, 300, 43, 8, UI_WHITE);
  gfx->drawRoundRect(83, 82, 300, 43, 8, UI_INK);
  uint8_t ts = uiTextWidth(show,2) <= 274 ? 2 : 1;
  uiPrintAt(show, CX-uiTextWidth(show,ts)/2, ts==2?91:94, UI_INK, ts);
}

static void renderKeyboardHangul() {
  static const char *row0[3]={"ㅣ","ㆍ","ㅡ"};
  static const char *row1[3]={"ㄱㅋ","ㄴㄹ","ㄷㅌ"};
  static const char *row2[3]={"ㅂㅍ","ㅅㅎ","ㅈㅊ"};
  static const char *row3[3]={"ㅇㅁ","쌍","<-"};
  const char **rows[4]={row0,row1,row2,row3};
  for(int r=0;r<4;r++) for(int c=0;c<3;c++) {
    int x=KKO_X+c*KKO_W, y=KKO_Y+r*KKO_H;
    bool warn=(r==3 && c>=1);
    drawKeyBox(x,y,KKO_W-8,KKO_H-7,rows[r][c],warn,(r==0)?2:1);
  }
  drawKeyBox(92,374,128,48,"ABC",false,2);
  drawKeyBox(246,374,128,48,"확인",true,2);
  uiPrintCenter("천지인", 430, UI_TRACK, 1);
}

static void renderKeyboardLatin() {
  for (int i=0;i<30;i++) {
    int x=KB_X+(i%KB_COLS)*KB_W, y=KB_Y+(i/KB_COLS)*KB_H;
    bool warn=(i>=27);
    gfx->fillRoundRect(x,y,KB_W-6,KB_H-6,6,warn?UI_BAR_WARN:UI_WHITE);
    gfx->drawRoundRect(x,y,KB_W-6,KB_H-6,6,UI_INK);
    if(i<27) {
      char t[2]={KB_LATIN[i],0};
      gfx->setTextColor(UI_INK); gfx->setTextSize(2);
      gfx->setCursor(x+KB_W/2-6,y+KB_H/2-10); gfx->print(t);
    } else {
      const char *lab=(i==27)?"한글":(i==28?"<-":(gLang==LANG_KO?"확인":"OK"));
      if(i==28) {
        gfx->setTextColor(UI_INK); gfx->setTextSize(2);
        gfx->setCursor(x+KB_W/2-15,y+KB_H/2-10); gfx->print(lab);
      } else uiPrintAt(lab,x+(KB_W-6-uiTextWidth(lab,1))/2,y+13,UI_INK,1);
    }
  }
}

void renderKeyboard() {
  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX,CY,231,UI_BG_DAY);
  uiPrintCenter(kbHangulMode?"한글 이름":"ABC 이름",45,UI_INK,2);
  renderNameBuffer();
  if(kbHangulMode) renderKeyboardHangul(); else renderKeyboardLatin();
  gfx->flush();
}

static void keyboardConfirm() {
  if(kbHangulMode) kbIme.commit(nameBuf,sizeof(nameBuf));
  kbSyncLen();
  pet.rename(nameBuf);
  kbOpen=false;
}

static void keyboardTapHangul(int16_t x,int16_t y) {
  if(y>=374 && y<426) {
    if(x>=92 && x<220) {
      kbIme.commit(nameBuf,sizeof(nameBuf)); kbIme.resetCompose(); kbHangulMode=false; kbSyncLen(); return;
    }
    if(x>=246 && x<374) { keyboardConfirm(); return; }
  }
  int col=(x-KKO_X)/KKO_W, row=(y-KKO_Y)/KKO_H;
  if(x<KKO_X || col<0 || col>=3 || row<0 || row>=4) return;
  if(row==0) {
    static const uint8_t tok[3]={2,0,1}; // ㅣ, ㆍ, ㅡ
    kbIme.inputVowel(tok[col],nameBuf,sizeof(nameBuf));
  } else if(row==1) {
    kbIme.inputGroup((uint8_t)col,nameBuf,sizeof(nameBuf));          // ㄱㅋ ㄴㄹ ㄷㅌ
  } else if(row==2) {
    kbIme.inputGroup((uint8_t)(3+col),nameBuf,sizeof(nameBuf));      // ㅂㅍ ㅅㅎ ㅈㅊ
  } else {
    if(col==0) kbIme.inputGroup(6,nameBuf,sizeof(nameBuf));          // ㅇㅁ
    else if(col==1) kbIme.inputDouble();                            // 쌍자음
    else kbIme.backspace(nameBuf);
  }
  kbSyncLen();
}

static void keyboardTapLatin(int16_t x,int16_t y) {
  int col=(x-KB_X)/KB_W, row=(y-KB_Y)/KB_H;
  if(col<0||col>=KB_COLS||row<0||row>=5) return;
  int i=row*KB_COLS+col; if(i>=30) return;
  if(i<27) {
    if(HangulComposer::utf8Count(nameBuf)<HangulComposer::MAX_NAME_CP && nameLen+1<sizeof(nameBuf)) {
      nameBuf[nameLen++]=KB_LATIN[i]; nameBuf[nameLen]=0;
    }
  } else if(i==27) {
    kbIme.resetCompose(); kbHangulMode=true;
  } else if(i==28) {
    HangulComposer::popUtf8(nameBuf); kbSyncLen();
  } else keyboardConfirm();
}

void keyboardTap(int16_t x,int16_t y) {
  if(kbHangulMode) keyboardTapHangul(x,y);
  else keyboardTapLatin(x,y);
}

// ---------- galeria pokedex ----------

#define GAL_X 73
#define GAL_Y 84
#define GAL_CELL 80

// dibuja una miniatura centrada en su celda; sil=true la pinta en tinta
void drawThumb(const uint8_t *b, int x, int y, int s, bool sil) {
  uint8_t w = b[0], h = b[1], n = b[2];
  const uint8_t *pal = b + 3;
  const uint8_t *d = pal + n * 2;
  int ox = x + (GAL_CELL - w * s) / 2;
  int oy = y + (GAL_CELL - h * s) / 2;
  for (int r = 0; r < h; r++) {
    for (int c = 0; c < w; c++) {
      uint8_t idx = d[r * w + c];
      if (idx == 0xFF) continue;
      uint16_t col = sil ? INK_K : (uint16_t)(pal[idx * 2] | (pal[idx * 2 + 1] << 8));
      gfx->fillRect(ox + c * s, oy + r * s, s, s, col);
    }
  }
}

void renderGallery() {
  if (galleryDetail) {
    gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,UI_BG_DAY);
    const DexEntry &d=DEX_TBL[galleryDetail]; bool reg=pet.isRegistered(galleryDetail);
    char head[64]; snprintf(head,sizeof(head),"#%03d %s%s",galleryDetail,pet.isShinyRegistered(galleryDetail)?"*":"",reg?localizedPokeName(galleryDetail):"???");
    uint8_t ts=(uiTextWidth(head,3)<=380)?3:2; uiPrintCenter(head, ts==3?46:52, reg?d.accent:UI_INK, ts);
    if(galleryPmd.loaded) drawPmdActM(galleryPmd,PMD_IDLE,CX,300,reg?millis():0,true,!reg,6);
    else { const uint8_t *t=thumbs.get(galleryDetail); if(t) drawThumb(t,CX-GAL_CELL,135,4,!reg); }
    uiPrintCenter(T(S_DETAIL_BACK), 400, UI_INK, 1); gfx->flush(); return;
  }
  if(!galleryDirty) return; galleryDirty=false;
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,UI_BG_DAY);
  char head[32]; snprintf(head,sizeof(head),T(S_POKEDEX_FMT),pet.registeredCount()); uiPrintCenter(head, 30, UI_INK, 3);
  for(int r=0;r<4;r++) for(int c=0;c<4;c++) { int16_t dex=galleryPage*16+r*4+c+1; if(dex>151) break; int x=GAL_X+c*GAL_CELL,y=GAL_Y+r*GAL_CELL; const uint8_t *t=thumbs.get(dex); if(t){ drawThumb(t,x,y,2,!pet.isRegistered(dex)); if(pet.isShinyRegistered(dex)){ gfx->setTextColor(UI_BAR_WARN);gfx->setTextSize(2);gfx->setCursor(x+62,y+4);gfx->print("*"); }} else { char num[6];snprintf(num,sizeof(num),"%d",dex);gfx->setTextColor(UI_TRACK);gfx->setTextSize(2);gfx->setCursor(x+24,y+32);gfx->print(num);} }
  for(int i=0;i<10;i++){ if(i==galleryPage) gfx->fillCircle(170+i*14,436,4,UI_INK); else gfx->drawCircle(170+i*14,436,3,UI_INK); }
  gfx->flush();
}

void galleryTap(int16_t x, int16_t y) {
  if (galleryDetail) {  // volver a la rejilla
    galleryDetail = 0;
    galleryPmd.unload();
    galleryDirty = true;
    return;
  }
  if (y < 72) {  // tocar la cabecera = salir
    galleryOpen = false;
    galleryPmd.unload();
    return;
  }
  int c = (x - GAL_X) / GAL_CELL, r = (y - GAL_Y) / GAL_CELL;
  if (c < 0 || c > 3 || r < 0 || r > 3) return;
  int16_t dex = galleryPage * 16 + r * 4 + c + 1;
  if (dex > 151) return;
  galleryDetail = dex;
  galleryPmd.load(dex, pet.isShinyRegistered(dex));
}

void drawBattery() {
  int pc = batPercent();
  if (pc < 0) return;  // sin bateria conectada
  int x = CX - 14, y = 12, w = 24, h = 11;
  bool charging = batCharging();
  uint16_t col = charging ? UI_BAR_OK
                 : (pc >= 40) ? inkColor()
                 : (pc >= 15) ? UI_BAR_WARN
                              : UI_BAR_BAD;
  gfx->drawRoundRect(x, y, w, h, 2, col);
  gfx->fillRect(x + w, y + 3, 3, 5, col);  // borne
  if (charging) {
    // rayo de carga (zigzag) en vez de la barra de nivel
    uint16_t bolt = C565(0xff, 0xd9, 0x4a);
    int bx = x + w / 2;
    gfx->fillTriangle(bx + 3, y + 1, bx - 4, y + 6, bx + 1, y + 6, bolt);
    gfx->fillTriangle(bx - 1, y + 5, bx + 4, y + 5, bx - 3, y + 10, bolt);
  } else {
    int fw = (w - 4) * pc / 100;
    if (fw > 0) gfx->fillRect(x + 2, y + 2, fw, h - 4, col);
  }
}

void drawHeader(const char *name, uint16_t nameColor, const char *msg) {
  drawBattery();
  uiPrintCenter(name, 44, nameColor, 3);
  uiPrintCenter(msg, 82, inkColor(), 2);
}

// animacion de la ceremonia (10s): despedida = reverencia con corazones y se
// aleja caminando; escapada = se asusta y sale corriendo. Sustituye al idle.
void drawCeremony() {
  if (!pmd.loaded) { drawPet(); return; }  // respaldo si no hay sprite PMD
  uint32_t now = millis();
  float t = pet.ceremonyT();               // 0..1 a lo largo de los 10s
  bool panic = (pet.ceremony == CER_RUNAWAY);
  int x = CX, y = PET_GROUND;
  uint8_t act = PMD_IDLE;

  if (panic) {
    // final triste: penumbra azulada + lluvia
    for (int i = 0; i < 46; i++) {
      int rx = (i * 47 + now / 3) % 466;
      int ry = (i * 91 + now / 2) % 470;
      gfx->drawLine(rx, ry, rx - 3, ry + 12, C565(0x6a, 0x84, 0xb0));
    }
    bool fade = false;
    if (t < 0.30f) {                       // cabizbajo, temblando
      act = pmd.has(PMD_HURT) ? PMD_HURT : PMD_IDLE;
      x = CX + (int)(4 * sinf(now * 0.04f));
    } else {                               // se aleja despacio y se desvanece
      act = pmd.has(PMD_WALKL) ? PMD_WALKL : PMD_IDLE;
      x = CX - (int)(((t - 0.30f) / 0.70f) * (CX + 120));
      fade = (t > 0.6f) && ((now / 160) % 2 == 0);  // parpadea hacia la silueta
    }
    drawPmdAct(act, x, y, now, true, fade, 5);  // fade=silueta: se difumina al irse
    // lagrima cayendo del bicho
    if (t < 0.55f) {
      int ty = y - 150 + (int)((now / 6) % 40);
      gfx->fillRect(x + 6, ty, 3, 6, C565(0x9a, 0xc4, 0xe8));
    }
    return;
  }

  // despedida epica: halo dorado pulsante + chispas y corazones que ascienden
  int gcy = PET_GROUND - 96;
  for (int k = 0; k < 4; k++) {
    int r = 60 + k * 34 + (int)(10 * sinf(now * 0.02f));
    gfx->drawCircle(CX, gcy, r, C565(0xff, 0xdf, 0x8a));
  }
  for (int i = 0; i < 16; i++) {
    int px = (i * 71 + 28) % 466;
    int py = 410 - (int)((now / 8 + i * 70) % 360);   // suben y reaparecen abajo
    if (py < 30) continue;
    if (i % 4 == 0) drawMap(SPR_HEART, 32, px - 8, py - 8, 1, false);  // corazoncito
    else gfx->fillRect(px, py, 4, 4, (i % 2) ? C565(0xff, 0xe7, 0x9f) : C565(0xff, 0x9a, 0xc0));
  }

  if (t < 0.45f) {                         // reverencia / pose de despedida
    act = pmd.has(PMD_POSE) ? PMD_POSE : (pmd.has(PMD_NOD) ? PMD_NOD : PMD_IDLE);
  } else {                                 // se aleja por la derecha
    act = pmd.has(PMD_WALKR) ? PMD_WALKR : PMD_IDLE;
    x = CX + (int)(((t - 0.45f) / 0.55f) * (CX + 140));
  }
  drawPmdAct(act, x, y, now, true, false, 5);
  if (pet.showHeart())                     // corazon grande siguiendo al bicho
    drawMap(SPR_HEART, 32, x + 50, y - 190, 2, false);
}

// dialogo de decision (2 botones apilados): evolucionar/mantener o despedirse/quedaros
void drawChoiceDialog() {
  const char *q,*o1,*o2; uint16_t c1,c2,t1,t2;
  if(choiceKind==1){ q=T(S_EVO_Q);o1=T(S_EVO_TAP);o2=T(S_EVO_KEEP);c1=UI_BAR_BAD;t1=UI_WHITE;c2=UI_TRACK;t2=UI_INK; }
  else { q=T(S_FAR_Q);o1=T(S_FAR_GO);o2=T(S_FAR_STAY);c1=UI_BAR_WARN;t1=UI_INK;c2=UI_BAR_OK;t2=UI_WHITE; }
  gfx->fillRoundRect(73,156,320,188,16,UI_WHITE);gfx->drawRoundRect(73,156,320,188,16,UI_INK);
  uiPrintCenter(q,174,UI_INK,2);
  gfx->fillRoundRect(93,206,280,52,12,c1);uiPrintCenter(o1,220,t1,2);
  gfx->fillRoundRect(93,268,280,52,12,c2);uiPrintCenter(o2,282,t2,2);
}

// boton-CTA rojo y grande para evolucionar (pulsa para llamar la atencion)
void drawEvolveButton() {
  uint32_t now = millis();
  int p = (int)(5 * sinf(now * 0.006f));  // late: -5..5
  int x = EVO_BTN_X - p, y = EVO_BTN_Y - p, w = EVO_BTN_W + 2 * p, h = EVO_BTN_H + 2 * p;
  gfx->fillRoundRect(x, y, w, h, 18, UI_BAR_BAD);
  gfx->drawRoundRect(x, y, w, h, 18, UI_WHITE);
  gfx->drawRoundRect(x + 2, y + 2, w - 4, h - 4, 16, UI_WHITE);
  const char *t = T(S_EVO_TAP); uiPrintCenter(t, y+h/2-12, UI_WHITE, 2);
}

// boton-CTA dorado de despedida: "<nombre> quiere decirte algo..."
void drawFarewellButton() {
  uint32_t now = millis();
  int p = (int)(4 * sinf(now * 0.005f));
  int x = FAR_BTN_X - p, y = FAR_BTN_Y - p, w = FAR_BTN_W + 2 * p, h = FAR_BTN_H + 2 * p;
  gfx->fillRoundRect(x, y, w, h, 16, UI_BAR_WARN);
  gfx->drawRoundRect(x, y, w, h, 16, UI_INK);
  char buf[96];
  const char *nm = pet.nick[0] ? pet.nick : localizedPokeName(pet.speciesId);
  snprintf(buf, sizeof(buf), T(S_FAREWELL_BTN), nm);
  uiPrintCenter(buf, y+h/2-10, UI_INK, 1);
}

// boton-CTA sombrio de escapada por abandono: "<nombre> se siente abandonado..."
// (final triste: azul-gris oscuro, latido lento y apagado)
void drawRunawayButton() {
  uint32_t now = millis();
  int p = (int)(3 * sinf(now * 0.003f));
  int x = FAR_BTN_X - p, y = FAR_BTN_Y - p, w = FAR_BTN_W + 2 * p, h = FAR_BTN_H + 2 * p;
  gfx->fillRoundRect(x, y, w, h, 16, C565(0x3a, 0x44, 0x5a));
  gfx->drawRoundRect(x, y, w, h, 16, C565(0x70, 0x80, 0x98));
  char buf[96];
  const char *nm = pet.nick[0] ? pet.nick : localizedPokeName(pet.speciesId);
  snprintf(buf, sizeof(buf), T(S_RUNAWAY_BTN), nm);
  uiPrintCenter(buf, y+h/2-10, C565(0xc8,0xd2,0xe0), 1);
}

// animacion epica de evolucion: halo radial + rayos giratorios + parpadeo del
// sprite acelerando + chispas que salen disparadas + fogonazo final
void drawEvolveFX(uint32_t now) {
  float t = pet.evolveT();          // 0..1
  int cx = CX, cy = PET_GROUND - 96;

  // halo radial que crece y pulsa
  int halo = 36 + (int)(t * 150) + (int)(8 * sinf(now * 0.02f));
  for (int k = 0; k < 4; k++) {
    int r = halo - k * 7;
    if (r > 0) gfx->drawCircle(cx, cy, r, UI_WHITE);
  }
  // rayos giratorios desde el centro del bicho
  float base = now * 0.004f;
  for (int i = 0; i < 12; i++) {
    float a = base + i * (float)(PI / 6);
    int len = 90 + (int)(70 * (0.5f + 0.5f * sinf(now * 0.012f + i)));
    gfx->drawLine(cx, cy, cx + (int)(cosf(a) * len), cy + (int)(sinf(a) * len), UI_WHITE);
  }
  // parpadeo entre la forma ANTERIOR y la NUEVA (siluetas), acelerando; al
  // final (t>0.9) se queda fija en la nueva para el fogonazo de revelado
  int period = 60 + (int)(220 * (1.0f - t));
  bool showOld = t < 0.9f && evoPmd.loaded && ((now / period) % 2) == 0;
  if (showOld) drawPmdActM(evoPmd, PMD_IDLE, cx, PET_GROUND, 0, true, true, 5);
  else drawPmdAct(PMD_IDLE, cx, PET_GROUND, 0, true, true, 5);
  // chispas que salen disparadas
  for (int i = 0; i < 10; i++) {
    float a = i * (float)(PI / 5) + t * 4.0f;
    int d = (int)((now / 14 + i * 33) % 200);
    int sx = cx + (int)(cosf(a) * d), sy = cy + (int)(sinf(a) * d);
    gfx->fillRect(sx - 2, sy - 2, 5, 5, (i & 1) ? C565(0xff, 0xe0, 0x70) : UI_WHITE);
  }
  // fogonazo final antes de revelar la forma nueva
  if (t > 0.9f) gfx->fillCircle(cx, cy, (int)(300 * (t - 0.9f) / 0.1f), UI_WHITE);
}

void drawPet() {
  if (pmd.loaded) {
    drawPetPMD();
    return;
  }
  if (mon.loaded) {
    drawPetSD();
    return;
  }
  int fi = flashIdxForDex(pet.speciesId);
  if (fi < 0) {
    // sin SD y sin sprite de flash: aviso claro de que faltan sprites
    gfx->setTextColor(inkColor());
    gfx->setTextSize(6);
    gfx->setCursor(CX - 18, PET_CY - 80);
    gfx->print("?");
    const char *l1=T(S_NO_SPRITES); uiPrintCenter(l1,PET_CY-4,inkColor(),2);
    const char *l2=T(S_LOAD_SPRITES); uiPrintCenter(l2,PET_CY+22,inkColor(),1);
    return;
  }
  const Species &sp = SPECIES[fi];
  int s = sp.scale;
  int x = CX - 16 * s;
  int y = PET_CY - 16 * s;

  // animacion de evolucion: alterna la silueta de la forma anterior y la nueva
  if (pet.evolving()) {
    bool flash = (millis() / 300) % 2;
    int16_t showDex = (flash && pet.prevSpeciesId >= 0) ? pet.prevSpeciesId : pet.speciesId;
    int sfi = flashIdxForDex(showDex);
    if (sfi >= 0) {
      const Species &show = SPECIES[sfi];
      drawMap(show.sprite, SPRITE_H, CX - 16 * show.scale, PET_CY - 16 * show.scale, show.scale, flash);
    }
    return;
  }

  PetMood m = pet.mood();
  if (m == MOOD_HAPPY && (millis() / 500) % 2) y -= 6;  // saltito

  drawMap(sp.sprite, SPRITE_H, x, y, s, false);

  // expresiones superpuestas usando las anclas de la especie
  bool blink = (millis() % 3500 < 300);
  if (m == MOOD_SLEEPING || blink) {
    overlayEye(sp, x, y, s, sp.eyeColL);
    overlayEye(sp, x, y, s, sp.eyeColR);
  }
  if (m == MOOD_EATING) overlayMouth(sp, x, y, s, true);
  else if (m == MOOD_SAD) overlayMouth(sp, x, y, s, false);

  if (pet.showHeart()) drawMap(SPR_HEART, 32, x + 20 * s, y - 2 * s, 2, false);
}

// ---------- escena de bano ----------

void startBath() {
  if (pet.isEgg() || pet.sleeping || pet.ceremony || bathUntil) return;
  bathUntil = millis() + 3000;
  bathPending = true;
  int cx = (int)beh.x;
  for (auto &b : bubbles) {
    b.x = cx - 70 + random(140);
    b.y = PET_GROUND - random(150);
    b.r = 8 + random(16);
    b.ph = random(64);
  }
}

void drawBath() {
  uint32_t now = millis();
  if (!bathUntil) return;
  uint32_t left = bathUntil - now;
  if (left > 800) {
    // espuma: pompas meciendose y subiendo poco a poco
    float t = now / 220.0f;
    for (auto &b : bubbles) {
      int bx = b.x + (int)(sinf(t + b.ph) * 6);
      int by = b.y - (int)((3000 - left) / 90);
      gfx->fillCircle(bx, by, b.r, UI_WHITE);
      gfx->drawCircle(bx, by, b.r, 0x7E3D);
      gfx->fillCircle(bx - b.r / 3, by - b.r / 3, b.r / 4, UI_BG_DAY);
    }
  } else {
    // las pompas revientan: destellos
    for (int i = 0; i < 8; i++) {
      auto &b = bubbles[i];
      int sx = b.x + (i % 3) * 6 - 6, sy = b.y - 18;
      uint16_t col = (i % 2) ? UI_BAR_WARN : UI_WHITE;
      gfx->fillRect(sx - 6, sy - 1, 13, 3, col);
      gfx->fillRect(sx - 1, sy - 6, 3, 13, col);
    }
  }
}

// ---------- mascota PMD: comportamiento ----------

uint32_t pmdActTotalMs(const PmdAct &a) {
  uint32_t t = 0;
  for (uint8_t i = 0; i < a.frames; i++) t += a.ms[i];
  return t ? t : 100;
}

uint8_t pmdFrameAt(const PmdAct &a, uint32_t t, bool loop) {
  uint32_t total = pmdActTotalMs(a);
  if (!loop && t >= total) return a.frames - 1;
  t %= total;
  uint8_t i = 0;
  while (t >= a.ms[i]) {
    t -= a.ms[i];
    i = (i + 1) % a.frames;
  }
  return i;
}

// dibuja una accion anclada por la base (centro-x, suelo) y devuelve su escala
// dibuja una accion de un PmdMon concreto (m); drawPmdAct usa el global pmd
void drawPmdActM(PmdMon &m, uint8_t actId, int cx, int groundY, uint32_t t, bool loop, bool sil, uint8_t maxS) {
  const PmdAct &a = m.acts[actId];
  if (!a.frames) return;
  uint8_t sBase = m.acts[PMD_IDLE].h ? 170 / m.acts[PMD_IDLE].h : 5;
  if (sBase < 2) sBase = 2;
  if (sBase > maxS) sBase = maxS;
  uint8_t s = sBase;
  while (s > 2 && a.h * s > 250) s--;  // acciones con frame grande (ataque)
  uint8_t fi = pmdFrameAt(a, t, loop);
  const uint8_t *fr = a.data + (uint32_t)fi * a.w * a.h;
  // anclar por los pies (a.base), no por el alto del lienzo: asi las acciones
  // con padding distinto (Hurt, Eat...) quedan todas a la misma altura de suelo
  int x0 = cx - a.w * s / 2, y0 = groundY - (a.base ? a.base : a.h) * s;
  for (int r = 0; r < a.h; r++) {
    const uint8_t *row = fr + r * a.w;
    for (int c = 0; c < a.w; c++) {
      uint8_t idx = row[c];
      if (idx == 0xFF) continue;
      gfx->fillRect(x0 + c * s, y0 + r * s, s, s, sil ? INK_K : m.pal[idx]);
    }
  }
}
void drawPmdAct(uint8_t actId, int cx, int groundY, uint32_t t, bool loop, bool sil, uint8_t maxS) {
  drawPmdActM(pmd, actId, cx, groundY, t, loop, sil, maxS);
}

// elige el siguiente capricho del bicho cuando esta contento
void behNext() {
  uint32_t now = millis();
  beh.t0 = now;
  int r = random(100);
  if (r < 35 && (pmd.has(PMD_WALKL) || pmd.has(PMD_WALKR))) {
    beh.mode = 1;  // paseo
    beh.targetX = 150 + random(176);
    beh.until = now + 15000;
  } else if (r < 60) {
    // gesto aleatorio entre los disponibles
    // (Hop fuera: salta demasiado alto; Sit fuera: mira hacia atras)
    static const uint8_t flair[] = { PMD_POSE, PMD_NOD, PMD_BREATH };
    uint8_t pick[3], n = 0;
    for (uint8_t f : flair)
      if (pmd.has(f)) pick[n++] = f;
    if (n) {
      beh.mode = 2;
      beh.act = pick[random(n)];
      beh.until = now + pmdActTotalMs(pmd.acts[beh.act]);
      return;
    }
    beh.mode = 0;
    beh.until = now + 2000 + random(3000);
  } else {
    beh.mode = 0;  // mirar al frente
    beh.until = now + 2000 + random(3000);
  }
}

void drawPetPMD() {
  uint32_t now = millis();

  if (pet.evolving()) {
    drawEvolveFX(now);
    return;
  }
  if (evoPmd.loaded) evoPmd.unload();  // termino la evolucion: libera la forma anterior

  PetMood m = pet.mood();
  uint8_t act;
  bool loop = true;
  if (m == MOOD_SLEEPING && pmd.has(PMD_SLEEP)) {
    act = PMD_SLEEP;
    beh.mode = 0;
  } else if (m == MOOD_EATING && pmd.has(PMD_EAT)) {
    act = PMD_EAT;
    beh.t0 = 0;
  } else if (m == MOOD_SAD && pmd.has(PMD_HURT)) {
    act = PMD_HURT;
  } else {
    // contento: el planificador decide (idle / paseo / gesto)
    if (now > beh.until) behNext();
    if (beh.mode == 1) {
      float d = beh.targetX - beh.x;
      if (fabsf(d) < 4) {
        behNext();
        act = PMD_IDLE;
      } else {
        beh.x += (d > 0 ? 3.0f : -3.0f);
        act = (d > 0) ? PMD_WALKR : PMD_WALKL;
      }
    } else {
      act = (beh.mode == 2) ? beh.act : PMD_IDLE;
      loop = false;
    }
    if (!pmd.has(act)) act = PMD_IDLE;
  }

  drawPmdAct(act, (int)beh.x, PET_GROUND, now - beh.t0, loop || act == PMD_IDLE, false, 5);

  if (pet.showHeart()) drawMap(SPR_HEART, 32, (int)beh.x + 50, PET_GROUND - 190, 2, false);
}

// sprite animado desde la SD: zoom entero por pixel, frames a su ritmo
void drawPetSD() {
  int s = mon.scale;
  int w = mon.w * s, h = mon.h * s;
  int x = CX - w / 2;
  int y = PET_CY - h / 2;

  bool sil = false;
  if (pet.evolving()) {
    sil = (millis() / 300) % 2;
  } else if (pet.mood() == MOOD_HAPPY && (millis() / 500) % 2) {
    y -= 6;  // saltito
  }

  uint16_t fm = mon.frameMs ? mon.frameMs : 100;
  uint16_t fi = pet.sleeping ? 0 : (millis() / fm) % mon.frames;
  const uint8_t *fr = mon.data + (uint32_t)fi * mon.w * mon.h;
  for (int r = 0; r < mon.h; r++) {
    const uint8_t *row = fr + r * mon.w;
    for (int c = 0; c < mon.w; c++) {
      uint8_t idx = row[c];
      if (idx == 0xFF) continue;
      gfx->fillRect(x + c * s, y + r * s, s, s, sil ? INK_K : mon.pal[idx]);
    }
  }

  // emotes en vez de expresiones (los sprites importados no tienen anclas)
  if (pet.showHeart()) drawMap(SPR_HEART, 32, x + w - 30, y - 50, 2, false);
}

// ojo cerrado: borra el ojo 3x4 y dibuja el parpado
void overlayEye(const Species &sp, int x, int y, int s, int col) {
  gfx->fillRect(x + col * s, y + sp.eyeRow * s, 3 * s, 4 * s, sp.bodyColor);
  gfx->fillRect(x + col * s, y + (sp.eyeRow + 2) * s, 3 * s, s, INK_K);
}

// borra la sonrisa base y pinta boca abierta (comer) o ceno (triste)
void overlayMouth(const Species &sp, int x, int y, int s, bool open) {
  int mc = sp.mouthCol, mr = sp.mouthRow;
  gfx->fillRect(x + (mc - 3) * s, y + mr * s, 7 * s, 2 * s, sp.bodyColor);
  if (open) {
    gfx->fillRect(x + (mc - 2) * s, y + mr * s, 5 * s, 2 * s, INK_K);
  } else {
    gfx->fillRect(x + (mc - 2) * s, y + mr * s, 5 * s, s, INK_K);
    gfx->fillRect(x + (mc - 3) * s, y + (mr + 1) * s, s, s, INK_K);
    gfx->fillRect(x + (mc + 3) * s, y + (mr + 1) * s, s, s, INK_K);
  }
}

void drawPoops() {
  for (int i = 0; i < pet.poops; i++) {
    drawMap(SPR_POOP, 32, 36 + i * 46, 244, 2, false);
  }
}

void drawBars() {
  drawBar(78, 318, T(S_BAR_FOOD), pet.fullness);
  drawBar(244, 318, T(S_BAR_JOY), pet.joy);
  drawBar(78, 346, T(S_BAR_ENE), pet.energy);
  drawBar(244, 346, T(S_BAR_HYG), pet.hygiene);
}

void drawBar(int x, int y, const char *label, uint8_t val) {
  const uint8_t fs = (gLang == LANG_KO ? 3 : 2);
  uiPrintAt(label, x, y-5, inkColor(), fs);
  int bx, bw, bh;
  if (gLang == LANG_KO) {
    bx = x + uiTextWidth(label, fs) + 6;
    int right = (x < 200) ? 230 : 438;
    bw = right - bx;
    // 원형 화면 오른쪽의 행복/위생 바가 지나치게 길어 보이지 않도록
    // 먹이/체력과 같은 최대 길이로 맞춘다.
    if (bw > 104) bw = 104;
    if (bw < 46) bw = 46;
    bh = 12;
  } else {
    bx = x + 48; bw = 100; bh = 15;
  }
  uint16_t fill = (val >= 50) ? UI_BAR_OK : (val >= 25) ? UI_BAR_WARN : UI_BAR_BAD;
  gfx->fillRoundRect(bx, y+1, bw, bh, 4, UI_TRACK);
  int fw = (bw - 4) * val / 100;
  if (fw > 0) gfx->fillRoundRect(bx + 2, y + 3, fw, bh - 4, 3, fill);
}

void drawButtons() {
  for (int i = 0; i < 4; i++) {
    bool off = pet.sleeping && i != 2;  // durmiendo solo funciona LUZ
    int bx = buttons[i].cx - BTN_HALF, by = buttons[i].cy - BTN_HALF;
    if (!pet.sleeping) gfx->fillRoundRect(bx, by, 2 * BTN_HALF, 2 * BTN_HALF, 14, UI_WHITE);
    gfx->drawRoundRect(bx, by, 2 * BTN_HALF, 2 * BTN_HALF, 14, inkColor());
    if (!off) drawMap(buttons[i].icon, 16, buttons[i].cx - 16, buttons[i].cy - 16, 2, false);
  }
}

const char *eggMsg() {
  switch (pet.eggCracks()) {
    case 0: return T(S_EGG_TOUCH);
    case 1: return T(S_EGG_MOVES);
    default: return T(S_EGG_ALMOST);
  }
}

const char *statusMsg() {
  if (pet.evolving()) return T(S_EVOLVING);
  if (bathUntil) return (gLang == LANG_KO) ? "첨벙첨벙!" : "Splish splash!";
  if (pet.sleeping) return (gLang == LANG_KO) ? "쿨쿨..." : "Zzz...";
  if (pet.eating()) return T(S_EATING);
  if (pet.showHeart()) return T(S_LIKES);
  if (pet.fullness < 25) return T(S_HUNGRY);
  if (pet.hygiene < 25) return T(S_NEEDS_BATH);
  if (pet.energy < 25) return T(S_EXHAUSTED);
  if (pet.joy < 25) return T(S_SAD);
  if (pet.weight > 60) return T(S_CHUBBY);
  if (pet.shiny && pet.ageMinutes < 15) return T(S_IS_SHINY);
  return T(S_HAPPY);
}

// dibuja un mapa de n x n pixeles escalado; silhouette=true lo pinta en tinta
void drawMap(const char *const *map, int n, int x, int y, int s, bool silhouette) {
  for (int r = 0; r < n; r++) {
    for (int c = 0; c < n; c++) {
      char ch = map[r][c];
      if (ch == '.') continue;
      gfx->fillRect(x + c * s, y + r * s, s, s, silhouette ? INK_K : spriteColor(ch));
    }
  }
}

// Services and hardware power transitions are kept together for auditability.
#include "power_runtime.inc"
