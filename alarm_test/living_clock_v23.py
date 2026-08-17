from pathlib import Path
import re
import shutil
import subprocess

# Alarm-only Living Clock experiment. The combo firmware is intentionally untouched.
root = Path('source_alarm/TamaPoke')
ino = root / 'TamaPoke.ino'
src = ino.read_text(encoding='utf-8')


def replace_function(src: str, signature: str, new_func: str) -> str:
    m = re.search(re.escape(signature) + r'\s*\{', src)
    if not m:
        raise SystemExit(f'Living Clock function not found: {signature}')
    start = m.start()
    brace = src.find('{', m.start(), m.end())
    depth = 0
    end = None
    for i in range(brace, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise SystemExit('Living Clock closing brace not found')
    return src[:start] + new_func + src[end:]


# Distinguishable test firmware version; save/NVS layout is unchanged.
src, n = re.subn(r'#define FW_VERSION "[^"]+"',
                 '#define FW_VERSION "1.6-ko-livingclock-test1"', src, count=1)
if n != 1:
    raise SystemExit('Living Clock FW_VERSION not found')

helper = r'''
// ---------- Living Clock TEST (alarm build only) ----------
static uint8_t livingPartOfDay(const struct tm &t) {
  const int h = t.tm_hour;
  if (h >= 5 && h < 8) return 0;   // dawn
  if (h >= 8 && h < 16) return 1;  // day
  if (h >= 16 && h < 19) return 2; // sunset
  if (h >= 19 && h < 22) return 3; // evening
  return 4;                        // night
}

static void livingCloud(int x, int y, uint16_t c) {
  gfx->fillCircle(x, y, 10, c);
  gfx->fillCircle(x + 14, y - 5, 15, c);
  gfx->fillCircle(x + 31, y + 1, 11, c);
  gfx->fillRoundRect(x - 4, y, 42, 12, 6, c);
}

static void livingStar(int x, int y, uint16_t c, uint8_t r=2) {
  gfx->fillCircle(x, y, r, c);
  if (r > 1) {
    gfx->drawLine(x - r - 2, y, x + r + 2, y, c);
    gfx->drawLine(x, y - r - 2, x, y + r + 2, c);
  }
}

static void livingPet(int groundY, bool sleeping, uint8_t mood) {
  if (pmd.loaded) {
    uint8_t act = sleeping && pmd.has(PMD_SLEEP) ? PMD_SLEEP : PMD_IDLE;
    bool flip = false;
    int x = CX;
    if (!sleeping) {
      // Slow wandering plus short pauses gives the desk clock a living-diorama feel.
      const uint32_t cycle = (millis() / 35UL) % 520UL;
      if (cycle < 160 && pmd.has(PMD_WALKR)) { act = PMD_WALKR; x = 145 + (int)cycle / 2; }
      else if (cycle < 220) { act = PMD_IDLE; x = 225; }
      else if (cycle < 380 && pmd.has(PMD_WALKL)) { act = PMD_WALKL; x = 305 - (int)(cycle - 220) / 2; }
      else { act = PMD_IDLE; x = 225; }
      // Every few seconds add a tiny bob so idle poses do not feel frozen.
      if (mood == 2) groundY -= (int)((millis() / 240UL) & 1UL) * 4;
    }
    drawPmdAct(act, x, groundY, millis(), true, flip, 3);
    return;
  }
  drawPet();
}
'''

marker = 'void renderStandbyClock() {'
if marker not in src:
    raise SystemExit('Living Clock standby marker missing')
src = src.replace(marker, helper + '\n' + marker, 1)

new_clock = r'''void renderStandbyClock() {
  uint32_t e = rtcEpoch();
  if (!e) e = pet.lastSeenEpoch;
  time_t tt = (time_t)e;
  struct tm tmv = {};
  gmtime_r(&tt, &tmv);

  const uint8_t pod = livingPartOfDay(tmv);
  const bool sleeping = pet.sleeping || pod == 4;

  uint16_t skyTop, skyLow, horizon, accent, soft;
  switch (pod) {
    case 0: // dawn: violet -> peach
      skyTop = C565(0x5d,0x63,0x9f); skyLow = C565(0xf4,0xa2,0x86);
      horizon = C565(0x78,0xa8,0x7d); accent = C565(0xff,0xd5,0x86); soft = C565(0xff,0xe6,0xd8); break;
    case 1: // day: bright blue
      skyTop = C565(0x35,0x8f,0xd2); skyLow = C565(0x82,0xc9,0xeb);
      horizon = C565(0x55,0xab,0x69); accent = C565(0xff,0xd8,0x50); soft = C565(0xe7,0xf7,0xff); break;
    case 2: // sunset: orange + magenta
      skyTop = C565(0x7b,0x52,0x91); skyLow = C565(0xf2,0x78,0x66);
      horizon = C565(0x55,0x79,0x63); accent = C565(0xff,0xbf,0x63); soft = C565(0xff,0xd5,0xc7); break;
    case 3: // evening: indigo
      skyTop = C565(0x28,0x35,0x68); skyLow = C565(0x5b,0x55,0x8a);
      horizon = C565(0x35,0x50,0x55); accent = C565(0xff,0xe2,0x93); soft = C565(0xc9,0xd5,0xff); break;
    default: // deep night
      skyTop = C565(0x0d,0x16,0x32); skyLow = C565(0x20,0x25,0x55);
      horizon = C565(0x22,0x38,0x45); accent = C565(0xff,0xf0,0xb0); soft = C565(0xb8,0xc8,0xff); break;
  }

  gfx->fillScreen(RGB565_BLACK);
  gfx->fillCircle(CX, CY, 231, skyTop);
  gfx->fillCircle(CX, CY + 151, 214, skyLow);
  gfx->drawCircle(CX, CY, 224, soft);

  // Time-of-day scenery. Everything is drawn procedurally, so it costs almost no flash.
  if (pod == 0) {
    gfx->fillCircle(361, 118, 22, accent);
    livingCloud(80 + (millis()/120UL)%55, 96, soft);
  } else if (pod == 1) {
    gfx->fillCircle(366, 98, 25, accent);
    livingCloud(74 + (millis()/150UL)%65, 90, soft);
    livingCloud(294 - (millis()/210UL)%50, 151, C565(0xd5,0xef,0xfa));
  } else if (pod == 2) {
    gfx->fillCircle(363, 137, 28, accent);
    // Slow drifting leaf/spark particles at sunset.
    for (uint8_t i=0;i<5;i++) {
      int x = 75 + (int)((millis()/45UL + i*73UL) % 330UL);
      int y = 90 + (int)((millis()/90UL + i*47UL) % 135UL);
      gfx->fillCircle(x, y, 2, C565(0xff,0xc0,0x71));
    }
  } else {
    // Evening/night: crescent, stars and an occasional shooting star.
    gfx->fillCircle(365, 105, pod == 3 ? 23 : 27, accent);
    gfx->fillCircle(379, 94, pod == 3 ? 22 : 26, skyTop);
    static const int16_t stars[][2] = {{86,88},{122,142},{161,82},{303,84},{405,142},{74,183},{390,194},{146,226},{327,238}};
    for (auto &st : stars) livingStar(st[0], st[1], soft, ((st[0] + millis()/700UL) & 3) == 0 ? 2 : 1);
    if (((millis()/1000UL) % 23UL) < 2UL) {
      int sx = 98 + (int)((millis()/18UL) % 165UL);
      int sy = 105 + (sx - 98)/3;
      gfx->drawLine(sx, sy, sx-28, sy-12, UI_WHITE);
      gfx->drawLine(sx-1, sy+1, sx-20, sy-7, soft);
    }
  }

  // Landscape without a rectangular pet card: the Pokemon lives directly in the scene.
  gfx->fillCircle(CX, 428, 180, horizon);
  gfx->fillCircle(112, 421, 74, pod <= 2 ? C565(0x48,0x86,0x5a) : C565(0x25,0x3a,0x46));
  gfx->fillCircle(365, 427, 78, pod <= 2 ? C565(0x4f,0x8f,0x61) : C565(0x29,0x3d,0x4b));

  // Centered battery + USB/charging pill.
  const int pct = batPercent();
  const bool hasBat = pct >= 0;
  const bool plugged = hasBat && usbPresent();
  const bool charging = hasBat && batCharging();
  const uint16_t glass = C565(0x18,0x25,0x42);
  gfx->fillRoundRect(CX - 75, 22, 150, 34, 17, glass);
  gfx->drawRoundRect(CX - 75, 22, 150, 34, 17, soft);
  const int ibx = CX - 59, iby = 31, ibw = 29, ibh = 15;
  const uint16_t batCol = charging ? UI_BAR_OK : UI_WHITE;
  gfx->drawRoundRect(ibx, iby, ibw, ibh, 3, batCol);
  gfx->fillRect(ibx + ibw, iby + 5, 3, 6, batCol);
  if (hasBat && !plugged) {
    int fw = (ibw - 4) * (pct > 100 ? 100 : pct) / 100;
    if (fw > 0) gfx->fillRect(ibx + 2, iby + 2, fw, ibh - 4, batCol);
  }
  if (plugged) {
    const uint16_t bolt = charging ? UI_BAR_OK : C565(0xff,0xd9,0x4a);
    gfx->fillTriangle(ibx+17, iby, ibx+10, iby+8, ibx+15, iby+8, bolt);
    gfx->fillTriangle(ibx+13, iby+7, ibx+19, iby+7, ibx+11, iby+15, bolt);
  }
  char bp[10]; snprintf(bp, sizeof(bp), hasBat ? "%d%%" : "--%%", hasBat ? (pct>100?100:pct) : 0);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(CX - 16, 32); gfx->print(bp);
  if (plugged) { gfx->setTextSize(1); gfx->setCursor(CX+36, 35); gfx->print(charging ? "CHG" : "USB"); }

  if (alarmEnabled()) {
    char ab[8]; snprintf(ab, sizeof(ab), "%02u:%02u", alarmHour(), alarmMinute());
    gfx->fillRoundRect(CX-60, 65, 120, 26, 13, glass);
    drawBellMini(CX-41, 68, UI_BAR_WARN);
    gfx->setTextColor(UI_WHITE); gfx->setTextSize(2); gfx->setCursor(CX-16, 71); gfx->print(ab);
  }

  // Large clock typography.
  char tb[8]; snprintf(tb, sizeof(tb), "%02d:%02d", tmv.tm_hour, tmv.tm_min);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(8);
  gfx->setCursor(CX - (int)strlen(tb)*24, 112); gfx->print(tb);

  char db[24]; snprintf(db, sizeof(db), "%04d.%02d.%02d", tmv.tm_year+1900, tmv.tm_mon+1, tmv.tm_mday);
  gfx->setTextColor(UI_WHITE); gfx->setTextSize(3);
  gfx->setCursor(CX - (int)strlen(db)*9, 205); gfx->print(db);
  if (gLang == LANG_KO) uiPrintCenter(weekdayKo(tmv.tm_wday), 239, UI_WHITE, 3);

  // Hourly mini-event: once per hour, 4 seconds of a celebratory overlay and a short cue.
  static int lastHourlyKey = -1;
  static uint32_t hourlyUntil = 0;
  const int hourlyKey = (tmv.tm_yday * 24) + tmv.tm_hour;
  if (tmv.tm_min == 0 && lastHourlyKey != hourlyKey) {
    lastHourlyKey = hourlyKey;
    hourlyUntil = millis() + 4000UL;
    sfxPlay(SFX_TAP);
  }
  if ((int32_t)(hourlyUntil - millis()) > 0) {
    const int pulse = 58 + (int)((millis()/90UL)%8UL);
    gfx->fillCircle(CX, 325, pulse, C565(0xff,0xd4,0x55));
    gfx->fillCircle(CX, 325, pulse-8, C565(0xf4,0x78,0x65));
    char hb[12]; snprintf(hb, sizeof(hb), "%02d:00", tmv.tm_hour);
    uiPrintCenter(koOr("정각!","HOURLY!"), 278, UI_WHITE, 2);
    uiPrintCenter(hb, 311, UI_WHITE, 3);
    livingPet(406, false, 2);
    gfx->flush();
    return;
  }

  // Alarm-time wake scene. Alarm audio/stop behavior remains handled by the existing alarm engine;
  // this only adds a brighter visual whenever the standby renderer is visible while ringing.
  if (alarmRinging()) {
    const uint32_t p = (millis()/140UL)%18UL;
    gfx->fillCircle(CX, 330, 72 + (int)p, C565(0xff,0xc1,0x4f));
    gfx->fillCircle(CX, 330, 58 + (int)p/2, C565(0xff,0xea,0x9e));
    uiPrintCenter(koOr("일어날 시간!","WAKE UP!"), 274, UI_INK, 3);
    livingPet(409 - (int)((millis()/160UL)&1UL)*8, false, 2);
    gfx->flush();
    return;
  }

  // Living Pokemon behavior. At night it sleeps; daytime/evening it wanders and pauses.
  livingPet(404, sleeping, (uint8_t)((millis()/5000UL)%3UL));
  if (sleeping) {
    gfx->setTextColor(soft); gfx->setTextSize(2); gfx->setCursor(319, 326); gfx->print("Zzz...");
  } else if (((millis()/1000UL)%17UL) < 3UL) {
    // Tiny speech bubble / idle moment every so often, no audio spam.
    gfx->fillRoundRect(300, 307, 74, 31, 14, UI_WHITE);
    uiPrintCenter(koOr("좋은 하루!","HI!"), 314, UI_INK, 1);
  }

  gfx->flush();
}'''

src = replace_function(src, 'void renderStandbyClock()', new_clock)
ino.write_text(src, encoding='utf-8')

# Compile only the alarm firmware again. Combo stays byte-for-byte as built before this script.
fqbn = 'esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build = Path('build_alarm')
if build.exists():
    shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(root)], check=True)
if not (build/'TamaPoke.ino.bin').is_file():
    raise SystemExit('Living Clock alarm binary missing')
print('Living Clock TEST alarm firmware compiled successfully')

# Installer card: touch only the alarm card.
page = Path('site/index.html')
html = page.read_text(encoding='utf-8')
repls = [
    ('⏰ ALARM · CLOCK UI 1.2', '🌅 ALARM · LIVING CLOCK TEST'),
    ('<h2>② 알람시계판</h2>', '<h2>② Living Clock 알람 테스트판</h2>'),
    ('manifest-alarm.json?v=stability2', 'manifest-alarm.json?v=livingclock23'),
    ('<button slot="activate">⏰ 알람시계판 설치</button>', '<button slot="activate">🌅 Living Clock 테스트 설치</button>'),
]
for old,new in repls:
    if old not in html:
        raise SystemExit(f'Living Clock page marker missing: {old}')
    html = html.replace(old,new,1)

anchor = '<p class="ok">✓ 낮/밤 투톤 시계 디자인 · 날짜/요일/알람 표시 재배치</p>'
extra = anchor + (
    '<p class="ok">✓ 새벽·낮·노을·저녁·밤 5단계 자동 배경</p>'
    '<p class="ok">✓ 포켓몬 좌우 산책·멈춤·수면 등 Living 행동</p>'
    '<p class="ok">✓ 구름·별·별똥별·노을 파티클 등 가벼운 화면 연출</p>'
    '<p class="ok">✓ 매 정각 4초 포켓몬 이벤트 + 짧은 효과음</p>'
    '<p class="ok">✓ 알람 울림 중 밝은 WAKE UP / 일어날 시간 연출</p>'
    '<p class="ok">✓ ③ 천지인 한방팩은 변경하지 않은 알람 전용 테스트</p>'
)
if anchor not in html:
    raise SystemExit('Living Clock page feature anchor missing')
html = html.replace(anchor, extra, 1)
page.write_text(html, encoding='utf-8')
print('Living Clock TEST installer page updated')
