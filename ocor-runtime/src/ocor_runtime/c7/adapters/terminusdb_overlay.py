"""Direct TerminusDB client adapter for the C7 ``ScenarioOverlayStore``.

OCOR-DEV-REM-0041, overlay unit (PO OCOR-DEV-0060-BA-SELECTED-COMPONENTS, change set
d; REM-0040-C7-SEALED-RESULT-PORT-DISPOSITION (2026-10-28), points 1, 3 and 9). A
scenario overlay is a TerminusDB branch of the canonical ``VersionedAssertedState``
database (ADD v1.3 Part I §2.4: "Branch di scenario: solo l'adapter
``ScenarioOverlayStore`` di ``C7``, privo della capability ``main.write``"), behind
``ocor_runtime.c7.scenario_overlay.ScenarioOverlayStore``. Every call to the server is
confined to this module (AFF-002/AFF-006, ``OCOR_LANGUAGE_POLICY.md`` row 8), on the
standard library only: no new dependency.

- No ``main.write``: every write targets ``scenario_<token>``, where ``token`` is the
  SHA-256 of the canonical ``(scenario_id, run_id, compartments)`` and is recomputed
  from the handle before every request, so no handle can name ``main`` or another
  run. ``main`` is only read, to verify that a snapshot commit is in its history.
- ``fork_scenario`` creates the branch from the snapshot commit (copy-on-write), adds
  the two overlay classes to the branch schema only, and records the run. An
  existing run is refused (``SCENARIO_EXISTS``): a rebase is a new run, never a
  rewrite. A fork interrupted before the run record leaves an overlay every
  operation refuses (``SCENARIO_INCOMPLETE``) until it is discarded.
- ``append_overlay`` inserts one ``C7OverlayDelta`` per revision in a WOQL transaction
  that also requires the previous delta, so concurrent appends get distinct,
  gap-free revisions; a delta is never updated or deleted. Each delta digest chains
  the previous one; ``read_at`` and ``append_overlay`` verify the whole chain and
  reject a tampered or missing delta.
- A delta is stored as opaque canonical JSON in its own class: it can never become a
  ``C3OutboxEntry``. Outbox entries replicated by the fork stay on the scenario branch,
  which the C3 relay never reads (§2.5 rule 11).
- ``discard`` deletes the scenario branch only. ``seal_result`` and
  ``read_sealed_result`` delegate unchanged to the injected
  ``ScenarioOverlayStoreSealSubset`` (OCOR-DEV-REM-0040, SeaweedFS).

The adapter never falls back to another store (DEC-201): an unreachable server raises
``STORE_UNAVAILABLE``. No credential ever appears in a message or ``repr``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

from ...errors import CanonicalizationError
from ...kernel.canonical import canonical_bytes, canonical_digest, parse_i_json
from ..runtime import CausalOutcome
from ..scenario_overlay import (
    CANONICAL_BRANCH,
    SCENARIO_BRANCH_PREFIX,
    OverlayDelta,
    OverlayView,
    ScenarioBranch,
    ScenarioOverlayError,
    ScenarioSnapshot,
)
from ..sealed_results import ScenarioOverlayStoreSealSubset, SealedResult

TERMINUS_BRANCH_PREFIX = "scenario_"
TERMINUS_BRANCH = re.compile(r"scenario_[0-9a-f]{64}")
COMMIT_REF = re.compile(r"[0-9a-z]{1,64}")
DATABASE_NAME = re.compile(r"[a-z][a-z0-9_]{2,62}")
RESERVED_DATABASES = frozenset({"ocor_default"})
MAX_IDENTIFIER_LENGTH = 512
MAX_DELTA_BYTES = 1 << 20
MAX_CONDITIONAL_ATTEMPTS = 64
LOG_PAGE = 200
RUN_KEY = "run"
NOT_FOUND_ERRORS = frozenset(
    {"api:UnresolvableAbsoluteDescriptor", "api:BranchDoesNotExistError", "api:UnknownDatabase"}
)


def _class(name: str, **fields: str) -> dict[str, Any]:
    return {"@type": "Class", "@id": name, "@key": {"@type": "Lexical", "@fields": ["key"]}, "key": "xsd:string", **fields}


# Added to the schema of the scenario branch only; the schema of ``main`` stays the
# exact C3 schema its own adapter enforces.
OVERLAY_SCHEMA: tuple[dict[str, Any], ...] = (
    _class(
        "C7ScenarioRun",
        scenario_id="xsd:string",
        run_id="xsd:string",
        compartments_json="xsd:string",
        canonical_commit_ref="xsd:string",
        scenario_branch="xsd:string",
    ),
    _class(
        "C7OverlayDelta",
        revision="xsd:integer",
        delta_json="xsd:string",
        delta_digest="xsd:string",
        previous_digest="xsd:string",
    ),
)


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_IDENTIFIER_LENGTH or value != value.strip():
        raise ScenarioOverlayError("SCENARIO_INVALID", f"{field} must be a non-empty trimmed string of at most {MAX_IDENTIFIER_LENGTH} characters")
    return value


def _compartments(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise ScenarioOverlayError("SCENARIO_INVALID", "compartments must be a non-empty tuple")
    items = tuple(_identifier(item, "compartment") for item in value)
    if len(set(items)) != len(items):
        raise ScenarioOverlayError("SCENARIO_INVALID", "compartments must be distinct")
    return tuple(sorted(items))


def run_token(scenario_id: str, run_id: str, compartments: tuple[str, ...]) -> str:
    """The isolation key of one ``(scenario_id, run_id, compartments)`` overlay."""
    identity = {"scenario_id": scenario_id, "run_id": run_id, "compartments": list(compartments)}
    return hashlib.sha256(canonical_bytes(identity)).hexdigest()


def _terminus_branch(branch: ScenarioBranch) -> str:
    """The scenario branch a handle may write, recomputed from its run identity.
    Every write path goes through here: no handle can name ``main``."""
    if not isinstance(branch, ScenarioBranch):
        raise ScenarioOverlayError("SCENARIO_HANDLE_INVALID", "a ScenarioBranch handle is required")
    token = run_token(
        _identifier(branch.scenario_id, "scenario_id"),
        _identifier(branch.run_id, "run_id"),
        _compartments(branch.compartments),
    )
    if branch.compartments != tuple(sorted(branch.compartments)) or branch.scenario_branch != SCENARIO_BRANCH_PREFIX + token:
        raise ScenarioOverlayError("SCENARIO_HANDLE_INVALID", "the handle does not name the overlay of its own run")
    if not isinstance(branch.canonical_commit_ref, str) or COMMIT_REF.fullmatch(branch.canonical_commit_ref) is None:
        raise ScenarioOverlayError("SCENARIO_HANDLE_INVALID", "the handle carries no canonical commit")
    name = TERMINUS_BRANCH_PREFIX + token
    if TERMINUS_BRANCH.fullmatch(name) is None or name == CANONICAL_BRANCH:
        raise ScenarioOverlayError("SCENARIO_HANDLE_INVALID", "not a scenario branch")
    return name


def _delta_key(revision: int) -> str:
    return f"{revision:012d}"


def _chain_digest(scenario_branch: str, revision: int, previous_digest: str | None, delta_json: str) -> str:
    return canonical_digest(
        {"scenario_branch": scenario_branch, "revision": revision, "previous_digest": previous_digest, "delta": delta_json}
    )


def _typed(value: object) -> dict[str, Any]:
    data_type = "xsd:integer" if isinstance(value, int) and not isinstance(value, bool) else "xsd:string"
    if data_type == "xsd:string" and not isinstance(value, str):
        raise ScenarioOverlayError("DELTA_INVALID", f"unsupported stored value {value!r}")
    return {"@type": "Value", "data": {"@type": data_type, "@value": value}}


def _insert(document: Mapping[str, Any]) -> dict[str, Any]:
    fields = [
        {"@type": "FieldValuePair", "field": name, "value": {"@type": "Value", "data": value} if name == "@type" else _typed(value)}
        for name, value in document.items()
    ]
    return {"@type": "InsertDocument", "document": {"@type": "Value", "dictionary": {"@type": "DictionaryTemplate", "data": fields}}}


def _node(doc_type: str, key: str) -> dict[str, Any]:
    return {"@type": "NodeValue", "node": f"{doc_type}/{key}"}


def _holds(doc_type: str, key: str, field: str, value: object) -> dict[str, Any]:
    return {"@type": "Triple", "subject": _node(doc_type, key), "predicate": {"@type": "NodeValue", "node": field}, "object": _typed(value)}


def _absent(doc_type: str, key: str) -> dict[str, Any]:
    present = {"@type": "Triple", "subject": _node(doc_type, key), "predicate": {"@type": "NodeValue", "node": "key"}, "object": {"@type": "Value", "variable": "Present"}}
    return {"@type": "Not", "query": present}


class TerminusDBScenarioOverlayStore:
    """The only module of C7 that talks to TerminusDB."""

    def __init__(
        self,
        *,
        url: str,
        password: str,
        database: str,
        sealed_results: ScenarioOverlayStoreSealSubset,
        user: str = "admin",
        organization: str = "admin",
        author: str = "c7-scenario-overlay",
        timeout: float = 30.0,
    ) -> None:
        if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme not in {"http", "https"}:
            raise ScenarioOverlayError("CONFIGURATION_INVALID", "url: a TerminusDB http(s) URL is required")
        if not isinstance(password, str) or not password:
            raise ScenarioOverlayError("CONFIGURATION_INVALID", "password: a TerminusDB password is required")
        if not isinstance(database, str) or DATABASE_NAME.fullmatch(database) is None or database in RESERVED_DATABASES:
            raise ScenarioOverlayError("CONFIGURATION_INVALID", "database: must match [a-z][a-z0-9_]{2,62} and not be reserved")
        if not isinstance(sealed_results, ScenarioOverlayStoreSealSubset):
            raise ScenarioOverlayError("CONFIGURATION_INVALID", "sealed_results: a ScenarioOverlayStoreSealSubset is required")
        self._url = url.rstrip("/")
        self._auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self._database = database
        self._organization = organization
        self._author = author
        self._timeout = timeout
        self._sealed_results = sealed_results
        self._initialized = False

    def __repr__(self) -> str:
        return f"TerminusDBScenarioOverlayStore(url={self._url!r}, database={self._database!r})"

    # --- transport ---------------------------------------------------------------

    def _request(self, method: str, path: str, *, body: object | None = None) -> tuple[int, Any, str]:
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
            raise ScenarioOverlayError("STORE_UNAVAILABLE", f"{method} {urllib.parse.urlsplit(path).path}: {error}") from error
        return status, self._parse(text), version

    @staticmethod
    def _parse(text: str) -> Any:
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            return json.loads(text[start:]) if start >= 0 else {"raw": text}

    @staticmethod
    def _error_type(body: Any) -> str:
        error = body.get("api:error", {}) if isinstance(body, dict) else {}
        return str(error.get("@type", "")) if isinstance(error, dict) else ""

    def _db(self) -> str:
        return f"{self._organization}/{self._database}"

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise ScenarioOverlayError("STORE_NOT_INITIALIZED", "initialize() has not verified the canonical store")

    # --- lifecycle -----------------------------------------------------------------

    def initialize(self) -> None:
        """Verifies that the canonical database exists. C7 never creates it: the
        canonical store and its ``main`` belong to C3."""
        status, body, _ = self._request("GET", "/api/db")
        if status != 200 or not isinstance(body, list):
            raise ScenarioOverlayError("BACKEND_ERROR", f"cannot list databases: {status}")
        existing = {entry.get("path", "").split("/")[-1] for entry in body if isinstance(entry, dict)}
        if self._database not in existing:
            raise ScenarioOverlayError("CANONICAL_STORE_ABSENT", f"database {self._database!r} does not exist")
        self._initialized = True

    # --- snapshots -------------------------------------------------------------------

    def current_canonical_commit(self) -> str:
        """The head commit of ``main`` (read only)."""
        self._require_initialized()
        status, body, _ = self._request("GET", f"/api/log/{self._db()}?count=1&start=0")
        if status != 200 or not isinstance(body, list) or not body:
            raise ScenarioOverlayError("BACKEND_ERROR", f"cannot read the log of main: {status}")
        return str(body[0]["identifier"])

    def _in_main_history(self, commit_ref: str) -> bool:
        start = 0
        while True:
            status, body, _ = self._request("GET", f"/api/log/{self._db()}?count={LOG_PAGE}&start={start}")
            if status != 200 or not isinstance(body, list):
                raise ScenarioOverlayError("BACKEND_ERROR", f"cannot read the log of main: {status}")
            if any(isinstance(entry, dict) and entry.get("identifier") == commit_ref for entry in body):
                return True
            if len(body) < LOG_PAGE:
                return False
            start += LOG_PAGE

    def open_snapshot(self, canonical_commit_ref: str) -> ScenarioSnapshot:
        if not isinstance(canonical_commit_ref, str) or COMMIT_REF.fullmatch(canonical_commit_ref) is None:
            raise ScenarioOverlayError("SNAPSHOT_INVALID", "a canonical commit reference is required")
        self._require_initialized()
        if not self._in_main_history(canonical_commit_ref):
            raise ScenarioOverlayError("SNAPSHOT_NOT_IN_MAIN", "the commit is not in the history of main")
        return ScenarioSnapshot(canonical_branch=CANONICAL_BRANCH, canonical_commit_ref=canonical_commit_ref)

    # --- scenario branches -------------------------------------------------------

    def fork_scenario(
        self, snapshot: ScenarioSnapshot, *, scenario_id: str, run_id: str, compartments: tuple[str, ...]
    ) -> ScenarioBranch:
        if (
            not isinstance(snapshot, ScenarioSnapshot)
            or snapshot.canonical_branch != CANONICAL_BRANCH
            or not isinstance(snapshot.canonical_commit_ref, str)
            or COMMIT_REF.fullmatch(snapshot.canonical_commit_ref) is None
        ):
            raise ScenarioOverlayError("SNAPSHOT_INVALID", "a snapshot of main is required")
        scenario_id = _identifier(scenario_id, "scenario_id")
        run_id = _identifier(run_id, "run_id")
        ordered = _compartments(compartments)
        token = run_token(scenario_id, run_id, ordered)
        branch = ScenarioBranch(
            scenario_id=scenario_id,
            run_id=run_id,
            compartments=ordered,
            canonical_commit_ref=snapshot.canonical_commit_ref,
            scenario_branch=SCENARIO_BRANCH_PREFIX + token,
        )
        name = _terminus_branch(branch)
        self._require_initialized()
        # A forged snapshot handle is re-checked against the history of main.
        if not self._in_main_history(snapshot.canonical_commit_ref):
            raise ScenarioOverlayError("SNAPSHOT_NOT_IN_MAIN", "the commit is not in the history of main")
        status, body, _ = self._request(
            "POST",
            f"/api/branch/{self._db()}/local/branch/{name}",
            body={"origin": f"{self._db()}/local/commit/{snapshot.canonical_commit_ref}"},
        )
        if self._error_type(body) == "api:BranchExistsError":
            raise ScenarioOverlayError("SCENARIO_EXISTS", "this run already has an overlay; a rebase is a new run")
        if status != 200:
            # Measured on the pinned 12.0.7: of concurrent creations of one branch
            # exactly one answers 200 and the others answer 500 InternalServerError.
            # A failed creation is therefore re-read: an existing branch means another
            # fork owns this run, and this call writes nothing.
            if name in self._branches():
                raise ScenarioOverlayError("SCENARIO_EXISTS", "this run already has an overlay; a rebase is a new run")
            raise ScenarioOverlayError("BACKEND_ERROR", f"cannot fork the scenario branch: {status}")
        query = urllib.parse.urlencode({"graph_type": "schema", "author": self._author, "message": "C7 overlay schema"})
        status, body, _ = self._request(
            "POST", f"/api/document/{self._db()}/local/branch/{name}?{query}", body=list(OVERLAY_SCHEMA)
        )
        if status != 200:
            raise ScenarioOverlayError("BACKEND_ERROR", f"cannot write the overlay schema: {status}")
        run = {
            "@type": "C7ScenarioRun",
            "key": RUN_KEY,
            "scenario_id": scenario_id,
            "run_id": run_id,
            "compartments_json": canonical_bytes(list(ordered)).decode("utf-8"),
            "canonical_commit_ref": snapshot.canonical_commit_ref,
            "scenario_branch": branch.scenario_branch,
        }
        if not self._transact(name, [_absent("C7ScenarioRun", RUN_KEY)], [_insert(run)], f"C7 fork {branch.scenario_branch}"):
            raise ScenarioOverlayError("SCENARIO_EXISTS", "this run already has an overlay; a rebase is a new run")
        return branch

    def _branches(self) -> set[str]:
        status, body, _ = self._request("GET", f"/api/db/{self._db()}?branches=true")
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("branches"), list):
            raise ScenarioOverlayError("BACKEND_ERROR", f"cannot list the branches: {status}")
        return {str(branch) for branch in body["branches"]}

    def _transact(self, name: str, conditions: Sequence[Mapping[str, Any]], writes: Sequence[Mapping[str, Any]], message: str) -> bool:
        """One WOQL transaction on the scenario branch ``name`` (never ``main``):
        ``False`` when a precondition failed, nothing written then."""
        if TERMINUS_BRANCH.fullmatch(name) is None:
            raise ScenarioOverlayError("SCENARIO_HANDLE_INVALID", "writes target scenario branches only")
        query = {"@type": "And", "and": [*conditions, *writes]}
        status, body, _ = self._request(
            "POST",
            f"/api/woql/{self._db()}/local/branch/{name}",
            body={"query": query, "commit_info": {"author": self._author, "message": message}},
        )
        if status == 200 and isinstance(body, dict) and isinstance(body.get("bindings"), list):
            return bool(body["bindings"])
        error = self._error_type(body)
        if error == "api:DocumentIdAlreadyExists":
            return False
        if error in NOT_FOUND_ERRORS:
            raise ScenarioOverlayError("SCENARIO_NOT_FOUND", "the scenario overlay does not exist")
        raise ScenarioOverlayError("BACKEND_ERROR", f"WOQL transaction: {status} {error}")

    def _read_overlay(self, branch: ScenarioBranch) -> tuple[str, tuple[OverlayDelta, ...]]:
        """Reads the run record and every delta at one commit of the scenario branch
        and verifies the handle and the whole delta chain."""
        name = _terminus_branch(branch)
        self._require_initialized()
        status, body, version = self._request(
            "GET", f"/api/document/{self._db()}/local/branch/{name}?type=C7OverlayDelta&as_list=true"
        )
        if status != 200 and self._error_type(body) in NOT_FOUND_ERRORS:
            raise ScenarioOverlayError("SCENARIO_NOT_FOUND", "the scenario overlay does not exist")
        if status != 200 or not isinstance(body, list) or not version.startswith("branch:"):
            raise ScenarioOverlayError("BACKEND_ERROR", f"cannot read the overlay: {status}")
        commit = version.partition(":")[2]
        run_id = urllib.parse.quote(f"C7ScenarioRun/{RUN_KEY}", safe="")
        status, run, _ = self._request("GET", f"/api/document/{self._db()}/local/commit/{commit}?id={run_id}")
        if status == 404 and self._error_type(run) == "api:DocumentNotFound":
            # The branch exists but its run record does not: the fork was interrupted
            # between the branch creation and the run record (a class absent from
            # the branch schema lists as empty on the pinned 12.0.7).
            raise ScenarioOverlayError("SCENARIO_INCOMPLETE", "the fork of this overlay did not complete; discard it")
        if status != 200 or not isinstance(run, dict):
            raise ScenarioOverlayError("BACKEND_ERROR", f"cannot read the run record: {status}")
        expected = {
            "scenario_id": branch.scenario_id,
            "run_id": branch.run_id,
            "compartments_json": canonical_bytes(list(branch.compartments)).decode("utf-8"),
            "canonical_commit_ref": branch.canonical_commit_ref,
            "scenario_branch": branch.scenario_branch,
        }
        if any(run.get(field) != value for field, value in expected.items()):
            raise ScenarioOverlayError("SCENARIO_HANDLE_INVALID", "the run record does not match the handle")
        documents = sorted(body, key=lambda item: int(item.get("revision", 0)) if isinstance(item, dict) else 0)
        deltas: list[OverlayDelta] = []
        previous: str | None = None
        for expected_revision, document in enumerate(documents, start=1):
            if not isinstance(document, dict) or int(document.get("revision", -1)) != expected_revision:
                raise ScenarioOverlayError("OVERLAY_TAMPERED", f"delta {expected_revision} is missing or out of order")
            if document.get("key") != _delta_key(expected_revision):
                raise ScenarioOverlayError("OVERLAY_TAMPERED", f"delta {expected_revision} has a foreign key")
            stored_previous = document.get("previous_digest") or None
            delta_json = document.get("delta_json")
            if stored_previous != previous or not isinstance(delta_json, str):
                raise ScenarioOverlayError("OVERLAY_TAMPERED", f"delta {expected_revision} breaks the chain")
            digest = _chain_digest(branch.scenario_branch, expected_revision, previous, delta_json)
            if document.get("delta_digest") != digest:
                raise ScenarioOverlayError("OVERLAY_TAMPERED", f"delta {expected_revision} does not match its digest")
            try:
                content = parse_i_json(delta_json)
            except (CanonicalizationError, ValueError) as error:
                raise ScenarioOverlayError("OVERLAY_TAMPERED", f"delta {expected_revision} is not canonical JSON") from error
            if not isinstance(content, dict) or canonical_bytes(content).decode("utf-8") != delta_json:
                raise ScenarioOverlayError("OVERLAY_TAMPERED", f"delta {expected_revision} is not canonical JSON")
            deltas.append(OverlayDelta(revision=expected_revision, delta=content, delta_digest=digest, previous_digest=previous))
            previous = digest
        return name, tuple(deltas)

    def append_overlay(self, branch: ScenarioBranch, delta: Mapping[str, Any]) -> OverlayDelta:
        if not isinstance(delta, Mapping):
            raise ScenarioOverlayError("DELTA_INVALID", "a delta is a JSON object")
        try:
            content = parse_i_json(canonical_bytes(dict(delta)))
            delta_json = canonical_bytes(content).decode("utf-8")
        except (CanonicalizationError, TypeError, ValueError) as error:
            raise ScenarioOverlayError("DELTA_INVALID", f"a delta must be canonical I-JSON: {error}") from error
        if len(delta_json.encode("utf-8")) > MAX_DELTA_BYTES:
            raise ScenarioOverlayError("DELTA_INVALID", f"a delta is at most {MAX_DELTA_BYTES} bytes")
        _terminus_branch(branch)
        for _ in range(MAX_CONDITIONAL_ATTEMPTS):
            name, deltas = self._read_overlay(branch)
            previous = deltas[-1].delta_digest if deltas else None
            revision = len(deltas) + 1
            digest = _chain_digest(branch.scenario_branch, revision, previous, delta_json)
            document = {
                "@type": "C7OverlayDelta",
                "key": _delta_key(revision),
                "revision": revision,
                "delta_json": delta_json,
                "delta_digest": digest,
                "previous_digest": previous or "",
            }
            conditions = [
                _holds("C7ScenarioRun", RUN_KEY, "scenario_branch", branch.scenario_branch),
                _absent("C7OverlayDelta", _delta_key(revision)),
            ]
            if previous is not None:
                conditions.append(_holds("C7OverlayDelta", _delta_key(revision - 1), "delta_digest", previous))
            if self._transact(name, conditions, [_insert(document)], f"C7 overlay {branch.scenario_branch} revision {revision}"):
                return OverlayDelta(revision=revision, delta=content, delta_digest=digest, previous_digest=previous)
        raise ScenarioOverlayError("WRITE_CONTENTION", "delta not appended within the attempt budget")

    def read_at(self, branch: ScenarioBranch, revision: int) -> OverlayView:
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ScenarioOverlayError("REVISION_INVALID", "a revision is a non-negative integer")
        _, deltas = self._read_overlay(branch)
        if revision > len(deltas):
            raise ScenarioOverlayError("REVISION_NOT_FOUND", f"the overlay has {len(deltas)} revisions")
        return OverlayView(branch=branch, revision=revision, deltas=deltas[:revision])

    def discard(self, branch: ScenarioBranch) -> bool:
        name = _terminus_branch(branch)
        self._require_initialized()
        status, body, _ = self._request("DELETE", f"/api/branch/{self._db()}/local/branch/{name}")
        if status == 200:
            return True
        if self._error_type(body) in NOT_FOUND_ERRORS:
            return False
        raise ScenarioOverlayError("BACKEND_ERROR", f"cannot discard the scenario branch: {status}")

    # --- sealed results (ScenarioOverlayStoreSealSubset, OCOR-DEV-REM-0040) ---------

    def seal_result(self, outcome: CausalOutcome) -> SealedResult:
        return self._sealed_results.seal_result(outcome)

    def read_sealed_result(self, reproducibility_digest: str) -> CausalOutcome:
        return self._sealed_results.read_sealed_result(reproducibility_digest)
