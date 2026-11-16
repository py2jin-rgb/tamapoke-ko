#!/usr/bin/env python3
"""Read back the public Pages release and verify every published checksum."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import tempfile
import urllib.request

from package_release import ROOT, digest, read_json, safe_path
from validate_release import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-commit', required=True)
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}', args.expected_commit):
        raise SystemExit('Pass the full commit SHA deployed to main')
    base = read_json(ROOT / 'tools/release_config.json')['public_base_url']

    def get(relative, max_bytes=20_000_000):
        request = urllib.request.Request(base + relative, headers={'Cache-Control': 'no-cache', 'User-Agent': 'TamaPoke-Published-Verify/2.8'})
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(f'Published file unexpectedly large: {relative}')
        return data

    sums = get('SHA256SUMS.txt', 100_000)
    rows = []
    with tempfile.TemporaryDirectory(prefix='tamapoke-published-') as d:
        site = Path(d)
        for line in sums.decode('utf-8').splitlines():
            sha, name = line.split('  ', 1)
            if not re.fullmatch('[a-f0-9]{64}', sha):
                raise ValueError('Invalid published checksum list')
            safe_path(site, name)
            rows.append((sha, name))
        if not rows or len(rows) > 60 or len({n for _, n in rows}) != len(rows):
            raise ValueError('Unexpected or duplicate published files')

        def fetch(row):
            expected, name = row
            data = get(name)
            if digest(data) != expected:
                raise ValueError(f'Published SHA256 mismatch: {name}')
            target = safe_path(site, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(fetch, rows))
        (site / 'SHA256SUMS.txt').write_bytes(sums)
        report = validate(site, args.expected_commit)
        report.update({'public_url': base, 'published_files_verified': len(rows)})
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
