# OCOR-DEV-REM-0068 — current evidence head contract

Design contract for the unit in CONFINE-G6 (2026-11-20) point 4, brought forward by REM-0066-CYCLE3-NO-GO (2026-11-24) points 1b and 2. This file is that contract. It contains no production code. The design review of `6c52de0657a62b5dd0053a7fd88b6e20fe1400ca` is `OCOR-DEV-REM-0068-6c52de0657a6-pre` (outcome sha256 `e959a0de2fb2ab1297d2bd16218b51ceb91c33d5af163f8611df4020664c4b95`): `BLOCKING_FINDINGS`, two blocking, zero advisory. Reviewer: Cursor CLI, `cursor-grok-4.6-xhigh`, xAI, reserve reviewer. Implementer of this contract: Grok Build, `grok-4.7`, xAI. Same vendor, different Grok generation. This commit closes both blocking findings. PRE-CAMPAIGN-REVIEW (2026-10-26) point 3 and CONFINE-G6 point 4 allow one design review: this commit does not request a second one. The code branch starts from `origin/main` only after the unit that replaces `FUSEKI-ARCHIVE-COPY-20261123` under FUSEKI-ARCHIVE-COPY-20261123-CYCLE3-NO-GO (2026-11-24) option 1 is on `origin/main`. That option is not applied in this commit. Candidate `24633cc9d4c49749bd33a386020fe0d9f6cf5174` is not modified.

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

`OCOR-DEV-REM-0068-REDESIGN (2026-11-28)` option 1 replaces the hand-extended matrix with one pure function on the explicit graph. `scripts/validate_current_evidence_head.py` exposes that function. E1, E2, and E3 are projections of it, not three scans. Evidence nodes are only descendants of the directory `reports/evidence/`, by path components: `reports/evidence-archive` is not a node. E2 lists Git paths terminated by NUL and keeps the blob name until the read, including a name that is not UTF-8. A `--record` outside that perimeter is a finding with code `OUTSIDE_EVIDENCE`. The finding names the task when the JSON carries one, otherwise the presented path. It is not PASS. Loading walks the JSON value on an explicit stack. It does not recurse on the Python call stack.

## Canonical identity

The canonical identity is `record_id` when that field is a non-empty string. Otherwise it is the `reconciles` map of the reconciliation record, whose key equals one exact historical string this contract already lists (repository path, path with `@sha256`, the long historical form, or a commit) and whose value designates exactly one listed record. The execution commit alone is not an identity. Two paths that share an execution commit, and that have no `record_id` and no unique historical key, are not one head. A new record with no `record_id` and no unique key is `RECONCILIATION_ABSENT`. Two records that receive the same key are `AMBIGUOUS_IDENTITY`. `supersedes` names a canonical `record_id`. Historical forms count only through that map.

Current set, from REM-0061-CYCLE5-REDESIGN (2026-11-13) option 1, which CONFINE-G6 point 4 places on this gate. A listed evidence record leaves the current set only when a distinct listed record of the same task names its canonical identity in `supersedes`. The head that remains is not named by that exit rule: no `supersedes` edge, including the reconciliation list, names it. A successor that some other listed record already supersedes is not current, so that historical pair is not class 7.

At this base, among completed tasks: 402 evidence JSON records, 75 without `record_id` (one original per task); 0 of 75 tasks have `record_id` on every record; 14 tasks have a single current head and that head has no `record_id` (`0001`, `0016`, `0018`, `0021`, `0024`, `0025`, `0026`, `0027`, `0053`, `0056`, `0057`, `0080`, `0083`, `0084`). `supersedes` strings: 305 match a listed identity, 15 are repository paths, 1 is the historical form `reports/evidence/G4/OCOR-DEV-0049.json@sha256:c2355d6d25714fb21b03f473c330d997e3ba4749bfc123ae490c4938c6c2683f (sigillato in df444af855e884d7783612b302e008b90105fe13, GO OCOR-DEV-0049-b14e4bf; nessun record_id)`, 6 name a `record_id` that is not an identity of a listed record of that task (`OCOR-DEV-0005-requalified-rem0029-1853a6461b08`, `OCOR-DEV-0019-rem0022-085d3fddbed0`, `OCOR-DEV-0040-rem0022-085d3fddbed0`, `OCOR-DEV-0050-rem0022-085d3fddbed0`, `OCOR-DEV-0050-requalified-rem0029-1853a6461b08`, `OCOR-DEV-0082-requalified-rem0029-1853a6461b08`). Twenty-two tasks have more than one current head under today's fallback identity: `0005` (2), `0017` (2), `0019` (2), `0028` (2), `0029` (2), `0030` (2), `0031` (2), `0033` (2), `0034` (2), `0035` (2), `0036` (2), `0039` (2), `0040` (2), `0042` (2), `0045` (2), `0046` (2), `0048` (2), `0049` (3), `0050` (8), `0061` (2), `0075` (2), `0082` (2). Five groups have two or more successors of the same predecessor (`0049` one group, `0050` three groups, `0075` one group).

## Migration

New files and new manifest entries only. No sealed record is rewritten. No existing manifest entry changes. One reconciliation record per affected task, measured on the base of the code branch, states the head that `select_most_recent` selects and the proof of that selection.

Affected at `618e72c00f994e8ea8899914548cc38743aa4569`: all 75 completed tasks, because each has at least one record without `record_id`. The reconciliation record is not an evidence record and is not a manifest entry. It has no `task_id`, so `discover_records` in the byte-identical drift script does not index it. It lives outside `reports/evidence`, at `reports/assurance/OCOR-DEV-REM-0068-RCCAD/reconciliation/<OCOR-DEV-NNNN>.json`. Fields: `remaining_head` (the canonical `record_id` of the evidence record that `select_most_recent` in the byte-identical `scripts/validate_evidence_input_drift.py` selects for that task on the base of the code branch; when that record has no `record_id`, the reconciliation assigns the canonical id and `reconciles` maps the identity `select_most_recent` used), `supersedes` (a list, one canonical `record_id` per discarded current evidence head, never including `remaining_head`), `reconciles` (a map from each historical identity string to a canonical `record_id` of a listed evidence record), and the proof of that selection. If the proof shows that the selected record cannot remain, for example because it does not pass the full validation of this gate, stop before production code and open one request. Each list element is one canonical identity. The list is how the single reconciliation record retires every discarded branch while the chosen head stays current. Evidence records keep a single string `supersedes`. Drift reads only a string and never sees this file, so it cannot select the reconciliation record in place of a sealed evidence record. The gate lists the file, does not treat it as a head candidate, and applies each list element as one supersedes edge. After that application the only current evidence head is `remaining_head`.

`ocor-runtime/schemas/evidence.schema.json` is the EV-001–EV-035 criterion object (`evidenceId`, `criterionId`, `outcome`) and has no `supersedes`. No schema in this tree contains `supersedes`. This commit does not change a schema, a contract, or a register. If the code phase finds an approved schema that rejects `reconciles` or a list-valued `supersedes` on this non-evidence file, stop before the production change and open one normative request.

The code phase remeasures on the `origin/main` from which its branch starts. That base is where `select_most_recent` chooses `remaining_head`. If the completed-task set is not these 75, or any completed task then has `record_id` on every record, stop and open one request. Do not invent paths. If `origin/main` changes before the merge, the reconciliation records of the affected tasks are redone on the new base with the same rule, and the gate counts are remeasured on the merge result. This is the alignment to A1, B1 and points 1 and 2 of OCOR-DEV-REM-0068-CURRENT-HEAD-READING (2026-11-24). That alignment changes no other reading. `OCOR-DEV-REM-0068-REDESIGN (2026-11-28)` option 1 replaces the hand-extended matrix and does not reopen this reading.

## Matrix

Three entry points of `scripts/validate_current_evidence_head.py`:

- E1, `--root .`: head property for every completed task, and manifest admission.
- E2, `--execution-commit <sha> --record <path>`: head property for that record's task in the tree of that commit. PASS only when the named record is the single current head. Manifests are not an input.
- E3, `--manifest <path>`: admission of that manifest. Head selection is not an input. CI does not add a separate E3 command: E1 already admits every manifest.

Seventeen input classes: (1) single record; (2) linear chain; (3) chain whose link is a path; (4) chain whose link is path`@sha256`; (5) chain whose link is a commit; (6) self-supersedes; (7) two successors of the same predecessor; (8) two heads with no common ancestor; (9) `supersedes` names nothing listed; (10) cycle; (11) reconciliation present and sufficient; (12) reconciliation absent; (13) reconciliation names an unlisted head; (14) manifest `path` or `task_id` is not a non-empty string; (15) listed file absent; (16) unlisted canonical evidence file present; (17) unreadable JSON.

The fifty-one cells, three entries by seventeen classes, stay the minimum. The outcome is the result of the cell, not a third axis. Outcomes are PASS with one validated head, or a finding with the task and a code. Never a silent skip. The hand-written extensions of that matrix are withdrawn. One pure function decides the graph. E1, E2, and E3 project it.

Outcomes of the fifty-one cells:

- Classes 1, 2, and 11, when the graph has one current evidence head and every `supersedes` edge is a listed canonical `record_id` (class 11 supplies that mapping for historical forms and for records without `record_id`): E1 PASS. E2 PASS only for the current head; E2 on a superseded record finds `NOT_CURRENT_HEAD`. E3 does not select heads; E1 carries the graph result, so an E3 shape PASS is not a PASS of the head property.
- Classes 3, 4, and 5 without a sufficient reconciliation: E1 and E2 find `RECONCILIATION_ABSENT`. With class 11 covering the historical string, they follow class 2. The execution commit alone does not cover class 5.
- Class 6: `SELF_SUPERSEDES`. Class 7, only when two or more current evidence records name the same predecessor: `TWO_SUCCESSORS`. A successor that is not current does not count. Class 8, two current evidence heads with no common ancestor: `MULTIPLE_HEADS`. Class 9, unless reconciliation maps the string: `SUPERSEDES_UNRESOLVED`. Class 10: `CYCLE`. Class 12: `RECONCILIATION_ABSENT`, also when the reconciliation file is missing, unreadable, or carries a non-empty `task_id`. Class 13: `RECONCILIATION_UNLISTED`, also when `remaining_head` or a `supersedes` element is not a canonical identity of a listed evidence record, or when the list names `remaining_head`. E1 and E2 emit these. No PASS. After a sufficient reconciliation the only current evidence head is `remaining_head`; any other count is `MULTIPLE_HEADS` or `RECONCILIATION_ABSENT`, never PASS.
- Classes 14–17: E1 and E3 find `MANIFEST_FIELD`, `MANIFEST_MISSING`, `MANIFEST_UNLISTED`, or `UNREADABLE_JSON`. E2 does not receive a manifest except the unreadable `--record` case of class 17, which is `UNREADABLE_JSON` on E2. Today's drift script skips unreadable JSON; this gate does not.
- A graph class presented only to E3 is not dropped: E1 emits the graph finding. A manifest class of 14, 15, or 16 is not an E2 input; E1 and E3 emit the finding. Class 16 on E3 is an unlisted canonical file in the directory of the requested manifest.

Overrides, which replace the withdrawn extensions:

- Reconciliation is only the exact directory `reports/assurance/OCOR-DEV-REM-0068-RCCAD/reconciliation/` and the exact name `<OCOR-DEV-NNNN>.json`. A file whose name ends in `.reconciliation.json`, anywhere under `reports/evidence/`, is an evidence record. It enters the graph or produces a finding. The suffix does not skip it. Sitting under `reports/evidence/` does not by itself make a file a reconciliation record.
- E3 receives the requested manifest and the files that manifest lists, and it still applies class 16 inside that manifest's directory. It does not read `reports/development/EXECUTION_STATE.json`. It does not emit `MANIFEST_UNLISTED` for a task of another gate. A record of another gate does not fail that E3 invocation. E3 without the state file is not `UNREADABLE_JSON` for that absence. E1 still admits every manifest and still emits the graph findings.
- Depth of a JSON value: a scalar (string, number, boolean, or null) has depth 0; an empty object or array has depth 1; any other object or array has depth 1 plus the maximum depth of its children. The limit is 11. A document at depth 11 is loaded. A document at depth 12 or more, on every entry that loads it, is JSON `UNREADABLE_JSON` that names the task and the code. Never `RecursionError`. Never empty stdout.

Depth measured on the code-branch base `23e6b62c36627de91cb85329b9a1164f3219cd53`, every `reports/evidence/**/*.json`, 450 files, 0 unreadable. Maximum depth 10, on `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0030.json`, `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0030.json`, and `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0030.json`. Histogram: depth 3 has 21, 4 has 178, 5 has 188, 6 has 11, 7 has 38, 9 has 11, 10 has 3. Stdout sha256 `dca24a5bc219514d2aed000bff95b20d05f3cf8810f90ce7c736bf2ca9432a5a`. The limit 11 is strictly above that maximum.

Eighteen cells are added. The count in this commit is 51 + 18 = 69.

| Cell | Proof |
| --- | --- |
| One pure function; E1, E2, and E3 are projections | Tests call the pure function and the three entries on the same graph |
| Directory perimeter, not a string prefix | Fixture `reports/evidence-archive` on E1 and on E2 |
| Git paths terminated by NUL, name kept until the read | The non-UTF-8 test of cycle 0 stays green |
| `--record` outside the perimeter is `OUTSIDE_EVIDENCE` | E2 on a sibling path is not PASS |
| Reconciliation only by exact directory and name | `second.reconciliation.json` under evidence is not skipped |
| Identity is `record_id`, else one historical key, never the commit alone | Two paths with the same execution commit |
| New record without `record_id` and without a unique key | `RECONCILIATION_ABSENT`, the cycle-1 VF-004 fixture, on the existing class 12 |
| Ambiguous key | `AMBIGUOUS_IDENTITY`, two records, one key |
| Iterative load; above the limit, JSON `UNREADABLE_JSON` | Accept depth 11 and reject depth 12, on every entry that loads |
| E3 reads the requested manifest and its listed files | Two valid manifests; a foreign record does not fail E3; E3 without state is not `UNREADABLE_JSON` |
| Independent oracle; production is the subject | The oracle does not import production; both verdicts' forms are cells |
| Cycle-0 tests that cycle 1 records as green stay | Same expectation; no test removed or loosened |
| Drift byte-identical; sealed records not rewritten | `git diff` of the drift script is empty |
| `vf004_schema_conformance` is not PASS | It stays `NOT_CORRECTED` |
| One campaign on the final HEAD and one verification by a provider other than xAI | Verdict on the exact HEAD; the verifier is not started by the implementer |
| No further cycle after a `NO_GO` | One new request only |

The eighteen added cells are: the pure-function projection; `reports/evidence-archive` on E1; the same on E2; E2 `OUTSIDE_EVIDENCE`; `second.reconciliation.json` under evidence on E1; the same on E2; the execution-commit collision on E1; the same on E2; `AMBIGUOUS_IDENTITY` on E1; the same on E2; depth 11 accepted on E1, on E2, and on E3; depth 12 rejected on E1, on E2, and on E3; the foreign-record E3 case; E3 without the state file. That is eighteen. The cycle-1 VF-004 fixture proves class 12 and is not a nineteenth cell. Codes added to the closed set are `OUTSIDE_EVIDENCE` and `AMBIGUOUS_IDENTITY`. The other codes stay.

## Examples

Positive, producer to consumer. Producer: class 2, record `A` with `record_id` `OCOR-DEV-0002-base`, record `B` with `record_id` `OCOR-DEV-0002-next` and `supersedes` `OCOR-DEV-0002-base`. Consumer: E1 PASS, validated head `B`. E2 PASS only when `--record` is `B`.

Negative, producer to consumer. Producer: class 7, records `B` and `C` both current and both `supersedes` `A`. Consumer: E1 finding for that task, code `TWO_SUCCESSORS`. Neither `B` nor `C` is PASS. The CI step is red. If a later record supersedes `C`, `C` is not current and that pair is not class 7; `B` and the later record are two current heads and the code is `MULTIPLE_HEADS` until the reconciliation list names every current head except `remaining_head`.

Positive, one graph, two gates. Producer writes record `A` and record `B`, which supersedes `A`, under `reports/evidence/G0`, and record `C` of its own task under `reports/evidence/G1`. Two manifests each list only their own files. Consumer E1 validates `B` for the task of `A` and `C` for its task. E3 on the G0 manifest alone does not read the state and does not emit `MANIFEST_UNLISTED` for `C`.

Negative, suffix under evidence. Producer adds, in the same task as `B`, a canonical record `D` in `second.reconciliation.json` under `reports/evidence`, listed in the manifest. Consumer E1 and E2 are not PASS. `D` enters the graph. The finding names the task and `MULTIPLE_HEADS`, or another code of this contract. `D` is not skipped.

## Oracle

The tests contain a reference selector on an abstract graph. It uses the Python standard library only and does not import production code, directly or indirectly. It runs on generated graphs: every class, pairwise combinations of classes, and random graphs with a fixed seed. It also includes the forms of both `NO_GO` verdicts and the cells for directory perimeter, reconciliation suffix, execution-commit collision, depth, and E3 isolation. Mutation probes: removing each new check fails at least one test. The reference selector is the expected result. The production script is the subject, not the oracle. Generated graphs compare that oracle with the production subject. They do not compare the oracle with itself.

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

Inventory measured on the code-branch base `origin/main` `23e6b62c36627de91cb85329b9a1164f3219cd53` with `discover_records` and `select_most_recent` of `scripts/validate_evidence_input_drift.py` on `reports/evidence`, without a filter on `completed_evidence_tasks`, for every existing file this unit changes: `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json`, `.github/workflows/ocor-tooling-bootstrap.yml`, and every `MANIFEST.json` under `reports/evidence` (`G0` through `G6`, and `reports/evidence/G2/blockers/MANIFEST.json`). Thirteen pins, ten current heads. No selected head pins a `MANIFEST.json`. This inventory replaces the pin-set sentences of the contract at `0203a772627b18f6d2caeccfeeecb3848def4229`. `OCOR-DEV-REM-0068-PIN-INVENTORY (2026-11-27)`.

| Task | `record_id` | File | Pin | Disposition |
| --- | --- | --- | --- | --- |
| `OCOR-DEV-0005` | `OCOR-DEV-0005-requalified-rem0069-34a66b063b78` | `scripts/validate_ocor_development_plan.py` | `028861101cb4f6a71af4063ae44bcc5eb58aec6835f5c1975d2dd5afb6677a50` | Regression-only requalification by this unit |
| `OCOR-DEV-0050` | `OCOR-DEV-0050-requalified-rem0069-34a66b063b78` | `scripts/validate_ocor_development_plan.py` | `028861101cb4f6a71af4063ae44bcc5eb58aec6835f5c1975d2dd5afb6677a50` | Regression-only requalification by this unit |
| `OCOR-DEV-0082` | `OCOR-DEV-0082-requalified-rem0069-34a66b063b78` | `scripts/validate_ocor_development_plan.py` | `028861101cb4f6a71af4063ae44bcc5eb58aec6835f5c1975d2dd5afb6677a50` | Regression-only requalification by this unit |
| `OCOR-DEV-REM-0018` | `OCOR-DEV-REM-0018-requalified-fuseki-20261121-dd0467f18816` | `scripts/validate_ocor_development_plan.py` | `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827` | Declared residual. Not requalified by this unit |
| `OCOR-DEV-REM-0022` | `OCOR-DEV-REM-0022-requalified-fuseki-20261121-dd0467f18816` | `scripts/validate_ocor_development_plan.py` | `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827` | Declared residual. Not requalified by this unit |
| `OCOR-DEV-REM-0023` | `OCOR-DEV-REM-0023-requalified-fuseki-20261121-dd0467f18816` | `scripts/validate_ocor_development_plan.py` | `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827` | Declared residual. Not requalified by this unit |
| `OCOR-DEV-REM-0036` | `OCOR-DEV-REM-0036-requalified-rem0059-636975eaacd7` | `scripts/validate_ocor_development_plan.py` | `7bcb652ccbed7d5154d3231b386725dbb31bfe199c5a9ac053977e6828ce196b` | Declared residual. Not requalified by this unit |
| `OCOR-DEV-REM-0037` | `OCOR-DEV-REM-0037-requalified-rem0056-de79d986d7f3` | `scripts/validate_ocor_development_plan.py` | `3c0fb2aaff43a3a71916d286e59b1c3b17597cef0ed1edfde714b034fa3ba4b5` | Declared residual. Not requalified by this unit |
| `OCOR-DEV-REM-0037` | `OCOR-DEV-REM-0037-requalified-rem0056-de79d986d7f3` | `reports/planning/OCOR_PLAN_RUN_STATE.json` | `ae3fde4245d75d6e2cfb0065c326552cdc7404d406e8292fa2bc87f653e39c2c` | Declared residual. Not requalified by this unit |
| `OCOR-DEV-REM-0038` | `OCOR-DEV-REM-0038-requalified-fuseki-20261121-dd0467f18816` | `scripts/validate_ocor_development_plan.py` | `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827` | Declared residual. Not requalified by this unit |
| `OCOR-DEV-REM-0038` | `OCOR-DEV-REM-0038-requalified-fuseki-20261121-dd0467f18816` | `.github/workflows/ocor-tooling-bootstrap.yml` | `674d25652621ca32a06cdb8413ac9b9dda589f069825460242b66e20df39cabe` | Declared residual. Not requalified by this unit |
| `OCOR-DEV-REM-0053` | `OCOR-DEV-REM-0053-requalified-rem0054-ff0508c04e5c` | `scripts/validate_ocor_development_plan.py` | `62661c88b7c864748d0ec8a31b9128dd8b6bb1a5ee7da34259966abdca1e6bf1` | Declared residual. Not requalified by this unit |
| `OCOR-DEV-REM-0053` | `OCOR-DEV-REM-0053-requalified-rem0054-ff0508c04e5c` | `reports/planning/OCOR_PLAN_RUN_STATE.json` | `2cbe44c0bde095c486c1ab24c1e2e21e065744cf084bf9c510b116d89c7f2952` | Declared residual. Not requalified by this unit |

Regression-only requalification paths for the three heads in `completed_evidence_tasks`. On this base those heads pin only `scripts/validate_ocor_development_plan.py`:

- `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0068.json` and `.log`
- `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0068.json` and `.log`
- `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0068.json` and `.log`

Each `supersedes` names the head `select_most_recent` returns on `origin/main` at code-phase merge time. The regression rows apply only while those heads are still selected. If `origin/main` changes before the merge, the inventory is remeasured on the merge result, as are the reconciliation records. If the heads in `completed_evidence_tasks` that pin a changed file are not exactly `OCOR-DEV-0005`, `OCOR-DEV-0050`, and `OCOR-DEV-0082`, stop and open one request. A residual set different from the seven tasks measured here does not stop the unit: the README lists it as measured. For this unit, the regression-only requalifications that follow from the allowlist, in point 2a of REM-0066-CYCLE3-NO-GO (2026-11-24) and in point 4 of that decision's verifier checks, are only those three tasks. The seven residual heads are not requalified here.

Reconciliation, one JSON and one log per completed task, not evidence and not a manifest entry, gate as measured: G0 `0001`–`0006`; G1 `0007`–`0014`; G2 `0015`–`0027` and `0070`–`0084`; G3 `0028`–`0031`; G4 `0032`–`0049`; G5 `0050`–`0059`; G6 `0061`. The path is `reports/assurance/OCOR-DEV-REM-0068-RCCAD/reconciliation/<OCOR-DEV-NNNN>.json` and the same path with `.log`. A range includes every integer in it. That is 75 tasks, 150 paths. None of those paths is under `reports/evidence`. None of those JSON files carries `task_id`.

Existing manifest files `reports/evidence/G0/MANIFEST.json` through `G6/MANIFEST.json` are already allowlisted. The code phase appends entries and does not change an existing entry. `.github/workflows/ocor-tooling-bootstrap.yml` is already allowlisted. The code phase adds one command to the existing drift step: `ocor-runtime/.venv/bin/python scripts/validate_current_evidence_head.py --root .` beside the unchanged drift command at line 125 of this base. No other workflow edit. The proof of `OCOR-DEV-REM-0068-GUARD-ADMISSION (2026-11-27)` stays: absence of the admitted block fails that proof.

## Sequence

This commit closes the two blocking findings of the one design review. It does not request another review. RED, GREEN, the pre-campaign review, the qualifying campaign, and verification come after the replacement unit of FUSEKI-ARCHIVE-COPY-20261123-CYCLE3-NO-GO (2026-11-24) option 1 is on `origin/main`. That replacement is on `origin/main`. This commit is the contract commit of `OCOR-DEV-REM-0068-REDESIGN (2026-11-28)` option 1. Its parent is `83c91b6775dd779d30fee608b26c91f11a808ae3`. It changes only this README. It is not repair cycle 2. RED follows this commit. Until this unit is integrated, no other unit starts a qualifying local campaign. State syncs are outside the pause. The change set at `24633cc9d4c49749bd33a386020fe0d9f6cf5174` receives no further commit and is not merged. There is no cycle 4 of `OCOR-DEV-REM-0066` and no cycle 4 of that change set. Candidate `3b2ee600ee5d9e3055e3d916628d958635fefff3` is not modified. `vf004_schema_conformance` stays `NOT_CORRECTED` and is not PASS. Claims stay `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC and Production `NO-GO`.
