"""C2 closed Problem model (Named Query Gateway contract, RFC 9457 restricted profile).

Realises ``Problem`` of
``ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml``
:435-485: the thirteen closed reason codes, the mandatory ``served`` for
``STALE_CONTEXT``, ``PROJECTION_NOT_READY`` and ``RELEASE_MISMATCH`` and the mandatory
``deferred_element`` for ``CAPABILITY_DEFERRED`` (ADD v1.3 :1362), and no other extension
member. The document is produced in the wire form of the contract (digests
``sha256:<hex>``, NORMATIVE-CONFORMANCE-PLAN point 4, NCR-C2-008 option 2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..kernel.canonical import canonical_digest

if TYPE_CHECKING:
    from .ports import C2Error, ServedContext

PROBLEM_REASON_CODES = (
    "POLICY_DENIED",
    "AUTHORITY_MISSING",
    "CAPABILITY_DENIED",
    "CONTRACT_NOT_FOUND",
    "CONTRACT_DIGEST_MISMATCH",
    "SCHEMA_VIOLATION",
    "PROJECTION_NOT_READY",
    "STALE_CONTEXT",
    "RELEASE_MISMATCH",
    "UNSUPPORTED_CAPABILITY",
    "CAPABILITY_DEFERRED",
    "CONTROL_PLANE_UNAVAILABLE",
    "SCENARIO_ISOLATION_VIOLATION",
)
SERVED_REQUIRED = frozenset({"STALE_CONTEXT", "PROJECTION_NOT_READY", "RELEASE_MISMATCH"})

# HTTP status of each closed reason code (contract :449, status 400..599).
PROBLEM_STATUS = {
    "POLICY_DENIED": 403,
    "AUTHORITY_MISSING": 401,
    "CAPABILITY_DENIED": 403,
    "CONTRACT_NOT_FOUND": 404,
    "CONTRACT_DIGEST_MISMATCH": 409,
    "SCHEMA_VIOLATION": 400,
    "PROJECTION_NOT_READY": 503,
    "STALE_CONTEXT": 409,
    "RELEASE_MISMATCH": 409,
    "UNSUPPORTED_CAPABILITY": 501,
    "CAPABILITY_DEFERRED": 501,
    "CONTROL_PLANE_UNAVAILABLE": 503,
    "SCENARIO_ISOLATION_VIOLATION": 403,
}
PROBLEM_MEDIA_TYPE = "application/problem+json"


def wire_digest(value: str) -> str:
    """``urn:sha256:<hex>`` (internal, LLD v1.1 :37) to ``sha256:<hex>`` (gateway wire)."""
    return "sha256:" + value.removeprefix("urn:sha256:")


def served_document(
    served: ServedContext, *, result_marking_ref: str | None = None, provenance_ref: str | None = None
) -> dict[str, Any]:
    """The contract ``ServedContext`` (:254-273) of an internal served context.

    ``result_marking_ref`` and ``provenance_ref`` are those the gateway computed for the
    result; when absent (an error before any result), the marking reference under which
    the error is disclosed and the content address of the served observation are used,
    so that the mandatory members are never fabricated from nothing.
    """

    marking = served.result_marking_ref or result_marking_ref
    if marking is None:
        raise ValueError("a served context needs the marking reference under which it is disclosed")
    observation = {
        "branch": served.branch,
        "ontology_release_digest": served.ontology_release_digest,
        "canonical_commit": served.canonical_commit,
        "projection_watermark": served.projection_watermark,
        "staleness_ms": served.staleness_ms,
        "governed_context_digest": served.governed_context_digest,
        "policy_bundle_digest": served.policy_bundle_digest,
    }
    provenance = served.provenance_ref or provenance_ref or canonical_digest(observation)
    document: dict[str, Any] = {
        "ontology_release": wire_digest(served.ontology_release_digest),
        "branch": served.branch,
        "served_commit": served.canonical_commit,
        "watermark": served.projection_watermark,
        "staleness_ms": served.staleness_ms,
        "result_marking_ref": marking,
        "provenance_ref": provenance,
    }
    if served.redaction_count:
        document["redaction_count"] = served.redaction_count
    return document


def problem_document(error: C2Error, *, correlation_id: str, result_marking_ref: str) -> dict[str, Any]:
    """The contract Problem document of a typed C2 failure (wire form)."""

    code = error.reason_code
    document: dict[str, Any] = {
        "type": "urn:ocor:problem:" + code.lower().replace("_", "-"),
        "title": code.replace("_", " ").capitalize(),
        "status": PROBLEM_STATUS[code],
        "reason_code": code,
        "correlation_id": correlation_id,
        "detail": error.detail[:1024],
    }
    if error.served is not None:
        document["served"] = served_document(error.served, result_marking_ref=result_marking_ref)
    if error.deferred_element is not None:
        document["deferred_element"] = error.deferred_element
    return document
