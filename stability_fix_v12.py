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

    # Keep the normal game screen simple while sleeping. Clock/time belongs to the
    # dedicated clock view; use only native ASCII here to avoid garbled text.
    old = '''  if (pet.sleeping) {
    gfx->setTextColor(UI_INK_NIGHT);
    gfx->setTextSize(3);
    gfx->setCursor(320, 130);
    gfx->print("Zz");
  }'''
    new = '''  if (pet.sleeping) {
    gfx->setTextColor(UI_INK_NIGHT);
    gfx->setTextSize(2);
    gfx->setCursor(312, 132);
    gfx->print("Zzz...");
  }'''
    s = replace_once(s, old, new, f"{root}: clean sleeping text")

    # Make the on-device version distinguishable without changing save layout.
    m = re.search(r'#define FW_VERSION "([^"]+)"', s)
    if not m:
        raise SystemExit(f"{root}: FW_VERSION not found")
    current = m.group(1)
    if not current.endswith("-stability2"):
        s = s[:m.start(1)] + current + "-stability2" + s[m.end(1):]

    p.write_text(s, encoding="utf-8")
    print(f"common stability2 fixes applied: {root}")


def patch_alarm_style(root: Path, combo: bool = False) -> None:
    p = root / "TamaPoke.ino"
    s = p.read_text(encoding="utf-8")

    # Clock view is a UI state independent from pet.sleeping.
    old = '''bool gestureFromStandby = false;'''
    new = '''bool gestureFromStandby = false;
bool manualClockView = false;  // PWR short press toggles game <-> clock view'''
    s = replace_once(s, old, new, f"{root}: manual clock state")

    # Automatic standby remains 30 seconds. Sleeping no longer forces the clock.
    old = '''  return millis() - lastInteract >= 30000UL;'''
    new = '''  return manualClockView || millis() - lastInteract >= 30000UL;'''
    s = replace_once(s, old, new, f"{root}: independent standby clock")

    # PWR short press: alarm stop keeps priority. On the normal home screen it
    # toggles clock/game. During modal screens/minigames preserve the old screen
    # off behavior so existing controls are not disrupted.
    old = '''    if (pwrShortPressed()) {
      if (alarmRinging()) {
        alarmStop();
        audioAlarmStop();
        alarmNotice = 2;
        alarmNoticeUntil = now + 3200;
        screenOff = false;
        lastInteract = now;
      } else {
        screenOff = !screenOff;
        if (!screenOff) lastInteract = now;
      }
    }'''
    new = '''    if (pwrShortPressed()) {
      if (alarmRinging()) {
        alarmStop();
        audioAlarmStop();
        alarmNotice = 2;
        alarmNoticeUntil = now + 3200;
        screenOff = false;
        manualClockView = false;
        lastInteract = now;
      } else {
        const bool modalOpen = alarmNotice || clockOpen || gameOpen || sackOpen ||
          galleryOpen || kbOpen || cardOpen || pet.awaitingStarter() || pet.ceremony ||
          confirmUntil || choiceKind || feedMenuUntil || bathUntil;
        if (modalOpen) {
          screenOff = !screenOff;
          if (!screenOff) lastInteract = now;
        } else {
          screenOff = false;
          manualClockView = !manualClockView;
          lastInteract = now;
        }
      }
    }'''
    s = replace_once(s, old, new, f"{root}: PWR clock toggle")

    # Leaving the clock view must never change the pet's sleep state. A tap exits
    # the clock; downward swipe still opens clock/alarm settings as before.
    old = '''    if (!holdFired && gestureFromStandby) {
      // 대기 시계에서 첫 탭은 해제만. 아래 스와이프만 설정 화면으로 진입.
      if (abs(dy) > 80 && abs(dx) < 70 && dt < 800 && dy > 0) openClock();
      gestureFromStandby = false;
    } else if (!holdFired && !swallowGesture) {'''
    new = '''    if (!holdFired && gestureFromStandby) {
      // Clock view and sleep state are independent. Exit the clock without waking.
      if (abs(dy) > 80 && abs(dx) < 70 && dt < 800 && dy > 0) openClock();
      manualClockView = false;
      gestureFromStandby = false;
      swallowGesture = false;
    } else if (!holdFired && !swallowGesture) {'''
    s = replace_once(s, old, new, f"{root}: clock exit without wake")

    if combo:
        # Day/night standby still follows RTC while awake. If the pet itself is
        # sleeping, show the sleeping/night visual even during daytime.
        old = '''  const bool dayMode = (tmv.tm_hour >= 6 && tmv.tm_hour < 20);'''
        new = '''  const bool dayMode = !pet.sleeping && (tmv.tm_hour >= 6 && tmv.tm_hour < 20);'''
        s = replace_once(s, old, new, f"{root}: sleeping pet clock visual")

    p.write_text(s, encoding="utf-8")
    print(f"alarm-style stability2 fixes applied: {root}")


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: stability_fix_v12.py STABLE_ROOT ALARM_ROOT COMBO_ROOT")
    stable, alarm, combo = map(Path, sys.argv[1:])
    for root in (stable, alarm, combo):
        patch_common(root)
    patch_alarm_style(alarm, combo=False)
    patch_alarm_style(combo, combo=True)
    print("ALL stability2 fixes applied")


if __name__ == "__main__":
    main()
