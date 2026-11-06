"""C6 -- ``G-CONTRACT``: the signed, active ActionType of a proposal (NCR-C6-002).

ADD v1.3 :2847: ``G-CONTRACT`` requires a valid schema, a signed and active ``ActionType``,
typed parameters, the declared ``effect_class``, ``risk_class``, timeout, retry, idempotency,
compensability and irreversibility, and present marking and provenance. LLD v1.1 :254 repeats
it for the C6 workflow. FR-080 (Register v1.1 :213): an ActionType without its reliability
fields is not published.

The risk class of an action is the risk class of its signed ActionType, never a value the
proposer chooses: a proposal that declares another effect or risk class than its ActionType is
refused (ADD v1.3 :2847), and without a valid risk classification the mutative request is
denied (ADD v1.3 :3298). The approval obligation then follows from that risk class
(``human_gate.gate_disposition``), and a canonical target never takes the ``NOT_REQUIRED``
disposition (LLD v1.1 :268, ``ACT-T07``).

The ActionType is published by the ontology-as-code release (C1) and signed by its publisher;
``ContractGate`` verifies the signature, the status and the active release at every
evaluation, and recomputes the ActionType digest the proposal pins.
"""

from __future__ import annotations

import hmac
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, ClassVar, Protocol, runtime_checkable

from ..c1.signing import Ed25519SigningKey
from ..errors import OCORError
from ..kernel.governance import RiskClass
from . import records
from .human_gate import ActiveReleasePort, SignerKeyring, signature_valid, signed_with

ACTION_TYPE_PAYLOAD_TYPE = "application/vnd.ocor.c1.action-type+json"
ACTION_TYPE_STATUSES = frozenset({"ACTIVE", "RETIRED"})
IRREVERSIBILITY_CLASSES = frozenset({"REVERSIBLE", "COMPENSABLE", "IRREVERSIBLE"})
PARAMETER_TYPES = frozenset({"string", "integer", "boolean"})


class ContractGateError(OCORError):
    """``G-CONTRACT`` refused. ``reason_code`` is one of SCHEMA_INVALID, ACTION_TYPE_UNKNOWN,
    ACTION_TYPE_SIGNATURE_INVALID, ACTION_TYPE_INACTIVE, ACTION_TYPE_MISMATCH and
    PARAMETERS_INVALID."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _parameter_schema(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise records.C6RecordError("RECORD_INVALID", "parameters must map each parameter name to its type")
    schema: dict[str, str] = {}
    for name, kind in value.items():
        schema[records.text_field("parameters", name)] = records.choice_field("parameters", kind, PARAMETER_TYPES)
    return MappingProxyType(dict(sorted(schema.items())))


@dataclass(frozen=True, slots=True)
class ActionType(records.SignedRecord):
    """A signed ActionType of the active release: effect and risk class, the capability it
    exercises, whether its target is canonical, its typed parameters and the reliability
    policy of FR-080 (timeout, retry, idempotency scope, compensability, irreversibility),
    with marking and provenance (ADD v1.3 :2847)."""

    RECORD_TYPE: ClassVar[str] = "ActionType"
    PAYLOAD_TYPE: ClassVar[str] = ACTION_TYPE_PAYLOAD_TYPE

    action_type_ref: str
    version: int
    status: str
    effect_class: str
    risk_class: RiskClass
    capability: str
    canonical_target: bool
    parameters: Mapping[str, str]
    timeout_seconds: int
    max_attempts: int
    idempotency_scope: str
    compensable: bool
    compensation_ref: str
    irreversibility_class: str
    marking_ref: str
    provenance_ref: str
    release_digest: str
    publisher_id: str
    keyid: str
    signature: str

    def __post_init__(self) -> None:
        for name in (
            "action_type_ref",
            "effect_class",
            "capability",
            "idempotency_scope",
            "compensation_ref",
            "provenance_ref",
            "publisher_id",
            "keyid",
        ):
            records.text_field(name, getattr(self, name))
        records.count_field("version", self.version, minimum=1)
        records.choice_field("status", self.status, ACTION_TYPE_STATUSES)
        object.__setattr__(self, "risk_class", records.risk_field("risk_class", self.risk_class))
        for name in ("canonical_target", "compensable"):
            if not isinstance(getattr(self, name), bool):
                raise records.C6RecordError("RECORD_INVALID", f"{name} must be a boolean")
        object.__setattr__(self, "parameters", _parameter_schema(self.parameters))
        records.count_field("timeout_seconds", self.timeout_seconds, minimum=1)
        records.count_field("max_attempts", self.max_attempts, minimum=1)
        records.choice_field("irreversibility_class", self.irreversibility_class, IRREVERSIBILITY_CLASSES)
        # ADD v1.3 :3303: an irreversible action is R3_HIGH_IMPACT; R2_CONTROLLED is reversible.
        if self.irreversibility_class == "IRREVERSIBLE" and (
            self.risk_class is not RiskClass.R3_HIGH_IMPACT or self.compensable
        ):
            raise records.C6RecordError(
                "RECORD_INVALID", "an irreversible ActionType is R3_HIGH_IMPACT and not compensable"
            )
        if self.irreversibility_class == "COMPENSABLE" and not self.compensable:
            raise records.C6RecordError("RECORD_INVALID", "a compensable ActionType declares compensable")
        records.digest_field("marking_ref", self.marking_ref)
        records.digest_field("release_digest", self.release_digest)
        records.signature_field("signature", self.signature)


def sign_action_type(key: Ed25519SigningKey, **values: Any) -> ActionType:
    """The publisher's signature of an ActionType (the C1 release publishes it signed)."""

    return signed_with(key, ActionType(**{**values, "signature": records.PLACEHOLDER_SIGNATURE}))


@runtime_checkable
class ActionTypeCatalog(Protocol):
    """The ActionTypes of the ontology-as-code release, by reference."""

    def action_type(self, action_type_ref: str) -> ActionType | None: ...


class InMemoryActionTypeCatalog:
    """Catalog of published ActionTypes; publishing accepts only a complete ActionType
    (FR-080) and retiring publishes the same ActionType with status ``RETIRED``."""

    def __init__(self) -> None:
        self._types: dict[str, ActionType] = {}
        self._lock = threading.Lock()

    def publish(self, action_type: ActionType) -> None:
        if not isinstance(action_type, ActionType):
            raise TypeError("only a complete, signed ActionType is published")
        with self._lock:
            self._types[action_type.action_type_ref] = action_type

    def retire(self, action_type_ref: str, *, key: Ed25519SigningKey) -> ActionType:
        with self._lock:
            current = self._types.get(action_type_ref) if isinstance(action_type_ref, str) else None
            if current is None:
                raise ContractGateError("ACTION_TYPE_UNKNOWN", "no ActionType is published under this reference")
            retired = signed_with(key, replace(current, status="RETIRED", signature=records.PLACEHOLDER_SIGNATURE))
            self._types[action_type_ref] = retired
            return retired

    def action_type(self, action_type_ref: str) -> ActionType | None:
        with self._lock:
            return self._types.get(action_type_ref)


def _typed(kind: str, value: object) -> bool:
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, str)


class ContractGate:
    """``G-CONTRACT`` of the action path (ADD v1.3 :2847, LLD v1.1 :254)."""

    def __init__(self, *, catalog: ActionTypeCatalog, publishers: SignerKeyring, releases: ActiveReleasePort) -> None:
        if not isinstance(catalog, ActionTypeCatalog):
            raise TypeError("catalog must implement ActionTypeCatalog")
        if not isinstance(publishers, SignerKeyring):
            raise TypeError("publishers must implement SignerKeyring")
        if not isinstance(releases, ActiveReleasePort):
            raise TypeError("releases must implement ActiveReleasePort")
        self._catalog = catalog
        self._publishers = publishers
        self._releases = releases

    def evaluate(self, proposal: object) -> ActionType:
        if not isinstance(proposal, records.ActionProposal):
            raise ContractGateError("SCHEMA_INVALID", "G-CONTRACT evaluates an ActionProposal")
        action_type = self._catalog.action_type(proposal.action_type_ref)
        if not isinstance(action_type, ActionType) or action_type.action_type_ref != proposal.action_type_ref:
            raise ContractGateError("ACTION_TYPE_UNKNOWN", "no ActionType is published for the proposal")
        if not signature_valid(self._publishers, action_type.publisher_id, action_type):
            raise ContractGateError("ACTION_TYPE_SIGNATURE_INVALID", "the ActionType signature does not verify")
        if action_type.status != "ACTIVE" or action_type.release_digest != self._releases.active_release_digest():
            raise ContractGateError("ACTION_TYPE_INACTIVE", "the ActionType is not active in the active release")
        if not hmac.compare_digest(action_type.digest(), proposal.action_type_digest):
            raise ContractGateError("ACTION_TYPE_MISMATCH", "the proposal pins another ActionType")
        if proposal.effect_class != action_type.effect_class or proposal.risk_class != action_type.risk_class:
            raise ContractGateError(
                "ACTION_TYPE_MISMATCH", "the proposal declares another effect or risk class than its ActionType"
            )
        given = proposal.parameters
        if set(given) != set(action_type.parameters) or not all(
            _typed(kind, given[name]) for name, kind in action_type.parameters.items()
        ):
            raise ContractGateError("PARAMETERS_INVALID", "the parameters are not those the ActionType types")
        return action_type


def proposal_for(
    action_type: ActionType,
    *,
    action_instance_id: str,
    proposer_id: str,
    target_ref: str,
    parameters: Mapping[str, Any],
    governed_context_digest: str,
    expected_revision: int,
    evidence_refs: tuple[str, ...],
    proposed_at: datetime,
) -> records.ActionProposal:
    """An ActionProposal pinned to an ActionType: the effect and risk class are the type's."""

    if not isinstance(action_type, ActionType):
        raise ContractGateError("SCHEMA_INVALID", "a proposal is built on a signed ActionType")
    return records.ActionProposal(
        action_instance_id=action_instance_id,
        proposer_id=proposer_id,
        action_type_ref=action_type.action_type_ref,
        action_type_digest=action_type.digest(),
        effect_class=action_type.effect_class,
        risk_class=action_type.risk_class,
        target_ref=target_ref,
        parameters=parameters,
        governed_context_digest=governed_context_digest,
        expected_revision=expected_revision,
        evidence_refs=evidence_refs,
        proposed_at=proposed_at,
    )
