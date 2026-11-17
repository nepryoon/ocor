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
The phase-A production tree was byte-identical to
`f485dc964e47bde83842ecd5ba2627d8342612f9`. The implementation commit is the
production edit. This derived contract implements
**REM-0063-CICLO-10-CONTRATTO (2026-11-16)**, points 1–3, and the single
calculation required by **REM-0063-CALCOLO-UNICO (2026-11-17)**. Codex
(`gpt-6.1-sol`, OpenAI, effort `max`) authored phase A and does not own the
cycle-10 code. From **REM-0063-CALCOLO-UNICO (2026-11-17)** point 1, Grok
Build (`grok-4.7`, xAI, effort `xhigh`) owns the code and wrote this
implementation. Earlier implementers remain Grok Build (`grok-4.7`, xAI) and
Codex CLI (`deepseek-flash`, `deepseek-v4-pro`, DeepSeek). The preventive
reviewer is Claude Code (`claude-fable-5-2`, Anthropic, effort `max`). The
design review `OCOR-DEV-REM-0063-3bad5d6ff394-pre` returned
`BLOCKING_FINDINGS`; that review is the only design review, its findings are
integrated here, and no further design review is requested. Final verifier:
Claude Code (`claude-opus-5-5`, Anthropic, effort `max`), assigned by
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
**REM-0063-CYCLE10-ORACLE-CONFLICT (2026-11-16)**, A1+B1
(request `0531a438f0d68637d8a7221507080a7c672c0847`, sha256
`35259990c43e2e2def484b7d763bdc691feb25e262e661d9a5323fa06fdeec41`;
disposition `7320dc93051aff01edcf242a78e790acae9ad60f`, sha256
`5c68feee5a9dc955eb93532b9348d6b8a3ed710dc4178dbbc0fd91e865bbdcfe`);
**REM-0063-CYCLE10-REMAINING-CONTRACT-QUESTIONS (2026-11-17)**, C1.

The profile validates every tool against the pinned official `Tool` definition,
then checks each schema's dialect, keywords and resolved targets. Missing or
non-schema targets cause typed refusal. Existing ambiguous-anchor and canonical
array-index restrictions remain. Percent-encoded anchors and the encoded leading
slash follow the original libraries, without helper substitutions (A1 above).
A1 of **REM-0063-CYCLE10-REMAINING-CONTRACT-QUESTIONS (2026-11-17)** extends that
realignment to the single omitted case `encoded-slash` of
`test_percent_encoded_fragments_resolve_before_the_pointer`: same name, inputs
and 19 cases; only `encoded-slash` expects `McpProfileError`. The old and new
expectation of every authorized realignment is the table
`repair_cycle_10.implementation.authorized_realignments` in the assurance
record. No other existing test changes.

Only reference spellings starting with `#` are accepted, even when an URI naming
a contained resource resolves without network access. The generator emits only
the prescribed local pointers and refuses a final schema requiring forbidden
spellings. The library outcome and this additional refusal are recorded separately.
Source: **REM-0063-CYCLE10-INTERNAL-RESOURCE-URI (2026-11-16)**, option 1,
request `620f56ba3206affd15679f0394c16c7a4eb0fa33`, sha256
`98827faf39c35d71dd3570e90baea7faa6c9e1539c2909d94bfb26bb1eb13acb`.

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
  identity. The unsealed phase-A oracle `_cycle10_base` previously used
  `urldefrag(schema.get("$id") or fixed)[0]`, so `"#"` became the empty
  string. The implementation commit aligns it to B1: absent, non-string,
  `""` and an empty pre-fragment use the fixed URI. No cell is removed.

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
The request file at `0531a438f0d68637d8a7221507080a7c672c0847` has sha256
`35259990c43e2e2def484b7d763bdc691feb25e262e661d9a5323fa06fdeec41`. The
disposition file at `7320dc93051aff01edcf242a78e790acae9ad60f` has sha256
`5c68feee5a9dc955eb93532b9348d6b8a3ed710dc4178dbbc0fd91e865bbdcfe`.
Q3: option 1 of **REM-0063-CYCLE10-INTERNAL-RESOURCE-URI (2026-11-16)** is decided.
The request file at `620f56ba3206affd15679f0394c16c7a4eb0fa33` has sha256
`98827faf39c35d71dd3570e90baea7faa6c9e1539c2909d94bfb26bb1eb13acb`. The
disposition file at `1a369324cd9c722772244afcdd890798d3c62b18` has sha256
`e1233e6b99ccbf9c9a68c2031b2f4cd4f64bdd31ffcc640a86ddfa555dc8d449`.
Q4/Q5/Q6, the questions **REM-0063-CYCLE10-REMAINING-CONTRACT-QUESTIONS**
collected, are decided by the Product Owner in person on 2026-11-17: A1, B1
and C1. A2, B2 and C2 are not applied. The file at
`99d93da7a481c44841d9d8003044aed37c026ce6` has sha256
`edc7fe84762a5f6fa2f512209df099bb72f0b8040da374974bc03f4f1dbb29d8`. One
contract question remains open: whether a nested resource is resolved by the
pinned libraries on the tool schema alone. That question is
`REM-0063-CYCLE10-NESTED-RESOURCE-RESOLUTION`, stated in **Single calculation
design**. The second review's blocking root-class coverage
is already in `66c14f60e440f287a88c5e01a0ab30259e303a26`; this design commit
adds no test. There is no third contract review.

The official fixture remains byte-identical. **REM-0063-PINNED-FIXTURE-DIFF-CHECK
(2026-11-16)**, option 1, leaves its whitespace check `NOT_GREEN` with a recorded
exception; every other file retains the check. The design review is integrated
in the implementation. The task module on this implementation passed 41896
tests, with 0 failures, 0 errors and 0 skipped, in 829.49 s (JUnit time
829.323 s). Raw log sha256
`1b5b9de216e6fb52c93e88a990674d0ddf2f8e18ec8d17d457ae4093a550c803`; JUnit
sha256 `5a1f1d541cdd3475a990188f7556c0d3010fc93147fb0bc01b3db4e2a86569ef`.
Both files are preserved as `matrix-task.raw.log` and `matrix-task.junit.xml`
under `~/.ocor-codex/rem-0063/cycle10-implementation/`. An earlier run stopped
by `--maxfail=20` is not green: 20 failed, 41534 passed, exit 1, raw sha256
`17a76e58dd4fdf5a4b6a52f2ee1d78609fdd1cb4f1f45a2eefd8d6824b8cf618`
(`matrix-green.raw.log`). The matrix stays 40180 cells. This task-module run
is not a qualifying campaign. The pre-campaign preventive review
`OCOR-DEV-REM-0063-cce3ba8ba7ab-pre` has already returned
`BLOCKING_FINDINGS` (6 blocking, 2 advisory). Reviewer: Claude Code,
`claude-fable-5-2`, Anthropic, effort max. Outcome-file sha256
`13effc01c0ba02480b457c2f0fe215910c7f3136211c1423903ab2d18e1c3421`.
The repairs that do not choose a normative reading are on this head. The
qualifying campaign waits on `REM-0063-CYCLE10-NESTED-RESOURCE-RESOLUTION`.
No second pre-campaign review is requested. The full pre-campaign gate is
not yet run. Fence unchanged:
E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC and Production NO-GO.

### Single calculation design

**REM-0063-CALCOLO-UNICO (2026-11-17)** points 3 and 5, superseding the
pre-implementation text of this subsection. Shared functions live in
`ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`. `codegen.py` imports them.
No new file under `ocor-runtime/src/`. No dependency or version change.
Matrix expectations stay the pinned libraries on the original schema bytes.

One contract question remains open: whether a nested resource is resolved by the pinned libraries on the tool schema alone, or kept as its own fragment root. That question is `REM-0063-CYCLE10-NESTED-RESOURCE-RESOLUTION`. The hand registration in `enter_subschema` and the `PointerToNowhere` retry are not claimed as the library applied as-is; they stay until that decision. Q4/A1 refuses a percent-encoded plain-name
anchor and the encoded-slash pointer before a successful literal resolve.
Q5/B1 is `operational_base`: absent, non-string, `""` and an empty
pre-fragment (`"#"`, `"###"`) use `urn:ocor:embedded-tool:{index}:{field}`;
every other root `$id` uses `urldefrag(...)[0]`. Q6/C1 scans every string
`$id` in that schema, including `const`, `default`, `examples` and `enum`,
and only against the fixed base. A trailing empty fragment is the same
identity. No suffix.

`SchemaCalculationFailure` carries `code` and `message`. The profile maps
`CRAWL` and `NOT_RESOLVABLE` to `MCP schema resource index is not resolvable`,
`INVALID_ID` to `MCP $id is not a valid URI reference`, and every other code
to `message`. The generator maps `CRAWL` to `C1Error`/`UNRESOLVED_REFERENCE`
(`unresolved MCP definition`), `NOT_RESOLVABLE` to `TYPE_ERROR` (`MCP schema
resource is not resolvable`), `INVALID_ID` and `COLLISION` and `BOUNDS` to
`TYPE_ERROR` with the shared message.

1. `json_bounds(document) -> None`. One walk. The root counts as one JSON
   value; keys do not count; depth starts at 1. `BOUNDS` above 4096 values
   or depth 32. Lone surrogates, non-finite numbers and non-JSON values fail
   on this walk. The profile calls it on the whole descriptor after the
   existing top-level `$defs` check and before the registry. `_mcp` calls
   the same function on the final descriptor after every closure and before
   `_json`. The call inside `_mcp_attach_definitions` is an early exit on
   that schema, not a second limit.
2. `operational_base(schema, *, index, field) -> str`. No suffix. `COLLISION`
   message `MCP schema base collides with a declared $id`.
3. `autonomous_registry(schema, base_uri, *, registry_factory=Registry, translate_null_applicator=False) -> Registry`.
   Two registries are built with `registry_factory`. `probe.crawl()` is
   discarded. The returned registry is never crawled and pins only the root
   passed to `with_resource`. `registry_factory` is the `codegen.Registry`
   global, read at the call inside `_mcp_attach_definitions`. Non-string
   `$id` values in schema position are `NOT_RESOLVABLE` before the resource
   is built. `Unresolvable` from the probe is `CRAWL`. `TypeError` from the
   probe is `NOT_RESOLVABLE`. `AttributeError` on `NoneType.values` or
   `rstrip` is `NOT_RESOLVABLE`. On the generator only, `NoneType.get` is
   `CRAWL`. Any other `AttributeError` is not remapped here: a scalar inside
   `$defs` still reaches the non-schema target check. `ValueError` is
   `INVALID_ID`. An unreferenced `$id` in instance data is not this refusal.
4. `enter_subschema(resolver, child) -> tuple[Resolver, bool]`. The boundary
   is `in_subresource` changing the base. A changed base is registered with
   `with_resource` only when the child is a library subresource of the
   resource `lookup("#")` already returns. An `$id` reached only through
   instance data changes the base and stays unregistered, so a later fragment
   fails closed. The caller's registry is not replaced.
5. `assert_reference_path_bound(schema, resolver) -> None`. Reference-path
   depth uses the profile graph's static-first breadth-first bound. A chain
   of named definitions is not a generator-only limit. Depth above 32 is
   `BOUNDS`. `json_bounds` remains the JSON value count and JSON depth.
   `_resolve_graph` and `_mcp_post_check` both call this function.
   Anchor-chain depth tests are unchanged.

Lookup uses the original reference spelling. An encoded fragment whose
decoded form does not start with `/` is refused before lookup. A plain-name
anchor with more than one owner of the same resource, keyed by `id` of the
resource root, is `MCP $ref anchor is ambiguous`; one node that declares both
`$anchor` and `$dynamicAnchor` with the same name is one owner. Pointer
indexes are checked on the decoded tokens; the primary lookup stays the
original spelling. `AttributeError` from a scalar target is recovered by
walking the original `#/` pointer on `lookup("#").contents`. A
`PointerToNowhere` on the resource pinned at the current base is retried
once after that URI is removed from the same registry, so a descendant whose
`$id` rejoins the URI is the resource the library crawl returns. The retry
does not build a new root resolver. The resolver `lookup` returns is the one
an anchor chain continues with.

The generator walks resources with `in_subresource` only. Two different nodes
that receive one base are `DUPLICATE_RESOURCE`. The closure is written on
the unpinned `lookup("#").contents`, or on the boundary node when that
lookup cannot retrieve a relative base. References are scanned from the
boundary as well as from that owner, so a reference that sits on the
boundary is not dropped when a descendant rejoins the URI. `$defs` are
placed on the owner. The earlier rule that treated every base change as its
own closure root is superseded: a joined URI whose unpinned crawl returns
an ancestor keeps the reachable references on that ancestor, and unreachable
`$defs` on the descendant are omitted.
`additionalItems` stays on the current resource unless its base changes, in
which case the generator reports `MCP schema resource is not crawled`.
`_mcp_attach_definitions` keeps its signature. `_mcp_ref`, `_mcp_defs_name`,
`_mcp_select_body`, the name-clash error and `without_context_overwrite` stay.
There is no cross-schema identifier union and no suffix loop.

Historical rows for the deleted helpers stay in the record. This implementation
deletes `_declared_id`, `_resource_uri`, `_changes_resource`,
`_synthetic_tool_uri`, `_collect_declared_ids`, `_walk_json`,
`_crawl_document_resources`, `_same_uri_resource_ancestors`,
`_collect_node_uris`, `_canonical_resource_contents`, the hand-written
resolver and `_PROFILE_SPECIFICATION`. The generator deletes `_mcp_bounds`,
`_mcp_declared_id`, `_mcp_resource_uri`, `_mcp_changes_resource`,
`_mcp_collect_ids`, `_mcp_synthetic_uri`, `_mcp_base_uri` and
`_mcp_seed_refs`. The profile `_reject_surrogate` is deleted; lone
surrogates stay on `json_bounds`. The `c8` helper of the same name is
unchanged. `_recover_scalar_target` remains: it recovers a scalar pointer
target after the library lookup has failed, and it is not a second resolver.
The nested-resource registration and the one `PointerToNowhere` retry stay
until `REM-0063-CYCLE10-NESTED-RESOURCE-RESOLUTION`.

Rules stricter than the libraries, each with its own typed error:

1. A reference must start with `#`. Profile: `MCP $ref must be a same-document fragment`. Generator: `C1Error`/`UNRESOLVED_REFERENCE`. Source: **REM-0063-CYCLE10-INTERNAL-RESOURCE-URI (2026-11-16)**, option 1.
2. A target that is not a JSON Schema is `MCP $ref target is not a JSON Schema`. Source: **MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)**, point 2.
3. A `$schema` outside draft 2020-12, and `$dynamicRef` / `$recursiveRef`, keep their existing typed refusals. Source: **MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)**, point 2.
4. Ambiguous anchors and non-canonical array indexes stay profile refusals. Encoded plain-name anchors do not resolve. Source: the tested profile rules, **ORACLE-CONFLICT** A1 and Q4/A1.
5. Fixed-base collision. Source: **ORACLE-CONFLICT** B1 and Q6/C1.
6. Generator duplicate URI. Source: the producer rule; stricter than library last-wins.
7. No descriptor `$defs`. Name clash: `MCP definition name clash`. Source: **MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15)**.
8. `without_context_overwrite` on the input schema. Source: **GENERATORE**, point 1.
9. `json_bounds` is the only value-count limit. Reference-path depth 32 is a separate rule. Source: **REM-0063-CICLO-10-CONTRATTO**, point 2, and **REM-0063-CYCLE7-NO-GO (2026-11-15)**, point 2.

`validate_mcp_descriptor` calls `json_bounds` on the descriptor, then builds one uncrawled registry per tool schema and resolves every `$ref` with the shared lookup. `_mcp` calls `json_bounds` and then `operational_base` on each tool schema field before `_mcp_attach_definitions`, then `json_bounds` on the assembled descriptor. A static failure still refuses the descriptor only when no reference path reaches that node. The implementation adds no dependency and accepts no spelling these decisions refuse. After a `NO_GO` of this cycle there is no further cycle.
