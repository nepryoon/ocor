"""Real Docker proof that a lane sandbox consumes a transferred locked image.

The deterministic cache checks live in test_local_lane_campaign.py, which the
validation-closure guards collect. This proof starts one private dockerd, loads
one image that is already on the host, and shows that an unchanged pinned pull
does not download it while a different digest is rejected.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
SPEC = importlib.util.spec_from_file_location('ocor_local_lanes_live', ROOT / 'scripts/run_local_lane_campaign.py')
assert SPEC is not None and SPEC.loader is not None
LANES = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LANES
SPEC.loader.exec_module(LANES)
IMAGE_CACHE = sys.modules['local_lane_image_cache']
CAMPAIGN = sys.modules['run_qualifying_campaign']

PIN = 'ghcr.io/spiffe/spire-agent@sha256:41b0dcd8b258a69db9e2768292a060766fb76fd866e4bc925849981ea1b825ff'
HEAD = 'a' * 40


def _combined(argv: list[str], *, timeout: float) -> tuple[int, str, str]:
    completed = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    return completed.returncode, completed.stdout.decode('utf-8', 'replace'), completed.stderr.decode('utf-8', 'replace')


def _root_image_present() -> bool:
    return LANES.run_command(
        ['docker', 'image', 'inspect', LANES.SANDBOX_ROOT_IMAGE], check=False).returncode == 0


def _release(items: list, work: Path, *, created_root: bool) -> None:
    """Remove only the sandboxes, volumes and root image this run created."""
    for item in items:
        LANES.run_command(['docker', 'rm', '-f', item.name], check=False)
        LANES.run_command(['docker', 'volume', 'rm', '-f', *item.volumes], check=False)
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    users = LANES.run_command(
        ['docker', 'ps', '-aq', '--filter', f'ancestor={LANES.SANDBOX_ROOT_IMAGE}'], check=False)
    if created_root and users.stdout.strip() == '':
        LANES.remove_root_image(LANES.run_command)
    for item in items:
        residue = LANES.run_command(['docker', 'ps', '-aq', '--filter', f'name={item.name}'], check=False)
        volumes = LANES.run_command(['docker', 'volume', 'ls', '-q', '--filter', f'name={item.name}'], check=False)
        assert residue.stdout.strip() == ''
        assert volumes.stdout.strip() == ''
    if created_root and users.stdout.strip() == '':
        assert _root_image_present() is False


def _lane(work: Path, index: int, campaign: str):
    item = LANES.Lane(index=index, campaign=campaign, root=work / f'lane-{index}',
                      home=Path.home(), uid=os.getuid(), gid=os.getgid())
    item.repository.mkdir(parents=True)
    item.output.mkdir(parents=True)
    return item


def test_lanes_cannot_change_the_shared_image_cache(tmp_path: Path) -> None:
    """Two lanes of one campaign can read the shared cache and cannot modify it."""
    work = tmp_path / 'cache-proof'
    cache = work / 'image-cache'
    cache.mkdir(parents=True)
    marker = cache / 'marker'
    marker.write_text('sealed\n', encoding='utf-8')
    campaign = LANES.campaign_id(HEAD, time.time_ns())
    items = [_lane(work, 1, campaign), _lane(work, 2, campaign)]
    created_root = not _root_image_present()
    try:
        LANES.ensure_root_image(LANES.run_command, LANES.host_usr_links())
        for item in items:
            LANES.start_sandbox(item, [], LANES.run_command, output_root=work, readonly_mounts=[cache])
            quoted = shlex.quote(str(marker))
            sibling = shlex.quote(str(cache / f'lane-{item.index}.new'))
            code, stdout, stderr = _combined(LANES.sandbox_exec_argv(
                item, '/usr/bin:/bin', ['sh', '-c', f'printf x >> {quoted}; touch {sibling}'], {}), timeout=60)
            assert code != 0, stdout + stderr
            assert marker.read_text(encoding='utf-8') == 'sealed\n'
            assert not (cache / f'lane-{item.index}.new').exists()
            note = item.output / 'writable.txt'
            note_code, note_out, note_err = _combined(LANES.sandbox_exec_argv(
                item, '/usr/bin:/bin', ['sh', '-c', f'printf ok > {shlex.quote(str(note))}'], {}), timeout=60)
            assert note_code == 0, note_out + note_err
            assert note.read_text(encoding='utf-8') == 'ok'
    finally:
        _release(items, work, created_root=created_root)


def test_transferred_image_satisfies_an_unchanged_pinned_pull(tmp_path: Path) -> None:
    work = tmp_path / 'live-proof'
    work.mkdir()
    lock = work / 'services.lock.json'
    lock.write_text(json.dumps({'services': [{'id': 'spire-agent', 'image': PIN}]}, indent=2, sort_keys=True) + '\n',
                    encoding='utf-8')
    cache = work / 'image-cache'
    item = _lane(work, 1, LANES.campaign_id(HEAD, time.time_ns()))
    created_root = not _root_image_present()
    try:
        manifest = IMAGE_CACHE.prepare_image_cache(lock, cache, LANES.run_command, timeout=180)
        assert manifest['images'][0]['status'] == 'PRESENT'
        assert manifest['images'][0]['pinned_reference'] == PIN
        image_id = manifest['images'][0]['image_id']
        assert image_id == 'sha256:' + PIN.rsplit(':', 1)[1]
        LANES.ensure_root_image(LANES.run_command, LANES.host_usr_links())
        LANES.start_sandbox(item, [], LANES.run_command, output_root=work, readonly_mounts=[cache])
        seeded = LANES.seed_lane_images(item, '/usr/bin:/bin', cache, lock, LANES.run_command, timeout=lambda: 180)
        assert seeded == {'loaded': ['spire-agent'], 'misses': []}
        pull = LANES.sandbox_exec_argv(item, '/usr/bin:/bin', ['docker', 'pull', PIN], {})
        code, stdout, stderr = _combined(pull, timeout=180)
        combined = stdout + stderr
        # docker load does not restore the repo digest. The unchanged pull reconfirms
        # the registry manifest and must consume the transferred blobs: no layer download.
        assert code == 0, combined[-2000:]
        assert 'Download complete' not in combined and 'Downloading' not in combined and 'Pulling fs layer' not in combined
        assert PIN.rsplit(':', 1)[1] in combined
        again_code, again_out, again_err = _combined(pull, timeout=180)
        again = again_out + again_err
        assert again_code == 0, again[-2000:]
        assert 'up to date' in again.lower() or 'Already exists' in again
        assert 'Download complete' not in again and 'Downloading' not in again
        inspected = LANES.run_command(LANES.sandbox_exec_argv(
            item, '/usr/bin:/bin', ['docker', 'image', 'inspect', image_id], {}))
        IMAGE_CACHE.parse_loaded_inspect(inspected.stdout, image_id)
        bad = PIN.split('@', 1)[0] + '@sha256:' + ('0' * 64)
        rejected = LANES.sandbox_exec_argv(item, '/usr/bin:/bin', ['docker', 'pull', bad], {})
        bad_code, bad_out, bad_err = _combined(rejected, timeout=180)
        assert bad_code != 0
        assert 'Download complete' not in bad_out + bad_err
    finally:
        _release([item], work, created_root=created_root)
