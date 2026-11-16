#!/usr/bin/env python3
"""Validate bytes, metadata, retained installers and non-erasing app-slot maps."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from package_release import ROOT, check_bytes, digest, read_json, safe_path


def require(condition, message):
    if not condition:
        raise ValueError(message)


class InstallerParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.installers = []

    def handle_starttag(self, tag, attrs):
        if tag == 'esp-web-install-button':
            self.installers.append(dict(attrs))


def validate(site, expected_commit=None):
    config = read_json(ROOT / 'tools/release_config.json')
    lock = read_json(ROOT / 'tools/baseline.lock.json')
    release = read_json(site / 'release.json')
    latest = read_json(site / 'ota-latest.json')
    require(release['version'] == latest['version'] == config['version'], 'Version mismatch')
    require(release['build'] == latest['build'] == config['build'], 'OTA build mismatch')
    require(re.fullmatch('[a-f0-9]{40}', release['source_commit']), 'Invalid source commit')
    if expected_commit:
        require(release['source_commit'] == expected_commit, 'Unexpected source commit')
        require(release['source_dirty'] is False, 'Production release contains uncommitted source changes')
    for key in ('sha256', 'size', 'source_commit', 'source_tree_sha256'):
        require(release[key] == latest[key], f'OTA/release mismatch: {key}')
    provenance = release['build_provenance']
    for key in ('sha256', 'size', 'build', 'source_tree_sha256'):
        require(provenance[key] == release[key], f'Compile provenance mismatch: {key}')
    require(provenance['firmware_version'] == release['firmware_version'], 'Compile version mismatch')
    binary = safe_path(site, release['firmware_path']).read_bytes()
    check_bytes(binary, release)
    require(24 < len(binary) <= config['app_slot_size'] and binary[0] == 0xE9, 'Invalid app image/slot size')
    require(release['firmware_version'].encode() in binary, 'Binary version marker mismatch')
    require(release['firmware_version'].startswith(config['version'] + '-ko-'), 'Firmware version mismatch')
    require(latest['url'] == config['public_base_url'] + release['firmware_path'], 'OTA URL mismatch')
    require(release['sha256'][:12] in Path(release['firmware_path']).name, 'Firmware filename/hash mismatch')
    require(release['hardware_battery_measurements_complete'] is False, 'Unexpected unverified battery performance claim')
    expected = {e['manifest']: (e['firmware_path'], config['app0_offset'], e['version']) for e in lock['releases']}
    for e in lock['releases']:
        check_bytes(safe_path(site, e['firmware_path']).read_bytes(), e)
    old = next(e for e in lock['releases'] if e['id'] == 'ota26')
    version = release['firmware_version'] + '-' + release['sha256'][:12]
    expected.update({'manifest-ota.json': (release['firmware_path'], config['app0_offset'], version),
                     'manifest-ota-app1.json': (release['firmware_path'], config['app1_offset'], version),
                     'manifest-ota-2.6-app1.json': (old['firmware_path'], config['app1_offset'], old['version'])})
    for name, (path, offset, ver) in expected.items():
        manifest = read_json(site / name)
        require(manifest.get('new_install_prompt_erase') is True, f'{name}: erase prompt must remain enabled')
        require(manifest['version'] == ver, f'{name}: version mismatch')
        require(manifest['builds'] == [{'chipFamily': config['chip_family'], 'parts': [{'path': path, 'offset': offset}]}], f'{name}: unsafe or mismatched flash map')
        if name in ('manifest-ota.json', 'manifest-ota-app1.json'):
            for key in ('sha256', 'size', 'source_commit', 'build'):
                require(manifest[key] == release[key], f'{name}: {key} mismatch')
    html = (site / 'index.html').read_text(encoding='utf-8')
    require(not re.search(r'__[A-Z_]+__', html), 'Unresolved page token')
    parser = InstallerParser()
    parser.feed(html)
    ids = [x.get('id') for x in parser.installers]
    require(len(ids) == len(set(ids)), 'Duplicate installer IDs')
    require(set(expected) == {urlsplit(x.get('manifest', '')).path for x in parser.installers}, 'Page installer links do not cover the expected manifests')
    for entry in parser.installers:
        u = urlsplit(entry['manifest'])
        require(not u.scheme and not u.netloc and u.path in expected, 'Unexpected external installer manifest')
    require(f'data-release-build="{config["build"]}"' in html, 'Page build marker mismatch')
    require(release['sha256'] in html and release['source_commit'] in html, 'Page release details mismatch')
    for line in (site / 'SHA256SUMS.txt').read_text().splitlines():
        sha, relative = line.split('  ', 1)
        require(digest(safe_path(site, relative).read_bytes()) == sha, f'Checksum list mismatch: {relative}')
    return {'version': release['version'], 'build': release['build'], 'size': len(binary),
            'sha256': release['sha256'], 'source_commit': release['source_commit'],
            'preserved_binary_count': len(lock['releases']), 'installer_count': len(expected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('site', nargs='?', type=Path, default=ROOT / 'site')
    parser.add_argument('--expected-commit')
    args = parser.parse_args()
    print(json.dumps(validate(args.site, args.expected_commit), indent=2))


if __name__ == '__main__':
    main()
