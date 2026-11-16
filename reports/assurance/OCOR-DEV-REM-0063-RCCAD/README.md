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

Status: phase A, contract and RED tests; production code is still exactly
`f485dc964e47bde83842ecd5ba2627d8342612f9`. This section is a derived contract
for review, under **REM-0063-CICLO-10-CONTRATTO (2026-11-16)**, points 1–3.
It does not declare either cycle-9 finding closed. Implementer of phase A:
Codex, `gpt-6.1-sol`, OpenAI, effort `max`. Earlier implementers remain
Grok Build (`grok-4.7`, xAI), and Codex CLI with `deepseek-flash` and
`deepseek-v4-pro` (DeepSeek). Claude Code, `claude-fable-5-2`, Anthropic,
is the assigned contract reviewer; the loop launches that review.

### Producer and consumer obligations

Each emitted `inputSchema` and `outputSchema` is an autonomous JSON Schema
2020-12 resource. Each has its own registry, containing that schema and its
contained resources only. Its base is its `$id`, when present; otherwise it
is the fixed URI for that tool and field. No resolution falls back to the
descriptor, another tool or a fetched document. This follows
**MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)**, points 1–2. A no-ID base collision
with a declared `$id` is a typed refusal, as expressly required by
**MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15)**, point 2; question Q2
below records the conflicting existing test.

The generator closes each resource over the IR types it uses, transitively,
with references of the form `#/$defs/<Name>`. It includes all and only reachable
definitions; a conflicting existing definition is a typed generation error.
There are no descriptor-level `$defs`. Rendering the same release twice yields
identical bytes, and `without_context_overwrite` still removes the transport
context field from the input schema. These obligations follow
**MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE**, points 1 and 3. The raw OaC contract
uses IR symbol references, which the existing compiler checks before generation.

On a successful public render, the actual emitted bytes must pass the public
profile, `Draft202012Validator.check_schema`, and resolution with unmodified
`referencing` 0.37.0 on each standalone schema. The oracle must not rewrite
`$id`, substitute a registry root, decode a reference into a different spelling,
or borrow a definition from another field. Unresolvable combinations require
`C1Error` before any artefacts are returned. This is the acceptance rule of
**REM-0063-CICLO-10-CONTRATTO**, point 2, and VF-001's required fix in
`OCOR-DEV-REM-0063-f485dc964e47-9`. Question Q1 identifies existing tests whose
oracles change the reference spelling and therefore need a PO disposition.

A delivered descriptor is validated against the pinned official `Tool`
definition, with schema, dialect, keyword and reference checks on each tool
schema alone. Failure is `McpProfileError`. The existing local-fragment rule
rejects a directly named resource URI even if a library could resolve it; a
missing target or a target that is not a schema is rejected. Bounds remain
4096 JSON values and depth 32, measured on the **final descriptor after closure**:
the root counts as one, mapping keys do not count as values, and every scalar,
sequence and mapping does. The generator must reject at 4097 or depth 33 with
`C1Error`; it must not return a descriptor the profile rejects for those bounds.
Sources: **REM-0063-CICLO-10-CONTRATTO**, point 2; its VF-002 required fix;
**REM-0063-CYCLE7-NO-GO (2026-11-15)**, point 2. No limit changes here.

The profile and generator currently compute resource/base identity separately
(`_build_schema_trees` and `_mcp_base_uri`, their resource-URI helpers) and
validate closure through separate paths (`_resolve_graph` and
`_mcp_post_check`). Phase B must make those paths agree. The agreement proof
chosen for this contract is the Cartesian public-path test below, using the
same independent library oracle on delivered and emitted schemas. Whether phase
B also shares a production helper is an implementation choice within scope;
the tests never use it to compute an expected answer.

### Case matrix

The product is deterministic; no seed or sampled subset is used. Each cell has
an acceptance or typed-refusal expectation derived from the standalone library
result and the expressly stricter profile rules above.

| Dimension | Values |
| --- | --- |
| Field | `inputSchema`, `outputSchema` |
| Root base | absent `$id`, absolute `$id`, relative `$id` |
| Nested ID | absent, empty, `#`, same-resource relative, same-resource absolute, new relative, new absolute, same URI on two distinct nodes |
| Reference | `#`, JSON Pointer, anchor, percent-encoded pointer segment, percent-encoded leading slash, percent-encoded anchor, nested resource URI, missing target, non-schema target |
| Position | `properties`, `$defs`, `allOf`, inside `const`, `default`, `examples` |
| Origin | delivered descriptor, public compiler and generator output |
| Unreferenced sibling | absent, present |
| Final bounds | 4096/4097 nodes; depth 32/33; direct and transitive IR-type growth |

The structural product has 10368 cells. Delivered-schema tests cover all 5184
cells of that origin. Generated-schema tests cover 576 cells: OaC's symbol
reference becomes the pointer form. The following are the complete exclusions
and input aliases, rather than hidden sample choices:

- G1: the other 4608 generated-origin cells use eight raw reference forms that
  OaC's existing symbol-table validation cannot express. They are covered by
  the delivered origin. No compiler admission is bypassed or changed.
- G2: a generated `$defs/target` with no incoming IR reference is unreachable.
  It must be omitted; no probe demands that omitted node survive. Delivered
  cells explicitly reference that position and therefore exercise it.
- I1: without a root ID, the same-resource-relative representative is `#`.
  Without an absolute root ID, the same-resource-absolute representative is
  also `#`. The fixed-base collision is tested separately for both fields.

Another 30 cases cover final node/depth boundaries, growth from direct and
transitive types, and the fixed-base collision. Total: 5790 new cases.
The generator tests require resolvable positives to render, prohibit blanket
refusal, validate every emitted field, and compare repeated render bytes.
The profile tests compare its public acceptance with the library's original
schema outcome. Library-only traversal uses `Resource.subresources`,
`Resolver.in_subresource` and `Resolver.lookup`, including pointer traversal
through instance data; it never implements pointer or anchor resolution itself.

### Open questions and stopping conditions

Q1: existing percent-encoded-anchor and encoded-leading-slash tests accept
references which the raw standalone libraries reject. Earlier differential
helpers deliberately substitute `#part` for `#p%61rt`. The cycle-10 rule requires
the unchanged schema and unchanged libraries. Which existing expectations and
helper mappings may be realigned is reserved to the PO; phase A changes none.

Q2: `test_cycle8_synthetic_uri_avoids_declared_id_collisions` expects selection
of another synthetic URI, while the generator decision's point 2 expressly
requires refusal on a fixed-base collision. Phase A preserves that existing
test and adds the prescribed negative; permission to realign the old test is
reserved to the PO.

These linked questions are collected in **REM-0063-CYCLE10-ORACLE-CONFLICT**,
under **REM-0063-CICLO-10-CONTRATTO**, point 6, and
**NORMATIVE-QUESTIONS-EARLY-DR (2026-11-09)**. They prevent phase B, not the
read-only contract review. The fixture-byte question remains separately open as
**REM-0063-PINNED-FIXTURE-DIFF-CHECK**; its pinned bytes and `NOT_GREEN`
classification are preserved (cycle-10 decision, point 5). Neither question
is silently decided by this derived contract. No production repair or full
campaign has started. Claims remain unchanged.
