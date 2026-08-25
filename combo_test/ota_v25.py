from pathlib import Path
import re, shutil, subprocess

SRC=Path('source_battle/TamaPoke')
ROOT=Path('source_ota/TamaPoke')
if ROOT.parent.exists(): shutil.rmtree(ROOT.parent)
ROOT.parent.mkdir(parents=True)
shutil.copytree(SRC, ROOT)
ino=ROOT/'TamaPoke.ino'
s=ino.read_text(encoding='utf-8')

# ⑤ forks the completed ④ Battle 2.4 source. ③/④ remain untouched installers.
s,n=re.subn(r'#define FW_VERSION "2\.4-ko-combo-battle"', '#define FW_VERSION "2.5-ko-combo-ota"', s, count=1)
if n!=1: raise SystemExit('OTA v2.5 firmware version marker missing')

# Battle already includes WiFi.h. Add only OTA/web dependencies.
incs='''#include <HTTPClient.h>\n#include <WiFiClientSecure.h>\n#include <WebServer.h>\n#include <Update.h>\n'''
marker='#include <esp_wifi.h>\n'
if marker not in s: raise SystemExit('OTA include anchor missing')
s=s.replace(marker, marker+incs, 1)

state=r'''
// ---------- Wi-Fi OTA Edition v2.5 ----------
static const uint16_t OTA_BUILD=250;
static const char *OTA_MANIFEST_URL="https://py2jin-rgb.github.io/tamapoke-ko/ota-latest.json";
static bool otaOpen=false, otaSetupAp=false;
static uint8_t otaState=0; // 0 idle, 1 AP setup, 2 connecting, 3 checking, 4 downloading, 5 done, 6 error
static String otaMsg="";
static String otaSsid="", otaPass="";
static Preferences otaPrefs;
static bool otaPrefsReady=false;
static WebServer otaServer(80);

static void otaPrefsInit(){
  if(otaPrefsReady) return;
  otaPrefsReady=true;
  otaPrefs.begin("tpk-ota",false);
  otaSsid=otaPrefs.getString("ssid","");
  otaPass=otaPrefs.getString("pass","");
}

static void otaWifiOff(){
  if(otaSetupAp){ otaServer.stop(); otaSetupAp=false; }
  WiFi.disconnect(true,true);
  WiFi.mode(WIFI_OFF);
  setCpuFrequencyMhz(80);
}

static String otaHtml(){
  return String("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>TamaPoke Wi-Fi</title><style>body{font-family:sans-serif;background:#111;color:#fff;max-width:520px;margin:30px auto;padding:20px}input,button{box-sizing:border-box;width:100%;padding:14px;margin:8px 0;border-radius:10px;border:0;font-size:16px}button{background:#ffd36a;font-weight:800}</style></head><body><h2>TamaPoke Wi-Fi 설정</h2><p>집 Wi-Fi 정보를 저장합니다. 저장 후 TamaPoke 화면에서 업데이트 확인을 눌러주세요.</p><form method='POST' action='/save'><input name='ssid' placeholder='Wi-Fi 이름(SSID)' required><input name='pass' type='password' placeholder='비밀번호'><button type='submit'>저장</button></form></body></html>");
}

static void otaStartSetupAp(){
  otaPrefsInit();
  otaWifiOff();
  setCpuFrequencyMhz(240);
  WiFi.mode(WIFI_AP);
  if(!WiFi.softAP("TamaPoke-Update")){ otaState=6; otaMsg="AP START ERROR"; return; }
  otaServer.on("/",HTTP_GET,[]{ otaServer.send(200,"text/html; charset=utf-8",otaHtml()); });
  otaServer.on("/save",HTTP_POST,[]{
    String ss=otaServer.arg("ssid"), pw=otaServer.arg("pass");
    ss.trim();
    if(ss.length()<1){ otaServer.send(400,"text/plain","SSID required"); return; }
    otaSsid=ss; otaPass=pw;
    otaPrefs.putString("ssid",otaSsid); otaPrefs.putString("pass",otaPass);
    otaServer.send(200,"text/html; charset=utf-8","<meta charset='utf-8'><h2>저장 완료</h2><p>TamaPoke로 돌아가 업데이트 확인을 눌러주세요.</p>");
    otaMsg="WI-FI SAVED";
  });
  otaServer.begin();
  otaSetupAp=true; otaState=1; otaMsg="TamaPoke-Update / 192.168.4.1";
}

static bool otaConnectSaved(){
  otaPrefsInit();
  if(otaSsid.length()<1){ otaStartSetupAp(); return false; }
  if(otaSetupAp){ otaServer.stop(); otaSetupAp=false; }
  setCpuFrequencyMhz(240);
  WiFi.mode(WIFI_STA);
  WiFi.begin(otaSsid.c_str(),otaPass.c_str());
  otaState=2; otaMsg="CONNECTING...";
  uint32_t st=millis();
  while(WiFi.status()!=WL_CONNECTED && millis()-st<15000UL){ delay(100); }
  if(WiFi.status()!=WL_CONNECTED){ otaState=6; otaMsg="WI-FI CONNECT FAIL"; otaWifiOff(); return false; }
  return true;
}

static String otaJsonString(const String &j,const char *key){
  String pat=String("\"")+key+"\":\""; int p=j.indexOf(pat); if(p<0)return ""; p+=pat.length(); int e=j.indexOf('"',p); if(e<0)return ""; return j.substring(p,e);
}
static int otaJsonInt(const String &j,const char *key){
  String pat=String("\"")+key+"\":"; int p=j.indexOf(pat); if(p<0)return -1; p+=pat.length(); while(p<(int)j.length() && j[p]==' ')p++; return j.substring(p).toInt();
}

static void otaDoUpdate(){
  if(!otaConnectSaved()) return;
  otaState=3; otaMsg="CHECKING UPDATE...";
  WiFiClientSecure client; client.setInsecure();
  HTTPClient http;
  if(!http.begin(client,OTA_MANIFEST_URL)){ otaState=6; otaMsg="MANIFEST OPEN FAIL"; otaWifiOff(); return; }
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
  int code=http.GET();
  if(code!=HTTP_CODE_OK){ otaState=6; otaMsg=String("MANIFEST HTTP ")+code; http.end(); otaWifiOff(); return; }
  String json=http.getString(); http.end();
  int build=otaJsonInt(json,"build"); String ver=otaJsonString(json,"version"); String url=otaJsonString(json,"url");
  if(build<0 || url.length()<8){ otaState=6; otaMsg="BAD MANIFEST"; otaWifiOff(); return; }
  if(build<=OTA_BUILD){ otaState=5; otaMsg=String("LATEST ")+ver; otaWifiOff(); return; }

  otaState=4; otaMsg=String("DOWNLOADING ")+ver;
  WiFiClientSecure binClient; binClient.setInsecure();
  HTTPClient bin;
  if(!bin.begin(binClient,url)){ otaState=6; otaMsg="BIN OPEN FAIL"; otaWifiOff(); return; }
  bin.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
  code=bin.GET();
  if(code!=HTTP_CODE_OK){ otaState=6; otaMsg=String("BIN HTTP ")+code; bin.end(); otaWifiOff(); return; }
  int len=bin.getSize();
  if(!Update.begin(len>0?(size_t)len:UPDATE_SIZE_UNKNOWN)){ otaState=6; otaMsg="OTA SLOT ERROR"; bin.end(); otaWifiOff(); return; }
  size_t wrote=Update.writeStream(*bin.getStreamPtr());
  bool ok=Update.end() && Update.isFinished() && (len<=0 || wrote==(size_t)len);
  bin.end();
  if(!ok){ Update.abort(); otaState=6; otaMsg="UPDATE WRITE FAIL"; otaWifiOff(); return; }
  otaState=5; otaMsg="UPDATE OK - RESTART";
  delay(900); ESP.restart();
}

static void startOta(){
  if(battleOpen) closeBattle();
  otaPrefsInit(); otaOpen=true; gameMenuOpen=false; otaState=0;
  otaMsg=otaSsid.length()?String("SAVED: ")+otaSsid:String("WI-FI SETUP REQUIRED");
  lastInteract=millis(); sfxPlay(SFX_GAME_OPEN);
}
static void closeOta(){ otaWifiOff(); otaOpen=false; otaState=0; otaMsg=""; lastInteract=millis(); }
static void otaPump(){ if(otaSetupAp) otaServer.handleClient(); if(otaOpen) lastInteract=millis(); }

static void otaTap(int16_t x,int16_t y){
  lastInteract=millis();
  if(y<70){ closeOta(); gameMenuOpen=true; return; }
  if(otaState==2 || otaState==3 || otaState==4) return;
  if(y>=278 && y<=342){ otaStartSetupAp(); return; }
  if(y>=354 && y<=420){ otaDoUpdate(); return; }
}

static void renderOta(){
  otaPump();
  gfx->fillScreen(RGB565_BLACK); gfx->fillCircle(CX,CY,231,C565(0xf0,0xf5,0xf8));
  uiPrintCenter(koOr("Wi-Fi 무선 업데이트","WI-FI UPDATE"),36,UI_INK,2);
  uiPrintCenter(koOr("위쪽 터치: 나가기","TOP: EXIT"),62,UI_TRACK,1);
  gfx->fillCircle(CX,150,52,C565(0x68,0xa8,0xe8));
  gfx->drawCircle(CX,150,34,UI_WHITE); gfx->drawCircle(CX,150,19,UI_WHITE); gfx->fillCircle(CX,150,5,UI_WHITE);
  char vb[40]; snprintf(vb,sizeof(vb),"OTA BUILD %u",OTA_BUILD); uiPrintCenter(vb,220,UI_TRACK,1);
  if(otaState==1){ uiPrintCenter(koOr("휴대폰 Wi-Fi에서 TamaPoke-Update 연결","CONNECT PHONE TO TamaPoke-Update"),244,UI_INK,1); uiPrintCenter("192.168.4.1",262,UI_TRACK,1); }
  else uiPrintCenter(otaMsg.c_str(),250,otaState==6?UI_BAR_WARN:UI_INK,1);
  gfx->fillRoundRect(68,278,330,64,16,C565(0x7f,0xc7,0xa0));
  gfx->drawRoundRect(68,278,330,64,16,C565(0x38,0x75,0x55));
  uiPrintCenter(koOr("Wi-Fi 설정 / 다시 설정","WI-FI SETUP"),299,UI_INK,2);
  gfx->fillRoundRect(68,354,330,66,16,C565(0xff,0xd0,0x66));
  gfx->drawRoundRect(68,354,330,66,16,C565(0x9c,0x70,0x22));
  uiPrintCenter(koOr("업데이트 확인","CHECK UPDATE"),376,UI_INK,2);
  gfx->flush();
}

'''
insert='// ---------- minijuego: toques con la pokeball ----------'
if insert not in s: raise SystemExit('OTA function insertion marker missing')
s=s.replace(insert,state+insert,1)

# Split the polished bottom hub button into Arcade/Battle and Wi-Fi Update.
old=r'''  gfx->fillRoundRect(68,370,330,44,13,C565(0x67,0x54,0xc5));
  gfx->drawRoundRect(68,370,330,44,13,UI_WHITE);
  comboFinalTextIn(koOr("아케이드 + 통신 배틀","ARCADE + BATTLE"),68,383,330,UI_WHITE,2);
  gfx->flush();'''
new=r'''  gfx->fillRoundRect(68,370,158,44,13,C565(0x67,0x54,0xc5));
  gfx->drawRoundRect(68,370,158,44,13,UI_WHITE);
  comboFinalTextIn(koOr("아케이드/배틀","ARCADE"),68,383,158,UI_WHITE,1);
  gfx->fillRoundRect(238,370,160,44,13,C565(0x47,0x9d,0x76));
  gfx->drawRoundRect(238,370,160,44,13,UI_WHITE);
  comboFinalTextIn(koOr("Wi-Fi 업데이트","WI-FI UPDATE"),238,383,160,UI_WHITE,1);
  gfx->flush();'''
if old not in s: raise SystemExit('OTA polished hub render anchor missing')
s=s.replace(old,new,1)

oldtap='if (x >= 68 && x <= 398 && y >= 370 && y <= 418) { gameMenuOpen=false; arcMenuOpen=true; sfxPlay(SFX_GAME_OPEN); return; }'
newtap='if (y >= 370 && y <= 418 && x >= 68 && x <= 226) { gameMenuOpen=false; arcMenuOpen=true; sfxPlay(SFX_GAME_OPEN); return; }\n  if (y >= 370 && y <= 418 && x >= 238 && x <= 398) { gameMenuOpen=false; startOta(); return; }'
if oldtap not in s: raise SystemExit('OTA polished hub touch anchor missing')
s=s.replace(oldtap,newtap,1)

# Modal routing comes before Battle and other game handlers.
rt='if (battleOpen) { battleTap(x, y); return; }'
if rt not in s: raise SystemExit('OTA battle touch route anchor missing')
s=s.replace(rt,'if (otaOpen) { otaTap(x, y); return; }\n  '+rt,1)
rr='if (battleOpen) { renderBattle(); return; }'
if rr not in s: raise SystemExit('OTA battle render route anchor missing')
s=s.replace(rr,'if (otaOpen) { renderOta(); return; }\n  '+rr,1)

# Ensure PWR/modal and standby guards understand OTA where their final patterns exist.
s=s.replace('battleOpen || galleryOpen','battleOpen || otaOpen || galleryOpen')
s=s.replace('battleOpen || kbOpen','battleOpen || otaOpen || kbOpen')
s=s.replace('rpsOpen || battleOpen || galleryOpen','rpsOpen || battleOpen || otaOpen || galleryOpen')
s=s.replace('rpsOpen || battleOpen || kbOpen','rpsOpen || battleOpen || otaOpen || kbOpen')

for must in ('2.5-ko-combo-ota','OTA_BUILD=250','OTA_MANIFEST_URL','Update.writeStream','TamaPoke-Update','startOta()','renderOta()','Wi-Fi 업데이트'):
    if must not in s: raise SystemExit('OTA invariant missing: '+must)
ino.write_text(s,encoding='utf-8')

fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'
build=Path('build_ota')
if build.exists(): shutil.rmtree(build)
build.mkdir()
subprocess.run(['arduino-cli','compile','--fqbn',fqbn,'--build-path',str(build),str(ROOT)],check=True)
if not (build/'TamaPoke.ino.bin').is_file(): raise SystemExit('OTA v2.5 binary missing')

# ⑤ installer card beneath ④.
page=Path('site/index.html'); html=page.read_text(encoding='utf-8')
style='.otacard{border-color:#478f70;background:#15251f}.otatag{display:inline-block;background:#173c30;color:#a8f0cf;border:1px solid #478f70;border-radius:999px;padding:4px 10px;font-size:12px;font-weight:800}.otawarn{background:#193127;border:1px solid #478f70;border-radius:12px;padding:14px;color:#c8f5df}.otainstall button{background:#8de0b8;color:#10241b}'
html=html.replace('</style>',style+'</style>',1)
card='''\n<div class="card otacard">\n<span class="otatag">📶 NEW · OTA 2.5</span>\n<h2>⑤ 천지인 Battle · Battery + Wi-Fi 무선 업데이트</h2>\n<p>④ Battle 2.4의 통신 배틀과 ③ Battery 기능을 유지하면서, <b>휴대폰으로 Wi-Fi를 한 번 등록한 뒤 기기에서 새 펌웨어를 무선 업데이트</b>할 수 있는 버전입니다.</p>\n<p class="ok">✓ 기존 포켓몬/배틀 저장 데이터와 별도 Wi-Fi 설정 저장</p><p class="ok">✓ 놀이 선택 → Wi-Fi 업데이트 → 설정/업데이트 확인</p><p class="ok">✓ 업데이트할 때만 Wi-Fi ON · 종료 후 OFF</p><p class="ok">✓ OTA 전용 슬롯에 기록 후 정상 완료시에만 재부팅</p>\n<div class="otawarn"><b>최초 1회:</b> 기기에서 Wi-Fi 설정 → 휴대폰을 <b>TamaPoke-Update</b>에 연결 → 브라우저에서 <b>192.168.4.1</b> → 집 Wi-Fi 저장. 이후 기기의 <b>업데이트 확인</b>을 누릅니다. 초기 설치 시 Erase/초기화는 선택하지 마세요.</div>\n<div class="install otainstall"><esp-web-install-button id="ota-installer" manifest="manifest-ota.json?v=ota25"><button slot="activate">📶 천지인 OTA 2.5 설치</button><span slot="unsupported">PC용 Chrome 또는 Edge가 필요합니다.</span><span slot="not-allowed">HTTPS 페이지에서 실행하세요.</span></esp-web-install-button></div>\n</div>\n'''
anchor='<div class="card"><h2>설치 순서</h2>'
if anchor not in html: raise SystemExit('OTA page install anchor missing')
html=html.replace(anchor,card+anchor,1)
html=html.replace('원하는 ①/②/③/④ 설치 버튼 선택','원하는 ①/②/③/④/⑤ 설치 버튼 선택',1)
page.write_text(html,encoding='utf-8')
print('v2.5 Wi-Fi OTA Edition compiled and installer card generated')
