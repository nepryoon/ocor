"""C5 schema registry: content-addressed payload schemas and event types.

ADD v1.3 :529: "Il ``payload`` subisce una seconda validazione obbligatoria contro lo schema
content-addressed indicato da ``payload_schema``; fallimento, schema assente o digest
discordante produce una ``Violation`` e quarantena". A schema is registered once under
``(schema_id, schema_version)``; its digest is the ``sha256:`` digest of its RFC 8785 bytes
and is never replaced. Each event type is bound to one schema pin and to the
``ResourceClass`` that determines its quota, priority and backpressure (LLD v1.1 :338).
``digest`` is the digest of the whole registry, bound into every checkpoint (LLD v1.1 :165).
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ..kernel.canonical import canonical_bytes
from .envelope import FORMATS, EnvelopeViolation, thaw
from .operations import ResourceClass


def schema_digest(document: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(thaw(document))).hexdigest()


@dataclass(frozen=True, slots=True)
class EventTypeRegistration:
    event_type_id: str
    payload_schema: Mapping[str, str]
    resource_class: ResourceClass


class SchemaRegistry:
    """In-process, append-only, content-addressed registry of one C1 release."""

    def __init__(self) -> None:
        self._schemas: dict[tuple[str, str], tuple[str, Draft202012Validator, dict[str, Any]]] = {}
        self._event_types: dict[str, EventTypeRegistration] = {}
        self._lock = threading.Lock()

    def register_schema(self, schema_id: str, schema_version: str, document: Mapping[str, Any]) -> dict[str, str]:
        if not all(isinstance(value, str) and value for value in (schema_id, schema_version)):
            raise ValueError("schema_id and schema_version are required")
        if not isinstance(document, Mapping):
            raise ValueError("a schema document is an object")
        frozen = json.loads(canonical_bytes(thaw(document)))
        try:
            Draft202012Validator.check_schema(frozen)
        except SchemaError as exc:
            raise ValueError(f"invalid JSON Schema 2020-12: {exc.message}") from exc
        digest = schema_digest(frozen)
        with self._lock:
            existing = self._schemas.get((schema_id, schema_version))
            if existing is not None and existing[0] != digest:
                raise ValueError("a registered schema version is immutable")
            self._schemas[(schema_id, schema_version)] = (digest, Draft202012Validator(frozen, format_checker=FORMATS), frozen)
        return {"schema_id": schema_id, "schema_version": schema_version, "schema_digest": digest}

    def register_event_type(
        self, event_type_id: str, *, payload_schema: Mapping[str, str], resource_class: ResourceClass
    ) -> EventTypeRegistration:
        if not isinstance(event_type_id, str) or not event_type_id:
            raise ValueError("event_type_id is required")
        if not isinstance(resource_class, ResourceClass):
            raise ValueError("a ResourceClass is required")
        pin = dict(payload_schema)
        self._resolve(pin)
        registration = EventTypeRegistration(event_type_id, MappingProxyType(pin), resource_class)
        with self._lock:
            existing = self._event_types.get(event_type_id)
            if existing is not None and existing != registration:
                raise ValueError("a registered event type is immutable")
            self._event_types[event_type_id] = registration
        return registration

    def _resolve(self, pin: Mapping[str, Any]) -> Draft202012Validator:
        schema_id, version = pin.get("schema_id"), pin.get("schema_version")
        entry = self._schemas.get((schema_id, version)) if isinstance(schema_id, str) and isinstance(version, str) else None
        if entry is None:
            raise EnvelopeViolation("UNKNOWN_SCHEMA", "the payload schema is not registered")
        if pin.get("schema_digest") != entry[0]:
            raise EnvelopeViolation("SCHEMA_DIGEST_MISMATCH", "the payload schema digest does not match the registry")
        return entry[1]

    def event_type(self, event_type_id: str) -> EventTypeRegistration:
        registration = self._event_types.get(event_type_id)
        if registration is None:
            raise EnvelopeViolation("UNKNOWN_SCHEMA", "the event type is not registered")
        return registration

    def validate_payload(self, envelope: Any) -> EventTypeRegistration:
        """The second, mandatory validation of the payload (ADD v1.3 :529)."""
        pin = dict(envelope.payload_schema)
        validator = self._resolve(pin)
        registration = self.event_type(envelope.event_type_id)
        if dict(registration.payload_schema) != pin:
            raise EnvelopeViolation("SCHEMA_VIOLATION", "the payload schema is not the one of the event type")
        if next(iter(validator.iter_errors(thaw(envelope.payload))), None) is not None:
            raise EnvelopeViolation("SCHEMA_VIOLATION", "the payload does not validate against its schema")
        return registration

    @property
    def digest(self) -> str:
        with self._lock:
            content = {
                "schemas": sorted([key[0], key[1], value[0]] for key, value in self._schemas.items()),
                "event_types": sorted(
                    [name, dict(item.payload_schema), item.resource_class.value] for name, item in self._event_types.items()
                ),
            }
        return "sha256:" + hashlib.sha256(canonical_bytes(content)).hexdigest()
