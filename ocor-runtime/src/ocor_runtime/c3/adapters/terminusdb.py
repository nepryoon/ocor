"""Direct TerminusDB client adapter for the C3 canonical commit slice.

OCOR-DEV-REM-0041 (PO OCOR-DEV-0060-BA-SELECTED-COMPONENTS, change set d): TerminusDB
is the canonical ``VersionedAssertedState`` store of ADD v1.3 Part I §2.2/§2.4. Every
HTTP call to the server is confined to this module (AFF-002/AFF-006,
``OCOR_LANGUAGE_POLICY.md`` row 8); the caller (``ocor_runtime.c3.terminusdb_service``)
only sees plain Python types.

BA-01 technique: one C3 commit is one TerminusDB WOQL transaction that inserts the
aggregate revision, the commit record, the idempotency binding and the immutable outbox
entry, so the server commits all of them in one local commit or none of them. The same
transaction carries its preconditions -- writer epoch, absent idempotency binding,
current aggregate revision -- and TerminusDB re-evaluates the whole query when it
retries a conflicting transaction, so a precondition that no longer holds writes
nothing. (Measured on the pinned server 12.0.7: the ``TerminusDB-Data-Version``
header of the document API is checked only before the server-side retry, so eight
concurrent conditional PUTs on one data version all succeeded; it is therefore never
used as a compare-and-swap here.) A transaction whose preconditions failed is re-read
and re-validated to name the reason, never blindly retried.

Writer fencing (ADD v1.3 §2.2 ``writer_epoch``, §6.2): ``acquire_writer`` advances the
``C3WriterFence`` epoch of the database (the ownership boundary); every write requires
in the same transaction that the stored epoch is still the writer's own, so a stale
writer is rejected and writes nothing. The relay works only on branch ``main``
(§2.5 rule 11): entries copied into a scenario branch by a fork are never read here,
and an acknowledgement is a separate ``C3DeliveryAttempt`` document, the outbox entry
itself stays immutable (§2.2, §2.3).

The adapter never falls back to another store (DEC-201): an unreachable server raises
``TerminusDBUnavailable``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ...kernel.canonical import canonical_bytes, canonical_digest, format_utc_timestamp, parse_i_json, parse_utc_timestamp

MAIN_BRANCH = "main"
FENCE_BOUNDARY = "c3-canonical"
MAX_CONDITIONAL_ATTEMPTS = 64
DATABASE_NAME = re.compile(r"[a-z][a-z0-9_]{2,62}")
RESERVED_DATABASES = frozenset({"ocor_default"})
DOCUMENT_TYPES = ("C3Aggregate", "C3Commit", "C3Idempotency", "C3OutboxEntry", "C3DeliveryAttempt", "C3WriterFence")


def _class(name: str, **fields: str) -> dict[str, Any]:
    return {"@type": "Class", "@id": name, "@key": {"@type": "Lexical", "@fields": ["key"]}, "key": "xsd:string", **fields}


SCHEMA: tuple[dict[str, Any], ...] = (
    {"@type": "@context", "@base": "terminusdb:///data/", "@schema": "terminusdb:///schema#"},
    _class(
        "C3Aggregate",
        tenant_id="xsd:string",
        aggregate_type="xsd:string",
        aggregate_ref="xsd:string",
        revision="xsd:integer",
        state_json="xsd:string",
        state_digest="xsd:string",
        commit_id="xsd:string",
    ),
    _class(
        "C3Commit",
        commit_id="xsd:string",
        command_id="xsd:string",
        command_digest="xsd:string",
        tenant_id="xsd:string",
        aggregate_type="xsd:string",
        aggregate_ref="xsd:string",
        from_revision="xsd:integer",
        to_revision="xsd:integer",
        state_digest="xsd:string",
        idempotency_key="xsd:string",
        decision_ref="xsd:string",
        authority_ref="xsd:string",
        evidence_refs_json="xsd:string",
        governed_context_digest="xsd:string",
        gate_package_digest="xsd:string",
        outbox_event_id="xsd:string",
        outbox_payload_digest="xsd:string",
        branch="xsd:string",
        committed_at="xsd:string",
        writer_epoch="xsd:integer",
    ),
    _class(
        "C3Idempotency",
        tenant_id="xsd:string",
        aggregate_type="xsd:string",
        aggregate_ref="xsd:string",
        idempotency_key="xsd:string",
        command_digest="xsd:string",
        commit_id="xsd:string",
    ),
    _class(
        "C3OutboxEntry",
        event_id="xsd:string",
        commit_id="xsd:string",
        aggregate_ref="xsd:string",
        aggregate_revision="xsd:integer",
        payload_json="xsd:string",
        payload_digest="xsd:string",
        branch="xsd:string",
        occurred_at="xsd:string",
    ),
    _class("C3DeliveryAttempt", event_id="xsd:string", outcome="xsd:string", acknowledged_at="xsd:string", writer_epoch="xsd:integer"),
    _class("C3WriterFence", boundary="xsd:string", writer_epoch="xsd:integer", writer_id="xsd:string"),
)


class TerminusDBCrashStage(StrEnum):
    """Test-only fault injection, mirroring ``adapters.postgres.CrashStage``.

    ``BEFORE_LOCAL_COMMIT`` and ``AFTER_LOCAL_COMMIT`` end the process with
    ``os._exit``; ``REJECTED_BATCH`` adds a document the server's schema check refuses
    to the same request, to prove the multi-document commit is all-or-nothing."""

    BEFORE_LOCAL_COMMIT = "BEFORE_LOCAL_COMMIT"
    AFTER_LOCAL_COMMIT = "AFTER_LOCAL_COMMIT"
    REJECTED_BATCH = "REJECTED_BATCH"


class TerminusDBAdapterError(RuntimeError):
    """Stable, bounded adapter failure; the caller translates contract reason codes
    into the sealed ``C3Error``."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


class TerminusDBUnavailable(TerminusDBAdapterError):
    """The server could not be reached or did not answer: the outcome of a write in
    flight is unknown and is resolved by retrying with the same idempotency key."""

    def __init__(self, message: str) -> None:
        super().__init__("BACKEND_UNAVAILABLE", message)


@dataclass(frozen=True, slots=True)
class CommitOutcome:
    commit_id: str
    from_revision: int
    to_revision: int
    state_digest: str
    outbox_event_id: str
    outbox_payload_digest: str
    committed_at: datetime
    replayed: bool


@dataclass(frozen=True, slots=True)
class SnapshotRow:
    revision: int
    state: dict[str, Any]
    state_digest: str
    commit_id: str


@dataclass(frozen=True, slots=True)
class OutboxRow:
    event_id: str
    commit_id: str
    aggregate_ref: str
    aggregate_revision: int
    payload: dict[str, Any]
    payload_digest: str
    branch: str
    occurred_at: datetime


def _key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return canonical_bytes(value).decode("utf-8")


def _outbox_payload(commit_id: str, aggregate_ref: str, to_revision: int, state_digest: str) -> dict[str, Any]:
    return {"commit_id": commit_id, "aggregate_ref": aggregate_ref, "to_revision": to_revision, "state_digest": state_digest}


def _outbox_document(commit: Mapping[str, Any]) -> dict[str, Any]:
    payload = _outbox_payload(commit["commit_id"], commit["aggregate_ref"], int(commit["to_revision"]), commit["state_digest"])
    return {
        "@type": "C3OutboxEntry",
        "key": _key(commit["outbox_event_id"]),
        "event_id": commit["outbox_event_id"],
        "commit_id": commit["commit_id"],
        "aggregate_ref": commit["aggregate_ref"],
        "aggregate_revision": int(commit["to_revision"]),
        "payload_json": _canonical_json(payload),
        "payload_digest": commit["outbox_payload_digest"],
        "branch": commit["branch"],
        "occurred_at": commit["committed_at"],
    }


def _idempotency_document(commit: Mapping[str, Any]) -> dict[str, Any]:
    scope = (commit["tenant_id"], commit["aggregate_type"], commit["aggregate_ref"], commit["idempotency_key"])
    return {
        "@type": "C3Idempotency",
        "key": _key(*scope),
        "tenant_id": scope[0],
        "aggregate_type": scope[1],
        "aggregate_ref": scope[2],
        "idempotency_key": scope[3],
        "command_digest": commit["command_digest"],
        "commit_id": commit["commit_id"],
    }


def _outcome(commit: Mapping[str, Any], *, replayed: bool) -> CommitOutcome:
    return CommitOutcome(
        commit_id=commit["commit_id"],
        from_revision=int(commit["from_revision"]),
        to_revision=int(commit["to_revision"]),
        state_digest=commit["state_digest"],
        outbox_event_id=commit["outbox_event_id"],
        outbox_payload_digest=commit["outbox_payload_digest"],
        committed_at=parse_utc_timestamp(commit["committed_at"]),
        replayed=replayed,
    )


def _typed(value: object) -> dict[str, Any]:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TerminusDBAdapterError("COMMIT_CONTRACT_INVALID", f"unsupported stored value {value!r}")
    data_type = "xsd:integer" if isinstance(value, int) else "xsd:string"
    return {"@type": "Value", "data": {"@type": data_type, "@value": value}}


def _template(document: Mapping[str, Any]) -> dict[str, Any]:
    fields = [
        {"@type": "FieldValuePair", "field": name, "value": {"@type": "Value", "data": value} if name == "@type" else _typed(value)}
        for name, value in document.items()
        if name != "@id"
    ]
    return {"@type": "Value", "dictionary": {"@type": "DictionaryTemplate", "data": fields}}


def _insert(document: Mapping[str, Any]) -> dict[str, Any]:
    return {"@type": "InsertDocument", "document": _template(document)}


def _update(document: Mapping[str, Any]) -> dict[str, Any]:
    return {"@type": "UpdateDocument", "document": _template(document)}


def _node(doc_type: str, key: str) -> dict[str, Any]:
    return {"@type": "NodeValue", "node": f"{doc_type}/{key}"}


def _holds(doc_type: str, key: str, field: str, value: object) -> dict[str, Any]:
    return {"@type": "Triple", "subject": _node(doc_type, key), "predicate": {"@type": "NodeValue", "node": field}, "object": _typed(value)}


def _absent(doc_type: str, key: str) -> dict[str, Any]:
    present = {"@type": "Triple", "subject": _node(doc_type, key), "predicate": {"@type": "NodeValue", "node": "key"}, "object": {"@type": "Value", "variable": "Present"}}
    return {"@type": "Not", "query": present}


class TerminusDBC3Adapter:
    """The only module of C3 that talks to TerminusDB."""

    def __init__(
        self,
        *,
        url: str,
        password: str,
        database: str,
        user: str = "admin",
        organization: str = "admin",
        writer_id: str = "c3-canonical-writer",
        timeout: float = 30.0,
    ) -> None:
        if not url or urllib.parse.urlsplit(url).scheme not in {"http", "https"}:
            raise ValueError("a TerminusDB http(s) URL is required")
        if not password:
            raise ValueError("a TerminusDB password is required")
        if not isinstance(database, str) or DATABASE_NAME.fullmatch(database) is None:
            raise ValueError("database must match [a-z][a-z0-9_]{2,62}")
        if database in RESERVED_DATABASES:
            raise ValueError(f"database {database!r} is reserved for the bootstrap fixtures")
        self._url = url.rstrip("/")
        self._auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self._database = database
        self._organization = organization
        self._writer_id = writer_id
        self._timeout = timeout
        self._epoch: int | None = None

    # --- transport ---------------------------------------------------------------

    def _request(
        self, method: str, path: str, *, body: object | None = None
    ) -> tuple[int, Any, str]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self._url + path, data=data, method=method)
        request.add_header("Authorization", self._auth)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                status, text = response.status, response.read().decode("utf-8")
                version = response.headers.get("TerminusDB-Data-Version", "")
        except urllib.error.HTTPError as error:
            status, text, version = error.code, error.read().decode("utf-8"), ""
        except (urllib.error.URLError, OSError) as error:
            raise TerminusDBUnavailable(f"{method} {path}: {error}") from error
        return status, self._parse(text), version

    @staticmethod
    def _parse(text: str) -> Any:
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # TerminusDB answers some not-found GETs with a status line before the JSON
            # body (see deploy/bootstrap/fixtures/load_fixtures.py); keep the JSON part.
            start = text.find("{")
            return json.loads(text[start:]) if start >= 0 else {"raw": text}

    def _branch_path(self) -> str:
        return f"/api/document/{self._organization}/{self._database}/local/branch/{MAIN_BRANCH}"

    def _commit_path(self, data_version: str) -> str:
        """The read path pinned to the commit named by a branch data version, so every
        read of one snapshot sees exactly the state the conditional write is checked
        against (a not-found answer carries no data version of its own)."""
        prefix, _, commit = data_version.partition(":")
        if prefix != "branch" or not commit:
            raise TerminusDBAdapterError("BACKEND_ERROR", f"unexpected data version {data_version!r}")
        return f"/api/document/{self._organization}/{self._database}/local/commit/{commit}"

    def _data_version(self) -> str:
        status, body, version = self._request("GET", f"{self._branch_path()}?type=C3WriterFence&as_list=true")
        if status != 200 or not version:
            raise TerminusDBAdapterError("BACKEND_ERROR", f"no branch data version: {status} {body}")
        return version

    def _get_document(self, doc_type: str, key: str, data_version: str | None = None) -> dict[str, Any] | None:
        version = data_version if data_version is not None else self._data_version()
        doc_id = urllib.parse.quote(f"{doc_type}/{key}", safe="")
        status, body, _ = self._request("GET", f"{self._commit_path(version)}?id={doc_id}")
        if status == 404 or (isinstance(body, dict) and body.get("api:status") == "api:not_found"):
            return None
        if status != 200 or not isinstance(body, dict):
            raise TerminusDBAdapterError("BACKEND_ERROR", f"GET {doc_type}: {status} {body}")
        return body

    def _list(self, doc_type: str, data_version: str) -> list[dict[str, Any]]:
        status, body, _ = self._request("GET", f"{self._commit_path(data_version)}?type={doc_type}&as_list=true")
        if status != 200 or not isinstance(body, list):
            raise TerminusDBAdapterError("BACKEND_ERROR", f"list {doc_type}: {status} {body}")
        return body

    def _snapshot(self, *refs: tuple[str, str]) -> tuple[list[dict[str, Any] | None], str]:
        """Reads several documents at one branch data version."""
        version = self._data_version()
        return [self._get_document(doc_type, key, version) for doc_type, key in refs], version

    def _transact(self, conditions: Sequence[Mapping[str, Any]], writes: Sequence[Mapping[str, Any]], message: str) -> bool:
        """Runs one WOQL transaction on ``main``: the writes happen only if every
        condition holds at commit time and no inserted identity already exists.
        Returns ``False`` when a precondition failed; nothing was written then."""
        query = {"@type": "And", "and": [*conditions, *writes]}
        status, body, _ = self._request(
            "POST",
            f"/api/woql/{self._organization}/{self._database}/local/branch/{MAIN_BRANCH}",
            body={"query": query, "commit_info": {"author": self._writer_id, "message": message}},
        )
        error = body.get("api:error", {}) if isinstance(body, dict) else {}
        if status == 200 and isinstance(body, dict) and isinstance(body.get("bindings"), list):
            return bool(body["bindings"])
        if isinstance(error, dict) and error.get("@type") == "api:DocumentIdAlreadyExists":
            # A concurrent transaction inserted the same identity first; the server
            # refused this whole transaction, which is a failed precondition.
            return False
        if isinstance(error, dict) and error.get("@type") == "api:WOQLSchemaCheckFailure":
            raise TerminusDBAdapterError("BATCH_REJECTED", f"the server refused the whole transaction: {body}")
        raise TerminusDBAdapterError("BACKEND_ERROR", f"WOQL transaction: {status} {body}")

    # --- lifecycle -----------------------------------------------------------------

    def initialize(self) -> None:
        """Creates the database and its schema if absent; existing canonical state is
        kept. A schema that differs from ``SCHEMA`` fails closed."""
        status, body, _ = self._request("GET", "/api/db")
        if status != 200 or not isinstance(body, list):
            raise TerminusDBAdapterError("BACKEND_ERROR", f"cannot list databases: {status} {body}")
        existing = {entry.get("path", "").split("/")[-1] for entry in body}
        if self._database not in existing:
            status, body, _ = self._request(
                "POST",
                f"/api/db/{self._organization}/{self._database}",
                body={"label": self._database, "comment": "OCOR C3 VersionedAssertedState", "schema": True},
            )
            if status != 200:
                raise TerminusDBAdapterError("BACKEND_ERROR", f"cannot create {self._database}: {status} {body}")
        schema_path = f"/api/document/{self._organization}/{self._database}?graph_type=schema&as_list=true"
        status, body, _ = self._request("GET", schema_path)
        if status != 200 or not isinstance(body, list):
            raise TerminusDBAdapterError("BACKEND_ERROR", f"cannot read the schema: {status} {body}")
        present = {item["@id"]: item for item in body if isinstance(item, dict) and "@id" in item}
        expected = {item["@id"]: item for item in SCHEMA if "@id" in item}
        if not present:
            query = urllib.parse.urlencode(
                {"graph_type": "schema", "author": self._writer_id, "message": "C3 schema", "full_replace": "true"}
            )
            status, body, _ = self._request(
                "POST", f"/api/document/{self._organization}/{self._database}?{query}", body=list(SCHEMA)
            )
            if status != 200:
                raise TerminusDBAdapterError("BACKEND_ERROR", f"cannot write the schema: {status} {body}")
        elif present != expected:
            divergent = sorted(name for name in set(present) | set(expected) if present.get(name) != expected.get(name))
            raise TerminusDBAdapterError("SCHEMA_MISMATCH", f"C3 class definitions differ from SCHEMA: {divergent}")

    def drop(self) -> None:
        status, body, _ = self._request("DELETE", f"/api/db/{self._organization}/{self._database}")
        if status not in (200, 404):
            raise TerminusDBAdapterError("BACKEND_ERROR", f"cannot delete {self._database}: {status} {body}")

    @property
    def writer_epoch(self) -> int | None:
        return self._epoch

    def acquire_writer(self) -> int:
        """Advances the fence of the ownership boundary and becomes its only writer."""
        key = _key(FENCE_BOUNDARY)
        for _ in range(MAX_CONDITIONAL_ATTEMPTS):
            (fence,), version = self._snapshot(("C3WriterFence", key))
            epoch = (int(fence["writer_epoch"]) if fence is not None else 0) + 1
            document = {"@type": "C3WriterFence", "key": key, "boundary": FENCE_BOUNDARY, "writer_epoch": epoch, "writer_id": self._writer_id}
            if fence is None:
                applied = self._transact([_absent("C3WriterFence", key)], [_insert(document)], f"C3 writer epoch {epoch}")
            else:
                applied = self._transact(
                    [_holds("C3WriterFence", key, "writer_epoch", epoch - 1)], [_update(document)], f"C3 writer epoch {epoch}"
                )
            if not applied:
                continue
            self._epoch = epoch
            return epoch
        raise TerminusDBAdapterError("WRITE_CONTENTION", "writer epoch not acquired within the attempt budget")

    def _check_fence(self, fence: Mapping[str, Any] | None) -> int:
        if self._epoch is None:
            raise TerminusDBAdapterError("SINGLE_WRITER_VIOLATION", "the writer has not acquired an epoch")
        stored = int(fence["writer_epoch"]) if fence is not None else 0
        if stored != self._epoch:
            raise TerminusDBAdapterError(
                "SINGLE_WRITER_VIOLATION", f"stale writer epoch {self._epoch}, boundary epoch is {stored}"
            )
        return self._epoch

    @staticmethod
    def _crash(selected: TerminusDBCrashStage | None, target: TerminusDBCrashStage) -> None:
        if selected is target:
            os._exit(86)

    # --- commit ----------------------------------------------------------------------

    def commit_transaction(
        self,
        *,
        tenant_id: str,
        aggregate_type: str,
        aggregate_ref: str,
        idempotency_key: str,
        command_id: str,
        command_digest: str,
        expected_revision: int,
        canonical_delta: Mapping[str, Any],
        decision_ref: str,
        authority_ref: str,
        evidence_refs: Sequence[str],
        governed_context_digest: str,
        gate_package_digest: str,
        branch: str,
        crash_after: TerminusDBCrashStage | None = None,
    ) -> CommitOutcome:
        if branch != MAIN_BRANCH:
            raise TerminusDBAdapterError("SINGLE_WRITER_VIOLATION", "canonical commits use main only")
        if self._epoch is None:
            raise TerminusDBAdapterError("SINGLE_WRITER_VIOLATION", "the writer has not acquired an epoch")
        aggregate_key = _key(tenant_id, aggregate_type, aggregate_ref)
        idempotency_doc_key = _key(tenant_id, aggregate_type, aggregate_ref, idempotency_key)
        for _ in range(MAX_CONDITIONAL_ATTEMPTS):
            (fence, binding, aggregate), version = self._snapshot(
                ("C3WriterFence", _key(FENCE_BOUNDARY)),
                ("C3Idempotency", idempotency_doc_key),
                ("C3Aggregate", aggregate_key),
            )
            epoch = self._check_fence(fence)
            if binding is not None:
                if binding["command_digest"] != command_digest:
                    raise TerminusDBAdapterError(
                        "IDEMPOTENCY_CONFLICT", "idempotency key or scope was rebound to different command content"
                    )
                commit = self._get_document("C3Commit", _key(binding["commit_id"]), version)
                if commit is None:
                    raise TerminusDBAdapterError("COMMIT_RECEIPT_MISMATCH", "idempotency binding without commit record")
                return _outcome(commit, replayed=True)

            revision = int(aggregate["revision"]) if aggregate is not None else 0
            if expected_revision != revision:
                raise TerminusDBAdapterError(
                    "REVISION_CONFLICT", f"expected revision {expected_revision}, found {revision}"
                )
            state = parse_i_json(aggregate["state_json"]) if aggregate is not None else {}
            new_state = {**state, **dict(canonical_delta)}
            new_state_digest = canonical_digest(new_state)
            to_revision = revision + 1
            commit_id = "urn:ocor:commit:sha256:" + hashlib.sha256(f"{command_digest}:{to_revision}".encode()).hexdigest()
            outbox_event_id = "urn:ocor:event:sha256:" + hashlib.sha256(f"{commit_id}:outbox".encode()).hexdigest()
            outbox_payload_digest = canonical_digest(
                _outbox_payload(commit_id, aggregate_ref, to_revision, new_state_digest)
            )
            commit = {
                "@type": "C3Commit",
                "key": _key(commit_id),
                "commit_id": commit_id,
                "command_id": command_id,
                "command_digest": command_digest,
                "tenant_id": tenant_id,
                "aggregate_type": aggregate_type,
                "aggregate_ref": aggregate_ref,
                "from_revision": revision,
                "to_revision": to_revision,
                "state_digest": new_state_digest,
                "idempotency_key": idempotency_key,
                "decision_ref": decision_ref,
                "authority_ref": authority_ref,
                "evidence_refs_json": _canonical_json(list(evidence_refs)),
                "governed_context_digest": governed_context_digest,
                "gate_package_digest": gate_package_digest,
                "outbox_event_id": outbox_event_id,
                "outbox_payload_digest": outbox_payload_digest,
                "branch": branch,
                "committed_at": format_utc_timestamp(datetime.now(UTC)),
                "writer_epoch": epoch,
            }
            aggregate_document = {
                    "@type": "C3Aggregate",
                    "key": aggregate_key,
                    "tenant_id": tenant_id,
                    "aggregate_type": aggregate_type,
                    "aggregate_ref": aggregate_ref,
                    "revision": to_revision,
                    "state_json": _canonical_json(new_state),
                    "state_digest": new_state_digest,
                    "commit_id": commit_id,
            }
            conditions = [
                _holds("C3WriterFence", _key(FENCE_BOUNDARY), "writer_epoch", epoch),
                _absent("C3Idempotency", idempotency_doc_key),
                _absent("C3Aggregate", aggregate_key) if aggregate is None else _holds("C3Aggregate", aggregate_key, "revision", revision),
            ]
            writes = [
                _insert(aggregate_document) if aggregate is None else _update(aggregate_document),
                _insert(commit),
                _insert(_idempotency_document(commit)),
                _insert(_outbox_document(commit)),
            ]
            if crash_after is TerminusDBCrashStage.REJECTED_BATCH:
                writes.append(_insert({**_outbox_document(commit), "key": _key(commit_id, "rejected"), "aggregate_revision": "not-an-integer"}))
            self._crash(crash_after, TerminusDBCrashStage.BEFORE_LOCAL_COMMIT)
            if not self._transact(conditions, writes, f"C3 commit {commit_id}"):
                continue
            self._crash(crash_after, TerminusDBCrashStage.AFTER_LOCAL_COMMIT)
            return _outcome(commit, replayed=False)
        raise TerminusDBAdapterError("WRITE_CONTENTION", "commit not applied within the attempt budget")

    # --- reads -------------------------------------------------------------------------

    def read_snapshot(self, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> SnapshotRow | None:
        document = self._get_document("C3Aggregate", _key(tenant_id, aggregate_type, aggregate_ref))
        if document is None:
            return None
        return SnapshotRow(
            revision=int(document["revision"]),
            state=dict(parse_i_json(document["state_json"])),
            state_digest=document["state_digest"],
            commit_id=document["commit_id"],
        )

    def current_revision(self, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> int:
        row = self.read_snapshot(tenant_id, aggregate_type, aggregate_ref)
        return row.revision if row is not None else 0

    # --- relay -------------------------------------------------------------------------

    def claim_outbox_batch(self, *, limit: int) -> tuple[OutboxRow, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise TerminusDBAdapterError("COMMIT_CONTRACT_INVALID", "limit must be a positive integer")
        version = self._data_version()
        entries = self._list("C3OutboxEntry", version)
        attempts = self._list("C3DeliveryAttempt", version)
        delivered = {attempt["event_id"] for attempt in attempts}
        pending = sorted(
            (entry for entry in entries if entry["branch"] == MAIN_BRANCH and entry["event_id"] not in delivered),
            key=lambda entry: (entry["occurred_at"], entry["event_id"]),
        )
        return tuple(
            OutboxRow(
                event_id=entry["event_id"],
                commit_id=entry["commit_id"],
                aggregate_ref=entry["aggregate_ref"],
                aggregate_revision=int(entry["aggregate_revision"]),
                payload=dict(parse_i_json(entry["payload_json"])),
                payload_digest=entry["payload_digest"],
                branch=entry["branch"],
                occurred_at=parse_utc_timestamp(entry["occurred_at"]),
            )
            for entry in pending[:limit]
        )

    def acknowledge_outbox(self, event_id: str, *, acknowledged_at: datetime) -> None:
        recorded_at = format_utc_timestamp(acknowledged_at)
        for _ in range(MAX_CONDITIONAL_ATTEMPTS):
            (fence, entry, attempt), version = self._snapshot(
                ("C3WriterFence", _key(FENCE_BOUNDARY)),
                ("C3OutboxEntry", _key(event_id)),
                ("C3DeliveryAttempt", _key(event_id)),
            )
            epoch = self._check_fence(fence)
            if entry is None or entry["branch"] != MAIN_BRANCH:
                raise TerminusDBAdapterError("OUTBOX_ENTRY_NOT_FOUND", f"no main outbox entry {event_id!r}")
            if attempt is not None:
                return
            document = {
                "@type": "C3DeliveryAttempt",
                "key": _key(event_id),
                "event_id": event_id,
                "outcome": "ACKNOWLEDGED",
                "acknowledged_at": recorded_at,
                "writer_epoch": epoch,
            }
            conditions = [
                _holds("C3WriterFence", _key(FENCE_BOUNDARY), "writer_epoch", epoch),
                _holds("C3OutboxEntry", _key(event_id), "branch", MAIN_BRANCH),
                _absent("C3DeliveryAttempt", _key(event_id)),
            ]
            if self._transact(conditions, [_insert(document)], f"C3 delivery {event_id}"):
                return
        raise TerminusDBAdapterError("WRITE_CONTENTION", "acknowledgement not applied within the attempt budget")

    def reconcile(self, *, limit: int) -> int:
        """Defense-in-depth repair, as in the PostgreSQL adapter: every commit record
        must have its idempotency binding and its outbox entry. Under normal operation
        this always holds because the four documents are one TerminusDB commit; a
        missing one (a simulated corruption) is re-derived from the commit record's
        own fields, never fabricated. Only branch ``main`` is reconciled."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise TerminusDBAdapterError("COMMIT_CONTRACT_INVALID", "limit must be a positive integer")
        for _ in range(MAX_CONDITIONAL_ATTEMPTS):
            (fence,), version = self._snapshot(("C3WriterFence", _key(FENCE_BOUNDARY)))
            epoch = self._check_fence(fence)
            commits = self._list("C3Commit", version)
            bindings = self._list("C3Idempotency", version)
            entries = self._list("C3OutboxEntry", version)
            bound = {binding["commit_id"] for binding in bindings}
            relayable = {entry["commit_id"] for entry in entries if entry["branch"] == MAIN_BRANCH}
            repairs: list[dict[str, Any]] = []
            for commit in sorted(commits, key=lambda item: item["commit_id"]):
                if commit["branch"] != MAIN_BRANCH:
                    continue
                if commit["commit_id"] not in bound and len(repairs) < limit:
                    repairs.append(_idempotency_document(commit))
                if commit["commit_id"] not in relayable and len(repairs) < limit:
                    repairs.append(_outbox_document(commit))
            if not repairs:
                return 0
            conditions = [_holds("C3WriterFence", _key(FENCE_BOUNDARY), "writer_epoch", epoch)]
            conditions += [_absent(repair["@type"], repair["key"]) for repair in repairs]
            if self._transact(conditions, [_insert(repair) for repair in repairs], "C3 reconcile"):
                return len(repairs)
        raise TerminusDBAdapterError("WRITE_CONTENTION", "reconciliation not applied within the attempt budget")
