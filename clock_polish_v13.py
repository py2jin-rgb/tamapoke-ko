from pathlib import Path
import re
import sys


def replace_function(src: str, signature: str, new_func: str, label: str) -> str:
    m = re.search(re.escape(signature) + r'\s*\{', src)
    if not m:
        raise SystemExit(f'clock polish function not found: {label}')
    start = m.start()
    brace = src.find('{', m.start(), m.end())
    if brace < 0:
        raise SystemExit(f'clock polish opening brace not found: {label}')
    depth = 0
    end = None
    for i in range(brace, len(src)):
        ch = src[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise SystemExit(f'clock polish closing brace not found: {label}')
    return src[:start] + new_func + src[end:]


def patch_one(root: Path, combo: bool) -> None:
    p = root / 'TamaPoke.ino'
    src = p.read_text(encoding='utf-8')

    awake_pet = 'drawStandbyAwakePet(392);' if combo else 'drawAlarmPet(392, false, 3);'

    new_func = r'''void renderStandbyClock() {
  uint32_t e = rtcEpoch();
  if (!e) e = pet.lastSeenEpoch;
  time_t tt = (time_t)e;
  struct tm tmv = {};
  gmtime_r(&tt, &tmv);

  const bool dayMode = !pet.sleeping && (tmv.tm_hour >= 6 && tmv.tm_hour < 20);
  const uint16_t sky = dayMode ? C565(0x38,0x8f,0xd1) : C565(0x12,0x18,0x35);
  const uint16_t sky2 = dayMode ? C565(0x6d,0xb8,0xe5) : C565(0x24,0x20,0x4a);
  const uint16_t card = dayMode ? C565(0x20,0x62,0x9a) : C565(0x0b,0x10,0x27);
  const uint16_t soft = dayMode ? C565(0xd9,0xf2,0xff) : C565(0xb9,0xc8,0xff);

  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, sky);
  // Layered circles make a soft two-tone watch face without gradients.
  gfx->fillCircle(CX, CY + 142, 214, sky2);
  gfx->drawCircle(CX, CY, 224, dayMode ? C565(0x9d,0xd7,0xf4) : C565(0x39,0x3d,0x72));

  if (dayMode) {
    // Sun + a soft cloud cluster.
    const uint16_t sun = C565(0xff,0xd8,0x57);
    gfx->fillCircle(365, 102, 24, sun);
    gfx->fillCircle(96, 84, 12, soft);
    gfx->fillCircle(113, 78, 17, soft);
    gfx->fillCircle(132, 86, 11, soft);
    gfx->fillRoundRect(87, 84, 55, 13, 6, soft);
  } else {
    // Crescent moon and calm star field.
    const uint16_t moon = C565(0xff,0xf2,0xc0);
    gfx->fillCircle(363, 105, 28, moon);
    gfx->fillCircle(378, 94, 27, sky);
    static const int16_t clkStars[][2] = {
      {94,91},{126,130},{169,79},{310,94},{404,144},{79,168},{389,185},{144,238}
    };
    for (auto &st : clkStars) gfx->fillCircle(st[0], st[1], 2, UI_WHITE);
  }

  // Battery is deliberately centered. USB power is shown even when the battery
  // is already full and AXP2101 no longer reports an active charge current.
  const int pct = batPercent();
  const bool hasBat = pct >= 0;
  const bool plugged = hasBat && usbPresent();
  const bool charging = hasBat && batCharging();
  const int bx = CX - 78, by = 25, bw = 156, bh = 34;
  gfx->fillRoundRect(bx, by, bw, bh, 17, card);
  gfx->drawRoundRect(bx, by, bw, bh, 17, dayMode ? C565(0x8f,0xce,0xef) : C565(0x4c,0x52,0x86));

  const int ibx = CX - 62, iby = 34, ibw = 31, ibh = 15;
  const uint16_t batCol = charging ? UI_BAR_OK : UI_WHITE;
  gfx->drawRoundRect(ibx, iby, ibw, ibh, 3, batCol);
  gfx->fillRect(ibx + ibw, iby + 5, 3, 6, batCol);
  if (plugged) {
    const uint16_t bolt = charging ? UI_BAR_OK : C565(0xff,0xd9,0x4a);
    const int lx = ibx + 15;
    gfx->fillTriangle(lx + 3, iby + 1, lx - 4, iby + 8, lx + 1, iby + 8, bolt);
    gfx->fillTriangle(lx - 1, iby + 7, lx + 4, iby + 7, lx - 3, iby + 14, bolt);
  } else if (hasBat) {
    int pc = pct > 100 ? 100 : pct;
    int fw = (ibw - 4) * pc / 100;
    if (fw > 0) gfx->fillRect(ibx + 2, iby + 2, fw, ibh - 4, batCol);
  }

  char bp[10];
  if (hasBat) snprintf(bp, sizeof(bp), "%d%%", pct > 100 ? 100 : pct);
  else snprintf(bp, sizeof(bp), "--%%");
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(2);
  gfx->setCursor(CX - 19, 35); gfx->print(bp);
  if (plugged) {
    gfx->setTextSize(1); gfx->setTextColor(charging ? UI_BAR_OK : C565(0xff,0xd9,0x4a));
    gfx->setCursor(CX + 36, 38); gfx->print(charging ? "CHG" : "USB");
  }

  // Alarm gets its own compact centered pill so the top of the round display stays balanced.
  if (alarmEnabled()) {
    char ab[8]; snprintf(ab, sizeof(ab), "%02u:%02u", alarmHour(), alarmMinute());
    gfx->fillRoundRect(CX - 64, 68, 128, 28, 14, card);
    drawBellMini(CX - 43, 71, UI_BAR_WARN);
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(2);
    gfx->setCursor(CX - 20, 75); gfx->print(ab);
  }

  char tb[8]; snprintf(tb, sizeof(tb), "%02d:%02d", tmv.tm_hour, tmv.tm_min);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(8);
  gfx->setCursor(CX - (int)strlen(tb) * 24, 112); gfx->print(tb);

  // Date and weekday are separated so Korean stays crisp and the whole layout remains centered.
  char db[24];
  snprintf(db, sizeof(db), "%04d.%02d.%02d", tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(3);
  gfx->setCursor(CX - (int)strlen(db) * 9, 205); gfx->print(db);
  if (gLang == LANG_KO) {
    uiPrintCenter(weekdayKo(tmv.tm_wday), 239, UI_WHITE, 3);
  }

  // Small horizon card keeps the pet visually anchored without crowding the clock.
  gfx->fillRoundRect(82, 292, 302, 112, 28, card);
  gfx->drawRoundRect(82, 292, 302, 112, 28, dayMode ? C565(0x85,0xc9,0xeb) : C565(0x43,0x47,0x78));
  if (dayMode) {
    gfx->fillRoundRect(105, 372, 256, 8, 4, C565(0x64,0xb6,0x76));
    AWAKE_PET_CALL
  } else {
    gfx->fillRoundRect(105, 372, 256, 8, 4, C565(0x38,0x3d,0x65));
    drawAlarmPet(392, true, 3);
    gfx->setTextColor(soft); gfx->setTextSize(2); gfx->setCursor(319, 320); gfx->print("Zzz...");
  }

  gfx->flush();
}'''.replace('AWAKE_PET_CALL', awake_pet)

    src = replace_function(src, 'void renderStandbyClock()', new_func, str(root))
    p.write_text(src, encoding='utf-8')
    print(f'clock polish v1.3 applied: {root}')


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit('usage: clock_polish_v13.py ALARM_ROOT COMBO_ROOT')
    patch_one(Path(sys.argv[1]), combo=False)
    patch_one(Path(sys.argv[2]), combo=True)
    print('clock polish v1.3 applied to alarm + combo')


if __name__ == '__main__':
    main()
