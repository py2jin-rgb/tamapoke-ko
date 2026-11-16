"""Host behavioral tests of the firmware's actual parser and battle functions.

The C++ functions are extracted from the canonical sketch, not reimplemented.
Only Arduino/hardware boundaries are stubbed. Hardware/TLS integration still
requires the real ESP32 compile and device checks.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "firmware/TamaPoke/TamaPoke.ino").read_text()


def function(name):
    import re
    match = re.search(r"(?m)^static [^\n]+\b" + name + r"\([^\n]*\)\s*\{", SOURCE)
    if not match:
        raise AssertionError(f"Missing function: {name}")
    start = match.start()
    at = SOURCE.index("{", match.start(), match.end())
    depth, quoted, escaped = 0, None, False
    while at < len(SOURCE):
        c = SOURCE[at]
        if quoted:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == quoted:
                quoted = None
        elif SOURCE.startswith("//", at):
            at = SOURCE.index("\n", at)
            continue
        elif c in "\"'":
            quoted = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if not depth:
                return SOURCE[start:at + 1]
        at += 1
    raise AssertionError(f"Unclosed function: {name}")


STRING_SHIM = r'''
#include <string>
#include <cstring>
#include <cstdint>
#include <iostream>
#include <cassert>
using std::size_t;
class String {
 public:
  std::string s;
  String()=default;
  String(const char *p):s(p){}
  String(const std::string &p):s(p){}
  size_t length()const{return s.length();}
  char operator[](size_t i)const{return s[i];}
  String &operator+=(char c){s+=c;return *this;}
  bool operator==(const char *p)const{return s==p;}
  bool operator!=(const char *p)const{return s!=p;}
  bool startsWith(const char *p)const{return s.rfind(p,0)==0;}
  bool endsWith(const char *p)const{size_t n=strlen(p);return s.size()>=n&&s.compare(s.size()-n,n,p)==0;}
  String substring(size_t p)const{return s.substr(p);}
  int indexOf(const char *p)const{auto i=s.find(p);return i==std::string::npos?-1:int(i);}
  void setCharAt(size_t i,char c){s[i]=c;}
};
'''


class WirelessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("g++"):
            raise unittest.SkipTest("g++ required for actual C++ function tests")
        cls.temp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temp.name)
        parser = STRING_SHIM + r'''
static const char *OTA_FIRMWARE_PREFIX="https://py2jin-rgb.github.io/tamapoke-ko/firmware/";
static uint32_t otaExpectedSize=0;
static String otaExpectedSha,otaUrl,otaVersion;
'''
        parser += "\n".join(function(n) for n in (
            "otaJsonSpace", "otaJsonString", "otaJsonUint", "otaAllowedUrl", "otaParseManifest"))
        parser += r'''
int main(){std::string line;while(std::getline(std::cin,line)){uint32_t b=0;bool ok=otaParseManifest(String(line),b);std::cout<<ok<<" "<<b<<" "<<otaExpectedSize<<" "<<otaExpectedSha.s<<"\n";}}
'''
        cls.parser = cls.compile("parser", parser)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def compile(cls, name, source):
        path = cls.work / (name + ".cpp")
        path.write_text(source)
        exe = cls.work / name
        subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", str(path), "-o", str(exe)], check=True, capture_output=True, text=True)
        return exe

    def valid(self):
        return {"build": 281, "size": 2048, "version": "2.8.1",
                "url": "https://py2jin-rgb.github.io/tamapoke-ko/firmware/test.bin",
                "sha256": "a1" * 32}

    def parse(self, payload):
        result = subprocess.run([str(self.parser)], input=payload + "\n", capture_output=True, text=True, check=True)
        return result.stdout.strip().split()

    def test_valid_whitespace_and_uppercase_digest(self):
        payload = self.valid()
        payload["sha256"] = payload["sha256"].upper()
        result = self.parse(json.dumps(payload))
        self.assertEqual(result, ["1", "281", "2048", "a1" * 32])

    def test_manifest_required_fields_and_strict_numbers(self):
        cases = []
        for key in self.valid():
            p = self.valid(); del p[key]; cases.append(json.dumps(p))
        for value in (0, -1, 1.5, 4294967296, "2048", None):
            p = self.valid(); p["size"] = value; cases.append(json.dumps(p))
        p = json.dumps(self.valid())
        cases.extend([p[:-1], p + "trailing", p[:-1] + ', "size": 4096}',
                      p.replace('"size": 2048', '"size": 02048')])
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.parse(payload)[0], "0")

    def test_binary_origin_and_path_are_pinned(self):
        for url in ("http://py2jin-rgb.github.io/tamapoke-ko/firmware/test.bin",
                    "https://py2jin-rgb.github.io.evil.test/tamapoke-ko/firmware/test.bin",
                    "https://py2jin-rgb.github.io/tamapoke-ko/firmware/../test.bin",
                    "https://py2jin-rgb.github.io/tamapoke-ko/firmware/%2e%2e/test.bin",
                    "https://py2jin-rgb.github.io/tamapoke-ko/firmware/test.bin?redirect=evil"):
            p = self.valid(); p["url"] = url
            with self.subTest(url=url):
                self.assertEqual(self.parse(json.dumps(p))[0], "0")

    def test_digest_format(self):
        for digest in ("", "a" * 63, "a" * 65, "x" * 64):
            p = self.valid(); p["sha256"] = digest
            self.assertEqual(self.parse(json.dumps(p))[0], "0")

    def test_battle_duplicate_packets_timeouts_and_final_grace(self):
        start = SOURCE.index("// ---------- Battle Edition v2.4:")
        end = SOURCE.index("\n", SOURCE.index("static const uint8_t battleBroadcast", start))
        globals_text = SOURCE[start:end]
        harness = STRING_SHIM + r'''
using portMUX_TYPE=int;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(x) ((void)(x))
#define portEXIT_CRITICAL(x) ((void)(x))
struct Preferences{void begin(const char*,bool){} uint16_t getUShort(const char*,int){return 0;} void putUShort(const char*,uint16_t){}};
struct esp_now_recv_info_t{};
static uint32_t fakeNow=0,lastInteract=0;
static bool gameMenuOpen=false;
static int radioStops=0,sent=0,rewards=0;
uint32_t millis(){return fakeNow;}
void esp_now_send(const uint8_t*,const uint8_t*,size_t){++sent;}
void esp_now_unregister_recv_cb(){}
void esp_now_deinit(){}
enum {WIFI_OFF,SFX_RPS_WIN,SFX_RPS_LOSE,SFX_RPS_DRAW,SFX_RPS_SELECT};
struct{void mode(int){++radioStops;}}WiFi;
struct{void minigameReward(int){++rewards;}}pet;
void sfxPlay(int){}
static void closeBattle();
'''
        harness += globals_text
        harness += "\n".join(function(n) for n in ("battleSend", "battleRecvCb", "battlePrefsInit",
            "battleRadioStop", "battleFinish", "battleBeats", "battleResolveRound", "battleAbort",
            "battlePump", "closeBattle", "battleTap"))
        harness += r'''
void reset(){
 battleOpen=battleRadioReady=battleAcceptRx=true; battleState=1; battlePeerId=2; battleSelfId=1;
 battleRound=1; battleMyHp=battlePeerHp=5; battleMyMove=battlePeerMove=-1;
 battleStartedAt=battleProgressAt=fakeNow=100; battleRevealUntil=0; battleFinishedAt=0;
 battleRxHead=battleRxCount=0; battleStatus=""; rewards=0; gameMenuOpen=false;
}
void incoming(int move,int round=1){BattlePacket p{BATTLE_MAGIC,1,3,(uint8_t)round,(int8_t)move,2,1};battleRecvCb(nullptr,(uint8_t*)&p,sizeof(p));}
int main(){
 reset(); battleMyMove=0; incoming(2); battlePump(fakeNow); assert(battlePeerHp==4);
 incoming(2); battlePump(fakeNow); assert(battlePeerHp==4); // no duplicate damage
 fakeNow+=1151; battlePump(fakeNow); assert(battleRound==2);
 incoming(2,1); battlePump(fakeNow); assert(battlePeerMove==-1); // stale round ignored
 reset(); incoming(2); battlePump(fakeNow); assert(battlePeerHp==5);
 battleTap(30,360); assert(battlePeerHp==4); // peer chose first; local choice resolves immediately
 reset(); battlePeerHp=1; battleMyMove=0; incoming(2); battlePump(fakeNow);
 assert(battleState==2&&rewards==1); incoming(2); battlePump(fakeNow); assert(rewards==1);
 fakeNow=battleFinishedAt+1800; battlePump(fakeNow); assert(!battleRadioReady&&battleOpen);
 fakeNow=battleFinishedAt+30000; battlePump(fakeNow); assert(!battleOpen&&gameMenuOpen);
 reset(); battleState=0; battlePeerId=0; fakeNow=battleStartedAt+44999; battlePump(fakeNow); assert(battleRadioReady);
 fakeNow++; battlePump(fakeNow); assert(!battleRadioReady&&battleState==2&&rewards==0);
 reset(); fakeNow=battleProgressAt+60000; battlePump(fakeNow); assert(!battleRadioReady&&battleState==2);
 reset(); battleAcceptRx=false; incoming(1); assert(battleRxCount==0);
 reset(); for(int i=0;i<8;++i)incoming(1); assert(battleRxCount==4); // bounded queue
 reset(); incoming(7); assert(battleRxCount==0); // malformed move rejected
 std::cout<<"battle checks passed\n";
}
'''
        exe = self.compile("battle", harness)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)

    def test_alarm_preserves_flash_transfer(self):
        harness = STRING_SHIM + r'''
static bool battleOpen=false,otaOpen=true,otaWriting=false,otaRestartPending=false;
static uint8_t otaState=2; static int releases=0,off=0;
enum {OTA_IDLE=0};
static void closeBattle(){battleOpen=false;}
static void otaReleaseTransfer(bool){++releases;}
static void otaWifiOff(){++off;}
static void otaSetState(uint8_t s,const String&){otaState=s;}
'''
        harness += function("closeOta") + function("radioOnAlarm")
        harness += r'''
int main(){
 otaWriting=true; radioOnAlarm(); assert(otaOpen&&releases==0&&off==0);
 closeOta(); assert(otaOpen&&releases==0&&off==0);
 otaWriting=false; otaRestartPending=true; radioOnAlarm(); assert(otaOpen&&off==0);
 otaRestartPending=false; battleOpen=true; radioOnAlarm(); assert(!otaOpen&&!battleOpen&&off==1);
}
'''
        exe = self.compile("alarm", harness)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)

    def test_verified_update_restart_waits_for_alarm_and_snooze(self):
        # Snooze is kept in RAM by the current alarm implementation. Restarting
        # immediately after snooze would lose it, even though ringing is false.
        # Exercise the real otaPump(), with inert hardware outside its restart arm.
        harness = STRING_SHIM + r'''
#include <ctime>
static bool ringing=false,snoozing=false,otaRestartPending=true,otaOpen=true,otaSetupAp=false;
static bool gameMenuOpen=false;
static uint32_t fakeNow=2000,otaRestartAt=1000,otaApSavedAt=0,otaStateSince=0;
enum {OTA_IDLE=0,OTA_AP=1,OTA_CONNECT=2,OTA_MANIFEST=3,OTA_DOWNLOAD=4,OTA_DONE=5,
      OTA_ERROR=6,OTA_TIME=7,OTA_BINARY=8,WL_CONNECTED=9};
static uint8_t otaState=OTA_DONE;
static const uint32_t OTA_AP_MS=180000,OTA_CONNECT_MS=15000,OTA_RESULT_MS=30000;
uint32_t millis(){return fakeNow;}
bool alarmRinging(){return ringing;}
bool alarmSnoozing(){return snoozing;}
struct {int restarts=0;void restart(){++restarts;}}ESP;
struct {int saves=0;bool savePending(){return true;}void flushSave(){++saves;}}pet;
struct {void handleClient(){}}otaServer;
struct {int status(){return 0;}}WiFi;
void configTime(int,int,const char*,const char*,const char*){}
static void otaWifiOff(){}
static void otaSetState(uint8_t state,const String&){otaState=state;}
static void otaFail(const String&){}
static void otaReadManifest(){}
static void otaBeginBinary(){}
static void otaDownloadChunk(uint32_t){}
static void closeOta(){}
'''
        harness += function("otaPump")
        harness += r'''
int main(){
 ringing=true;otaPump(fakeNow);assert(ESP.restarts==0&&pet.saves==0);
 ringing=false;snoozing=true;otaPump(fakeNow);assert(ESP.restarts==0&&pet.saves==0);
 ringing=true;otaPump(fakeNow);assert(ESP.restarts==0&&pet.saves==0);
 ringing=snoozing=false;otaRestartAt=fakeNow+1;otaPump(fakeNow);assert(ESP.restarts==0);
 ++fakeNow;otaPump(fakeNow);assert(ESP.restarts==1&&pet.saves==1);
 ESP.restarts=pet.saves=0;fakeNow=0xffffff00U;otaRestartAt=0x100U;
 otaPump(fakeNow);assert(ESP.restarts==0);fakeNow=0x100U;
 otaPump(fakeNow);assert(ESP.restarts==1&&pet.saves==1);
}
'''
        exe = self.compile("restart", harness)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)

    def test_download_never_activates_unverified_or_incomplete_image(self):
        harness = STRING_SHIM + r'''
static uint32_t fakeNow=100,otaLastProgress=100,otaDownloadStarted=100,otaRestartAt=0;
static const uint32_t OTA_STALL_MS=12000,OTA_TOTAL_MS=180000;
static uint32_t otaExpectedSize=4,otaReceived=0;
static String otaExpectedSha,otaMsg;
static bool otaWriting=true,otaRestartPending=false;
static int otaState=4,criticalCalls=0,wifiOff=0,aborts=0,hashError=0;
enum {OTA_DONE=5,OTA_ERROR=6};
uint32_t millis(){return fakeNow;}
void delay(int n){fakeNow+=n;}
void serviceCriticalTasks(){++criticalCalls;assert(otaWriting);}
struct Hash{}otaHash;
int mbedtls_sha256_update(Hash*,uint8_t*,size_t){return hashError;}
int mbedtls_sha256_finish(Hash*,uint8_t *out){memset(out,0,32);return hashError;}
struct StreamMock{
 uint8_t data[8]={0,1,2,3};int count=4,pos=0;
 int available(){return count-pos;}
 int read(uint8_t *out,size_t n){if(n>(size_t)available())n=available();memcpy(out,data+pos,n);pos+=n;return n;}
}streamMock;
struct HttpMock{bool connectedFlag=true;StreamMock *getStreamPtr(){return &streamMock;}bool connected(){return connectedFlag;}}otaBinHttp;
struct UpdateMock{
 int ends=0,writes=0;bool shortWrite=false;
 size_t write(uint8_t*,size_t n){++writes;return shortWrite?0:n;}
 bool end(bool){++ends;return true;}bool isFinished(){return true;}
}Update;
static void otaReleaseTransfer(bool abort){if(abort)++aborts;otaWriting=false;}
static void otaWifiOff(){assert(!otaWriting);++wifiOff;}
static void otaSetState(uint8_t state,const String &message){otaState=state;otaMsg=message;}
'''
        harness += function("otaFail") + function("otaDownloadChunk")
        harness += r'''
void reset(){
 fakeNow=otaLastProgress=otaDownloadStarted=100; otaExpectedSize=4; otaReceived=0;
 otaExpectedSha=std::string(64,'0'); otaWriting=true; otaRestartPending=false;
 criticalCalls=wifiOff=aborts=hashError=0; otaState=4;
 streamMock.count=4;streamMock.pos=0;otaBinHttp.connectedFlag=true;Update=UpdateMock{};
}
int main(){
 reset();otaDownloadChunk(fakeNow);assert(Update.ends==1&&otaRestartPending&&wifiOff==1&&aborts==0&&criticalCalls==1);
 reset();otaExpectedSha=std::string(64,'1');otaDownloadChunk(fakeNow);assert(Update.ends==0&&aborts==1&&otaMsg=="SHA256 MISMATCH");
 reset();streamMock.count=2;otaBinHttp.connectedFlag=false;otaDownloadChunk(fakeNow);assert(Update.ends==0&&aborts==1&&otaMsg=="BIN INCOMPLETE");
 reset();Update.shortWrite=true;otaDownloadChunk(fakeNow);assert(Update.ends==0&&aborts==1&&otaMsg=="UPDATE WRITE FAIL");
 reset();hashError=-1;otaDownloadChunk(fakeNow);assert(Update.ends==0&&aborts==1);
 reset();fakeNow=12101;otaDownloadChunk(fakeNow);assert(Update.writes==0&&Update.ends==0&&aborts==1&&otaMsg=="DOWNLOAD TIMEOUT");
}
'''
        exe = self.compile("download", harness)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
