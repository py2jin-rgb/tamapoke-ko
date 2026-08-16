from pathlib import Path
import re, sys

root = Path(sys.argv[1])
ino_p = root / 'TamaPoke.ino'
ph_p = root / 'pet.h'
pc_p = root / 'pet.cpp'

def one(s, old, new, label):
    if old not in s:
        raise SystemExit(f'marker not found: {label}')
    return s.replace(old, new, 1)

# ---------------- pet progress ----------------
s = ph_p.read_text(encoding='utf-8')
s = one(s,
'''  uint16_t rpsHi = 0;      // mejor numero de victorias en una partida de 5 rondas''',
'''  uint16_t rpsHi = 0;      // mejor numero de victorias en una partida de 5 rondas
  uint16_t quizLv = 1;     // highest unlocked level in the 151 picture quiz''',
'quiz progress field')
s = one(s,
'''  void minigameReward(uint16_t score); // recompensa suave para juegos nuevos''',
'''  void minigameReward(uint16_t score); // recompensa suave para juegos nuevos
  void setQuizLevel(uint16_t level);      // persist 151-quiz progress without extra pet rewards''',
'quiz progress declaration')
ph_p.write_text(s, encoding='utf-8')

s = pc_p.read_text(encoding='utf-8')
s = one(s,
'''  prefs.putUShort("rhi", rpsHi);''',
'''  prefs.putUShort("rhi", rpsHi);
  prefs.putUShort("qlv", quizLv);''',
'quiz save')
s = one(s,
'''  rpsHi = prefs.getUShort("rhi", 0);''',
'''  rpsHi = prefs.getUShort("rhi", 0);
  quizLv = prefs.getUShort("qlv", 1);
  if (quizLv < 1 || quizLv > 151) quizLv = 1;''',
'quiz load')
marker = '// saco de entrenamiento: los golpes entrenan la fuerza. Devuelve la subida.\nuint8_t Pet::trainStrength'
if marker not in s:
    raise SystemExit('quiz progress implementation marker missing')
impl = '''void Pet::setQuizLevel(uint16_t level) {
  if (level < 1) level = 1;
  if (level > 151) level = 151;
  quizLv = level;
  save();
}

'''
s = s.replace(marker, impl + marker, 1)
pc_p.write_text(s, encoding='utf-8')

# ---------------- TamaPoke quiz engine ----------------
s = ino_p.read_text(encoding='utf-8')
s = re.sub(r'#define FW_VERSION "[^"]+"', '#define FW_VERSION "1.9-ko-combo-quiz151"', s, count=1)

s = one(s,
'''bool gameMenuOpen = false;
bool moleOpen = false;
bool rpsOpen = false;''',
'''bool gameMenuOpen = false;
bool moleOpen = false;
bool rpsOpen = false;
bool quizOpen = false;''',
'quiz open state')

s = one(s,
'''int16_t rpsOpponentDex = 0;''',
'''int16_t rpsOpponentDex = 0;

uint16_t quizLevel = 1;
uint16_t quizTargetDex = 4;
uint16_t quizChoices[3] = {4, 7, 1};
uint8_t quizCorrectSlot = 0;
uint32_t quizCountdownEnd = 0;
uint32_t quizFeedbackUntil = 0;
bool quizWasCorrect = false;
bool quizCompleted = false;''',
'quiz globals')

s = one(s,
'''void renderRps();''',
'''void renderRps();
void startQuiz151();
void quiz151Tap(int16_t x, int16_t y);
void renderQuiz151();''',
'quiz prototypes')

# Close/block the quiz anywhere the other modal minigames are closed/blocked.
s = one(s,
'''    gameOpen=false; sackOpen=false; gameMenuOpen=false; moleOpen=false; rpsOpen=false;''',
'''    gameOpen=false; sackOpen=false; gameMenuOpen=false; moleOpen=false; rpsOpen=false; quizOpen=false;''',
'alarm closes quiz')
s = s.replace('gameMenuOpen || moleOpen || rpsOpen ||', 'gameMenuOpen || moleOpen || rpsOpen || quizOpen ||')
s = s.replace('!gameMenuOpen && !moleOpen && !rpsOpen &&', '!gameMenuOpen && !moleOpen && !rpsOpen && !quizOpen &&')

s = one(s,
'''  if (gameMenuOpen) { gameMenuTap(x, y); return; }
  if (rpsOpen) { rpsTap(x, y); return; }''',
'''  if (gameMenuOpen) { gameMenuTap(x, y); return; }
  if (quizOpen) { quiz151Tap(x, y); return; }
  if (rpsOpen) { rpsTap(x, y); return; }''',
'quiz tap dispatch')

s = one(s,
'''  if (gameMenuOpen) { renderGameMenu(); return; }
  if (moleOpen) { renderMole(); return; }
  if (rpsOpen) { renderRps(); return; }''',
'''  if (gameMenuOpen) { renderGameMenu(); return; }
  if (moleOpen) { renderMole(); return; }
  if (rpsOpen) { renderRps(); return; }
  if (quizOpen) { renderQuiz151(); return; }''',
'quiz render dispatch')

s = one(s,
'''  gameOpen=false; moleOpen=false; rpsOpen=false; sackOpen=false;''',
'''  gameOpen=false; moleOpen=false; rpsOpen=false; quizOpen=false; sackOpen=false;''',
'open game menu closes quiz')

s = one(s,
'''  if (x>=244 && x<=408 && y>=246 && y<=356) sfxPlay(SFX_DENY);''',
'''  if (x>=244 && x<=408 && y>=246 && y<=356) {
    gameMenuOpen=false; startQuiz151(); return;
  }''',
'quiz menu tap')

s = one(s,
'''  gameCard(244,246,164,110,C565(0xdb,0xdf,0xe5),koOr("다음 게임","MORE"),3);''',
'''  gameCard(244,246,164,110,C565(0xdb,0xdf,0xe5),koOr("151 퀴즈","151 QUIZ"),3);''',
'quiz menu card')

# Fun ordering: familiar mascots first, then a fixed mixed tour through all original 151.
order = [4,25,7,1,133,52,39,54,143,10,16,19,37,58,60,74,92,129,147,151,6,9,3,26,134,135,136,131,130,149,150,105,34,97,69,36,28,18,61,84,121,138,140,14,80,101,51,46,57,20,148,70,106,5,17,79,42,89,55,41,78,102,44,112,8,66,71,50,137,11,65,67,68,96,90,62,22,75,77,125,142,141,113,116,127,94,12,47,98,124,32,144,132,119,76,82,2,123,27,128,108,100,99,115,122,63,53,30,91,114,48,13,95,49,110,38,56,111,103,120,33,88,85,43,73,145,87,117,139,81,59,31,86,118,40,104,21,24,29,45,107,35,146,83,109,72,93,64,15,23,126]
if len(order) != 151 or len(set(order)) != 151 or min(order) != 1 or max(order) != 151:
    raise SystemExit('quiz order must contain every dex number 1..151 exactly once')

names = [
'이상해씨','이상해풀','이상해꽃','파이리','리자드','리자몽','꼬부기','어니부기','거북왕','캐터피',
'단데기','버터플','뿔충이','딱충이','독침붕','구구','피죤','피죤투','꼬렛','레트라',
'깨비참','깨비드릴조','아보','아보크','피카츄','라이츄','모래두지','고지','니드런F','니드리나',
'니드퀸','니드런M','니드리노','니드킹','삐삐','픽시','식스테일','나인테일','푸린','푸크린',
'주뱃','골뱃','뚜벅쵸','냄새꼬','라플레시아','파라스','파라섹트','콘팡','도나리','디그다',
'닥트리오','나옹','페르시온','고라파덕','골덕','망키','성원숭','가디','윈디','발챙이',
'슈륙챙이','강챙이','캐이시','윤겔라','후딘','알통몬','근육몬','괴력몬','모다피','우츠동',
'우츠보트','왕눈해','독파리','꼬마돌','데구리','딱구리','포니타','날쌩마','야돈','야도란',
'코일','레어코일','파오리','두두','두트리오','쥬쥬','쥬레곤','질퍽이','질뻐기','셀러',
'파르셀','고오스','고우스트','팬텀','롱스톤','슬리프','슬리퍼','크랩','킹크랩','찌리리공',
'붐볼','아라리','나시','탕구리','텅구리','시라소몬','홍수몬','내루미','또가스','또도가스',
'뿔카노','코뿌리','럭키','덩쿠리','캥카','쏘드라','시드라','콘치','왕콘치','별가사리',
'아쿠스타','마임맨','스라크','루주라','에레브','마그마','쁘사이저','켄타로스','잉어킹','갸라도스',
'라프라스','메타몽','이브이','샤미드','쥬피썬더','부스터','폴리곤','암나이트','암스타','투구',
'투구푸스','프테라','잠만보','프리져','썬더','파이어','미뇽','신뇽','망나뇽','뮤츠','뮤'
]
if len(names) != 151:
    raise SystemExit('quiz names must contain 151 entries')

order_cpp = ','.join(str(x) for x in order)
names_cpp = ',\n  '.join('"' + x + '"' for x in names)

quiz_block = f'''// ---------- 151 포켓몬 그림 퀴즈 ----------
static const uint16_t QUIZ151_ORDER[151] = {{{order_cpp}}};
static const char *const QUIZ151_NAMES[151] = {{
  {names_cpp}
}};

static uint16_t quizWrapDex(int v) {{
  while (v < 1) v += 151;
  while (v > 151) v -= 151;
  return (uint16_t)v;
}}

static const char *quiz151Name(uint16_t dex) {{
  return (dex >= 1 && dex <= 151) ? QUIZ151_NAMES[dex - 1] : "?";
}}

static uint8_t quiz151CountdownSec(uint16_t level) {{
  if (level <= 1) return 5;       // Lv.1: 5-4-3-2-1
  if (level <= 40) return 3;      // Lv.2~40: 3-2-1
  if (level <= 100) return 2;
  return 1;
}}

static void quiz151BuildChoices() {{
  uint16_t a, b;
  if (quizLevel <= 20) {{
    a = quizWrapDex((int)quizTargetDex + 47);
    b = quizWrapDex((int)quizTargetDex + 89);
  }} else if (quizLevel <= 80) {{
    a = quizWrapDex((int)quizTargetDex + ((quizLevel & 1) ? 1 : -1));
    b = quizWrapDex((int)quizTargetDex + 53);
  }} else {{
    // Late game deliberately uses nearby dex entries more often, which frequently
    // places evolution-family or visually similar names together.
    a = quizWrapDex((int)quizTargetDex - 1);
    b = quizWrapDex((int)quizTargetDex + 1);
  }}
  if (a == quizTargetDex) a = quizWrapDex((int)a + 7);
  if (b == quizTargetDex || b == a) b = quizWrapDex((int)b + 11);
  if (b == quizTargetDex || b == a) b = quizWrapDex((int)b + 17);

  quizCorrectSlot = (uint8_t)((quizLevel * 7u) % 3u);
  uint8_t j = 0;
  for (uint8_t i = 0; i < 3; ++i) {{
    if (i == quizCorrectSlot) quizChoices[i] = quizTargetDex;
    else quizChoices[i] = (j++ == 0) ? a : b;
  }}
}}

static void quiz151PrepareLevel() {{
  if (quizLevel < 1) quizLevel = 1;
  if (quizLevel > 151) quizLevel = 151;
  quizTargetDex = QUIZ151_ORDER[quizLevel - 1];
  quiz151BuildChoices();
  miniOpponentPmd.unload();
  miniOpponentPmd.load(quizTargetDex, false);
  quizFeedbackUntil = 0;
  quizWasCorrect = false;
  quizCountdownEnd = millis() + (uint32_t)quiz151CountdownSec(quizLevel) * 1000UL;
}}

void startQuiz151() {{
  if (pet.isEgg() || pet.sleeping || pet.ceremony) return;
  quizOpen = true;
  gameMenuOpen = gameOpen = moleOpen = rpsOpen = sackOpen = false;
  quizLevel = pet.quizLv;
  if (quizLevel < 1 || quizLevel > 151) quizLevel = 1;
  quizCompleted = false;
  quiz151PrepareLevel();
  sfxPlay(SFX_GAME_START);
}}

void quiz151Tap(int16_t x, int16_t y) {{
  if (y < 72) {{ quizOpen = false; miniOpponentPmd.unload(); return; }}
  uint32_t now = millis();
  if (quizFeedbackUntil || now < quizCountdownEnd) return;
  if (y < 326 || y > 418) return;

  int8_t pick = -1;
  if (x >= 28 && x <= 150) pick = 0;
  else if (x >= 172 && x <= 294) pick = 1;
  else if (x >= 316 && x <= 438) pick = 2;
  if (pick < 0) return;

  if (quizChoices[pick] == quizTargetDex) {{
    quizWasCorrect = true;
    sfxPlay(SFX_RPS_WIN);
    if (quizLevel >= 151) {{
      quizCompleted = true;
      pet.setQuizLevel(151);
      pet.minigameReward(20);
      quizFeedbackUntil = now + 3600;
    }} else {{
      ++quizLevel;
      pet.setQuizLevel(quizLevel);
      quizFeedbackUntil = now + 1100;
    }}
  }} else {{
    quizWasCorrect = false;
    sfxPlay(SFX_RPS_LOSE);
    quizFeedbackUntil = now + 1200;
  }}
}}

void renderQuiz151() {{
  uint32_t now = millis();
  if (quizFeedbackUntil && now >= quizFeedbackUntil) {{
    quizFeedbackUntil = 0;
    if (quizCompleted) {{
      quizOpen = false;
      miniOpponentPmd.unload();
      return;
    }}
    quiz151PrepareLevel();
  }}

  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, C565(0xef,0xf4,0xff));
  uiPrintCenter(koOr("151 포켓몬 퀴즈","151 POKEMON QUIZ"), 38, UI_INK, 3);
  char hdr[28];
  snprintf(hdr, sizeof(hdr), "Lv.%u / 151", (unsigned)quizLevel);
  uiPrintCenter(hdr, 78, UI_INK, 2);

  if (quizFeedbackUntil) {{
    if (quizCompleted) {{
      uiPrintCenter(koOr("151마리 마스터!","151 MASTER!"), 154, UI_BAR_WARN, 3);
      uiPrintCenter(koOr("모든 레벨 완료!","ALL LEVELS CLEAR"), 214, UI_INK, 2);
      if (miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd, PMD_IDLE, CX, 348, now, true, false, 3);
    }} else if (quizWasCorrect) {{
      uiPrintCenter(koOr("정답! 다음 레벨!","CORRECT! NEXT!"), 150, UI_BAR_OK, 3);
      uiPrintCenter(quiz151Name(quizTargetDex), 214, UI_INK, 3);
    }} else {{
      uiPrintCenter(koOr("아쉽다! 다시 도전!","TRY AGAIN!"), 150, UI_BAR_WARN, 3);
      uiPrintCenter(quiz151Name(quizTargetDex), 214, UI_INK, 3);
    }}
    gfx->flush();
    return;
  }}

  if (now < quizCountdownEnd) {{
    uint32_t leftMs = quizCountdownEnd - now;
    uint8_t sec = (uint8_t)((leftMs + 999) / 1000);
    uiPrintCenter(koOr("그림을 잘 봐!","GET READY!"), 136, UI_INK, 2);
    char c[4]; snprintf(c, sizeof(c), "%u", sec);
    uiPrintCenter(c, 204, UI_BAR_WARN, 6);
    uiPrintCenter(koOr("위쪽을 누르면 나가기","Tap top to exit"), 382, UI_TRACK, 1);
    gfx->flush();
    return;
  }}

  uiPrintCenter(koOr("이 포켓몬은 누구?","WHO IS THIS?"), 112, UI_INK, 2);
  if (miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd, PMD_IDLE, CX, 276, now, true, false, 3);
  else {{ gfx->fillCircle(CX, 212, 42, UI_WHITE); uiPrintAt("?", CX-9, 198, UI_INK, 4); }}

  const int bx[3] = {{28,172,316}};
  const int bw = 122, by = 326, bh = 92;
  const uint16_t bc[3] = {{C565(0xff,0xc7,0x72), C565(0x8d,0xd8,0xa0), C565(0x9e,0xc5,0xff)}};
  for (uint8_t i=0; i<3; ++i) {{
    gfx->fillRoundRect(bx[i], by, bw, bh, 15, bc[i]);
    gfx->drawRoundRect(bx[i], by, bw, bh, 15, UI_INK);
    const char *nm = quiz151Name(quizChoices[i]);
    uint8_t fs = uiTextWidth(nm, 2) <= bw-10 ? 2 : 1;
    uiPrintAt(nm, bx[i] + (bw-uiTextWidth(nm,fs))/2, by + (fs==2 ? 31 : 38), UI_INK, fs);
  }}
  gfx->flush();
}}

'''

marker = '// ---------- minijuego: toques con la pokeball ----------\n'
if marker not in s:
    raise SystemExit('quiz insertion marker missing')
s = s.replace(marker, quiz_block + marker, 1)

ino_p.write_text(s, encoding='utf-8')
print('151-level Pokemon picture quiz added')
