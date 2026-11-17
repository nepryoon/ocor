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

Phase A, completed after the second and final contract review, stays valid.
Production remains byte-identical to `f485dc964e47bde83842ecd5ba2627d8342612f9`.
This derived contract implements **REM-0063-CICLO-10-CONTRATTO (2026-11-16)**,
points 1–3, and the single-calculation design required by
**REM-0063-CALCOLO-UNICO (2026-11-17)** before any production edit. It closes no
production finding. Codex (`gpt-6.1-sol`, OpenAI, effort `max`) authored phase A
and does not own the cycle-10 code. From **REM-0063-CALCOLO-UNICO (2026-11-17)**
point 1, Grok Build (`grok-4.7`, xAI, effort `xhigh`) owns the code. Earlier
implementers remain Grok Build (`grok-4.7`, xAI) and Codex CLI (`deepseek-flash`,
`deepseek-v4-pro`, DeepSeek). The preventive reviewer is Claude Code
(`claude-fable-5-2`, Anthropic, effort `max`). Final verifier: Claude Code
(`claude-opus-5-5`, Anthropic, effort `max`), assigned by
**VERIFIER-CLAUDE-REM0063 (2026-11-16)**. The PO declares the same-provider,
different-model limit between reviewer and verifier. No implementer is Anthropic.

### Producer and consumer obligations

Every emitted `inputSchema` and `outputSchema` is an autonomous JSON Schema
2020-12 resource. Its registry contains only that schema and its contained
resources. The base follows B1 below: a root `$id` with a non-empty
pre-fragment part, otherwise the fixed tool/field URI. No lookup falls back
to the descriptor, another schema or network retrieval.
The oracle never rewrites schema bytes or reference spellings. Sources:
**MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)**, points 1–2.

The generator includes all and only transitively reachable IR definitions in
each resource's `$defs`, using `#/$defs/<Name>`. Unreachable user definitions are
omitted; a same-name/different-content definition is a typed error. No top-level
`$defs` is emitted or accepted by the profile. `without_context_overwrite` and
byte-identical repeated generation remain mandatory. Sources:
**MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15)**, points 1–3.
The existing producer restriction on distinct resource roots claiming one URI
remains `C1Error`/`DUPLICATE_RESOURCE`; it is stricter than the library-selected
winner. Both orders and repeated ancestor/descendant IDs are covered.

Every emitted descriptor must pass the public profile. Each final schema used
alone must pass `Draft202012Validator.check_schema` and resolve its references
with unmodified `referencing` 0.37.0. An unresolvable closure causes
`C1Error`/`UNRESOLVED_REFERENCE` before artefacts are returned. A fixed base
colliding with a declared ID inside that same schema causes `C1Error`/`TYPE_ERROR`
or `McpProfileError`, without suffix selection. A final empty fragment does not
make a different identity. An equal `$id` in another field, tool or descriptor
metadata is not a collision of this registry (C1). Sources:
**REM-0063-CICLO-10-CONTRATTO**, point 2;
**REM-0063-CYCLE10-ORACLE-CONFLICT (2026-11-16)**, A1+B1;
**REM-0063-CYCLE10-REMAINING-CONTRACT-QUESTIONS (2026-11-17)**, C1.

The profile validates every tool against the pinned official `Tool` definition,
then checks each schema's dialect, keywords and resolved targets. Missing or
non-schema targets cause typed refusal. Existing ambiguous-anchor and canonical
array-index restrictions remain. Percent-encoded anchors and the encoded leading
slash follow the original libraries, without helper substitutions (A1 above).
A1 of **REM-0063-CYCLE10-REMAINING-CONTRACT-QUESTIONS (2026-11-17)** extends that
realignment to the single omitted case `encoded-slash` of
`test_percent_encoded_fragments_resolve_before_the_pointer`: same name, inputs
and 19 cases; only `encoded-slash` will expect `McpProfileError`. This design
commit does not change that existing test. The implementation commit does, and
the record lists the old and new expectation. No other existing test changes.

Only reference spellings starting with `#` are accepted, even when an URI naming
a contained resource resolves without network access. The generator emits only
the prescribed local pointers and refuses a final schema requiring forbidden
spellings. The library outcome and this additional refusal are recorded separately.
Source: **REM-0063-CYCLE10-INTERNAL-RESOURCE-URI (2026-11-16)**, option 1.

Bounds apply after the complete definition closure: 4096 JSON values and depth
32; the root counts as one, keys do not count. At 4097 or depth 33, generator and
profile refuse with their typed errors. Direct and transitive type growth counts.
Sources: **REM-0063-CICLO-10-CONTRATTO**, point 2 and VF-002;
**REM-0063-CYCLE7-NO-GO (2026-11-15)**, point 2. No bound changes.

Resource, base, reference target, closure placement and bounds are one
calculation, specified in **Single calculation design** and required by
**REM-0063-CALCOLO-UNICO (2026-11-17)** point 3. Agreement is still proved on
both public paths: independent library resolution, exact closure trees,
positive/negative instance twins and identical repeated render bytes. No
expected answer uses a production helper, including the shared one.

### Deterministic case matrix

| Dimension | Values and explicit representatives |
| --- | --- |
| Field | `inputSchema`, `outputSchema` |
| Root | absent, absolute; `root.json`, `./root.json`, `../up/root.json`, `relative/root.json`, `rel/dir/`; fragment-only and empty roots use the fixed base under decided B1 |
| Independent outer/inner IDs | absent, empty, `#`, root-relative, root-absolute, new relative/absolute, repeated URI; exact literal root repetition in the added product |
| Reference | `#`, pointer, anchor, percent segment/leading slash/anchor, contained-resource URI; parent/root/child/missing targets |
| Target | present, missing, invalid schema, non-schema; duplicate anchor; foreign field/tool/descriptor |
| Position | `properties`, `$defs`, `allOf`, `const`, `default`, `examples`; `not`, `items` in the added product |
| Duplicate order | both sibling orders and ancestor/descendant repetition |
| Origin/closure | delivered; public compiler/generator; direct/transitive types; unused sibling absent/present |
| Tokens/bounds | `~0`, `~1`, malformed escape, non-ASCII percent segments, array 2/02; 4096/4097 nodes, depth 32/33 |
| Fixed base | tool indices 0/1, both fields/origins, collision/noncollision, ID with/without final `#` |

The unchanged first 29746 cells remain: original delivered/generated 5184/576,
bounds/collision 30, two-level delivered/generated 18432/4608, sibling orders 288,
form/target state 216, isolation 108, ambiguous anchor 48, tokens 144,
both-origin collisions 4, library-state controls 24, root-fragment twins 12,
generated duplicate orders 72. Additions: root-class delivered **9216**
(2×6×2×6×8×8), public generation **1152** (2×6×2×6×8), data-target validity 18,
indexed fixed-base collision/twin 32, preserved anchor-context instances 16.
Total: **40180** cells in 23 test functions. Each product is fully enumerated,
without sampling. They are factored products, not a claim to execute their full
mutual cross-product. Their restrictions are:

- G1: generated OaC references are IR symbols. Arbitrary fragment spellings,
  pointer grammar, foreign targets and malformed schema targets belong to the
  delivered products; they are not generated-source cells.
- G2: an OaC definition without an incoming reference is omitted. Generated
  `$defs` target cells assert omission, not resolution of an unreachable node.
- G3: the original generated product varies unused siblings; its two-level
  extension varies direct/transitive reachability instead. Duplicate sibling
  orders have separate generated and delivered products. The added root-class
  generator product uses direct types; transitivity remains in the unchanged
  4608-cell product.
- I1: the old same-relative/absolute aliases are preserved in their original
  products. They do not represent literal relative-root repetition. The added
  product crosses each of the six explicit root spellings with exact literal
  repetition and five other nested-ID modes, under same-resource/new-absolute
  ancestors, in both origins. No root-class exclusion is hidden in an alias.
- F1: the original two-level product uses eight literal references. Encoded
  forms, invalid targets and URI spellings use separate products; root-class
  additions cross encoded-pointer forms with the extra root/ID classes.
  Form/target-state uses an absolute root/holder; isolation, token grammar and
  ambiguous-anchor products use their original no-root-ID construction.
- F2: `not` and `items` represent single-schema keywords; other single-schema,
  map/list keywords and `enum` data are not multiplied into these products.
  They follow the same pinned `Resource.subresources` and pointer machinery;
  no coverage of every keyword Cartesian combination is claimed. Invalid
  resolved schemas under `const/default/examples` are tested separately:
  the root passes `check_schema`, but the selected target must fail it.
- V1: cyclic `allOf/$ref:'#'` may not terminate instance validation. Their
  schema validity/resolution checks remain; recursive instance execution is
  `NOT_EXECUTED`, never a passing instance. Nonrecursive entry probes really run.
- B1/C1: empty and fragment-only roots use the fixed base; collision rows
  cover only the same schema, including index 1 and final-empty-fragment
  identity. The phase-A oracle `_cycle10_base` still treats `"#"` as an empty
  base. The implementation commit aligns that unsealed oracle to B1 and
  records the difference. No cell is removed.

The static matrix oracle uses `Resource.subresources`, `Resolver.in_subresource`
and `Resolver.lookup` on the original resource, preserving registry crawl state.
It checks `entry` with the same resolver/base. Its domain is the factored products,
not all valid schemas: a static-context failure may be irrelevant when an anchor
path reaches that node with a different library resolver. The existing profile
rule and cycle-8 tests for those paths remain unchanged. The added 16-cell public
characterisation uses real positive/negative `Draft202012Validator` instances,
without the stricter static oracle. No original matrix assertion is weakened.

### Decisions, questions and stopping conditions

Q1/Q2: A1+B1 of **REM-0063-CYCLE10-ORACLE-CONFLICT (2026-11-16)** are decided.
Q3: option 1 of **REM-0063-CYCLE10-INTERNAL-RESOURCE-URI (2026-11-16)** is decided.
Q4/Q5/Q6, the questions **REM-0063-CYCLE10-REMAINING-CONTRACT-QUESTIONS**
collected, are decided by the Product Owner in person on 2026-11-17: A1, B1
and C1. A2, B2 and C2 are not applied. The file at
`99d93da7a481c44841d9d8003044aed37c026ce6` has sha256
`edc7fe84762a5f6fa2f512209df099bb72f0b8040da374974bc03f4f1dbb29d8`. No question
in this contract remains open. The second review's blocking root-class coverage
is already in `66c14f60e440f287a88c5e01a0ab30259e303a26`; this design commit
adds no test. There is no third contract review.

The official fixture remains byte-identical. **REM-0063-PINNED-FIXTURE-DIFF-CHECK
(2026-11-16)**, option 1, leaves its whitespace check `NOT_GREEN` with a recorded
exception; every other file retains the check. No production repair or full
campaign has started. After the single design review, one implementation turns
the whole matrix and the existing tests green, then preventive review, local
gate, campaign, distinct check and final verification. Fence unchanged:
E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC and Production NO-GO.

### Single calculation design

**REM-0063-CALCOLO-UNICO (2026-11-17)** points 3–4. This commit does not modify
`ocor-runtime/src/`. The shared functions below will live in
`ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`, which `codegen.py` already
imports. No new file under `ocor-runtime/src/`. Duplicate helpers that the
table retires are deleted in the implementation commit. Matrix expectations
stay the pinned libraries on the original schema bytes, never a production
function.

No contract question remains open, so no shared function is left depending on
an undecided option. Q4/A1 changes only the existing `encoded-slash` assertion
named above. Q5/B1 is the base rule of `operational_base`: absent, non-string,
`""` and an identifier with an empty pre-fragment part (`"#"`, `"###"`) use
`urn:ocor:embedded-tool:{index}:{field}`; every other root `$id` uses that
pre-fragment part. The schema bytes are not rewritten. Q6/C1 limits the
fixed-base collision to string `$id` values inside that same schema, and a
trailing empty fragment is the same identity. A suffix that dodges the
collision is forbidden.

Shared functions and the errors they surface. Callers map
`SchemaCalculationFailure` to the public type already used on that path:
`McpProfileError` in `validate_mcp_descriptor`, `C1Error` in `_mcp`. The public
message and `DiagnosticCode` stay those the tests already name.

1. `operational_base(schema, *, index, field) -> str`. Errors: `COLLISION`
   (`McpProfileError` or `C1Error`/`TYPE_ERROR`) when the fixed base equals a
   `$id` in that schema under C1; `INVALID_ID` (`TYPE_ERROR`, message
   `MCP $id is not a valid URI reference`) when a declared pre-fragment part
   is not a URI reference. No suffix.
2. `json_bounds(document) -> None`. One walk. The root counts as one JSON
   value; object keys do not count. Depth starts at 1. Error `BOUNDS`
   (`MCP schema exceeds the revision bounds`, profile; `C1Error`/`TYPE_ERROR`
   with that message, generator) when the value count exceeds 4096 or the
   depth exceeds 32. The profile's non-JSON refusals (lone surrogate,
   non-finite number, non-JSON value) stay on this same walk and are not a
   second counter. The generator calls it on the schema after `$defs` closure,
   before the artefact is returned, and the profile calls it on the descriptor
   it receives.
3. `autonomous_registry(schema, base_uri) -> Registry`. Built only with
   `referencing` 0.37.0: `Registry().with_resource(base_uri, DRAFT202012.create_resource(schema)).crawl()`.
   The root URI entry stays the resource passed to `with_resource`, because
   the library resolver keeps that root until an `$id` changes the base. That
   pin does not walk pointers and does not rewrite bytes. Crawl failure is
   `NOT_RESOLVABLE` (`MCP schema resource index is not resolvable`, or
   `C1Error`/`UNRESOLVED_REFERENCE` on the generator).
4. `lookup_original(registry, base_uri, reference) -> Lookup`.
   `registry.resolver(base_uri).lookup(reference)` on the original spelling.
   The result carries the library contents and the resolver `lookup` returned,
   so an anchor chain keeps that resolver. `Unresolvable` is
   `UNRESOLVED_REFERENCE` (`MCP $ref does not resolve in the descriptor`, or
   `C1Error`/`UNRESOLVED_REFERENCE`). No decode-and-re-encode step feeds the
   lookup.

Resource identity for closure placement is the crawled registry, not a second
`urljoin` walker. `contained_resources` is that registry's entries. Two
distinct nodes that the library assigns one URI are `DUPLICATE_RESOURCE` on
the generator only (`C1Error`); the profile keeps the library's last-wins
result for siblings and does not invent another winner.

| Duplicated today | Disposition |
| --- | --- |
| `_declared_id` / `_mcp_declared_id` | Merge into `operational_base`. |
| `_resource_uri` / `_mcp_resource_uri`, `_changes_resource` / `_mcp_changes_resource` | Delete. Identity comes from the registry. |
| `_synthetic_tool_uri` / `_mcp_synthetic_uri` (suffix loop) | Delete. Collision refuses. |
| `_collect_declared_ids` / `_mcp_collect_ids` | Merge into the C1 collision read inside `operational_base`. |
| `_walk_json` bounds and `_mcp_bounds` | Merge into `json_bounds`. |
| `_crawl_document_resources`, `_same_uri_resource_ancestors`, `_mcp_iter_resources`, `_mcp_post_check` crawl | Merge into `autonomous_registry`. |
| `_resolve_reference` rewrite and `_lookup_reference` / post-check `lookup` | Merge into `lookup_original`. |
| `_iter_schema_children` versus `DRAFT202012.subresources_of` | Resolution uses only the library subresources. |
| `_mcp_ref`, `_mcp_defs_name`, `_mcp_select_body`, name clash, `without_context_overwrite` | Stay. They emit or select definition bodies; they do not resolve `$ref`. |
| `_PROFILE_SPECIFICATION` scalar guard | Stays only as the typed translation of the library `AttributeError` on a scalar target. It must not select a different resource. |

Rules stricter than `referencing` 0.37.0 and `Draft202012Validator`. Each runs
after the library result, refuses something the library would still accept or
maps a library failure to the typed error, and does not change a successful
library target.

1. Reference spelling must start with `#`. Other spellings, including a URI
   that names a contained resource, are refused. Profile:
   `MCP $ref must be a same-document fragment`. Generator:
   `C1Error`/`UNRESOLVED_REFERENCE`. Source:
   **REM-0063-CYCLE10-INTERNAL-RESOURCE-URI (2026-11-16)**, option 1.
2. A resolved target that is not a JSON Schema 2020-12 schema, including a
   boolean schema only when `check_schema` accepts it, is
   `MCP $ref target is not a JSON Schema 2020-12 schema`. Source:
   **MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)**, point 2.
3. A `$schema` outside the accepted 2020-12 dialect is
   `MCP schema dialect must be JSON Schema 2020-12`. `$dynamicRef` and
   `$recursiveRef` are `MCP $ref resolution does not follow dynamic references`.
   Source: **MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)**, point 2.
4. A plain-name anchor owned by more than one node of the same resource is
   `MCP $ref anchor is ambiguous`. A non-canonical array index, judged from
   the parent object `lookup_original` returned for the original pointer
   prefix, is `MCP $ref fragment is not a valid JSON Pointer`. Malformed
   percent-encoding and a non-UTF-8 fragment keep their current typed
   messages. These checks do not replace the reference passed to `lookup`.
   Source: the profile module as already tested; percent-encoded leading
   slash additionally **REM-0063-CYCLE10-ORACLE-CONFLICT** A1 and Q4/A1.
5. Fixed-base collision inside the same schema, including a final `#`, is
   rule `COLLISION` above. No suffix. Source: **ORACLE-CONFLICT** B1 and Q6/C1.
6. Two generator nodes with one library URI are `DUPLICATE_RESOURCE`. Source:
   the producer rule already in this contract; stricter than library last-wins.
7. A descriptor `$defs` above the tool schemas is refused by the profile.
   The generator emits none. A same-name definition with different content is
   `C1Error`/`TYPE_ERROR` (`MCP definition name clash`). Source:
   **MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15)**, points 1–2.
8. `without_context_overwrite` remains the profile function the generator
   already calls. Source: **GENERATORE**, point 1.
9. Bounds are `json_bounds`, not a second limit. Source:
   **REM-0063-CICLO-10-CONTRATTO**, point 2, and
   **REM-0063-CYCLE7-NO-GO (2026-11-15)**, point 2.

Call sites. `validate_mcp_descriptor`, for each `inputSchema` and
`outputSchema`: `operational_base`, `autonomous_registry`, `json_bounds`, then
the stricter checks, then `lookup_original` for every `$ref`. `_mcp` and
`_mcp_attach_definitions`: the same base and registry to decide which resource
receives which `#/$defs/<Name>` closure; `lookup_original` before returning
bytes; `json_bounds` on the closed schema. The anchor-chain rule is unchanged:
the static matrix oracle is not this calculation, and a static failure still
refuses the descriptor only when no reference path reaches that node
(**REM-0063-CYCLE10-REMAINING-CONTRACT-QUESTIONS**, final paragraph).

The implementation commit is the only production edit. It does not add a
dependency, change a version, or accept a spelling these decisions refuse.
After a `NO_GO` of this cycle there is no further cycle.
