"""Property tests of the canonical kernel (OCOR-DEV-REM-0060, NCP-U12, NCR-TESTS-005).

Technique routing of docs/development_methodology/OCOR_TEST_STRATEGY.md:18 ("Canonical kernel |
examples, property tests, differential oracle, determinism"). The kernel produces RFC 8785 bytes for
I-JSON values and the ``urn:sha256`` digest of those bytes (LLD v1.1 §1.1, docs/OCOR_LLD_v1.1.md:37;
``ocor_runtime.kernel.canonical``). The properties hold for every generated I-JSON value; the
differential oracle is the Python standard library serialiser on the subset where RFC 8785 and a sorted
compact ``json.dumps`` coincide (integers, no floats, keys below U+D800 so that UTF-16 and code point
order agree). Generation is derandomised and writes no example database.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ocor_runtime.errors import CanonicalizationError
from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest, parse_i_json, verify_canonical_digest

PROFILE = settings(max_examples=300, derandomize=True, database=None, deadline=None, suppress_health_check=[HealthCheck.too_slow])
SAFE_INTEGER = 2**53

_text = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=12)
_key = st.text(alphabet=st.characters(max_codepoint=0xD7FF, blacklist_categories=("Cs",)), max_size=8)
_integer = st.integers(min_value=-SAFE_INTEGER, max_value=SAFE_INTEGER)
_finite = st.floats(allow_nan=False, allow_infinity=False)
_scalar = st.one_of(st.none(), st.booleans(), _integer, _finite, _text)
i_json = st.recursive(_scalar, lambda children: st.one_of(st.lists(children, max_size=4), st.dictionaries(_text, children, max_size=4)), max_leaves=20)
_oracle_scalar = st.one_of(st.none(), st.booleans(), _integer, st.text(alphabet=st.characters(max_codepoint=0xD7FF, blacklist_categories=("Cs",)), max_size=12))
oracle_json = st.recursive(
    _oracle_scalar, lambda children: st.one_of(st.lists(children, max_size=4), st.dictionaries(_key, children, max_size=4)), max_leaves=20
)


def _reverse_members(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _reverse_members(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_reverse_members(item) for item in value]
    return value


@PROFILE
@given(i_json)
def test_canonical_bytes_are_deterministic_and_a_fixed_point_of_parsing(value: Any):
    encoded = canonical_bytes(value)
    assert canonical_bytes(value) == encoded
    assert canonical_bytes(parse_i_json(encoded)) == encoded
    encoded.decode("utf-8", errors="strict")


@PROFILE
@given(i_json)
def test_canonical_bytes_do_not_depend_on_member_order(value: Any):
    assert canonical_bytes(_reverse_members(value)) == canonical_bytes(value)


@PROFILE
@given(oracle_json)
def test_canonical_bytes_agree_with_the_differential_oracle(value: Any):
    oracle = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert canonical_bytes(value) == oracle


@PROFILE
@given(i_json)
def test_digest_is_the_sha256_urn_of_the_canonical_bytes_and_verifies(value: Any):
    digest = canonical_digest(value)
    assert digest == "urn:sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()
    assert verify_canonical_digest(value, digest) == digest


@PROFILE
@given(i_json, i_json)
def test_digest_separates_values_with_different_canonical_bytes(left: Any, right: Any):
    if canonical_bytes(left) != canonical_bytes(right):
        assert canonical_digest(left) != canonical_digest(right)
    else:
        assert canonical_digest(left) == canonical_digest(right)


@PROFILE
@given(st.sampled_from([math.nan, math.inf, -math.inf]), st.lists(_integer, max_size=3), st.sampled_from(["top", "list", "object"]))
def test_non_finite_numbers_are_rejected_in_every_position(number: float, siblings: list[int], position: str):
    value: Any = {"top": number, "list": [*siblings, number], "object": {"nested": [{"deep": number}]}}[position]
    with pytest.raises(CanonicalizationError, match="NaN and Infinity") as excinfo:
        canonical_bytes(value)
    assert excinfo.value.code == "CANONICALIZATION_INVALID"


@PROFILE
@given(st.integers(min_value=SAFE_INTEGER + 1, max_value=2**80) | st.integers(min_value=-(2**80), max_value=-SAFE_INTEGER - 1))
def test_integers_outside_binary64_exactness_are_rejected(number: int):
    if float(number) == number:
        # exactly representable powers of two are valid I-JSON numbers
        assert canonical_bytes(number)
        return
    with pytest.raises(CanonicalizationError, match="binary64") as excinfo:
        canonical_bytes(number)
    assert excinfo.value.code == "CANONICALIZATION_INVALID"


@PROFILE
@given(st.sampled_from([b"x", {1: 2}, {None: 1}, {1.5: 1}, set(), object(), "\ud800", {"\udfff": 1}, ["\ud83d"]]))
def test_values_outside_i_json_are_rejected(value: Any):
    with pytest.raises(CanonicalizationError) as excinfo:
        canonical_bytes(value)
    assert excinfo.value.code == "CANONICALIZATION_INVALID"
