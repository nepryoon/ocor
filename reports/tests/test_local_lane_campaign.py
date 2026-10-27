"""RED-first controls for the local two-lane full-suite orchestrator (OCOR-DEV-REM-0037).

PO LOCAL-SUITE-SPLIT (2026-10-25) point 4 and LOCAL-SUITE-SPLIT-REACTIVATION
(2026-10-26) point 5: a deterministic partition computed from measured per-case
times, every collected case exactly once, and an exact JUnit union with zero
skips (missing, duplicated and extra cases are rejected). Memory admission
falls back to the serial suite below the measured start threshold.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
SPEC = importlib.util.spec_from_file_location('ocor_local_lanes', ROOT / 'scripts/run_local_lane_campaign.py')
assert SPEC is not None and SPEC.loader is not None
LANES = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LANES
SPEC.loader.exec_module(LANES)
CAMPAIGN = sys.modules['run_qualifying_campaign']

M49 = 'tests/tasks/test_ocor_dev_0049.py'
HELM = CAMPAIGN.HELM_NODE


def nodes():
    return [
        'tests/tasks/test_a.py::test_one',
        'tests/tasks/test_a.py::test_two[x]',
        'tests/tasks/test_b.py::test_one',
        f'{M49}::test_slow',
        f'{M49}::test_mid',
        f'{M49}::test_fast[p1]',
        HELM,
        'tests/tasks/test_c.py::TestK::test_one',
    ]


def weights():
    return {
        'tests.tasks.test_a::test_one': 5.0,
        'tests.tasks.test_a::test_two[x]': 5.0,
        'tests.tasks.test_b::test_one': 2.0,
        'tests.tasks.test_ocor_dev_0049::test_slow': 300.0,
        'tests.tasks.test_ocor_dev_0049::test_mid': 200.0,
        'tests.tasks.test_ocor_dev_0049::test_fast[p1]': 10.0,
        'tests.tasks.test_ocor_dev_0049::' + HELM.split('::')[-1]: 400.0,
    }


def write_junit(path: Path, cases, *, skipped=(), failed=()):
    suite = ET.Element('testsuite', name='pytest', tests=str(len(cases)), failures=str(len(failed)), errors='0', skipped=str(len(skipped)))
    for classname, name in cases:
        case = ET.SubElement(suite, 'testcase', classname=classname, name=name, time='0.1')
        if (classname, name) in skipped:
            ET.SubElement(case, 'skipped')
        if (classname, name) in failed:
            ET.SubElement(case, 'failure')
    root = ET.Element('testsuites')
    root.append(suite)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
    return path


def lane_junits(tmp_path, parts):
    return [write_junit(tmp_path / f'lane-{index}.xml', [CAMPAIGN.junit_identity(node) for node in part])
            for index, part in enumerate(parts, start=1)]


# --- partitioner ----------------------------------------------------------

def test_partition_places_every_collected_case_exactly_once():
    parts = LANES.lane_partition(nodes(), weights())
    flat = [node for part in parts for node in part]
    assert len(parts) == 2 and all(parts)
    assert sorted(flat) == sorted(nodes()) and len(flat) == len(set(flat))


def test_partition_is_deterministic_and_independent_of_weight_order():
    reordered = dict(reversed(list(weights().items())))
    first = LANES.lane_partition(nodes(), weights())
    assert LANES.lane_partition(list(nodes()), reordered) == first
    assert LANES.lane_partition(nodes(), weights()) == first


def test_partition_keeps_collection_order_inside_each_lane():
    order = {node: index for index, node in enumerate(nodes())}
    for part in LANES.lane_partition(nodes(), weights()):
        assert part == sorted(part, key=order.__getitem__)


def test_partition_keeps_every_other_module_whole():
    parts = LANES.lane_partition(nodes(), weights())
    for module in ('tests/tasks/test_a.py', 'tests/tasks/test_b.py', 'tests/tasks/test_c.py'):
        holders = [index for index, part in enumerate(parts) if any(node.startswith(module + '::') for node in part)]
        assert len(holders) == 1, module


def test_partition_distributes_the_0049_module_across_both_lanes():
    parts = LANES.lane_partition(nodes(), weights())
    assert all(any(node.startswith(M49 + '::') for node in part) for part in parts)


def test_partition_balances_lanes_within_the_largest_unit():
    parts = LANES.lane_partition(nodes(), weights())
    loads = LANES.lane_loads(parts, weights())
    assert max(loads) - min(loads) <= max(weights().values())
    # Helm (400 s) and the slow 0049 case (300 s) must not share a lane.
    assert not any(HELM in part and f'{M49}::test_slow' in part for part in parts)


def test_unmeasured_cases_use_the_declared_default_weight():
    assert LANES.case_weight('tests/tasks/test_c.py::TestK::test_one', weights()) == LANES.DEFAULT_CASE_SECONDS
    assert LANES.case_weight(f'{M49}::test_slow', weights()) == 300.0


@pytest.mark.parametrize('bad', [
    [],
    ['tests/tasks/test_a.py::test_one'],
    ['tests/tasks/test_a.py::test_one', 'tests/tasks/test_a.py::test_one'],
    ['tests/tasks/test_a.py::test_one', 'tests/tasks/test_a.py::test_two'],
])
def test_partition_rejects_empty_duplicate_or_unsplittable_collections(bad):
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.lane_partition(bad, weights())


def test_partition_rejects_ambiguous_junit_identities():
    with pytest.raises(CAMPAIGN.CampaignError, match='JUnit'):
        LANES.lane_partition(['tests/x.py::test_a', 'tests/x/py::test_a', 'tests/y.py::test_b'], {})


@pytest.mark.parametrize('lanes', [0, 1, 3])
def test_partition_supports_exactly_two_lanes(lanes):
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.lane_partition(nodes(), weights(), lanes=lanes)


def test_partition_digest_changes_with_assignment():
    parts = LANES.lane_partition(nodes(), weights())
    swapped = [parts[1], parts[0]]
    assert CAMPAIGN.partition_digest(parts) != CAMPAIGN.partition_digest(swapped)


# --- exact union ----------------------------------------------------------

def test_union_accepts_exactly_the_collected_cases(tmp_path):
    parts = LANES.lane_partition(nodes(), weights())
    summary = LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts))
    assert summary == {'collected': len(nodes()), 'executed': len(nodes()), 'missing': [], 'duplicated': [], 'unexpected': [],
                       'lanes': [len(part) for part in parts]}


def test_union_rejects_a_missing_case(tmp_path):
    parts = LANES.lane_partition(nodes(), weights())
    parts[0] = parts[0][1:]
    with pytest.raises(CAMPAIGN.CampaignError, match='missing'):
        LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts))


def test_union_rejects_a_duplicated_case(tmp_path):
    parts = LANES.lane_partition(nodes(), weights())
    parts[1] = parts[1] + [parts[0][0]]
    with pytest.raises(CAMPAIGN.CampaignError, match='duplicated'):
        LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts))


def test_union_rejects_an_extra_case(tmp_path):
    parts = LANES.lane_partition(nodes(), weights())
    parts[1] = parts[1] + ['tests/tasks/test_z.py::test_extra']
    with pytest.raises(CAMPAIGN.CampaignError, match='unexpected'):
        LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts))


def test_union_rejects_a_skipped_case(tmp_path):
    parts = LANES.lane_partition(nodes(), weights())
    cases = [CAMPAIGN.junit_identity(node) for node in parts[0]]
    paths = lane_junits(tmp_path, parts)
    write_junit(paths[0], cases, skipped={cases[0]})
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.check_exact_union(nodes(), paths)


def test_union_rejects_a_failed_case(tmp_path):
    parts = LANES.lane_partition(nodes(), weights())
    cases = [CAMPAIGN.junit_identity(node) for node in parts[1]]
    paths = lane_junits(tmp_path, parts)
    write_junit(paths[1], cases, failed={cases[-1]})
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.check_exact_union(nodes(), paths)


def test_union_rejects_a_missing_lane(tmp_path):
    parts = LANES.lane_partition(nodes(), weights())
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts)[:1])


def test_union_rejects_an_absent_junit(tmp_path):
    parts = LANES.lane_partition(nodes(), weights())
    paths = lane_junits(tmp_path, parts)
    paths[1].unlink()
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.check_exact_union(nodes(), paths)


# --- memory admission -----------------------------------------------------

def meminfo(total_kib, available_kib):
    return f'MemTotal:       {total_kib} kB\nMemFree:        1 kB\nMemAvailable:   {available_kib} kB\n'


def test_memory_admission_starts_two_lanes_at_or_above_the_threshold():
    threshold_kib = int(LANES.TWO_LANE_START_THRESHOLD_MIB * 1024)
    assert LANES.memory_admission(meminfo(31743008, threshold_kib + 1024))['mode'] == 'TWO_LANE'
    assert LANES.memory_admission(meminfo(31743008, threshold_kib + 1))['mode'] == 'TWO_LANE'


def test_memory_admission_falls_back_to_serial_below_the_threshold():
    threshold_kib = int(LANES.TWO_LANE_START_THRESHOLD_MIB * 1024)
    decision = LANES.memory_admission(meminfo(31743008, threshold_kib - 1))
    assert decision['mode'] == 'SERIAL'
    assert decision['mem_available_kib'] == threshold_kib - 1 and decision['threshold_mib'] == LANES.TWO_LANE_START_THRESHOLD_MIB


@pytest.mark.parametrize('text', ['', 'MemTotal: 1 kB\n', 'MemAvailable: x kB\nMemTotal: 1 kB\n'])
def test_memory_admission_without_a_readable_measure_is_serial(text):
    assert LANES.memory_admission(text)['mode'] == 'SERIAL'


def test_threshold_is_the_measured_value_and_the_guard_is_unchanged():
    assert LANES.TWO_LANE_START_THRESHOLD_MIB == 14340.6
    assert LANES.MEMORY_GUARD_MIB == 3000


# --- limits, weights file and defaults ------------------------------------

def test_limits_are_the_governed_full_suite_limits_applied_to_the_whole_campaign():
    assert LANES.FULL_SUITE_LIMIT_SECONDS == CAMPAIGN.FULL_SUITE_LIMIT_SECONDS == 5400
    assert LANES.PO_DECISION_THRESHOLD_SECONDS == CAMPAIGN.PO_DECISION_THRESHOLD_SECONDS == 3600
    with pytest.raises(CAMPAIGN.CampaignError, match='90-minute'):
        LANES.check_campaign_deadline(5400)
    assert LANES.check_campaign_deadline(3601) is True
    assert LANES.check_campaign_deadline(3599) is False


def test_derived_weights_are_reproducible_from_a_junit(tmp_path):
    junit = tmp_path / 'm.xml'
    suite = ET.Element('testsuite', name='pytest', tests='3', failures='0', errors='0', skipped='0')
    for name, seconds in (('test_slow', '2.5'), ('test_fast', '0.01'), ('test_edge', '0.5')):
        ET.SubElement(suite, 'testcase', classname='tests.tasks.test_a', name=name, time=seconds)
    ET.ElementTree(suite).write(junit, encoding='utf-8', xml_declaration=True)
    derived = LANES.derive_weights(junit)
    assert derived['weights'] == {'tests.tasks.test_a::test_edge': 0.5, 'tests.tasks.test_a::test_slow': 2.5}
    assert derived['default_case_seconds'] == LANES.DEFAULT_CASE_SECONDS
    assert derived['minimum_case_seconds'] == LANES.MINIMUM_MEASURED_SECONDS
    assert derived['source']['cases'] == 3 and len(derived['source']['junit_sha256']) == 64
    assert LANES.derive_weights(junit) == derived


def test_committed_weights_file_is_well_formed_and_covers_the_measured_slow_cases():
    data = json.loads(LANES.WEIGHTS_PATH.read_text(encoding='utf-8'))
    assert data['default_case_seconds'] == LANES.DEFAULT_CASE_SECONDS
    assert data['source']['junit_sha256'] == 'a7e4ada48efa056c62ee28c579c02901f595f3d361004a1ea07db4bd91e2059e'
    assert data['source']['cases'] == 3224
    assert all(value >= LANES.MINIMUM_MEASURED_SECONDS for value in data['weights'].values())
    assert data['weights']['tests.tasks.test_ocor_dev_0049::' + HELM.split('::')[-1]] > 400
    assert LANES.load_weights() == data['weights']


def test_measured_partition_estimate_is_reported_with_its_lower_bound():
    data = json.loads(LANES.WEIGHTS_PATH.read_text(encoding='utf-8'))
    estimate = LANES.partition_estimate(list(data['weights'].keys()), data['weights'])
    assert estimate['lower_bound_seconds'] == max(data['weights'].values())
    assert len(estimate['lane_seconds']) == 2
    assert max(estimate['lane_seconds']) >= estimate['lower_bound_seconds']


def test_orchestrator_does_not_alter_the_serial_campaign_defaults():
    # The additive orchestrator imports the sealed supervisor; it never rebinds it.
    assert CAMPAIGN.MANDATORY_CONTAINERS == 15
    assert CAMPAIGN.PART_LIMIT_SECONDS == 2700 and CAMPAIGN.PART_REBALANCE_SECONDS == 1800
    assert CAMPAIGN.INDEPENDENT_MODULES == frozenset({M49})


# --- lane lifecycle: provisioning, private-daemon sandbox, teardown -------
# Both lanes run in an OCOR-labelled sandbox with its own dockerd, network
# namespace, /run, /tmp and HOME, so the default names and ports of the stack
# (ocor-bootstrap, ocor-poc, 127.0.0.1) stay unchanged and the host daemon's
# development stack is never touched.

HEAD = 'db8b42c6db7a98f694d91017c97ec5697a93d7d4'
CAMPAIGN_ID = 'db8b42c6db7a-1793000000'


class FakeRunner:
    """Records argv; scripted replies by argv prefix (first match wins)."""

    def __init__(self, replies=None):
        self.calls = []
        self.replies = list(replies or [])

    def __call__(self, argv, *, cwd=None, env=None, input=None, timeout=600, check=True):
        argv = [str(item) for item in argv]
        self.calls.append({'argv': argv, 'cwd': None if cwd is None else str(cwd), 'env': env, 'input': input})
        for prefix, returncode, stdout in self.replies:
            if argv[:len(prefix)] == prefix or (prefix and prefix[0] == '*' and ' '.join(prefix[1:]) in ' '.join(argv)):
                break
        else:
            returncode, stdout = 0, ''
        if check and returncode:
            raise CAMPAIGN.CampaignError(f'command failed ({returncode}): {argv[:6]}')
        return LANES.CommandResult(returncode, stdout)

    def argvs(self):
        return [call['argv'] for call in self.calls]


def lane(tmp_path, index=1):
    return LANES.Lane(index=index, campaign=CAMPAIGN_ID, root=tmp_path / 'lanes' / f'lane-{index}',
                      home=Path('/home/luca'), uid=1000, gid=1000)


def test_campaign_id_is_the_head_prefix_and_start_time_and_rejects_bad_input():
    assert LANES.campaign_id(HEAD, 1793000000) == 'db8b42c6db7a-1793000000'
    for head in ('', 'DB8B42C6DB7A98F694D91017C97EC5697A93D7D4', HEAD[:39], HEAD + 'x'):
        with pytest.raises(CAMPAIGN.CampaignError):
            LANES.campaign_id(head, 1793000000)


def test_lane_resources_are_scoped_to_the_campaign_and_never_use_the_stack_names(tmp_path):
    first, second = lane(tmp_path, 1), lane(tmp_path, 2)
    assert first.name == f'ocor-lane-{CAMPAIGN_ID}-1' and second.name == f'ocor-lane-{CAMPAIGN_ID}-2'
    assert first.volumes == (f'{first.name}-docker', f'{first.name}-home')
    assert first.repository == first.root / 'repo' and first.output == first.root / 'out'
    assert {first.name, second.name}.isdisjoint({'ocor-bootstrap', 'ocor-poc'})
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.Lane(index=3, campaign=CAMPAIGN_ID, root=tmp_path, home=Path('/home/luca'), uid=1000, gid=1000)


def test_lane_path_puts_locked_tools_first_then_the_lane_checkout(tmp_path):
    item = lane(tmp_path)
    path = LANES.lane_path(item, [Path('/home/luca/.ocor-codex/impl-env/x/bin')])
    assert path.split(':') == ['/home/luca/.ocor-codex/impl-env/x/bin', str(item.repository / '.ocor/tools/bin'),
                               str(item.repository / 'ocor-runtime/.venv/bin'), '/usr/local/bin', '/usr/bin', '/bin']


def test_tool_mounts_cover_the_resolved_locked_tools_read_only(tmp_path):
    home = tmp_path / 'home'
    target = home / '.ocor-codex/c5resume/toolchain/node-v20/bin/node'
    git = home / '.ocor-codex/rem0019/isolated-git/usr/lib/git-core/git'
    python = home / '.local/share/uv/python/cpython/bin/python3.12'
    for path in (target, git, python):
        path.parent.mkdir(parents=True)
        path.write_text('')
    bindir = home / '.ocor-codex/impl-env/unit/bin'
    bindir.mkdir(parents=True)
    (bindir / 'node').symlink_to(target)
    (bindir / 'git').symlink_to(git)
    (bindir / 'docker').symlink_to('/usr/bin/docker')
    mounts = LANES.tool_mounts([bindir, python], home)
    assert mounts == sorted([home / '.local/share/uv', home / '.ocor-codex/c5resume/toolchain',
                             home / '.ocor-codex/impl-env/unit', home / '.ocor-codex/rem0019/isolated-git'])


def test_tool_mounts_reject_tools_outside_home_and_usr(tmp_path):
    home = tmp_path / 'home'
    bindir = home / '.ocor-codex/impl-env/unit/bin'
    bindir.mkdir(parents=True)
    (bindir / 'evil').symlink_to('/opt/elsewhere/evil')
    with pytest.raises(CAMPAIGN.CampaignError, match='outside'):
        LANES.tool_mounts([bindir], home)


def test_sandbox_run_argv_has_the_exact_mount_set_and_the_campaign_label(tmp_path):
    item = lane(tmp_path)
    mounts = [Path('/home/luca/.local/share/uv'), Path('/home/luca/.ocor-codex/impl-env/unit')]
    argv = LANES.sandbox_run_argv(item, mounts, output_root=tmp_path / 'out')
    assert argv == [
        'docker', 'run', '-d', '--name', item.name, '--label', f'{LANES.LANE_LABEL}={CAMPAIGN_ID}',
        '--privileged', '--cgroupns=private',
        '-v', '/usr:/usr:ro', '-v', '/etc:/etc:ro',
        '-v', f'{item.volumes[0]}:/var/lib/docker', '-v', f'{item.volumes[1]}:/home/luca',
        '-v', '/home/luca/.local/share/uv:/home/luca/.local/share/uv:ro',
        '-v', '/home/luca/.ocor-codex/impl-env/unit:/home/luca/.ocor-codex/impl-env/unit:ro',
        '-v', f'{item.root}:{item.root}', '-v', f'{tmp_path / "out"}:{tmp_path / "out"}',
        '--tmpfs', '/run', '--tmpfs', '/tmp:exec,mode=1777', '--tmpfs', '/root',
        '-e', 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin',
        LANES.SANDBOX_ROOT_IMAGE, '/bin/sh', '-c', LANES.sandbox_init(item)]


def test_sandbox_init_nests_cgroup_v2_and_starts_a_private_dockerd_for_the_lane_group(tmp_path):
    script = LANES.sandbox_init(lane(tmp_path))
    assert 'mkdir -p /sys/fs/cgroup/init' in script and 'cgroup.subtree_control' in script
    assert 'chown 1000:1000 /home/luca' in script and 'ln -sfn /run /var/run' in script
    assert script.endswith('exec /usr/bin/dockerd --host unix:///run/docker.sock --group 1000 --data-root /var/lib/docker')


def test_sandbox_exec_runs_as_the_lane_user_with_the_lane_home_and_path(tmp_path):
    item = lane(tmp_path)
    argv = LANES.sandbox_exec_argv(item, '/p/bin:/usr/bin', ['python', '-V'], {'B': '2', 'A': '1'})
    assert argv == ['docker', 'exec', '-u', '1000:1000', '-w', str(item.repository), '-e', 'HOME=/home/luca',
                    '-e', 'PATH=/p/bin:/usr/bin', '-e', 'A=1', '-e', 'B=2', item.name, 'python', '-V']


def test_empty_root_is_deterministic_and_contains_only_directories_and_usr_links():
    import io
    import tarfile
    links = {'bin': 'usr/bin', 'lib': 'usr/lib', 'lib64': 'usr/lib64', 'sbin': 'usr/sbin'}
    data = LANES.empty_root_tar(links)
    assert data == LANES.empty_root_tar(dict(reversed(list(links.items()))))
    members = tarfile.open(fileobj=io.BytesIO(data)).getmembers()
    assert all(member.isdir() or member.issym() for member in members)
    assert {m.name: m.linkname for m in members if m.issym()} == {**links, 'var/run': '/run'}
    assert {'usr', 'etc', 'proc', 'sys', 'dev', 'run', 'tmp', 'root', 'home', 'var/lib/docker'} <= {m.name for m in members if m.isdir()}
    assert all(member.mtime == 0 and member.uid == 0 for member in members)


def test_ensure_root_image_imports_locally_only_when_absent():
    absent = FakeRunner([(['docker', 'image', 'inspect'], 1, '')])
    LANES.ensure_root_image(absent, {'bin': 'usr/bin'})
    assert absent.argvs()[-1] == ['docker', 'import', '--change', f'LABEL {LANES.LANE_LABEL}=root', '-', LANES.SANDBOX_ROOT_IMAGE]
    assert absent.calls[-1]['input'] == LANES.empty_root_tar({'bin': 'usr/bin'})
    present = FakeRunner()
    LANES.ensure_root_image(present, {'bin': 'usr/bin'})
    assert not any('import' in argv for argv in present.argvs())
    assert not any('pull' in argv for argv in absent.argvs() + present.argvs())


def source_checkout(tmp_path):
    source = tmp_path / 'source'
    (source / '.ocor/tools/bin').mkdir(parents=True)
    (source / '.ocor/cache/fuseki/sha512').mkdir(parents=True)
    for tool in ('helm', 'kind', 'kubectl'):
        (source / '.ocor/tools/bin' / tool).write_text(tool)
    (source / '.ocor/cache/fuseki/sha512/abc').write_text('archive')
    (source / '.ocor/bootstrap.env').write_text('OCOR_LOCAL_POSTGRES_PASSWORD=host-secret\n')
    return source


def test_provision_steps_clone_the_exact_head_self_contained_with_the_locked_extras(tmp_path):
    item = lane(tmp_path)
    steps = LANES.provision_steps(item, tmp_path / 'source', HEAD)
    repo, sdk = item.repository, item.repository / 'ocor-runtime/sdk/typescript'
    assert steps == [
        (['git', 'clone', '--no-hardlinks', '--no-checkout', '--quiet', str(tmp_path / 'source'), str(repo)], None),
        (['git', '-C', str(repo), 'checkout', '--quiet', '--detach', HEAD], None),
        (['uv', 'sync', '--project', str(repo / 'ocor-runtime'), '--frozen', '--extra', 'test', '--extra', 'lint'], repo),
        (['npm', 'ci', '--no-audit', '--no-fund'], sdk),
        (['npm', 'run', 'build'], sdk)]


def test_provision_lane_copies_tools_and_cache_but_never_credentials(tmp_path, monkeypatch):
    item, source = lane(tmp_path), source_checkout(tmp_path)
    runner = FakeRunner([(['git', '-C', str(item.repository), 'rev-parse', 'HEAD'], 0, HEAD + '\n')])
    monkeypatch.setattr(LANES, 'verify_lane_tools', lambda repository: None)
    result = LANES.provision_lane(item, source, HEAD, runner, {'PATH': '/x'})
    assert (item.repository / '.ocor/tools/bin/kind').read_text() == 'kind'
    assert (item.repository / '.ocor/cache/fuseki/sha512/abc').read_text() == 'archive'
    assert not (item.repository / '.ocor/bootstrap.env').exists()
    assert item.output.is_dir() and result['head'] == HEAD
    assert ['git', '-C', str(item.repository), 'status', '--porcelain', '--untracked-files=no'] in runner.argvs()


def test_provision_lane_refuses_an_existing_lane_root(tmp_path):
    item = lane(tmp_path)
    item.root.mkdir(parents=True)
    with pytest.raises(CAMPAIGN.CampaignError, match='exists'):
        LANES.provision_lane(item, source_checkout(tmp_path), HEAD, FakeRunner(), {})


def test_provision_lane_fails_closed_on_a_head_mismatch_or_tracked_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(LANES, 'verify_lane_tools', lambda repository: None)
    source = source_checkout(tmp_path)
    item = lane(tmp_path, 1)
    other = FakeRunner([(['git', '-C', str(item.repository), 'rev-parse', 'HEAD'], 0, '0' * 40 + '\n')])
    with pytest.raises(CAMPAIGN.CampaignError, match='HEAD'):
        LANES.provision_lane(item, source, HEAD, other, {})
    item = lane(tmp_path, 2)
    dirty = FakeRunner([(['git', '-C', str(item.repository), 'rev-parse', 'HEAD'], 0, HEAD + '\n'),
                        (['git', '-C', str(item.repository), 'status'], 0, ' M scripts/x.py\n')])
    with pytest.raises(CAMPAIGN.CampaignError, match='tracked'):
        LANES.provision_lane(item, source, HEAD, dirty, {})


def test_lane_tools_are_verified_against_the_qualification_lock(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'infra').mkdir(parents=True)
    (repo / '.ocor/tools/bin').mkdir(parents=True)
    import hashlib
    tools = []
    for name in ('helm', 'kind', 'kubectl'):
        (repo / '.ocor/tools/bin' / name).write_bytes(name.encode())
        tools.append({'id': name, 'binary_sha256': hashlib.sha256(name.encode()).hexdigest()})
    (repo / 'infra/qualification_tools.lock.json').write_text(json.dumps({'tools': tools}))
    LANES.verify_lane_tools(repo)
    (repo / '.ocor/tools/bin/kind').write_bytes(b'tampered')
    with pytest.raises(CAMPAIGN.CampaignError, match='kind'):
        LANES.verify_lane_tools(repo)


def test_start_sandbox_creates_labelled_volumes_and_waits_for_an_empty_private_daemon(tmp_path):
    item = lane(tmp_path)
    runner = FakeRunner()
    LANES.start_sandbox(item, [], runner, output_root=tmp_path / 'out', sleep=lambda seconds: None)
    argvs = runner.argvs()
    for volume in item.volumes:
        assert ['docker', 'volume', 'create', '--label', f'{LANES.LANE_LABEL}={CAMPAIGN_ID}', volume] in argvs
    assert argvs.index(LANES.sandbox_run_argv(item, [], output_root=tmp_path / 'out')) > 1
    assert ['docker', 'exec', item.name, 'docker', 'info', '--format', '{{.ServerVersion}}'] in argvs
    assert ['docker', 'exec', item.name, 'docker', 'ps', '-aq'] in argvs


def test_start_sandbox_fails_closed_when_the_private_daemon_never_answers(tmp_path):
    item = lane(tmp_path)
    runner = FakeRunner([(['docker', 'exec', item.name, 'docker', 'info'], 1, '')])
    waits = []
    with pytest.raises(CAMPAIGN.CampaignError, match='not ready'):
        LANES.start_sandbox(item, [], runner, output_root=tmp_path / 'out', sleep=waits.append)
    assert sum(waits) <= LANES.SANDBOX_READY_SECONDS
    assert len([a for a in runner.argvs() if a[:5] == ['docker', 'exec', item.name, 'docker', 'info']]) >= 2


def test_start_sandbox_rejects_a_private_daemon_that_is_not_empty(tmp_path):
    item = lane(tmp_path)
    runner = FakeRunner([(['docker', 'exec', item.name, 'docker', 'volume', 'ls', '-q'], 0, 'leftover\n')])
    with pytest.raises(CAMPAIGN.CampaignError, match='not empty'):
        LANES.start_sandbox(item, [], runner, output_root=tmp_path / 'out', sleep=lambda seconds: None)


def test_teardown_runs_every_step_after_a_failure_and_then_fails_closed(tmp_path):
    item = lane(tmp_path)
    item.repository.mkdir(parents=True)
    runner = FakeRunner([(['*', 'bootstrap_ci_environment.py', '--teardown'], 1, '')])
    with pytest.raises(CAMPAIGN.CampaignError, match='teardown'):
        LANES.teardown_lane(item, '/p', runner)
    argvs = runner.argvs()
    assert ['docker', 'rm', '-f', item.name] in argvs
    assert ['docker', 'volume', 'rm', *item.volumes] in argvs
    assert not item.repository.exists()


def test_teardown_rejects_residue_inside_the_private_daemon(tmp_path):
    item = lane(tmp_path)
    runner = FakeRunner([(['docker', 'exec', item.name, 'docker', 'ps', '-aq'], 0, 'abc\n')])
    with pytest.raises(CAMPAIGN.CampaignError, match='residue'):
        LANES.teardown_lane(item, '/p', runner)
    assert ['docker', 'rm', '-f', item.name] in runner.argvs()


def test_teardown_order_is_stack_then_inner_check_then_sandbox_then_volumes(tmp_path):
    item = lane(tmp_path)
    runner = FakeRunner()
    result = LANES.teardown_lane(item, '/p', runner)
    argvs = runner.argvs()
    stack = next(i for i, a in enumerate(argvs) if 'bootstrap_ci_environment.py' in ' '.join(a))
    inner = argvs.index(['docker', 'exec', item.name, 'docker', 'ps', '-aq'])
    assert stack < inner < argvs.index(['docker', 'rm', '-f', item.name]) < argvs.index(['docker', 'volume', 'rm', *item.volumes])
    assert argvs[stack][:6] == ['docker', 'exec', '-u', '1000:1000', '-w', str(item.repository)]
    assert result['status'] == 'PASS'


def test_host_residue_is_checked_by_campaign_label_and_root_image(tmp_path):
    clean = FakeRunner([(['docker', 'image', 'inspect'], 1, '')])
    assert LANES.check_host_residue(CAMPAIGN_ID, clean) == {'containers': [], 'volumes': [], 'networks': [], 'root_image': False}
    label = f'label={LANES.LANE_LABEL}={CAMPAIGN_ID}'
    assert ['docker', 'ps', '-aq', '--filter', label] in clean.argvs()
    assert ['docker', 'volume', 'ls', '-q', '--filter', label] in clean.argvs()
    dirty = FakeRunner([(['docker', 'volume', 'ls'], 0, 'v1\n'), (['docker', 'image', 'inspect'], 1, '')])
    with pytest.raises(CAMPAIGN.CampaignError, match='residue'):
        LANES.check_host_residue(CAMPAIGN_ID, dirty)
    image = FakeRunner()
    with pytest.raises(CAMPAIGN.CampaignError, match='residue'):
        LANES.check_host_residue(CAMPAIGN_ID, image)
