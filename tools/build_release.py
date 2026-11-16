#!/usr/bin/env python3
"""Compile the canonical fifth edition once, using the pinned toolchain."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from package_release import digest, source_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arduino-cli', default='arduino-cli')
    parser.add_argument('--config-file', type=Path, help='Optional Arduino CLI YAML configuration')
    parser.add_argument('--font', type=Path, help='Explicit Nanum TTF for the Hangul generator')
    parser.add_argument('--build-dir', type=Path, default=ROOT / '.build' / 'ota')
    parser.add_argument('--skip-font', action='store_true', help='Reuse an already generated Hangul header')
    args = parser.parse_args()
    config = json.loads((ROOT / 'tools/release_config.json').read_text())
    source = ROOT / 'firmware/TamaPoke'
    text = (source / 'TamaPoke.ino').read_text(encoding='utf-8')
    version = re.search(r'^#define\s+FW_VERSION\s+"([^"]+)"', text, re.M)
    build = re.search(r'\bOTA_BUILD\s*=\s*(\d+)\s*;', text)
    if not version or not version[1].startswith(config['version'] + '-ko-'):
        raise SystemExit('Canonical FW_VERSION does not match release_config.json')
    if not build or int(build[1]) != config['build']:
        raise SystemExit('Canonical OTA_BUILD does not match release_config.json')
    cli = [args.arduino_cli]
    if args.config_file:
        cli += ['--config-file', str(args.config_file.resolve())]
    cli_version = subprocess.check_output(cli + ['version'], text=True)
    if not re.search(r'\b' + re.escape(config['arduino_cli']) + r'\b', cli_version):
        raise SystemExit(f"Use Arduino CLI {config['arduino_cli']}; got {cli_version.strip()}")
    if not args.skip_font:
        generate = [sys.executable, str(ROOT / 'combo_test/gen_hangul_font.py'), str(source / 'hangul_full16.h')]
        if args.font:
            generate += ['--font', str(args.font.resolve())]
        subprocess.run(generate, check=True)
    if not (source / 'hangul_full16.h').is_file():
        raise SystemExit('Generated Hangul font is missing')
    args.build_dir.mkdir(parents=True, exist_ok=True)
    source_before, source_files = source_fingerprint(source)
    subprocess.run(cli + ['compile', '--fqbn', config['fqbn'],
                    '--build-path', str(args.build_dir.resolve()), str(source)], check=True)
    binary = args.build_dir / 'TamaPoke.ino.bin'
    if not binary.is_file() or not 0 < binary.stat().st_size <= config['app_slot_size']:
        raise SystemExit('Compiled firmware missing or larger than the 3 MiB OTA slot')
    source_after, _ = source_fingerprint(source)
    if source_before != source_after:
        raise SystemExit('Canonical source changed while compilation was running; rebuild the completed source')
    candidates = [Path('/usr/share/fonts/truetype/nanum') / name for name in
                  ('NanumBarunGothicBold.ttf', 'NanumGothicBold.ttf', 'NanumGothic.ttf')]
    font = args.font if args.font else next((p for p in candidates if p.is_file()), None)
    font_info = {'generated_this_build': not args.skip_font,
                 'header_sha256': digest((source / 'hangul_full16.h').read_bytes())}
    if font and not args.skip_font:
        font_info.update({'file_name': font.name, 'sha256': digest(font.read_bytes())})
    provenance = {'firmware_version': version[1], 'build': int(build[1]),
                  'size': binary.stat().st_size, 'sha256': digest(binary.read_bytes()),
                  'arduino_cli_output': cli_version.strip(), 'fqbn': config['fqbn'],
                  'source_tree_sha256': source_after, 'source_files': source_files, 'hangul_font': font_info}
    (args.build_dir / 'build-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    print('Hangul font provenance:', json.dumps(font_info))
    print(f'Compiled {version[1]} / build {build[1]}: {binary.stat().st_size} bytes')


if __name__ == '__main__':
    main()
