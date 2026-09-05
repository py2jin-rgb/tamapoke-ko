from pathlib import Path
import hashlib, json, shutil, subprocess, re

# Arduino's generated prototypes cover functions but not globals. The OTA modal
# flag must exist before onTap()/render(), while the rest of the OTA state can
# stay with the implementation block later in the sketch.
otap=Path('combo_test/ota_v25.py')
t=otap.read_text(encoding='utf-8')
t=t.replace("s=s.replace(marker, marker+incs, 1)",
            "s=s.replace(marker, marker+incs+'static bool otaOpen=false;\\n', 1)",1)
t=t.replace('static bool otaOpen=false, otaSetupAp=false;',
            'static bool otaSetupAp=false;',1)
if "marker+incs+'static bool otaOpen=false;\\n'" not in t:
    raise SystemExit('OTA early-state patch failed')
otap.write_text(t,encoding='utf-8')

# Build the existing ⑤ OTA base, then add the ⑤-only persistent volume layer.
subprocess.run(['python3','combo_test/ota_v25.py'],check=True)
subprocess.run(['python3','combo_test/volume_ota_v26.py'],check=True)

src=Path('build_ota/TamaPoke.ino.bin')
if not src.is_file(): raise SystemExit('OTA volume pipeline binary missing')
data=src.read_bytes()
sha=hashlib.sha256(data).hexdigest(); short=sha[:12]
name=f'tamapoke-ko-cheonjiin-ota26-volume-{short}.bin'
site=Path('site'); fw=site/'firmware'; fw.mkdir(parents=True,exist_ok=True)
shutil.copy2(src,fw/name)

manifest={
  'name':'TamaPoke KO Cheonjiin OTA Volume 2.6',
  'version':f'2.6-ko-combo-ota-volume-{short}',
  'new_install_prompt_erase':True,
  'builds':[{'chipFamily':'ESP32-S3','parts':[{'path':f'firmware/{name}','offset':65536}]}]
}
(site/'manifest-ota.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
latest={
  'build':260,
  'version':'2.6',
  'url':f'https://py2jin-rgb.github.io/tamapoke-ko/firmware/{name}',
  'sha256':sha
}
(site/'ota-latest.json').write_text(json.dumps(latest,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
(site/'ota-info.txt').write_text(
    f'OTA Volume 2.6 SHA256: {sha}\nFile: {name}\nBuild: 260\nVolume: 0/25/50/75/100 percent, NVS persisted, PCM amplitude scaled\nManifest: ota-latest.json\n',encoding='utf-8')

# ota_v25 generates the new ⑤ card. If an older ⑤ card is already present from
# an earlier page patch, delete the older one(s) and keep only the last/newest ⑤.
page=site/'index.html'
html=page.read_text(encoding='utf-8')
card_re=re.compile(r'\n<div class="card(?: [^"]*)?">(?:(?!\n<div class="card(?: |\")).)*?<h2>⑤[^<]*</h2>(?:(?!\n<div class="card(?: |\")).)*?(?=\n<div class="card(?: |\")|\n<footer>)',re.S)
matches=list(card_re.finditer(html))
if len(matches)>1:
    keep=matches[-1].group(0)
    html=card_re.sub('',html)
    anchor='<div class="card"><h2>설치 순서</h2>'
    if anchor not in html: raise SystemExit('installer 5 cleanup anchor missing')
    html=html.replace(anchor,keep+'\n'+anchor,1)

# Upgrade the single remaining ⑤ card to 2.6 and advertise the real PCM volume
# control while leaving ①~④ untouched.
html=html.replace('📶 NEW · OTA 2.5','🔊 NEW · OTA + VOLUME 2.6',1)
html=html.replace('manifest-ota.json?v=ota25','manifest-ota.json?v=ota26volume',1)
html=html.replace('📶 천지인 OTA 2.5 설치','🔊 천지인 OTA + Volume 2.6 설치',1)
needle='<p class="ok">✓ OTA 전용 슬롯에 기록 후 정상 완료시에만 재부팅</p>'
extra=needle+'<p class="ok">✓ 소리 0 / 25 / 50 / 75 / 100% 조절 · 재부팅 후에도 저장</p>'
if needle not in html: raise SystemExit('OTA volume page feature anchor missing')
html=html.replace(needle,extra,1)
if html.count('<h2>⑤') != 1:
    raise SystemExit(f'installer 5 card count must be 1, got {html.count("<h2>⑤")}')
page.write_text(html,encoding='utf-8')

for must in ('⑤ 천지인 Battle · Battery + Wi-Fi 무선 업데이트','manifest-ota.json?v=ota26volume','OTA + VOLUME 2.6','0 / 25 / 50 / 75 / 100%'):
    if must not in html: raise SystemExit('OTA volume installer invariant missing: '+must)
print('OTA Volume 2.6 publish complete; single installer ⑤ kept:',name,sha)
