from pathlib import Path
import hashlib, json, shutil, subprocess

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

subprocess.run(['python3','combo_test/ota_v25.py'],check=True)

src=Path('build_ota/TamaPoke.ino.bin')
if not src.is_file(): raise SystemExit('OTA pipeline binary missing')
data=src.read_bytes()
sha=hashlib.sha256(data).hexdigest(); short=sha[:12]
name=f'tamapoke-ko-cheonjiin-ota25-{short}.bin'
site=Path('site'); fw=site/'firmware'; fw.mkdir(parents=True,exist_ok=True)
shutil.copy2(src,fw/name)

manifest={
  'name':'TamaPoke KO Cheonjiin OTA 2.5',
  'version':f'2.5-ko-combo-ota-{short}',
  'new_install_prompt_erase':True,
  'builds':[{'chipFamily':'ESP32-S3','parts':[{'path':f'firmware/{name}','offset':65536}]}]
}
(site/'manifest-ota.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
latest={
  'build':250,
  'version':'2.5',
  'url':f'https://py2jin-rgb.github.io/tamapoke-ko/firmware/{name}',
  'sha256':sha
}
(site/'ota-latest.json').write_text(json.dumps(latest,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
(site/'ota-info.txt').write_text(
    f'OTA 2.5 SHA256: {sha}\nFile: {name}\nBuild: 250\nManifest: ota-latest.json\n',encoding='utf-8')

html=(site/'index.html').read_text(encoding='utf-8')
for must in ('⑤ 천지인 Battle · Battery + Wi-Fi 무선 업데이트','manifest-ota.json?v=ota25','TamaPoke-Update'):
    if must not in html: raise SystemExit('OTA installer invariant missing: '+must)
print('OTA 2.5 publish complete:',name,sha)
