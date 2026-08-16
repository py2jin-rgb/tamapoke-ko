from pathlib import Path

p = Path('site/index.html')
s = p.read_text(encoding='utf-8')

repls = [
    ('manifest.json?v=stable-textfix2', 'manifest.json?v=stability2'),
    ('✓ 공놀이/훈련 최고기록 한글 표시 수정</p>', '✓ 공놀이/훈련 최고기록 한글 표시 수정</p><p class="ok">✓ 메달 획득 한글 깨짐 수정 · 수면 Zzz 표시 깨짐 보정</p>'),

    ('🧪 TEST · ALARM v1.1', '✅ ALARM · STABILITY 2'),
    ('<h2>② 알람 테스트판</h2>', '<h2>② 알람시계판</h2>'),
    ('안정판에 알람 기능을 추가한 별도 시험용 펌웨어입니다.', '안정판에 알람시계와 30초 대기 시계를 추가한 버전입니다.'),
    ('manifest-alarm.json?v=alarm11', 'manifest-alarm.json?v=stability2'),
    ('<button slot="activate">🧪 알람 v1.1 설치</button>', '<button slot="activate">⏰ 알람시계판 설치</button>'),
    ('<div class="testwarn"><b>테스트판:</b> 컴파일 검증은 완료했지만 실제 기기 동작을 계속 확인 중입니다. <b>Erase/초기화는 선택하지 마세요.</b></div>', '<div class="testwarn"><b>안정화 2:</b> 수면 상태와 시계 화면을 분리했습니다. PWR 짧게 눌러 게임↔시계를 전환하고, 30초 무조작 시에도 시계로 들어갑니다. 시계에서 나와도 잠든 상태는 유지됩니다. <b>Erase/초기화는 선택하지 마세요.</b></div>'),
    ('✓ 알람 설정값 NVS 저장</p>', '✓ 알람 설정값 NVS 저장</p><p class="ok">✓ 메달 획득 한글 깨짐 수정</p><p class="ok">✓ PWR 짧게: 게임 ↔ 시계 토글</p><p class="ok">✓ 30초 무조작 시 시계 · 수면 상태와 시계 화면 완전 분리</p>'),

    ('🧪 NEW TEST · COMBO v1.0', '✅ COMBO · STABILITY 2'),
    ('③ 안정판 + 알람 + 한글 천지인</h2>', '③ 알람 + 한글 천지인 한방판</h2>'),
    ('① 안정판의 수정사항과 ② 알람 v1.1을 합친 뒤, 이름변경에 <b>한글 천지인 조합 키보드</b>를 추가한 통합 시험판입니다.', '① 안정판의 수정사항과 ② 알람시계를 합치고, 이름변경에 <b>한글 천지인 조합 키보드</b>를 추가한 통합판입니다.'),
    ('manifest-combo.json?v=combo10', 'manifest-combo.json?v=stability2'),
    ('<button slot="activate">⌨️ 천지인 통합판 설치</button>', '<button slot="activate">⌨️ 알람 + 천지인 한방판 설치</button>'),
    ('<div class="combowarn"><b>통합 테스트판 주의:</b> GitHub ESP32 컴파일은 성공했습니다. 하지만 천지인 터치 위치·글꼴 크기·이름 저장 후 모든 화면 표시는 아직 실기 확인 전입니다. 문제가 있으면 ① 안정판으로 즉시 돌아갈 수 있습니다. <b>Erase/초기화는 선택하지 마세요.</b></div>', '<div class="combowarn"><b>안정화 2:</b> 천지인은 그대로 유지하고, 수면과 시계 화면을 분리했습니다. PWR 짧게 게임↔시계, 30초 무조작 시 자동 시계, 시계에서 나와도 수면 상태 유지입니다. 낮 시간에 실제로 잠든 경우에는 걷는 화면 대신 수면 화면을 표시합니다. <b>Erase/초기화는 선택하지 마세요.</b></div>'),
]

for old, new in repls:
    if old not in s:
        raise SystemExit(f'page marker not found: {old}')
    s = s.replace(old, new, 1)

marker = '<p class="ok">✓ 전체 현대 한글 음절 표시용 폴백 글꼴 포함</p>'
add = marker + '<p class="ok">✓ 대기 시계 06:00~19:59: 해 표시 + 포켓몬 깨어서 좌우 걷기</p><p class="ok">✓ 대기 시계 20:00~05:59: 달 + 수면 + Zzz...</p><p class="ok">✓ PWR 짧게 게임↔시계 · 30초 자동 시계 · 수면 상태 유지</p><p class="ok">✓ 메달 획득 한글 깨짐 및 수면 글씨 깨짐 보정</p>'
if marker not in s:
    raise SystemExit('combo feature marker not found')
s = s.replace(marker, add, 1)

p.write_text(s, encoding='utf-8')
print('installer page updated for stability2 clock UX')
