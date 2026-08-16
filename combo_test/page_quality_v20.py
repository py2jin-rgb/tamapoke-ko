from pathlib import Path

p = Path('site/index.html')
s = p.read_text(encoding='utf-8')

repls = [
    ('🎮 COMBO · QUIZ 151', '✨ COMBO · QUALITY GAMES 2.0'),
    ('③ 알람 + 천지인 + 미니게임 + 날짜 + 151퀴즈 한방판', '③ 천지인 + 퀄업 미니게임 + 날짜 + 151퀴즈 한방판'),
    ('알람시계 + 한글 천지인 + stability2 + 미니게임 + 날짜설정을 유지하면서 <b>1세대 151마리 그림 맞히기 퀴즈</b>를 추가한 통합판입니다.', '천지인·알람·날짜·151퀴즈를 그대로 유지하면서 <b>포켓몬 테마 미니게임 UI와 게임성을 전면 개선하고 몬스터볼 캐치를 추가</b>한 통합판입니다.'),
    ('manifest-combo.json?v=quiz151', 'manifest-combo.json?v=quality20'),
    ('🎮 천지인 + 게임 + 날짜 + 151퀴즈 설치', '✨ 천지인 한방팩 v2.0 설치'),
    ('<div class="combowarn"><b>1.9 QUIZ 151:</b> Lv.1 파이리(5초), Lv.2 피카츄(3초)로 시작해 151마리를 재미있는 고정 순서로 진행합니다. 후반으로 갈수록 준비시간이 2초→1초로 짧아지고 오답 후보도 더 헷갈리게 구성됩니다. 최고 진행 레벨은 기기에 저장됩니다. <b>Erase/초기화는 선택하지 마세요.</b></div>', '<div class="combowarn"><b>2.0 퀄올리기:</b> 피카츄 잡기는 12칸·5단계 속도 상승형으로 개편했고, 가위바위보는 현재 키우는 포켓몬 VS 상대 포켓몬 대전 화면으로 개선했습니다. 151퀴즈는 SD/이미지 로드 실패를 명확히 안내하고, 새 게임 몬스터볼 캐치를 추가했습니다. <b>Erase/초기화는 선택하지 마세요.</b></div>'),
]

for old, new in repls:
    if old not in s:
        raise SystemExit(f'quality page marker not found: {old}')
    s = s.replace(old, new, 1)

marker = '<p class="ok">✓ 정답 시 다음 레벨 · 오답 시 같은 레벨 재도전 · 진행 레벨 NVS 저장</p>'
add = marker + (
    '<p class="ok">✓ 가위바위보: 현재 키우는 포켓몬 VS 상대 포켓몬 대전형 UI</p>'
    '<p class="ok">✓ 피카츄 잡기: 12칸 · 5단계 · 단계마다 등장 속도 상승</p>'
    '<p class="ok">✓ 151퀴즈: SD/이미지 미로드 시 ? + 안내문 · 정답 입력 차단</p>'
    '<p class="ok">✓ 새 게임: 몬스터볼 캐치 · 볼/열매/사탕 점수 · 돌 피하기</p>'
    '<p class="ok">✓ 몬스터볼 캐치 최고점 NVS 저장 · 현재 포켓몬으로 직접 캐치</p>'
)
if marker not in s:
    raise SystemExit('quality page feature marker not found')
s = s.replace(marker, add, 1)

p.write_text(s, encoding='utf-8')
print('installer page updated for quality games 2.0')
