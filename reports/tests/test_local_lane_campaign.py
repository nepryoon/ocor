"""RED-first controls for the local full-suite lane orchestrator (OCOR-DEV-REM-0037, OCOR-DEV-REM-0056).

PO LOCAL-SUITE-SPLIT (2026-10-25) point 4 and LOCAL-SUITE-SPLIT-REACTIVATION
(2026-10-26) point 5: a deterministic partition computed from measured per-case
times, every collected case exactly once, and an exact JUnit union with zero
skips (missing, duplicated and extra cases are rejected). Memory admission
falls back to the serial suite below the measured start threshold.

PO LOCAL-SUITE-FOUR-LANES (2026-11-07): four lanes, admitted in three levels
(FOUR_LANE, TWO_LANE with the unchanged threshold, SERIAL); partition, union,
supervision, results and teardown work on the lane count admitted at start.

PO TMP-RESIDUI-CAMPAGNA (2026-11-11): before any lane checkout, a work directory
on the /tmp user quota is refused when the measured lane budget does not fit;
SIGTERM and SIGHUP remove the script-created trees and leave the result file.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import signal
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
CACHE_SPEC = importlib.util.spec_from_file_location('local_lane_image_cache', ROOT / 'scripts/local_lane_image_cache.py')
assert CACHE_SPEC is not None and CACHE_SPEC.loader is not None
IMAGE_CACHE = importlib.util.module_from_spec(CACHE_SPEC)
sys.modules['local_lane_image_cache'] = IMAGE_CACHE
CACHE_SPEC.loader.exec_module(IMAGE_CACHE)
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

ADMITTED = (4, 2)


def test_the_orchestrator_runs_four_lanes_and_admits_only_four_or_two():
    assert LANES.LANE_COUNT == 4
    assert LANES.ADMITTED_LANE_COUNTS == (4, 2)


@pytest.mark.parametrize('count', ADMITTED)
def test_partition_places_every_collected_case_exactly_once(count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    flat = [node for part in parts for node in part]
    assert len(parts) == count and all(parts)
    assert sorted(flat) == sorted(nodes()) and len(flat) == len(set(flat))


def test_partition_defaults_to_four_lanes():
    assert LANES.lane_partition(nodes(), weights()) == LANES.lane_partition(nodes(), weights(), lanes=4)
    assert len(LANES.lane_partition(nodes(), weights())) == 4


@pytest.mark.parametrize('count', ADMITTED)
def test_partition_is_deterministic_and_independent_of_weight_order(count):
    reordered = dict(reversed(list(weights().items())))
    first = LANES.lane_partition(nodes(), weights(), lanes=count)
    assert LANES.lane_partition(list(nodes()), reordered, lanes=count) == first
    assert LANES.lane_partition(nodes(), weights(), lanes=count) == first


@pytest.mark.parametrize('count', ADMITTED)
def test_partition_keeps_collection_order_inside_each_lane(count):
    order = {node: index for index, node in enumerate(nodes())}
    for part in LANES.lane_partition(nodes(), weights(), lanes=count):
        assert part == sorted(part, key=order.__getitem__)


@pytest.mark.parametrize('count', ADMITTED)
def test_partition_keeps_every_other_module_whole(count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    for module in ('tests/tasks/test_a.py', 'tests/tasks/test_b.py', 'tests/tasks/test_c.py'):
        holders = [index for index, part in enumerate(parts) if any(node.startswith(module + '::') for node in part)]
        assert len(holders) == 1, module


@pytest.mark.parametrize('count', ADMITTED)
def test_partition_distributes_the_0049_module_across_every_lane(count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    assert all(any(node.startswith(M49 + '::') for node in part) for part in parts)


@pytest.mark.parametrize('count', ADMITTED)
def test_partition_balances_lanes_within_the_largest_unit(count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    loads = LANES.lane_loads(parts, weights())
    assert max(loads) - min(loads) <= max(LANES.case_weight(node, weights()) for node in nodes())
    # Helm (400 s) and the slow 0049 case (300 s) must not share a lane.
    assert not any(HELM in part and f'{M49}::test_slow' in part for part in parts)


def test_four_way_partition_separates_the_three_heaviest_units():
    parts = LANES.lane_partition(nodes(), weights(), lanes=4)
    heavy = [HELM, f'{M49}::test_slow', f'{M49}::test_mid']
    holders = [next(index for index, part in enumerate(parts) if node in part) for node in heavy]
    assert len(set(holders)) == 3


def test_unmeasured_cases_use_the_declared_default_weight():
    assert LANES.case_weight('tests/tasks/test_c.py::TestK::test_one', weights()) == LANES.DEFAULT_CASE_SECONDS
    assert LANES.case_weight(f'{M49}::test_slow', weights()) == 300.0


@pytest.mark.parametrize('count', ADMITTED)
@pytest.mark.parametrize('bad', [
    [],
    ['tests/tasks/test_a.py::test_one'],
    ['tests/tasks/test_a.py::test_one', 'tests/tasks/test_a.py::test_one'],
    ['tests/tasks/test_a.py::test_one', 'tests/tasks/test_a.py::test_two'],
])
def test_partition_rejects_empty_duplicate_or_unsplittable_collections(bad, count):
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.lane_partition(bad, weights(), lanes=count)


def test_four_way_partition_rejects_fewer_units_than_lanes():
    three_units = ['tests/tasks/test_a.py::test_one', 'tests/tasks/test_b.py::test_one', 'tests/tasks/test_c.py::test_one']
    assert len(LANES.lane_partition(three_units, {}, lanes=2)) == 2
    with pytest.raises(CAMPAIGN.CampaignError, match='nonempty'):
        LANES.lane_partition(three_units, {}, lanes=4)


def test_partition_rejects_ambiguous_junit_identities():
    with pytest.raises(CAMPAIGN.CampaignError, match='JUnit'):
        LANES.lane_partition(['tests/x.py::test_a', 'tests/x/py::test_a', 'tests/y.py::test_b'], {})


@pytest.mark.parametrize('lanes', [0, 1, 3, 5, 8, -4, True])
def test_partition_supports_only_the_admitted_lane_counts(lanes):
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.lane_partition(nodes(), weights(), lanes=lanes)


@pytest.mark.parametrize('count', ADMITTED)
def test_partition_digest_changes_with_assignment(count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    swapped = [parts[1], parts[0], *parts[2:]]
    assert CAMPAIGN.partition_digest(parts) != CAMPAIGN.partition_digest(swapped)


# --- exact union ----------------------------------------------------------

@pytest.mark.parametrize('count', ADMITTED)
def test_union_accepts_exactly_the_collected_cases(tmp_path, count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    summary = LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts), lanes=count)
    assert summary == {'collected': len(nodes()), 'executed': len(nodes()), 'missing': [], 'duplicated': [], 'unexpected': [],
                       'lanes': [len(part) for part in parts]}


def test_union_defaults_to_four_lanes(tmp_path):
    parts = LANES.lane_partition(nodes(), weights(), lanes=4)
    assert LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts))['lanes'] == [len(part) for part in parts]
    (tmp_path / 'two').mkdir()
    two = lane_junits(tmp_path / 'two', LANES.lane_partition(nodes(), weights(), lanes=2))
    with pytest.raises(CAMPAIGN.CampaignError, match='expected 4 lane JUnit files'):
        LANES.check_exact_union(nodes(), two)


@pytest.mark.parametrize('count', ADMITTED)
def test_union_rejects_a_missing_case(tmp_path, count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    # drop from a lane that keeps other cases, so the rejection is for the missing case
    big = max(range(len(parts)), key=lambda index: len(parts[index]))
    parts[big] = parts[big][1:]
    with pytest.raises(CAMPAIGN.CampaignError, match='missing'):
        LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts), lanes=count)


@pytest.mark.parametrize('count', ADMITTED)
def test_union_rejects_a_duplicated_case(tmp_path, count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    parts[-1] = parts[-1] + [parts[0][0]]
    with pytest.raises(CAMPAIGN.CampaignError, match='duplicated'):
        LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts), lanes=count)


@pytest.mark.parametrize('count', ADMITTED)
def test_union_rejects_an_extra_case(tmp_path, count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    parts[-1] = parts[-1] + ['tests/tasks/test_z.py::test_extra']
    with pytest.raises(CAMPAIGN.CampaignError, match='unexpected'):
        LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts), lanes=count)


@pytest.mark.parametrize('count', ADMITTED)
def test_union_rejects_a_skipped_case(tmp_path, count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    cases = [CAMPAIGN.junit_identity(node) for node in parts[0]]
    paths = lane_junits(tmp_path, parts)
    write_junit(paths[0], cases, skipped={cases[0]})
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.check_exact_union(nodes(), paths, lanes=count)


@pytest.mark.parametrize('count', ADMITTED)
def test_union_rejects_a_failed_case(tmp_path, count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    cases = [CAMPAIGN.junit_identity(node) for node in parts[-1]]
    paths = lane_junits(tmp_path, parts)
    write_junit(paths[-1], cases, failed={cases[-1]})
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.check_exact_union(nodes(), paths, lanes=count)


@pytest.mark.parametrize('count', ADMITTED)
def test_union_rejects_a_missing_lane(tmp_path, count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    with pytest.raises(CAMPAIGN.CampaignError, match=f'expected {count} lane JUnit files'):
        LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts)[:-1], lanes=count)


def test_union_of_four_lanes_rejects_any_single_absent_lane(tmp_path):
    parts = LANES.lane_partition(nodes(), weights(), lanes=4)
    paths = lane_junits(tmp_path, parts)
    for absent in range(4):
        with pytest.raises(CAMPAIGN.CampaignError, match='expected 4 lane JUnit files'):
            LANES.check_exact_union(nodes(), paths[:absent] + paths[absent + 1:], lanes=4)


@pytest.mark.parametrize('lanes', [0, 1, 3, 5])
def test_union_rejects_a_lane_count_that_is_not_admitted(tmp_path, lanes):
    parts = LANES.lane_partition(nodes(), weights(), lanes=4)
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.check_exact_union(nodes(), lane_junits(tmp_path, parts), lanes=lanes)


@pytest.mark.parametrize('count', ADMITTED)
def test_union_rejects_an_absent_junit(tmp_path, count):
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    paths = lane_junits(tmp_path, parts)
    paths[-1].unlink()
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.check_exact_union(nodes(), paths, lanes=count)


# --- memory admission -----------------------------------------------------

def meminfo(total_kib, available_kib):
    return f'MemTotal:       {total_kib} kB\nMemFree:        1 kB\nMemAvailable:   {available_kib} kB\n'


def test_memory_admission_starts_two_lanes_at_or_above_the_threshold():
    threshold_kib = int(LANES.TWO_LANE_START_THRESHOLD_MIB * 1024)
    assert LANES.memory_admission(meminfo(31743008, threshold_kib + 1024))['mode'] == 'TWO_LANE'
    assert LANES.memory_admission(meminfo(31743008, threshold_kib + 1))['mode'] == 'TWO_LANE'
    assert LANES.memory_admission(meminfo(31743008, threshold_kib + 1))['lanes'] == 2


def test_memory_admission_falls_back_to_serial_below_the_threshold():
    threshold_kib = int(LANES.TWO_LANE_START_THRESHOLD_MIB * 1024)
    decision = LANES.memory_admission(meminfo(31743008, threshold_kib - 1))
    assert decision['mode'] == 'SERIAL' and decision['lanes'] == 1
    assert decision['mem_available_kib'] == threshold_kib - 1 and decision['threshold_mib'] == LANES.TWO_LANE_START_THRESHOLD_MIB


def test_memory_admission_starts_four_lanes_at_or_above_the_four_lane_threshold():
    four_kib = LANES.FOUR_LANE_START_THRESHOLD_MIB * 1024
    for available in (int(four_kib) + 1, int(four_kib) + 1024, 57000000):
        decision = LANES.memory_admission(meminfo(64199664, available))
        assert decision['mode'] == 'FOUR_LANE' and decision['lanes'] == 4, available
        assert decision['threshold_mib'] == LANES.FOUR_LANE_START_THRESHOLD_MIB


def test_memory_admission_falls_back_to_two_lanes_just_below_the_four_lane_threshold():
    four_kib = LANES.FOUR_LANE_START_THRESHOLD_MIB * 1024
    for available in (int(four_kib) - 1, int(LANES.TWO_LANE_START_THRESHOLD_MIB * 1024) + 1, 26000000):
        decision = LANES.memory_admission(meminfo(64199664, available))
        assert decision['mode'] == 'TWO_LANE' and decision['lanes'] == 2, available
        assert decision['threshold_mib'] == LANES.TWO_LANE_START_THRESHOLD_MIB
        assert 'below the four-lane threshold' in decision['reason']


def test_memory_admission_boundaries_are_inclusive_at_each_level():
    exact_four = LANES.memory_admission(f'MemTotal: 64199664 kB\nMemAvailable: {26297549} kB\n')
    assert exact_four['mode'] == 'FOUR_LANE'
    assert LANES.memory_admission('MemTotal: 64199664 kB\nMemAvailable: 26297548 kB\n')['mode'] == 'TWO_LANE'
    assert LANES.memory_admission('MemTotal: 64199664 kB\nMemAvailable: 14684775 kB\n')['mode'] == 'TWO_LANE'
    assert LANES.memory_admission('MemTotal: 64199664 kB\nMemAvailable: 14684774 kB\n')['mode'] == 'SERIAL'


def test_memory_admission_records_both_thresholds_and_the_guard():
    decision = LANES.memory_admission(meminfo(64199664, 57000000))
    assert decision['thresholds_mib'] == {'FOUR_LANE': 25681.2, 'TWO_LANE': 14340.6}
    assert decision['guard_mib'] == 3000 and decision['mem_total_kib'] == 64199664 and decision['mem_available_kib'] == 57000000


@pytest.mark.parametrize('text', ['', 'MemTotal: 1 kB\n', 'MemAvailable: x kB\nMemTotal: 1 kB\n',
                                  'MemAvailable: 57000000 kB\n', 'MemTotal: 64199664 kB\nMemAvailable: -5 kB\n'])
def test_memory_admission_without_a_readable_measure_is_serial(text):
    decision = LANES.memory_admission(text)
    assert decision['mode'] == 'SERIAL' and decision['lanes'] == 1


def test_threshold_is_the_measured_value_and_the_guard_is_unchanged():
    assert LANES.TWO_LANE_START_THRESHOLD_MIB == 14340.6
    assert LANES.MEMORY_GUARD_MIB == 3000


def test_four_lane_threshold_follows_the_measured_rule_of_rem_0037():
    # lanes x single-lane peak occupancy (5670.3 MiB) + the unchanged guard
    assert LANES.LANE_PEAK_OCCUPANCY_MIB == 5670.3
    assert LANES.FOUR_LANE_START_THRESHOLD_MIB == 25681.2
    assert LANES.FOUR_LANE_START_THRESHOLD_MIB == round(4 * LANES.LANE_PEAK_OCCUPANCY_MIB + LANES.MEMORY_GUARD_MIB, 1)
    assert LANES.TWO_LANE_START_THRESHOLD_MIB == round(2 * LANES.LANE_PEAK_OCCUPANCY_MIB + LANES.MEMORY_GUARD_MIB, 1)
    assert LANES.ADMISSION_LEVELS == (('FOUR_LANE', 4, 25681.2), ('TWO_LANE', 2, 14340.6))


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
    nodeids = list(data['weights'].keys())
    assert estimate['lower_bound_seconds'] == max(LANES.case_weight(node, data['weights']) for node in nodeids)
    assert len(estimate['lane_seconds']) == 4 and estimate['lanes'] == 4
    assert max(estimate['lane_seconds']) >= estimate['lower_bound_seconds']
    two = LANES.partition_estimate(nodeids, data['weights'], lanes=2)
    assert len(two['lane_seconds']) == 2 and two['lanes'] == 2
    assert two['lower_bound_seconds'] == estimate['lower_bound_seconds']


# The 0049 Helm case sleeps until the next tick of the approved */15 CronJob
# schedule (wall-clock aligned, 0..900 s); a single measured time is therefore no
# upper bound. Found by the REM-0037 kind smoke at 0724a04 (1224.5 s in a lane
# against 429.1 s in the measurement). Partition weights only, never selection.
def test_clock_aligned_case_weight_adds_a_full_cron_period():
    key = 'tests.tasks.test_ocor_dev_0049::' + HELM.split('::')[-1]
    assert LANES.CLOCK_ALIGNED_WAIT_SECONDS == {key: 900.0}
    assert LANES.case_weight(HELM, {key: 429.129}) == pytest.approx(1329.129)
    # unmeasured: the default plus the full period, never less than the period
    assert LANES.case_weight(HELM, {}) == pytest.approx(LANES.DEFAULT_CASE_SECONDS + 900.0)
    # every other case keeps its measured weight
    assert LANES.case_weight(f'{M49}::test_slow', weights()) == 300.0


def _constant_product(node):
    """Value of an integer literal or a product of integer literals; anything else fails."""
    import ast
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _constant_product(node.left) * _constant_product(node.right)
    assert isinstance(node, ast.Constant) and type(node.value) is int, ast.dump(node)
    return node.value


def test_clock_aligned_wait_matches_the_only_cron_aligned_0049_case():
    import ast
    tree = ast.parse((ROOT / 'ocor-runtime' / M49).read_text(encoding='utf-8'))
    period = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'CRON_PERIOD_SECONDS' for t in node.targets)]
    assert len(period) == 1 and _constant_product(period[0]) == 900
    users = sorted(fn.name for fn in tree.body if isinstance(fn, ast.FunctionDef)
                   and any(isinstance(n, ast.Name) and n.id == 'CRON_PERIOD_SECONDS' for n in ast.walk(fn)))
    assert users == [HELM.split('::')[-1]]
    assert set(LANES.CLOCK_ALIGNED_WAIT_SECONDS.values()) == {900.0}


@pytest.mark.parametrize('count', ADMITTED)
def test_partition_estimate_counts_the_clock_aligned_wait_in_the_lower_bound(count):
    estimate = LANES.partition_estimate(nodes(), weights(), lanes=count)
    assert estimate['lower_bound_seconds'] == pytest.approx(1300.0)
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    helm_lane = next(index for index, part in enumerate(parts) if HELM in part)
    assert parts[helm_lane] == [HELM]


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
    fourth = lane(tmp_path, 4)
    assert fourth.name == f'ocor-lane-{CAMPAIGN_ID}-4'
    assert len({lane(tmp_path, index).name for index in range(1, 5)}) == 4
    for index in (0, 5, -1):
        with pytest.raises(CAMPAIGN.CampaignError):
            LANES.Lane(index=index, campaign=CAMPAIGN_ID, root=tmp_path, home=Path('/home/luca'), uid=1000, gid=1000)


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


def test_shared_image_cache_is_mounted_read_only_after_the_writable_output(tmp_path):
    """A lane sees the campaign output writable and the shared image cache read-only."""
    item = lane(tmp_path)
    output = tmp_path / 'out'
    cache = output / 'image-cache'
    argv = LANES.sandbox_run_argv(item, [], output_root=output, readonly_mounts=[cache])
    output_mount = f'{output}:{output}'
    cache_mount = f'{cache}:{cache}:ro'
    assert output_mount in argv
    assert cache_mount in argv
    assert argv.index(output_mount) < argv.index(cache_mount)
    assert f'{cache}:{cache}' not in argv


def test_readonly_mount_cannot_hide_the_writable_campaign_output(tmp_path):
    item = lane(tmp_path)
    output = tmp_path / 'out'
    with pytest.raises(CAMPAIGN.CampaignError, match='writable campaign output'):
        LANES.sandbox_run_argv(item, [], output_root=output, readonly_mounts=[output])
    with pytest.raises(CAMPAIGN.CampaignError, match='writable campaign output'):
        LANES.sandbox_run_argv(item, [], output_root=output, readonly_mounts=[tmp_path])
    with pytest.raises(CAMPAIGN.CampaignError, match='absolute path'):
        LANES.sandbox_run_argv(item, [], output_root=output, readonly_mounts=[Path('image-cache')])


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


DELEGATED = 'cpuset cpu io memory hugetlb pids rdma misc\n'


def test_start_sandbox_creates_labelled_volumes_and_waits_for_an_empty_private_daemon(tmp_path):
    item = lane(tmp_path)
    runner = FakeRunner([(['docker', 'exec', item.name, 'cat', '/sys/fs/cgroup/cgroup.subtree_control'], 0, DELEGATED)])
    LANES.start_sandbox(item, [], runner, output_root=tmp_path / 'out', sleep=lambda seconds: None)
    argvs = runner.argvs()
    for volume in item.volumes:
        assert ['docker', 'volume', 'create', '--label', f'{LANES.LANE_LABEL}={CAMPAIGN_ID}', volume] in argvs
    assert argvs.index(LANES.sandbox_run_argv(item, [], output_root=tmp_path / 'out')) > 1
    assert ['docker', 'exec', item.name, 'docker', 'info', '--format', '{{.ServerVersion}}'] in argvs
    assert ['docker', 'exec', item.name, 'docker', 'ps', '-aq'] in argvs


def test_sandbox_init_retries_the_controller_delegation_and_fails_closed_before_dockerd(tmp_path):
    # A docker exec that arrives before the delegation lands in the root cgroup
    # and makes the single write fail: the init moves late processes and retries.
    script = LANES.sandbox_init(lane(tmp_path))
    delegation, _, rest = script.partition('exec /usr/bin/dockerd')
    assert f'seq 1 {LANES.CGROUP_DELEGATION_ATTEMPTS}' in delegation
    assert delegation.index('xargs -rn1 < /sys/fs/cgroup/cgroup.procs') < delegation.index('> /sys/fs/cgroup/cgroup.subtree_control')
    assert 'grep -qw memory /sys/fs/cgroup/cgroup.subtree_control || exit 97' in delegation
    assert rest == ' --host unix:///run/docker.sock --group 1000 --data-root /var/lib/docker'


def test_cgroup_delegation_is_bounded():
    assert 1 < LANES.CGROUP_DELEGATION_ATTEMPTS * LANES.CGROUP_DELEGATION_PAUSE_SECONDS <= LANES.SANDBOX_READY_SECONDS


@pytest.mark.parametrize('delegated', ['', 'cpu io pids\n', 'cpuset cpu io hugetlb pids\n'])
def test_start_sandbox_fails_closed_without_the_delegated_resource_controllers(tmp_path, delegated):
    item = lane(tmp_path)
    runner = FakeRunner([(['docker', 'exec', item.name, 'cat', '/sys/fs/cgroup/cgroup.subtree_control'], 0, delegated)])
    with pytest.raises(CAMPAIGN.CampaignError, match='controllers'):
        LANES.start_sandbox(item, [], runner, output_root=tmp_path / 'out', sleep=lambda seconds: None)


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
             'pytest_exit': 0, 'head': HEAD, 'bootstrap_exit': 0}
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
        if world['bootstrap_exit'] and '--teardown' not in argv:
            if check:
                raise CAMPAIGN.CampaignError('command failed (1)')
            return LANES.CommandResult(1, json.dumps({'status': 'FAIL', 'error': 'complete stack failed', 'echo': SECRET}))
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
    {'campaign_start': 0}, {'lane': 5}, {'lane': 0}, {'lane': '1'}, {'lane': True}, {'stop_file': ''}])
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


def test_lane_keeps_the_redacted_bootstrap_output_when_the_bootstrap_fails(lane_world, tmp_path):
    lane_world['bootstrap_exit'] = 1
    spec = lane_spec(tmp_path)
    assert run_lane(lane_world, spec) == 1
    result = assert_lane_failed(spec, 'bootstrap')
    log = (spec.parent / 'bootstrap.log').read_text()
    assert 'complete stack failed' in log and SECRET not in log and '[REDACTED]' in log
    assert 'complete stack failed' in result['error'] and SECRET not in result['error']
    assert not [call for call in lane_world['calls'] if call[0] in ('collect', 'pytest')]


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


def four_lanes(tmp_path):
    lanes = [lane(tmp_path, index) for index in range(1, 5)]
    for item in lanes:
        item.output.mkdir(parents=True)
    return lanes


def admitted_lanes(tmp_path, count):
    return two_lanes(tmp_path) if count == 2 else four_lanes(tmp_path)


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


def test_supervision_of_four_passing_lanes_writes_no_stop_request(tmp_path):
    lanes, clock = four_lanes(tmp_path), FakeClock()
    processes = {index: FakeProcess(0, index) for index in range(1, 5)}
    report = LANES.supervise_lanes(processes, lanes, clock.now - 10, clock=clock, sleep=clock.sleep)
    assert report['returncodes'] == {1: 0, 2: 0, 3: 0, 4: 0} and report['first_failure'] is None
    assert not any((item.output / 'STOP').exists() for item in lanes)


def test_first_failure_of_one_of_four_lanes_stops_the_other_three(tmp_path):
    lanes, clock = four_lanes(tmp_path), FakeClock()
    processes = {1: FakeProcess(1, 4), 2: FakeProcess(1, 5), 3: FakeProcess(1, 1), 4: FakeProcess(1, 6)}
    report = LANES.supervise_lanes(processes, lanes, clock.now, clock=clock, sleep=clock.sleep)
    assert report['first_failure'] == 3 and report['returncodes'] == {1: 1, 2: 1, 3: 1, 4: 1}
    assert all('lane 3' in (lanes[index].output / 'STOP').read_text() for index in (0, 1, 3))
    assert not (lanes[2].output / 'STOP').exists() and report['killed_after_grace'] == []


def test_host_clock_at_the_limit_stops_all_four_lanes(tmp_path):
    lanes, clock = four_lanes(tmp_path), FakeClock()
    processes = {index: FakeProcess(1, 3) for index in range(1, 5)}
    report = LANES.supervise_lanes(processes, lanes, clock.now - 5400, clock=clock, sleep=clock.sleep)
    assert '90-minute campaign limit reached' in report['stop_reason']
    assert all('90-minute' in (item.output / 'STOP').read_text() for item in lanes)


def test_stuck_lanes_among_four_are_killed_after_the_grace(tmp_path):
    lanes, clock = four_lanes(tmp_path), FakeClock(step=60.0)
    stuck = {1: FakeProcess(0, None), 4: FakeProcess(0, None)}
    report = LANES.supervise_lanes({**stuck, 2: FakeProcess(1, 0), 3: FakeProcess(0, 0)}, lanes, clock.now,
                                   clock=clock, sleep=clock.sleep)
    assert all(process.killed for process in stuck.values()) and sorted(report['killed_after_grace']) == [1, 4]


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


@pytest.mark.parametrize('count', ADMITTED)
def test_lane_results_must_all_pass_for_their_exact_selection_and_head(tmp_path, count):
    lanes = admitted_lanes(tmp_path, count)
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    for item, part in zip(lanes, parts):
        write_lane_result(item, part)
    results = LANES.read_lane_results(lanes, HEAD, parts)
    assert [result['lane'] for result in results] == list(range(1, count + 1))


@pytest.mark.parametrize('count', ADMITTED)
@pytest.mark.parametrize('change, match', [
    ({'status': 'FAIL', 'error': 'pytest exit code 1'}, 'pytest exit code 1'),
    ({'candidate_head': '0' * 40}, 'head'),
    ({'lane': 1}, 'lane'),
    ({'selected_sha256': '0' * 64}, 'selection'),
])
def test_lane_results_reject_a_failure_another_head_lane_or_selection(tmp_path, change, match, count):
    lanes = admitted_lanes(tmp_path, count)
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    for item, part in zip(lanes[:-1], parts[:-1]):
        write_lane_result(item, part)
    write_lane_result(lanes[-1], parts[-1], **change)
    with pytest.raises(CAMPAIGN.CampaignError, match=match):
        LANES.read_lane_results(lanes, HEAD, parts)


@pytest.mark.parametrize('count', ADMITTED)
def test_lane_results_reject_an_absent_result(tmp_path, count):
    lanes = admitted_lanes(tmp_path, count)
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    for item, part in zip(lanes[:-1], parts[:-1]):
        write_lane_result(item, part)
    with pytest.raises(CAMPAIGN.CampaignError, match=f'lane {count}'):
        LANES.read_lane_results(lanes, HEAD, parts)


def test_lane_results_reject_a_lane_set_that_differs_from_the_partition(tmp_path):
    lanes = four_lanes(tmp_path)
    parts = LANES.lane_partition(nodes(), weights(), lanes=4)
    for item, part in zip(lanes, parts):
        write_lane_result(item, part)
    with pytest.raises(ValueError):
        LANES.read_lane_results(lanes[:3], HEAD, parts)


@pytest.mark.parametrize('count', ADMITTED)
def test_merged_junit_keeps_every_lane_suite_and_enforces_required_modules(tmp_path, count):
    lanes = admitted_lanes(tmp_path, count)
    parts = LANES.lane_partition(nodes(), weights(), lanes=count)
    for item, part in zip(lanes, parts):
        write_junit(item.output / LANES.LANE_JUNIT, [CAMPAIGN.junit_identity(node) for node in part])
    merged = tmp_path / 'merged.xml'
    counts = LANES.merge_lane_junit(lanes, merged, required_modules=['test_ocor_dev_0049'])
    assert counts == {'tests': len(nodes()), 'failures': 0, 'errors': 0, 'skipped': 0}
    assert [suite.get('name') for suite in ET.parse(merged).getroot().iter('testsuite')] == [
        f'pytest-lane-{index}' for index in range(1, count + 1)]
    with pytest.raises(CAMPAIGN.CampaignError, match='required guard'):
        LANES.merge_lane_junit(lanes, tmp_path / 'other.xml', required_modules=['test_ocor_dev_0048'])


def test_coverage_of_four_lanes_is_combined_with_every_lane_path_remapped(tmp_path):
    lanes = four_lanes(tmp_path)
    for item in lanes:
        (item.output / 'runtime_coverage.data').write_bytes(b'data-%d' % item.index)
    suite, output = tmp_path / 'host/ocor-runtime', tmp_path / 'campaign'
    output.mkdir()
    runner = FakeRunner()
    LANES.combine_lane_coverage(suite, lanes, output, runner)
    text = (output / 'lane_coverage.rc').read_text()
    sources = [line.strip() for line in text.split('source =', 1)[1].splitlines() if line.strip()]
    assert sources == [str(suite / 'src'), *(str(item.repository / 'ocor-runtime/src') for item in lanes)]
    combine, _ = runner.calls
    assert combine['argv'][-4:] == [str(output / f'runtime_coverage.lane-{index}') for index in range(1, 5)]


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
    world = {'calls': [], 'lane_exit': {1: 0, 2: 0, 3: 0, 4: 0}, 'fail_provision': None, 'collected': nodes(), 'head': HEAD}
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

    def prepare_image_cache(lock_path, destination, runner, *, timeout):
        world['calls'].append(('prepare_image_cache', str(lock_path)))
        if callable(timeout):
            timeout()
        return {'images': [], 'lock_sha256': '0' * 64, 'schema': 'ocor-local-lane-image-cache/v1'}

    def seed_lane_images(item, path, cache_dir, lock_path, runner, *, timeout):
        world['calls'].append(('image_cache', item.index))
        if callable(timeout):
            timeout()
        return {'loaded': [], 'misses': [], 'status': 'COLD'}

    def provision_lane(item, source_path, head, runner, env):
        world['calls'].append(('provision', item.index))
        if world['fail_provision'] == item.index:
            raise CAMPAIGN.CampaignError(f'lane {item.index} provisioning failed')
        item.output.mkdir(parents=True)
        item.repository.mkdir(parents=True)
        return {'lane': item.index, 'head': head, 'repository': str(item.repository)}

    def start_sandbox(item, mounts, runner, *, output_root, readonly_mounts=None, sleep=None):
        world['calls'].append(('sandbox', item.index))
        world.setdefault('readonly_mounts', []).append(
            (item.index, [str(path) for path in (readonly_mounts or [])]))
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
    monkeypatch.setattr(LANES, 'prepare_image_cache', prepare_image_cache)
    monkeypatch.setattr(LANES, 'seed_lane_images', seed_lane_images)
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
    assert result['admission_level'] == 'TWO_LANE' and result['lanes_admitted'] == 2 and result['lanes_run'] == 2
    assert 'below the four-lane threshold' in result['memory']['reason']
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
    assert result['admission_level'] == 'SERIAL' and result['lanes_admitted'] == 1 and result['lanes_run'] == 0
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
    monkeypatch.setattr(LANES, 'lane_partition', lambda collected, weights_map, lanes: [collected[:3], collected[4:]])
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL' and 'missing' in result['error']


FOUR_LANE_MEMINFO = meminfo(64199664, 57000000)


def test_execute_runs_four_lanes_in_parallel_when_memory_admits_them(host_world):
    host_world['collected'] = [*nodes(), M48]
    host_world['meminfo'].write_text(FOUR_LANE_MEMINFO)
    result = execute(host_world)
    assert result['status'] == 'PASS' and result == stored_result(host_world)
    assert result['mode'] == 'FOUR_LANE' and result['admission_level'] == 'FOUR_LANE' and result['memory']['mode'] == 'FOUR_LANE'
    assert result['lanes_admitted'] == 4 and result['lanes_run'] == 4
    collected = host_world['collected']
    assert len(result['collection']['lane_cases']) == 4 and sum(result['collection']['lane_cases']) == len(collected)
    assert len(result['collection']['lane_estimated_seconds']) == 4
    assert result['union'] == {'collected': len(collected), 'executed': len(collected), 'missing': [], 'duplicated': [], 'unexpected': [],
                               'lanes': result['collection']['lane_cases']}
    assert result['counts'] == {'tests': len(collected), 'failures': 0, 'errors': 0, 'skipped': 0}
    assert [entry['lane'] for entry in result['lanes']] == [1, 2, 3, 4]
    assert all(entry['result']['status'] == 'PASS' for entry in result['lanes'])
    calls = [call[0] for call in host_world['calls']]
    launches = [i for i, call in enumerate(calls) if call == 'launch']
    assert len(launches) == 4 and launches == list(range(launches[0], launches[0] + 4))
    assert max(i for i, call in enumerate(calls) if call in ('provision', 'sandbox')) < launches[0]
    assert calls.count('provision') == calls.count('sandbox') == calls.count('teardown') == 4
    assert calls.index('coverage') > launches[-1] and calls[-1] == 'residue'
    assert result['limit_seconds'] == 5400 and result['threshold_seconds'] == 3600


def test_execute_falls_back_to_two_lanes_below_the_four_lane_threshold(host_world):
    host_world['meminfo'].write_text(meminfo(64199664, int(LANES.FOUR_LANE_START_THRESHOLD_MIB * 1024) - 1))
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'PASS' and result['admission_level'] == 'TWO_LANE' and result['lanes_run'] == 2
    calls = [call[0] for call in host_world['calls']]
    assert calls.count('launch') == calls.count('teardown') == 2


def test_execute_with_four_lanes_records_the_failing_lane_and_tears_down_all_four(host_world):
    host_world['meminfo'].write_text(FOUR_LANE_MEMINFO)
    host_world['lane_exit'][3] = 1
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL' and 'lane 3' in result['error'] and result['supervision']['first_failure'] == 3
    calls = [call[0] for call in host_world['calls']]
    assert calls.count('teardown') == 4 and 'coverage' not in calls and calls[-1] == 'residue'


def test_execute_with_four_lanes_tears_down_all_four_when_provisioning_fails(host_world):
    host_world['meminfo'].write_text(FOUR_LANE_MEMINFO)
    host_world['fail_provision'] = 3
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL' and 'provisioning failed' in result['error']
    assert result['lanes_admitted'] == 4 and result['lanes_run'] == 0
    calls = [call[0] for call in host_world['calls']]
    assert 'launch' not in calls and calls.count('teardown') == 4 and calls[-1] == 'residue'


def test_execute_with_four_lanes_rejects_a_union_with_an_absent_lane(host_world, monkeypatch):
    host_world['meminfo'].write_text(FOUR_LANE_MEMINFO)
    real = LANES.check_exact_union
    monkeypatch.setattr(LANES, 'check_exact_union', lambda collected, junits, lanes: real(collected, junits[:-1], lanes=lanes))
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL' and 'expected 4 lane JUnit files' in result['error']


# --- lifecycle check: four sandboxes, parallel stack bootstrap, typed probes --
# PO LOCAL-SUITE-FOUR-LANES (2026-11-07) point 3: provisioning, the four private
# daemons, the four stacks bootstrapped in parallel, the typed probe of every
# service, teardown without residue; per lane the bootstrap time and the time
# Temporal answers SERVING since the start of its container.

STARTED_AT = '2026-11-07T10:00:00.250000000Z'
SERVING_WALL = 1794045658.25  # 2026-11-07T10:00:58.25Z


def bootstrap_output(*, status='PASS', services=None):
    services = [{'service': name, 'status': state} for name, state in (services or {'postgresql': 'READY', 'temporal': 'READY'}).items()]
    final = {'status': status, 'provisioning_seconds': 101.5,
             'services': {'status': 'PASS' if all(item['status'] == 'READY' for item in services) else 'FAIL', 'services': services}}
    if status != 'PASS':
        final = {'status': 'FAIL', 'error': 'typed service health failed'}
    return ('{"operation": "teardown", "status": "PASS"}\n{"exit_code": 0, "operation": "control-plane SVID"}\n'
            + json.dumps(final, indent=2, sort_keys=True) + '\n')


def test_bootstrap_summary_reads_the_final_typed_result():
    summary = LANES.bootstrap_summary(bootstrap_output())
    assert summary == {'status': 'PASS', 'provisioning_seconds': 101.5, 'services': {'postgresql': 'READY', 'temporal': 'READY'}}


@pytest.mark.parametrize('text', ['', 'no json\n', '{"operation": "x"}\n{\n  "status": "PASS"\n', '[1, 2]\n',
                                  '{"status": "PASS", "services": {"services": [{"service": "x"}]}}\n',
                                  '{"status": "PASS", "services": {"services": "x"}}\n',
                                  '{"status": "PASS", "services": {"services": []}}\n',
                                  '{"status": "PASS", "services": {"services": [{"service": "x", "status": "READY"},'
                                  ' {"service": "x", "status": "READY"}]}}\n'])
def test_bootstrap_summary_rejects_absent_or_malformed_output(text):
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.bootstrap_summary(text)


@pytest.mark.parametrize('final', [
    {'status': 1}, {'status': None}, {'status': 'FAIL', 'error': {'x': 1}}, {'status': 'FAIL', 'error': 5},
    {'status': 'PASS', 'provisioning_seconds': True, 'services': {'services': [{'service': 'x', 'status': 'READY'}]}},
    {'status': 'PASS', 'provisioning_seconds': '101', 'services': {'services': [{'service': 'x', 'status': 'READY'}]}},
    {'status': 'PASS', 'services': {'services': [{'service': 'x', 'status': 'READY'}]}},
])
def test_bootstrap_summary_takes_no_field_by_conversion(final):
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.bootstrap_summary(json.dumps(final, indent=2) + '\n')


def test_bootstrap_summary_keeps_a_typed_failure():
    assert LANES.bootstrap_summary('{"status": "FAIL", "error": "typed service health failed"}\n') == {
        'status': 'FAIL', 'error': 'typed service health failed'}
    assert LANES.bootstrap_summary('{"status": "FAIL"}\n') == {'status': 'FAIL', 'error': ''}


@pytest.mark.parametrize('text', ['2026-13-01T00:00:00Z', '2026-02-30T00:00:00Z', '2026-11-07T24:00:00Z',
                                  '2026-11-07T10:61:00Z', '2026-11-07T10:00:00.Z', '2026-11-07T10:00:00.1234567890Z'])
def test_container_start_rejects_impossible_or_malformed_times(text):
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.container_started_epoch(text)


def test_container_start_is_parsed_with_nanoseconds_and_rejects_other_text():
    assert LANES.container_started_epoch(STARTED_AT) == pytest.approx(1794045600.25)
    assert LANES.container_started_epoch('2026-11-07T10:00:00Z') == pytest.approx(1794045600.0)
    for text in ('', '0001-01-01T00:00:00Z', 'yesterday', '2026-11-07 10:00:00', '2026-11-07T10:00:00.1+01:00'):
        with pytest.raises(CAMPAIGN.CampaignError):
            LANES.container_started_epoch(text)


def temporal_runner(*, serving=True, started=STARTED_AT, extra=()):
    return FakeRunner([*extra, (['*', 'git rev-parse HEAD'], 0, HEAD + '\n'),
                       (['*', 'operator cluster health'], 0 if serving else 1, 'SERVING\n' if serving else 'context deadline exceeded\n'),
                       (['*', '{{.State.StartedAt}}'], 0, started + '\n')])


def test_temporal_serving_is_measured_from_the_start_of_its_container(tmp_path):
    item = four_lanes(tmp_path)[0]
    runner = temporal_runner()
    observed = LANES.observe_temporal_serving(item, '/p', runner, finished=lambda: False, wall=lambda: SERVING_WALL,
                                              sleep=lambda seconds: None, monotonic=FakeClock(0.0, 1.0))
    assert observed['serving'] is True and observed['seconds_from_container_start'] == pytest.approx(58.0)
    assert observed['container_started_at'] == STARTED_AT
    health = [argv for argv in runner.argvs() if 'health' in argv][0]
    assert health[-11:] == ['docker', 'exec', 'ocor-bootstrap-temporal-admin-tools-1', 'temporal', 'operator', 'cluster', 'health',
                            '--address', 'temporal:7233', '--command-timeout', '5s']
    assert health[:3] == ['docker', 'exec', '-u'] and item.name in health
    assert any('ocor-bootstrap-temporal-1' in argv for argv in runner.argvs() if '{{.State.StartedAt}}' in argv)


def test_temporal_not_serving_before_the_bootstrap_ends_is_recorded_as_not_observed(tmp_path):
    item = four_lanes(tmp_path)[0]
    polls = []

    def finished():
        polls.append(1)
        return len(polls) > 3
    observed = LANES.observe_temporal_serving(item, '/p', temporal_runner(serving=False), finished=finished, wall=lambda: SERVING_WALL,
                                              sleep=lambda seconds: None, monotonic=FakeClock(0.0, 1.0))
    assert observed['serving'] is False and observed['seconds_from_container_start'] is None and observed['polls'] >= 3


def test_temporal_observation_is_bounded(tmp_path):
    item = four_lanes(tmp_path)[0]
    clock = FakeClock(0.0, 0.0)
    observed = LANES.observe_temporal_serving(item, '/p', temporal_runner(serving=False), finished=lambda: False,
                                              wall=lambda: SERVING_WALL, sleep=lambda seconds: setattr(clock, 'now', clock.now + 30.0),
                                              monotonic=clock)
    assert observed['serving'] is False and clock.now >= LANES.LIFECYCLE_BOOTSTRAP_LIMIT_SECONDS


def lifecycle(world, runner=None, *, lanes=4):
    return LANES.lifecycle_check(world['work'], HEAD, [Path('/home/luca/.ocor-codex/impl-env/x/bin')], runner or temporal_runner(),
                                 source=world['source'], launcher=world['bootstrap_launcher'], meminfo_path=world['meminfo'],
                                 wall=lambda: SERVING_WALL, sleep=lambda seconds: None, lanes=lanes)


@pytest.fixture
def life_world(host_world):
    host_world['meminfo'].write_text(FOUR_LANE_MEMINFO)
    host_world['bootstrap'] = {}

    def bootstrap_launcher(argv, log):
        index = int(argv[argv.index('-w') + 1].split('/lane-')[-1].split('/')[0])
        host_world['calls'].append(('bootstrap', index, list(argv)))
        exit_code, text = host_world['bootstrap'].get(index, (0, bootstrap_output()))
        log.write_text(text)
        return FakeProcess(exit_code, 1)
    host_world['bootstrap_launcher'] = bootstrap_launcher
    return host_world


def test_lifecycle_check_bootstraps_four_stacks_in_parallel_and_records_the_measures(life_world):
    report = lifecycle(life_world)
    assert report['status'] == 'PASS', report.get('error')
    assert report['lanes_requested'] == 4 and report['memory']['mode'] == 'FOUR_LANE'
    assert [entry['lane'] for entry in report['lanes']] == [1, 2, 3, 4]
    for entry in report['lanes']:
        assert entry['bootstrap']['exit_code'] == 0 and isinstance(entry['bootstrap']['seconds'], float)
        assert entry['bootstrap']['services'] == {'postgresql': 'READY', 'temporal': 'READY'}
        assert entry['temporal']['serving'] is True and entry['temporal']['seconds_from_container_start'] == pytest.approx(58.0)
        assert entry['probes']['head'] == HEAD
    calls = [call[0] for call in life_world['calls']]
    starts = [i for i, call in enumerate(calls) if call == 'bootstrap']
    assert len(starts) == 4 and starts == list(range(starts[0], starts[0] + 4))
    assert max(i for i, call in enumerate(calls) if call in ('provision', 'sandbox')) < starts[0]
    assert calls.count('teardown') == 4 and calls[-1] == 'residue'
    bootstrap = next(call[2] for call in life_world['calls'] if call[0] == 'bootstrap')
    command = bootstrap[-1]
    assert bootstrap[:3] == ['docker', 'exec', '-u'] and 'bootstrap_ci_environment.py --teardown --execute' in command
    assert 'bootstrap_ci_environment.py --execute --timeout 600' in command
    assert command.index('--teardown') < command.index('--timeout 600')
    assert report['staggered'] is False


def test_lifecycle_check_fails_closed_on_a_lane_bootstrap_failure_and_still_tears_down_all(life_world):
    life_world['bootstrap'][2] = (1, bootstrap_output(status='FAIL'))
    report = lifecycle(life_world)
    assert report['status'] == 'FAIL' and 'lane 2' in report['error'] and 'bootstrap' in report['error']
    calls = [call[0] for call in life_world['calls']]
    assert calls.count('teardown') == 4 and calls[-1] == 'residue'


def test_lifecycle_check_rejects_a_service_that_is_not_ready(life_world):
    life_world['bootstrap'][4] = (0, bootstrap_output(services={'postgresql': 'READY', 'temporal': 'DEGRADED'}))
    report = lifecycle(life_world)
    assert report['status'] == 'FAIL' and 'lane 4' in report['error'] and 'temporal' in report['error']


def test_lifecycle_check_rejects_a_temporal_that_was_never_seen_serving(life_world):
    report = lifecycle(life_world, temporal_runner(serving=False))
    assert report['status'] == 'FAIL' and 'Temporal' in report['error']
    assert [call[0] for call in life_world['calls']].count('teardown') == 4


def test_lifecycle_check_refuses_more_lanes_than_memory_admits(life_world):
    life_world['meminfo'].write_text(meminfo(64199664, 26000000))
    report = lifecycle(life_world)
    assert report['status'] == 'FAIL' and 'admits 2' in report['error']
    assert not [call for call in life_world['calls'] if call[0] in ('provision', 'sandbox', 'bootstrap')]


def test_lifecycle_check_of_two_lanes_is_admitted_at_the_two_lane_level(life_world):
    life_world['meminfo'].write_text(meminfo(64199664, 26000000))
    report = lifecycle(life_world, lanes=2)
    assert report['status'] == 'PASS' and [entry['lane'] for entry in report['lanes']] == [1, 2]


@pytest.mark.parametrize('lanes', [0, 1, 3, 5])
def test_lifecycle_check_runs_only_an_admitted_lane_count(life_world, lanes):
    report = lifecycle(life_world, lanes=lanes)
    assert report['status'] == 'FAIL'
    assert not [call for call in life_world['calls'] if call[0] in ('provision', 'bootstrap')]


def test_lifecycle_check_kills_a_bootstrap_that_exceeds_its_bound(life_world, monkeypatch):
    stuck = FakeProcess(0, None)
    life_world['bootstrap_launcher'] = lambda argv, log: (log.write_text(''), stuck)[1]
    monkeypatch.setattr(LANES, 'LIFECYCLE_BOOTSTRAP_LIMIT_SECONDS', 0)
    report = lifecycle(life_world)
    assert report['status'] == 'FAIL' and 'bound' in report['error'] and stuck.killed
    assert [call[0] for call in life_world['calls']].count('teardown') == 4


def test_lifecycle_check_records_an_unreadable_temporal_start_as_not_observed(life_world):
    report = lifecycle(life_world, temporal_runner(extra=[(['*', '{{.State.StartedAt}}'], 1, '')]))
    assert report['status'] == 'FAIL' and 'Temporal was not observed SERVING' in report['error']
    assert all(entry['temporal']['serving'] is False and entry['temporal']['error'] for entry in report['lanes'])
    assert [call[0] for call in life_world['calls']].count('teardown') == 4


def test_lifecycle_check_with_a_malformed_temporal_start_fails_closed(life_world):
    report = lifecycle(life_world, temporal_runner(started='0001-01-01T00:00:00Z'))
    assert report['status'] == 'FAIL' and 'unexpected container start time' in report['error']


def test_lifecycle_check_stops_the_started_bootstraps_when_a_launch_fails(life_world):
    started = []
    real = life_world['bootstrap_launcher']

    def launcher(argv, log):
        index = int(argv[argv.index('-w') + 1].split('/lane-')[-1].split('/')[0])
        if index == 3:
            raise OSError('cannot start lane 3 bootstrap')
        real(argv, log)
        started.append(FakeProcess(0, None))
        return started[-1]
    life_world['bootstrap_launcher'] = launcher
    report = lifecycle(life_world)
    assert report['status'] == 'FAIL' and 'lane 3' in report['error']
    assert len(started) == 2 and all(process.killed for process in started)
    assert [call[0] for call in life_world['calls']].count('teardown') == 4


def test_lifecycle_check_kills_every_running_bootstrap_when_the_wait_fails(life_world, monkeypatch):
    stuck = [FakeProcess(0, None) for _ in range(4)]
    pending = iter(stuck)
    life_world['bootstrap_launcher'] = lambda argv, log: (log.write_text(''), next(pending))[1]
    calls = {'n': 0}

    def failing_sleep(seconds):
        calls['n'] += 1
        if calls['n'] > 2:
            raise OSError('host clock unavailable')
    report = LANES.lifecycle_check(life_world['work'], HEAD, [Path('/x/bin')], temporal_runner(serving=False), source=life_world['source'],
                                   launcher=life_world['bootstrap_launcher'], meminfo_path=life_world['meminfo'],
                                   wall=lambda: SERVING_WALL, sleep=failing_sleep, lanes=4)
    assert report['status'] == 'FAIL' and 'host clock unavailable' in report['error']
    assert all(process.killed for process in stuck)
    assert [call[0] for call in life_world['calls']].count('teardown') == 4


def test_lifecycle_cli_passes_the_lane_count(monkeypatch, tmp_path):
    seen = {}

    def fake(work, head, tool_bins, **kwargs):
        seen.update(kwargs)
        return {'status': 'PASS'}
    monkeypatch.setattr(LANES, 'lifecycle_check', fake)
    assert LANES.main(['--lifecycle-check', str(tmp_path), '--expected-head', HEAD, '--tool-bin', str(tmp_path)]) == 0
    assert seen['lanes'] == 4
    assert LANES.main(['--lifecycle-check', str(tmp_path), '--expected-head', HEAD, '--tool-bin', str(tmp_path), '--lanes', '2']) == 0
    assert seen['lanes'] == 2
    with pytest.raises(SystemExit):
        LANES.main(['--lifecycle-check', str(tmp_path), '--expected-head', HEAD, '--tool-bin', str(tmp_path), '--lanes', '3'])


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


# --- input robustness of every parsing path (preventive review OCOR-DEV-REM-0056-0fd478064f9b-pre) --
# PRE-REVIEW-INPUT-ROBUSTNESS (2026-10-29) and NCP-THROUGHPUT-RULES (2026-11-05)
# point 1, on the whole orchestrator: shape checked without conversion (ASCII
# digits only, no bool where a number is due, no NaN or Infinity), decoding and
# conversion errors translated into the typed CampaignError or the recorded
# serial fallback, tampered data refused, and every process stopped on every
# error path.

ARABIC_INDIC = str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩')
FULLWIDTH = str.maketrans('0123456789', '０１２３４５６７８９')


@pytest.mark.parametrize('text', [
    'MemTotal: ² kB\nMemAvailable: 57000000 kB\n',
    'MemTotal: 64199664 kB\nMemAvailable: ¹ kB\n',
    FOUR_LANE_MEMINFO.translate(ARABIC_INDIC),
    FOUR_LANE_MEMINFO.translate(FULLWIDTH),
    'MemTotal: 64199664 kB\nMemAvailable: 57000000 MB\n',
    'MemTotal: 64199664 kB\nMemAvailable: 57000000\n',
    'MemTotal: 64199664 kB\nMemAvailable: 57000000 kB extra\n',
    'MemTotal: 64199664 kB\nMemAvailable: 57000000 kB\nMemAvailable: 1 kB\n',
])
def test_memory_admission_reads_only_ascii_kib_fields_and_never_raises(text):
    decision = LANES.memory_admission(text)
    assert decision['mode'] == 'SERIAL' and decision['lanes'] == 1


@pytest.mark.parametrize('content', [b'\xff\xfe' + FOUR_LANE_MEMINFO.encode(), FOUR_LANE_MEMINFO.encode() + b'\x80'])
def test_memory_reading_of_non_utf8_meminfo_is_the_recorded_serial_fallback(tmp_path, content):
    path = tmp_path / 'meminfo'
    path.write_bytes(content)
    decision = LANES.read_memory_admission(path)
    assert decision['mode'] == 'SERIAL' and decision['lanes'] == 1 and 'meminfo' in decision['reason']
    absent = LANES.read_memory_admission(tmp_path / 'absent')
    assert absent['mode'] == 'SERIAL' and 'meminfo unreadable' in absent['reason']
    path.write_text(FOUR_LANE_MEMINFO)
    assert LANES.read_memory_admission(path)['mode'] == 'FOUR_LANE'


def test_execute_with_non_utf8_meminfo_records_the_serial_fallback(host_world):
    host_world['meminfo'].write_bytes(b'\xff\xfe' + FOUR_LANE_MEMINFO.encode())
    result = execute(host_world)
    assert result['status'] == 'SERIAL_FALLBACK' and result == stored_result(host_world)
    assert not [call for call in host_world['calls'] if call[0] in ('provision', 'sandbox', 'launch')]


def test_lifecycle_check_with_non_utf8_meminfo_records_the_serial_fallback(life_world):
    life_world['meminfo'].write_bytes(b'\xff\xfe' + FOUR_LANE_MEMINFO.encode())
    report = lifecycle(life_world)
    assert report['status'] == 'FAIL' and report['memory']['mode'] == 'SERIAL' and 'admits 1' in report['error']
    assert not [call for call in life_world['calls'] if call[0] in ('provision', 'sandbox', 'bootstrap')]


def typed_final(**changes):
    final = {'status': 'PASS', 'provisioning_seconds': 101.5,
             'services': {'status': 'PASS', 'services': [{'service': 'postgresql', 'status': 'READY'}]}}
    final.update(changes)
    return final


@pytest.mark.parametrize('text', [
    '{"status": "PASS", "provisioning_seconds": NaN, "services": {"status": "PASS", "services": [{"service": "x", "status": "READY"}]}}\n',
    '{"status": "PASS", "provisioning_seconds": Infinity, "services": {"status": "PASS", "services": [{"service": "x", "status": "READY"}]}}\n',
    '{"status": "PASS", "provisioning_seconds": -Infinity, "services": {"status": "PASS", "services": [{"service": "x", "status": "READY"}]}}\n',
    json.dumps(typed_final(provisioning_seconds=-5.0)) + '\n',
    json.dumps(typed_final(services={'status': 'FAIL', 'services': [{'service': 'postgresql', 'status': 'READY'}]})) + '\n',
    json.dumps(typed_final(services={'status': 1, 'services': [{'service': 'postgresql', 'status': 'READY'}]})) + '\n',
    json.dumps(typed_final(services={'services': [{'service': 'postgresql', 'status': 'READY'}]})) + '\n',
    json.dumps(typed_final(services={'status': 'PASS', 'services': [{'service': '', 'status': 'READY'}]})) + '\n',
    json.dumps(typed_final(services={'status': 'PASS', 'services': [{'service': 'postgresql', 'status': ''}]})) + '\n',
    json.dumps(typed_final(services={})) + '\n',
    '{}\n',
])
def test_bootstrap_summary_refuses_non_finite_negative_or_inconsistent_results(text):
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.bootstrap_summary(text)


def test_bootstrap_summary_accepts_an_integral_provisioning_time():
    assert LANES.bootstrap_summary(json.dumps(typed_final(provisioning_seconds=0)) + '\n')['provisioning_seconds'] == 0


@pytest.mark.parametrize('text', [STARTED_AT.translate(ARABIC_INDIC), STARTED_AT.translate(FULLWIDTH),
                                  '2026-11-07T10:00:00.٢٥Z'])
def test_container_start_refuses_non_ascii_digits(text):
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.container_started_epoch(text)


def test_lifecycle_check_refuses_a_bootstrap_log_that_is_not_utf8(life_world):
    real = life_world['bootstrap_launcher']

    def launcher(argv, log):
        process = real(argv, log)
        if '/lane-2/' in argv[argv.index('-w') + 1]:
            log.write_bytes(bootstrap_output().replace('postgresql', 'post\udcffgres').encode('utf-8', 'surrogateescape'))
        return process
    life_world['bootstrap_launcher'] = launcher
    report = lifecycle(life_world)
    assert report['status'] == 'FAIL' and 'lane 2' in report['error'] and 'UTF-8' in report['error']
    lane_two = report['lanes'][1]['bootstrap']
    assert lane_two['status'] == 'FAIL' and 'services' not in lane_two
    assert [call[0] for call in life_world['calls']].count('teardown') == 4


def test_lane_bootstrap_record_is_failed_whenever_the_lane_is_rejected(life_world):
    life_world['bootstrap'][3] = (0, bootstrap_output(services={'postgresql': 'READY', 'temporal': 'DEGRADED'}))
    report = lifecycle(life_world, temporal_runner())
    assert report['status'] == 'FAIL'
    assert [entry['bootstrap']['status'] for entry in report['lanes']] == ['PASS', 'PASS', 'FAIL', 'PASS']
    life_world['calls'].clear()
    report = lifecycle(life_world, temporal_runner(serving=False))
    assert all(entry['bootstrap']['status'] == 'FAIL' for entry in report['lanes'])


def test_a_temporal_probe_that_times_out_once_does_not_end_the_observation(tmp_path):
    item = four_lanes(tmp_path)[0]
    inner = temporal_runner()
    probes = []

    def runner(argv, **kwargs):
        if 'health' in argv:
            probes.append(1)
            if len(probes) == 1:
                raise CAMPAIGN.CampaignError('command could not run: probe timed out after 15 s')
        return inner(argv, **kwargs)
    observed = LANES.observe_temporal_serving(item, '/p', runner, finished=lambda: False, wall=lambda: SERVING_WALL,
                                              sleep=lambda seconds: None, monotonic=FakeClock(0.0, 1.0))
    assert observed['serving'] is True and observed['polls'] == 2 and observed['probe_errors'] == 1


class WaitTimesOut(FakeProcess):
    """A bootstrap that never ends and whose wait after kill times out."""

    def __init__(self):
        super().__init__(0, None)

    def poll(self):
        return None

    def wait(self, timeout=None):
        import subprocess
        raise subprocess.TimeoutExpired('docker', timeout)


def test_lifecycle_check_stops_every_bootstrap_when_one_wait_times_out(life_world, monkeypatch):
    stubborn = WaitTimesOut()
    others = [FakeProcess(0, None) for _ in range(3)]
    pending = iter([stubborn, *others])
    life_world['bootstrap_launcher'] = lambda argv, log: (log.write_text(''), next(pending))[1]
    monkeypatch.setattr(LANES, 'LIFECYCLE_BOOTSTRAP_LIMIT_SECONDS', 0)
    report = lifecycle(life_world, temporal_runner(serving=False))
    assert report['status'] == 'FAIL' and 'lane 1' in report['error'] and 'did not stop' in report['error']
    assert stubborn.killed and all(process.killed for process in others)
    assert [call[0] for call in life_world['calls']].count('teardown') == 4


def test_lifecycle_check_translates_a_wait_timeout_in_the_cleanup(life_world):
    stubborn = WaitTimesOut()
    pending = iter([FakeProcess(0, None), stubborn, FakeProcess(0, None), FakeProcess(0, None)])
    started = []

    def launcher(argv, log):
        log.write_text('')
        if len(started) == 3:
            raise OSError('cannot start lane 4 bootstrap')
        started.append(next(pending))
        return started[-1]
    life_world['bootstrap_launcher'] = launcher
    report = lifecycle(life_world)
    assert report['status'] == 'FAIL' and 'lane 4' in report['error'] and 'lane 2' in report['error']
    assert all(process.killed for process in started)
    assert [call[0] for call in life_world['calls']].count('teardown') == 4


def test_supervision_translates_a_kill_that_does_not_stop_a_lane(tmp_path):
    lanes, clock = four_lanes(tmp_path), FakeClock(step=60.0)
    stubborn, stuck = WaitTimesOut(), FakeProcess(0, None)
    with pytest.raises(CAMPAIGN.CampaignError, match='lane 1'):
        LANES.supervise_lanes({1: stubborn, 2: FakeProcess(1, 0), 3: stuck, 4: FakeProcess(0, 0)}, lanes, clock.now,
                              clock=clock, sleep=clock.sleep)
    assert stubborn.killed and stuck.killed


def test_execute_records_a_lane_that_does_not_stop_and_tears_down_all(host_world, monkeypatch):
    host_world['meminfo'].write_text(FOUR_LANE_MEMINFO)
    monkeypatch.setattr(LANES, 'STOP_GRACE_SECONDS', 0)
    real = host_world['launcher']

    def launcher(argv, log):
        real(argv, log)
        return WaitTimesOut() if '/lane-1/' in argv[argv.index('--run-lane') + 1] else FakeProcess(1, 0)
    host_world['launcher'] = launcher
    result = execute(host_world)
    assert result['status'] == 'FAIL' and 'lane 1' in result['error'] and result == stored_result(host_world)
    assert [call[0] for call in host_world['calls']].count('teardown') == 4


@pytest.mark.parametrize('content', [b'[]', b'null', b'{}', b'"spec"', b'{"head": ', b'\xff\xfe{}'])
def test_lane_spec_refuses_a_document_that_is_not_a_spec_object(tmp_path, content):
    path = lane_spec(tmp_path)
    path.write_bytes(content)
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.load_lane_spec(path)


@pytest.mark.parametrize('change', [
    {'selection': [{}]}, {'selection': [['a::b']]}, {'selection': ['tests/a.py::t', 1]},
    {'campaign_start': True}, {'campaign_start': float('nan')}, {'campaign_start': float('inf')}, {'campaign_start': '1793000000'},
    {'stop_file': 5}, {'extra': 1}])
def test_lane_spec_takes_no_field_by_conversion(tmp_path, change):
    path = lane_spec(tmp_path)
    path.write_text(json.dumps({**json.loads(path.read_text()), **change}))
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.load_lane_spec(path)


@pytest.mark.parametrize('content', [b'[]', b'null', b'\xff\xfe{}', b'{"lane": 1, "campaign_start": NaN}'])
def test_lane_with_an_unreadable_spec_records_a_typed_failure(lane_world, tmp_path, content):
    spec = lane_spec(tmp_path)
    spec.write_bytes(content)
    assert run_lane(lane_world, spec) == 1
    result = assert_lane_failed(spec, 'lane spec')
    assert result['lane'] is None
    assert not [call for call in lane_world['calls'] if call[0] in ('run', 'pytest')]


def test_lane_stops_on_a_stop_request_that_is_not_utf8(lane_world, tmp_path):
    spec = lane_spec(tmp_path)
    (spec.parent / 'STOP').write_bytes(b'lane 2 failed \xff\n')
    assert run_lane(lane_world, spec) == 1
    assert_lane_failed(spec, 'stopped by the orchestrator')


def test_lane_service_environment_refuses_an_env_file_that_is_not_utf8(tmp_path):
    (tmp_path / '.ocor').mkdir()
    (tmp_path / '.ocor/bootstrap.env').write_bytes(b'OCOR_LOCAL_POSTGRES_PASSWORD=\xff\xfe\n')
    with pytest.raises(CAMPAIGN.CampaignError, match='env'):
        LANES.lane_service_environment(tmp_path)


@pytest.mark.parametrize('content', [b'[]', b'null', b'{}', b'"PASS"', b'{"status": ', b'\xff\xfe{}'])
def test_lane_results_refuse_a_document_that_is_not_a_result_object(tmp_path, content):
    lanes = four_lanes(tmp_path)
    parts = LANES.lane_partition(nodes(), weights(), lanes=4)
    for item, part in zip(lanes, parts):
        write_lane_result(item, part)
    (lanes[1].output / 'lane_result.json').write_bytes(content)
    with pytest.raises(CAMPAIGN.CampaignError, match='lane 2'):
        LANES.read_lane_results(lanes, HEAD, parts)


@pytest.mark.parametrize('change', [{'lane': True}, {'po_decision_required': 'false'}, {'po_decision_required': 0},
                                    {'po_decision_required': None}, {'selected': True}, {'selected': float('nan')}])
def test_lane_results_take_no_field_by_conversion(tmp_path, change):
    lanes = four_lanes(tmp_path)
    parts = LANES.lane_partition(nodes(), weights(), lanes=4)
    for item, part in zip(lanes, parts):
        write_lane_result(item, part)
    write_lane_result(lanes[0], parts[0], **change)
    with pytest.raises(CAMPAIGN.CampaignError, match='lane 1'):
        LANES.read_lane_results(lanes, HEAD, parts)


@pytest.mark.parametrize('content', [b'\xff\xfe{}', b'{"status": ', b'[]'])
def test_execute_records_a_corrupted_lane_result_and_tears_down_all(host_world, content):
    host_world['meminfo'].write_text(FOUR_LANE_MEMINFO)
    real = host_world['launcher']

    def launcher(argv, log):
        process = real(argv, log)
        if '/lane-2/' in argv[argv.index('--run-lane') + 1]:
            (Path(argv[argv.index('--run-lane') + 1]).parent / 'lane_result.json').write_bytes(content)
        return process
    host_world['launcher'] = launcher
    result = execute(host_world)
    assert result['status'] == 'FAIL' and 'lane 2' in result['error'] and result == stored_result(host_world)
    lane_two = next(entry for entry in result['lanes'] if entry['lane'] == 2)
    assert 'unreadable' in lane_two['result']
    assert [call[0] for call in host_world['calls']].count('teardown') == 4


@pytest.mark.parametrize('weights_doc', [
    [], {}, {'weights': []}, {'weights': {'a::b': '5'}}, {'weights': {'a::b': True}}, {'weights': {'a::b': -1}},
    {'weights': {'a::b': None}}])
def test_weights_file_takes_no_weight_by_conversion(tmp_path, weights_doc):
    path = tmp_path / 'lane_weights.json'
    path.write_text(json.dumps(weights_doc))
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.load_weights(path)


@pytest.mark.parametrize('content', [b'{"weights": {"a::b": NaN}}', b'{"weights": {"a::b": Infinity}}', b'\xff{}', b'{"weights": '])
def test_weights_file_refuses_non_finite_or_undecodable_content(tmp_path, content):
    path = tmp_path / 'lane_weights.json'
    path.write_bytes(content)
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.load_weights(path)
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.load_weights(tmp_path / 'absent.json')


@pytest.mark.parametrize('seconds', ['nan', 'inf', '-1', 'abc', '٢.5', ''])
def test_derived_weights_refuse_a_time_that_is_not_a_finite_ascii_number(tmp_path, seconds):
    junit = write_junit(tmp_path / 'm.xml', [('tests.tasks.test_a', 'test_x')])
    junit.write_text(junit.read_text().replace('time="0.1"', f'time="{seconds}"'))
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.derive_weights(junit)


def test_derived_weights_refuse_a_malformed_junit(tmp_path):
    junit = tmp_path / 'm.xml'
    junit.write_text('<testsuite><testcase')
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.derive_weights(junit)
    assert LANES.main(['--derive-weights', str(junit)]) == 1


@pytest.mark.parametrize('lock', [[], {}, {'tools': {}}, {'tools': [5]}, {'tools': [{'id': 'kind'}]},
                                  {'tools': [{'id': '../kind', 'binary_sha256': '0' * 64}]},
                                  {'tools': [{'id': 'kind', 'binary_sha256': 'ABC'}]}, {'tools': []}])
def test_lane_tools_lock_is_refused_when_malformed(tmp_path, lock):
    repo = tmp_path / 'repo'
    (repo / 'infra').mkdir(parents=True)
    (repo / 'infra/qualification_tools.lock.json').write_text(json.dumps(lock))
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.verify_lane_tools(repo)


def test_lane_tools_lock_that_is_not_utf8_is_refused(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'infra').mkdir(parents=True)
    (repo / 'infra/qualification_tools.lock.json').write_bytes(b'\xff{"tools": []}')
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.verify_lane_tools(repo)


def test_power_reading_with_an_undecodable_supply_is_not_executed(tmp_path):
    root = power_supplies(tmp_path, AC={'type': 'Mains', 'online': '1'})
    (root / 'AC/online').write_bytes(b'\xff\n')
    assert LANES.power_reading(root)['source'] == 'NOT_EXECUTED'


# --- local image cache: transfer locked host images, never pull (OCOR-DEV-REM-0061) ---
# Archives are OCI layouts. The image id is an index.json manifest digest plus
# its blob, never the classic manifest.json Config. A miss is an absent host
# image. An empty or inconsistent document fails closed.

DIGEST_A = 'ab' * 32
DIGEST_B = 'cd' * 32
PIN_A = f'openpolicyagent/opa@sha256:{DIGEST_A}'
PIN_B = f'ghcr.io/spiffe/spire-agent@sha256:{DIGEST_B}'
ID_A = f'sha256:{DIGEST_A}'
ID_B = f'sha256:{DIGEST_B}'
FUSEKI_BASE = 'eclipse-temurin@sha256:db1689535962d757a5adabf57387584ed543d38c0b9d1fe870123ea362ad73b0'


def canonical(document):
    return json.dumps(document, indent=2, sort_keys=True) + '\n'


def write_lock(path, services):
    path.write_text(canonical({'schema_version': '1.0', 'services': services}), encoding='utf-8')


def oci_tar(image_id, *, index_digest=None, include_index=True, include_blob=True, classic_config=None):
    """OCI layout whose index manifest digest defaults to image_id. Classic Config is a different blob."""
    claimed = index_digest or image_id
    hex_id = claimed.split(':', 1)[1]
    config_hex = classic_config or ('c' * 64)
    index = {'manifests': [{'digest': claimed, 'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'size': 2}],
             'schemaVersion': 2}
    classic = [{'Config': f'blobs/sha256/{config_hex}', 'Layers': [], 'RepoTags': None}]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        def add(name, payload):
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        add('oci-layout', {'imageLayoutVersion': '1.0.0'})
        if include_index:
            add('index.json', index)
        add('manifest.json', classic)
        if include_blob:
            add(f'blobs/sha256/{hex_id}', b'{}')
        add(f'blobs/sha256/{config_hex}', b'{"architecture":"amd64"}')
    return buffer.getvalue()


class CacheRunner:
    """Scripts host inspect and save. Save writes an OCI tar; it never pulls."""

    def __init__(self, images, *, tar_for=None, empty_inspect=()):
        self.calls = []
        self.images = images
        self.tar_for = tar_for or {}
        self.empty_inspect = set(empty_inspect)

    def __call__(self, argv, *, cwd=None, env=None, input=None, timeout=600, check=True):
        argv = [str(item) for item in argv]
        self.calls.append(argv)
        if argv[:3] == ['docker', 'image', 'inspect'] and len(argv) == 4:
            reference = argv[3]
            if reference in self.empty_inspect:
                return LANES.CommandResult(0, '')
            spec = self.images.get(reference)
            if spec is None or spec[0] != 0:
                if check:
                    raise CAMPAIGN.CampaignError(f'command failed (1): {argv[:6]}')
                return LANES.CommandResult(1, '')
            _code, image_id, digests, extra = spec
            document = {'Id': image_id, 'RepoDigests': digests, 'Os': 'linux'}
            document.update(extra)
            return LANES.CommandResult(0, json.dumps([document]))
        if argv[:4] == ['docker', 'image', 'save', '-o'] and len(argv) == 6:
            archive, reference = Path(argv[4]), argv[5]
            image_id = self.tar_for.get(reference, self.images[reference][1])
            archive.write_bytes(image_id if isinstance(image_id, bytes) else oci_tar(image_id))
            return LANES.CommandResult(0, '')
        raise CAMPAIGN.CampaignError(f'unexpected command: {argv}')


def present(reference, digest, *, digests=None, extra=None):
    return (0, f'sha256:{digest}', list(digests if digests is not None else [reference]), extra or {})


def services_for(*pins):
    return [{'id': service_id, 'image': reference} for service_id, reference in pins]


def test_serial_fallback_does_not_prepare_an_image_cache(host_world):
    host_world['meminfo'].write_text(meminfo(31743008, 1000))
    result = execute(host_world)
    assert result['status'] == 'SERIAL_FALLBACK'
    assert not [call for call in host_world['calls'] if call[0] in ('prepare_image_cache', 'image_cache')]


def test_each_lane_receives_the_shared_cache_as_a_read_only_mount(host_world):
    execute(host_world, selection=nodes())
    cache = str(host_world['work'] / 'image-cache')
    assert host_world['readonly_mounts'] == [(1, [cache]), (2, [cache])]


def test_lifecycle_mounts_the_shared_cache_read_only_for_every_lane(life_world):
    report = lifecycle(life_world)
    assert report['status'] == 'PASS', report.get('error')
    cache = str(life_world['work'] / 'image-cache')
    assert life_world['readonly_mounts'] == [(index, [cache]) for index in range(1, 5)]


def test_each_lane_is_seeded_after_its_sandbox_and_before_launch(host_world):
    execute(host_world, selection=nodes())
    calls = [call[0] for call in host_world['calls']]
    assert calls.count('prepare_image_cache') == 1
    assert calls.index('root_image') < calls.index('prepare_image_cache') < calls.index('provision')
    pending = False
    seeds = 0
    for call in calls:
        if call == 'sandbox':
            pending = True
        elif call == 'image_cache':
            assert pending
            pending = False
            seeds += 1
        elif call == 'launch':
            assert not pending
    assert seeds == 2 and calls.count('launch') == 2


def test_lifecycle_seeds_every_sandbox_before_bootstrap(life_world):
    report = lifecycle(life_world)
    assert report['status'] == 'PASS', report.get('error')
    calls = [call[0] for call in life_world['calls']]
    assert calls.count('prepare_image_cache') == 1 and calls.count('image_cache') == 4
    assert calls.index('prepare_image_cache') < calls.index('sandbox')
    assert max(i for i, call in enumerate(calls) if call == 'image_cache') < calls.index('bootstrap')


def test_bootstrap_pull_and_the_lane_bootstrap_budget_stay_unchanged():
    source = (ROOT / 'scripts/bootstrap_ci_environment.py').read_text(encoding='utf-8')
    assert '["docker", "pull", service["image"]]' in source
    assert '"--pull"' in source
    assert LANES.LANE_BOOTSTRAP == (
        ['scripts/bootstrap_ci_environment.py', '--teardown', '--execute'],
        ['scripts/bootstrap_ci_environment.py', '--execute', '--timeout', '600'])
    assert LANES.FULL_SUITE_LIMIT_SECONDS == 5400 and LANES.PROVISION_TIMEOUT_SECONDS == 1200
    cache_source = (ROOT / 'scripts/local_lane_image_cache.py').read_text(encoding='utf-8')
    lane_source = (ROOT / 'scripts/run_local_lane_campaign.py').read_text(encoding='utf-8')
    assert '"docker", "pull"' not in cache_source and '"docker", "build"' not in cache_source
    assert 'FULL_SUITE_LIMIT_SECONDS = campaign.FULL_SUITE_LIMIT_SECONDS' in lane_source


def test_image_cache_transfer_does_not_restart_the_campaign_clock(host_world, monkeypatch):
    ticks = {'n': 0}
    base = LANES.time.time()

    def now():
        ticks['n'] += 1
        return base + ticks['n']

    monkeypatch.setattr(LANES.time, 'time', now)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'PASS', result.get('error')
    assert result['campaign_start'] == base + 1 and ticks['n'] > 1


def test_image_cache_transfer_stops_at_the_existing_campaign_deadline(host_world, monkeypatch):
    calls = {'n': 0}

    def now():
        calls['n'] += 1
        if calls['n'] == 1:
            return 5_000.0
        return 5_000.0 + LANES.FULL_SUITE_LIMIT_SECONDS + 1

    monkeypatch.setattr(LANES.time, 'time', now)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL'
    assert result['error'] == 'campaign deadline exhausted during image cache transfer'
    names = [call[0] for call in host_world['calls']]
    assert 'prepare_image_cache' in names
    assert 'sandbox' not in names and 'launch' not in names


@pytest.mark.parametrize('result', [None, True, 1.5, SimpleNamespace(returncode=True, stdout=''),
                                     SimpleNamespace(returncode=1.5, stdout=''),
                                     SimpleNamespace(returncode=0, stdout=None),
                                     SimpleNamespace(returncode=0, stdout=b'ok'),
                                     SimpleNamespace(returncode=None, stdout='')])
def test_seed_refuses_a_docker_result_that_is_not_a_code_and_text(tmp_path, monkeypatch, result):
    cache = tmp_path / 'cache'
    cache.mkdir()
    lock = tmp_path / 'services.lock.json'
    lock.write_text('{}\n', encoding='utf-8')
    image_id = 'sha256:' + 'ab' * 32

    def verify(cache_dir, lock_path):
        return {'images': [{
            'archive': 'opa-pinned_pull.tar', 'image_id': image_id, 'service_id': 'opa', 'status': 'PRESENT',
        }]}

    monkeypatch.setattr(LANES.image_cache, 'verify_image_cache', verify)

    def runner(argv, **kwargs):
        return result

    lane = LANES.Lane(index=1, campaign='a' * 12 + '-1', root=tmp_path / 'lane', home=tmp_path / 'home', uid=1, gid=1)
    with pytest.raises(CAMPAIGN.CampaignError, match='image cache load failed: opa: image cache command result is malformed'):
        LANES.seed_lane_images(lane, '/usr/bin:/bin', cache, lock, runner, timeout=5)


def test_execute_fails_closed_when_the_image_cache_load_fails(host_world, monkeypatch):
    def seed(item, path, cache_dir, lock_path, runner, *, timeout):
        host_world['calls'].append(('image_cache', item.index))
        raise CAMPAIGN.CampaignError('image cache load failed: opa: command failed (1)')

    monkeypatch.setattr(LANES, 'seed_lane_images', seed)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL' and 'image cache load failed: opa' in result['error']
    names = [call[0] for call in host_world['calls']]
    assert 'launch' not in names and names.count('teardown') == 2


def test_cache_repo_lock_pins_the_fuseki_base_and_every_service_image():
    document = json.loads((ROOT / 'infra/services.lock.json').read_text(encoding='utf-8'))
    pins = IMAGE_CACHE.locked_image_pins(document)
    expected = []
    for service in document['services']:
        if 'image' in service:
            expected.append((service['id'], 'pinned_pull', service['image']))
        if service['id'] == 'fuseki':
            expected.append((service['id'], 'fuseki_base', service['build']['base_image']))
    assert [(item['service_id'], item['role'], item['pinned_reference']) for item in pins] == expected
    assert len(pins) == 14
    fuseki = next(item for item in pins if item['service_id'] == 'fuseki')
    assert fuseki['role'] == 'fuseki_base' and fuseki['pinned_reference'] == FUSEKI_BASE
    assert all('ocor/jena-fuseki' not in item['pinned_reference'] for item in pins)


def test_cache_rejects_a_service_with_neither_image_nor_fuseki_base():
    with pytest.raises(CAMPAIGN.CampaignError, match='neither a pinned image nor a Fuseki base image'):
        IMAGE_CACHE.locked_image_pins({'services': [{'id': 'orphan'}]})
    with pytest.raises(CAMPAIGN.CampaignError, match='Fuseki base image is missing'):
        IMAGE_CACHE.locked_image_pins({'services': [{'id': 'fuseki', 'build': {}}]})
    with pytest.raises(CAMPAIGN.CampaignError, match='malformed pinned reference'):
        IMAGE_CACHE.locked_image_pins({'services': [{'id': 'fuseki', 'build': {'base_image': 'ocor/jena-fuseki:6.2.0'}}]})


@pytest.mark.parametrize('reference', [
    '',
    'openpolicyagent/opa:latest',
    'openpolicyagent/opa@sha256:' + 'AB' * 32,
    'openpolicyagent/opa@sha256:' + 'ab' * 31,
    'openpolicyagent/opa@sha256:' + 'gg' * 32,
    'pä@sha256:' + 'ab' * 32,
    'Openpolicyagent/opa@sha256:' + 'ab' * 32,
    'opa@sha256:' + 'ab' * 32 + ' ',
])
def test_cache_rejects_a_malformed_pinned_reference_before_compare(reference):
    text = json.dumps([{'Id': ID_A, 'RepoDigests': [reference]}])
    with pytest.raises(CAMPAIGN.CampaignError, match='malformed pinned reference'):
        IMAGE_CACHE.parse_host_inspect(text, reference)


def test_cache_prepares_a_valid_archive_and_verifies_it(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A), ('spire-agent', PIN_B)))
    runner = CacheRunner({PIN_A: present(PIN_A, DIGEST_A), PIN_B: present(PIN_B, DIGEST_B, extra={'Size': 3})})
    manifest = IMAGE_CACHE.prepare_image_cache(lock, tmp_path / 'image-cache', runner, timeout=1200)
    assert manifest['schema'] == 'ocor-local-lane-image-cache/v1'
    assert manifest['lock_sha256'] == hashlib.sha256(lock.read_bytes()).hexdigest()
    assert [item['status'] for item in manifest['images']] == ['PRESENT', 'PRESENT']
    assert manifest['images'][0]['image_id'] == ID_A
    assert manifest['images'][0]['archive'] == 'opa-pinned_pull.tar'
    stored = json.loads((tmp_path / 'image-cache' / 'manifest.json').read_text(encoding='utf-8'))
    assert stored == manifest
    assert (tmp_path / 'image-cache' / 'manifest.json').read_text(encoding='utf-8') == canonical(manifest)
    verified = IMAGE_CACHE.verify_image_cache(tmp_path / 'image-cache', lock)
    assert verified == manifest
    assert not any('pull' in argv or 'build' in argv for argv in runner.calls)


def test_cache_missing_image_is_a_cold_miss_without_save_or_pull(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A)))
    runner = CacheRunner({})
    manifest = IMAGE_CACHE.prepare_image_cache(lock, tmp_path / 'image-cache', runner, timeout=lambda: 30)
    assert manifest['images'] == [{
        'pinned_reference': PIN_A, 'role': 'pinned_pull', 'service_id': 'opa', 'status': 'MISS'}]
    assert runner.calls == [['docker', 'image', 'inspect', PIN_A]]
    assert list((tmp_path / 'image-cache').iterdir()) == [tmp_path / 'image-cache' / 'manifest.json']


def test_cache_empty_inspect_is_not_a_miss(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A)))
    runner = CacheRunner({PIN_A: present(PIN_A, DIGEST_A)}, empty_inspect={PIN_A})
    with pytest.raises(CAMPAIGN.CampaignError, match='not valid JSON'):
        IMAGE_CACHE.prepare_image_cache(lock, tmp_path / 'image-cache', runner, timeout=30)
    assert not (tmp_path / 'image-cache').exists()
    assert not any(argv[2] == 'save' for argv in runner.calls if len(argv) > 2)


def test_cache_rejects_an_image_id_that_differs_from_the_locked_digest(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A)))
    runner = CacheRunner({PIN_A: present(PIN_A, DIGEST_B, digests=[PIN_A])})
    with pytest.raises(CAMPAIGN.CampaignError, match='image id does not match the locked digest'):
        IMAGE_CACHE.prepare_image_cache(lock, tmp_path / 'image-cache', runner, timeout=30)
    assert not any(len(argv) > 2 and argv[2] == 'save' for argv in runner.calls)


def test_cache_rejects_a_pinned_reference_absent_from_repo_digests():
    text = json.dumps([{'Id': ID_A, 'RepoDigests': [PIN_B], 'RepoTags': ['opa:local']}])
    with pytest.raises(CAMPAIGN.CampaignError, match='pinned reference is absent from RepoDigests'):
        IMAGE_CACHE.parse_host_inspect(text, PIN_A)


def test_cache_rejects_an_altered_archive(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A)))
    runner = CacheRunner({PIN_A: present(PIN_A, DIGEST_A)})
    cache = tmp_path / 'image-cache'
    IMAGE_CACHE.prepare_image_cache(lock, cache, runner, timeout=30)
    archive = cache / 'opa-pinned_pull.tar'
    archive.write_bytes(archive.read_bytes()[:-1] + bytes([archive.read_bytes()[-1] ^ 0x01]))
    with pytest.raises(CAMPAIGN.CampaignError, match='image cache archive is altered'):
        IMAGE_CACHE.verify_image_cache(cache, lock)


def test_cache_rejects_an_archive_whose_oci_index_digest_differs(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A)))
    runner = CacheRunner({PIN_A: present(PIN_A, DIGEST_A)}, tar_for={PIN_A: oci_tar(ID_A, index_digest=ID_B)})
    with pytest.raises(CAMPAIGN.CampaignError, match='image cache archive image id does not match'):
        IMAGE_CACHE.prepare_image_cache(lock, tmp_path / 'image-cache', runner, timeout=30)
    assert not (tmp_path / 'image-cache').exists()


def test_cache_rejects_a_classic_config_blob_as_the_image_id(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A)))
    payload = oci_tar(ID_A, index_digest=ID_B, classic_config=DIGEST_A)
    runner = CacheRunner({PIN_A: present(PIN_A, DIGEST_A)}, tar_for={PIN_A: payload})
    with pytest.raises(CAMPAIGN.CampaignError, match='image cache archive image id does not match'):
        IMAGE_CACHE.prepare_image_cache(lock, tmp_path / 'image-cache', runner, timeout=30)


def test_cache_rejects_a_load_error(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A)))
    builder = CacheRunner({PIN_A: present(PIN_A, DIGEST_A)})
    cache = tmp_path / 'image-cache'
    IMAGE_CACHE.prepare_image_cache(lock, cache, builder, timeout=30)

    class LoadRunner:
        def __init__(self):
            self.calls = []

        def __call__(self, argv, *, cwd=None, env=None, input=None, timeout=600, check=True):
            argv = [str(item) for item in argv]
            self.calls.append(argv)
            if 'load' in argv:
                raise CAMPAIGN.CampaignError(f'command failed (1): {argv[:6]}')
            if argv[-3:] == ['docker', 'image', 'inspect']:
                return LANES.CommandResult(0, json.dumps([{'Id': ID_A, 'RepoDigests': []}]))
            raise CAMPAIGN.CampaignError(f'unexpected command: {argv}')

    runner = LoadRunner()
    with pytest.raises(CAMPAIGN.CampaignError, match='image cache load failed: opa'):
        LANES.seed_lane_images(lane(tmp_path), '/usr/bin', cache, lock, runner, timeout=1200)
    assert runner.calls and 'load' in runner.calls[0]
    assert all('pull' not in argv for argv in runner.calls)


def test_cache_seed_skips_load_for_a_miss_and_checks_a_loaded_id(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A), ('spire-agent', PIN_B)))
    builder = CacheRunner({PIN_A: present(PIN_A, DIGEST_A)})
    cache = tmp_path / 'image-cache'
    IMAGE_CACHE.prepare_image_cache(lock, cache, builder, timeout=30)

    class SeedRunner:
        def __init__(self, ident):
            self.ident = ident
            self.calls = []

        def __call__(self, argv, *, cwd=None, env=None, input=None, timeout=600, check=True):
            argv = [str(item) for item in argv]
            self.calls.append(argv)
            if 'load' in argv:
                return LANES.CommandResult(0, '')
            return LANES.CommandResult(0, json.dumps([{'Id': self.ident, 'Os': 'linux'}]))

    loaded = SeedRunner(ID_A)
    seeded = LANES.seed_lane_images(lane(tmp_path), '/usr/bin', cache, lock, loaded, timeout=lambda: 50)
    assert seeded == {'loaded': ['opa'], 'misses': ['spire-agent']}
    assert len(loaded.calls) == 2 and 'load' in loaded.calls[0] and loaded.calls[1][-1] == ID_A
    mismatched = SeedRunner(ID_B)
    with pytest.raises(CAMPAIGN.CampaignError, match='loaded image id does not match the cache'):
        LANES.seed_lane_images(lane(tmp_path), '/usr/bin', cache, lock, mismatched, timeout=50)


@pytest.mark.parametrize(('document', 'match'), [
    ('null', 'one-element list'),
    ('{}', 'one-element list'),
    ('[]', 'one-element list'),
    (json.dumps([{'Id': ID_A}, {'Id': ID_A}]), 'one-element list'),
    ('[null]', 'element is null'),
    ('[{}]', 'image id is missing'),
    (json.dumps([{'RepoDigests': [PIN_A]}]), 'image id is missing'),
    (json.dumps([{'Id': True, 'RepoDigests': [PIN_A]}]), 'image id is not a string'),
    (json.dumps([{'Id': 1, 'RepoDigests': [PIN_A]}]), 'image id is not a string'),
    (json.dumps([{'Id': 1.5, 'RepoDigests': [PIN_A]}]), 'image id is not a string'),
    (json.dumps([{'Id': '', 'RepoDigests': [PIN_A]}]), 'image id is not a digest'),
    (json.dumps([{'Id': 'sha256:' + 'AB' * 32, 'RepoDigests': [PIN_A]}]), 'image id is not a digest'),
    (json.dumps([{'Id': ID_A, 'RepoDigests': {}}]), 'RepoDigests is not a list of strings'),
    (json.dumps([{'Id': ID_A, 'RepoDigests': None}]), 'RepoDigests is not a list of strings'),
    (json.dumps([{'Id': ID_A, 'RepoDigests': [None]}]), 'RepoDigests is not a list of strings'),
    (json.dumps([{'Id': ID_A, 'RepoDigests': [{}]}]), 'RepoDigests is not a list of strings'),
    (json.dumps([{'Id': ID_A}]), 'RepoDigests is not a list of strings'),
    (json.dumps([{'Id': ID_A, 'RepoDigests': [PIN_A]}]) + '\n{}', 'not valid JSON'),
])
def test_cache_rejects_inspect_documents_with_the_wrong_shape(document, match):
    with pytest.raises(CAMPAIGN.CampaignError, match=match):
        IMAGE_CACHE.parse_host_inspect(document, PIN_A)


def test_cache_rejects_a_lone_surrogate_before_digest_compare():
    raw = '[{"Id": "%s", "RepoDigests": ["%s"], "nested": {"labels": ["\\uD800"]}}]' % (ID_A, PIN_B)
    with pytest.raises(CAMPAIGN.CampaignError, match='lone surrogate'):
        IMAGE_CACHE.parse_host_inspect(raw, PIN_A)
    key = '[{"Id": "%s", "RepoDigests": ["%s"], "\\uD800": 1}]' % (ID_A, PIN_A)
    with pytest.raises(CAMPAIGN.CampaignError, match='lone surrogate'):
        IMAGE_CACHE.parse_host_inspect(key, PIN_A)


def test_cache_accepts_a_valid_surrogate_pair_in_an_unused_field():
    raw = '[{"Id": "%s", "RepoDigests": ["%s"], "note": "\\uD800\\uDC00"}]' % (ID_A, PIN_A)
    assert IMAGE_CACHE.parse_host_inspect(raw, PIN_A) == ID_A
    loaded = '[{"Id": "%s", "RepoDigests": [], "note": "\\uD800\\uDC00"}]' % ID_A
    IMAGE_CACHE.parse_loaded_inspect(loaded, ID_A)


def test_cache_rejects_duplicate_keys_nan_and_trailing_junk():
    duplicate = '[{"Id": "%s", "Id": "%s", "RepoDigests": ["%s"]}]' % (ID_A, ID_B, PIN_A)
    with pytest.raises(CAMPAIGN.CampaignError, match='duplicate key'):
        IMAGE_CACHE.parse_host_inspect(duplicate, PIN_A)
    nan = '[{"Id": "%s", "RepoDigests": ["%s"], "Size": NaN}]' % (ID_A, PIN_A)
    with pytest.raises(CAMPAIGN.CampaignError, match='non-finite JSON number'):
        IMAGE_CACHE.parse_host_inspect(nan, PIN_A)
    with pytest.raises(CAMPAIGN.CampaignError, match='not valid JSON'):
        IMAGE_CACHE.parse_host_inspect('', PIN_A)


def test_cache_loaded_inspect_rejects_a_bool_digest_list_and_accepts_no_repo_digests():
    with pytest.raises(CAMPAIGN.CampaignError, match='RepoDigests is not a list of strings'):
        IMAGE_CACHE.parse_loaded_inspect(json.dumps([{'Id': ID_A, 'RepoDigests': True}]), ID_A)
    with pytest.raises(CAMPAIGN.CampaignError, match='element is null'):
        IMAGE_CACHE.parse_loaded_inspect('[null]', ID_A)
    IMAGE_CACHE.parse_loaded_inspect(json.dumps([{'Id': ID_A, 'RepoDigests': []}]), ID_A)
    with pytest.raises(CAMPAIGN.CampaignError, match='image id is not a digest'):
        IMAGE_CACHE.parse_loaded_inspect(json.dumps([{'Id': ID_A}]), 'sha256:' + 'AB' * 32)


def test_cache_rejects_an_existing_destination_a_bad_lock_and_a_hash_mismatch(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A)))
    destination = tmp_path / 'image-cache'
    destination.mkdir()
    runner = CacheRunner({PIN_A: present(PIN_A, DIGEST_A)})
    with pytest.raises(CAMPAIGN.CampaignError, match='image cache destination exists'):
        IMAGE_CACHE.prepare_image_cache(lock, destination, runner, timeout=30)
    assert destination.exists() and runner.calls == []
    destination.rmdir()
    lock.write_bytes(b'\xff{"services": []}')
    with pytest.raises(CAMPAIGN.CampaignError, match='not UTF-8'):
        IMAGE_CACHE.prepare_image_cache(lock, destination, runner, timeout=30)
    write_lock(lock, services_for(('opa', PIN_A)))
    IMAGE_CACHE.prepare_image_cache(lock, destination, runner, timeout=30)
    original = lock.read_bytes()
    lock.write_text(canonical({'schema_version': '1.0', 'services': services_for(('opa', PIN_B))}), encoding='utf-8')
    with pytest.raises(CAMPAIGN.CampaignError, match='image cache lock hash does not match'):
        IMAGE_CACHE.verify_image_cache(destination, lock)
    lock.write_bytes(original)
    manifest_path = destination / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['images'][0]['pinned_reference'] = PIN_B
    manifest['images'][0]['image_id'] = ID_B
    manifest_path.write_text(canonical(manifest), encoding='utf-8')
    with pytest.raises(CAMPAIGN.CampaignError, match='image cache pin list does not match the lock'):
        IMAGE_CACHE.verify_image_cache(destination, lock)


def test_cache_manifest_rejects_extra_keys_and_a_miss_that_claims_an_archive(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A)))
    runner = CacheRunner({})
    cache = tmp_path / 'image-cache'
    manifest = IMAGE_CACHE.prepare_image_cache(lock, cache, runner, timeout=30)
    manifest['extra'] = 1
    (cache / 'manifest.json').write_text(canonical(manifest), encoding='utf-8')
    with pytest.raises(CAMPAIGN.CampaignError, match='malformed'):
        IMAGE_CACHE.verify_image_cache(cache, lock)
    del manifest['extra']
    manifest['images'][0]['archive'] = 'opa-pinned_pull.tar'
    (cache / 'manifest.json').write_text(canonical(manifest), encoding='utf-8')
    with pytest.raises(CAMPAIGN.CampaignError, match='malformed'):
        IMAGE_CACHE.verify_image_cache(cache, lock)


def test_cache_stops_before_a_command_when_the_timeout_callback_refuses(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A)))
    runner = CacheRunner({PIN_A: present(PIN_A, DIGEST_A)})

    def refuse():
        raise CAMPAIGN.CampaignError('campaign deadline exhausted during image cache transfer')

    with pytest.raises(CAMPAIGN.CampaignError, match='campaign deadline exhausted during image cache transfer'):
        IMAGE_CACHE.prepare_image_cache(lock, tmp_path / 'image-cache', runner, timeout=refuse)
    assert not (tmp_path / 'image-cache').exists()
    assert runner.calls == []


@pytest.mark.parametrize('result', [None, True, 1.5, SimpleNamespace(returncode=True, stdout=''),
                                     SimpleNamespace(returncode=1.5, stdout=''),
                                     SimpleNamespace(returncode=0, stdout=None),
                                     SimpleNamespace(returncode=0, stdout=b'ok'),
                                     SimpleNamespace(returncode=None, stdout='')])
def test_cache_rejects_a_command_result_that_is_not_a_code_and_text(tmp_path, result):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, services_for(('opa', PIN_A)))

    class BadRunner:
        def __call__(self, argv, *, cwd=None, env=None, input=None, timeout=600, check=True):
            del argv, cwd, env, input, timeout, check
            return result

    with pytest.raises(CAMPAIGN.CampaignError, match='image cache command result is malformed'):
        IMAGE_CACHE.prepare_image_cache(lock, tmp_path / 'image-cache', BadRunner(), timeout=5)
    assert not (tmp_path / 'image-cache').exists()


def test_cache_does_not_pull_or_build_while_preparing(tmp_path):
    lock = tmp_path / 'services.lock.json'
    write_lock(lock, [{'id': 'fuseki', 'build': {'base_image': FUSEKI_BASE}}])
    runner = CacheRunner({FUSEKI_BASE: present(FUSEKI_BASE, FUSEKI_BASE.rsplit(':', 1)[1])})
    manifest = IMAGE_CACHE.prepare_image_cache(lock, tmp_path / 'image-cache', runner, timeout=15)
    assert manifest['images'][0]['role'] == 'fuseki_base'
    assert manifest['images'][0]['archive'] == 'fuseki-fuseki_base.tar'
    assert all(argv[:3] == ['docker', 'image', 'inspect'] or argv[:4] == ['docker', 'image', 'save', '-o'] for argv in runner.calls)
    assert not any('pull' in argv or 'build' in argv for argv in runner.calls)


@pytest.mark.parametrize('check', [True, False])
def test_command_output_is_decoded_as_strict_utf8(check):
    assert LANES.run_command([sys.executable, '-c', 'print("SERVING")'], check=check) == LANES.CommandResult(0, 'SERVING\n')
    with pytest.raises(CAMPAIGN.CampaignError, match='UTF-8'):
        LANES.run_command([sys.executable, '-c', 'import sys; sys.stdout.buffer.write(b"SERV\\xffING")'], check=check)


# Measured on campaign-46835be (image cache) and the rem-0061 worktree at 2baa4aa
# (checkout without the venv, and the venv). Tools is the published 181 MiB mount.
TMP_IMAGE_CACHE_BYTES = 1_790_746_974
TMP_LANE_CHECKOUT_BYTES = 1_242_693_615
TMP_LANE_VENV_BYTES = 1_052_242_023
TMP_LANE_TOOLS_BYTES = 181 * 1024 * 1024
TMP_LANE_MARGIN_BYTES = 1024 ** 3


def tmp_budget(lanes):
    per_lane = TMP_LANE_CHECKOUT_BYTES + TMP_LANE_VENV_BYTES + TMP_LANE_TOOLS_BYTES
    return TMP_IMAGE_CACHE_BYTES + lanes * per_lane + TMP_LANE_MARGIN_BYTES


def tight_tmp_reading():
    return {
        'path': '/tmp', 'filesystem_free_bytes': 30_000_000_000, 'usrquota': True,
        'quota': {'hard_bytes': 8_000_000_000, 'used_bytes': 7_000_000_000, 'free_bytes': 1_000_000_000},
        'quota_error': None, 'free_bytes': 1_000_000_000,
    }


def patch_tmp_space(monkeypatch, reading, *, same):
    monkeypatch.setattr(LANES, 'measure_tmp_space', lambda path=Path('/tmp'): reading, raising=False)
    monkeypatch.setattr(LANES, '_same_device', lambda left, right: same, raising=False)


def test_tmp_lane_budget_uses_the_measured_sizes():
    assert LANES.TMP_IMAGE_CACHE_BYTES == TMP_IMAGE_CACHE_BYTES
    assert LANES.TMP_LANE_CHECKOUT_BYTES == TMP_LANE_CHECKOUT_BYTES
    assert LANES.TMP_LANE_VENV_BYTES == TMP_LANE_VENV_BYTES
    assert LANES.TMP_LANE_TOOLS_BYTES == TMP_LANE_TOOLS_BYTES
    assert LANES.TMP_LANE_MARGIN_BYTES == TMP_LANE_MARGIN_BYTES
    assert LANES.tmp_lane_budget_bytes(2) == tmp_budget(2)
    assert LANES.tmp_lane_budget_bytes(4) == tmp_budget(4)
    with pytest.raises(CAMPAIGN.CampaignError):
        LANES.tmp_lane_budget_bytes(3)


def test_usrquota_follows_the_longest_mount_and_the_super_options():
    table = (
        '25 1 8:1 / / rw,relatime - ext4 /dev/sda1 rw\n'
        '36 25 0:32 / /tmp rw,nosuid,nodev shared:16 - tmpfs tmpfs '
        'rw,nosuid,nodev,size=32099836k,nr_inodes=1048576,inode64,usrquota\n'
    )
    assert LANES.usrquota_in_mountinfo(table, Path('/tmp')) is True
    assert LANES.usrquota_in_mountinfo(table, Path('/tmp/ocor-verify/lane-2')) is True
    assert LANES.usrquota_in_mountinfo(table, Path('/home/luca')) is False
    plain = '36 25 0:32 / /tmp rw,nosuid,nodev - tmpfs tmpfs rw,nosuid,nodev,size=32099836k\n'
    assert LANES.usrquota_in_mountinfo(plain, Path('/tmp')) is False
    escaped = '40 25 0:33 / /tmp/lane\\040a rw,usrquota - tmpfs tmpfs rw\n'
    assert LANES.usrquota_in_mountinfo(escaped, Path('/tmp/lane a/repo')) is True
    assert LANES.usrquota_in_mountinfo('', Path('/tmp')) is False
    assert LANES.usrquota_in_mountinfo('not a mount line\n', Path('/tmp')) is False
    assert LANES.usrquota_in_mountinfo('36 25 0:32 / /tmp rw,usrquota\n', Path('/tmp')) is False


def test_quota_free_bytes_treats_the_hard_limit_as_kibibytes():
    assert LANES.quota_free_bytes(25679868, 1_143_410_688, 0x3F) == 25679868 * 1024 - 1_143_410_688
    assert LANES.quota_free_bytes(0, 10, 0x3F) is None
    assert LANES.quota_free_bytes(10, 10 * 1024 + 5, 0x3F) == 0
    with pytest.raises(CAMPAIGN.CampaignError, match='not valid'):
        LANES.quota_free_bytes(1, 0, 0)
    with pytest.raises(CAMPAIGN.CampaignError, match='malformed'):
        LANES.quota_free_bytes(True, 0, 0x3F)


def _hook_unlimited_tmp_quota(monkeypatch, filesystem_free):
    """usrquota on, hard limit unset, filesystem free forced. The real measure runs."""

    class Stats:
        f_bavail = filesystem_free
        f_frsize = 1

    monkeypatch.setattr(LANES.os, 'statvfs', lambda path: Stats())
    monkeypatch.setattr(LANES, 'mount_has_usrquota', lambda path: True)
    monkeypatch.setattr(LANES, '_read_user_quota', lambda path: {
        'hard_kib': 0, 'hard_bytes': None, 'used_bytes': 0, 'free_bytes': None, 'valid': 0x3F,
    })


def test_read_user_quota_refuses_a_failed_syscall(monkeypatch, tmp_path):
    def failed(number, descriptor, command, uid, ref):
        del number, descriptor, command, uid, ref
        LANES.ctypes.set_errno(1)
        return -1

    class Lib:
        syscall = staticmethod(failed)

    monkeypatch.setattr(LANES.ctypes, 'CDLL', lambda name, use_errno=True: Lib())
    monkeypatch.setattr(LANES.os, 'uname', lambda: type('Uname', (), {'machine': 'x86_64'})())
    with pytest.raises(CAMPAIGN.CampaignError, match='quotactl_fd failed: errno 1'):
        LANES._read_user_quota(tmp_path)


def test_read_user_quota_reports_an_unset_hard_limit_as_unlimited(monkeypatch, tmp_path):
    def succeed(number, descriptor, command, uid, ref):
        del number, descriptor, command, uid
        block = ref._obj
        block.dqb_bhardlimit = 0
        block.dqb_curspace = 0
        block.dqb_valid = LANES.QIF_BLIMITS | LANES.QIF_SPACE
        return 0

    class Lib:
        syscall = staticmethod(succeed)

    monkeypatch.setattr(LANES.ctypes, 'CDLL', lambda name, use_errno=True: Lib())
    monkeypatch.setattr(LANES.os, 'uname', lambda: type('Uname', (), {'machine': 'x86_64'})())
    quota = LANES._read_user_quota(tmp_path)
    assert quota['hard_kib'] == 0 and quota['hard_bytes'] is None and quota['free_bytes'] is None


def test_measure_tmp_space_keeps_an_unlimited_quota_distinct_from_filesystem_free(monkeypatch):
    _hook_unlimited_tmp_quota(monkeypatch, 1)
    reading = LANES.measure_tmp_space(Path('/tmp'))
    assert reading['filesystem_free_bytes'] == 1
    assert reading['usrquota'] is True and reading['quota_error'] is None
    assert reading['quota']['hard_kib'] == 0 and reading['quota']['free_bytes'] is None
    assert reading['free_bytes'] is None
    assert reading['quota_unlimited'] is True


def test_lane_launch_refuses_an_unlimited_quota_when_filesystem_free_is_below_the_budget(host_world, monkeypatch):
    """An unset hard limit removes only the quota check. The filesystem limit stays."""
    _hook_unlimited_tmp_quota(monkeypatch, 1)
    monkeypatch.setattr(LANES, '_same_device', lambda left, right: True, raising=False)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL'
    assert 'tmp space is not enough' in result['error']
    assert 'filesystem free 1 bytes' in result['error']
    assert f'required {tmp_budget(2)} bytes for 2 lanes' in result['error']
    assert 'unlimited' in result['error']
    names = [call[0] for call in host_world['calls']]
    assert 'prepare_image_cache' not in names and 'provision' not in names and 'root_image' not in names


def test_lane_launch_admits_an_unlimited_quota_when_filesystem_free_is_above_the_budget(host_world, monkeypatch):
    _hook_unlimited_tmp_quota(monkeypatch, tmp_budget(2) + 1)
    monkeypatch.setattr(LANES, '_same_device', lambda left, right: True, raising=False)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'PASS', result.get('error')
    assert result['tmp_space']['decision'] == 'enough' and result['tmp_space']['quota_unlimited'] is True
    assert result['tmp_space']['filesystem_free_bytes'] == tmp_budget(2) + 1
    assert 'prepare_image_cache' in [call[0] for call in host_world['calls']]


def test_lane_launch_refuses_a_short_filesystem_when_the_hard_limit_is_unset(host_world, monkeypatch):
    """A caller-supplied free_bytes does not waive a short /tmp filesystem."""
    patch_tmp_space(monkeypatch, {
        'path': '/tmp', 'filesystem_free_bytes': 1, 'usrquota': True,
        'quota': {'hard_kib': 0, 'hard_bytes': None, 'used_bytes': 0, 'free_bytes': None},
        'quota_error': None, 'free_bytes': 1,
    }, same=True)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL'
    assert 'tmp space is not enough' in result['error']
    assert 'filesystem free 1 bytes' in result['error']
    assert 'unlimited' in result['error']
    assert f'required {tmp_budget(2)} bytes for 2 lanes' in result['error']
    names = [call[0] for call in host_world['calls']]
    assert 'prepare_image_cache' not in names and 'provision' not in names and 'root_image' not in names


def test_measure_tmp_space_reads_filesystem_free_and_user_quota_when_enabled():
    reading = LANES.measure_tmp_space(Path('/tmp'))
    assert reading['path'] == '/tmp'
    assert type(reading['filesystem_free_bytes']) is int and reading['filesystem_free_bytes'] >= 0
    assert reading['usrquota'] is LANES.mount_has_usrquota(Path('/tmp'))
    if reading['usrquota']:
        assert reading['quota_error'] is None
        quota = reading['quota']
        assert quota['valid'] & (LANES.QIF_BLIMITS | LANES.QIF_SPACE) == (LANES.QIF_BLIMITS | LANES.QIF_SPACE)
        if quota['hard_kib'] == 0:
            assert quota['free_bytes'] is None and reading['free_bytes'] is None
            assert reading['quota_unlimited'] is True
        else:
            assert quota['hard_bytes'] == quota['hard_kib'] * 1024
            assert reading['free_bytes'] == max(0, quota['hard_bytes'] - quota['used_bytes'])
    else:
        assert reading['quota'] is None and reading['free_bytes'] == reading['filesystem_free_bytes']


def test_lane_launch_refuses_when_tmp_quota_cannot_hold_the_lanes(host_world, monkeypatch):
    patch_tmp_space(monkeypatch, tight_tmp_reading(), same=True)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL'
    assert 'tmp space is not enough' in result['error']
    assert f"free 1000000000 bytes, required {tmp_budget(2)} bytes for 2 lanes" in result['error']
    assert 'filesystem free 30000000000 bytes' in result['error']
    assert 'quota hard 8000000000 bytes, used 7000000000 bytes' in result['error']
    names = [call[0] for call in host_world['calls']]
    assert 'prepare_image_cache' not in names and 'provision' not in names and 'root_image' not in names


def test_lane_launch_refuses_when_the_tmp_user_quota_is_unreadable(host_world, monkeypatch):
    patch_tmp_space(monkeypatch, {
        'path': '/tmp', 'filesystem_free_bytes': 30_000_000_000, 'usrquota': True,
        'quota': None, 'quota_error': 'quotactl_fd failed: errno 1', 'free_bytes': None,
    }, same=True)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL'
    assert 'tmp space is not enough' in result['error'] and 'unreadable' in result['error']
    assert 'quotactl_fd failed: errno 1' in result['error']
    assert f'required {tmp_budget(2)} bytes for 2 lanes' in result['error']
    names = [call[0] for call in host_world['calls']]
    assert 'prepare_image_cache' not in names and 'provision' not in names


def test_lane_launch_proceeds_when_the_tmp_quota_holds_the_lanes(host_world, monkeypatch):
    reading = tight_tmp_reading()
    reading['free_bytes'] = 100_000_000_000
    reading['quota'] = {'hard_bytes': 200_000_000_000, 'used_bytes': 100_000_000_000, 'free_bytes': 100_000_000_000}
    patch_tmp_space(monkeypatch, reading, same=True)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'PASS', result.get('error')
    assert result['tmp_space']['applies'] is True and result['tmp_space']['decision'] == 'enough'
    assert result['tmp_space']['required_bytes'] == tmp_budget(2)
    assert result == stored_result(host_world)
    assert 'prepare_image_cache' in [call[0] for call in host_world['calls']]


def test_lane_launch_refuses_a_short_filesystem_when_usrquota_is_absent(host_world, monkeypatch):
    patch_tmp_space(monkeypatch, {
        'path': '/tmp', 'filesystem_free_bytes': 1, 'usrquota': False,
        'quota': None, 'quota_error': None, 'free_bytes': 1,
    }, same=True)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL'
    assert 'tmp space is not enough' in result['error']
    assert 'filesystem free 1 bytes' in result['error']
    assert 'no user quota' in result['error']
    assert f'required {tmp_budget(2)} bytes for 2 lanes' in result['error']
    names = [call[0] for call in host_world['calls']]
    assert 'prepare_image_cache' not in names and 'provision' not in names and 'root_image' not in names


def test_lane_launch_refuses_a_short_filesystem_when_the_finite_quota_holds(host_world, monkeypatch):
    budget = tmp_budget(2)
    patch_tmp_space(monkeypatch, {
        'path': '/tmp', 'filesystem_free_bytes': 1, 'usrquota': True,
        'quota': {'hard_kib': 1, 'hard_bytes': budget + 10, 'used_bytes': 0, 'free_bytes': budget + 10},
        'quota_error': None, 'free_bytes': budget + 10,
    }, same=True)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL'
    assert 'filesystem free 1 bytes' in result['error']
    assert f'required {budget} bytes for 2 lanes' in result['error']
    assert 'quota free' in result['error']
    names = [call[0] for call in host_world['calls']]
    assert 'prepare_image_cache' not in names and 'provision' not in names and 'root_image' not in names


def test_lane_launch_names_quota_and_filesystem_when_both_are_short(host_world, monkeypatch):
    reading = tight_tmp_reading()
    reading['filesystem_free_bytes'] = 1
    patch_tmp_space(monkeypatch, reading, same=True)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL'
    assert 'free 1000000000 bytes' in result['error']
    assert f'required {tmp_budget(2)} bytes for 2 lanes' in result['error']
    assert 'filesystem free 1 bytes is below the required' in result['error']
    assert 'quota hard 8000000000 bytes, used 7000000000 bytes' in result['error']
    names = [call[0] for call in host_world['calls']]
    assert 'prepare_image_cache' not in names and 'provision' not in names


def test_lane_launch_admits_when_usrquota_is_absent_and_the_filesystem_holds_the_lanes(host_world, monkeypatch):
    budget = tmp_budget(2)
    patch_tmp_space(monkeypatch, {
        'path': '/tmp', 'filesystem_free_bytes': budget + 1, 'usrquota': False,
        'quota': None, 'quota_error': None, 'free_bytes': budget + 1,
    }, same=True)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'PASS', result.get('error')
    assert result['tmp_space']['applies'] is True and result['tmp_space']['decision'] == 'enough'
    assert result['tmp_space']['usrquota'] is False
    assert 'prepare_image_cache' in [call[0] for call in host_world['calls']]


def test_lane_launch_ignores_tmp_quota_when_work_is_on_another_device(host_world, monkeypatch):
    patch_tmp_space(monkeypatch, tight_tmp_reading(), same=False)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'PASS', result.get('error')
    assert result['tmp_space']['applies'] is False and result['tmp_space']['decision'] == 'not_applicable'


def test_serial_fallback_does_not_consult_tmp_quota(host_world, monkeypatch):
    host_world['meminfo'].write_text(meminfo(31743008, 1000))

    def boom(path=Path('/tmp')):
        raise AssertionError(f'tmp quota consulted for {path}')

    monkeypatch.setattr(LANES, 'measure_tmp_space', boom, raising=False)
    result = execute(host_world)
    assert result['status'] == 'SERIAL_FALLBACK'
    assert 'tmp_space' not in result


def test_lifecycle_refuses_before_provision_when_tmp_quota_cannot_hold_the_lanes(life_world, monkeypatch):
    patch_tmp_space(monkeypatch, tight_tmp_reading(), same=True)
    report = lifecycle(life_world)
    assert report['status'] == 'FAIL'
    assert 'tmp space is not enough' in report['error']
    assert f'required {tmp_budget(4)} bytes for 4 lanes' in report['error']
    names = [call[0] for call in life_world['calls']]
    assert 'prepare_image_cache' not in names and 'provision' not in names and 'bootstrap' not in names


def test_lifecycle_refuses_a_short_filesystem_before_provision_when_usrquota_is_absent(life_world, monkeypatch):
    patch_tmp_space(monkeypatch, {
        'path': '/tmp', 'filesystem_free_bytes': 1, 'usrquota': False,
        'quota': None, 'quota_error': None, 'free_bytes': 1,
    }, same=True)
    report = lifecycle(life_world)
    assert report['status'] == 'FAIL'
    assert 'filesystem free 1 bytes' in report['error']
    assert 'no user quota' in report['error']
    assert f'required {tmp_budget(4)} bytes for 4 lanes' in report['error']
    names = [call[0] for call in life_world['calls']]
    assert 'prepare_image_cache' not in names and 'provision' not in names and 'bootstrap' not in names


def test_execute_binds_stop_signals_around_the_lanes(host_world, monkeypatch):
    seen = {}

    def bind(callback):
        seen['callback'] = callback
        return lambda: seen.setdefault('restored', True)

    monkeypatch.setattr(LANES, 'bind_campaign_stop_signals', bind, raising=False)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'PASS', result.get('error')
    assert seen.get('restored') is True and callable(seen.get('callback'))


def test_stop_signal_handler_releases_then_exits():
    calls = []
    restore = LANES.bind_campaign_stop_signals(lambda: calls.append('go'))
    try:
        handler = signal.getsignal(signal.SIGTERM)
        with pytest.raises(SystemExit) as caught:
            handler(signal.SIGTERM, None)
        assert caught.value.code == 128 + signal.SIGTERM
        assert calls == ['go']
        hangup = signal.getsignal(signal.SIGHUP)
        with pytest.raises(SystemExit) as caught_hup:
            hangup(signal.SIGHUP, None)
        assert caught_hup.value.code == 128 + signal.SIGHUP
    finally:
        restore()


def _lane_residue(tmp_path):
    work = tmp_path / 'work'
    cache = work / 'image-cache'
    cache.mkdir(parents=True)
    (cache / 'blob').write_text('image')
    repo = work / 'lane-1' / 'repo'
    repo.mkdir(parents=True)
    (repo / 'f').write_text('checkout')
    out = work / 'lane-1' / 'out'
    out.mkdir()
    (out / 'lane_runner.log').write_text('log\n')
    (work / 'campaign_result.json').write_text('{}\n')
    lane = LANES.Lane(1, 'aaaaaaaaaaaa-1', work / 'lane-1', tmp_path / 'home', 1, 1)
    return work, cache, repo, out, lane


def test_discard_removes_a_tmp_quota_cache_and_keeps_the_result(tmp_path):
    work, cache, repo, out, lane = _lane_residue(tmp_path)
    LANES.discard_script_work_trees(work, [lane], consumes_tmp_quota=True)
    LANES.discard_script_work_trees(work, [lane], consumes_tmp_quota=True)
    assert not cache.exists() and not repo.exists()
    assert (work / 'campaign_result.json').read_text() == '{}\n'
    assert (out / 'lane_runner.log').read_text() == 'log\n'


def test_discard_removes_the_image_cache_when_work_does_not_consume_tmp_quota(tmp_path):
    work, cache, repo, out, lane = _lane_residue(tmp_path)
    LANES.discard_script_work_trees(work, [lane], consumes_tmp_quota=False)
    assert not cache.exists() and not repo.exists()
    assert (work / 'campaign_result.json').read_text() == '{}\n'
    assert (out / 'lane_runner.log').read_text() == 'log\n'


def test_a_delivered_sigterm_removes_tmp_trees_and_keeps_the_result(tmp_path):
    work, cache, repo, out, _lane = _lane_residue(tmp_path)
    code = (
        'import os, signal, sys\n'
        'from pathlib import Path\n'
        'sys.path.insert(0, sys.argv[1])\n'
        'import run_local_lane_campaign as lanes\n'
        'work = Path(sys.argv[2])\n'
        'lane = lanes.Lane(1, "aaaaaaaaaaaa-1", work / "lane-1", work / "home", 1, 1)\n'
        'def release():\n'
        '    lanes.discard_script_work_trees(work, [lane], consumes_tmp_quota=True)\n'
        'lanes.bind_campaign_stop_signals(release)\n'
        'os.kill(os.getpid(), signal.SIGTERM)\n'
        'print("STILL_ALIVE", flush=True)\n'
    )
    proc = subprocess.run([sys.executable, '-c', code, str(ROOT / 'scripts'), str(work)],
                          cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 128 + signal.SIGTERM, proc.stderr
    assert 'STILL_ALIVE' not in proc.stdout
    assert not cache.exists() and not repo.exists()
    assert (work / 'campaign_result.json').read_text() == '{}\n'
    assert (out / 'lane_runner.log').read_text() == 'log\n'


def test_execute_release_removes_only_a_tmp_quota_cache(host_world, monkeypatch):
    """The release bound to SIGTERM drops the cache only when the pre-check applied."""
    cache = host_world['work'] / 'image-cache'
    cache.mkdir(parents=True)
    (cache / 'kept').write_text('archive')
    seen = {}

    def bind(callback):
        seen['callback'] = callback
        return lambda: seen.setdefault('restored', True)

    monkeypatch.setattr(LANES, 'bind_campaign_stop_signals', bind, raising=False)
    patch_tmp_space(monkeypatch, {
        'path': '/tmp', 'filesystem_free_bytes': 100_000_000_000, 'usrquota': True,
        'quota': {'hard_bytes': 200_000_000_000, 'used_bytes': 1, 'free_bytes': 100_000_000_000},
        'quota_error': None, 'free_bytes': 100_000_000_000,
    }, same=True)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'PASS', result.get('error')
    assert seen.get('restored') is True and not cache.exists()
    assert (host_world['work'] / 'campaign_result.json').is_file()
    seen['callback']()
    assert not cache.exists()


def test_execute_release_removes_the_cache_when_tmp_quota_does_not_apply(host_world, monkeypatch):
    cache = host_world['work'] / 'image-cache'
    cache.mkdir(parents=True)
    (cache / 'kept').write_text('archive')
    patch_tmp_space(monkeypatch, tight_tmp_reading(), same=False)
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'PASS', result.get('error')
    assert not cache.exists()
    assert (host_world['work'] / 'campaign_result.json').is_file()


def test_a_delivered_sigterm_removes_the_cache_without_usrquota(tmp_path):
    work, cache, repo, out, _lane = _lane_residue(tmp_path)
    code = (
        'import os, signal, sys\n'
        'from pathlib import Path\n'
        'sys.path.insert(0, sys.argv[1])\n'
        'import run_local_lane_campaign as lanes\n'
        'work = Path(sys.argv[2])\n'
        'lane = lanes.Lane(1, "aaaaaaaaaaaa-1", work / "lane-1", work / "home", 1, 1)\n'
        'def release():\n'
        '    lanes.discard_script_work_trees(work, [lane], consumes_tmp_quota=False)\n'
        'lanes.bind_campaign_stop_signals(release)\n'
        'os.kill(os.getpid(), signal.SIGTERM)\n'
        'print("STILL_ALIVE", flush=True)\n'
    )
    proc = subprocess.run([sys.executable, '-c', code, str(ROOT / 'scripts'), str(work)],
                          cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 128 + signal.SIGTERM, proc.stderr
    assert 'STILL_ALIVE' not in proc.stdout
    assert not cache.exists() and not repo.exists()
    assert (work / 'campaign_result.json').read_text() == '{}\n'
    assert (out / 'lane_runner.log').read_text() == 'log\n'


@pytest.mark.parametrize('usrquota', [True, False])
def test_a_failed_launch_removes_the_image_cache(host_world, monkeypatch, usrquota):
    budget = tmp_budget(2)
    cache = host_world['work'] / 'image-cache'
    cache.mkdir(parents=True)
    (cache / 'blob').write_text('image')
    reading = {
        'path': '/tmp', 'filesystem_free_bytes': budget + 1, 'usrquota': usrquota,
        'quota': None, 'quota_error': None, 'free_bytes': budget + 1,
    }
    if usrquota:
        reading['quota'] = {
            'hard_kib': 1, 'hard_bytes': budget + 1, 'used_bytes': 0, 'free_bytes': budget + 1,
        }
    patch_tmp_space(monkeypatch, reading, same=True)
    host_world['fail_provision'] = 1
    result = execute(host_world, selection=nodes())
    assert result['status'] == 'FAIL'
    assert 'provisioning failed' in result['error']
    assert not cache.exists()
    assert (host_world['work'] / 'campaign_result.json').is_file()
    assert [call[0] for call in host_world['calls']].count('teardown') == 2


_LANE_SECRET = 'synthetic-lane-password'


def _plant_lane_secret(world, *, raw):
    real = world['launcher']

    def launcher(argv, log):
        process = real(argv, log)
        index = int(argv[argv.index('--run-lane') + 1].split('/lane-')[-1].split('/')[0])
        if index != 1:
            return process
        item = next(entry for entry in world['lanes'] if entry.index == index)
        (item.repository / '.ocor').mkdir(parents=True, exist_ok=True)
        (item.repository / '.ocor/bootstrap.env').write_text(
            f'OCOR_LOCAL_POSTGRES_PASSWORD={_LANE_SECRET}\n')
        log.write_bytes(raw)
        return process

    world['launcher'] = launcher


def _enough_tmp(monkeypatch, *, usrquota):
    budget = tmp_budget(2)
    reading = {
        'path': '/tmp', 'filesystem_free_bytes': budget + 1, 'usrquota': usrquota,
        'quota': None, 'quota_error': None, 'free_bytes': budget + 1,
    }
    if usrquota:
        reading['quota'] = {
            'hard_kib': 1, 'hard_bytes': budget + 1, 'used_bytes': 0, 'free_bytes': budget + 1,
        }
    patch_tmp_space(monkeypatch, reading, same=True)


def test_a_non_utf8_lane_log_is_redacted_and_does_not_skip_teardown(host_world, monkeypatch):
    cache = host_world['work'] / 'image-cache'
    cache.mkdir(parents=True)
    (cache / 'blob').write_text('image')
    _enough_tmp(monkeypatch, usrquota=False)
    _plant_lane_secret(host_world, raw=b'password ' + _LANE_SECRET.encode() + b' \xff\n')
    result = execute(host_world, selection=nodes())
    rendered = json.dumps(result)
    assert result['status'] == 'FAIL'
    assert 'UnicodeDecodeError' in result['error']
    assert _LANE_SECRET not in rendered
    assert [call[0] for call in host_world['calls']].count('teardown') == 2
    assert 'remove_root_image' in [call[0] for call in host_world['calls']]
    assert not cache.exists()
    assert (host_world['work'] / 'campaign_result.json').is_file()
    log = host_world['work'] / 'lane-1' / 'out' / 'lane_runner.log'
    assert log.is_file()
    assert _LANE_SECRET.encode() not in log.read_bytes()


def test_a_redactor_io_error_does_not_skip_teardown_or_expose_the_secret(host_world, monkeypatch):
    cache = host_world['work'] / 'image-cache'
    cache.mkdir(parents=True)
    (cache / 'blob').write_text('image')
    _enough_tmp(monkeypatch, usrquota=True)

    def boom(repository, path):
        del repository, path
        raise OSError('log unreadable ' + _LANE_SECRET)

    monkeypatch.setattr(LANES.bootstrap_ci, 'redact_campaign_log', boom)
    _plant_lane_secret(host_world, raw=f'password {_LANE_SECRET}\n'.encode())
    result = execute(host_world, selection=nodes())
    rendered = json.dumps(result)
    assert result['status'] == 'FAIL'
    assert 'OSError' in result['error']
    assert _LANE_SECRET not in rendered
    assert 'log unreadable' not in rendered
    assert [call[0] for call in host_world['calls']].count('teardown') == 2
    assert not cache.exists()
    log = host_world['work'] / 'lane-1' / 'out' / 'lane_runner.log'
    assert log.is_file()
    assert _LANE_SECRET.encode() not in log.read_bytes()
