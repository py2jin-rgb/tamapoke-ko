#!/usr/bin/env python3
"""Package the canonical firmware and checksum-locked previous releases."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, data):
    # The older 2.6 OTA parser requires compact JSON strings without spaces.
    Path(path).write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')


def safe_path(root, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError(f'Unsafe release path: {relative}')
    target = Path(root).joinpath(*p.parts)
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError(f'Release path escapes destination: {relative}')
    return target


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check_bytes(data, entry):
    if len(data) != entry['size']:
        raise ValueError(f"Size mismatch: {entry['firmware_path']}")
    if digest(data) != entry['sha256']:
        raise ValueError(f"SHA256 mismatch: {entry['firmware_path']}")
    return data


def fetch_baseline(entry, cache):
    target = safe_path(cache, entry['firmware_path'])
    if target.is_file():
        return target, check_bytes(target.read_bytes(), entry)
    # Never fall back to a different firmware or rebuild a legacy version silently.
    req = urllib.request.Request(entry['url'], headers={'User-Agent': 'TamaPoke-Release-Verify/2.8'})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            data = response.read(entry['size'] + 1)
    except Exception as exc:
        raise RuntimeError(f"Locked baseline unavailable: {entry['url']}. Restore the exact verified bytes; no substitute is allowed.") from exc
    check_bytes(data, entry)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.download')
    temp.write_bytes(data)
    temp.replace(target)
    return target, data


def install_manifest(name, version, path, offset, metadata=None):
    result = {'name': name, 'version': version, 'new_install_prompt_erase': True,
              'builds': [{'chipFamily': 'ESP32-S3', 'parts': [{'path': path, 'offset': offset}]}]}
    if metadata:
        result.update(metadata)
    return result


def install_dual_slot_manifest(name, version, path, app0_offset, app1_offset, metadata=None):
    """Write the SAME verified app image into both existing OTA app slots.
    
    No bootloader, partition table, NVS, otadata, or filesystem parts are included.
    This is only for the known 16 MiB app3M_fat9M_16MB layout.
    """
    if not (0 < app0_offset < app1_offset):
        raise ValueError('Invalid OTA app partition offsets')
    result = install_manifest(name, version, path, app0_offset, metadata)
    result['builds'][0]['parts'].append({'path': path, 'offset': app1_offset})
    return result


def source_fingerprint(source):
    files = sorted(p for p in Path(source).iterdir() if p.is_file() and p.suffix in ('.ino', '.cpp', '.c', '.h', '.hpp', '.inc'))
    if not files:
        raise ValueError('Canonical source directory is empty')
    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode('utf-8') + b'\0' + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest(), [{'path': p.name, 'sha256': digest(p.read_bytes())} for p in files]


def package(binary, output, cache, source, commit=None):
    config = read_json(ROOT / 'tools/release_config.json')
    lock = read_json(ROOT / 'tools/baseline.lock.json')
    text = (source / 'TamaPoke.ino').read_text(encoding='utf-8')
    match = re.search(r'^#define\s+FW_VERSION\s+"([^"]+)"', text, re.M)
    build = re.search(r'\bOTA_BUILD\s*=\s*(\d+)\s*;', text)
    if not match or not match[1].startswith(config['version'] + '-ko-') or not build or int(build[1]) != config['build']:
        raise ValueError('Canonical version/build does not match release configuration')
    fw_version = match[1]
    data = binary.read_bytes()
    if not 24 < len(data) <= config['app_slot_size'] or data[0] != 0xE9:
        raise ValueError('Firmware is not a size-compatible ESP application image')
    if config['app1_offset'] - config['app0_offset'] != config['app_slot_size']:
        raise ValueError('Dual-slot USB requires the exact configured 3 MiB OTA slot layout')
    if fw_version.encode() not in data:
        raise ValueError('Compiled binary does not contain the expected firmware version; rebuild it')
    sha = digest(data)
    relative = f"firmware/tamapoke-ko-system-battery{config['version'].replace('.', '')}-{sha[:12]}.bin"
    commit = commit or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('Source commit must be the complete 40-character Git SHA')
    tree_sha, files = source_fingerprint(source)
    provenance_file = binary.parent / 'build-provenance.json'
    if not provenance_file.is_file():
        raise ValueError('Build provenance is missing; compile with tools/build_release.py first')
    provenance = read_json(provenance_file)
    if provenance.get('source_tree_sha256') != tree_sha or provenance.get('sha256') != sha or provenance.get('size') != len(data):
        raise ValueError('Source or firmware differs from the completed build provenance; rebuild it')
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT, text=True).strip())
    # Download and verify everything before replacing a previously prepared site.
    with ThreadPoolExecutor(max_workers=4) as pool:
        baselines = list(pool.map(lambda e: fetch_baseline(e, cache), lock['releases']))
    if output.is_symlink():
        raise ValueError('Refusing a symlink output directory')
    output = output.resolve()
    if output in (ROOT.resolve(), ROOT.parent.resolve(), Path('/')) or output == source.resolve():
        raise ValueError('Refusing to replace a source/workspace directory')
    marker = output / '.tamapoke-release-output'
    if output.exists() and any(output.iterdir()) and not marker.is_file():
        raise ValueError('Output directory is not empty and is not a previously generated release')
    output.mkdir(parents=True, exist_ok=True)
    # Only remove previous generated files under the dedicated output directory.
    for child in output.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    (output / 'firmware').mkdir()
    marker.write_text('Generated by tools/package_release.py\n', encoding='utf-8')
    legacy = []
    for entry, (_, old_data) in zip(lock['releases'], baselines):
        safe_path(output, entry['firmware_path']).write_bytes(old_data)
        write_json(output / entry['manifest'], install_manifest(entry['name'], entry['version'], entry['firmware_path'], config['app0_offset']))
        legacy.append(entry)
        if entry['id'] == 'ota26':
            write_json(output / 'manifest-ota-2.6-app1.json', install_manifest(entry['name'] + ' / app1', entry['version'], entry['firmware_path'], config['app1_offset']))
    safe_path(output, relative).write_bytes(data)
    meta = {'source_commit': commit, 'sha256': sha, 'size': len(data), 'build': config['build']}
    version = fw_version + '-' + sha[:12]
    write_json(output / 'manifest-ota.json', install_manifest(config['name'], version, relative, config['app0_offset'], meta))
    write_json(output / 'manifest-ota-app1.json', install_manifest(config['name'] + ' / app1', version, relative, config['app1_offset'], meta))
    write_json(output / 'manifest-ota-usb.json',
               install_dual_slot_manifest(config['name'] + ' / USB both OTA slots', version, relative,
                                          config['app0_offset'], config['app1_offset'], meta))
    latest = {'build': config['build'], 'version': config['version'], 'url': config['public_base_url'] + relative,
              'sha256': sha, 'size': len(data), 'source_commit': commit, 'source_tree_sha256': tree_sha}
    write_json(output / 'ota-latest.json', latest)
    release = {'schema_version': 1, **latest, 'firmware_version': fw_version, 'firmware_path': relative,
               'source_dirty': dirty, 'source_files': files, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
               'build_provenance': provenance,
               'hardware_battery_measurements_complete': config['hardware_battery_measurements_complete'],
               'toolchain': {k: config[k] for k in ('arduino_cli', 'esp32_core', 'fqbn', 'libraries')},
               'baseline_source_commit': lock['source_commit'], 'previous_releases': legacy}
    write_json(output / 'release.json', release)
    html = (ROOT / 'docs/index.html').read_text(encoding='utf-8')
    substitutions = {'__RELEASE_VERSION__': config['version'], '__RELEASE_BUILD__': str(config['build']),
                     '__RELEASE_SHA256__': sha, '__RELEASE_SIZE__': str(len(data)), '__SOURCE_COMMIT__': commit,
                     '__RELEASE_BINARY__': relative}
    for token, value in substitutions.items():
        html = html.replace(token, value)
    (output / 'index.html').write_text(html, encoding='utf-8')
    (output / '.nojekyll').touch()
    info = [f"⑤ {fw_version} / build {config['build']}", f'Source commit: {commit}', f'Source tree SHA256: {tree_sha}',
            f'Firmware: {relative}', f'Size: {len(data)}', f'SHA256: {sha}', 'Hardware battery duration: not measured',
            'USB simple: one click writes the identical app image to BOTH app0 0x10000 and app1 0x310000; NEVER erase.',
            'USB advanced: choose a confirmed running app slot only. Wi-Fi OTA remains available.', '', 'Preserved releases:']
    info += [f"{e['name']}: {e['size']} bytes / {e['sha256']} / {e['firmware_path']}" for e in legacy]
    (output / 'build-info.txt').write_text('\n'.join(info) + '\n', encoding='utf-8')
    (output / 'ota-info.txt').write_text('\n'.join(info[:7]) + '\n', encoding='utf-8')
    checksums = [f'{digest(p.read_bytes())}  {p.relative_to(output).as_posix()}'
                 for p in sorted(output.rglob('*'))
                 if p.is_file() and p.name != 'SHA256SUMS.txt'
                 and not any(part.startswith('.') for part in p.relative_to(output).parts)]
    (output / 'SHA256SUMS.txt').write_text('\n'.join(checksums) + '\n', encoding='utf-8')
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / '.build/ota/TamaPoke.ino.bin')
    parser.add_argument('--output', type=Path, default=ROOT / 'site')
    parser.add_argument('--cache', type=Path, default=ROOT / '.build/baseline-cache')
    parser.add_argument('--source', type=Path, default=ROOT / 'firmware/TamaPoke')
    parser.add_argument('--source-commit')
    args = parser.parse_args()
    release = package(args.binary, args.output, args.cache, args.source, args.source_commit)
    print(json.dumps({k: release[k] for k in ('version', 'build', 'size', 'sha256', 'source_commit', 'source_dirty')}, indent=2))


if __name__ == '__main__':
    main()
