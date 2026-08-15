from pathlib import Path

p = Path('source_combo/TamaPoke/TamaPoke.ino')
s = p.read_text(encoding='utf-8')

old_ver = '#define FW_VERSION "1.6-ko-combo1.0"'
new_ver = '#define FW_VERSION "1.6-ko-combo1.1"'
if old_ver not in s:
    raise SystemExit('combo v1.0 version marker not found')
s = s.replace(old_ver, new_ver, 1)

anchor = '''static void drawAlarmPet(int groundY, bool sleeping, uint8_t maxScale = 4) {
  if (pmd.loaded) {
    uint8_t act = sleeping && pmd.has(PMD_SLEEP) ? PMD_SLEEP : PMD_IDLE;
    drawPmdAct(act, CX, groundY, millis(), true, false, maxScale);
    return;
  }
  // Fallback keeps the same proven sprite loader; most installed packs use PMD.
  drawPet();
}
'''
helper = anchor + '''
// Daytime standby pet: walk left/right across the lower part of the round screen.
// Uses the same 06:00..19:59 daytime boundary as the normal TamaPoke scene.
static void drawStandbyAwakePet(int groundY) {
  if (pmd.loaded) {
    const int leftX = 138;
    const int rightX = 328;
    const uint32_t span = (uint32_t)(rightX - leftX);
    const uint32_t phase = (millis() / 18UL) % (span * 2UL);
    const bool goingRight = phase < span;
    const int x = goingRight
      ? leftX + (int)phase
      : rightX - (int)(phase - span);

    uint8_t act = PMD_IDLE;
    if (goingRight && pmd.has(PMD_WALKR)) act = PMD_WALKR;
    else if (!goingRight && pmd.has(PMD_WALKL)) act = PMD_WALKL;
    drawPmdAct(act, x, groundY, millis(), true, false, 3);
    return;
  }
  drawPet();
}
'''
if anchor not in s:
    raise SystemExit('drawAlarmPet anchor not found')
s = s.replace(anchor, helper, 1)

old_scene = '''  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, C565(0x0d,0x17,0x2a));

  // Small night-sky decoration.
  for (auto &st : STARS) gfx->fillCircle(st[0], st[1], 2, UI_WHITE);
  gfx->fillCircle(362, 98, 31, C565(0xff,0xf5,0xc9));
  gfx->fillCircle(378, 87, 29, C565(0x0d,0x17,0x2a));
'''
new_scene = '''  const bool dayMode = (tmv.tm_hour >= 6 && tmv.tm_hour < 20);
  const uint16_t standbyBg = dayMode ? C565(0x2f,0x83,0xc5) : C565(0x0d,0x17,0x2a);

  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, standbyBg);

  if (dayMode) {
    // Day: clear sky + sun. No stars/moon while the pet is awake.
    const uint16_t sun = C565(0xff,0xd4,0x4f);
    gfx->fillCircle(362, 98, 26, sun);
    gfx->drawLine(362, 58, 362, 68, sun);
    gfx->drawLine(362, 128, 362, 138, sun);
    gfx->drawLine(322, 98, 332, 98, sun);
    gfx->drawLine(392, 98, 402, 98, sun);
    gfx->drawLine(334, 70, 341, 77, sun);
    gfx->drawLine(383, 119, 390, 126, sun);
    gfx->drawLine(334, 126, 341, 119, sun);
    gfx->drawLine(383, 77, 390, 70, sun);
  } else {
    // Night: keep the original stars and crescent moon.
    for (auto &st : STARS) gfx->fillCircle(st[0], st[1], 2, UI_WHITE);
    gfx->fillCircle(362, 98, 31, C565(0xff,0xf5,0xc9));
    gfx->fillCircle(378, 87, 29, standbyBg);
  }
'''
if old_scene not in s:
    raise SystemExit('standby night scene block not found')
s = s.replace(old_scene, new_scene, 1)

old_pet = '''  drawAlarmPet(385, true, 3);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(320, 300); gfx->print("Zzz...");
  gfx->flush();
'''
new_pet = '''  if (dayMode) {
    drawStandbyAwakePet(385);
  } else {
    drawAlarmPet(385, true, 3);
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(320, 300); gfx->print("Zzz...");
  }
  gfx->flush();
'''
if old_pet not in s:
    raise SystemExit('standby sleeping pet block not found')
s = s.replace(old_pet, new_pet, 1)

p.write_text(s, encoding='utf-8')
print('combo v1.1 standby applied: day 06-19 sun + walking, night moon + sleeping')
