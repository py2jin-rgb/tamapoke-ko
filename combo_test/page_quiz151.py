from pathlib import Path

p = Path('site/index.html')
s = p.read_text(encoding='utf-8')

repls = [
    ('🎮 COMBO · GAMES 1 + DATE', '🎮 COMBO · QUIZ 151'),
    ('③ 알람 + 한글 천지인 + 미니게임 + 날짜설정 한방판', '③ 알람 + 천지인 + 미니게임 + 날짜 + 151퀴즈 한방판'),
    ('알람시계 + 한글 천지인 + stability2 + 미니게임을 유지하면서 <b>날짜 직접 설정과 한글 폰트 확대</b>를 추가한 통합판입니다.', '알람시계 + 한글 천지인 + stability2 + 미니게임 + 날짜설정을 유지하면서 <b>1세대 151마리 그림 맞히기 퀴즈</b>를 추가한 통합판입니다.'),
    ('manifest-combo.json?v=datefont1', 'manifest-combo.json?v=quiz151'),
    ('🎮 천지인 + 게임 + 날짜판 설치', '🎮 천지인 + 게임 + 날짜 + 151퀴즈 설치'),
    ('<div class="combowarn"><b>1.8 실기 확인:</b> 천지인/알람/시계/미니게임은 유지하고 날짜(년·월·일) 설정과 안전한 영역의 한글 글씨 확대를 추가했습니다. 원형 화면에서 잘림 여부는 실기 확인 후 미세조정할 수 있습니다. <b>Erase/초기화는 선택하지 마세요.</b></div>', '<div class="combowarn"><b>1.9 QUIZ 151:</b> Lv.1 파이리(5초), Lv.2 피카츄(3초)로 시작해 151마리를 재미있는 고정 순서로 진행합니다. 후반으로 갈수록 준비시간이 2초→1초로 짧아지고 오답 후보도 더 헷갈리게 구성됩니다. 최고 진행 레벨은 기기에 저장됩니다. <b>Erase/초기화는 선택하지 마세요.</b></div>'),
]

for old, new in repls:
    if old not in s:
        raise SystemExit(f'quiz page marker not found: {old}')
    s = s.replace(old, new, 1)

marker = '<p class="ok">✓ 천지인 키보드 좌표·키캡 크기는 기존 그대로 유지</p>'
add = marker + (
    '<p class="ok">✓ 새 게임: 1세대 151마리 그림 맞히기 · 3지선다</p>'
    '<p class="ok">✓ Lv.1 파이리 5-4-3-2-1 · Lv.2 피카츄부터 3-2-1</p>'
    '<p class="ok">✓ Lv.41부터 2초 · Lv.101부터 1초 준비 카운트</p>'
    '<p class="ok">✓ 익숙한 포켓몬부터 시작해 151마리를 섞은 고정 레벨 순서</p>'
    '<p class="ok">✓ 후반 레벨은 도감번호가 가까운 포켓몬을 오답으로 넣어 난이도 상승</p>'
    '<p class="ok">✓ 정답 시 다음 레벨 · 오답 시 같은 레벨 재도전 · 진행 레벨 NVS 저장</p>'
)
if marker not in s:
    raise SystemExit('quiz page feature marker not found')
s = s.replace(marker, add, 1)

p.write_text(s, encoding='utf-8')
print('installer page updated for quiz151')
