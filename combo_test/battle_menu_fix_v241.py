from pathlib import Path
import re

p=Path('combo_test/battle_v24.py')
s=p.read_text(encoding='utf-8')

anchor="# Route touch/render into the battle modal before existing minigame handlers.\n"
if anchor not in s:
    raise SystemExit('battle menu fix anchor missing')

fix=r"""# Final Battery 2.3 menu is the polished arcade layout, not the old MORE tile.
# Add Battle as the fourth arcade entry while preserving Tetris/Snake/Minesweeper.
def replace_cpp_function(text, signature, body):
    m=re.search(re.escape(signature)+r'\s*\{',text)
    if not m: raise SystemExit('battle final menu function missing: '+signature)
    start=m.start(); brace=text.find('{',m.start(),m.end()); depth=0; end=None
    for i in range(brace,len(text)):
        if text[i]=='{': depth+=1
        elif text[i]=='}':
            depth-=1
            if depth==0: end=i+1; break
    if end is None: raise SystemExit('battle final menu closing brace missing: '+signature)
    return text[:start]+body+text[end:]

# Main game menu keeps every existing game, but labels the arcade entry clearly.
s=s.replace('comboFinalTextIn(koOr(\"새 미니게임 3종\",\"3 NEW GAMES\"),68,383,330,UI_WHITE,2);',
            'comboFinalTextIn(koOr(\"아케이드 + 통신 배틀\",\"ARCADE + BATTLE\"),68,383,330,UI_WHITE,2);',1)

s=replace_cpp_function(s,'void arcGameMenuTap(int16_t x,int16_t y)',r'''void arcGameMenuTap(int16_t x,int16_t y) {
  lastInteract=millis();
  if (y < 78) { arcMenuOpen=false; gameMenuOpen=true; return; }
  if (x>=46 && x<=222 && y>=112 && y<=226) { arcStartTetris(); return; }
  if (x>=244 && x<=420 && y>=112 && y<=226) { arcStartSnake(); return; }
  if (x>=72 && x<=394 && y>=246 && y<=350) { arcStartMine(1); return; }
  if (x>=72 && x<=394 && y>=362 && y<=424) { arcMenuOpen=false; startBattle(); return; }
}''')

s=replace_cpp_function(s,'void arcRenderMenu()',r'''void arcRenderMenu() {
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xf1,0xf4,0xfb));
  uiPrintCenter(koOr("포켓 아케이드","POCKET ARCADE"),36,UI_INK,2);
  uiPrintCenter(koOr("게임 또는 통신 배틀을 골라줘!","CHOOSE GAME / BATTLE"),64,UI_TRACK,1);
  arcCard(46,94,176,116,C565(0x9f,0xd2,0xff),koOr("테트리스","TETRIS"),koOr("줄을 지우면 빨라져!","LINES = FASTER"));
  arcCard(244,94,176,116,C565(0xa9,0xe3,0xa6),koOr("지렁이","SNAKE"),koOr("먹으면 더 빨라져!","FOOD = FASTER"));
  arcCard(72,224,322,116,C565(0xff,0xd2,0x8b),koOr("지뢰찾기","MINESWEEPER"),koOr("깨면 지뢰가 늘어!","MORE MINES"));
  gfx->fillRoundRect(72,362,322,62,16,C565(0xff,0xc8,0x5a));
  gfx->drawRoundRect(72,362,322,62,16,C565(0x9a,0x6a,0x20));
  comboFinalTextIn(koOr("통신 배틀","BATTLE"),72,381,322,UI_INK,2);
  gfx->flush();
}''')

if '아케이드 + 통신 배틀' not in s or 'arcMenuOpen=false; startBattle(); return;' not in s:
    raise SystemExit('battle final menu reachability invariant missing')
"""

s=s.replace(anchor,fix+'\n'+anchor,1)

# Keep the existing workflow stable: when Battle 2.4 has built and written its
# installer card, generate/publish the independent ⑤ OTA 2.5 edition next.
hook="subprocess.run(['python3','combo_test/ota_pipeline_v25.py'],check=True)"
if hook not in s:
    s += "\n\n# ⑤ Wi-Fi OTA Edition pipeline\n" + hook + "\n"

p.write_text(s,encoding='utf-8')
print('Battle 2.4 final arcade menu reachability fix + OTA 2.5 hook applied')
