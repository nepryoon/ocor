"""C4 canonical marking evaluation (OCOR-DEV-REM-0052, NCP-U05, NCR-C4-002).

The marking exists in one canonical form, the ``marking`` object of ADD v1.3 §3.2 ``$defs``
(:741-787), governed by the ``MarkingSchemeDefinition`` of §3.1.1 (:429) as the C1 IR carries
it (``ocor_runtime.c1.oac``); every other form is a projection of that object (§3.0.2,
:396-401). This module evaluates the object with the scheme and computes the algebra of §5.3
(:3256-3282):

* ``classification_level`` is the one label of ``labels`` that is a level of the scheme; the
  other labels are partitioned by ``mandatory_markings`` and ``caveats`` (§3.0.2 :399);
* dominance is the declared lattice on the level, superset on the four RESTRICTION families and
  subset on ``permitted_purposes`` (PERMISSION);
* the conservative join is the least upper bound of the levels, the union of the restriction
  families and the intersection of the permitted purposes; incomparable levels are DENY, or the
  top only when the scheme declares ``MOST_RESTRICTIVE``; an empty intersection is DENY.

A marking that is not the canonical object of the active scheme, an unknown value, a digest that
does not match the object (§3.0.2 :401) or an incomparable join is ``MARKING_UNRESOLVED``
(LLD v1.1 §1.3 :67), never a permissive posture. A scheme outside the supported profile is
refused at construction (§5.3 :3268).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..c5.envelope import EnvelopeViolation, marking_digest

RESTRICTION_FAMILIES = ("mandatory_markings", "caveats", "dissemination_controls", "handling_instructions")
PERMISSION_FAMILY = "permitted_purposes"
FAMILIES = (*RESTRICTION_FAMILIES, PERMISSION_FAMILY)
MARKING_FIELDS = frozenset({"scheme_id", "labels", *FAMILIES, "marking_digest"})
SCHEME_FIELDS = frozenset({"scheme_id", "version", "levels", "top", "bottom", "dominance_relation",
                           "family_definitions", "unknown_value_behavior", "incomparable_behavior",
                           "declassification_authority_ref"})
FAMILY_FIELDS = frozenset({"family", "vocabulary", "kind", "join_operator", "meet_operator", "neutral_element"})
_MAX_LENGTH = {"handling_instructions": 256}


class MarkingSchemeError(ValueError):
    """A ``MarkingSchemeDefinition`` outside the supported profile (ADD v1.3 :429, :3268)."""


class MarkingUnresolved(ValueError):
    """``MARKING_UNRESOLVED`` (LLD v1.1 §1.3 :67): the marking is missing, not canonical,
    unknown to the active scheme, does not match its digest, or has no conservative join."""

    reason_code = "MARKING_UNRESOLVED"

    def __init__(self, message: str) -> None:
        super().__init__(f"MARKING_UNRESOLVED: {message}")


@dataclass(frozen=True, slots=True)
class EvaluatedMarking:
    """The evaluation of a canonical marking object under the active scheme (§3.0.2 :399)."""

    scheme_id: str
    classification_level: str
    families: Mapping[str, frozenset[str]]
    marking_digest: str

    @property
    def marking_ref(self) -> str:
        """The ``*_marking_ref`` projection of the object: ``urn:`` + its digest (§3.0.2 :398)."""
        return "urn:" + self.marking_digest


def _strings(value: object, where: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise MarkingSchemeError(f"{where} must be an array of non-empty strings")
    if len(set(value)) != len(value):
        raise MarkingSchemeError(f"{where} contains duplicates")
    return list(value)


class CanonicalMarkingScheme:
    """The active ``MarkingSchemeDefinition`` of the C1 IR, validated against the supported
    profile, and the evaluation, dominance and conservative join of canonical marking objects."""

    def __init__(self, definition: Mapping[str, Any]) -> None:
        if not isinstance(definition, Mapping):
            raise TypeError("a MarkingSchemeDefinition of the C1 IR is required")
        fields = set(definition) - {"construct"}
        if fields != SCHEME_FIELDS or definition.get("construct", "MarkingSchemeDefinition") != "MarkingSchemeDefinition":
            raise MarkingSchemeError("the MarkingSchemeDefinition is not the closed construct of ADD v1.3 :429")
        scheme_id = definition["scheme_id"]
        if not isinstance(scheme_id, str) or not scheme_id:
            raise MarkingSchemeError("scheme_id must be a non-empty string")
        levels = _strings(definition["levels"], "levels")
        if not levels:
            raise MarkingSchemeError("levels must declare at least one level")
        relation = definition["dominance_relation"]
        if not isinstance(relation, list) or any(
                not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(v, str) for v in pair)
                for pair in relation):
            raise MarkingSchemeError("dominance_relation must be an array of [lower, upper] pairs")
        order = {(str(lower), str(upper)) for lower, upper in relation}
        self._check_lattice(levels, order, definition["top"], definition["bottom"])
        if definition["unknown_value_behavior"] != "DENY":
            raise MarkingSchemeError("unknown_value_behavior must be DENY: no implicit default")
        if definition["incomparable_behavior"] not in ("DENY", "MOST_RESTRICTIVE"):
            raise MarkingSchemeError("incomparable_behavior must be DENY or MOST_RESTRICTIVE")
        self._scheme_id = scheme_id
        self._levels = tuple(levels)
        self._order = frozenset(order)
        self._top = str(definition["top"])
        self._incomparable = str(definition["incomparable_behavior"])
        self._vocabulary = self._check_families(definition["family_definitions"])

    @staticmethod
    def _check_lattice(levels: list[str], order: set[tuple[str, str]], top: object, bottom: object) -> None:
        """A partial order (reflexive, antisymmetric, transitive) with the declared top and bottom
        and a unique join and meet for every pair (ADD v1.3 :429)."""
        if any(a not in levels or b not in levels for a, b in order):
            raise MarkingSchemeError("dominance_relation names an undeclared level")
        if any((level, level) not in order for level in levels):
            raise MarkingSchemeError("dominance_relation is not reflexive")
        if any(a != b and (b, a) in order for a, b in order):
            raise MarkingSchemeError("dominance_relation is not antisymmetric")
        if any((a, d) not in order for a, b in order for c, d in order if b == c):
            raise MarkingSchemeError("dominance_relation is not transitive")
        if top not in levels or any((level, top) not in order for level in levels):
            raise MarkingSchemeError("top is not the greatest level")
        if bottom not in levels or any((bottom, level) not in order for level in levels):
            raise MarkingSchemeError("bottom is not the least level")
        for a in levels:
            for b in levels:
                uppers = [u for u in levels if (a, u) in order and (b, u) in order]
                lowers = [w for w in levels if (w, a) in order and (w, b) in order]
                if len([u for u in uppers if all((u, o) in order for o in uppers)]) != 1 or \
                        len([w for w in lowers if all((o, w) in order for o in lowers)]) != 1:
                    raise MarkingSchemeError(f"levels {a!r} and {b!r} have no unique join and meet")

    @staticmethod
    def _check_families(definitions: object) -> Mapping[str, frozenset[str]]:
        """The five families once each, RESTRICTION with UNION join for the four restriction
        families and PERMISSION with INTERSECTION join for the purposes (ADD v1.3 :3268-3278)."""
        if not isinstance(definitions, list) or len(definitions) != len(FAMILIES):
            raise MarkingSchemeError("the five mandatory marking families must each be declared once")
        vocabulary: dict[str, frozenset[str]] = {}
        for family in definitions:
            if not isinstance(family, Mapping) or set(family) != FAMILY_FIELDS:
                raise MarkingSchemeError("a family definition is not the closed record of ADD v1.3 :429")
            name = family["family"]
            if name not in FAMILIES or name in vocabulary:
                raise MarkingSchemeError("the five mandatory marking families must each be declared once")
            expected = ("PERMISSION", "INTERSECTION", "UNION") if name == PERMISSION_FAMILY else \
                ("RESTRICTION", "UNION", "INTERSECTION")
            if (family["kind"], family["join_operator"], family["meet_operator"]) != expected:
                raise MarkingSchemeError(f"family {name!r} is outside the supported profile: {expected} is required")
            words = _strings(family["vocabulary"], f"family {name!r} vocabulary")
            if not set(_strings(family["neutral_element"], f"family {name!r} neutral element")) <= set(words):
                raise MarkingSchemeError(f"family {name!r}: neutral element is outside the vocabulary")
            vocabulary[str(name)] = frozenset(words)
        return vocabulary

    @property
    def scheme_id(self) -> str:
        return self._scheme_id

    def _leq(self, lower: str, upper: str) -> bool:
        return (lower, upper) in self._order

    def evaluate(self, marking: object) -> EvaluatedMarking:
        """The evaluation of a canonical ``marking`` object, or ``MarkingUnresolved``."""
        if not isinstance(marking, Mapping) or set(marking) != MARKING_FIELDS:
            raise MarkingUnresolved("the marking is not the closed object of ADD v1.3 §3.2 $defs.marking")
        if marking["scheme_id"] != self._scheme_id:
            raise MarkingUnresolved("the marking names a scheme that is not the active one")
        values: dict[str, frozenset[str]] = {}
        for name in ("labels", *FAMILIES):
            items = marking[name]
            limit = _MAX_LENGTH.get(name, 128)
            if not isinstance(items, list) or any(
                    not isinstance(item, str) or not 1 <= len(item) <= limit for item in items):
                raise MarkingUnresolved(f"{name} must be an array of strings of 1..{limit} characters")
            if len(set(items)) != len(items):
                raise MarkingUnresolved(f"{name} must hold unique items")
            values[name] = frozenset(items)
        try:
            digest = marking_digest(marking)
        except EnvelopeViolation as exc:
            raise MarkingUnresolved("the marking cannot be digested") from exc
        if marking["marking_digest"] != digest:
            raise MarkingUnresolved("marking_digest does not match the object")
        levels = values["labels"] & set(self._levels)
        if len(levels) != 1:
            raise MarkingUnresolved("labels must name exactly one level of the scheme")
        mandatory, caveats = values["mandatory_markings"], values["caveats"]
        if mandatory & caveats or values["labels"] - levels != mandatory | caveats:
            raise MarkingUnresolved("mandatory_markings and caveats must partition the labels beyond the level")
        for name in FAMILIES:
            unknown = values[name] - self._vocabulary[name]
            if unknown:
                raise MarkingUnresolved(f"{name} holds values unknown to the scheme: {sorted(unknown)}")
        if not values[PERMISSION_FAMILY]:
            raise MarkingUnresolved("permitted_purposes is empty")
        return EvaluatedMarking(scheme_id=self._scheme_id, classification_level=next(iter(levels)),
                                families={name: values[name] for name in FAMILIES}, marking_digest=digest)

    def _evaluated(self, marking: object) -> EvaluatedMarking:
        return marking if isinstance(marking, EvaluatedMarking) and marking.scheme_id == self._scheme_id \
            else self.evaluate(marking)

    def dominates(self, upper: object, lower: object) -> bool:
        """Whether ``upper`` is at least as restrictive as ``lower`` on the level and on every
        family (ADD v1.3 §5.3 :3271-3278); an incomparable level never dominates."""
        high, low = self._evaluated(upper), self._evaluated(lower)
        if not self._leq(low.classification_level, high.classification_level):
            return False
        if any(not high.families[name] >= low.families[name] for name in RESTRICTION_FAMILIES):
            return False
        return high.families[PERMISSION_FAMILY] <= low.families[PERMISSION_FAMILY]

    def authorized(self, content: object, clearance: object) -> bool:
        """A reader whose clearance dominates the content marking may read it."""
        return self.dominates(clearance, content)

    def _level_join(self, levels: list[str]) -> str:
        result = levels[0]
        for level in levels[1:]:
            if self._leq(level, result):
                continue
            if self._leq(result, level):
                result = level
                continue
            if self._incomparable == "MOST_RESTRICTIVE":
                return self._top
            raise MarkingUnresolved(f"levels {result!r} and {level!r} are incomparable")
        return result

    def join(self, *markings: object) -> dict[str, Any]:
        """The conservative join of the inputs, a canonical marking object with its own digest
        (ADD v1.3 §5.3 :3256-3266); never less restrictive than any input."""
        if not markings:
            raise MarkingUnresolved("the join of no marking is undefined")
        evaluated = [self._evaluated(marking) for marking in markings]
        level = self._level_join([value.classification_level for value in evaluated])
        families: dict[str, list[str]] = {
            name: sorted(set().union(*(value.families[name] for value in evaluated))) for name in RESTRICTION_FAMILIES}
        purposes = frozenset.intersection(*(value.families[PERMISSION_FAMILY] for value in evaluated))
        if not purposes:
            raise MarkingUnresolved("the intersection of the permitted purposes is empty")
        result: dict[str, Any] = {
            "scheme_id": self._scheme_id,
            "labels": sorted({level, *families["mandatory_markings"], *families["caveats"]}),
            **families,
            PERMISSION_FAMILY: sorted(purposes),
        }
        result["marking_digest"] = marking_digest(result)
        return result
