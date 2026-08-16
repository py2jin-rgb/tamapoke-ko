from pathlib import Path
import re
import shutil
import subprocess

# ---- Final firmware polish applied after the proven 2.0 quality patch ----
ino = Path('source_combo/TamaPoke/TamaPoke.ino')
src = ino.read_text(encoding='utf-8')

def once(old: str, new: str, label: str) -> None:
    global src
    if old not in src:
        raise SystemExit(f'final polish marker not found: {label}')
    src = src.replace(old, new, 1)

src, n = re.subn(r'#define FW_VERSION "2\.0-ko-combo-qualitygames"',
                 '#define FW_VERSION "2.0-ko-combo-qualitygames-final"', src, count=1)
if n != 1:
    raise SystemExit('final polish version marker not found')

once(
'''  moleStageBannerUntil=0;\n  if(now>=moleNextAt) molePickNew();''',
'''  moleStageBannerUntil=0;\n  // 짧은 등장 효과음: 자동으로 새 피카츄가 나타날 때만 재생한다.\n  // 타격음과 겹치지 않게 성공 터치 뒤의 molePickNew()에는 추가하지 않는다.\n  if(now>=moleNextAt) { molePickNew(); sfxPlay(SFX_GAME_TICK); }''',
'Pikachu appearance sound')

once(
'''    bw = right - bx;\n    if (bw < 46) bw = 46;\n    bh = 12;''',
'''    bw = right - bx;\n    // 원형 화면 오른쪽의 행복/위생 바가 지나치게 길어 보이지 않도록\n    // 먹이/체력과 같은 최대 길이로 맞춘다.\n    if (bw > 104) bw = 104;\n    if (bw < 46) bw = 46;\n    bh = 12;''',
'status bar width cap')

once(
'''  } else {\n    quizWasCorrect = false;\n    sfxPlay(SFX_RPS_LOSE);\n    quizFeedbackUntil = now + 1200;\n  }''',
'''  } else {\n    quizWasCorrect = false;\n    // 서바이벌 규칙: 한 문제라도 틀리면 저장 진행도까지 Lv.1로 초기화.\n    // 피드백 화면에서는 방금 틀린 레벨/포켓몬을 보여주고, 종료 후 Lv.1부터 재시작한다.\n    pet.setQuizLevel(1);\n    sfxPlay(SFX_RPS_LOSE);\n    quizFeedbackUntil = now + 1500;\n  }''',
'quiz wrong resets progress')

once(
'''    if (quizCompleted) {\n      quizOpen = false;\n      miniOpponentPmd.unload();\n      return;\n    }\n    quiz151PrepareLevel();''',
'''    if (quizCompleted) {\n      quizOpen = false;\n      miniOpponentPmd.unload();\n      return;\n    }\n    if (!quizWasCorrect) quizLevel = 1;\n    quiz151PrepareLevel();''',
'quiz restart level one')

once(
'''      uiPrintCenter(koOr("아쉽다! 다시 도전!","TRY AGAIN!"), 150, UI_BAR_WARN, 3);''',
'''      uiPrintCenter(koOr("틀렸어요! 처음부터!","WRONG! BACK TO LV.1"), 150, UI_BAR_WARN, 3);''',
'quiz wrong message')

ino.write_text(src, encoding='utf-8')

# The clock screen is shared by the ② alarm build and ③ combo build. Apply the
# same centered battery/USB charging-aware watch face to both sources here,
# after all source-generation patches have finished.
subprocess.run([
    'python3', 'clock_polish_v13.py',
    'source_alarm/TamaPoke', 'source_combo/TamaPoke'
], check=True)

fqbn = 'esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'

# Recompile alarm so the second installer also receives the new clock UI.
alarm_build = Path('build_alarm')
if alarm_build.exists():
    shutil.rmtree(alarm_build)
alarm_build.mkdir()
subprocess.run([
    'arduino-cli', 'compile', '--fqbn', fqbn,
    '--build-path', str(alarm_build), 'source_alarm/TamaPoke'
], check=True)
if not (alarm_build / 'TamaPoke.ino.bin').is_file():
    raise SystemExit('clock-polished alarm firmware binary missing')
print('alarm clock UI firmware compiled successfully')

# Compile again so the web installer receives the polished source rather than the
# earlier 2.0 binary produced one step before this script runs.
build = Path('build_combo')
if build.exists():
    shutil.rmtree(build)
build.mkdir()
subprocess.run([
    'arduino-cli', 'compile', '--fqbn', fqbn,
    '--build-path', str(build), 'source_combo/TamaPoke'
], check=True)
if not (build / 'TamaPoke.ino.bin').is_file():
    raise SystemExit('final polished combo firmware binary missing')
print('final firmware + clock polish compiled successfully')

# ---- Installer page text ----
p = Path('site/index.html')
s = p.read_text(encoding='utf-8')

repls = [
    ('🎮 COMBO · QUIZ 151', '✨ COMBO · QUALITY GAMES 2.0 FINAL'),
    ('③ 알람 + 천지인 + 미니게임 + 날짜 + 151퀴즈 한방판', '③ 천지인 + 퀄업 미니게임 + 날짜 + 151퀴즈 한방판'),
    ('알람시계 + 한글 천지인 + stability2 + 미니게임 + 날짜설정을 유지하면서 <b>1세대 151마리 그림 맞히기 퀴즈</b>를 추가한 통합판입니다.', '천지인·알람·날짜·151퀴즈를 그대로 유지하면서 <b>포켓몬 테마 미니게임과 메인 상태창을 실기 화면 기준으로 마지막 다듬은 통합판</b>입니다.'),
    ('manifest-combo.json?v=quiz151', 'manifest-combo.json?v=quality20final'),
    ('🎮 천지인 + 게임 + 날짜 + 151퀴즈 설치', '✨ 천지인 한방팩 v2.0 FINAL 설치'),
    ('<div class="combowarn"><b>1.9 QUIZ 151:</b> Lv.1 파이리(5초), Lv.2 피카츄(3초)로 시작해 151마리를 재미있는 고정 순서로 진행합니다. 후반으로 갈수록 준비시간이 2초→1초로 짧아지고 오답 후보도 더 헷갈리게 구성됩니다. 최고 진행 레벨은 기기에 저장됩니다. <b>Erase/초기화는 선택하지 마세요.</b></div>', '<div class="combowarn"><b>2.0 FINAL:</b> 피카츄 잡기 12칸·5단계와 포켓몬 VS, 몬스터볼 캐치를 유지하면서 피카츄 등장 효과음을 보강했습니다. 메인 화면 행복/위생 게이지는 먹이/체력과 같은 최대 길이로 정리했고, 151퀴즈는 한 문제라도 틀리면 Lv.1부터 다시 시작하도록 변경했습니다. <b>Erase/초기화는 선택하지 마세요.</b></div>'),
]

for old, new in repls:
    if old not in s:
        raise SystemExit(f'quality page marker not found: {old}')
    s = s.replace(old, new, 1)

marker = '<p class="ok">✓ 정답 시 다음 레벨 · 오답 시 같은 레벨 재도전 · 진행 레벨 NVS 저장</p>'
add = (
    '<p class="ok">✓ 151퀴즈: 정답 시 다음 레벨 · 오답 시 Lv.1부터 재시작 · 진행도 즉시 Lv.1 저장</p>'
    '<p class="ok">✓ 가위바위보: 현재 키우는 포켓몬 VS 상대 포켓몬 대전형 UI</p>'
    '<p class="ok">✓ 피카츄 잡기: 12칸 · 5단계 · 등장/타격/실패/단계업 효과음</p>'
    '<p class="ok">✓ 메인 상태창: 행복/위생 게이지 길이를 먹이/체력과 균형 맞춤</p>'
    '<p class="ok">✓ 151퀴즈: SD/이미지 미로드 시 ? + 안내문 · 정답 입력 차단</p>'
    '<p class="ok">✓ 새 게임: 몬스터볼 캐치 · 볼/열매/사탕 점수 · 돌 피하기</p>'
    '<p class="ok">✓ 몬스터볼 캐치 최고점 NVS 저장 · 현재 포켓몬으로 직접 캐치</p>'
)
if marker not in s:
    raise SystemExit('quality page feature marker not found')
s = s.replace(marker, add, 1)

p.write_text(s, encoding='utf-8')

# Finally annotate both ② and ③ cards with the new clock/charging behavior.
subprocess.run(['python3', 'combo_test/page_clock_v13.py'], check=True)
print('installer page updated for quality games 2.0 FINAL + clock UI')
