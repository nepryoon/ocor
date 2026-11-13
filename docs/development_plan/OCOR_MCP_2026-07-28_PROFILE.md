# OCOR MCP profile for revision 2026-07-28

Derived correspondence for OCOR-DEV-REM-0063 (FABLE52-POST-POC-PROGRAMME
(2026-11-11) point 1). This document is not evidence and does not verify
FR-047, FR-169 or NFR-022.

The text read is the Model Context Protocol changelog for revision 2026-07-28:

- URL: `https://modelcontextprotocol.io/specification/2026-07-28/changelog`
- Retrieved bytes: `docs/specification/2026-07-28/changelog.mdx` from the
  `modelcontextprotocol` repository
- Read date: 2026-11-13
- sha256: `b327e576f4c96b34e92f338f8ffefc35e13d0e953ab76bdb3aab342d104c8e53`

The Tool definition checked by the tests is `schema/2026-07-28/schema.json`
from the same repository. sha256
`edbb197ed0f92e90d658866e23cf76f107df0caac5ce25c2b9e64e1ca9a6314a`.
The copy and its licence notice live under
`ocor-runtime/tests/fixtures/mcp/2026-07-28/`.

The governed revision is one constant on the C1 generator. The generated
descriptor reports it as `x-ocor-mcp-protocol-revision`. ADD v1.3 section 3.5
(the Tool Contract schema) is unchanged. An MCP call carries
`governed_context_ref` (ADD v1.3 line 382, transport origin). This unit is not
an MCP server: it does not implement `_meta`, Streamable HTTP, tasks or
authorisation. Those behaviours are the G-1 follow-up in
`docs/development_plan/post_poc/README.md` (G9, WS-09: stateless MCP transport,
Tasks extension and authorisation) and stay `DEFERRED_POST_POC`.

Dispositions used below are `CONFORMANT`, `NOT_APPLICABLE` and
`DEFERRED_POST_POC`.

| Id | Changelog entry | Generated descriptor | Tool Contract | C8 tool runtime | C2 boundary | Disposition |
| --- | --- | --- | --- | --- | --- | --- |
| major-1 | Remove protocol sessions and `Mcp-Session-Id`. List results no longer vary per connection. | The descriptor is static and has no session field. | Unchanged. | `call_tool` has no session parameter and no session state. | `admit_mcp_tool_call` delegates to that function and has no session. | CONFORMANT |
| major-2 | Remove the `initialize` handshake. Each request carries its protocol version and client capabilities. | The descriptor reports the governed revision. There is no handshake document. | Unchanged. | The first call carries `governed_context_ref` and does not call `initialize`. OCOR uses that ref (ADD v1.3 line 382), not MCP `_meta`. | The same call. A missing ref is `CAPABILITY_DENIED`. | CONFORMANT |
| major-3 | Add `server/discover`. | Not a server advertisement. | Unchanged. | Not a server. | Not a transport. | DEFERRED_POST_POC |
| major-4 | Replace HTTP GET and resource subscriptions with `subscriptions/listen`. | No subscription stream. | Unchanged. | No listener. | No listener. | DEFERRED_POST_POC |
| major-5 | Remove `ping`, `logging/setLevel` and roots list-changed notifications. | The profile does not emit those methods. | Unchanged. | Nothing in this boundary implements them. | Nothing in this boundary implements them. | NOT_APPLICABLE |
| major-6 | Move tasks into the official tasks extension. | No task handle. | Unchanged. | No task methods. | No task methods. | DEFERRED_POST_POC |
| major-7 | Multi-round-trip requests replace server-initiated requests. | No round-trip result. | Unchanged. | The call returns the frozen context record, not an input request. | Same result. | NOT_APPLICABLE |
| major-8 | Results carry `resultType`. | No MCP result object. | Unchanged. | Not an MCP result. | Not an MCP result. | NOT_APPLICABLE |
| major-9 | Remove SSE resumability and `Last-Event-ID`. | No SSE stream. | Unchanged. | No event stream. | No event stream. | DEFERRED_POST_POC |
| minor-1 | `extensions` on client and server capabilities. | No capability advertisement. | Unchanged. | Not a server. | Not a server. | NOT_APPLICABLE |
| minor-2 | OpenTelemetry keys in `_meta`. | No `_meta`. | Unchanged. | No trace context on this boundary. | No trace context on this boundary. | NOT_APPLICABLE |
| minor-3 | `tools/list` should be in a deterministic order. | Tools are sorted by the emitted name. | Unchanged. | The descriptor is the list. | The descriptor is the list. | CONFORMANT |
| minor-4 | Require `Mcp-Method` and `Mcp-Name`, and allow `x-mcp-header`. | No HTTP request. | Unchanged. | No header projection. | No header projection. | DEFERRED_POST_POC |
| minor-5 | `ttlMs` and `cacheScope` on list and read results. | The descriptor is not a list response. | Unchanged. | No cache hint. | No cache hint. | DEFERRED_POST_POC |
| minor-6 | Resource not-found moves from `-32002` to `-32602`. | No JSON-RPC resource error. | Unchanged. | Refusals use `CAPABILITY_DENIED`. | The same refusal. | NOT_APPLICABLE |
| minor-7 | Authorisation responses should include `iss`. | No authorisation response. | Unchanged. | No token exchange. | No token exchange. | DEFERRED_POST_POC |
| minor-8 | Dynamic client registration must set `application_type`. | No client registration. | Unchanged. | No client registration. | No client registration. | DEFERRED_POST_POC |
| minor-9 | Client credentials are bound to the issuing authorisation server. | No stored credential. | Unchanged. | No credential store. | No credential store. | DEFERRED_POST_POC |
| minor-10 | `inputSchema` and `outputSchema` are JSON Schema 2020-12, with `$ref` resolution and composition bounds. | Each tool schema is checked as 2020-12. `$ref` must be a same-document fragment and must resolve. Depth is at most 32 and the walk stops at 4096 nodes. | Unchanged. | The call boundary does not recompile the schema. | The call boundary does not recompile the schema. | CONFORMANT |
| minor-11 | Remove the elicitation-complete notification and `elicitationId`. | Not emitted. | Unchanged. | Not implemented. | Not implemented. | NOT_APPLICABLE |
| minor-12 | Partition JSON-RPC server error codes and renumber the new errors. | No JSON-RPC error object. | Unchanged. | `CAPABILITY_DENIED` is the OCOR reason code. | The same reason code. | NOT_APPLICABLE |
| deprecated-1 | Deprecate Roots, Sampling and Logging. | Not adopted. | Unchanged. | Not adopted. | Not adopted. | NOT_APPLICABLE |
| deprecated-2 | HTTP+SSE transport is Deprecated. | No HTTP+SSE transport. | Unchanged. | No transport. | No transport. | DEFERRED_POST_POC |
| deprecated-3 | Deprecate `includeContext` values `thisServer` and `allServers`. | Not adopted. | Unchanged. | Not adopted. | Not adopted. | NOT_APPLICABLE |
| deprecated-4 | Deprecate OAuth 2.0 dynamic client registration. | No registration protocol. | Unchanged. | No registration protocol. | No registration protocol. | DEFERRED_POST_POC |
| other-schema-1 | `schema.json` uses `number` for minimum, maximum and default. | Tools are validated against that corrected schema. | Unchanged. | No separate numeric coercion. | No separate numeric coercion. | CONFORMANT |
| governance-1 | Adopt the feature lifecycle and deprecation policy. | Process only. | Unchanged. | Process only. | Process only. | NOT_APPLICABLE |
| process-1 | Formalise the PR-based SEP workflow. | Process only. | Unchanged. | Process only. | Process only. | NOT_APPLICABLE |
