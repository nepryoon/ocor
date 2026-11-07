"""Resolving marking evaluation for the current components (OCOR-DEV-REM-0054, NCP-U08, NCR-C6-012).

The C2 gateway and the C8 tool runtime evaluate a ``MarkingSet`` (one label per marking scheme)
over the validated finite lattices of ``c4_marking.MarkingSchemeDefinition``. The legacy
``c4_marking.MarkingEngine`` defaults a missing scheme to the bottom in its join and ignores it in
its authorization; it stays unchanged in the legacy slice (programme point 6), and the current
components no longer use it. Here (LLD v1.1 §1.3 :67) a marking that is missing, incomparable or
unresolvable is ``MARKING_UNRESOLVED``:

* a marking resolves only when it is a ``MarkingSet`` naming every scheme of the active set, and
  no other, each with a label of that scheme;
* the clearance dominates the content only when it dominates it on every scheme; a pair of labels
  that the lattice does not order is unresolved, never a plain denial or a permit;
* the join is the conservative least upper bound of complete markings, never less restrictive than
  any input (FR-131); the join of no marking is undefined.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from ..c4_marking import MarkingSchemeDefinition, MarkingSet
from ..errors import MarkingError
from .marking import MarkingSchemeError, MarkingUnresolved


class ResolvedMarkingEngine:
    """The active marking schemes and the resolving evaluation of ``MarkingSet`` values."""

    def __init__(self, schemes: Iterable[MarkingSchemeDefinition]) -> None:
        definitions = tuple(schemes)
        if any(not isinstance(scheme, MarkingSchemeDefinition) for scheme in definitions):
            raise TypeError("every marking scheme must be a validated MarkingSchemeDefinition")
        if not definitions:
            raise MarkingSchemeError("at least one marking scheme is required")
        mapping = {scheme.scheme_id: scheme for scheme in definitions}
        if len(mapping) != len(definitions):
            raise MarkingSchemeError("marking scheme identifiers must be unique")
        self._schemes = MappingProxyType(mapping)

    @property
    def schemes(self) -> Mapping[str, MarkingSchemeDefinition]:
        return self._schemes

    def resolve(self, markings: object) -> MarkingSet:
        """``markings`` when it names every active scheme, and only those, with a known label."""
        if not isinstance(markings, MarkingSet):
            raise MarkingUnresolved("the marking is not a MarkingSet")
        values = markings.values
        missing = sorted(set(self._schemes) - set(values))
        if missing:
            raise MarkingUnresolved(f"the marking names no label for the schemes {missing}")
        unknown = sorted(str(scheme_id) for scheme_id in set(values) - set(self._schemes))
        if unknown:
            raise MarkingUnresolved(f"the marking names unknown schemes {unknown}")
        for scheme_id, label in values.items():
            if not isinstance(label, str) or label not in self._schemes[scheme_id].labels:
                raise MarkingUnresolved(f"the label of scheme {scheme_id!r} is not a label of that scheme")
        return markings

    def dominates(self, upper: object, lower: object) -> bool:
        """Whether ``upper`` is at least as restrictive as ``lower`` on every scheme; an unordered
        pair of labels is ``MarkingUnresolved``."""
        high, low = self.resolve(upper), self.resolve(lower)
        dominated = True
        for scheme_id, scheme in self._schemes.items():
            if scheme.leq(low[scheme_id], high[scheme_id]):
                continue
            if not scheme.leq(high[scheme_id], low[scheme_id]):
                raise MarkingUnresolved(f"the labels of scheme {scheme_id!r} are incomparable")
            dominated = False
        return dominated

    def authorized(self, content: object, clearance: object) -> bool:
        """A clearance that dominates the content marking may read it."""
        return self.dominates(clearance, content)

    def join(self, *markings: object) -> MarkingSet:
        """The conservative least upper bound of complete markings, scheme by scheme."""
        if not markings:
            raise MarkingUnresolved("the join of no marking is undefined")
        resolved = [self.resolve(marking) for marking in markings]
        try:
            return MarkingSet({scheme_id: scheme.join(*(marking[scheme_id] for marking in resolved))
                               for scheme_id, scheme in self._schemes.items()})
        except MarkingError as exc:  # a lattice always has the join; never a permissive default
            raise MarkingUnresolved(str(exc)) from exc
