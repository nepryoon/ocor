# OCOR-DEV-REM-0068 — current evidence head contract

Design contract for the unit in CONFINE-G6 (2026-11-20) point 4, brought forward by REM-0066-CYCLE3-NO-GO (2026-11-24) points 1b and 2. This file is that contract. It contains no production code. One design review follows this commit. The code branch starts from `origin/main` only after `FUSEKI-ARCHIVE-COPY-20261123` is on `origin/main`, and only after that review.

## Why this file is not an extension of OCOR-DEV-REM-0067

The published contract on `governed/ocor-dev-rem-0067-fuseki-ci-label-contract` at `1ac9d2846624b55b5472d4d91d10104098ef3f99` is the FUSEKI-ETICHETTA-CI contract. Points 2a and 2b of REM-0066-CYCLE3-NO-GO name the contract of the CONFINE-G6 point-4 unit, which is this file. They are absent from the REM-0067 contract because they do not belong to that unit.

The review `OCOR-DEV-REM-0067-88d526421d77-pre` on `88d526421d77cbe8db4f1a1546b41dcb929a7156` returned one blocking finding. Commit `1ac9d2846624b55b5472d4d91d10104098ef3f99` closes it: a bare compose up can create `ocor/jena-fuseki:6.2.0` when that image is absent, and that residual path stays outside the CI-bootstrap property. That commit states that the correction does not request a second design review. The three advisory findings are accepted there. This unit does not edit that README.

## Identifier

CONFINE-G6 point 4 asks for the first free `OCOR-DEV-REM-*` verified read-only on `origin/main`. Measured on `origin/main` `618e72c00f994e8ea8899914548cc38743aa4569`:

- `git grep -h -o -E 'OCOR-DEV-REM-[0-9]{4}' origin/main | sort -u | tail -n 1` prints `OCOR-DEV-REM-0066`.
- `git branch -r | grep -oE -i 'ocor-dev-rem-[0-9]{4}' | tr '[:lower:]' '[:upper:]' | sort -u | tail -n 1` prints `OCOR-DEV-REM-0067`.

`OCOR-DEV-REM-0067` is already the published Fuseki CI-label unit. It is absent from `origin/main` and present in remote branch names. The first identifier absent from both is `OCOR-DEV-REM-0068`. Gaps below 0066 are not filled.

## Property

For every task in `completed_evidence_tasks`, the new gate either validates exactly one current head, in full, or emits a finding that names the task and a code. No path returns PASS for a record that a distinct listed record of the same task supersedes. Every manifest entry is admitted or produces a finding. A presented input is never skipped.

`scripts/validate_evidence_input_drift.py` stays byte-identical, including `select_most_recent`. REM-0061-STRICT-SELECTION-REPO-HEADS points 1, 4, 6, and 7 still hold. CONFINE-G6 removes only point 8 for `OCOR-DEV-REM-0060` and the second half of point 5. The strict property moves to this gate. `select_most_recent` can still return the latest `created_at` among several current heads and PASS. This gate does not. CI runs both. The workflow step fails when this gate fails.

## Canonical identity

The canonical identity is `record_id`. The gate does not invent an identity from `commit` or from the path at selection time. A record with no `record_id` receives its identity from a reconciliation record. `supersedes` names a canonical `record_id`. Historical forms (path, path with `@sha256`, commit) count only through reconciliation.

At this base, among completed tasks: 402 evidence JSON records, 75 without `record_id` (one original per task); 0 of 75 tasks have `record_id` on every record; 14 tasks have a single current head and that head has no `record_id` (`0001`, `0016`, `0018`, `0021`, `0024`, `0025`, `0026`, `0027`, `0053`, `0056`, `0057`, `0080`, `0083`, `0084`). `supersedes` strings: 305 match a listed identity, 15 are repository paths, 1 is the historical form `reports/evidence/G4/OCOR-DEV-0049.json@sha256:c2355d6d25714fb21b03f473c330d997e3ba4749bfc123ae490c4938c6c2683f (sigillato in df444af855e884d7783612b302e008b90105fe13, GO OCOR-DEV-0049-b14e4bf; nessun record_id)`, 6 name a `record_id` that is not an identity of a listed record of that task (`OCOR-DEV-0005-requalified-rem0029-1853a6461b08`, `OCOR-DEV-0019-rem0022-085d3fddbed0`, `OCOR-DEV-0040-rem0022-085d3fddbed0`, `OCOR-DEV-0050-rem0022-085d3fddbed0`, `OCOR-DEV-0050-requalified-rem0029-1853a6461b08`, `OCOR-DEV-0082-requalified-rem0029-1853a6461b08`). Twenty-two tasks have more than one current head under today's fallback identity: `0005` (2), `0017` (2), `0019` (2), `0028` (2), `0029` (2), `0030` (2), `0031` (2), `0033` (2), `0034` (2), `0035` (2), `0036` (2), `0039` (2), `0040` (2), `0042` (2), `0045` (2), `0046` (2), `0048` (2), `0049` (3), `0050` (8), `0061` (2), `0075` (2), `0082` (2). Five groups have two or more successors of the same predecessor (`0049` one group, `0050` three groups, `0075` one group).

## Migration

New files and new manifest entries only. No sealed record is rewritten. No existing manifest entry changes. One reconciliation record per affected task, measured at the unit base, states the head that remains and the proof of that choice.

Affected at `618e72c00f994e8ea8899914548cc38743aa4569`: all 75 completed tasks, because each has at least one record without `record_id`. The reconciliation record uses the existing task-evidence shape (`task_id`, `record_id`, `supersedes`, `inputs`, `created_at`) plus `reconciles`, a map from each historical identity string to a canonical `record_id` of a listed record. `supersedes` on the reconciliation record names the canonical `record_id` of the head that remains. `ocor-runtime/schemas/evidence.schema.json` is the EV-001–EV-035 criterion object (`evidenceId`, `criterionId`, `outcome`) and has no `supersedes`. No schema in this tree contains `supersedes`. This commit does not change a schema, a contract, or a register. If the code phase finds an approved schema that rejects `reconciles`, stop before the production change and open one normative request.

The code phase remeasures on the `origin/main` from which its branch starts. If the completed-task set is not these 75, or any completed task then has `record_id` on every record, stop and open one request. Do not invent paths.

## Matrix

Three entry points of `scripts/validate_current_evidence_head.py`:

- E1, `--root .`: head property for every completed task, and manifest admission.
- E2, `--execution-commit <sha> --record <path>`: head property for that record's task in the tree of that commit. PASS only when the named record is the single current head. Manifests are not an input.
- E3, `--manifest <path>`: admission of that manifest. Head selection is not an input. CI does not add a separate E3 command: E1 already admits every manifest.

Seventeen input classes: (1) single record; (2) linear chain; (3) chain whose link is a path; (4) chain whose link is path`@sha256`; (5) chain whose link is a commit; (6) self-supersedes; (7) two successors of the same predecessor; (8) two heads with no common ancestor; (9) `supersedes` names nothing listed; (10) cycle; (11) reconciliation present and sufficient; (12) reconciliation absent; (13) reconciliation names an unlisted head; (14) manifest `path` or `task_id` is not a non-empty string; (15) listed file absent; (16) unlisted canonical evidence file present; (17) unreadable JSON.

Cell count: 3 × 17 = 51. The outcome is the result of the cell, not a third axis. Outcomes are PASS with one validated head, or a finding with the task and a code. Never a silent skip.

Outcome function:

- Classes 1, 2, and 11, when the graph has one head and every `supersedes` is a listed canonical `record_id` (class 11 supplies that mapping for historical forms and for records without `record_id`): E1 PASS. E2 PASS only for the current head; E2 on a superseded record finds `NOT_CURRENT_HEAD`. E3 does not select heads; E1 carries the graph result, so an E3 shape PASS is not a PASS of the head property.
- Classes 3, 4, and 5 without a sufficient reconciliation: E1 and E2 find `RECONCILIATION_ABSENT`. With class 11 covering the historical string, they follow class 2.
- Class 6: `SELF_SUPERSEDES`. Class 7: `TWO_SUCCESSORS`. Class 8: `MULTIPLE_HEADS`. Class 9, unless reconciliation maps the string: `SUPERSEDES_UNRESOLVED`. Class 10: `CYCLE`. Class 12: `RECONCILIATION_ABSENT`. Class 13: `RECONCILIATION_UNLISTED`. E1 and E2 emit these. No PASS.
- Classes 14–17: E1 and E3 find `MANIFEST_FIELD`, `MANIFEST_MISSING`, `MANIFEST_UNLISTED`, or `UNREADABLE_JSON`. E2 does not receive a manifest. An unreadable file passed as `--record` is `UNREADABLE_JSON` on E2. Today's drift script skips unreadable JSON; this gate does not.
- A graph class presented only to E3 is not dropped: E1 emits the graph finding. A manifest class is not an E2 input; E1 and E3 emit the finding.

## Examples

Positive, producer to consumer. Producer: class 2, record `A` with `record_id` `OCOR-DEV-0002-base`, record `B` with `record_id` `OCOR-DEV-0002-next` and `supersedes` `OCOR-DEV-0002-base`. Consumer: E1 PASS, validated head `B`. E2 PASS only when `--record` is `B`.

Negative, producer to consumer. Producer: class 7, records `B` and `C` both `supersedes` `A`. Consumer: E1 finding for that task, code `TWO_SUCCESSORS`. Neither `B` nor `C` is PASS. The CI step is red.

## Oracle

The tests contain a reference selector on an abstract graph. It uses the Python standard library only and does not import production code, directly or indirectly. It runs on generated graphs: every class, pairwise combinations of classes, and random graphs with a fixed seed. Mutation probes: removing each new check fails at least one test. The reference selector is the expected result. The production script is the subject, not the oracle.

## Later units

On the merge result with `main`, this gate fails when a task has more than one current head. A requalification names in `supersedes` the current head on `main` at merge time: the canonical `record_id` this gate validates. After this unit, a new record without `record_id` is a finding. `select_most_recent` remains in the unchanged drift script for hash checks only.

## Allowlist and digest (points 2a and 2b)

Point 2b. The allowlist in `scripts/validate_ocor_development_plan.py` stays among the inputs evidence records pin. This contract does not remove it and does not move it. No normative request is opened. The class defect, a requalification left attached to a head that another merged change set has already superseded, is closed by this gate and by naming that current head in `supersedes`.

Point 2a. This commit adds one allowlist entry, `reports/assurance/OCOR-DEV-REM-0068-RCCAD/README.md`, and the validator rewrites its own sha256 in `reports/planning/OCOR_PLAN_RUN_STATE.json`. Both paths are already planning or extension inputs. No other allowlist line is added now. Records that pin the validator are not rewritten in this commit. The existing drift gate therefore fails for the three tasks below until the code phase requalifies them. That failure is expected on this design head. It is corrected before any `verify_request.json` of the code phase, not in this commit.

Code-phase allowlist entries, listed here and not added now:

- `scripts/validate_current_evidence_head.py`
- `reports/tests/test_validate_current_evidence_head.py`
- `reports/assurance/OCOR-DEV-REM-0068-RCCAD/OCOR-DEV-REM-0068.json`
- `reports/assurance/OCOR-DEV-REM-0068-RCCAD/OCOR-DEV-REM-0068.log`
- `reports/assurance/OCOR-DEV-REM-0068-RCCAD/red.log`
- `reports/assurance/OCOR-DEV-REM-0068-RCCAD/green.log`
- `reports/assurance/OCOR-DEV-REM-0068-RCCAD/pre-campaign.log` only if that log is produced

Regression-only requalifications, because `select_most_recent` on this base pins `scripts/validate_ocor_development_plan.py` in exactly these heads: `OCOR-DEV-0005` (`OCOR-DEV-0005-requalified-fuseki-20261121-dd0467f18816`, G0), `OCOR-DEV-0050` (`OCOR-DEV-0050-requalified-fuseki-20261121-dd0467f18816`, G5), `OCOR-DEV-0082` (`OCOR-DEV-0082-requalified-fuseki-20261121-dd0467f18816`, G2). No current head pins `scripts/validate_evidence_input_drift.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json`, or `.github/workflows/ocor-tooling-bootstrap.yml`. Paths:

- `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0068.json` and `.log`
- `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0068.json` and `.log`
- `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0068.json` and `.log`

Each `supersedes` names the head `select_most_recent` returns on `origin/main` at code-phase merge time. The names above apply only while those heads are still selected. The code phase remeasures. If the pin set is not exactly `{OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082}`, stop and open one request.

Reconciliation, one JSON and one log per completed task, gate as measured: G0 `0001`–`0006`; G1 `0007`–`0014`; G2 `0015`–`0027` and `0070`–`0084`; G3 `0028`–`0031`; G4 `0032`–`0049`; G5 `0050`–`0059`; G6 `0061`. The path is `reports/evidence/<gate>/<OCOR-DEV-NNNN>.reconciled-rem0068.json` and the same path with `.log`. A range includes every integer in it. That is 75 tasks, 150 paths.

Existing manifest files `reports/evidence/G0/MANIFEST.json` through `G6/MANIFEST.json` are already allowlisted. The code phase appends entries and does not change an existing entry. `.github/workflows/ocor-tooling-bootstrap.yml` is already allowlisted. The code phase adds one command to the existing drift step: `ocor-runtime/.venv/bin/python scripts/validate_current_evidence_head.py --root .` beside the unchanged drift command at line 125 of this base. No other workflow edit.

## Sequence

This commit is the design contract. The next step is one design review. RED, GREEN, the pre-campaign review, the qualifying campaign, and verification come after `FUSEKI-ARCHIVE-COPY-20261123` is on `origin/main`. Until this unit is integrated, no other unit starts a qualifying local campaign. State syncs and the archive-copy change set are outside that pause. There is no cycle 4 of `OCOR-DEV-REM-0066` in this iteration. Candidate `3b2ee600ee5d9e3055e3d916628d958635fefff3` is not modified. Claims stay `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC and Production `NO-GO`.
