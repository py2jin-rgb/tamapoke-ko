#include "../firmware/TamaPoke/power_policy.h"
#include <cassert>
#include <iostream>

using namespace TamaPower;

int main() {
  Inputs x{0,50,false,false,false,false,false,false,false,false,false,false,true};
  unsigned cases=0;
  auto check=[&](uint32_t idle, int stage, int bright, int mhz, bool sleep) {
    x.idleMs=idle; auto p=decide(x);
    assert(p.dimStage==stage && p.brightness==bright && p.cpuMHz==mhz && p.maySleep==sleep);
    ++cases;
  };
  check(29999,0,127,240,false);
  check(30000,1,64,240,false);
  check(119999,1,64,240,false);
  check(120000,2,0,80,true);
  x.manualClock=true; check(600000,2,0,80,true);
  x.alwaysOnClock=true; check(600000,1,64,240,false);
  x.manualOff=true; check(600000,1,0,80,true);
  x.alarm=true; check(600000,0,127,240,false);
  x.alarm=false; x.manualOff=false; x.alwaysOnClock=false;
  x.usb=true; check(600000,1,64,240,false);
  x.manualClock=false; check(600000,2,0,80,false);
  x.usb=false; x.radio=true; check(600000,2,0,240,false);
  x.radio=false; x.audio=true; check(600000,2,0,240,false);
  x.audio=false; x.criticalWork=true; check(600000,0,127,240,false);
  x.criticalWork=false; x.touch=true; check(600000,2,0,80,false);
  x.touch=false; x.sleepEnabled=false; check(600000,2,0,80,false);
  x.sleepEnabled=true; x.petSleeping=true; x.brightnessPct=100;
  check(0,0,51,240,false);
  x.alarm=true; check(0,0,255,240,false);
  x.alarm=false; x.petSleeping=false; x.brightnessPct=25;
  check(30000,1,63,240,false);
  // millis wrap and paused-game deadlines must remain valid across UINT32_MAX.
  uint32_t t=0xfffffff0U; shiftDeadline(t,32); assert(t==16 && !reached(15,t) && reached(16,t));
  uint32_t unset=0; shiftDeadline(unset,32); assert(unset==0);
  uint32_t now=50, last=0xffffff00U; x.idleMs=now-last;
  assert(decide(x).dimStage==0); ++cases;
  std::cout << "power policy: " << cases << " scenarios passed\n";
}
