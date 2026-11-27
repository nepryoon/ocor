# OCOR-DEV-REM-0069 — governed Fuseki archive copy

Design contract for the unit that replaces change set `FUSEKI-ARCHIVE-COPY-20261123`. Authority: FUSEKI-ARCHIVE-COPY-20261123-CYCLE3-NO-GO (2026-11-24) option 1, points 1–6, decided by the Product Owner in person in the handwritten section. This file is that contract. It contains no production acquisition code. The two acquisition blobs are not copied in this commit.

Candidate `24633cc9d4c49749bd33a386020fe0d9f6cf5174` receives no commit and is not merged. This is not a cycle 4. Candidate `3b2ee600ee5d9e3055e3d916628d958635fefff3` is not modified and is not merged. No code branch of `OCOR-DEV-REM-0068` or `OCOR-DEV-REM-0067` starts until this unit is on `origin/main`. No qualifying campaign of `OCOR-DEV-REM-0068` starts. Claims stay `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC and Production `NO-GO`.

## Identifier

Measured read-only immediately before this commit, on `origin/main` `618e72c00f994e8ea8899914548cc38743aa4569`:

- `git grep -h -o -E 'OCOR-DEV-REM-[0-9]{4}' origin/main | sort -u | tail -n 1` prints `OCOR-DEV-REM-0066`.
- Remote branch names, case-insensitive, top out at `OCOR-DEV-REM-0068` (`governed/ocor-dev-rem-0068-current-head-contract`). `OCOR-DEV-REM-0067` is the published Fuseki CI-label contract. Neither identifier is filled as a hole, and neither is this unit.

The first identifier absent from `origin/main` content and from remote branch names is `OCOR-DEV-REM-0069`.

## Replacement

This unit takes the place of `FUSEKI-ARCHIVE-COPY-20261123` in every governing decision that names that change set, including CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23), FUSEKI-ARCHIVE-COPY-20261123-CYCLE2-NO-GO (2026-11-24), and REM-0066-CYCLE3-NO-GO (2026-11-24).

- Point 1a of REM-0066-CYCLE3-NO-GO applies here: the four-lane qualifying campaign of this unit is not subject to point 1d (the pause on other units' qualifying campaigns until the CONFINE-G6 point-4 unit is integrated).
- Where a decision requires `FUSEKI-ARCHIVE-COPY-20261123` to be on `origin/main`, the condition is that this unit is on `origin/main`.
- The governed copy, the source order, the requalifications, and the single CI attempt after `GO_FOR_EVIDENCE_SEAL` from CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 apply to this unit.

## Frozen acquisition blobs

The code phase copies these blobs from the rejected change set without changing their behaviour. It does not edit them.

| Path | Git blob | sha256 |
| --- | --- | --- |
| `scripts/acquire_fuseki_archive.py` | `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded` | `c25d013922a86a402e5a6131779a0375c5260ae9bff8b950b505874c8c0c3848` |
| `reports/tests/test_fuseki_archive_acquisition.py` | `dee2ca8813565043b20798a634743edcf0fd5f20` | `9bb58c5880f05b8e0275ce06db97ac4f86ea12e759186aed0edbdfbe7cdd4ce9` |

On this base the same paths are different blobs (`c7a8651775d32147c3d6b04c08b16f816f5571ce`, sha256 `8ec95e9842f765f10d827130927334bc679ec5d6c0b8384eb4e6e63754140c43`, and `15a4241e788ff8e83d5ec1cb4aa9bb984b27952c`, sha256 `963d1624508c675d6b2c1fbc48f23818e4a39635e2fd2f806188465498033c4b`). Both path strings are already in `extension_paths`. This commit does not change them.

If the code phase needs a production file other than those two, plus the records, manifests, and logs the process already provides, and plus the allowlist exception below, stop and open one decision request.

## Producer to consumer

Producer: `scripts/acquire_fuseki_archive.py` asks the governed copy first, anonymously, at `https://github.com/nepryoon/ocor/releases/download/mirror-apache-jena-fuseki-6.2.0/apache-jena-fuseki-6.2.0.tar.gz`. It accepts only an HTTPS redirect to `release-assets.githubusercontent.com`. It verifies SHA-512 `ba65f5867d2d4741b2ed9e2af5a0d4fbb447909894ab2a0c6bc4dac8997f4fe339c87b13c48d45d054977769f0f8bf763ea346b1f7792d5cdc458041bd43a132`. Only then does it try the three Apache sources, `archive.apache.org` last. The 600-second budget and its existing split stay. No token, credential, or authorization header is sent.

Consumer: the current-proof record names the qualified commit. In `inputs` it names the two digests `c25d013922a86a402e5a6131779a0375c5260ae9bff8b950b505874c8c0c3848` and `9bb58c5880f05b8e0275ce06db97ac4f86ea12e759186aed0edbdfbe7cdd4ce9`. The historical digests `23046a9cc08a6b6dadc5a6aadd0e404b60bbe5014dbb205fea4f7906825eccef` and `b24a30f630942f151d7e4697eeb91c70b4f87fc06ab528d71c3b5472f656b073` stay in a named historical block. They are not the current proof.

## Proof table

Point 2 replaces the plan-state row of option 1. The diff of `reports/planning/OCOR_PLAN_RUN_STATE.json` against `origin/main` is the validator digest string only. It is not the 23 entries of FUSEKI-ARCHIVE-COPY-20261123-CYCLE2-NO-GO point 1.

Before `verify_request.json`, the code phase runs every row on the final HEAD and records in the unit JSON the command, the outcome, and the sha256 of each output. If a row is not run or does not pass, do not write `verify_request.json`. This commit does not run the table and does not write `verify_request.json`.

| Criterion | Proof |
| --- | --- |
| Candidate `24633cc9d4c49749bd33a386020fe0d9f6cf5174` is unchanged and not merged | `git rev-parse` of `governed/fuseki-archive-copy-20261123` and no merge on `origin/main` |
| The two acquisition blobs stay the blobs cited above | `git rev-parse` of the two paths equals `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded` and `dee2ca8813565043b20798a634743edcf0fd5f20` |
| Plan state changes only in the authorized digest string | diff against `origin/main` is that one hex substitution; the file is not reserialized |
| `exit_file_absent` is false when the exit file exists and contains `1` | record read on `guards`, `mermaid`, and `plan`, distinct from the first-attempt log |
| Root `code_commit` and `inputs` of the current proof are the qualified code | sha256 of the two files at the proof HEAD; historical digests in a named block |
| The role scan names the scanned HEAD (VF-005) | scanned-HEAD field in the record |
| VF-004 stays `NOT_CORRECTED` and is not `PASS` | the same pre-existing FAIL: `reports/tests/test_schema_conformance.py` is 97 PASS and 1 FAIL on `CANONICAL_COMMIT` R1 without Human Gate, expected `REJECT`, got `ACCEPT`; not marked `PASS` |
| New campaign on the unit HEAD, zero skips | campaign counts and the union check |
| One verification, verifier from a vendor other than xAI, not started by the implementer | verdict on the exact HEAD |

The campaign already run on `9b27e16cf810f7cf6c11ecd76b53b84b63668ed2` does not transfer. One four-lane campaign on the unit HEAD, then one verification. After a `NO_GO` of this unit, one new decision request only. No cycle 4 on `24633cc9d4c49749bd33a386020fe0d9f6cf5174`.

`scripts/validate_ocor_development_plan.py` rewrites `reports/planning/OCOR_PLAN_RUN_STATE.json` with `json.dumps(..., ensure_ascii=False)`. That rewrite is the cycle-3 VF-001 failure. The code phase patches only the digest hex in place. After any gate that runs the validator, restore the file and re-apply only that substitution. Every other byte stays identical to `origin/main`. The digest on this base, before this commit, is `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827`. This commit replaces that string with the sha256 of the allowlisted validator and changes nothing else in the file.

## Paths and allowlist

Point 2, before code. The closed set below replaces the 23 entries. Only these new entries, and the digest update, are admitted in `scripts/validate_ocor_development_plan.py` and `reports/planning/OCOR_PLAN_RUN_STATE.json`. No other line of either file changes. The allowlist stays an evidence input. This contract does not remove it and does not move it.

Already allowlisted, or planning paths, so they need no new entry:

- `scripts/acquire_fuseki_archive.py`
- `reports/tests/test_fuseki_archive_acquisition.py`
- `reports/evidence/G0/MANIFEST.json`, `reports/evidence/G2/MANIFEST.json`, `reports/evidence/G5/MANIFEST.json` (surgical updates only; no existing entry changes; G4 is not touched)
- `scripts/validate_ocor_development_plan.py` and `reports/planning/OCOR_PLAN_RUN_STATE.json`

New entries inserted in this commit. This commit creates only the README. The other files are created later. The code phase does not add a further allowlist entry. If a path outside this list is required, stop and open one decision request.

- `reports/assurance/OCOR-DEV-REM-0069-RCCAD/README.md`
- `reports/assurance/OCOR-DEV-REM-0069-RCCAD/OCOR-DEV-REM-0069.json`
- `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0069.json` and `.log`
- `reports/evidence/G2/OCOR-DEV-0072.requalified-rem0069.json` and `.log`
- `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0069.json` and `.log`
- `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0069.json` and `.log`

The unit record is the JSON file. Proof command, outcome, and output sha256 go in that JSON. There is no separate unit log in the repository. `reports/development/ITERATION_LOG.md` is not edited on this branch. No campaign raw log is a repository path. No G4 record is created. The rejected requalifications of `OCOR-DEV-REM-0018`, `OCOR-DEV-REM-0022`, `OCOR-DEV-REM-0023`, `OCOR-DEV-REM-0036`, `OCOR-DEV-REM-0037`, `OCOR-DEV-REM-0038`, and `OCOR-DEV-REM-0053` are not carried as new records. Their current heads are part of the inventory of pins of `scripts/validate_ocor_development_plan.py` on this base. `OCOR-DEV-REM-0018`, `OCOR-DEV-REM-0022`, `OCOR-DEV-REM-0023`, and `OCOR-DEV-REM-0038` remain pinned to `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827`, without a successor, as a residual accepted by `OCOR-DEV-REM-0069-INVENTORY-NO-GO (2026-11-26)`. `OCOR-DEV-REM-0036`, `OCOR-DEV-REM-0037`, and `OCOR-DEV-REM-0053` already pinned a different digest before this unit.

## Requalifications

Inventory of the pins of `scripts/validate_ocor_development_plan.py` on this candidate, using `select_most_recent` in `scripts/validate_evidence_input_drift.py` on `reports/evidence`, without a filter on `completed_evidence_tasks`. A prior scan of nine tasks does not replace it. Ten current heads pin that script. Heads outside `completed_evidence_tasks` are part of this inventory.

The `OCOR-DEV-0072` row is unchanged. It pins `scripts/acquire_fuseki_archive.py`, not the plan script:

| Task | Gate | `record_id` named by `supersedes` | Pinned file |
| --- | --- | --- | --- |
| `OCOR-DEV-0072` | G2 | `OCOR-DEV-0072-requalified-rem0038-36e61515552d` | `scripts/acquire_fuseki_archive.py` |

| Task | Current head `record_id` | Pin of `scripts/validate_ocor_development_plan.py` | Disposition |
| --- | --- | --- | --- |
| `OCOR-DEV-0005` | `OCOR-DEV-0005-requalified-rem0069-34a66b063b78` | `028861101cb4f6a71af4063ae44bcc5eb58aec6835f5c1975d2dd5afb6677a50` | Requalified by this unit |
| `OCOR-DEV-0050` | `OCOR-DEV-0050-requalified-rem0069-34a66b063b78` | `028861101cb4f6a71af4063ae44bcc5eb58aec6835f5c1975d2dd5afb6677a50` | Requalified by this unit |
| `OCOR-DEV-0082` | `OCOR-DEV-0082-requalified-rem0069-34a66b063b78` | `028861101cb4f6a71af4063ae44bcc5eb58aec6835f5c1975d2dd5afb6677a50` | Requalified by this unit |
| `OCOR-DEV-REM-0018` | `OCOR-DEV-REM-0018-requalified-fuseki-20261121-dd0467f18816` | `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827` | Remains pinned to `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827`, without a successor, as a residual accepted by `OCOR-DEV-REM-0069-INVENTORY-NO-GO (2026-11-26)` |
| `OCOR-DEV-REM-0022` | `OCOR-DEV-REM-0022-requalified-fuseki-20261121-dd0467f18816` | `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827` | Remains pinned to `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827`, without a successor, as a residual accepted by `OCOR-DEV-REM-0069-INVENTORY-NO-GO (2026-11-26)` |
| `OCOR-DEV-REM-0023` | `OCOR-DEV-REM-0023-requalified-fuseki-20261121-dd0467f18816` | `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827` | Remains pinned to `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827`, without a successor, as a residual accepted by `OCOR-DEV-REM-0069-INVENTORY-NO-GO (2026-11-26)` |
| `OCOR-DEV-REM-0038` | `OCOR-DEV-REM-0038-requalified-fuseki-20261121-dd0467f18816` | `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827` | Remains pinned to `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827`, without a successor, as a residual accepted by `OCOR-DEV-REM-0069-INVENTORY-NO-GO (2026-11-26)` |
| `OCOR-DEV-REM-0036` | `OCOR-DEV-REM-0036-requalified-rem0059-636975eaacd7` | `7bcb652ccbed7d5154d3231b386725dbb31bfe199c5a9ac053977e6828ce196b` | Pin already different from the base before this unit |
| `OCOR-DEV-REM-0037` | `OCOR-DEV-REM-0037-requalified-rem0056-de79d986d7f3` | `3c0fb2aaff43a3a71916d286e59b1c3b17597cef0ed1edfde714b034fa3ba4b5` | Pin already different from the base before this unit |
| `OCOR-DEV-REM-0053` | `OCOR-DEV-REM-0053-requalified-rem0054-ff0508c04e5c` | `62661c88b7c864748d0ec8a31b9128dd8b6bb1a5ee7da34259966abdca1e6bf1` | Pin already different from the base before this unit |

No selected head pins `reports/tests/test_fuseki_archive_acquisition.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json`, or any `MANIFEST.json`. The four requalification identities `OCOR-DEV-0005-requalified-fuseki-20261121-dd0467f18816`, `OCOR-DEV-0050-requalified-fuseki-20261121-dd0467f18816`, `OCOR-DEV-0072-requalified-rem0038-36e61515552d`, and `OCOR-DEV-0082-requalified-fuseki-20261121-dd0467f18816` are `record_id` values. `supersedes` names that identity and does not name the new record. Four tasks, including `OCOR-DEV-0050`, is more than three. CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 point 4, which point 1c of this decision applies here, already authorises those substantial requalifications. No sealed record is rewritten.

The code phase remeasures on the `origin/main` from which it merges. If that main has moved, the affected records are redone on the newly selected head. If the pin set of `scripts/validate_ocor_development_plan.py` is not exactly these ten tasks, stop and open one decision request.

Head counts on this base, same selector: 22 tasks have more than one current head, and 5 groups have two or more successors of the same predecessor (`OCOR-DEV-0049` one group, `OCOR-DEV-0050` three groups, `OCOR-DEV-0075` one group). CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 point 4 says the head counts do not increase. The code phase remeasures both counts before publishing the records. If either count would increase, stop and open one decision request. Do not write `verify_request.json`.

This commit changes the validator and does not requalify. Drift for `OCOR-DEV-0005`, `OCOR-DEV-0050`, and `OCOR-DEV-0082` is therefore expected to fail on this design head. That failure is not a campaign. It is corrected in the later requalification commit, before any `verify_request.json`. `OCOR-DEV-0072` does not drift until the acquisition blob is copied.

## Sequence and roles

This commit requests one design review and then stops. The campaign does not start in the same iteration as that request. After the review: the record and the plan bytes (blobs, requalifications, manifests, proof rows), one four-lane campaign on that HEAD, one distinct check, then `verify_request.json`. No full suite in the review iteration. Estimated cost from option 1: three iterations after this contract (record and plan bytes, campaign, verification).

Implementer of this contract, and producer of the two frozen blobs in cycles 0–3 of the replaced change set: Grok Build, `grok-4.7`, xAI. The preventive reviewer and the verifier are chosen by the loop. The implementer does not start them. The verifier's vendor is not xAI. Cycle-3 verifier of the replaced change set: Codex, OpenAI, model `NOT_EXPOSED_BY_RUNTIME`.

No new `DEC-*`. No edit to `inputs/`, sealed records, gates, thresholds, or claims.
