#include <Arduino.h>
#include <driver/i2s_std.h>
#include <esp32-hal-i2c.h>
#include <audio.h>
#include <cstdlib>
#include <functional>

static void waitFor(const char *what, const std::function<bool()> &check, uint32_t timeout = 2500) {
  uint32_t started = millis();
  while (!check()) {
    if (millis() - started > timeout) {
      std::fprintf(stderr, "FAIL timeout: %s; live=%d enabled=%d busy=%d\n", what,
                   Mock::liveChannels.load(), Mock::enabledChannels.load(), audioBusy());
      std::_Exit(1);
    }
    delay(2);
  }
}

static void idle() {
  waitFor("quiescent audio", [] { return !audioBusy() && Mock::liveChannels == 0; });
  assert(!Mock::pa);
  assert(Mock::allocations == Mock::deletes);
}

static void reserve() {
  waitFor("sleep reservation", [] { return audioPrepareSleep(); });
  assert(Mock::enabledChannels == 0 && Mock::liveChannels == 0 && !Mock::pa);
}

static void cueAndIdle() {
  unsigned allocations = Mock::allocations;
  sfxPlay(SFX_TAP);
  waitFor("cue allocated", [allocations] { return Mock::allocations > allocations; });
  idle();
}

int main() {
  audioBegin();
  waitFor("boot cue", [] { return Mock::allocations > 0; });
  idle();
  assert(Mock::suspendEnds >= 2); // Initial cleanup plus post-cue power-down.
  std::puts("PASS TX-only playback, codec suspend, idle channel release");

  reserve();
  unsigned before = Mock::allocations;
  std::thread producer([] { sfxPlay(SFX_TAP); });
  producer.join();
  delay(40);
  assert(audioBusy()); // New request is retained, not dropped by the sleep gate.
  assert(Mock::allocations == before && Mock::enabledChannels == 0);
  audioAfterWake();
  waitFor("reserved cue resumes", [before] { return Mock::allocations > before; });
  idle();
  reserve();
  audioAfterWake(); // A caller may abort the actual sleep and still release.
  cueAndIdle();
  std::puts("PASS prepare/wake reservation, concurrent queued request, sleep cancellation");

  audioSetEnabled(false);
  before = Mock::allocations;
  sfxPlay(SFX_TAP);
  delay(30);
  assert(Mock::allocations == before && !audioBusy());
  audioAlarmStart();
  waitFor("alarm ignores game mute", [] { return Mock::pa.load(); });
  assert(audioBusy() && audioAlarmActive() && !audioPrepareSleep());
  audioAlarmStop();
  idle();
  assert(!audioEnabled());
  audioSetVolume(0);
  before = Mock::allocations;
  audioAlarmStart();
  delay(40);
  assert(audioAlarmActive() && audioBusy() && Mock::allocations == before && !Mock::pa);
  audioAlarmStop();
  idle();
  audioSetVolume(25);
  audioSetEnabled(true);
  assert(audioVolume() == 25);
  audioSetVolume(37);
  assert(audioVolume() == 100);
  std::puts("PASS game mute, silent volume-0 alarm, stop, supported-volume validation");

  reserve();
  before = Mock::allocations;
  std::thread alarmProducer([] { audioAlarmStart(); });
  alarmProducer.join();
  delay(40);
  assert(audioAlarmActive() && Mock::allocations == before && Mock::enabledChannels == 0);
  audioAfterWake();
  waitFor("alarm after sleep reservation", [] { return Mock::pa.load(); });
  audioAlarmStop();
  idle();
  std::puts("PASS alarm arriving during reservation is retained and resumes");

  auto failure = [](const char *label, const std::function<void()> &inject) {
    unsigned allocations = Mock::allocations;
    unsigned starts = Mock::paStarts;
    inject();
    sfxPlay(SFX_TAP);
    waitFor(label, [allocations] { return Mock::allocations > allocations; });
    idle();
    assert(Mock::paStarts == starts); // Never enable PA on failed initialization.
    delay(1100);
    cueAndIdle(); // A later request must recover, with no leaked TX handle.
    std::printf("PASS %s cleanup and recovery\n", label);
  };
  failure("I2S init failure", [] { Mock::failInit = true; });
  failure("I2S enable failure", [] { Mock::failEnable = true; });
  failure("codec write failure", [] { Mock::failRegister = 0x0D; });
  failure("I2S write failure", [] { Mock::failWrite = true; });

  std::puts("All audio host tests passed. Hardware timing/current/pop behavior still requires device verification.");
  std::fflush(stdout);
  std::fflush(stderr);
  // The mocked FreeRTOS worker is a process-lifetime task, just as on device.
  // Exit without destroying static test synchronization objects under it.
  std::_Exit(0);
}
