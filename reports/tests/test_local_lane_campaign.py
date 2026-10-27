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
