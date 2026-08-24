from pathlib import Path
import re, shutil, subprocess

root=Path('source_combo/TamaPoke')
ino=root/'TamaPoke.ino'
s=ino.read_text(encoding='utf-8')


def replace_once(old,new,label):
    global s
    if old not in s:
        raise SystemExit(f'power v2.3 marker missing: {label}')
    s=s.replace(old,new,1)


def replace_function(text, signature, new_func):
    m=re.search(re.escape(signature)+r'\s*\{',text)
    if not m:
        raise SystemExit(f'power v2.3 function missing: {signature}')
    start=m.start(); brace=text.find('{',m.start(),m.end()); depth=0; end=None
    for i in range(brace,len(text)):
        if text[i]=='{': depth+=1
        elif text[i]=='}':
            depth-=1
            if depth==0:
                end=i+1; break
    if end is None: raise SystemExit(f'power v2.3 closing brace missing: {signature}')
    return text[:start]+new_func+text[end:]

# Final ③ firmware version after the proven v2.2.4 real-device pass.
s,n=re.subn(r'#define FW_VERSION "2\.2-ko-combo-arcade-fix224"',
            '#define FW_VERSION "2.3-ko-combo-battery"',s,count=1)
if n!=1: raise SystemExit('power v2.3 firmware version marker missing')

if '#include <Preferences.h>' not in s:
    s='#include <Preferences.h>\n'+s

# Add persistent user brightness and CPU eco state beside the existing AMOLED
# dimStage state. We keep the original touch wake logic intact.
marker='uint8_t dimStage = 0;'
if marker not in s:
    raise SystemExit('power v2.3 dimStage marker missing')
power=r'''uint8_t dimStage = 0;

// ---------- Battery Edition v2.3 (combo only) ----------
static Preferences powerPrefs;
static bool powerPrefsReady=false;
static uint8_t powerBrightnessPct=50;  // 25/50/75/100, saved in NVS
static bool powerCpuEco=false;
static uint32_t powerNoticeUntil=0;

static uint8_t powerRawFromPct(uint8_t pct) {
  if (pct>100) pct=100;
  return (uint8_t)((uint16_t)pct*255U/100U);
}

static void powerInitOnce() {
  if (powerPrefsReady) return;
  powerPrefsReady=true;
  powerPrefs.begin("tpk-power",false);
  uint8_t v=powerPrefs.getUChar("bright",50);
  if (v!=25 && v!=50 && v!=75 && v!=100) v=50;
  powerBrightnessPct=v;
}

static void powerCycleBrightness() {
  powerInitOnce();
  if (powerBrightnessPct==25) powerBrightnessPct=50;
  else if (powerBrightnessPct==50) powerBrightnessPct=75;
  else if (powerBrightnessPct==75) powerBrightnessPct=100;
  else powerBrightnessPct=25;
  powerPrefs.putUChar("bright",powerBrightnessPct);
  lastInteract=millis();
  powerNoticeUntil=millis()+1800UL;
  sfxPlay(SFX_TAP);
}
'''
s=s.replace(marker,power,1)

# Replace the original 90 s / 5 min dimmer with a more aggressive battery path.
# Important: panel->setBrightness() is already the proven display API used by
# TamaPoke on this exact CO5300 board, so no new panel driver path is introduced.
s=replace_function(s,'void updateBrightness(uint32_t now)',r'''void updateBrightness(uint32_t now) {
  // Visible game/pet events must wake the display just like the original code.
  if (pet.evolving() || pet.ceremony || pet.eating() || pet.showHeart() || alarmRinging()) {
    lastInteract=now;
  }

  powerInitOnce();
  const uint32_t idle=now-lastInteract;

  // Manual clock is deliberate desk-clock use: never turn it fully off, but
  // after 30 s cap it to 25% so leaving the clock on does not run the AMOLED hot.
  if (manualClockView) dimStage=(idle>=30000UL)?1:0;
  else dimStage=(idle>=120000UL)?2:(idle>=30000UL)?1:0;

  uint8_t target=powerRawFromPct(powerBrightnessPct);
  if (pet.sleeping && target>51) target=51;       // <=20% while pet sleeps

  if (dimStage==1 && target>64) target=64;       // <=25% after 30 s
  if (dimStage==2) target=0;                     // AMOLED off after 2 min
  if (screenOff) target=0;                       // PWR manual screen off

  static uint8_t current=255;
  if (target!=current) {
    current=target;
    panel->setBrightness(target);
  }

  // At true black there is no reason to keep the S3 at 240 MHz. We deliberately
  // do NOT enter deep sleep: touch, PWR polling, RTC and alarm remain alive.
  const bool eco=(target==0);
  if (eco && !powerCpuEco) {
    setCpuFrequencyMhz(80);
    powerCpuEco=true;
  } else if (!eco && powerCpuEco) {
    setCpuFrequencyMhz(240);
    powerCpuEco=false;
  }
}''')

# PWR behavior: on the manual clock face, a short press cycles brightness.
# A screen tap still exits the clock as before. Everywhere else retains the
# existing alarm/modal/PWR semantics from stability2.
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
        lastInteract = now;
      } else {
        const bool modalOpen = alarmNotice || clockOpen || gameOpen || sackOpen ||
          galleryOpen || kbOpen || cardOpen || pet.awaitingStarter() || pet.ceremony ||
          confirmUntil || choiceKind || feedMenuUntil || bathUntil;
        if (manualClockView && !modalOpen) {
          powerCycleBrightness();
        } else if (modalOpen) {
          screenOff = !screenOff;
          if (!screenOff) lastInteract = now;
        } else {
          screenOff = false;
          manualClockView = !manualClockView;
          lastInteract = now;
        }
      }
    }'''
replace_once(old,new,'PWR brightness cycle')

# When the AMOLED is off we also stop wasting QSPI bandwidth redrawing at 10 fps.
# Input/pet/alarm logic still runs every loop. This replacement is optional across
# source revisions, but mandatory on the current v2.2.4 source.
pat=re.compile(r'''if \(now - lastRender >= \(uint32_t\)\(\(gameOpen \|\| sackOpen\) \? 85 : 100\)\) \{''')
rep='''uint32_t powerFrameMs = (screenOff || dimStage >= 2) ? 1000UL : (dimStage == 1 ? 250UL : ((gameOpen || sackOpen) ? 85UL : 100UL));\n  if (now - lastRender >= powerFrameMs) {'''
s,n=pat.subn(rep,s,count=1)
if n!=1:
    raise SystemExit('power v2.3 render cadence marker missing')

# Optional on-screen confirmation while cycling brightness in manual clock mode.
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
        if needle in fn:
            notice=r'''  if ((int32_t)(powerNoticeUntil-millis())>0) {
    char pb[18]; snprintf(pb,sizeof(pb),"BRIGHT %u%%",powerBrightnessPct);
    gfx->fillRoundRect(CX-76,252,152,30,15,C565(0x18,0x25,0x42));
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(1); gfx->setCursor(CX-45,262); gfx->print(pb);
  }
  gfx->flush();
}'''
            fn=fn.rsplit(needle,1)[0]+notice
            s=s[:start]+fn+s[end:]

ino.write_text(s,encoding='utf-8')

# Compile the exact final ③ combo after all battery changes.
fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_combo')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file(): raise SystemExit('v2.3 battery combo binary missing')
print('v2.3 combo Battery Edition compiled successfully')

# Installer card. The workflow creates the final manifest after this script.
page=Path('site/index.html')
html=page.read_text(encoding='utf-8')
html=html.replace('manifest-combo.json?v=userfix21','manifest-combo.json?v=battery23',1)
# Later arcade page passes may already have a v2.2.x title, so update flexibly.
html=re.sub(r'(천지인[^<]{0,80})v2\.2(?:\.\d+)?',r'\1v2.3 Battery',html,count=1)
anchor='✓ v2.1: 성공 타격음 강화 · 시계 포켓몬 배경박스 제거 · 151퀴즈 포켓몬 확대/매번 랜덤'
if anchor in html:
    html=html.replace(anchor,anchor+'<br>✓ Battery: 밝기 25/50/75/100 저장 · 30초 감광 · 2분 AMOLED OFF · CPU 80MHz 절전',1)
page.write_text(html,encoding='utf-8')
