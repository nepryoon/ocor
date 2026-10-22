#!/usr/bin/env python3
"""Real REM-0029 teardown acceptance; explicit mutation, one exclusive OCOR stack."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'status': 'DRY_RUN', 'scope': 'ocor-bootstrap network and own temporary holder only'}))
        return 0
    args.output_dir.mkdir(parents=True, exist_ok=True)
    events = []

    def call(command, timeout=30):
        started = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        events.append({'command': command, 'exit_code': result.returncode,
                       'duration_seconds': time.monotonic() - started,
                       'stdout': result.stdout, 'stderr': result.stderr})
        (args.output_dir / 'real-teardown.log').write_text(json.dumps(events, indent=2, sort_keys=True) + '\n')
        return result

    network = 'ocor-bootstrap_ocor-bootstrap'
    holder = 'ocor-rem0029-holder-' + uuid.uuid4().hex[:12]
    lock = json.loads((ROOT / 'infra/toolchain.lock.json').read_text())
    image = next(t['container_image'] for t in lock['tools'] if t['id'] == 'java')
    names = call(['docker', 'network', 'ls', '--filter', 'label=com.docker.compose.project=ocor-bootstrap', '--format', '{{.Name}}'])
    assert names.returncode == 0 and names.stdout.splitlines() == [network], 'exclusive initialized bootstrap network required'
    before = json.loads(call(['docker', 'network', 'inspect', network]).stdout)[0]
    assert before['Labels']['com.docker.compose.project'] == 'ocor-bootstrap'
    result_code = 1
    try:
        result = call(['docker', 'run', '--detach', '--name', holder, '--label', 'ocor.rem0029.owner=qualification',
                       '--network', network, '--entrypoint', '/bin/sh', image, '-c', 'sleep 600'])
        assert result.returncode == 0
        result = call([sys.executable, 'scripts/reset_test_environment.py', '--execute'], timeout=250)
        response = json.loads(result.stdout)
        remaining = json.loads(call(['docker', 'network', 'inspect', before['Id']]).stdout)[0]
        assert remaining['Id'] == before['Id'] and remaining['Containers'], 'the occupied network must really remain'
        assert result.returncode != 0, 'RED: Compose zero with an occupied owned network must never be PASS'
        assert response['status'] == 'FAIL' and response['compose_exit_code'] == 0
        assert response['owned_resources_remaining']['networks'] == [{'id': before['Id'], 'name': network}]
        result_code = 0
    finally:
        call(['docker', 'rm', '--force', '--volumes', holder])
        # Exact session-owned network only; never prune or disconnect unrelated endpoints.
        try:
            # On a pre-mutation rejection, the original stack may still be up.
            down = call(['docker', 'compose', '--env-file', str(ROOT / '.ocor/bootstrap.env'), '-p', 'ocor-bootstrap',
                         '-f', 'deploy/bootstrap/compose.yaml', 'down', '--volumes', '--remove-orphans'], timeout=180)
            assert down.returncode == 0
            cleaned = call([sys.executable, 'scripts/reset_test_environment.py', '--execute'], timeout=250)
            if result_code == 0:
                assert cleaned.returncode == 0 and json.loads(cleaned.stdout)['status'] == 'PASS'
        finally:
            (args.output_dir / 'real-teardown.log').write_text(json.dumps(events, indent=2, sort_keys=True) + '\n')
        raw = json.dumps(events, indent=2, sort_keys=True) + '\n'
        path = args.output_dir / 'real-teardown.log'
        path.write_text(raw)
        (args.output_dir / 'result.json').write_text(json.dumps({
            'status': 'PASS' if result_code == 0 else 'FAIL', 'exit_code': result_code,
            'real_network_uuid': before['Id'], 'network_remaining_was_proved': True,
            'raw_output_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'scope': 'exclusive ocor-bootstrap and exact session-owned holder/network; no mocks'
        }, indent=2, sort_keys=True) + '\n')
    return result_code


if __name__ == '__main__':
    raise SystemExit(main())
