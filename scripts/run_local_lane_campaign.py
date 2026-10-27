#!/usr/bin/env python3
"""Partition and union checks for the local full suite in two parallel lanes (OCOR-DEV-REM-0037).

PO LOCAL-SUITE-SPLIT (2026-10-25) as reactivated by LOCAL-SUITE-SPLIT-REACTIVATION
(2026-10-26). Additive orchestrator: it imports the sealed supervisor
``run_qualifying_campaign.py`` and never rebinds it, so the serial campaign,
the CI parts and the verifier procedure keep their behaviour.

- The partition is deterministic and computed from the per-case times of the
  serial measurement campaign (``WEIGHTS_PATH``). Every module stays whole except
  the cases of ``INDEPENDENT_MODULES`` (0049), which are distributed across the
  lanes; each lane keeps collection order.
- The union of the lanes' JUnit must equal the collection exactly, zero skips.
- Two lanes start only if MemAvailable reaches the measured start threshold;
  otherwise the serial suite runs and the fallback is recorded.
- The governed full-suite limits apply to the whole campaign, not to a lane.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

import run_qualifying_campaign as campaign
from run_qualifying_campaign import CampaignError

LANE_COUNT = 2
FULL_SUITE_LIMIT_SECONDS = campaign.FULL_SUITE_LIMIT_SECONDS
PO_DECISION_THRESHOLD_SECONDS = campaign.PO_DECISION_THRESHOLD_SECONDS
# Measured in the serial campaign at 266cf12 (REM-0037 preimplementation record):
# 2 x conservative single-lane peak occupancy (5670.3 MiB) + the unchanged guard.
TWO_LANE_START_THRESHOLD_MIB = 14340.6
MEMORY_GUARD_MIB = 3000
# Partition weights only; they never select or exclude a case.
MINIMUM_MEASURED_SECONDS = 0.5
DEFAULT_CASE_SECONDS = 0.05
WEIGHTS_PATH = Path(__file__).resolve().parents[1] / "reports/assurance/OCOR-DEV-REM-0037-RCCAD/lane_weights.json"


def weight_key(nodeid: str) -> str:
    classname, name = campaign.junit_identity(nodeid)
    return f"{classname}::{name}"


def case_weight(nodeid: str, weights: dict[str, float]) -> float:
    return float(weights.get(weight_key(nodeid), DEFAULT_CASE_SECONDS))


def derive_weights(junit: Path) -> dict[str, Any]:
    """Reproducible weights file content from a PASS serial JUnit."""
    root = ET.parse(junit).getroot()
    cases = list(root.iter("testcase"))
    weights = {f"{case.get('classname', '')}::{case.get('name', '')}": round(float(case.get("time", "0")), 3)
               for case in cases}
    return {
        "default_case_seconds": DEFAULT_CASE_SECONDS,
        "minimum_case_seconds": MINIMUM_MEASURED_SECONDS,
        "source": {"cases": len(cases), "junit_sha256": hashlib.sha256(junit.read_bytes()).hexdigest()},
        "weights": {key: value for key, value in sorted(weights.items()) if value >= MINIMUM_MEASURED_SECONDS},
    }


def load_weights(path: Path = WEIGHTS_PATH) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: float(value) for key, value in data["weights"].items()}


def lane_partition(nodeids: list[str], weights: dict[str, float], *, lanes: int = LANE_COUNT) -> list[list[str]]:
    """Longest-processing-time assignment of whole units; ties resolve by node ID and lane index."""
    if lanes != LANE_COUNT:
        raise CampaignError(f"the local suite runs in exactly {LANE_COUNT} lanes")
    if not nodeids or len(nodeids) != len(set(nodeids)):
        raise CampaignError(f"cannot partition {len(nodeids)} collected tests with duplicates or none")
    if len({campaign.junit_identity(node) for node in nodeids}) != len(nodeids):
        raise CampaignError("collected node IDs are not uniquely identifiable in JUnit")
    units = campaign.partition_units(nodeids)
    if len(units) < lanes:
        raise CampaignError(f"cannot partition {len(units)} units into {lanes} nonempty lanes")
    loads = [(0.0, index) for index in range(lanes)]
    assigned: list[list[str]] = [[] for _ in range(lanes)]
    for unit in sorted(units, key=lambda item: (-sum(case_weight(node, weights) for node in item), item[0])):
        load, index = heapq.heappop(loads)
        assigned[index].extend(unit)
        heapq.heappush(loads, (load + sum(case_weight(node, weights) for node in unit), index))
    order = {node: position for position, node in enumerate(nodeids)}
    parts = [sorted(part, key=order.__getitem__) for part in assigned]
    if not all(parts):
        raise CampaignError("a lane received no tests")
    return parts


def lane_loads(parts: list[list[str]], weights: dict[str, float]) -> list[float]:
    return [round(sum(case_weight(node, weights) for node in part), 3) for part in parts]


def partition_estimate(nodeids: list[str], weights: dict[str, float]) -> dict[str, Any]:
    parts = lane_partition(nodeids, weights)
    return {"lane_cases": [len(part) for part in parts], "lane_seconds": lane_loads(parts, weights),
            "lower_bound_seconds": max(case_weight(node, weights) for node in nodeids),
            "partition_sha256": campaign.partition_digest(parts)}


def check_exact_union(collected: list[str], junits: list[Path]) -> dict[str, Any]:
    """Accept the lanes only if their JUnit union is exactly the collection, with zero skips."""
    if len(junits) != LANE_COUNT:
        raise CampaignError(f"expected {LANE_COUNT} lane JUnit files, found {len(junits)}")
    executed: list[tuple[str, str]] = []
    per_lane = []
    for path in junits:
        cases = campaign.junit_cases(path)
        per_lane.append(len(cases))
        executed.extend(cases)
    wanted = {campaign.junit_identity(node) for node in collected}
    occurrences = Counter(executed)
    seen = set(occurrences)
    discrepancies = {"missing": sorted("::".join(case) for case in wanted - seen),
                     "duplicated": sorted("::".join(case) for case, times in occurrences.items() if times > 1),
                     "unexpected": sorted("::".join(case) for case in seen - wanted)}
    for key, cases_found in discrepancies.items():
        if cases_found:
            raise CampaignError(f"union of lanes has {key} tests: {cases_found[:20]}")
    return {"collected": len(collected), "executed": len(executed), **discrepancies, "lanes": per_lane}


def memory_admission(meminfo: str) -> dict[str, Any]:
    """TWO_LANE only with a readable MemAvailable at or above the measured threshold."""
    values: dict[str, int] = {}
    for line in meminfo.splitlines():
        key, _, rest = line.partition(":")
        fields = rest.split()
        if fields and fields[0].isdigit():
            values[key.strip()] = int(fields[0])
    available = values.get("MemAvailable")
    decision = {"mem_total_kib": values.get("MemTotal"), "mem_available_kib": available,
                "threshold_mib": TWO_LANE_START_THRESHOLD_MIB, "guard_mib": MEMORY_GUARD_MIB}
    if available is None or values.get("MemTotal") is None:
        return {**decision, "mode": "SERIAL", "reason": "MemTotal or MemAvailable unreadable"}
    if available / 1024 >= TWO_LANE_START_THRESHOLD_MIB:
        return {**decision, "mode": "TWO_LANE", "reason": "MemAvailable at or above the measured threshold"}
    return {**decision, "mode": "SERIAL", "reason": "MemAvailable below the measured threshold"}


def check_campaign_deadline(elapsed: float) -> bool:
    """Whole-campaign clock: the lanes share the governed full-suite limit."""
    return campaign.check_deadline(elapsed, limit=FULL_SUITE_LIMIT_SECONDS, threshold=PO_DECISION_THRESHOLD_SECONDS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--derive-weights", type=Path, metavar="JUNIT", help="write the weights file content derived from a serial PASS JUnit")
    parser.add_argument("--plan", action="store_true", help="collect on this checkout and print the memory decision and lane estimate")
    args = parser.parse_args(argv)
    if args.derive_weights:
        print(json.dumps(derive_weights(args.derive_weights), indent=2, sort_keys=True))
        return 0
    if args.plan:
        try:
            collected = campaign.collect_nodeids(Path(__file__).resolve().parents[1] / "ocor-runtime", ["tests/"])
            weights = load_weights()
            plan = {"collected": len(collected), "collected_sha256": campaign.collection_digest(collected),
                    "memory": memory_admission(Path("/proc/meminfo").read_text()), **partition_estimate(collected, weights)}
        except (CampaignError, OSError, ValueError, KeyError) as exc:
            print(json.dumps({"status": "FAIL", "error": str(exc)}))
            return 1
        print(json.dumps({"status": "PASS", **plan}, sort_keys=True))
        return 0
    parser.error("choose --derive-weights or --plan")
    return 2


if __name__ == "__main__":
    sys.exit(main())
