from pathlib import Path
import shutil, subprocess

ROOT=Path('source_ota/TamaPoke')
ino=ROOT/'TamaPoke.ino'
if not ino.is_file():
    raise SystemExit('⑤ clock fix missing source_ota/TamaPoke/TamaPoke.ino')

s=ino.read_text(encoding='utf-8')

# ⑤ only: keep ①~④ untouched. Fix standby-clock overlap seen on real hardware.
# The 3x PMD sprite was intruding into the enlarged date/time area. Make the
# standby pet smaller and anchor it lower on the scene, preserving day/night UI.
old_ver='#define FW_VERSION "2.6-ko-combo-ota-volume"'
new_ver='#define FW_VERSION "2.7-ko-combo-ota-volume-clockfix"'
if old_ver not in s:
    raise SystemExit('⑤ clock fix version marker missing')
s=s.replace(old_ver,new_ver,1)

if 'static const uint16_t OTA_BUILD=260;' not in s:
    raise SystemExit('⑤ clock fix OTA build marker missing')
s=s.replace('static const uint16_t OTA_BUILD=260;','static const uint16_t OTA_BUILD=270;',1)

# Daytime walking helper: only the standby helper uses this exact generated line.
walk='drawPmdAct(act, x, groundY, millis(), true, false, 3);'
if walk not in s:
    raise SystemExit('⑤ clock fix daytime pet scale marker missing')
s=s.replace(walk,'drawPmdAct(act, x, groundY, millis(), true, false, 2);',1)

# Standby scene anchors from the combo clock source.
if 'drawStandbyAwakePet(385);' not in s:
    raise SystemExit('⑤ clock fix daytime ground marker missing')
s=s.replace('drawStandbyAwakePet(385);','drawStandbyAwakePet(410);',1)

if 'drawAlarmPet(385, true, 3);' not in s:
    raise SystemExit('⑤ clock fix night pet marker missing')
s=s.replace('drawAlarmPet(385, true, 3);','drawAlarmPet(410, true, 2);',1)

# Keep the enlarged date readable, but move it slightly upward to guarantee a
# clean gap even for taller PMD sprites.
date_old='gfx->setCursor(x0, 178); gfx->print(db);\n    uiPrintAt(wd, x0 + dateW + gap, 178, UI_WHITE, 3);'
date_new='gfx->setCursor(x0, 170); gfx->print(db);\n    uiPrintAt(wd, x0 + dateW + gap, 170, UI_WHITE, 3);'
if date_old not in s:
    raise SystemExit('⑤ clock fix standby date marker missing')
s=s.replace(date_old,date_new,1)

for must in ('2.7-ko-combo-ota-volume-clockfix','OTA_BUILD=270','drawStandbyAwakePet(410);','drawAlarmPet(410, true, 2);'):
    if must not in s:
        raise SystemExit('⑤ clock fix invariant missing: '+must)

ino.write_text(s,encoding='utf-8')

fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_ota')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(ROOT)],check=True)
if not (build/'TamaPoke.ino.bin').is_file():
    raise SystemExit('⑤ clock fix binary missing')
print('⑤ OTA Volume 2.7 clock layout fix compiled: smaller/lower standby pet, date gap restored')
