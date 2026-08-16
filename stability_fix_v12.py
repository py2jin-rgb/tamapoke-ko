from pathlib import Path
import re
import sys


def replace_once(src: str, old: str, new: str, label: str) -> str:
    if old not in src:
        raise SystemExit(f"stability patch marker not found: {label}")
    return src.replace(old, new, 1)


def patch_common(root: Path) -> None:
    p = root / "TamaPoke.ino"
    s = p.read_text(encoding="utf-8")

    # Medal/milestone popup: Korean UTF-8 must go through the language-aware renderer.
    old = '''  gfx->setTextColor(UI_INK);
  gfx->setTextSize(3);
  gfx->setCursor(CX - strlen(l1) * 9, 176);
  gfx->print(l1);
  gfx->setTextSize(2);
  gfx->setCursor(CX - strlen(l2) * 6, 212);
  gfx->print(l2);'''
    new = '''  uiPrintCenter(l1, 172, UI_INK, 3);
  uiPrintCenter(l2, 208, UI_INK, 2);'''
    s = replace_once(s, old, new, f"{root}: medal celebration renderer")

    # Medal badges on the profile page had the same byte-length/ASCII-font problem.
    old = '''  gfx->setTextColor(got ? UI_BG_DAY : 0x9492);
  gfx->setTextSize(2);
  gfx->setCursor(x + (100 - (int)strlen(medalLabel(i)) * 12) / 2, y + 5);
  gfx->print(medalLabel(i));'''
    new = '''  const char *ml = medalLabel(i);
  uiPrintAt(ml, x + (100 - uiTextWidth(ml, 2)) / 2, y + 3,
            got ? UI_BG_DAY : 0x9492, 2);'''
    s = replace_once(s, old, new, f"{root}: medal badge renderer")

    # Show the current RTC time immediately while the pet is sleeping.
    old = '''  if (pet.sleeping) {
    gfx->setTextColor(UI_INK_NIGHT);
    gfx->setTextSize(3);
    gfx->setCursor(320, 130);
    gfx->print("Zz");
  }'''
    new = '''  if (pet.sleeping) {
    uint32_t sleepEpoch = rtcEpoch();
    if (!sleepEpoch) sleepEpoch = pet.lastSeenEpoch;
    char sleepTime[8];
    if (sleepEpoch) snprintf(sleepTime, sizeof(sleepTime), "%02u:%02u",
                             (unsigned)((sleepEpoch / 3600UL) % 24UL),
                             (unsigned)((sleepEpoch / 60UL) % 60UL));
    else snprintf(sleepTime, sizeof(sleepTime), "--:--");
    uiPrintCenter(sleepTime, 76, UI_INK_NIGHT, 3);
    gfx->setTextColor(UI_INK_NIGHT);
    gfx->setTextSize(3);
    gfx->setCursor(320, 130);
    gfx->print("Zz");
  }'''
    s = replace_once(s, old, new, f"{root}: sleeping clock overlay")

    # Make the on-device version distinguishable without changing save layout.
    m = re.search(r'#define FW_VERSION "([^"]+)"', s)
    if not m:
        raise SystemExit(f"{root}: FW_VERSION not found")
    current = m.group(1)
    if not current.endswith("-stability1"):
        s = s[:m.start(1)] + current + "-stability1" + s[m.end(1):]

    p.write_text(s, encoding="utf-8")
    print(f"common stability fixes applied: {root}")


def patch_alarm_style(root: Path, combo: bool = False) -> None:
    p = root / "TamaPoke.ino"
    s = p.read_text(encoding="utf-8")

    # Manual sleep should open the clock immediately instead of waiting 30 seconds.
    old = '''  return millis() - lastInteract >= 30000UL;'''
    new = '''  return pet.sleeping || millis() - lastInteract >= 30000UL;'''
    s = replace_once(s, old, new, f"{root}: immediate sleep standby")

    # First gesture from a manually sleeping standby clock wakes the pet as it exits.
    # This removes the confusing clock -> frozen-looking game -> separate Wake step.
    old = '''    if (!holdFired && gestureFromStandby) {
      // 대기 시계에서 첫 탭은 해제만. 아래 스와이프만 설정 화면으로 진입.
      if (abs(dy) > 80 && abs(dx) < 70 && dt < 800 && dy > 0) openClock();
      gestureFromStandby = false;
    } else if (!holdFired && !swallowGesture) {'''
    new = '''    if (!holdFired && gestureFromStandby) {
      // First interaction leaves standby. If standby came from manual sleep,
      // wake the pet at the same time so gameplay resumes without a second tap.
      const bool wakeFromSleep = pet.sleeping;
      if (abs(dy) > 80 && abs(dx) < 70 && dt < 800 && dy > 0) openClock();
      if (wakeFromSleep) pet.toggleLight();
      gestureFromStandby = false;
      swallowGesture = false;
    } else if (!holdFired && !swallowGesture) {'''
    s = replace_once(s, old, new, f"{root}: wake on standby exit")

    if combo:
        # The combo daytime standby normally shows a walking pet. Manual sleep must
        # always use the night/sleep visual even if the real clock says daytime.
        old = '''  const bool dayMode = (tmv.tm_hour >= 6 && tmv.tm_hour < 20);'''
        new = '''  const bool dayMode = !pet.sleeping && (tmv.tm_hour >= 6 && tmv.tm_hour < 20);'''
        s = replace_once(s, old, new, f"{root}: manual sleep overrides daytime standby")

    p.write_text(s, encoding="utf-8")
    print(f"alarm-style stability fixes applied: {root}")


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: stability_fix_v12.py STABLE_ROOT ALARM_ROOT COMBO_ROOT")
    stable, alarm, combo = map(Path, sys.argv[1:])
    for root in (stable, alarm, combo):
        patch_common(root)
    patch_alarm_style(alarm, combo=False)
    patch_alarm_style(combo, combo=True)
    print("ALL stability fixes applied")


if __name__ == "__main__":
    main()
