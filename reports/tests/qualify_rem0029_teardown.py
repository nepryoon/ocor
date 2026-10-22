#!/usr/bin/env python3
"""Real REM-0029 teardown acceptance; explicit mutation, one exclusive OCOR stack."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def qualify_anonymous_volume(call, image: str) -> dict:
    """Real Docker race: remove the owned container without -v just before down.

    All Docker calls and return codes are real. The injected scheduling point
    models another teardown removing the container first, leaving its anonymous
    volume invisible to Compose. The boundary must retain its earlier binding.
    """
    holder = 'ocor-bootstrap-rem0029-volume-' + uuid.uuid4().hex[:12]
    volume = None
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('reset_rem0029_live', ROOT / 'scripts/reset_test_environment.py')
    assert spec and spec.loader
    boundary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boundary)
    actual_run = boundary.run

    def raced_run(command, **kwargs):
        if command[:2] == ['docker', 'compose']:
            removed = call(['docker', 'rm', '--force', holder])  # Deliberately retain the anonymous volume.
            assert removed.returncode == 0
        result = actual_run(command, **kwargs)
        return result

    try:
        started = call(['docker', 'run', '--detach', '--name', holder,
                        '--label', 'com.docker.compose.project=ocor-bootstrap',
                        '--label', 'com.docker.compose.service=rem0029-volume',
                        '--network', 'none', '--volume', '/ocor-rem0029', '--entrypoint', '/bin/sh', image, '-c', 'sleep 600'])
        assert started.returncode == 0
        container = json.loads(call(['docker', 'inspect', holder]).stdout)[0]
        volume = next(m['Name'] for m in container['Mounts'] if m['Destination'] == '/ocor-rem0029')
        metadata = json.loads(call(['docker', 'volume', 'inspect', volume]).stdout)[0]
        assert metadata['Labels'].get('com.docker.volume.anonymous') == ''
        assert 'com.docker.compose.project' not in metadata['Labels']
        boundary.run = raced_run
        code, report = boundary.teardown(ROOT, boundary.teardown_command(ROOT))
        assert code != 0 and report['status'] == 'FAIL' and report['compose_exit_code'] == 0
        assert report['owned_resources_remaining']['volumes'] == [
            {'id': volume, 'name': volume, 'anonymous_mount_owner_ids': [container['Id']]}]
        assert call(['docker', 'volume', 'inspect', volume]).returncode == 0
        return {'status':'PASS', 'real_container_uuid':container['Id'], 'real_volume_name':volume,
                'actual_boundary_response':report, 'fault':'real rm without -v immediately before real Compose down; no fabricated Docker result'}
    finally:
        boundary.run = actual_run
        # Only exact resources created by this function; both cleanup results checked.
        names = call(['docker', 'ps', '-aq', '--filter', 'name=^/' + holder + '$'])
        assert names.returncode == 0
        if names.stdout.strip():
            assert call(['docker', 'rm', '--force', '--volumes', holder]).returncode == 0
        if volume is not None:
            remaining = call(['docker', 'volume', 'ls', '--format', '{{.Name}}'])
            assert remaining.returncode == 0
            if volume in remaining.stdout.splitlines():
                assert call(['docker', 'volume', 'rm', volume]).returncode == 0


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
            'status': 'NETWORK_PASS_PENDING_ANONYMOUS' if result_code == 0 else 'FAIL', 'exit_code': result_code,
            'real_network_uuid': before['Id'], 'network_remaining_was_proved': True,
            'raw_output_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'scope': 'exclusive ocor-bootstrap and exact session-owned holder/network; no mocks'
        }, indent=2, sort_keys=True) + '\n')
    if result_code == 0:
        anonymous = qualify_anonymous_volume(call, image)
        empty = call([sys.executable, 'scripts/reset_test_environment.py', '--execute'], timeout=250)
        assert empty.returncode == 0 and json.loads(empty.stdout)['status'] == 'PASS'
        path = args.output_dir / 'real-teardown.log'
        result = json.loads((args.output_dir / 'result.json').read_text())
        result['status'] = 'PASS'
        result['anonymous_volume'] = anonymous
        result['raw_output_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        (args.output_dir / 'result.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result_code


if __name__ == '__main__':
    raise SystemExit(main())
