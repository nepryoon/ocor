"""PostgreSQL persistence of the Function & Model Registry (``RegistryStore`` port).

The only module of the registry that imports ``psycopg`` (AFF-002/AFF-006). All tables
of the registry schema are append-only: a trigger rejects every ``UPDATE`` and
``DELETE``. Entries form a hash chain (``registry_commit``), audit records form a
second hash chain (``audit_ref``), artefacts are content-addressed and re-hashed on
every read, and invocation lineage (FR-060) is stored with the exact request and
result. Commits of each chain are serialised with a transaction-scoped advisory lock.
An unreachable server is ``CONTROL_PLANE_UNAVAILABLE``: the registry never falls back.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ...kernel.canonical import canonical_digest
from ..contract import RegistryError, json_mapping

SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]{0,40}")
T = TypeVar("T")

_DDL = """
CREATE SCHEMA IF NOT EXISTS {s};
CREATE TABLE IF NOT EXISTS {s}.registry_artifact (
  digest TEXT PRIMARY KEY, content BYTEA NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS {s}.registry_entry (
  seq BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL, entry_key TEXT NOT NULL, resource_id TEXT NOT NULL,
  semantic_version TEXT NOT NULL, record JSONB NOT NULL, descriptor_digest TEXT NOT NULL,
  previous_commit TEXT NOT NULL, registry_commit TEXT NOT NULL UNIQUE, audit_ref TEXT NOT NULL,
  accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (kind, entry_key));
CREATE TABLE IF NOT EXISTS {s}.registry_revocation (
  digest TEXT PRIMARY KEY, reason TEXT NOT NULL, change_proposal_ref TEXT NOT NULL, audit_ref TEXT NOT NULL,
  revoked_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS {s}.registry_invocation (
  invocation_id TEXT PRIMARY KEY, kind TEXT NOT NULL, entry_key TEXT NOT NULL, idempotency_key TEXT,
  request_digest TEXT NOT NULL, record JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (kind, entry_key, idempotency_key));
CREATE TABLE IF NOT EXISTS {s}.registry_audit (
  seq BIGSERIAL PRIMARY KEY, event TEXT NOT NULL, detail JSONB NOT NULL, previous_hash TEXT NOT NULL,
  audit_hash TEXT NOT NULL UNIQUE, recorded_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE OR REPLACE FUNCTION {s}.registry_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'registry tables are append-only'; END $$;
"""
_TABLES = ("registry_artifact", "registry_entry", "registry_revocation", "registry_invocation", "registry_audit")
_GENESIS = "urn:sha256:" + "0" * 64


def _unavailable(exc: Exception) -> RegistryError:
    return RegistryError("CONTROL_PLANE_UNAVAILABLE", f"registry store unavailable: {type(exc).__name__}")


class PostgresRegistryStore:
    """``RegistryStore`` on PostgreSQL; ``schema`` isolates one registry instance."""

    def __init__(self, dsn: str, *, schema: str = "ocor_registry", connect_timeout: int = 5) -> None:
        if not isinstance(dsn, str) or not dsn:
            raise ValueError("a PostgreSQL DSN is required")
        if SCHEMA_NAME.fullmatch(schema) is None:
            raise ValueError("invalid registry schema name")
        self._dsn = dsn
        self._schema = schema
        self._timeout = connect_timeout

    def __repr__(self) -> str:
        return f"PostgresRegistryStore(schema={self._schema!r})"

    @property
    def schema(self) -> str:
        return self._schema

    def _run(self, work: Callable[[psycopg.Connection[dict[str, Any]]], T]) -> T:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=self._timeout) as connection:
                with connection.transaction():
                    return work(connection)
        except psycopg.OperationalError as exc:
            raise _unavailable(exc) from exc

    def _t(self, table: str) -> str:
        return f"{self._schema}.{table}"

    def initialize(self) -> None:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> None:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("ocor-registry-ddl",))
            connection.execute(_DDL.format(s=self._schema))
            for table in _TABLES:
                trigger = f"{table}_append_only"
                exists = connection.execute(
                    "SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s AND t.tgname = %s",
                    (self._schema, trigger)).fetchone()
                if exists is None:
                    connection.execute(
                        f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {self._t(table)} "
                        f"FOR EACH ROW EXECUTE FUNCTION {self._schema}.registry_append_only()")

        self._run(work)

    def drop(self) -> None:
        """Remove a disposable registry schema (qualification tooling only)."""
        self._run(lambda connection: connection.execute(f"DROP SCHEMA IF EXISTS {self._schema} CASCADE"))

    # -- artefacts --------------------------------------------------------------------
    def put_artifact(self, content: bytes) -> str:
        if not isinstance(content, bytes):
            raise RegistryError("SCHEMA_VIOLATION", "artefact content must be bytes")
        digest = "urn:sha256:" + hashlib.sha256(content).hexdigest()
        self._run(lambda connection: connection.execute(
            f"INSERT INTO {self._t('registry_artifact')} (digest, content) VALUES (%s, %s) "
            "ON CONFLICT (digest) DO NOTHING", (digest, content)))
        return digest

    def get_artifact(self, digest: str) -> bytes:
        row = self._run(lambda connection: connection.execute(
            f"SELECT content FROM {self._t('registry_artifact')} WHERE digest = %s", (digest,)).fetchone())
        if row is None:
            raise RegistryError("CONTRACT_REJECTED", f"artefact {digest} is not in the registry store")
        content = bytes(row["content"])
        if "urn:sha256:" + hashlib.sha256(content).hexdigest() != digest:
            raise RegistryError("CONTRACT_REJECTED", f"stored artefact {digest} does not match its digest")
        return content

    # -- audit ------------------------------------------------------------------------
    def _audit(self, connection: psycopg.Connection[dict[str, Any]], event: str, detail: Mapping[str, Any]) -> str:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self._schema + "/audit",))
        row = connection.execute(
            f"SELECT audit_hash FROM {self._t('registry_audit')} ORDER BY seq DESC LIMIT 1").fetchone()
        previous = row["audit_hash"] if row else _GENESIS
        body = json_mapping(detail)
        audit_hash = canonical_digest({"previous_hash": previous, "event": event, "detail": body})
        connection.execute(
            f"INSERT INTO {self._t('registry_audit')} (event, detail, previous_hash, audit_hash) "
            "VALUES (%s, %s, %s, %s)", (event, Jsonb(body), previous, audit_hash))
        return audit_hash

    def append_audit(self, event: str, detail: Mapping[str, Any]) -> str:
        return self._run(lambda connection: self._audit(connection, event, detail))

    def audit_chain(self) -> list[dict[str, Any]]:
        return self._run(lambda connection: connection.execute(
            f"SELECT event, detail, previous_hash, audit_hash FROM {self._t('registry_audit')} ORDER BY seq"
        ).fetchall())

    # -- entries ----------------------------------------------------------------------
    def append_entry(self, *, kind: str, entry_key: str, resource_id: str, semantic_version: str,
                     record: Mapping[str, Any], descriptor_digest: str,
                     audit_detail: Mapping[str, Any]) -> dict[str, Any]:
        """Append an entry once; an identical entry returns the stored row unchanged."""

        def work(connection: psycopg.Connection[dict[str, Any]]) -> dict[str, Any]:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self._schema + "/entry",))
            existing = connection.execute(
                f"SELECT * FROM {self._t('registry_entry')} WHERE kind = %s AND entry_key = %s",
                (kind, entry_key)).fetchone()
            if existing is not None:
                if existing["descriptor_digest"] != descriptor_digest:
                    raise RegistryError("IDEMPOTENCY_CONFLICT", "a published pin is immutable")
                return dict(existing)
            row = connection.execute(
                f"SELECT registry_commit FROM {self._t('registry_entry')} ORDER BY seq DESC LIMIT 1").fetchone()
            previous = row["registry_commit"] if row else _GENESIS
            body = json_mapping(record)
            commit = canonical_digest({"previous_commit": previous, "kind": kind, "record": body})
            audit_ref = self._audit(connection, f"{kind}_PUBLISHED", dict(audit_detail) | {"registry_commit": commit})
            inserted = connection.execute(
                f"INSERT INTO {self._t('registry_entry')} (kind, entry_key, resource_id, semantic_version, record, "
                "descriptor_digest, previous_commit, registry_commit, audit_ref) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (kind, entry_key, resource_id, semantic_version, Jsonb(body), descriptor_digest, previous, commit,
                 audit_ref)).fetchone()
            assert inserted is not None
            return dict(inserted)

        return self._run(work)

    def find_entry(self, kind: str, entry_key: str) -> dict[str, Any] | None:
        row = self._run(lambda connection: connection.execute(
            f"SELECT * FROM {self._t('registry_entry')} WHERE kind = %s AND entry_key = %s",
            (kind, entry_key)).fetchone())
        return dict(row) if row else None

    def has_version(self, kind: str, resource_id: str, semantic_version: str) -> bool:
        row = self._run(lambda connection: connection.execute(
            f"SELECT 1 FROM {self._t('registry_entry')} WHERE kind = %s AND resource_id = %s "
            "AND semantic_version = %s LIMIT 1", (kind, resource_id, semantic_version)).fetchone())
        return row is not None

    def entry_chain(self) -> list[dict[str, Any]]:
        return self._run(lambda connection: connection.execute(
            f"SELECT kind, record, previous_commit, registry_commit FROM {self._t('registry_entry')} ORDER BY seq"
        ).fetchall())

    # -- revocation -------------------------------------------------------------------
    def revoke(self, digest: str, *, reason: str, change_proposal_ref: str) -> str:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> str:
            existing = connection.execute(
                f"SELECT audit_ref FROM {self._t('registry_revocation')} WHERE digest = %s", (digest,)).fetchone()
            if existing is not None:
                return str(existing["audit_ref"])
            audit_ref = self._audit(connection, "ARTIFACT_REVOKED", {
                "digest": digest, "reason": reason, "change_proposal_ref": change_proposal_ref})
            connection.execute(
                f"INSERT INTO {self._t('registry_revocation')} (digest, reason, change_proposal_ref, audit_ref) "
                "VALUES (%s, %s, %s, %s)", (digest, reason, change_proposal_ref, audit_ref))
            return audit_ref

        return self._run(work)

    def revoked(self, digests: Iterable[str]) -> frozenset[str]:
        wanted = sorted(set(digests))
        rows = self._run(lambda connection: connection.execute(
            f"SELECT digest FROM {self._t('registry_revocation')} WHERE digest = ANY(%s)", (wanted,)).fetchall())
        return frozenset(str(row["digest"]) for row in rows)

    # -- invocations ------------------------------------------------------------------
    def record_invocation(self, *, invocation_id: str, kind: str, entry_key: str, idempotency_key: str | None,
                          request_digest: str, record: Mapping[str, Any]) -> dict[str, Any]:
        """Store the lineage of an invocation; a replayed idempotency key returns the first one."""

        def work(connection: psycopg.Connection[dict[str, Any]]) -> dict[str, Any]:
            if idempotency_key is not None:
                existing = connection.execute(
                    f"SELECT * FROM {self._t('registry_invocation')} WHERE kind = %s AND entry_key = %s "
                    "AND idempotency_key = %s", (kind, entry_key, idempotency_key)).fetchone()
                if existing is not None:
                    return dict(existing)
            inserted = connection.execute(
                f"INSERT INTO {self._t('registry_invocation')} (invocation_id, kind, entry_key, idempotency_key, "
                "request_digest, record) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (kind, entry_key, idempotency_key) DO NOTHING RETURNING *",
                (invocation_id, kind, entry_key, idempotency_key, request_digest, Jsonb(json_mapping(record)))
            ).fetchone()
            if inserted is None:
                raced = connection.execute(
                    f"SELECT * FROM {self._t('registry_invocation')} WHERE kind = %s AND entry_key = %s "
                    "AND idempotency_key = %s", (kind, entry_key, idempotency_key)).fetchone()
                assert raced is not None
                return dict(raced)
            return dict(inserted)

        return self._run(work)

    def find_invocation_by_key(self, kind: str, entry_key: str, idempotency_key: str) -> dict[str, Any] | None:
        row = self._run(lambda connection: connection.execute(
            f"SELECT * FROM {self._t('registry_invocation')} WHERE kind = %s AND entry_key = %s "
            "AND idempotency_key = %s", (kind, entry_key, idempotency_key)).fetchone())
        return dict(row) if row else None

    def get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        row = self._run(lambda connection: connection.execute(
            f"SELECT * FROM {self._t('registry_invocation')} WHERE invocation_id = %s", (invocation_id,)).fetchone())
        return dict(row) if row else None

    def now(self) -> datetime:
        row = self._run(lambda connection: connection.execute("SELECT now() AS at").fetchone())
        assert row is not None
        value: datetime = row["at"]
        return value
