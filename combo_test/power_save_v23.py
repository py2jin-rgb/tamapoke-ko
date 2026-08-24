from pathlib import Path
import re, shutil, subprocess

root=Path('source_combo/TamaPoke')
ino=root/'TamaPoke.ino'
s=ino.read_text(encoding='utf-8')


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

# Run only after the final proven v2.2.4 real-device patch.
s,n=re.subn(r'#define FW_VERSION "2\.2-ko-combo-arcade-fix224"','#define FW_VERSION "2.3-ko-combo-battery"',s,count=1)
if n!=1: raise SystemExit('power v2.3 firmware version marker missing')
if '#include <Preferences.h>' not in s: s='#include <Preferences.h>\n'+s

marker='uint8_t dimStage = 0;'
if marker not in s: raise SystemExit('power v2.3 dimStage marker missing')
power=r'''uint8_t dimStage = 0;

// ---------- Battery Edition v2.3 (combo only) ----------
static Preferences powerPrefs;
static bool powerPrefsReady=false;
static uint8_t powerBrightnessPct=50;  // 25/50/75/100, persisted in NVS
static bool powerCpuEco=false;
static uint32_t powerNoticeUntil=0;

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
'''
s=s.replace(marker,power,1)

# Replace the old 90 s / 5 min dimmer.  Keep the exact panel brightness API that
# the original firmware already uses on this CO5300 board.  Alarm wake explicitly
# clears screenOff so an alarm can never ring behind a black display.
s=replace_function(s,'void updateBrightness(uint32_t now)',r'''void updateBrightness(uint32_t now) {
  if (alarmRinging()) {
    screenOff=false;
    lastInteract=now;
  }
  if (pet.evolving() || pet.ceremony || pet.eating() || pet.showHeart()) lastInteract=now;

  powerInitOnce();
  const uint32_t idle=now-lastInteract;
  if (manualClockView) dimStage=(idle>=30000UL)?1:0;
  else dimStage=(idle>=120000UL)?2:(idle>=30000UL)?1:0;

  uint8_t target=powerRawFromPct(powerBrightnessPct);
  if (pet.sleeping && target>51) target=51;  // <=20% while sleeping
  if (dimStage==1 && target>64) target=64;  // <=25% after 30 s
  if (dimStage==2 || screenOff) target=0;   // AMOLED black after 2 min/manual off

  static uint8_t current=255;
  if(target!=current) {
    current=target;
    panel->setBrightness(target);
  }

  // No deep sleep in v2.3: touch, PWR, RTC and alarm logic remain live.
  const bool eco=(target==0);
  if(eco && !powerCpuEco) {
    setCpuFrequencyMhz(80);
    powerCpuEco=true;
  } else if(!eco && powerCpuEco) {
    setCpuFrequencyMhz(240);
    powerCpuEco=false;
  }
}''')

# Preserve the complete v2.2.4 modal list. Only change the final PWR decision:
# while the intentional clock face is open, PWR cycles user brightness.
needle='''        if (modalOpen) {
          screenOff = !screenOff;
          if (!screenOff) lastInteract = now;
        } else {
          screenOff = false;
          manualClockView = !manualClockView;
          lastInteract = now;
        }'''
replacement='''        if (manualClockView && !modalOpen) {
          powerCycleBrightness();
        } else if (modalOpen) {
          screenOff = !screenOff;
          if (!screenOff) lastInteract = now;
        } else {
          screenOff = false;
          manualClockView = !manualClockView;
          lastInteract = now;
        }'''
if needle not in s: raise SystemExit('power v2.3 final PWR branch marker missing')
s=s.replace(needle,replacement,1)

# Do not depend on the exact final v2.2.4 render-condition text: several game
# passes expand that condition.  Instead throttle immediately before the unique
# lastRender condition.  All pet/input/alarm work above it still runs every loop.
render_marker='  if (now - lastRender >='
ri=s.find(render_marker)
if ri<0: raise SystemExit('power v2.3 final lastRender marker missing')
guard='''  // Battery Edition render throttle: logic stays responsive while QSPI/AMOLED work drops sharply.\n  if ((screenOff || dimStage >= 2) && now - lastRender < 1000UL) return;\n  if (dimStage == 1 && now - lastRender < 250UL) return;\n'''
s=s[:ri]+guard+s[ri:]

# Optional visual feedback when cycling brightness on the manual clock face.
clock_m=re.search(r'void renderStandbyClock\(\)\s*\{',s)
if clock_m:
    start=clock_m.start(); brace=s.find('{',clock_m.start(),clock_m.end()); depth=0; end=None
    for i in range(brace,len(s)):
        if s[i]=='{': depth+=1
        elif s[i]=='}':
            depth-=1
            if depth==0: end=i+1; break
    if end:
        fn=s[start:end]; flush_marker='  gfx->flush();\n}'
        if flush_marker in fn:
            notice=r'''  if ((int32_t)(powerNoticeUntil-millis())>0) {
    char pb[18]; snprintf(pb,sizeof(pb),"BRIGHT %u%%",powerBrightnessPct);
    gfx->fillRoundRect(CX-76,252,152,30,15,C565(0x18,0x25,0x42));
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(1); gfx->setCursor(CX-45,262); gfx->print(pb);
  }
  gfx->flush();
}'''
            fn=fn.rsplit(flush_marker,1)[0]+notice
            s=s[:start]+fn+s[end:]

# Source-level invariants before spending time compiling.
for must in ('2.3-ko-combo-battery','powerBrightnessPct','setCpuFrequencyMhz(80)',
             'arcRenderTetris','arcRenderSnake','arcRenderMine','startMole','startRps','startQuiz151'):
    if must not in s: raise SystemExit(f'power v2.3 invariant missing: {must}')
if s.count('Battery Edition render throttle') != 1:
    raise SystemExit('power v2.3 render throttle duplicate/missing')

ino.write_text(s,encoding='utf-8')

# Compile the exact final ③ source after all battery changes.
fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_combo')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file(): raise SystemExit('v2.3 battery combo binary missing')
print('v2.3 combo Battery Edition compiled successfully')

# Update the generated installer card. Final binary/manifest is created by pages.yml.
page=Path('site/index.html'); html=page.read_text(encoding='utf-8')
html=html.replace('manifest-combo.json?v=userfix21','manifest-combo.json?v=battery23',1)
html=re.sub(r'(천지인[^<]{0,80})v2\.2(?:\.\d+)?',r'\1v2.3 Battery',html,count=1)
anchor='✓ v2.1: 성공 타격음 강화 · 시계 포켓몬 배경박스 제거 · 151퀴즈 포켓몬 확대/매번 랜덤'
if anchor in html:
    html=html.replace(anchor,anchor+'<br>✓ Battery: 밝기 25/50/75/100 저장 · 30초 감광 · 2분 AMOLED OFF · CPU 80MHz 절전',1)
page.write_text(html,encoding='utf-8')
