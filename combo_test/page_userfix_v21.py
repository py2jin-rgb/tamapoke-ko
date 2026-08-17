from pathlib import Path
import re
import shutil
import subprocess

# Final user-requested fixes for the ③ Alarm + Cheonjiin combo build.
root = Path('source_combo/TamaPoke')
ino = root / 'TamaPoke.ino'
audio = root / 'audio.cpp'
src = ino.read_text(encoding='utf-8')
aud = audio.read_text(encoding='utf-8')

def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f'v2.1 marker not found: {label}')
    return text.replace(old, new, 1)

aud = once(aud,'static const Note N_MOLE_H1[]    = {{740, 28}, {988, 35}};','static const Note N_MOLE_H1[]    = {{190, 18}, {720, 28}, {1040, 42}};','mole hit sound 1')
aud = once(aud,'static const Note N_MOLE_H2[]    = {{831, 28}, {1109, 35}};','static const Note N_MOLE_H2[]    = {{220, 18}, {830, 28}, {1240, 42}};','mole hit sound 2')
aud = once(aud,'static const Note N_MOLE_H3[]    = {{932, 28}, {1245, 38}};','static const Note N_MOLE_H3[]    = {{260, 18}, {930, 28}, {1480, 44}};','mole hit sound 3')
aud = once(aud,'{N_MOLE_H1, 2}, {N_MOLE_H2, 2}, {N_MOLE_H3, 2}, {N_MOLE_MISS, 2},','{N_MOLE_H1, 3}, {N_MOLE_H2, 3}, {N_MOLE_H3, 3}, {N_MOLE_MISS, 2},','mole note table lengths')
audio.write_text(aud, encoding='utf-8')

clock_old = '''  // Small horizon card keeps the pet visually anchored without crowding the clock.\n  gfx->fillRoundRect(82, 292, 302, 112, 28, card);\n  gfx->drawRoundRect(82, 292, 302, 112, 28, dayMode ? C565(0x85,0xc9,0xeb) : C565(0x43,0x47,0x78));\n  if (dayMode) {\n    gfx->fillRoundRect(105, 372, 256, 8, 4, C565(0x64,0xb6,0x76));\n    drawStandbyAwakePet(392);\n  } else {\n    gfx->fillRoundRect(105, 372, 256, 8, 4, C565(0x38,0x3d,0x65));\n    drawAlarmPet(392, true, 3);\n    gfx->setTextColor(soft); gfx->setTextSize(2); gfx->setCursor(319, 320); gfx->print("Zzz...");\n  }'''
clock_new = '''  // Pokemon now sits directly on the watch-face background: no large card/box.\n  if (dayMode) {\n    gfx->fillRoundRect(150, 386, 166, 5, 3, C565(0x64,0xb6,0x76));\n    drawStandbyAwakePet(392);\n  } else {\n    gfx->fillRoundRect(150, 386, 166, 5, 3, C565(0x38,0x3d,0x65));\n    drawAlarmPet(392, true, 3);\n    gfx->setTextColor(soft); gfx->setTextSize(2); gfx->setCursor(319, 320); gfx->print("Zzz...");\n  }'''
src = once(src, clock_old, clock_new, 'standby Pokemon card removal')
src = once(src,'  quizTargetDex = QUIZ151_ORDER[quizLevel - 1];','  const uint16_t previousDex = quizTargetDex;\n  do { quizTargetDex = (uint16_t)(1 + random(151)); } while (quizTargetDex == previousDex);','quiz random target')
src = once(src,'  quizCorrectSlot = (uint8_t)((quizLevel * 7u) % 3u);','  quizCorrectSlot = (uint8_t)random(3);','quiz random correct slot')
pat = re.compile(r'drawPmdActM\(miniOpponentPmd,\s*PMD_IDLE,\s*CX,\s*276,\s*now,\s*true,\s*false,\s*3\)')
src, n = pat.subn('drawPmdActM(miniOpponentPmd, PMD_IDLE, CX, 294, now, true, false, 4)', src, count=1)
if n != 1: raise SystemExit('v2.1 marker not found: quiz main Pokemon scale')
src, n = re.subn(r'#define FW_VERSION "2\.0-ko-combo-qualitygames-final"','#define FW_VERSION "2.1-ko-combo-userfix"',src,count=1)
if n != 1: raise SystemExit('v2.1 marker not found: firmware version')
ino.write_text(src, encoding='utf-8')

fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_combo')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)],check=True)
if not (build/'TamaPoke.ino.bin').is_file(): raise SystemExit('v2.1 combo firmware binary missing')

page=Path('site/index.html'); html=page.read_text(encoding='utf-8')
html=once(html,'✨ COMBO · QUALITY GAMES 2.0 FINAL','✨ COMBO · USER FIX 2.1','page combo badge')
html=once(html,'✨ 천지인 한방팩 v2.0 FINAL 설치','✨ 천지인 한방팩 v2.1 설치','page install button')
html=once(html,'manifest-combo.json?v=quality20final','manifest-combo.json?v=userfix21','manifest cache key')
old_warn='<div class="combowarn"><b>2.0 FINAL:</b> 피카츄 잡기 12칸·5단계와 포켓몬 VS, 몬스터볼 캐치를 유지하면서 피카츄 등장 효과음을 보강했습니다. 메인 화면 행복/위생 게이지는 먹이/체력과 같은 최대 길이로 정리했고, 151퀴즈는 한 문제라도 틀리면 Lv.1부터 다시 시작하도록 변경했습니다. <b>Erase/초기화는 선택하지 마세요.</b></div>'
new_warn='<div class="combowarn"><b>2.1 USER FIX:</b> 두더지/피카츄 잡기 성공 타격음을 더 강한 뿅·톡 계열 3단 음으로 보강했습니다. 시계모드 포켓몬 뒤 큰 네모 박스를 제거했고, 151 이름맞추기는 포켓몬을 더 크게 표시하며 매 문제·오답 재시작마다 대상과 정답 위치를 새로 랜덤 선택합니다. <b>Erase/초기화는 선택하지 마세요.</b></div>'
html=once(html,old_warn,new_warn,'page v2.1 warning')
feature_anchor='<p class="ok">✓ 피카츄 잡기: 12칸 · 5단계 · 등장/타격/실패/단계업 효과음</p>'
feature_new=feature_anchor+'\n    <p class="ok">✓ v2.1: 성공 타격음 강화 · 시계 포켓몬 배경박스 제거 · 151퀴즈 포켓몬 확대/매번 랜덤</p>'
html=once(html,feature_anchor,feature_new,'page v2.1 feature line')
page.write_text(html,encoding='utf-8')
print('installer page updated for combo v2.1 user fixes')

# Progressive arcade pack, then the real-device Korean alignment bugfix.
subprocess.run(['python3','combo_test/page_arcade_v22.py'],check=True)
subprocess.run(['python3','combo_test/page_arcade_fix_v221.py'],check=True)
