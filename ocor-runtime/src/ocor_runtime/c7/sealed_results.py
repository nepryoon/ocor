"""C7 sealed causal results: the ``sealResult`` subset of ``ScenarioOverlayStore``.

OCOR-DEV-REM-0040 (PO OCOR-DEV-0060-BA-SELECTED-COMPONENTS, change set c; placed by
REM-0040-C7-SEALED-RESULT-PORT-DISPOSITION (2026-10-28), option 1). ADD v1.3 §4.2
defines the vendor-neutral ``ScenarioOverlayStore`` port with six operations
(``openSnapshot``, ``forkScenario``, ``appendOverlay``, ``readAt``, ``sealResult``,
``discard``). This module reproduces only ``sealResult`` and the read of a sealed
result by its digest, the part of ``readAt`` that concerns results; the overlay
operations belong to OCOR-DEV-REM-0041 (TerminusDB, ADD v1.3 Part I §2.4), whose
complete ``ScenarioOverlayStore`` composes these names and signatures unchanged.

The sealed content is the canonical serialization from which
``ocor_runtime.c7.runtime`` computes ``CausalOutcome.reproducibility_digest``; the
digest is the content address. ``c7/runtime.py``, ``CausalOutcome``, contracts,
schemas and reason codes are unchanged; the ``code`` of ``SealedResultError`` is an
adapter failure code, never a ``CausalOutcome`` reason code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..errors import OCORError
from .runtime import CausalOutcome


class SealedResultError(OCORError):
    """A sealed-result operation failed closed. ``code`` names the reason; the message
    never carries credentials."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class SealedResult:
    """Receipt of ``seal_result``: the content address and whether this call wrote it
    (``False`` for an idempotent repeat of an identical result)."""

    reproducibility_digest: str
    newly_sealed: bool


@runtime_checkable
class ScenarioOverlayStoreSealSubset(Protocol):
    """The ``sealResult`` subset of ``ScenarioOverlayStore`` (ADD v1.3 §4.2).

    It covers ``sealResult`` and the read of a sealed result by its digest (the part
    of ``readAt`` that concerns results). The overlay operations (``openSnapshot``,
    ``forkScenario``, ``appendOverlay``, ``readAt`` on overlays, ``discard``) belong to
    OCOR-DEV-REM-0041, whose complete ``ScenarioOverlayStore`` composes these two
    methods without renaming them or changing their signatures.

    - ``seal_result`` stores the canonical serialization of ``outcome`` immutably under
      its ``reproducibility_digest``, after verifying that the digest is the content's;
      sealing an identical result again is idempotent, a different content under the
      same digest is rejected.
    - ``read_sealed_result`` returns the sealed outcome after recomputing its digest;
      a content that does not match is rejected, never returned.
    """

    def seal_result(self, outcome: CausalOutcome) -> SealedResult: ...

    def read_sealed_result(self, reproducibility_digest: str) -> CausalOutcome: ...
