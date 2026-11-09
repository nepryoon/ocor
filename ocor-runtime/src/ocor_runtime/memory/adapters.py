"""Real adapters of the governed memory stores (OCOR-DEV-0051, NCP-U11).

PostgreSQL holds the metadata store, the encrypted content objects and the
full-text index (one schema per deployment); Qdrant holds the vector index
(one collection per partition and vector representation version); OpenBao
transit seals the content with a key derived from each content address.  The
adapters implement the ports of :mod:`ocor_runtime.memory.stores` (LLD v1.1
§§2.8.1-2.8.4); backend identifiers never cross those ports.

They moved here from ``tests/tasks/test_ocor_dev_0051.py`` with unchanged
behaviour (NORMATIVE-CONFORMANCE-PLAN point 2, ADD v1.3 Part II §2.2).  The
lifecycle of the backends (containers, credentials, disposable schemas) stays
in the qualification tooling, outside the product path.
"""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import psycopg

from ..kernel.canonical import canonical_bytes
from .model import memory_version_ref
from .stores import (
    EligibilityPredicate,
    IndexEntry,
    IndexHit,
    LexicalProfile,
    MemoryPartition,
    RepresentationPointer,
    SealedContent,
    StagedVersion,
    StoredVersion,
    VectorProfile,
    VersionState,
    predecessor_not_committed,
    stage_conflict,
)

__all__ = [
    "OpenBaoTransitCipher",
    "PostgresContentStore",
    "PostgresLexicalIndex",
    "PostgresStores",
    "QdrantVectorIndex",
    "TransitClient",
]


def _http(method: str, url: str, body: Any | None = None, *, headers: Mapping[str, str] | None = None, timeout: float = 5.0) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return exc.code, None


class TransitClient(Protocol):
    """An authenticated OpenBao client: ``call`` returns the decoded JSON body."""

    def call(self, method: str, path: str, body: Any | None = None) -> Any: ...


class OpenBaoTransitCipher:
    """AES-256-GCM96 transit key derived per content address, AAD = canonical context."""

    def __init__(self, bao: TransitClient, key: str = "memory-content") -> None:
        self._bao = bao
        self._key = key

    @staticmethod
    def _params(context: Mapping[str, str]) -> dict[str, str]:
        encoded = canonical_bytes(dict(context))
        return {
            "context": base64.b64encode(hashlib.sha256(encoded).digest()).decode(),
            "associated_data": base64.b64encode(encoded).decode(),
        }

    def seal(self, *, context: Mapping[str, str], plaintext: bytes) -> SealedContent:
        data = self._bao.call(
            "POST",
            f"/v1/ocor-memory-transit/encrypt/{self._key}",
            {"plaintext": base64.b64encode(plaintext).decode(), **self._params(context)},
        )
        return SealedContent(f"urn:ocor:memory-key:transit:{self._key}", data["data"]["ciphertext"].encode())

    def open(self, *, context: Mapping[str, str], sealed: SealedContent) -> bytes:
        data = self._bao.call(
            "POST",
            f"/v1/ocor-memory-transit/decrypt/{self._key}",
            {"ciphertext": sealed.ciphertext.decode(), **self._params(context)},
        )
        return base64.b64decode(data["data"]["plaintext"])



def _attribute_sql(column: str, where: EligibilityPredicate) -> tuple[str, list[Any]]:
    """The eligibility predicate as SQL over an ``index_attributes`` jsonb column."""

    a = column
    clauses = [
        f"({a}->>'superseded') = 'false'", f"({a}->>'deleted') = 'false'", f"{a}->>'lifecycle_status' = 'ACTIVE'",
        f"{a}->>'memory_kind' = ANY(%s)", f"{a}->>'memory_scope' = ANY(%s)",
        f"({a}->>'valid_from_us')::bigint <= %s", f"({a}->>'valid_until_us')::bigint > %s",
        f"({a}->>'expires_at_us')::bigint > %s",
    ]
    params: list[Any] = [sorted(where.memory_kinds), sorted(where.memory_scopes), where.valid_at_us, where.valid_at_us, where.now_us]
    if where.source_kinds is not None:
        clauses.append(f"{a}->>'source_kind' = ANY(%s)")
        params.append(sorted(where.source_kinds))
    if where.content_schema_refs is not None:
        clauses.append(f"{a}->>'content_schema_ref' = ANY(%s)")
        params.append(sorted(where.content_schema_refs))
    if where.min_confidence is not None:
        clauses.append(f"({a}->>'confidence')::float8 >= %s")
        params.append(where.min_confidence)
    if where.exclude_taint_labels:
        clauses.append(f"NOT ({a}->'taint_labels' ?| %s)")
        params.append(sorted(where.exclude_taint_labels))
    if where.excluded_memory_item_ids:
        clauses.append(f"NOT ({a}->>'memory_item_id' = ANY(%s))")
        params.append(sorted(where.excluded_memory_item_ids))
    return " AND ".join(clauses), params


def _item_sql(where: EligibilityPredicate) -> tuple[str, list[Any]]:
    """The eligibility predicate as SQL over the stored item of a metadata version."""

    i = "(v.body::jsonb -> 'item')"
    clauses = [
        f"{i}->>'deletion_epoch' IS NULL", f"{i}->>'lifecycle_status' = 'ACTIVE'",
        f"{i}->>'memory_kind' = ANY(%s)", f"{i}->>'memory_scope' = ANY(%s)",
        f"({i}->>'valid_from')::timestamptz <= %s",
        f"({i}->>'valid_until' IS NULL OR ({i}->>'valid_until')::timestamptz > %s)",
        f"({i}->>'expires_at' IS NULL OR ({i}->>'expires_at')::timestamptz > %s)",
    ]
    params: list[Any] = [sorted(where.memory_kinds), sorted(where.memory_scopes), where.valid_at, where.valid_at, where.now]
    if where.source_kinds is not None:
        clauses.append(f"{i}->>'source_kind' = ANY(%s)")
        params.append(sorted(where.source_kinds))
    if where.content_schema_refs is not None:
        clauses.append(f"{i}->>'content_schema_ref' = ANY(%s)")
        params.append(sorted(where.content_schema_refs))
    if where.min_confidence is not None:
        clauses.append(f"({i}->>'confidence')::float8 >= %s")
        params.append(where.min_confidence)
    if where.exclude_taint_labels:
        clauses.append(f"NOT ({i}->'taint_labels' ?| %s)")
        params.append(sorted(where.exclude_taint_labels))
    if where.excluded_memory_item_ids:
        clauses.append("NOT (v.memory_item_id = ANY(%s))")
        params.append(sorted(where.excluded_memory_item_ids))
    return " AND ".join(clauses), params


def _layout_name(prefix: str, partition_digest: str, representation_version: str) -> str:
    return prefix + hashlib.sha256(f"{partition_digest}|{representation_version}".encode()).hexdigest()[:40]


class PostgresStores:
    """Metadata store, content store and full-text index on one PostgreSQL schema."""

    def __init__(self, dsn: str, schema: str) -> None:
        self.dsn = dsn
        self.schema = schema
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{schema}".partitions (partition_digest text PRIMARY KEY, body text NOT NULL)'
            )
            conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{schema}".versions ('
                "memory_item_id text NOT NULL, memory_version integer NOT NULL, "
                "partition_digest text NOT NULL REFERENCES "
                f'"{schema}".partitions(partition_digest), '
                "stage_digest text NOT NULL, body text NOT NULL, staged_at text NOT NULL, "
                "state text NOT NULL CHECK (state IN ('PENDING','COMMITTED')), committed_at text, "
                "PRIMARY KEY (memory_item_id, memory_version))"
            )
            conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{schema}".pointers (store_ref text PRIMARY KEY, '
                "memory_item_id text NOT NULL, memory_version integer NOT NULL, body text NOT NULL, "
                "state text NOT NULL CHECK (state IN ('PENDING','COMMITTED')), "
                f'FOREIGN KEY (memory_item_id, memory_version) REFERENCES "{schema}".versions)'
            )
            conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{schema}".heads (memory_item_id text PRIMARY KEY, head_version integer NOT NULL)'
            )
            conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{schema}".content (object_ref text PRIMARY KEY, '
                "partition_digest text NOT NULL, key_ref text NOT NULL, ciphertext bytea NOT NULL)"
            )
            conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{schema}".lexical_layouts (table_name text PRIMARY KEY, '
                "partition_digest text NOT NULL, representation_version text NOT NULL, configuration text NOT NULL)"
            )

    def connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.dsn)

    # -- MemoryMetadataStore -------------------------------------------------

    def _row(self, row: tuple[str, str, str, str | None]) -> StoredVersion:
        body, staged_at, state, committed_at = row
        return StoredVersion(StagedVersion.from_body(json.loads(body), staged_at), VersionState(state), committed_at)

    def stage(self, staged: StagedVersion) -> StoredVersion:
        s = self.schema
        with self.connect() as conn, conn.transaction():
            conn.execute(
                f'INSERT INTO "{s}".partitions VALUES (%s, %s) ON CONFLICT DO NOTHING',
                (staged.partition.digest, canonical_bytes(staged.partition.to_mapping()).decode()),
            )
            inserted = conn.execute(
                f'INSERT INTO "{s}".versions VALUES (%s, %s, %s, %s, %s, %s, %s, NULL) ON CONFLICT DO NOTHING RETURNING 1',
                (
                    staged.memory_item_id, staged.memory_version, staged.partition.digest, staged.stage_digest,
                    canonical_bytes(staged.body()).decode(), staged.staged_at, "PENDING",
                ),
            ).fetchone()
            if inserted is None:
                row = conn.execute(
                    f'SELECT stage_digest, body, staged_at, state, committed_at FROM "{s}".versions '
                    "WHERE memory_item_id = %s AND memory_version = %s FOR SHARE",
                    (staged.memory_item_id, staged.memory_version),
                ).fetchone()
                assert row is not None
                if row[0] != staged.stage_digest:
                    raise stage_conflict(staged.memory_version_ref)
                return self._row(row[1:])
            for pointer in staged.pointers:
                conn.execute(
                    f'INSERT INTO "{s}".pointers VALUES (%s, %s, %s, %s, %s)',
                    (pointer.store_ref, staged.memory_item_id, staged.memory_version,
                     canonical_bytes(pointer.to_mapping()).decode(), "PENDING"),
                )
        return StoredVersion(staged, VersionState.PENDING, None)

    def get(self, memory_item_id: str, memory_version: int) -> StoredVersion | None:
        with self.connect() as conn:
            row = conn.execute(
                f'SELECT body, staged_at, state, committed_at FROM "{self.schema}".versions '
                "WHERE memory_item_id = %s AND memory_version = %s",
                (memory_item_id, memory_version),
            ).fetchone()
        return None if row is None else self._row(row)

    def commit(self, memory_item_id: str, memory_version: int, *, stage_digest: str, committed_at: str) -> StoredVersion:
        s = self.schema
        with self.connect() as conn, conn.transaction():
            row = conn.execute(
                f'SELECT stage_digest, body, staged_at, state, committed_at FROM "{s}".versions '
                "WHERE memory_item_id = %s AND memory_version = %s FOR UPDATE",
                (memory_item_id, memory_version),
            ).fetchone()
            if row is None or row[0] != stage_digest:
                raise stage_conflict(memory_version_ref(memory_item_id, memory_version))
            if row[3] == "COMMITTED":
                return self._row(row[1:])
            conn.execute(f'INSERT INTO "{s}".heads VALUES (%s, 0) ON CONFLICT DO NOTHING', (memory_item_id,))
            head = conn.execute(
                f'SELECT head_version FROM "{s}".heads WHERE memory_item_id = %s FOR UPDATE', (memory_item_id,)
            ).fetchone()
            assert head is not None
            if head[0] != memory_version - 1:
                raise predecessor_not_committed(memory_version_ref(memory_item_id, memory_version))
            conn.execute(
                f'UPDATE "{s}".versions SET state = %s, committed_at = %s WHERE memory_item_id = %s AND memory_version = %s',
                ("COMMITTED", committed_at, memory_item_id, memory_version),
            )
            conn.execute(
                f'UPDATE "{s}".pointers SET state = %s WHERE memory_item_id = %s AND memory_version = %s',
                ("COMMITTED", memory_item_id, memory_version),
            )
            conn.execute(
                f'UPDATE "{s}".heads SET head_version = %s WHERE memory_item_id = %s', (memory_version, memory_item_id)
            )
            committed = conn.execute(
                f'SELECT body, staged_at, state, committed_at FROM "{s}".versions '
                "WHERE memory_item_id = %s AND memory_version = %s",
                (memory_item_id, memory_version),
            ).fetchone()
        assert committed is not None
        return self._row(committed)

    def head(self, memory_item_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                f'SELECT head_version FROM "{self.schema}".heads WHERE memory_item_id = %s', (memory_item_id,)
            ).fetchone()
        return 0 if row is None else int(row[0])

    def pointer(self, store_ref: str) -> tuple[RepresentationPointer, VersionState] | None:
        with self.connect() as conn:
            row = conn.execute(
                f'SELECT body, state FROM "{self.schema}".pointers WHERE store_ref = %s', (store_ref,)
            ).fetchone()
        if row is None:
            return None
        return RepresentationPointer.from_mapping(json.loads(row[0])), VersionState(row[1])

    def versions_in(self, partition_digest: str) -> tuple[StoredVersion, ...]:
        with self.connect() as conn:
            rows = conn.execute(
                f'SELECT body, staged_at, state, committed_at FROM "{self.schema}".versions '
                "WHERE partition_digest = %s ORDER BY memory_item_id, memory_version",
                (partition_digest,),
            ).fetchall()
        return tuple(self._row(row) for row in rows)

    def partitions(self) -> tuple[MemoryPartition, ...]:
        with self.connect() as conn:
            rows = conn.execute(f'SELECT body FROM "{self.schema}".partitions ORDER BY partition_digest').fetchall()
        return tuple(MemoryPartition.from_mapping(json.loads(row[0])) for row in rows)

    def eligible_versions(self, partition_digest: str, where: EligibilityPredicate) -> tuple[StoredVersion, ...]:
        """Port v2: committed head versions whose stored item matches ``where``, in the WHERE clause."""

        predicate, params = _item_sql(where)
        s = self.schema
        with self.connect() as conn:
            rows = conn.execute(
                f'SELECT v.body, v.staged_at, v.state, v.committed_at FROM "{s}".versions v '
                f'JOIN "{s}".heads h ON h.memory_item_id = v.memory_item_id AND h.head_version = v.memory_version '
                f"WHERE v.partition_digest = %s AND v.state = 'COMMITTED' AND {predicate} "
                "ORDER BY v.memory_item_id, v.memory_version",
                (partition_digest, *params),
            ).fetchall()
        return tuple(self._row(row) for row in rows)


class PostgresContentStore:
    def __init__(self, stores: PostgresStores) -> None:
        self._s = stores

    def put(self, object_ref: str, partition_digest: str, sealed: SealedContent) -> None:
        with self._s.connect() as conn:
            conn.execute(
                f'INSERT INTO "{self._s.schema}".content VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING',
                (object_ref, partition_digest, sealed.key_ref, sealed.ciphertext),
            )

    def get(self, object_ref: str) -> SealedContent | None:
        with self._s.connect() as conn:
            row = conn.execute(
                f'SELECT key_ref, ciphertext FROM "{self._s.schema}".content WHERE object_ref = %s', (object_ref,)
            ).fetchone()
        return None if row is None else SealedContent(row[0], bytes(row[1]))

    def delete(self, object_ref: str) -> None:
        with self._s.connect() as conn:
            conn.execute(f'DELETE FROM "{self._s.schema}".content WHERE object_ref = %s', (object_ref,))

    def refs(self, partition_digest: str) -> tuple[str, ...]:
        with self._s.connect() as conn:
            rows = conn.execute(
                f'SELECT object_ref FROM "{self._s.schema}".content WHERE partition_digest = %s ORDER BY object_ref',
                (partition_digest,),
            ).fetchall()
        return tuple(row[0] for row in rows)


class PostgresLexicalIndex:
    """One physical table per partition and lexical representation version (port v2).

    The ``attributes`` column holds ``index_attributes`` beside the pointer
    payload; ``search_eligible`` evaluates the eligibility predicate in the
    same statement as the full-text match and the ranking.
    """

    def __init__(self, stores: PostgresStores) -> None:
        self._s = stores

    def table(self, partition: MemoryPartition, representation_version: str) -> str:
        return _layout_name("lex_", partition.digest, representation_version)

    def _layout(self, conn: psycopg.Connection[Any], table: str) -> str | None:
        row = conn.execute(
            f'SELECT configuration FROM "{self._s.schema}".lexical_layouts WHERE table_name = %s', (table,)
        ).fetchone()
        return None if row is None else str(row[0])

    def upsert(
        self, partition: MemoryPartition, profile: LexicalProfile, store_ref: str, payload: Mapping[str, object], document: str,
        *, attributes: Mapping[str, object] | None = None,
    ) -> None:
        s, table = self._s.schema, self.table(partition, profile.representation_version)
        with self._s.connect() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{s}.{table}",))
            if self._layout(conn, table) is None:
                conn.execute(
                    f'CREATE TABLE "{s}"."{table}" (store_ref text PRIMARY KEY, payload text NOT NULL, '
                    "document text NOT NULL, tsv tsvector NOT NULL, attributes jsonb NOT NULL DEFAULT '{}'::jsonb)"
                )
                conn.execute(f'CREATE INDEX "{table}_tsv" ON "{s}"."{table}" USING GIN (tsv)')
                conn.execute(
                    f'INSERT INTO "{s}".lexical_layouts VALUES (%s, %s, %s, %s)',
                    (table, partition.digest, profile.representation_version, profile.text_search_configuration),
                )
            conn.execute(
                f'INSERT INTO "{s}"."{table}" VALUES (%s, %s, %s, to_tsvector(%s::regconfig, %s), %s::jsonb) '
                "ON CONFLICT (store_ref) DO NOTHING",
                (store_ref, canonical_bytes(dict(payload)).decode(), document,
                 profile.text_search_configuration, document, json.dumps(dict(attributes or {}))),
            )

    def search(self, partition: MemoryPartition, representation_version: str, query: str, *, limit: int, offset: int) -> Sequence[IndexHit]:
        s, table = self._s.schema, self.table(partition, representation_version)
        with self._s.connect() as conn:
            config = self._layout(conn, table)
            if config is None:
                return []
            rows = conn.execute(
                f'SELECT store_ref, payload, ts_rank_cd(tsv, q) AS score FROM "{s}"."{table}", '
                "plainto_tsquery(%s::regconfig, %s) AS q WHERE tsv @@ q "
                "ORDER BY score DESC, store_ref ASC LIMIT %s OFFSET %s",
                (config, query, limit, offset),
            ).fetchall()
        return [IndexHit(row[0], json.loads(row[1]), float(row[2])) for row in rows]

    def search_eligible(
        self, partition: MemoryPartition, representation_version: str, query: str, *,
        where: EligibilityPredicate, limit: int, offset: int,
    ) -> Sequence[IndexHit]:
        s, table = self._s.schema, self.table(partition, representation_version)
        predicate, params = _attribute_sql("attributes", where)
        with self._s.connect() as conn:
            config = self._layout(conn, table)
            if config is None:
                return []
            rows = conn.execute(
                f'SELECT store_ref, payload, ts_rank_cd(tsv, q) AS score FROM "{s}"."{table}", '
                f"plainto_tsquery(%s::regconfig, %s) AS q WHERE tsv @@ q AND {predicate} "
                "ORDER BY score DESC, store_ref ASC LIMIT %s OFFSET %s",
                (config, query, *params, limit, offset),
            ).fetchall()
        return [IndexHit(row[0], json.loads(row[1]), float(row[2])) for row in rows]

    def score_entries(
        self, partition: MemoryPartition, representation_version: str, query: str, store_refs: Sequence[str]
    ) -> Mapping[str, float]:
        """``ts_rank_cd`` of exactly these entries; 0 for a document the query does not match."""

        s, table = self._s.schema, self.table(partition, representation_version)
        with self._s.connect() as conn:
            config = self._layout(conn, table)
            if config is None:
                return {}
            rows = conn.execute(
                f'SELECT store_ref, CASE WHEN tsv @@ q THEN ts_rank_cd(tsv, q) ELSE 0 END FROM "{s}"."{table}", '
                "plainto_tsquery(%s::regconfig, %s) AS q WHERE store_ref = ANY(%s)",
                (config, query, list(store_refs)),
            ).fetchall()
        return {row[0]: float(row[1]) for row in rows}

    def retire(self, partition: MemoryPartition, representation_version: str, memory_item_id: str, below_version: int) -> None:
        s, table = self._s.schema, self.table(partition, representation_version)
        with self._s.connect() as conn:
            if self._layout(conn, table) is None:
                return
            conn.execute(
                f'UPDATE "{s}"."{table}" SET attributes = jsonb_set(attributes, \'{{superseded}}\', \'true\'::jsonb) '
                "WHERE attributes->>'memory_item_id' = %s AND (attributes->>'memory_version')::integer < %s",
                (memory_item_id, below_version),
            )

    def get(self, partition: MemoryPartition, representation_version: str, store_ref: str) -> Mapping[str, object] | None:
        s, table = self._s.schema, self.table(partition, representation_version)
        with self._s.connect() as conn:
            if self._layout(conn, table) is None:
                return None
            row = conn.execute(f'SELECT payload FROM "{s}"."{table}" WHERE store_ref = %s', (store_ref,)).fetchone()
        return None if row is None else json.loads(row[0])

    def read_back(self, partition: MemoryPartition, representation_version: str, store_ref: str) -> IndexEntry | None:
        """Payload and searched document; a tsvector not derived from the document is no body."""

        s, table = self._s.schema, self.table(partition, representation_version)
        with self._s.connect() as conn:
            config = self._layout(conn, table)
            if config is None:
                return None
            row = conn.execute(
                f'SELECT payload, document, tsv = to_tsvector(%s::regconfig, document) FROM "{s}"."{table}" '
                "WHERE store_ref = %s",
                (config, store_ref),
            ).fetchone()
        if row is None:
            return None
        return IndexEntry(json.loads(row[0]), str(row[1]) if row[2] else None)

    def entries(self, partition: MemoryPartition, representation_version: str) -> Sequence[IndexHit]:
        s, table = self._s.schema, self.table(partition, representation_version)
        with self._s.connect() as conn:
            if self._layout(conn, table) is None:
                return []
            rows = conn.execute(f'SELECT store_ref, payload FROM "{s}"."{table}" ORDER BY store_ref').fetchall()
        return [IndexHit(row[0], json.loads(row[1]), 0.0) for row in rows]

    def remove(self, partition: MemoryPartition, representation_version: str, store_ref: str) -> None:
        s, table = self._s.schema, self.table(partition, representation_version)
        with self._s.connect() as conn:
            if self._layout(conn, table) is not None:
                conn.execute(f'DELETE FROM "{s}"."{table}" WHERE store_ref = %s', (store_ref,))


class QdrantVectorIndex:
    """One Qdrant collection per partition and vector representation version (port v2).

    ``index_attributes`` are stored under the ``eligibility`` payload key beside
    the pointer; ``search_eligible`` passes the eligibility predicate to
    Qdrant as the query's payload filter.
    """

    def __init__(self, endpoint: str, namespace: str) -> None:
        self.endpoint = endpoint
        self.namespace = namespace

    def collection(self, partition: MemoryPartition, representation_version: str) -> str:
        return _layout_name(f"ocor_{self.namespace}_", partition.digest, representation_version)

    @staticmethod
    def point_id(store_ref: str) -> str:
        return str(uuid.UUID(hashlib.sha256(store_ref.encode()).hexdigest()[:32]))

    def _call(self, method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
        return _http(method, f"{self.endpoint}{path}", body, timeout=3.0)

    def _require(self, status: int, what: str) -> None:
        if status != 200:
            raise RuntimeError(f"Qdrant {what} -> {status}")

    def upsert(
        self, partition: MemoryPartition, profile: VectorProfile, store_ref: str, payload: Mapping[str, object], vector: Sequence[float],
        *, attributes: Mapping[str, object] | None = None,
    ) -> None:
        name = self.collection(partition, profile.representation_version)
        status, _ = self._call("GET", f"/collections/{name}")
        if status == 404:
            status, _ = self._call(
                "PUT", f"/collections/{name}", {"vectors": {"size": profile.embedding_dimensions, "distance": "Cosine"}}
            )
            if status != 200:
                # A concurrent creator may have won the race; the collection must now exist.
                status, _ = self._call("GET", f"/collections/{name}")
                self._require(status, "create collection")
        else:
            self._require(status, "get collection")
        status, _ = self._call(
            "PUT",
            f"/collections/{name}/points?wait=true",
            {"points": [{"id": self.point_id(store_ref), "vector": list(vector), "payload": {
                "store_ref": store_ref, "pointer": dict(payload), **({"eligibility": dict(attributes)} if attributes is not None else {}),
            }}]},
        )
        self._require(status, "upsert")

    @staticmethod
    def eligibility_filter(where: EligibilityPredicate) -> dict[str, Any]:
        """The eligibility predicate as a Qdrant payload filter."""

        e = "eligibility."
        must: list[dict[str, Any]] = [
            {"key": e + "superseded", "match": {"value": False}},
            {"key": e + "deleted", "match": {"value": False}},
            {"key": e + "lifecycle_status", "match": {"value": "ACTIVE"}},
            {"key": e + "memory_kind", "match": {"any": sorted(where.memory_kinds)}},
            {"key": e + "memory_scope", "match": {"any": sorted(where.memory_scopes)}},
            {"key": e + "valid_from_us", "range": {"lte": where.valid_at_us}},
            {"key": e + "valid_until_us", "range": {"gt": where.valid_at_us}},
            {"key": e + "expires_at_us", "range": {"gt": where.now_us}},
        ]
        if where.source_kinds is not None:
            must.append({"key": e + "source_kind", "match": {"any": sorted(where.source_kinds)}})
        if where.content_schema_refs is not None:
            must.append({"key": e + "content_schema_ref", "match": {"any": sorted(where.content_schema_refs)}})
        if where.min_confidence is not None:
            must.append({"key": e + "confidence", "range": {"gte": where.min_confidence}})
        query_filter: dict[str, Any] = {"must": must}
        must_not: list[dict[str, Any]] = []
        if where.exclude_taint_labels:
            must_not.append({"key": e + "taint_labels", "match": {"any": sorted(where.exclude_taint_labels)}})
        if where.excluded_memory_item_ids:
            must_not.append({"key": e + "memory_item_id", "match": {"any": sorted(where.excluded_memory_item_ids)}})
        if must_not:
            query_filter["must_not"] = must_not
        return query_filter

    def search_eligible(
        self, partition: MemoryPartition, representation_version: str, vector: Sequence[float], *,
        where: EligibilityPredicate, limit: int, offset: int,
    ) -> Sequence[IndexHit]:
        name = self.collection(partition, representation_version)
        status, data = self._call(
            "POST", f"/collections/{name}/points/query",
            {"query": list(vector), "filter": self.eligibility_filter(where), "limit": limit, "offset": offset,
             "with_payload": True, "with_vector": False},
        )
        if status == 404:
            return []
        self._require(status, "filtered query")
        return self._hits(data["result"]["points"])

    def score_entries(
        self, partition: MemoryPartition, representation_version: str, vector: Sequence[float], store_refs: Sequence[str]
    ) -> Mapping[str, float]:
        """Qdrant's own similarity for exactly these points (``has_id`` filter)."""

        if not store_refs:
            return {}
        name = self.collection(partition, representation_version)
        status, data = self._call(
            "POST", f"/collections/{name}/points/query",
            {"query": list(vector), "filter": {"must": [{"has_id": [self.point_id(ref) for ref in store_refs]}]},
             "limit": len(store_refs), "with_payload": True, "with_vector": False},
        )
        if status == 404:
            return {}
        self._require(status, "scoring query")
        wanted = set(store_refs)
        return {hit.store_ref: hit.score for hit in self._hits(data["result"]["points"]) if hit.store_ref in wanted}

    def retire(self, partition: MemoryPartition, representation_version: str, memory_item_id: str, below_version: int) -> None:
        name = self.collection(partition, representation_version)
        status, _ = self._call(
            "POST", f"/collections/{name}/points/payload?wait=true",
            {"payload": {"superseded": True}, "key": "eligibility", "filter": {"must": [
                {"key": "eligibility.memory_item_id", "match": {"value": memory_item_id}},
                {"key": "eligibility.memory_version", "range": {"lt": below_version}},
            ]}},
        )
        if status != 404:
            self._require(status, "retire")

    UNBOUND_POINT = "urn:ocor:unbound-point:"

    def _hits(self, points: Sequence[Mapping[str, Any]]) -> list[IndexHit]:
        hits = []
        for point in points:
            payload = point.get("payload") or {}
            store_ref = payload.get("store_ref")
            # A point not stored under its own ref's id is addressed by raw id so
            # that reconciliation can still remove it.
            if not isinstance(store_ref, str) or self.point_id(store_ref) != str(point["id"]):
                store_ref = self.UNBOUND_POINT + str(point["id"])
            pointer = payload.get("pointer")
            hits.append(IndexHit(store_ref, pointer if isinstance(pointer, dict) else {}, float(point.get("score", 0.0))))
        return hits

    def search(self, partition: MemoryPartition, representation_version: str, vector: Sequence[float], *, limit: int, offset: int) -> Sequence[IndexHit]:
        name = self.collection(partition, representation_version)
        status, data = self._call(
            "POST", f"/collections/{name}/points/query",
            {"query": list(vector), "limit": limit, "offset": offset, "with_payload": True, "with_vector": False},
        )
        if status == 404:
            return []
        self._require(status, "query")
        return self._hits(data["result"]["points"])

    def get(self, partition: MemoryPartition, representation_version: str, store_ref: str) -> Mapping[str, object] | None:
        name = self.collection(partition, representation_version)
        status, data = self._call("GET", f"/collections/{name}/points/{self.point_id(store_ref)}")
        if status == 404:
            return None
        self._require(status, "get point")
        payload = data["result"]["payload"]
        return payload["pointer"] if payload.get("store_ref") == store_ref else None

    def read_back(self, partition: MemoryPartition, representation_version: str, store_ref: str) -> IndexEntry | None:
        """Payload and the vector Qdrant persisted and ranks (binary32)."""

        name = self.collection(partition, representation_version)
        status, data = self._call(
            "POST", f"/collections/{name}/points",
            {"ids": [self.point_id(store_ref)], "with_payload": True, "with_vector": True},
        )
        if status == 404:
            return None
        self._require(status, "retrieve point")
        points = data["result"]
        if not points:
            return None
        payload = points[0].get("payload") or {}
        if payload.get("store_ref") != store_ref or not isinstance(payload.get("pointer"), dict):
            return None
        vector = points[0].get("vector")
        return IndexEntry(payload["pointer"], tuple(vector) if isinstance(vector, list) else None)

    def entries(self, partition: MemoryPartition, representation_version: str) -> Sequence[IndexHit]:
        name = self.collection(partition, representation_version)
        status, data = self._call("POST", f"/collections/{name}/points/scroll", {"limit": 10000, "with_payload": True})
        if status == 404:
            return []
        self._require(status, "scroll")
        return self._hits(data["result"]["points"])

    def remove(self, partition: MemoryPartition, representation_version: str, store_ref: str) -> None:
        name = self.collection(partition, representation_version)
        point = store_ref.removeprefix(self.UNBOUND_POINT) if store_ref.startswith(self.UNBOUND_POINT) else self.point_id(store_ref)
        status, _ = self._call("POST", f"/collections/{name}/points/delete?wait=true", {"points": [point]})
        if status != 404:
            self._require(status, "delete")

    def count(self, partition: MemoryPartition, representation_version: str) -> int:
        name = self.collection(partition, representation_version)
        status, data = self._call("POST", f"/collections/{name}/points/count", {"exact": True})
        if status == 404:
            return 0
        self._require(status, "count")
        return int(data["result"]["count"])

    def collections(self) -> list[str]:
        status, data = self._call("GET", "/collections")
        self._require(status, "list collections")
        return sorted(c["name"] for c in data["result"]["collections"] if c["name"].startswith(f"ocor_{self.namespace}_"))

