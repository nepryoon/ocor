"""C5 Subscribe surface: Event Subscription Contract, delivered events and opaque cursors.

ADD v1.3 :2573-2575: ``ContractDefinition.kind = EVENT`` defines the subscription and change
feed surface materialised by C5 through the port ``Subscribe`` (Register :79, FR-016); "non
espone dialect, offset fisici del broker o identificativi interni: il consumer si muove per
``subscription_id`` e cursor opaco". ``SUBSCRIPTION_CONTRACT_SCHEMA`` is the JSON Schema
2020-12 of ADD v1.3 :2577-2700, verbatim; a contract that does not validate is
``SCHEMA_VIOLATION``. A ``DeliveredEvent`` carries the subscription and the admitted envelope
only: no partition and no offset. Delivery is at least once and the consumer deduplicates by
``event_id`` (the contract's ``delivery`` block).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from .envelope import FORMATS, CanonicalIngestionEnvelope, EnvelopeViolation, thaw

# ADD v1.3 :2577-2700, event-subscription-contract:1.1 (verbatim).
SUBSCRIPTION_CONTRACT_SCHEMA: dict[str, Any] = json.loads(
    r"""
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:ocor:schema:event-subscription-contract:1.1",
  "title": "OCOR Event Subscription Contract",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "subscription_contract_id",
    "version",
    "contract_digest",
    "governed_context_ref",
    "event_type_refs",
    "delivery",
    "ordering",
    "filter",
    "payload_schema",
    "marking_policy",
    "replay",
    "error_codes"
  ],
  "properties": {
    "subscription_contract_id": {"$ref": "#/$defs/stableId"},
    "version": {"$ref": "#/$defs/semver"},
    "contract_digest": {"$ref": "#/$defs/digest"},
    "governed_context_ref": {"type": "string", "pattern": "^urn:sha256:[0-9a-f]{64}$"},
    "event_type_refs": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/stableId"}
    },
    "delivery": {
      "type": "object",
      "additionalProperties": false,
      "required": ["semantics", "consumer_must_deduplicate", "dedup_key"],
      "properties": {
        "semantics": {"const": "AT_LEAST_ONCE"},
        "consumer_must_deduplicate": {"const": true},
        "dedup_key": {"const": "event_id"},
        "max_in_flight": {"type": "integer", "minimum": 1}
      }
    },
    "ordering": {
      "type": "object",
      "additionalProperties": false,
      "required": ["guarantee", "ordering_key_field"],
      "properties": {
        "guarantee": {"const": "PER_ORDERING_KEY"},
        "ordering_key_field": {"const": "ordering_key"}
      }
    },
    "filter": {
      "type": "object",
      "additionalProperties": false,
      "required": ["filter_contract_id", "arbitrary_predicates_allowed"],
      "properties": {
        "filter_contract_id": {"$ref": "#/$defs/stableId"},
        "arbitrary_predicates_allowed": {"const": false}
      }
    },
    "payload_schema": {"$ref": "#/$defs/schemaPin"},
    "marking_policy": {
      "type": "object",
      "additionalProperties": false,
      "required": ["propagate_marking", "redact_unauthorized", "declare_redactions"],
      "properties": {
        "propagate_marking": {"const": true},
        "redact_unauthorized": {"const": true},
        "declare_redactions": {"const": true}
      }
    },
    "replay": {
      "type": "object",
      "additionalProperties": false,
      "required": ["replay_allowed", "cursor_opaque", "authorization_required"],
      "properties": {
        "replay_allowed": {"type": "boolean"},
        "cursor_opaque": {"const": true},
        "authorization_required": {"const": true},
        "max_replay_window": {"type": "string", "pattern": "^P[0-9]+D$"}
      }
    },
    "error_codes": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {
        "enum": [
          "POLICY_DENIED",
          "AUTHORITY_MISSING",
          "SCHEMA_VIOLATION",
          "RELEASE_MISMATCH",
          "SUBSCRIPTION_NOT_FOUND",
          "CURSOR_EXPIRED",
          "REPLAY_DENIED",
          "CONTROL_PLANE_UNAVAILABLE"
        ]
      }
    }
  },
  "allOf": [
    {
      "if": {
        "properties": {
          "replay": {
            "properties": {"replay_allowed": {"const": true}},
            "required": ["replay_allowed"]
          }
        },
        "required": ["replay"]
      },
      "then": {"properties": {"replay": {"required": ["max_replay_window"]}}}
    },
    {
      "if": {
        "properties": {
          "replay": {
            "properties": {"replay_allowed": {"const": false}},
            "required": ["replay_allowed"]
          }
        },
        "required": ["replay"]
      },
      "then": {"properties": {"replay": {"not": {"required": ["max_replay_window"]}}}}
    }
  ],
  "$defs": {
    "stableId": {
      "type": "string",
      "pattern": "^urn:ocor:[A-Za-z0-9._~:/-]{1,240}$"
    },
    "semver": {
      "type": "string",
      "pattern": "^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\\+[0-9A-Za-z.-]+)?$"
    },
    "digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "schemaPin": {
      "type": "object",
      "additionalProperties": false,
      "required": ["schema_id", "version", "digest"],
      "properties": {
        "schema_id": {"$ref": "#/$defs/stableId"},
        "version": {"$ref": "#/$defs/semver"},
        "digest": {"$ref": "#/$defs/digest"}
      }
    }
  }
}
"""
)
_VALIDATOR = Draft202012Validator(SUBSCRIPTION_CONTRACT_SCHEMA, format_checker=FORMATS)


def validate_contract(contract: object) -> dict[str, Any]:
    if not isinstance(contract, Mapping):
        raise EnvelopeViolation("SCHEMA_VIOLATION", "the subscription contract is not an object")
    candidate = thaw(contract)
    error = next(iter(sorted(_VALIDATOR.iter_errors(candidate), key=lambda item: list(item.absolute_path))), None)
    if error is not None:
        where = "/".join(str(part) for part in error.absolute_path) or "(root)"
        raise EnvelopeViolation("SCHEMA_VIOLATION", f"subscription contract {where}: {error.validator} constraint not met")
    assert isinstance(candidate, dict)
    return candidate


@dataclass(frozen=True, slots=True)
class DeliveredEvent:
    """One delivery of an admitted envelope to a subscription (no broker coordinates)."""

    subscription_id: str
    envelope: CanonicalIngestionEnvelope


@dataclass(frozen=True, slots=True)
class SubscriptionBatch:
    events: tuple[DeliveredEvent, ...]
    cursor: str


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    cursor: str
    delivered: tuple[str, ...]
    quarantined: tuple[str, ...]
