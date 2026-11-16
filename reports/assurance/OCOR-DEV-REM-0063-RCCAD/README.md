# OCOR-DEV-REM-0063

MCP profile for FABLE52-POST-POC-PROGRAMME (2026-11-11) point 1.
Protocol revision 2026-07-28. The Tool Contract schema in ADD v1.3 section 3.5 is unchanged.
FR-047, FR-169 and NFR-022 are not verified by this unit; OCOR-DEV-0065 verifies them.
Claims stay E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC NO-GO, Production NO-GO.

The cycle-2 decoder commit is `3dd37e29222ae2c85f400f4fc7573def127f6a53`.
The class-coverage execution commit is `a284c11238063760c471d80cd9e0f7b6c957e42b`.
This record supersedes `OCOR-DEV-REM-0063-d215c7d2c1dc`.
The four-lane campaign at `c28cd9c411c466f38e9671d2774939bb9a910a30` does not qualify the cycle-2 head.
The qualifying four-lane campaign is `fbe0200c24c0-1794612781` on `fbe0200c24c07340b67430a3b0a24a3cac65ba82`: 6014 tests, 0 failures, 0 errors, 0 skipped, 1719.366 s, MAINS.
The class-coverage pre-campaign gate ran on `a284c11238063760c471d80cd9e0f7b6c957e42b`: 51 PASS, 6 NOT_EXECUTED, 97.897 s.
The same gate ran on the evidence commit `a756fb9faf6860d218096d39fb10678dc9135b08`: 51 PASS, 6 NOT_EXECUTED, 99.195 s.
The gate on the campaign head `fbe0200c24c07340b67430a3b0a24a3cac65ba82` is 51 PASS, 6 NOT_EXECUTED, 98.198 s. That log was pre-campaign.log for cycle 2. Its bytes remain at `aec75cd69010a29fe0997cd3dd15e5c89c639633`. Cycle 3 replaced the working-tree file.
The evidence commits do not change the execution-commit inputs.
The plan validator is unchanged, so the regression requalifications stay on their declared commit.

Preventive review OCOR-DEV-REM-0063-9dc963f40644-pre found that the malformed-fragment rows do not plant the undecoded token, so they pass on the resolver before the decoder. The class-coverage tests at a284c11238063760c471d80cd9e0f7b6c957e42b plant that key. The cycle-2 red.log keeps the previous RED as a byte prefix (sha256 67868a1e29c59e4e42c5197874e15d89c2e3f0094c97b35c8d1dcbabbb511bec) and appends the planted-key RED and the identity-decode mutation. Those bytes remain at `aec75cd69010a29fe0997cd3dd15e5c89c639633`. GREEN of that cycle is 188 passed. The four-lane campaign at c28cd9c411c466f38e9671d2774939bb9a910a30 does not qualify the cycle-2 head. The qualifying cycle-2 campaign is fbe0200c24c0-1794612781, and it does not qualify the cycle-3 head.

Cycle 3 code and tests are `aec75cd69010a29fe0997cd3dd15e5c89c639633`. RED `51a3b58ecda1e52aaab47c97269e45170562a6c1` on `19f63aeec7d16c7d329aff3421415bcb5e5dd43a`: 46 failed, 42 passed, 188 deselected. GREEN of the task module: 276 passed. The qualifying four-lane campaign is `aec75cd69010-1794649854`: 6102 tests, 0 failures, 0 errors, 0 skipped, 1674.782 s, MAINS. `fbe0200c24c0-1794612781` qualified cycle 2 and does not qualify this head. VF-004 is not closed by this suite. Claims stay E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC NO-GO, Production NO-GO.

Cycle 4 code is `d849a827fae51d56e371357812b453a7082d4e59`. RED `0914a61bcb78b0e1710b9fbc43df205450921005`: 22 failed, 6 passed, 293 deselected. GREEN of the task module: 321 passed. The qualifying four-lane campaign is `d849a827fae5-1794672102`: 6147 tests, 0 failures, 0 errors, 0 skipped, 1748.014 s, MAINS. `aec75cd69010-1794649854` qualified cycle 3 and does not qualify this head. Preventive review `OCOR-DEV-REM-0063-fed65a3b0b8f-pre` returned BLOCKING_FINDINGS. The blocking rows were fixed in the code commit above. No second preventive review was requested. The gate on this head is 51 PASS, 0 failed, 6 NOT_EXECUTED. Claims stay E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC NO-GO, Production NO-GO.

Cycle 5 code is `3305ab4cf85ea8aabca0aad58c3d3ff60c770306`. RED `b3a0b5c0fa9fcef6b3189959cfd589a349515316` of the new tests: 4 failed, 1 passed. GREEN of the task module: 431 passed. Oracle referencing 0.37.0, 105 generated cases, result PASS. The qualifying four-lane campaign is `3305ab4cf85e-1794700091`: 6257 tests, 0 failures, 0 errors, 0 skipped, 1656.782 s, MAINS. `d849a827fae5-1794672102` qualified cycle 4 and does not qualify this head. Preventive review `OCOR-DEV-REM-0063-3305ab4cf85e-pre` returned NO_BLOCKING_FINDINGS. The one advisory was evidence-only and this record is regenerated on this head. No second preventive review was requested. The gate on this head is 51 PASS, 0 failed, 6 NOT_EXECUTED. The distinct check `3305ab4cf85e-1794701778` passed: 410 tests, exact union, empty residue. Claims stay E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC NO-GO, Production NO-GO.

Cycle 6 code is `265f6ad2ced262999bd23c35c9dea3fc94caf988`. RED of the cycle-6 tests on `2018893ae8f37a9a6428c8c2b785055c763bbeec` before the production edit: 76 failed, 293 passed. GREEN of the task module: 800 passed. Oracle referencing 0.37.0, 240 generated cases, result PASS. The qualifying four-lane campaign is `265f6ad2ced2-1794717879`: 6626 tests, 0 failures, 0 errors, 0 skipped, 1642.715 s, MAINS. `3305ab4cf85e-1794700091` qualified cycle 5 and does not qualify this head. Preventive review `OCOR-DEV-REM-0063-2018893ae8f3-pre` returned BLOCKING_FINDINGS. P1, P2 and P3 are fixed on this head. P4 is the inventory realignment in this record. No second preventive review was requested. The gate on this head is 51 PASS, 0 failed, 6 NOT_EXECUTED. The distinct check `265f6ad2ced2-1794719545` passed: 410 tests, exact union, empty residue. Claims stay E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC NO-GO, Production NO-GO.

Cycle 7 code is `0c8bf777f363fffc42234d14b239e4f0b0a8e652`. Every `$ref` is resolved by referencing 0.37.0 with DRAFT202012, the current resource and base URI; the manual resolver is removed. RED of the cycle-7 tests on `d70920ea901ffa5b06b2c28fd1fdd785b2f7b125` before the production edit: 39 failed, 33 passed. GREEN of the task module: 934 passed, three consecutive runs. Oracle referencing 0.37.0: 36 differential cases and 32 empty-pointer cases, result PASS. The qualifying serial campaign is `0c8bf777f363-1794742597`: 6760 tests, 0 failures, 0 errors, 0 skipped, 4267.300933112041 s, SERIAL_FALLBACK, exact JUnit/collection union. Power state was not recorded. `265f6ad2ced2-1794717879` qualified cycle 6 and does not qualify this head. Preventive review `OCOR-DEV-REM-0063-baef056e5bf6-pre` returned BLOCKING_FINDINGS. The blocking findings are fixed on this head. No second preventive review was requested. The gate on this head is 51 PASS, 0 failed, 6 NOT_EXECUTED. The distinct check `0c8bf777f363-1794746955` passed: 410 tests, exact union, empty residue. Implementers: Grok Build, grok-4.7, xAI (original and cycles 1-6); Codex CLI, deepseek-flash, DeepSeek (cycle 7). Preventive reviewer cycle 7: Claude Code, claude-fable-5-2, Anthropic. Final verifier: Codex, OpenAI, separate context. Claims stay E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC NO-GO, Production NO-GO.

Cycle 8 code is `8a4893df052b04f3e357490e1e83c64288bb5603` with the RED, GREEN and pre-campaign logs at `f72a324e25ed72fd58f688bf365058bc40555f11`; the preventive review `OCOR-DEV-REM-0063-5356e0d3eb7b-pre` returned BLOCKING_FINDINGS (P1-P3 blocking, P4-P9 advisory) and the repair head is `271bdaf561ab99a6b8b96c58f067f6aa096b6f2f`. VF-001 of `OCOR-DEV-REM-0063-07eb4fd2040b-7` is closed: every embedded tool schema gets its own local registry keyed by the effective base, so a no-op `$id` reached through const/default/examples keeps the embedded resource, the document fallback survives and the documented ambiguity check stays active; the anchor crawl (P1) and the repeated nested `$id` across schema trees (P2) now follow referencing 0.37.0 as well. RED of the cycle-8 tests on `07eb4fd2040b4081f577c80dcfb1641d09a4da7c` before the production edit: 60 failed, 96 passed, 934 deselected. RED of the anchor repair on `5356e0d3eb7b7168192afec98ea7685f00f641bb` before the production edit: 38 failed, 18 passed, 1090 deselected. GREEN of the task module on the repair head: 1146 passed, three consecutive runs. Oracle referencing 0.37.0: 104 generated cases query the pinned library (48 of the local matrix, 56 of the anchor and repeated-`$id` matrices), result PASS; the outer and ambiguous matrices (96 cases) and the 12 missing-target cases assert profile rules without calling the library. The qualifying serial campaign is `f72a324e25ed-1794759063`: 6916 tests, 0 failures, 0 errors, 0 skipped, 3985.283470831986 s, SERIAL_FALLBACK, exact JUnit/collection union, power not recorded by the serial runner; it qualified the pre-repair head only, and a new qualifying campaign and distinct check are required on the repair head after the new preventive review. `0c8bf777f363-1794742597` qualified cycle 7 and does not qualify this head. The distinct check `f72a324e25ed-1794763318` passed: 410 tests, exact union, empty residue; the anonymous-pull rate-limit reading for that execution was not performed and the deficit is recorded in the record instead of fabricated. VF-002 is NOT closed: the explicit gate `git diff --check <base>..<head>` exits 2 because the pinned byte-exact official fixture schema.json ends with a blank line at EOF (schema.json:3963: new blank line at EOF.); the committed red.log strips the trailing whitespace of the pytest progress lines and the raw bytes are preserved content-addressed at `~/.ocor-codex/rem-0063/preserved/8a4893df052b/red.log.cycle8.raw` (sha256 `6ae5073a2a67fd062c4314618f9fe0cd8144e70f2a63cda9cdcbaf3258a1d3c7`); the real gate outcome is recorded without claiming it green. Implementers: Grok Build, grok-4.7, xAI (original and cycles 1-6); Codex CLI, deepseek-flash, DeepSeek (cycle 7); Codex CLI, deepseek-v4-pro, DeepSeek (cycle 8). Preventive reviewer cycle 8: Claude Code, claude-fable-5-2, Anthropic (per REM-0063-CYCLE7-NO-GO point 4). Final verifier: Codex, OpenAI, separate context. Claims stay E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC NO-GO, Production NO-GO.

Cycle 8 prereview-fix code is `edfe829322d57875c2bd0685a50f9710b4636726`, closing P1, P2 and P3 of the preventive review `OCOR-DEV-REM-0063-e2efce6f3dfa-pre` (BLOCKING_FINDINGS on the repair head `271bdaf561ab99a6b8b96c58f067f6aa096b6f2f`). RED of the prereview-fix tests on `e2efce6f3dfa996dada7374694cf7b20719cd7b5` before the production edit: 102 failed, 134 passed, 934 deselected, with the library-order failure `[props_first-b_first]`; the raw bytes are preserved content-addressed at `~/.ocor-codex/rem-0063/preserved/edfe829/red.log.cycle8-prereview.raw` (sha256 `84b2f853ab6370d0f3ebba7f560ed08fcbff6550e70df400934aa85ffaba1d79`). GREEN of the task module on the fix head: 1170 passed, three consecutive runs (raw logs sha256 `f6aac01a7fdcb919e356551cf7a6bc4c789a57787807ba5ae8ddb12f04e71d42`, `e7f536fceda69ff056d22cb66cd2c7c0400485e54146da12487789d2fe5ade72`, `7747cda9e9d64aa82397e12b1fc8cdcf1dfc46a70444b66b03cba8a45a3aeac9`). The cycle-6/cycle-7 regression selection on the same head passes 503 tests; the REM-0047 task module passes 25 tests. Oracle referencing 0.37.0: 112 differential cases (48 no-op `$id` reached through const/default/examples, 56 anchor and repeated-`$id`, 8 pointer/anchor member orders), result PASS. P4 (advisory) is OPEN_PO_DECISION_REQUIRED: the explicit gate `git diff --check <base>..<head>` exits 2 because the pinned byte-exact official fixture `ocor-runtime/tests/fixtures/mcp/2026-07-28/schema.json` ends with a blank line at EOF, kept byte-exact per DEPENDENCY.md; the real gate outcome is recorded and never declared green. P5 (advisory) is FIXED_RECORD. The new preventive review on this head is PENDING; a new qualifying campaign and distinct check are required on this head after the review. Implementers: Grok Build, grok-4.7, xAI (original and cycles 1-6); Codex CLI, deepseek-flash, DeepSeek (cycle 7); Codex CLI, deepseek-v4-pro, DeepSeek (cycle 8). Preventive reviewer: Claude Code, claude-fable-5-2, Anthropic. Final verifier: Codex, OpenAI, separate context. Claims stay E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC NO-GO, Production NO-GO.

## Cycle 10 contract

Phase A, second contract review. Production remains byte-identical to
`f485dc964e47bde83842ecd5ba2627d8342612f9`. This derived contract implements
**REM-0063-CICLO-10-CONTRATTO (2026-11-16)**, points 1–3; it closes no production
finding. Codex (`gpt-6.1-sol`, OpenAI, effort `max`) owns cycle 10. Earlier
implementers remain Grok Build (`grok-4.7`, xAI) and Codex CLI
(`deepseek-flash`, `deepseek-v4-pro`, DeepSeek). The assigned contract reviewer
is Claude Code (`claude-fable-5-2`, Anthropic, effort `max`), launched by the loop.

### Producer and consumer obligations

Every emitted `inputSchema` and `outputSchema` is an autonomous JSON Schema
2020-12 resource: its registry contains that schema and its contained resources
only. Its base is its declared `$id`, otherwise the fixed URI for its tool and
field. No lookup falls back to the descriptor, another field, another tool or
network retrieval. Sources: **MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)**, points 1–2.
An empty URI fragment is normalised by the library's registry rules; the schema
bytes and reference spelling are never rewritten for the oracle.

The generator includes all and only transitively reachable IR definitions in
each resource's `$defs`, with `#/$defs/<Name>` references. Unreachable user
`$defs` are omitted. A same-name/different-content definition is a typed error.
The descriptor has no top-level `$defs`; the profile rejects that form.
Input generation preserves `without_context_overwrite`. Repeated generation
is byte-identical. Sources: **MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15)**,
points 1–3. Existing generator refusal of two distinct resource roots claiming
one URI remains `C1Error`/`DUPLICATE_RESOURCE` (`codegen.py::_mcp_iter_resources`);
it is stricter than the profile's library-selected resource winner. This is an
existing restriction, not a new acceptance rule. Both sibling orders and repeated
ancestor/descendant IDs are covered. **SELF-CHECK-ORACOLO (2026-11-14)**, point 2,
permits a documented stricter rule; no new restriction is introduced here.

Successful public generation must return bytes which pass the public profile,
`Draft202012Validator.check_schema`, and unmodified `referencing` 0.37.0 on each
schema alone. An unresolvable closure is `C1Error`/`UNRESOLVED_REFERENCE` before
artefacts are returned. A fixed no-ID base colliding with a declared `$id` is
refused by both producer (`C1Error`/`TYPE_ERROR`) and consumer (`McpProfileError`),
without suffix selection. This applies to both fields and origins. Sources:
**REM-0063-CICLO-10-CONTRATTO**, point 2; **REM-0063-CYCLE10-ORACLE-CONFLICT
(2026-11-16)**, A1 and B1, including B1's producer/consumer agreement.

The profile validates each tool against the pinned official `Tool` definition,
then schema, dialect, keyword and reference rules on each schema alone. A missing
or non-schema target is a typed refusal; ambiguous anchors retain the stricter
rule already documented in `mcp_profile.py::_reject_ambiguous_anchor`. Canonical
array-index restrictions remain unchanged. Percent-encoded anchors and an encoded
leading slash follow the unchanged libraries, without helper substitutions:
**REM-0063-CYCLE10-ORACLE-CONFLICT**, A1. Existing tests are preserved in phase A;
only its enumerated realignments may occur in phase B.

The current module restricts references to fragments. Whether an URI naming a
contained resource also counts as internal is **open question Q3**, not decided
here. Matrix cells for that spelling retain the current refusal conditionally;
their library resolution outcome is recorded separately. No retrieval is ever
allowed. Sources of the question: **MCP-TOOL-SCHEMA-AUTONOMO**, points 1–2;
**REM-0063-CYCLE7-NO-GO (2026-11-15)**, point 2; the current module's stricter rule.

Final bounds are 4096 JSON values and depth 32, measured on the final descriptor
after closure; root counts as one, keys do not count, scalars/arrays/objects do.
At 4097 or depth 33 the generator raises `C1Error`, and the profile raises
`McpProfileError`; direct and transitive type growth counts. No bounds change.
Sources: **REM-0063-CICLO-10-CONTRATTO**, point 2 and VF-002; **REM-0063-CYCLE7-NO-GO**,
point 2. Tests check boundary reasons as well as typed errors.

Profile and generator separately compute resource/base identities and closure.
Agreement is proved through both public paths across the products below, with
one independent library oracle, exact expected closure trees, accepted/rejected
instance twins and repeated render bytes. Neither expected targets nor expected
answers use a production helper. Sharing a production helper remains optional
within the authorised scope (**REM-0063-CICLO-10-CONTRATTO**, point 2).

### Deterministic case matrix

| Dimension | Values |
| --- | --- |
| Field | `inputSchema`, `outputSchema` |
| Root | no ID, absolute ID, relative ID; trailing/empty fragment in oracle controls |
| Outer ID and inner ID, independently | absent, empty, `#`, same relative, same absolute, new relative, new absolute, repeated URI |
| Reference | `#`, pointer, anchor, percent segment/leading slash/anchor, contained-resource URI; child/parent/root-only target, missing anchor |
| Target | present, missing, invalid schema; duplicate anchor; foreign field/tool/descriptor |
| Position | `properties`, `$defs`, `allOf`, `const`, `default`, `examples` |
| Duplicate order | holder first, shadow first; ancestor/descendant repeated IDs |
| Origin | delivered; public compiler and generator |
| Closure | direct enum, transitive struct → enum; unused sibling absent/present |
| Tokens and bounds | `~0`, `~1`, malformed escape, percent non-ASCII, index 2/02; 4096/4097, depth 32/33 |

The original 5790 cells remain: delivered product 5184, generated product 576,
boundaries/collision 30. New products: two-level delivered 18432 (2×3×8×8×6×8),
two-level generated 4608 (2×3×8×8×6×2), sibling orders 288, form/target state 216,
foreign-target isolation 108, anchor ambiguity 48, token product 144,
both-origin collisions 4, library-state controls 24, positive root-fragment twins 12,
and generated duplicate orders 72. Total: **29746** cases.
Every listed product is fully enumerated without sampling. The following are
the complete exclusions and aliases; they are not omitted cells disguised as PASS:

- G1: OaC permits IR-symbol references, not arbitrary raw fragment spellings.
  Generated-origin reference spellings other than the generated pointer are
  excluded (4608 cells in the original theoretical product). Delivered products
  exercise those spellings, target states, isolation and token grammar.
- G2: a `$defs/target` with no incoming OaC reference is unreachable and omitted.
  Generated tests assert its absence; delivered cells explicitly select it.
- G3: the two-level generated product varies direct/transitive reachability;
  unused-sibling variation stays in the original generated product. Sibling
  insertion order has separate delivered and generated products; the generator
  retains its typed duplicate-URI refusal, without choosing a library winner.
- I1: same-relative/absolute representatives with no corresponding declared
  root use `#`; repeated-URI values intentionally alias the absolute child URI.
  The independent product includes both equal ancestor/descendant IDs and
  same-resource children below new resources. Fixed-base collisions are separate
  products for **both** origins, not excluded from generator agreement.
- V1: cyclic `allOf/$ref:'#'` may not terminate instance validation. These cells
  assert schema validity and library resolution only; instance execution is
  explicitly `NOT_EXECUTED` on `RecursionError`, never called a passing instance.
  All nonrecursive entry probes evaluate `entry` with the same resolver/base.

The oracle uses only `Resource.subresources`, `Resolver.in_subresource` and
`Resolver.lookup` for traversal/resolution. Its visited state includes the library
registry's resources, uncrawled set and anchors: an anchor-induced crawl cannot
reuse a stale answer. `Draft202012Validator` really reaches `entry`, with the
same base and unmodified schema. Generated cells also compare the entire emitted
closure, every other emitted field, positive `ACTIVE` and negative `WRONG`
instances where a target is emitted. Ordinary instance-validation errors are
not resolution errors; no missing target is accepted on their basis.

### Decisions, questions and stopping conditions

Q1/Q2 are decided by **REM-0063-CYCLE10-ORACLE-CONFLICT (2026-11-16)**: A1+B1.
Their original RED remains historical; newly enumerated RED outcomes are recorded
by reason and family. No phase-A change to a pre-cycle-10 test, fixture or oracle is
permitted. Phase B applies only the realignments expressly listed in that decision.

Q3 is **REM-0063-CYCLE10-INTERNAL-RESOURCE-URI**, raised after the first contract
review identified a conflict between the module restriction and the wording of
the standalone-resource decisions. Its disposition is required before dependent
production changes or a full campaign. Neither the first nor second contract
review can choose that normative interpretation.

The fixed official fixture remains byte-identical. **REM-0063-PINNED-FIXTURE-DIFF-CHECK
(2026-11-16)** adopts option 1: its whitespace check remains `NOT_GREEN` with
an explicitly recorded exception, never PASS; other files keep the same check.
No production repair or full campaign has started. Claim fence unchanged:
E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC and Production NO-GO.
