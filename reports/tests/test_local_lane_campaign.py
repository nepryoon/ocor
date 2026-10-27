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
BOOTSTRAP = sys.modules['bootstrap_ci_environment']

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


# --- per-lane runner inside the sandbox -----------------------------------
# The lane runner mirrors the sealed supervisor's execution body on the lane's
# own stack: exact head, CI bootstrap, the lane's explicit node list proven by
# collection, pytest with JUnit and coverage, mandatory-stack and Kubernetes
# checks, the whole-campaign clock, and a stop request from the orchestrator.

LANE_SELECTION = ['tests/tasks/test_a.py::test_one', f'{M49}::test_slow', HELM]
SECRET = 'lane-generated-password'


def lane_spec(tmp_path, *, selection=None, started=None, head=HEAD, index=1):
    output = tmp_path / 'out'
    output.mkdir(exist_ok=True)
    spec = {'campaign_start': LANE_CLOCK[0] - 10 if started is None else started, 'head': head, 'lane': index,
            'selection': list(LANE_SELECTION if selection is None else selection), 'stop_file': str(output / 'STOP')}
    path = output / 'lane_spec.json'
    path.write_text(json.dumps(spec))
    return path


LANE_CLOCK = [1793000000.0]


class FakeRecorder:
    instances = []

    def __init__(self, repository):
        self.finished = False
        FakeRecorder.instances.append(self)

    def finish(self):
        self.finished = True


def container(name, *, restarts=0, running=True, oom=False):
    return {'Id': f'id-{name}', 'RestartCount': restarts,
            'State': {'StartedAt': 't0', 'Running': running, 'OOMKilled': oom}}


def mandatory_stack(**changes):
    stack = {f'/ocor-bootstrap-s{index}-1': container(f's{index}') for index in range(CAMPAIGN.MANDATORY_CONTAINERS)}
    stack.update(changes)
    return stack


@pytest.fixture
def lane_world(tmp_path, monkeypatch):
    """A lane clone with a generated env file; sealed helpers observed, not rebound in the sealed module's callers."""
    repository = tmp_path / 'repo'
    (repository / 'ocor-runtime').mkdir(parents=True)
    (repository / '.ocor').mkdir()
    (repository / '.ocor/bootstrap.env').write_text(f'OCOR_LOCAL_POSTGRES_PASSWORD={SECRET}\nOTHER=1\n')
    (repository / 'ocor-runtime/.coverage').write_bytes(b'coverage')
    world = {'repository': repository, 'calls': [], 'stacks': [], 'collected': None, 'junit_cases': None,
             'pytest_exit': 0, 'head': HEAD}
    FakeRecorder.instances = []

    def verify_revision(path, head):
        world['calls'].append(('verify_revision', str(path), head))
        if head != world['head']:
            raise CAMPAIGN.CampaignError(f'candidate HEAD mismatch: {world["head"]}')

    def collect_nodeids(directory, selection):
        world['calls'].append(('collect', str(directory), list(selection)))
        return list(selection) if world['collected'] is None else world['collected']

    def inspect_stack():
        return world['stacks'].pop(0) if len(world['stacks']) > 1 else (world['stacks'][0] if world['stacks'] else mandatory_stack())

    def runner(argv, *, cwd=None, env=None, input=None, timeout=600, check=True):
        world['calls'].append(('run', [str(item) for item in argv], dict(env or {})))
        return LANES.CommandResult(0, json.dumps({'status': 'PASS', 'echo': SECRET}))

    def pytest_command(output, selection):
        cases = world['junit_cases'] or [CAMPAIGN.junit_identity(node) for node in selection]
        source = write_junit(tmp_path / 'prepared.xml', cases)
        world['calls'].append(('pytest', list(selection)))
        return [sys.executable, '-c', 'import shutil, sys; shutil.copyfile(sys.argv[1], sys.argv[2]); sys.exit(int(sys.argv[3]))',
                str(source), str(output / 'runtime_junit_post_approval.xml'), str(world['pytest_exit'])]

    monkeypatch.setattr(CAMPAIGN, 'verify_revision', verify_revision)
    monkeypatch.setattr(CAMPAIGN, 'collect_nodeids', collect_nodeids)
    monkeypatch.setattr(CAMPAIGN, 'inspect_stack', inspect_stack)
    monkeypatch.setattr(CAMPAIGN, 'inspect_kubernetes_runtimes', lambda: {})
    monkeypatch.setattr(CAMPAIGN, 'start_health_observer', lambda output, limit: None)
    monkeypatch.setattr(CAMPAIGN, 'finish_health_observer', lambda process, output: None)
    monkeypatch.setattr(BOOTSTRAP, 'SessionRecorder', FakeRecorder)
    monkeypatch.setattr(CAMPAIGN, 'collect_kubernetes_diagnostics', lambda output: output.write_text('diag\n'))
    monkeypatch.setattr(BOOTSTRAP, 'collect_stack_diagnostics', lambda repository, output: output.write_text('stats\n'))
    monkeypatch.setattr(CAMPAIGN.kind_observer, 'start_sampler', lambda pgid, kind_binary=None: None)
    monkeypatch.setattr(CAMPAIGN.kind_observer, 'stop_sampler', lambda thread: None)
    monkeypatch.setattr(LANES, 'lane_pytest_command', pytest_command)
    monkeypatch.setattr(LANES, 'LANE_POLL_SECONDS', 0.01)
    monkeypatch.setattr(LANES.time, 'time', lambda: LANE_CLOCK[0])
    for key in ('OCOR_BOOTSTRAP_ENV', 'OCOR_LIVE_POSTGRES_DSN'):
        monkeypatch.delenv(key, raising=False)
    world['runner'] = runner
    return world


def run_lane(world, spec):
    return LANES.run_lane(spec, repository=world['repository'], runner=world['runner'])


def lane_result(spec):
    return json.loads((spec.parent / 'lane_result.json').read_text())


def test_lane_pytest_command_is_the_sealed_supervisor_command_with_the_explicit_selection(tmp_path):
    command = LANES.lane_pytest_command(tmp_path, LANE_SELECTION)
    assert command[:6] == [sys.executable, '-m', 'pytest', '-v', '--cov=src', '--cov-report=term-missing']
    assert command[6:8] == [f'--cov-report=json:{tmp_path / "runtime_coverage_post_approval.json"}',
                            f'--junitxml={tmp_path / "runtime_junit_post_approval.xml"}']
    assert command[8:] == LANE_SELECTION
    assert not any(item.startswith(('--deselect', '-k', '-m', '--lf', '-x')) for item in command[3:])


@pytest.mark.parametrize('change', [
    {'head': HEAD[:39]}, {'head': HEAD.upper()}, {'selection': []}, {'selection': [HELM, HELM]},
    {'campaign_start': 0}, {'lane': 3}, {'stop_file': ''}])
def test_lane_spec_rejects_incomplete_or_ambiguous_input(tmp_path, change):
    path = lane_spec(tmp_path)
    data = {**json.loads(path.read_text()), **change}
    path.write_text(json.dumps(data))
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.load_lane_spec(path)


def test_lane_service_environment_is_the_ci_environment_of_the_lane_stack(tmp_path):
    (tmp_path / '.ocor').mkdir()
    (tmp_path / '.ocor/bootstrap.env').write_text(f'OCOR_LOCAL_POSTGRES_PASSWORD={SECRET}\n')
    assert LANES.lane_service_environment(tmp_path) == {
        'OCOR_BOOTSTRAP_ENV': str((tmp_path / '.ocor/bootstrap.env').resolve()),
        'OCOR_LIVE_POSTGRES_DSN': f'postgresql://ocor:{SECRET}@127.0.0.1:55433/ocor'}
    (tmp_path / '.ocor/bootstrap.env').write_text('OTHER=1\n')
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.lane_service_environment(tmp_path)


def test_lane_runs_its_exact_selection_on_its_own_stack_and_records_a_pass(lane_world, tmp_path):
    spec = lane_spec(tmp_path)
    assert run_lane(lane_world, spec) == 0
    result = lane_result(spec)
    assert result['status'] == 'PASS' and result['lane'] == 1 and result['candidate_head'] == HEAD
    assert result['counts'] == {'tests': 3, 'failures': 0, 'errors': 0, 'skipped': 0}
    assert result['selected'] == len(LANE_SELECTION) and result['po_decision_required'] is False
    assert result['limit_seconds'] == 5400 and result['campaign_elapsed_seconds'] >= 10
    assert (spec.parent / 'runtime_coverage.data').read_bytes() == b'coverage'
    runs = [call[1] for call in lane_world['calls'] if call[0] == 'run']
    assert [argv[1:] for argv in runs] == [['scripts/bootstrap_ci_environment.py', '--teardown', '--execute'],
                                           ['scripts/bootstrap_ci_environment.py', '--execute', '--timeout', '600']]
    order = [call[0] for call in lane_world['calls']]
    assert order.index('verify_revision') < order.index('run') < order.index('collect') < order.index('pytest')
    assert ('collect', str(lane_world['repository'] / 'ocor-runtime'), LANE_SELECTION) in lane_world['calls']
    assert [call[0] for call in lane_world['calls']].count('verify_revision') == 2
    assert FakeRecorder.instances and FakeRecorder.instances[0].finished
    assert LANES.os.environ['OCOR_LIVE_POSTGRES_DSN'].endswith('@127.0.0.1:55433/ocor')


def assert_lane_failed(spec, match):
    result = lane_result(spec)
    assert result['status'] == 'FAIL' and match in result['error']
    return result


def test_lane_fails_closed_on_a_head_mismatch_before_any_bootstrap(lane_world, tmp_path):
    lane_world['head'] = '0' * 40
    spec = lane_spec(tmp_path)
    assert run_lane(lane_world, spec) == 1
    assert_lane_failed(spec, 'HEAD mismatch')
    assert not [call for call in lane_world['calls'] if call[0] in ('run', 'pytest')]


def test_lane_fails_closed_when_collection_differs_from_its_selection(lane_world, tmp_path):
    lane_world['collected'] = LANE_SELECTION[:-1]
    spec = lane_spec(tmp_path)
    assert run_lane(lane_world, spec) == 1
    assert_lane_failed(spec, 'does not collect exactly')
    assert not [call for call in lane_world['calls'] if call[0] == 'pytest']


def test_lane_requires_exactly_the_mandatory_containers(lane_world, tmp_path):
    stack = mandatory_stack()
    stack.pop(next(iter(stack)))
    lane_world['stacks'] = [stack]
    spec = lane_spec(tmp_path)
    assert run_lane(lane_world, spec) == 1
    assert_lane_failed(spec, f'expected {CAMPAIGN.MANDATORY_CONTAINERS} mandatory containers')


def test_lane_stops_on_a_restarted_service(lane_world, tmp_path):
    name = '/ocor-bootstrap-s0-1'
    lane_world['stacks'] = [mandatory_stack(), mandatory_stack(**{name: container('s0', restarts=1)})]
    lane_world['pytest_exit'] = 0
    spec = lane_spec(tmp_path)
    assert run_lane(lane_world, spec) == 1
    assert_lane_failed(spec, 'service restarted')
    assert (spec.parent / 'docker-stats.log').exists()


def test_lane_stops_when_the_orchestrator_requests_it(lane_world, tmp_path):
    spec = lane_spec(tmp_path)
    (spec.parent / 'STOP').write_text('lane 2 failed\n')
    assert run_lane(lane_world, spec) == 1
    assert_lane_failed(spec, 'stopped by the orchestrator')


def test_lane_shares_the_whole_campaign_clock(lane_world, tmp_path):
    spec = lane_spec(tmp_path, started=LANE_CLOCK[0] - 5400)
    assert run_lane(lane_world, spec) == 1
    assert_lane_failed(spec, '90-minute campaign limit reached')
    assert not [call for call in lane_world['calls'] if call[0] in ('run', 'pytest')]


def test_lane_reports_the_notification_threshold_on_the_whole_campaign_clock(lane_world, tmp_path):
    spec = lane_spec(tmp_path, started=LANE_CLOCK[0] - 3601)
    assert run_lane(lane_world, spec) == 0
    assert lane_result(spec)['po_decision_required'] is True


def test_lane_rejects_a_pytest_failure_exit(lane_world, tmp_path):
    lane_world['pytest_exit'] = 1
    spec = lane_spec(tmp_path)
    assert run_lane(lane_world, spec) == 1
    assert_lane_failed(spec, 'pytest exit code 1')


def test_lane_rejects_a_junit_that_differs_from_its_selection(lane_world, tmp_path):
    lane_world['junit_cases'] = [CAMPAIGN.junit_identity(node) for node in LANE_SELECTION[:-1]]
    spec = lane_spec(tmp_path)
    assert run_lane(lane_world, spec) == 1
    assert_lane_failed(spec, 'lane JUnit differs from its selection')


def test_lane_redacts_generated_credentials_from_its_logs(lane_world, tmp_path):
    spec = lane_spec(tmp_path)
    assert run_lane(lane_world, spec) == 0
    assert (spec.parent / 'bootstrap.log').read_text().count('[REDACTED]') == 2
    for path in spec.parent.iterdir():
        if path.is_file():
            assert SECRET not in path.read_text(errors='replace'), path.name


def test_lane_cli_runs_the_spec_and_returns_its_status(lane_world, tmp_path, monkeypatch):
    spec = lane_spec(tmp_path)
    seen = {}
    monkeypatch.setattr(LANES, 'run_lane', lambda path: seen.setdefault('spec', path) and 0)
    assert LANES.main(['--run-lane', str(spec)]) == 0
    assert seen['spec'] == spec.resolve()


# --- --execute orchestration on the host ------------------------------------
# Memory admission first (SERIAL fallback recorded, nothing provisioned), the
# exact head and the collection on the host checkout, the deterministic
# partition, both lanes provisioned and started, then launched in parallel with
# only HOME and PATH. The host keeps the whole-campaign clock; the first failure
# of either lane stops the other. The union must be exact, coverage is combined
# onto the host checkout, and both lanes are always torn down with zero residue.

class FakeProcess:
    """A lane runner process: exit code after ``polls`` polls, or never if None."""

    def __init__(self, returncode=0, polls=1):
        self.returncode, self.polls, self.killed = returncode, polls, False

    def poll(self):
        if self.killed:
            return -9
        if self.polls is None:
            return None
        if self.polls > 0:
            self.polls -= 1
            return None
        return self.returncode

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.poll()


class FakeClock:
    def __init__(self, start=LANE_CLOCK[0], step=5.0):
        self.now, self.step = start, step

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += self.step


def two_lanes(tmp_path):
    lanes = [lane(tmp_path, 1), lane(tmp_path, 2)]
    for item in lanes:
        item.output.mkdir(parents=True)
    return lanes


def test_lane_spec_is_written_in_the_lane_output_and_is_exact(tmp_path):
    item = two_lanes(tmp_path)[0]
    path = LANES.write_lane_spec(item, HEAD, LANE_SELECTION, LANE_CLOCK[0])
    assert path == item.output / 'lane_spec.json'
    spec = LANES.load_lane_spec(path)
    assert spec == {'campaign_start': LANE_CLOCK[0], 'head': HEAD, 'lane': 1, 'selection': LANE_SELECTION,
                    'stop_file': str(item.output / 'STOP')}
    assert path.read_text() == json.dumps(spec, indent=2, sort_keys=True) + '\n'


def test_lane_run_argv_runs_the_lane_runner_in_its_sandbox_with_only_home_and_path(tmp_path):
    item = two_lanes(tmp_path)[0]
    spec = item.output / 'lane_spec.json'
    argv = LANES.lane_run_argv(item, '/p/bin:/usr/bin', spec)
    python = str(item.repository / 'ocor-runtime/.venv/bin/python')
    assert argv == LANES.sandbox_exec_argv(item, '/p/bin:/usr/bin', [python, 'scripts/run_local_lane_campaign.py', '--run-lane', str(spec)], {})
    assert [argv[i + 1].split('=', 1)[0] for i, value in enumerate(argv) if value == '-e'] == ['HOME', 'PATH']


def test_supervision_of_two_passing_lanes_writes_no_stop_request(tmp_path):
    lanes, clock = two_lanes(tmp_path), FakeClock()
    report = LANES.supervise_lanes({1: FakeProcess(0, 2), 2: FakeProcess(0, 3)}, lanes, clock.now - 10, clock=clock, sleep=clock.sleep)
    assert report == {'returncodes': {1: 0, 2: 0}, 'first_failure': None, 'stop_reason': None, 'killed_after_grace': [],
                      'po_decision_required': False}
    assert not any((item.output / 'STOP').exists() for item in lanes)


def test_first_failure_of_a_lane_stops_the_other_and_waits_for_it(tmp_path):
    lanes, clock = two_lanes(tmp_path), FakeClock()
    other = FakeProcess(1, 4)
    report = LANES.supervise_lanes({1: other, 2: FakeProcess(1, 1)}, lanes, clock.now, clock=clock, sleep=clock.sleep)
    assert report['first_failure'] == 2 and report['returncodes'] == {1: 1, 2: 1}
    assert 'lane 2' in (lanes[0].output / 'STOP').read_text()
    assert not (lanes[1].output / 'STOP').exists()
    assert other.poll() == 1 and not other.killed and report['killed_after_grace'] == []


def test_host_clock_at_the_limit_stops_both_lanes(tmp_path):
    lanes, clock = two_lanes(tmp_path), FakeClock()
    report = LANES.supervise_lanes({1: FakeProcess(1, 3), 2: FakeProcess(1, 3)}, lanes, clock.now - 5400, clock=clock, sleep=clock.sleep)
    assert '90-minute campaign limit reached' in report['stop_reason']
    assert all('90-minute' in (item.output / 'STOP').read_text() for item in lanes)


def test_host_clock_reports_the_notification_threshold(tmp_path):
    lanes, clock = two_lanes(tmp_path), FakeClock()
    report = LANES.supervise_lanes({1: FakeProcess(0, 1), 2: FakeProcess(0, 1)}, lanes, clock.now - 3601, clock=clock, sleep=clock.sleep)
    assert report['po_decision_required'] is True and report['stop_reason'] is None


def test_a_lane_that_ignores_the_stop_request_is_killed_after_the_grace(tmp_path):
    lanes, clock = two_lanes(tmp_path), FakeClock(step=60.0)
    stuck = FakeProcess(0, None)
    report = LANES.supervise_lanes({1: stuck, 2: FakeProcess(1, 0)}, lanes, clock.now, clock=clock, sleep=clock.sleep)
    assert stuck.killed and report['killed_after_grace'] == [1] and report['first_failure'] == 2
    assert clock.now - LANE_CLOCK[0] >= LANES.STOP_GRACE_SECONDS


def test_stop_grace_covers_the_longest_uninterruptible_lane_step():
    assert LANES.STOP_GRACE_SECONDS >= LANES.PROVISION_TIMEOUT_SECONDS + 60
    assert LANES.STOP_GRACE_SECONDS < LANES.FULL_SUITE_LIMIT_SECONDS


def write_lane_result(item, part, **changes):
    result = {'status': 'PASS', 'lane': item.index, 'candidate_head': HEAD, 'selected': len(part),
              'selected_sha256': CAMPAIGN.collection_digest(part), 'lane_duration_seconds': 12.5,
              'campaign_elapsed_seconds': 20.0, 'counts': {'tests': len(part), 'failures': 0, 'errors': 0, 'skipped': 0},
              'po_decision_required': False, **changes}
    (item.output / 'lane_result.json').write_text(json.dumps(result))
    return result


def test_lane_results_must_both_pass_for_their_exact_selection_and_head(tmp_path):
    lanes = two_lanes(tmp_path)
    parts = LANES.lane_partition(nodes(), weights())
    for item, part in zip(lanes, parts):
        write_lane_result(item, part)
    results = LANES.read_lane_results(lanes, HEAD, parts)
    assert [result['lane'] for result in results] == [1, 2]


@pytest.mark.parametrize('change, match', [
    ({'status': 'FAIL', 'error': 'pytest exit code 1'}, 'pytest exit code 1'),
    ({'candidate_head': '0' * 40}, 'head'),
    ({'lane': 1}, 'lane'),
    ({'selected_sha256': '0' * 64}, 'selection'),
])
def test_lane_results_reject_a_failure_another_head_lane_or_selection(tmp_path, change, match):
    lanes = two_lanes(tmp_path)
    parts = LANES.lane_partition(nodes(), weights())
    write_lane_result(lanes[0], parts[0])
    write_lane_result(lanes[1], parts[1], **change)
    with pytest.raises(CAMPAIGN.CampaignError, match=match):
        LANES.read_lane_results(lanes, HEAD, parts)


def test_lane_results_reject_an_absent_result(tmp_path):
    lanes = two_lanes(tmp_path)
    parts = LANES.lane_partition(nodes(), weights())
    write_lane_result(lanes[0], parts[0])
    with pytest.raises(CAMPAIGN.CampaignError, match='lane 2'):
        LANES.read_lane_results(lanes, HEAD, parts)


def test_merged_junit_keeps_every_lane_suite_and_enforces_required_modules(tmp_path):
    lanes = two_lanes(tmp_path)
    parts = LANES.lane_partition(nodes(), weights())
    for item, part in zip(lanes, parts):
        write_junit(item.output / LANES.LANE_JUNIT, [CAMPAIGN.junit_identity(node) for node in part])
    merged = tmp_path / 'merged.xml'
    counts = LANES.merge_lane_junit(lanes, merged, required_modules=['test_ocor_dev_0049'])
    assert counts == {'tests': len(nodes()), 'failures': 0, 'errors': 0, 'skipped': 0}
    assert [suite.get('name') for suite in ET.parse(merged).getroot().iter('testsuite')] == ['pytest-lane-1', 'pytest-lane-2']
    with pytest.raises(CAMPAIGN.CampaignError, match='required guard'):
        LANES.merge_lane_junit(lanes, tmp_path / 'other.xml', required_modules=['test_ocor_dev_0048'])


def test_coverage_is_combined_onto_the_host_checkout_with_both_lane_paths_remapped(tmp_path):
    lanes = two_lanes(tmp_path)
    for item in lanes:
        (item.output / 'runtime_coverage.data').write_bytes(b'data-%d' % item.index)
    suite, output = tmp_path / 'host/ocor-runtime', tmp_path / 'campaign'
    output.mkdir()
    runner = FakeRunner()
    LANES.combine_lane_coverage(suite, lanes, output, runner)
    rcfile = output / 'lane_coverage.rc'
    text = rcfile.read_text()
    sources = [line.strip() for line in text.split('source =', 1)[1].splitlines() if line.strip()]
    assert sources == [str(suite / 'src'), *(str(item.repository / 'ocor-runtime/src') for item in lanes)]
    combine, report = runner.calls
    assert combine['argv'][1:4] == ['-m', 'coverage', 'combine'] and f'--rcfile={rcfile}' in combine['argv']
    assert combine['argv'][-2:] == [str(output / 'runtime_coverage.lane-1'), str(output / 'runtime_coverage.lane-2')]
    assert report['argv'][1:4] == ['-m', 'coverage', 'json'] and str(output / 'runtime_coverage_post_approval.json') in report['argv']
    assert combine['cwd'] == report['cwd'] == str(suite)
    assert (output / 'runtime_coverage.lane-2').read_bytes() == b'data-2'


def test_coverage_combination_fails_closed(tmp_path):
    lanes = two_lanes(tmp_path)
    for item in lanes:
        (item.output / 'runtime_coverage.data').write_bytes(b'x')
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.combine_lane_coverage(tmp_path, lanes, tmp_path, FakeRunner([(['*', 'coverage combine'], 1, '')]))


def power_supplies(tmp_path, **supplies):
    root = tmp_path / 'power'
    for name, values in supplies.items():
        (root / name).mkdir(parents=True)
        for key, value in values.items():
            (root / name / key).write_text(value + '\n')
    return root


def test_power_reading_reports_mains_battery_or_not_executed(tmp_path):
    mains = power_supplies(tmp_path / 'a', AC={'type': 'Mains', 'online': '1'}, BAT0={'type': 'Battery', 'status': 'Charging'})
    assert LANES.power_reading(mains)['source'] == 'MAINS'
    battery = power_supplies(tmp_path / 'b', AC={'type': 'Mains', 'online': '0'}, BAT0={'type': 'Battery', 'status': 'Discharging'})
    assert LANES.power_reading(battery)['source'] == 'BATTERY'
    assert LANES.power_reading(tmp_path / 'absent')['source'] == 'NOT_EXECUTED'
    reading = LANES.power_reading(mains)
    assert reading['supplies']['AC'] == {'online': '1', 'type': 'Mains'} and 'read_at' in reading


@pytest.fixture
def host_world(tmp_path, monkeypatch):
    """The host side of --execute with lane provisioning, sandboxes and lane processes observed."""
    world = {'calls': [], 'lane_exit': {1: 0, 2: 0}, 'fail_provision': None, 'collected': nodes(), 'head': HEAD}
    source = tmp_path / 'host'
    (source / 'ocor-runtime').mkdir(parents=True)
    world['source'] = source

    def verify_revision(path, head):
        world['calls'].append(('verify_revision', str(path)))
        if head != world['head']:
            raise CAMPAIGN.CampaignError(f'candidate HEAD mismatch: {world["head"]}')

    def collect_nodeids(directory, selection):
        world['calls'].append(('collect', str(directory), list(selection)))
        return list(world['collected'])

    def provision_lane(item, source_path, head, runner, env):
        world['calls'].append(('provision', item.index))
        if world['fail_provision'] == item.index:
            raise CAMPAIGN.CampaignError(f'lane {item.index} provisioning failed')
        item.output.mkdir(parents=True)
        item.repository.mkdir(parents=True)
        return {'lane': item.index, 'head': head, 'repository': str(item.repository)}

    def start_sandbox(item, mounts, runner, *, output_root, sleep=None):
        world['calls'].append(('sandbox', item.index))
        return {'lane': item.index, 'sandbox': item.name}

    def launcher(argv, log):
        index = int(argv[argv.index('--run-lane') + 1].split('/lane-')[-1].split('/')[0])
        world['calls'].append(('launch', index))
        item = next(entry for entry in world['lanes'] if entry.index == index)
        spec = LANES.load_lane_spec(item.output / 'lane_spec.json')
        if world['lane_exit'][index] == 0:
            write_junit(item.output / LANES.LANE_JUNIT, [CAMPAIGN.junit_identity(node) for node in spec['selection']])
            (item.output / 'runtime_coverage.data').write_bytes(b'cov')
            write_lane_result(item, spec['selection'])
        else:
            write_lane_result(item, spec['selection'], status='FAIL', error=f'lane {index} pytest exit code 1')
        log.write_text('lane log\n')
        return FakeProcess(world['lane_exit'][index], 1)

    def teardown_lane(item, path, runner):
        world['calls'].append(('teardown', item.index))
        return {'lane': item.index, 'status': 'PASS'}

    real_lane = LANES.Lane

    def lane_factory(*args, **kwargs):
        item = real_lane(*args, **kwargs)
        world.setdefault('lanes', []).append(item)
        return item

    monkeypatch.setattr(CAMPAIGN, 'verify_revision', verify_revision)
    monkeypatch.setattr(CAMPAIGN, 'collect_nodeids', collect_nodeids)
    monkeypatch.setattr(LANES, 'load_weights', weights)
    monkeypatch.setattr(LANES, 'provision_lane', provision_lane)
    monkeypatch.setattr(LANES, 'start_sandbox', start_sandbox)
    monkeypatch.setattr(LANES, 'ensure_root_image', lambda runner, links: world['calls'].append(('root_image',)))
    monkeypatch.setattr(LANES, 'host_usr_links', lambda: {'bin': 'usr/bin'})
    monkeypatch.setattr(LANES, 'teardown_lane', teardown_lane)
    monkeypatch.setattr(LANES, 'remove_root_image', lambda runner: world['calls'].append(('remove_root_image',)))
    monkeypatch.setattr(LANES, 'check_host_residue', lambda campaign_name, runner: world['calls'].append(('residue',)) or {})
    monkeypatch.setattr(LANES, 'combine_lane_coverage', lambda suite, lanes, output, runner: world['calls'].append(('coverage', str(suite))))
    monkeypatch.setattr(LANES, 'tool_mounts', lambda paths, home: [])
    monkeypatch.setattr(LANES, 'Lane', lane_factory)
    monkeypatch.setattr(LANES, 'SUPERVISE_POLL_SECONDS', 0)
    world['launcher'] = launcher
    world['meminfo'] = tmp_path / 'meminfo'
    world['meminfo'].write_text(meminfo(31743008, 26000000))
    world['power'] = power_supplies(tmp_path, AC={'type': 'Mains', 'online': '1'})
    world['work'] = tmp_path / 'work'
    return world


def execute(world, selection=('tests/',)):
    return LANES.execute_campaign(world['work'], HEAD, [Path('/home/luca/.ocor-codex/impl-env/x/bin')], list(selection),
                                  source=world['source'], runner=FakeRunner(), launcher=world['launcher'],
                                  meminfo_path=world['meminfo'], power_root=world['power'])


def stored_result(world):
    return json.loads((world['work'] / 'campaign_result.json').read_text())


M48 = 'tests/tasks/test_ocor_dev_0048.py::test_guard'


def test_execute_runs_both_lanes_in_parallel_and_records_an_exact_pass(host_world):
    host_world['collected'] = [*nodes(), M48]
    result = execute(host_world)
    assert result['status'] == 'PASS' and result == stored_result(host_world)
    assert result['mode'] == 'TWO_LANE' and result['selection_scope'] == 'FULL_SUITE' and result['qualifying_scope'] is True
    assert result['head'] == HEAD and result['memory']['mode'] == 'TWO_LANE'
    collected = host_world['collected']
    assert result['collection']['collected'] == len(collected)
    assert result['collection']['collected_sha256'] == CAMPAIGN.collection_digest(collected)
    assert result['union'] == {'collected': len(collected), 'executed': len(collected), 'missing': [], 'duplicated': [], 'unexpected': [],
                               'lanes': result['collection']['lane_cases']}
    assert result['counts'] == {'tests': len(collected), 'failures': 0, 'errors': 0, 'skipped': 0}
    assert result['required_modules'] == ['test_ocor_dev_0048', 'test_ocor_dev_0049']
    assert result['power_start']['source'] == result['power_end']['source'] == 'MAINS'
    assert result['limit_seconds'] == 5400 and result['threshold_seconds'] == 3600
    assert isinstance(result['total_duration_seconds'], float) and result['po_decision_required'] is False
    assert [entry['lane'] for entry in result['lanes']] == [1, 2]
    assert all('provisioning_seconds' in entry and entry['result']['status'] == 'PASS' for entry in result['lanes'])
    calls = [call[0] for call in host_world['calls']]
    assert calls.index('verify_revision') < calls.index('collect') < calls.index('root_image') < calls.index('provision')
    launches = [i for i, call in enumerate(calls) if call == 'launch']
    assert len(launches) == 2 and max(i for i, call in enumerate(calls) if call in ('provision', 'sandbox')) < launches[0]
    assert launches[1] == launches[0] + 1
    assert calls.index('coverage') > launches[1]
    assert calls.count('teardown') == 2 and calls.index('teardown') > calls.index('coverage')
    assert calls.index('remove_root_image') < calls.index('residue') and calls[-1] == 'residue'
    assert calls.count('verify_revision') == 2
    assert ('collect', str(host_world['source'] / 'ocor-runtime'), ['tests/']) in host_world['calls']


def test_execute_full_suite_requires_the_sealed_supervisor_guards(host_world):
    result = execute(host_world)
    assert result['status'] == 'FAIL' and 'required guard' in result['error']
    assert [call[0] for call in host_world['calls']].count('teardown') == 2


def test_execute_with_an_explicit_selection_is_marked_non_qualifying(host_world):
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'PASS' and result['selection_scope'] == 'EXPLICIT_NON_QUALIFYING'
    assert result['qualifying_scope'] is False and result['required_modules'] == []


def test_execute_below_the_memory_threshold_records_the_serial_fallback_and_provisions_nothing(host_world):
    host_world['meminfo'].write_text(meminfo(31743008, 1000))
    result = execute(host_world)
    assert result['status'] == 'SERIAL_FALLBACK' and result['mode'] == 'SERIAL' and result['memory']['mode'] == 'SERIAL'
    assert 'run_qualifying_campaign.py' in result['next_action']
    assert not [call for call in host_world['calls'] if call[0] in ('provision', 'sandbox', 'launch', 'root_image')]
    assert stored_result(host_world) == result


def test_execute_fails_closed_on_a_host_head_mismatch_before_provisioning(host_world):
    host_world['head'] = '0' * 40
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL' and 'HEAD mismatch' in result['error']
    assert not [call for call in host_world['calls'] if call[0] in ('provision', 'launch')]


def test_execute_records_the_failing_lane_and_still_tears_down_both(host_world):
    host_world['lane_exit'][2] = 1
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL' and 'lane 2' in result['error']
    assert result['supervision']['first_failure'] == 2
    calls = [call[0] for call in host_world['calls']]
    assert calls.count('teardown') == 2 and 'coverage' not in calls and calls[-1] == 'residue'


def test_execute_tears_down_both_lanes_when_provisioning_fails(host_world):
    host_world['fail_provision'] = 2
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL' and 'provisioning failed' in result['error']
    calls = [call[0] for call in host_world['calls']]
    assert 'launch' not in calls and calls.count('teardown') == 2 and calls[-1] == 'residue'


def test_execute_rejects_a_union_that_differs_from_the_collection(host_world, monkeypatch):
    monkeypatch.setattr(LANES, 'lane_partition', lambda collected, weights_map: [collected[:3], collected[4:]])
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL' and 'missing' in result['error']


@pytest.mark.parametrize('argv', [
    ['--execute', '/tmp/w'],
    ['--execute', '/tmp/w', '--expected-head', HEAD],
    ['--execute', '/tmp/w', '--tool-bin', '/x'],
])
def test_execute_cli_requires_the_head_and_the_locked_tools(argv):
    with pytest.raises(SystemExit):
        LANES.main(argv)


def test_execute_cli_passes_the_selection_and_returns_the_status(monkeypatch, tmp_path):
    seen = {}

    def fake(work, head, tool_bins, selection, **kwargs):
        seen.update(work=work, head=head, tool_bins=tool_bins, selection=selection)
        return {'status': 'SERIAL_FALLBACK'}
    monkeypatch.setattr(LANES, 'execute_campaign', fake)
    assert LANES.main(['--execute', str(tmp_path / 'w'), '--expected-head', HEAD, '--tool-bin', str(tmp_path)]) == 3
    assert seen['selection'] == ['tests/'] and seen['head'] == HEAD
    monkeypatch.setattr(LANES, 'execute_campaign', lambda *a, **k: {'status': 'PASS'})
    assert LANES.main(['--execute', str(tmp_path / 'w'), '--expected-head', HEAD, '--tool-bin', str(tmp_path),
                       '--select', 'tests/a.py::t', '--select', 'tests/b.py::t']) == 0
    monkeypatch.setattr(LANES, 'execute_campaign', lambda *a, **k: {'status': 'FAIL'})
    assert LANES.main(['--execute', str(tmp_path / 'w'), '--expected-head', HEAD, '--tool-bin', str(tmp_path)]) == 1
