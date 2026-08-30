from pathlib import Path
import shutil, subprocess

ROOT=Path('source_ota/TamaPoke')
ino=ROOT/'TamaPoke.ino'
audio=ROOT/'audio.cpp'
audio_h=ROOT/'audio.h'
for p in (ino,audio,audio_h):
    if not p.is_file(): raise SystemExit(f'volume v2.6 missing source: {p}')

s=ino.read_text(encoding='utf-8')
a=audio.read_text(encoding='utf-8')
h=audio_h.read_text(encoding='utf-8')

# ⑤ only: OTA 2.5 -> OTA + persistent five-step volume 2.6.
s=s.replace('#define FW_VERSION "2.5-ko-combo-ota"','#define FW_VERSION "2.6-ko-combo-ota-volume"',1)
s=s.replace('static const uint16_t OTA_BUILD=250;','static const uint16_t OTA_BUILD=260;',1)
if '2.6-ko-combo-ota-volume' not in s or 'OTA_BUILD=260' not in s:
    raise SystemExit('volume v2.6 firmware/build marker patch failed')

# Audio is I2S PCM into the ES8311 DAC. Scale the generated PCM amplitude so
# this is real volume control rather than simply muting the amplifier.
anchor='static bool gOn = true;\n'
if anchor not in a: raise SystemExit('volume audio state anchor missing')
a=a.replace(anchor,anchor+'static uint8_t gVolumePct = 100;\n',1)
old='  const int16_t amp = 5000;'
new='  const int16_t amp = (int16_t)(5000L * gVolumePct / 100L);'
if old not in a: raise SystemExit('volume PCM amplitude anchor missing')
a=a.replace(old,new,1)
old='''  gOn = p.getBool("snd", true);\n  p.end();'''
new='''  gOn = p.getBool("snd", true);\n  gVolumePct = p.getUChar("vol", 100);\n  if (gVolumePct!=0 && gVolumePct!=25 && gVolumePct!=50 && gVolumePct!=75 && gVolumePct!=100) gVolumePct=100;\n  p.end();'''
if old not in a: raise SystemExit('volume NVS load anchor missing')
a=a.replace(old,new,1)
a=a.replace('if (gReady && gOn && gQ) xQueueSend(gQ, &id, 0);','if (gReady && gOn && gVolumePct>0 && gQ) xQueueSend(gQ, &id, 0);',1)
end='bool audioEnabled() { return gOn; }'
extra='''bool audioEnabled() { return gOn; }\n\nvoid audioSetVolume(uint8_t pct) {\n  if (pct!=0 && pct!=25 && pct!=50 && pct!=75 && pct!=100) pct=100;\n  gVolumePct=pct;\n  Preferences p;\n  p.begin("tamapoke", false);\n  p.putUChar("vol", gVolumePct);\n  p.end();\n}\nuint8_t audioVolume() { return gVolumePct; }'''
if end not in a: raise SystemExit('volume audio API anchor missing')
a=a.replace(end,extra,1)
if 'void audioSetVolume(uint8_t pct);' not in h:
    h += '\nvoid audioSetVolume(uint8_t pct);\nuint8_t audioVolume();\n'

# Add a dedicated volume control pill to the Wi-Fi update screen. Touch cycles
# 0 -> 25 -> 50 -> 75 -> 100 -> 0 and the value is saved immediately in NVS.
pump='static void otaPump(){ if(otaSetupAp) otaServer.handleClient(); if(otaOpen) lastInteract=millis(); }\n'
volfn=r'''static void otaVolumeNext(){
  uint8_t v=audioVolume();
  uint8_t n=(v==0)?25:(v==25)?50:(v==50)?75:(v==75)?100:0;
  audioSetVolume(n);
  otaMsg=String("VOLUME ")+n+"%";
  if(n>0) sfxPlay(SFX_TAP);
}
'''
if pump not in s: raise SystemExit('volume OTA pump anchor missing')
s=s.replace(pump,pump+volfn,1)

tap='''  if(otaState==2 || otaState==3 || otaState==4) return;\n  if(y>=278 && y<=342){ otaStartSetupAp(); return; }'''
tapnew='''  if(otaState==2 || otaState==3 || otaState==4) return;\n  if(y>=220 && y<=268){ otaVolumeNext(); return; }\n  if(y>=278 && y<=342){ otaStartSetupAp(); return; }'''
if tap not in s: raise SystemExit('volume OTA touch anchor missing')
s=s.replace(tap,tapnew,1)

status='''  if(otaState==1){ uiPrintCenter(koOr("휴대폰 Wi-Fi에서 TamaPoke-Update 연결","CONNECT PHONE TO TamaPoke-Update"),244,UI_INK,1); uiPrintCenter("192.168.4.1",262,UI_TRACK,1); }\n  else uiPrintCenter(otaMsg.c_str(),250,otaState==6?UI_BAR_WARN:UI_INK,1);\n  gfx->fillRoundRect(68,278,330,64,16,C565(0x7f,0xc7,0xa0));'''
statusnew='''  if(otaState==1){ uiPrintCenter(koOr("휴대폰 Wi-Fi에서 TamaPoke-Update 연결","CONNECT PHONE TO TamaPoke-Update"),194,UI_INK,1); uiPrintCenter("192.168.4.1",208,UI_TRACK,1); }\n  else uiPrintCenter(otaMsg.c_str(),204,otaState==6?UI_BAR_WARN:UI_INK,1);\n  char volb[28]; snprintf(volb,sizeof(volb),"VOLUME %u%%",audioVolume());\n  gfx->fillRoundRect(98,220,270,48,14,C565(0xd7,0xe0,0xf0));\n  gfx->drawRoundRect(98,220,270,48,14,C565(0x6b,0x78,0x94));\n  uiPrintCenter(volb,236,UI_INK,2);\n  gfx->fillRoundRect(68,278,330,64,16,C565(0x7f,0xc7,0xa0));'''
if status not in s: raise SystemExit('volume OTA render anchor missing')
s=s.replace(status,statusnew,1)

for must in ('audioSetVolume','audioVolume()','VOLUME %u%%','OTA_BUILD=260','2.6-ko-combo-ota-volume'):
    if must not in s+a+h: raise SystemExit('volume v2.6 invariant missing: '+must)

ino.write_text(s,encoding='utf-8')
audio.write_text(a,encoding='utf-8')
audio_h.write_text(h,encoding='utf-8')

fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_ota')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(ROOT)],check=True)
if not (build/'TamaPoke.ino.bin').is_file(): raise SystemExit('OTA volume v2.6 binary missing')
print('⑤ OTA volume v2.6 compiled: 0/25/50/75/100%, NVS persisted, PCM amplitude scaled')
