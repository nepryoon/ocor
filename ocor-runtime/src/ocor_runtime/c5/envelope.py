"""C5 envelope: ``canonical-ingestion-envelope:1.2``, producer signature and C5 errors.

Realises the envelope validator of ADD v1.3 :286 (module "Envelope validator") and the closed
envelope of LLD v1.1 :154 ("Producer firma envelope e digest"):

- ``ENVELOPE_SCHEMA`` is the JSON Schema 2020-12 of ADD v1.3 :531-840, verbatim. An envelope is
  admitted only if it validates, with ``format`` asserted for ``uuid`` and ``date-time``; a
  missing, extra or malformed field is a typed ``Violation`` (``SCHEMA_VIOLATION``, class
  ``PERMANENT``): "incomplete -> REJECTED" (ADD v1.3 :379), Register :199 (FR-069).
- The producer signs the envelope and its payload digest: ``integrity.payload_digest`` is the
  ``sha256:`` digest of the RFC 8785 bytes of ``payload``; the Ed25519 signature covers the DSSE
  pre-authentication encoding of the RFC 8785 bytes of the whole envelope without
  ``integrity.signature_ref``; ``integrity.signature_ref`` is the ``urn:sha256:`` content
  reference of the signature bytes.
- ``CanonicalIngestionEnvelope`` is deeply immutable: every mapping is read-only and every array
  a tuple, so an admitted or dead-lettered envelope can never change.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from ..c1.signing import Ed25519SigningKey, dsse_pae, ed25519_verify
from ..kernel.canonical import canonical_bytes

ENVELOPE_SCHEMA_ID = "urn:ocor:schema:canonical-ingestion-envelope:1.2"
SIGNATURE_PAYLOAD_TYPE = "application/vnd.ocor.canonical-ingestion-envelope+json"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
CONTENT_REF = re.compile(r"urn:sha256:[0-9a-f]{64}")
RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})")

# ADD v1.3 :531-840, canonical-ingestion-envelope:1.2 (verbatim).
ENVELOPE_SCHEMA: dict[str, Any] = json.loads(
    r"""
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:ocor:schema:canonical-ingestion-envelope:1.2",
  "title": "OCOR Canonical Ingestion Envelope",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "envelope_version",
    "event_id",
    "tenant_id",
    "organization_id",
    "domain_id",
    "compartments",
    "world_ref",
    "ingest_mode",
    "semantic_class",
    "event_type_id",
    "event_time",
    "ingest_time",
    "ordering_key",
    "idempotency_key",
    "purpose",
    "source",
    "aggregate",
    "payload_schema",
    "payload",
    "classification_marking",
    "provenance_ref",
    "integrity",
    "effective_principal_id",
    "actor_chain",
    "governed_context_digest",
    "ontology_release_digest",
    "policy_bundle_digest",
    "correlation_id",
    "transport"
  ],
  "properties": {
    "envelope_version": {"const": "1.2"},
    "event_id": {"type": "string", "format": "uuid"},
    "tenant_id": {"$ref": "#/$defs/stableId"},
    "organization_id": {"$ref": "#/$defs/stableId"},
    "domain_id": {"$ref": "#/$defs/stableId"},
    "compartments": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/stableId"}
    },
    "purpose": {"type": "string", "minLength": 1, "maxLength": 256},
    "effective_principal_id": {"$ref": "#/$defs/stableId"},
    "actor_chain": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/stableId"}
    },
    "governed_context_digest": {"$ref": "#/$defs/digest"},
    "ontology_release_digest": {"$ref": "#/$defs/digest"},
    "policy_bundle_digest": {"$ref": "#/$defs/digest"},
    "world_ref": {"$ref": "#/$defs/stableId"},
    "ingest_mode": {"enum": ["BATCH", "STREAM", "CDC"]},
    "semantic_class": {
      "enum": ["OBSERVATION", "CLAIM", "OBSERVED_EVENT", "CDC_CHANGE"]
    },
    "event_type_id": {"$ref": "#/$defs/stableId"},
    "event_time": {"type": "string", "format": "date-time"},
    "effective_time": {
      "type": "object",
      "additionalProperties": false,
      "required": ["from"],
      "properties": {
        "from": {"type": "string", "format": "date-time"},
        "to": {
          "oneOf": [
            {"type": "string", "format": "date-time"},
            {"type": "null"}
          ]
        }
      }
    },
    "ingest_time": {"type": "string", "format": "date-time"},
    "ordering_key": {"type": "string", "minLength": 1, "maxLength": 512},
    "idempotency_key": {"type": "string", "minLength": 16, "maxLength": 256},
    "source": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "source_id",
        "source_record_id",
        "adapter_id",
        "adapter_version"
      ],
      "properties": {
        "source_id": {"$ref": "#/$defs/stableId"},
        "source_record_id": {"type": "string", "minLength": 1, "maxLength": 512},
        "adapter_id": {"$ref": "#/$defs/stableId"},
        "adapter_version": {"$ref": "#/$defs/semver"},
        "source_event_time_quality": {
          "enum": ["SOURCE_ASSERTED", "DERIVED", "UNKNOWN"]
        }
      }
    },
    "aggregate": {
      "type": "object",
      "additionalProperties": false,
      "required": ["aggregate_type_id", "aggregate_id"],
      "properties": {
        "aggregate_type_id": {"$ref": "#/$defs/stableId"},
        "aggregate_id": {"type": "string", "minLength": 1, "maxLength": 512},
        "expected_revision": {"type": "integer", "minimum": 0}
      }
    },
    "payload_schema": {"$ref": "#/$defs/schemaPin"},
    "payload": {"type": "object"},
    "classification_marking": {"$ref": "#/$defs/marking"},
    "provenance_ref": {"$ref": "#/$defs/contentRef"},
    "integrity": {
      "type": "object",
      "additionalProperties": false,
      "required": ["payload_digest", "source_producer_principal_ref"],
      "properties": {
        "payload_digest": {"$ref": "#/$defs/digest"},
        "source_producer_principal_ref": {"$ref": "#/$defs/stableId"},
        "signature_ref": {"$ref": "#/$defs/contentRef"}
      }
    },
    "correlation_id": {"type": "string", "format": "uuid"},
    "causation_id": {
      "oneOf": [
        {"type": "string", "format": "uuid"},
        {"type": "null"}
      ]
    },
    "transport": {
      "oneOf": [
        {"$ref": "#/$defs/batchTransport"},
        {"$ref": "#/$defs/streamTransport"},
        {"$ref": "#/$defs/cdcTransport"}
      ]
    }
  },
  "allOf": [
    {
      "if": {
        "properties": {"ingest_mode": {"const": "BATCH"}},
        "required": ["ingest_mode"]
      },
      "then": {"properties": {"transport": {"$ref": "#/$defs/batchTransport"}}}
    },
    {
      "if": {
        "properties": {"ingest_mode": {"const": "STREAM"}},
        "required": ["ingest_mode"]
      },
      "then": {"properties": {"transport": {"$ref": "#/$defs/streamTransport"}}}
    },
    {
      "if": {
        "properties": {"ingest_mode": {"const": "CDC"}},
        "required": ["ingest_mode"]
      },
      "then": {
        "properties": {
          "semantic_class": {"const": "CDC_CHANGE"},
          "transport": {"$ref": "#/$defs/cdcTransport"}
        }
      }
    },
    {
      "if": {
        "properties": {"semantic_class": {"const": "CDC_CHANGE"}},
        "required": ["semantic_class"]
      },
      "then": {
        "properties": {
          "ingest_mode": {"const": "CDC"},
          "transport": {"$ref": "#/$defs/cdcTransport"}
        }
      }
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
    "digest": {
      "type": "string",
      "pattern": "^sha256:[0-9a-f]{64}$"
    },
    "contentRef": {
      "type": "string",
      "pattern": "^urn:sha256:[0-9a-f]{64}$"
    },
    "schemaPin": {
      "type": "object",
      "additionalProperties": false,
      "required": ["schema_id", "schema_version", "schema_digest"],
      "properties": {
        "schema_id": {"$ref": "#/$defs/stableId"},
        "schema_version": {"$ref": "#/$defs/semver"},
        "schema_digest": {"$ref": "#/$defs/digest"}
      }
    },
    "marking": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "scheme_id",
        "labels",
        "mandatory_markings",
        "caveats",
        "dissemination_controls",
        "permitted_purposes",
        "handling_instructions",
        "marking_digest"
      ],
      "properties": {
        "scheme_id": {"$ref": "#/$defs/stableId"},
        "labels": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {"type": "string", "minLength": 1, "maxLength": 128}
        },
        "dissemination_controls": {
          "type": "array",
          "uniqueItems": true,
          "items": {"type": "string", "minLength": 1, "maxLength": 128}
        },
        "mandatory_markings": {
          "type": "array",
          "uniqueItems": true,
          "items": {"type": "string", "minLength": 1, "maxLength": 128}
        },
        "caveats": {
          "type": "array",
          "uniqueItems": true,
          "items": {"type": "string", "minLength": 1, "maxLength": 128}
        },
        "permitted_purposes": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {"type": "string", "minLength": 1, "maxLength": 128}
        },
        "handling_instructions": {
          "type": "array",
          "uniqueItems": true,
          "items": {"type": "string", "minLength": 1, "maxLength": 256}
        },
        "marking_digest": {"$ref": "#/$defs/digest"}
      }
    },
    "batchTransport": {
      "type": "object",
      "additionalProperties": false,
      "required": ["mode", "batch_id", "record_index"],
      "properties": {
        "mode": {"const": "BATCH"},
        "batch_id": {"type": "string", "format": "uuid"},
        "record_index": {"type": "integer", "minimum": 0}
      }
    },
    "streamTransport": {
      "type": "object",
      "additionalProperties": false,
      "required": ["mode", "stream_id", "partition", "offset"],
      "properties": {
        "mode": {"const": "STREAM"},
        "stream_id": {"$ref": "#/$defs/stableId"},
        "partition": {"type": "integer", "minimum": 0},
        "offset": {"type": "string", "minLength": 1, "maxLength": 256}
      }
    },
    "cdcTransport": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "mode",
        "operation",
        "source_transaction_id",
        "source_position"
      ],
      "properties": {
        "mode": {"const": "CDC"},
        "operation": {"enum": ["CREATE", "UPDATE", "DELETE", "SNAPSHOT"]},
        "source_transaction_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 256
        },
        "source_position": {"type": "string", "minLength": 1, "maxLength": 256},
        "before_digest": {
          "oneOf": [{"$ref": "#/$defs/digest"}, {"type": "null"}]
        },
        "after_digest": {
          "oneOf": [{"$ref": "#/$defs/digest"}, {"type": "null"}]
        }
      }
    }
  }
}
"""
)


class BackboneError(RuntimeError):
    """A governed C5 refusal: a reason code and the failure class of LLD v1.1 :156-163."""

    def __init__(self, reason_code: str, message: str, *, failure_class: str = "PERMANENT") -> None:
        self.reason_code = reason_code
        self.failure_class = failure_class
        super().__init__(f"{reason_code}: {message}")


class EnvelopeViolation(BackboneError):
    """A typed ``Violation`` of the envelope contract (ADD v1.3 :529, Register :199)."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(reason_code, message, failure_class="PERMANENT")


def _date_time(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if RFC3339.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("z", "Z").replace("t", "T"))
    except ValueError:
        return False
    return True


def _uuid(value: object) -> bool:
    if not isinstance(value, str):
        return True
    try:
        return str(uuid.UUID(value)) == value.lower() and len(value) == 36
    except ValueError:
        return False


FORMATS = FormatChecker(formats=())
FORMATS.checks("date-time")(_date_time)
FORMATS.checks("uuid")(_uuid)
_VALIDATOR = Draft202012Validator(ENVELOPE_SCHEMA, format_checker=FORMATS)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """A mutable deep copy of a frozen value (for serialisation and callers)."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [thaw(item) for item in value]
    return value


def payload_digest(payload: Mapping[str, Any]) -> str:
    """``sha256:`` digest of the RFC 8785 bytes of a payload (ADD v1.3 ``$defs.digest``)."""
    return "sha256:" + hashlib.sha256(canonical_bytes(thaw(payload))).hexdigest()


def content_ref(data: bytes) -> str:
    return "urn:sha256:" + hashlib.sha256(data).hexdigest()


def _validate(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EnvelopeViolation("SCHEMA_VIOLATION", "the envelope is not an object")
    try:
        candidate = json.loads(canonical_bytes(thaw(value)))
    except (TypeError, ValueError) as exc:
        raise EnvelopeViolation("SCHEMA_VIOLATION", "the envelope is not canonical I-JSON") from exc
    errors = sorted(_VALIDATOR.iter_errors(candidate), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(part) for part in first.absolute_path) or "(root)"
        raise EnvelopeViolation("SCHEMA_VIOLATION", f"{where}: {first.validator} constraint not met")
    if not isinstance(candidate, dict):
        raise EnvelopeViolation("SCHEMA_VIOLATION", "the envelope is not an object")
    return candidate


@dataclass(frozen=True, slots=True, init=False)
class CanonicalIngestionEnvelope:
    """An admitted ``canonical-ingestion-envelope:1.2`` (ADD v1.3 :531-840), deeply immutable."""

    _value: Mapping[str, Any]

    def __init__(self, value: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_value", _freeze(_validate(value)))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CanonicalIngestionEnvelope:
        return cls(value)

    def to_mapping(self) -> dict[str, Any]:
        result = thaw(self._value)
        assert isinstance(result, dict)
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.to_mapping())

    def __getitem__(self, name: str) -> Any:
        return self._value[name]

    @property
    def event_id(self) -> str:
        return str(self._value["event_id"])

    @property
    def tenant_id(self) -> str:
        return str(self._value["tenant_id"])

    @property
    def event_type_id(self) -> str:
        return str(self._value["event_type_id"])

    @property
    def ordering_key(self) -> str:
        return str(self._value["ordering_key"])

    @property
    def idempotency_key(self) -> str:
        return str(self._value["idempotency_key"])

    @property
    def governed_context_digest(self) -> str:
        return str(self._value["governed_context_digest"])

    @property
    def ontology_release_digest(self) -> str:
        return str(self._value["ontology_release_digest"])

    @property
    def effective_principal_id(self) -> str:
        return str(self._value["effective_principal_id"])

    @property
    def ingest_time(self) -> datetime:
        return datetime.fromisoformat(str(self._value["ingest_time"]).replace("z", "Z").replace("t", "T"))

    @property
    def payload(self) -> Mapping[str, Any]:
        payload = self._value["payload"]
        assert isinstance(payload, Mapping)
        return payload

    @property
    def payload_schema(self) -> Mapping[str, Any]:
        pin = self._value["payload_schema"]
        assert isinstance(pin, Mapping)
        return pin

    @property
    def integrity(self) -> Mapping[str, Any]:
        integrity = self._value["integrity"]
        assert isinstance(integrity, Mapping)
        return integrity

    @property
    def aggregate(self) -> Mapping[str, Any]:
        aggregate = self._value["aggregate"]
        assert isinstance(aggregate, Mapping)
        return aggregate

    def signing_bytes(self) -> bytes:
        """The bytes the producer signature covers: DSSE PAE of the envelope without
        ``integrity.signature_ref``."""
        view = self.to_mapping()
        view["integrity"].pop("signature_ref", None)
        return dsse_pae(SIGNATURE_PAYLOAD_TYPE, canonical_bytes(view))


@dataclass(frozen=True, slots=True)
class SignedEnvelope:
    """An envelope with the detached producer signature its ``integrity.signature_ref`` names."""

    envelope: CanonicalIngestionEnvelope
    signature: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, CanonicalIngestionEnvelope):
            raise EnvelopeViolation("SCHEMA_VIOLATION", "a CanonicalIngestionEnvelope is required")
        if not isinstance(self.signature, bytes) or len(self.signature) != 64:
            raise EnvelopeViolation("SIGNATURE_INVALID", "an Ed25519 signature is 64 bytes")


class ProducerSigner:
    """The producer side of LLD v1.1 :154: fills ``integrity`` and signs envelope and digest."""

    def __init__(self, principal_ref: str, key: Ed25519SigningKey) -> None:
        if not isinstance(principal_ref, str) or not principal_ref:
            raise ValueError("a producer principal reference is required")
        if not isinstance(key, Ed25519SigningKey):
            raise TypeError("an Ed25519 signing key is required")
        self._principal = principal_ref
        self._key = key

    def __repr__(self) -> str:
        return f"ProducerSigner(principal_ref={self._principal!r})"

    def sign(self, value: Mapping[str, Any]) -> SignedEnvelope:
        draft = thaw(value)
        if not isinstance(draft, dict) or not isinstance(draft.get("payload"), dict):
            raise EnvelopeViolation("SCHEMA_VIOLATION", "the envelope and its payload must be objects")
        integrity = draft.get("integrity")
        integrity = dict(integrity) if isinstance(integrity, dict) else {}
        integrity.pop("signature_ref", None)
        integrity["payload_digest"] = payload_digest(draft["payload"])
        integrity["source_producer_principal_ref"] = self._principal
        draft["integrity"] = integrity
        unsigned = CanonicalIngestionEnvelope.from_mapping(draft)
        signature = self._key.sign(unsigned.signing_bytes())
        draft["integrity"]["signature_ref"] = content_ref(signature)
        return SignedEnvelope(CanonicalIngestionEnvelope.from_mapping(draft), signature)


class ProducerKeyring:
    """Trusted Ed25519 public keys of the producers, by producer principal reference."""

    def __init__(self, keys: Mapping[str, bytes]) -> None:
        if not isinstance(keys, Mapping) or not keys:
            raise ValueError("at least one trusted producer key is required")
        for principal, key in keys.items():
            if not isinstance(principal, str) or not principal or not isinstance(key, bytes) or len(key) != 32:
                raise ValueError("producer keys map principal references to 32-byte Ed25519 public keys")
        self._keys = MappingProxyType(dict(keys))

    def verify(self, signed: SignedEnvelope) -> None:
        """Verify the payload digest, the signature reference and the producer signature."""
        envelope = signed.envelope
        integrity = envelope.integrity
        if integrity.get("payload_digest") != payload_digest(envelope.payload):
            raise EnvelopeViolation("PAYLOAD_DIGEST_MISMATCH", "the payload does not match its signed digest")
        if integrity.get("signature_ref") != content_ref(signed.signature):
            raise EnvelopeViolation("SIGNATURE_INVALID", "the signature does not match its reference")
        key = self._keys.get(str(integrity.get("source_producer_principal_ref")))
        if key is None or not ed25519_verify(key, envelope.signing_bytes(), signed.signature):
            raise EnvelopeViolation("SIGNATURE_INVALID", "the producer signature does not verify")
