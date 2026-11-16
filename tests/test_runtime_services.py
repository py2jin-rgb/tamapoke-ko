"""Behavioral host checks for the actual low-power runtime service functions.

The production functions are compiled unchanged against small hardware/game
boundary stubs. No renderer is supplied: critical services must work without it.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "firmware/TamaPoke/power_runtime.inc").read_text()


def function(name):
    match = re.search(r"(?m)^(?:static )?void " + name + r"\([^\n]*\)\s*\{", SOURCE)
    if not match:
        raise AssertionError(f"Missing runtime service: {name}")
    at = SOURCE.index("{", match.start(), match.end())
    depth, quote, escaped = 0, None, False
    while at < len(SOURCE):
        c = SOURCE[at]
        if quote:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == quote:
                quote = None
        elif SOURCE.startswith("//", at):
            at = SOURCE.index("\n", at)
            continue
        elif c in "\"'":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if not depth:
                return SOURCE[match.start():at + 1]
        at += 1
    raise AssertionError(f"Unclosed service: {name}")


HEADER = r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <string>
#include "power_policy.h"
'''


class RuntimeServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("g++"):
            raise unittest.SkipTest("g++ required for production C++ function tests")
        cls.temp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def compile(self, name, source):
        cpp = self.work / (name + ".cpp")
        exe = self.work / name
        cpp.write_text(HEADER + source)
        result = subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra",
                                 "-I", str(ROOT / "firmware/TamaPoke"), str(cpp), "-o", str(exe)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return exe

    def run_case(self, exe, case=None):
        result = subprocess.run([str(exe)] + ([case] if case else []), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pet_alarm_and_bath_complete_without_any_render(self):
        harness = r'''
static uint32_t fakeNow=1000;
uint32_t millis(){return fakeNow;}
static bool gameOpen=true,sackOpen=false,gameMenuOpen=false,arcMenuOpen=false;
static bool arcTetrisOpen=false,arcSnakeOpen=false,arcMineOpen=false;
static bool moleOpen=false,rpsOpen=false,quizOpen=false,catchOpen=false,galleryOpen=false;
static bool kbOpen=false,clockOpen=false,cardOpen=false,screenOff=true,manualClockView=true;
static bool powerForceRender=false,bathPending=true,ringing=false,fireAlarm=false;
static uint8_t dimStage=2,choiceKind=0,alarmNotice=0;
static uint32_t feedMenuUntil=0,confirmUntil=0,choiceUntil=0,lastInteract=0;
static uint32_t alarmNoticeUntil=0,bathUntil=900;
static int polls=0,radioStops=0,alarmStarts=0,alarmStops=0,audioServices=0;
struct PetMock{
 int updates=0,cleans=0;uint32_t updatedAt=0;
 void update(uint32_t now){++updates;updatedAt=now;}
 bool wantEvolveButton(){return false;}bool canRunawayNow(){return false;}
 void clean(){++cleans;}
}pet;
struct UnloadMock{int unloads=0;void unload(){++unloads;}}galleryPmd,miniOpponentPmd;
enum {PMD_POSE=0,SFX_MEDAL=1,SFX_DENY=2};
struct {int acts[1]={500};bool has(int){return true;}}pmd;
struct {int mode=0,act=0;uint32_t t0=0,until=0;}beh;
uint32_t pmdActTotalMs(int a){return a;}
uint32_t rtcEpoch(){return 1800000000;}
void alarmUpdate(uint32_t){++polls;if(fireAlarm)ringing=true;}
bool alarmRinging(){return ringing;}
void radioOnAlarm(){++radioStops;}
void audioAlarmStart(){++alarmStarts;}void audioAlarmStop(){++alarmStops;}
void audioService(){++audioServices;}void sfxPlay(int){}
'''
        harness += function("serviceCriticalTasks")
        harness += r'''
int main(){
 // Screen stays off, yet the pet advances and a timed bath completes once.
 serviceCriticalTasks();
 assert(pet.updates==1&&pet.updatedAt==1000&&polls==1&&screenOff);
 assert(pet.cleans==1&&!bathPending&&bathUntil==0&&beh.until==2000);
 fakeNow=1001;serviceCriticalTasks();assert(pet.updates==2&&polls==1&&pet.cleans==1);
 // No renderer or wireless pump exists in this harness; the alarm still wakes UI/audio.
 fakeNow=2000;fireAlarm=true;serviceCriticalTasks();
 assert(polls==2&&radioStops==1&&alarmStarts==1);
 assert(!screenOff&&!manualClockView&&!gameOpen&&powerForceRender&&dimStage==0);
 assert(galleryPmd.unloads==1&&miniOpponentPmd.unloads==1);
 fakeNow=2001;serviceCriticalTasks();assert(radioStops==1&&alarmStarts==1);
 ringing=false;fakeNow=2002;serviceCriticalTasks();assert(alarmStops==1&&audioServices==5);
}
'''
        self.run_case(self.compile("critical", harness))

    def test_minigames_pause_and_resume_without_sleep_catchup(self):
        harness = r'''
static bool gameOpen=false,sackOpen=false,moleOpen=false,rpsOpen=false,quizOpen=false,catchOpen=false;
static bool arcTetrisOpen=false,arcSnakeOpen=false,arcMineOpen=false,powerPanelSleeping=false;
static bool ringing=false,otaWorking=false,sackNewHi=false,rpsNewHi=false;
static bool quizCompleted=false,quizWasCorrect=false,arcTOver=false,arcSOver=false;
static uint32_t gameOverUntil=0,hitTime=0,sackUntil=0,sackOverUntil=0,moleNextAt=0;
static uint32_t moleResultUntil=0,moleStageBannerUntil=0,rpsRevealUntil=0,rpsResultUntil=0;
static uint32_t quizCountdownEnd=0,quizFeedbackUntil=0,catchEndAt=0,catchResultUntil=0,catchLastStep=0;
static uint32_t arcTNext=0,arcTBanner=0,arcSNext=0,arcSBanner=0,arcMClearUntil=0;
static int sackHits=0,sackGain=0,rpsPlayer=0,rpsCpu=0,rpsRound=0,rpsWins=0,rpsDraws=0;
static int quizLevel=0,catchLives=3,catchItemY=0,catchItemX=0,catchPetX=0,catchItemType=0,catchScore=0;
static int arcMStage=1,ballSteps=0,snakeSteps=0,tetrisSteps=0,catchFinishes=0;
static float sackShake=0;
enum {SFX_MEDAL,SFX_PLAY,SFX_GAME_TICK,SFX_GAME_OVER,SFX_DENY,SFX_GAME_START,CATCH_ROCK};
struct {int strHi=0,rpsHi=0;int trainStrength(int){return 0;}void minigameReward(int){}}pet;
struct {void unload(){}}miniOpponentPmd;
bool alarmRinging(){return ringing;}bool otaBusy(){return otaWorking;}
void sfxPlay(int){}void stepGame(){++ballSteps;}void molePickNew(){}
void quiz151PrepareLevel(){}void catchFinish(uint32_t){++catchFinishes;}
int catchSpeed(){return 2;}int catchValue(int){return 1;}void catchSpawnItem(){}
void arcTDrop(){++tetrisSteps;}uint32_t arcTDelay(){return 100;}
void arcSMove(){++snakeSteps;}uint32_t arcSSpeed(){return 100;}
void arcMSetupStage(int){}
'''
        harness += function("serviceGameLogic")
        harness += r'''
int main(int argc,char **argv){
 assert(argc==2);std::string test=argv[1];
 if(test=="ball"){
  gameOpen=true;hitTime=100;serviceGameLogic(100);assert(ballSteps==1);
  powerPanelSleeping=true;serviceGameLogic(120);serviceGameLogic(10000);assert(ballSteps==1);
  powerPanelSleeping=false;serviceGameLogic(10120);assert(ballSteps==1&&hitTime==10100);
  serviceGameLogic(10204);assert(ballSteps==1);serviceGameLogic(10205);assert(ballSteps==2);
 }else if(test=="snake"||test=="tetris"){
  if(test=="snake"){arcSnakeOpen=true;arcSNext=1100;}else{arcTetrisOpen=true;arcTNext=1100;}
  serviceGameLogic(1000);powerPanelSleeping=true;serviceGameLogic(1050);serviceGameLogic(10000);
  assert(snakeSteps==0&&tetrisSteps==0);
  powerPanelSleeping=false;serviceGameLogic(11050);assert(snakeSteps==0&&tetrisSteps==0);
  assert((test=="snake"?arcSNext:arcTNext)==11100);
  serviceGameLogic(11100);assert(snakeSteps+tetrisSteps==1);
 }else if(test=="catch"){
  catchOpen=true;catchLastStep=1000;catchEndAt=36000;serviceGameLogic(1000);
  powerPanelSleeping=true;serviceGameLogic(1010);serviceGameLogic(10000);assert(catchItemY==0);
  powerPanelSleeping=false;serviceGameLogic(11010);
  assert(catchLastStep==11000&&catchEndAt==46000&&catchItemY==0&&catchFinishes==0);
  serviceGameLogic(11037);assert(catchItemY==0);
  serviceGameLogic(11049);assert(catchItemY==2&&catchLastStep==11038);
  serviceGameLogic(11075);assert(catchItemY==2);serviceGameLogic(11076);assert(catchItemY==4);
 }else if(test=="changed-modal"){
  gameOpen=true;powerPanelSleeping=true;serviceGameLogic(1000);
  gameOpen=false;arcTetrisOpen=true;arcTNext=12000;
  powerPanelSleeping=false;serviceGameLogic(11000);assert(arcTNext==12000&&tetrisSteps==0);
 }else return 2;
}
'''
        exe = self.compile("games", harness)
        for case in ("ball", "snake", "tetris", "catch", "changed-modal"):
            with self.subTest(case=case):
                self.run_case(exe, case)

    def test_sleep_reservation_is_released_on_success_cancel_and_failure(self):
        harness = r'''
using esp_err_t=int;
using gpio_num_t=int;
enum {ESP_OK=0,ESP_FAIL=-1,LOW=0,HIGH=1,TP_INT=11,ESP_SLEEP_WAKEUP_GPIO=3,
      GPIO_INTR_NEGEDGE=2,GPIO_INTR_LOW_LEVEL=4};
static uint32_t fakeNow=1000,powerSleepRetryAt=0,powerSleepCount=0,powerSleepErrors=0;
static uint64_t powerSleepUs=0;static int64_t fakeUs=0;
static esp_err_t powerLastSleepError=0;
static bool gTouchIrq=false,wasPressed=false,powerPanelSleeping=true,powerWakeReady=true;
static bool radio=false,ota=false,audio=false,alarm=false,usb=false,reserveOk=true,cancelAfterReserve=false;
static bool cancelAfterConfig=false,irqEnabled=true,wakeArmed=false,freshUsb=false;
static int gpio=HIGH,prepareCalls=0,reservations=0,releases=0,sleepCalls=0;
static int timerResult=ESP_OK,sleepResult=ESP_OK,wakeResult=ESP_OK,wakeCause=0;
static int irqType=GPIO_INTR_NEGEDGE,irqMasks=0,irqRestores=0;
static TamaPower::Plan powerPlan{2,0,80,true,true};
struct {int available(){return 0;}}Serial;
uint32_t millis(){return fakeNow;}int digitalRead(int){return gpio;}
bool radioBusy(){return radio;}bool otaBusy(){return ota;}bool audioBusy(){return audio;}
bool alarmRinging(){return alarm;}bool usbPresent(){return usb;}
bool usbPresentNow(){return freshUsb;}
void delay(int n){fakeNow+=n;fakeUs+=(int64_t)n*1000;}
bool audioPrepareSleep(){++prepareCalls;if(reserveOk)++reservations;if(cancelAfterReserve)gTouchIrq=true;return reserveOk;}
void audioAfterWake(){++releases;assert(releases<=reservations);}
int gpio_intr_disable(gpio_num_t){irqEnabled=false;++irqMasks;return ESP_OK;}
int gpio_wakeup_enable(gpio_num_t,int type){assert(!irqEnabled);irqType=type;wakeArmed=true;return wakeResult;}
int gpio_wakeup_disable(gpio_num_t){wakeArmed=false;return ESP_OK;}
int gpio_set_intr_type(gpio_num_t,int type){irqType=type;return ESP_OK;}
int gpio_intr_enable(gpio_num_t){irqEnabled=true;++irqRestores;return ESP_OK;}
int esp_sleep_enable_timer_wakeup(uint32_t us){assert(us==TamaPower::SLEEP_POLL_US);if(cancelAfterConfig)gpio=LOW;return timerResult;}
int64_t esp_timer_get_time(){return fakeUs;}
int esp_light_sleep_start(){assert(!irqEnabled&&wakeArmed&&irqType==GPIO_INTR_LOW_LEVEL);++sleepCalls;fakeUs+=200000;fakeNow+=200;return sleepResult;}
int esp_sleep_get_wakeup_cause(){return wakeCause;}
'''
        harness += function("powerIdle")
        harness += r'''
int main(int argc,char **argv){
 assert(argc==2);std::string test=argv[1];
 if(test=="ineligible")radio=true;
 else if(test=="usb-inserted")freshUsb=true;
 else if(test=="reserve-denied")reserveOk=false;
 else if(test=="cancel")cancelAfterReserve=true;
 else if(test=="cancel-late")cancelAfterConfig=true;
 else if(test=="wake-config-fail")wakeResult=ESP_FAIL;
 else if(test=="timer-fail")timerResult=ESP_FAIL;
 else if(test=="sleep-fail")sleepResult=ESP_FAIL;
 else if(test=="gpio-wake")wakeCause=ESP_SLEEP_WAKEUP_GPIO;
 else {assert(test=="success");fakeNow=0x80000100U;} // zero retry sentinel must work beyond 2^31 ms
 powerIdle();
 assert(irqEnabled&&!wakeArmed&&irqType==GPIO_INTR_NEGEDGE&&irqMasks==irqRestores);
 if(test=="ineligible"||test=="usb-inserted"){assert(prepareCalls==0&&releases==0&&sleepCalls==0);}
 else if(test=="reserve-denied"){assert(prepareCalls==1&&reservations==0&&releases==0&&sleepCalls==0);}
 else {
  assert(reservations==1&&releases==1);
  if(test=="cancel"||test=="cancel-late")assert(sleepCalls==0&&powerSleepCount==0&&powerSleepErrors==0);
  else if(test=="timer-fail"||test=="wake-config-fail")assert(sleepCalls==0&&powerSleepErrors==1&&powerSleepCount==0);
  else if(test=="sleep-fail")assert(sleepCalls==1&&powerSleepErrors==1&&powerSleepCount==0);
  else assert(sleepCalls==1&&powerSleepCount==1&&powerSleepErrors==0&&powerSleepUs==200000&&powerSleepRetryAt==0);
  if(test=="gpio-wake")assert(gTouchIrq);
 }
}
'''
        exe = self.compile("sleep", harness)
        for case in ("ineligible", "usb-inserted", "reserve-denied", "cancel", "cancel-late", "wake-config-fail", "timer-fail", "sleep-fail", "success", "gpio-wake"):
            with self.subTest(case=case):
                self.run_case(exe, case)


if __name__ == "__main__":
    unittest.main()
