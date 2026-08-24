from pathlib import Path
import re, shutil, subprocess

root=Path('source_combo/TamaPoke')
ino=root/'TamaPoke.ino'
s=ino.read_text(encoding='utf-8')

# ---- helpers ---------------------------------------------------------------
def replace_once(old,new,label):
    global s
    if old not in s:
        raise SystemExit(f'power v2.3 marker missing: {label}')
    s=s.replace(old,new,1)

def insert_into_function(text, signature, code, at_start=True):
    m=re.search(re.escape(signature)+r'\s*\{',text)
    if not m: raise SystemExit(f'power v2.3 function missing: {signature}')
    brace=text.find('{',m.start(),m.end())
    if at_start:
        return text[:brace+1]+'\n'+code+'\n'+text[brace+1:]
    raise NotImplementedError

# Version marker after the real-device v2.2.4 pass.
s,n=re.subn(r'#define FW_VERSION "2\.2-ko-combo-arcade-fix224"',
            '#define FW_VERSION "2.3-ko-combo-battery"',s,count=1)
if n!=1: raise SystemExit('power v2.3 firmware version marker missing')

# Preferences is an ESP32 Arduino core library; no extra dependency is needed.
if '#include <Preferences.h>' not in s:
    s='#include <Preferences.h>\n'+s

# Insert power manager beside the already-proven standby state.  The Waveshare
# CO5300 Arduino driver exposes Display_Brightness(0..255) in the official demo.
marker='bool gestureFromStandby = false;\nbool manualClockView = false;  // PWR short press toggles game <-> clock view'
if marker not in s:
    raise SystemExit('power v2.3 standby-state marker missing')
power=r'''bool gestureFromStandby = false;
bool manualClockView = false;  // PWR short press toggles game <-> clock view

// ---------- Battery Edition v2.3 (combo only) ----------
static Preferences powerPrefs;
static bool powerPrefsReady=false;
static uint8_t powerBrightnessPct=75;   // user level: 25/50/75/100
static uint8_t powerAppliedPct=255;     // impossible sentinel
static bool powerCpuEco=false;
static uint32_t powerNoticeUntil=0;

static uint8_t powerPctToRaw(uint8_t pct) {
  if (pct>100) pct=100;
  return (uint8_t)((uint16_t)pct*255U/100U);
}

static void powerSetDisplayPct(uint8_t pct) {
  if (pct==powerAppliedPct) return;
  powerAppliedPct=pct;
  gfx->Display_Brightness(powerPctToRaw(pct));
}

static void powerInitOnce() {
  if (powerPrefsReady) return;
  powerPrefsReady=true;
  powerPrefs.begin("tpk-power", false);
  uint8_t saved=powerPrefs.getUChar("bright",75);
  if (saved!=25 && saved!=50 && saved!=75 && saved!=100) saved=75;
  powerBrightnessPct=saved;
  powerSetDisplayPct(powerBrightnessPct);
}

static void powerCycleBrightness() {
  powerInitOnce();
  if (powerBrightnessPct==25) powerBrightnessPct=50;
  else if (powerBrightnessPct==50) powerBrightnessPct=75;
  else if (powerBrightnessPct==75) powerBrightnessPct=100;
  else powerBrightnessPct=25;
  powerPrefs.putUChar("bright",powerBrightnessPct);
  powerSetDisplayPct(powerBrightnessPct);
  powerNoticeUntil=millis()+1800UL;
  sfxPlay(SFX_TAP);
}

static void powerActivityNow() {
  lastInteract=millis();
  powerInitOnce();
  if (powerCpuEco) { setCpuFrequencyMhz(240); powerCpuEco=false; }
  powerSetDisplayPct(powerBrightnessPct);
}

static void powerService() {
  powerInitOnce();
  const uint32_t idle=millis()-lastInteract;

  // Manual clock view is intentional desk-clock use: keep it readable, but at
  // a capped level to avoid running the AMOLED at full output for hours.
  if (manualClockView) {
    if (powerCpuEco) { setCpuFrequencyMhz(240); powerCpuEco=false; }
    uint8_t p=powerBrightnessPct>75?75:powerBrightnessPct;
    powerSetDisplayPct(p);
    return;
  }

  // 0-30 s: chosen brightness. 30-120 s: dim clock. 120 s+: AMOLED black and
  // CPU reduced to 80 MHz. Touch/button polling remains alive so wake is safe.
  if (idle < 30000UL) {
    if (powerCpuEco) { setCpuFrequencyMhz(240); powerCpuEco=false; }
    powerSetDisplayPct(powerBrightnessPct);
  } else if (idle < 120000UL) {
    if (powerCpuEco) { setCpuFrequencyMhz(240); powerCpuEco=false; }
    uint8_t dim=powerBrightnessPct>25?25:powerBrightnessPct;
    powerSetDisplayPct(dim);
  } else {
    powerSetDisplayPct(0);
    if (!powerCpuEco) { setCpuFrequencyMhz(80); powerCpuEco=true; }
  }
}
'''
s=s.replace(marker,power,1)

# PWR short press while the manual clock is already open cycles brightness.
old=r'''    if (pwrShortPressed()) {
      if (alarmRinging()) {
        alarmStop();
        audioAlarmStop();
        alarmNotice = 2;
        alarmNoticeUntil = now + 3200;
        screenOff = false;
        manualClockView = false;
        lastInteract = now;
      } else {
        const bool modalOpen = alarmNotice || clockOpen || gameOpen || sackOpen ||
          galleryOpen || kbOpen || cardOpen || pet.awaitingStarter() || pet.ceremony ||
          confirmUntil || choiceKind || feedMenuUntil || bathUntil;
        if (modalOpen) {
          screenOff = !screenOff;
          if (!screenOff) lastInteract = now;
        } else {
          screenOff = false;
          manualClockView = !manualClockView;
          lastInteract = now;
        }
      }
    }'''
new=r'''    if (pwrShortPressed()) {
      if (alarmRinging()) {
        alarmStop();
        audioAlarmStop();
        alarmNotice = 2;
        alarmNoticeUntil = now + 3200;
        screenOff = false;
        manualClockView = false;
        powerActivityNow();
      } else {
        const bool modalOpen = alarmNotice || clockOpen || gameOpen || sackOpen ||
          galleryOpen || kbOpen || cardOpen || pet.awaitingStarter() || pet.ceremony ||
          confirmUntil || choiceKind || feedMenuUntil || bathUntil;
        if (manualClockView && !modalOpen) {
          // Clock view: PWR cycles 25/50/75/100%; tap the face to exit clock.
          powerCycleBrightness();
          lastInteract=now;
        } else if (modalOpen) {
          screenOff = !screenOff;
          if (!screenOff) powerActivityNow();
        } else {
          screenOff = false;
          manualClockView = !manualClockView;
          powerActivityNow();
        }
      }
    }'''
replace_once(old,new,'PWR brightness control')

# Every loop services power state. Existing touch/game handlers already update
# lastInteract, so any normal interaction restores the selected brightness.
s=insert_into_function(s,'void loop()','  powerService();')

# Whenever existing code assigns the interaction timestamp, wake display/CPU on
# the following service pass. No touch-controller sleep is used in this release.

# Add a tiny brightness notice to standby clock just before its final flush.
# This is deliberately optional: if renderer shape changes, power saving still builds.
clock_m=re.search(r'void renderStandbyClock\(\)\s*\{',s)
if clock_m:
    start=clock_m.start(); brace=s.find('{',clock_m.start(),clock_m.end()); depth=0; end=None
    for i in range(brace,len(s)):
        if s[i]=='{': depth+=1
        elif s[i]=='}':
            depth-=1
            if depth==0: end=i+1; break
    if end:
        fn=s[start:end]
        needle='  gfx->flush();\n}'
        notice=r'''  if ((int32_t)(powerNoticeUntil-millis())>0) {
    char pb[18]; snprintf(pb,sizeof(pb),"BRIGHT %u%%",powerBrightnessPct);
    gfx->fillRoundRect(CX-72,250,144,30,15,C565(0x18,0x25,0x42));
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(1); gfx->setCursor(CX-42,261); gfx->print(pb);
  }
  gfx->flush();
}'''
        if needle in fn:
            fn=fn.rsplit(needle,1)[0]+notice
            s=s[:start]+fn+s[end:]

ino.write_text(s,encoding='utf-8')

# Recompile the exact final combo source after power changes.
fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_combo')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file(): raise SystemExit('v2.3 battery combo binary missing')
print('v2.3 combo Battery Edition compiled successfully')

# Installer card only; manifest binary is generated by the workflow afterwards.
page=Path('site/index.html')
html=page.read_text(encoding='utf-8')
html=html.replace('v2.2.4','v2.3 Battery',1)
html=html.replace('manifest-combo.json?v=userfix21','manifest-combo.json?v=battery23',1)
# Add a compact feature line if the combo card still contains the known v2.1 line.
anchor='✓ v2.1: 성공 타격음 강화 · 시계 포켓몬 배경박스 제거 · 151퀴즈 포켓몬 확대/매번 랜덤'
if anchor in html:
    html=html.replace(anchor,anchor+'<br>✓ Battery: 밝기 25/50/75/100 저장 · 30초 자동감광 · 2분 화면OFF · 80MHz 절전',1)
page.write_text(html,encoding='utf-8')
