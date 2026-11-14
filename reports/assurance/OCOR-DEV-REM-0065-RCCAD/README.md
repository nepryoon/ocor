# OCOR-DEV-REM-0065

Derived agentic risk map authorised by FABLE52-POST-POC-PROGRAMME
(2026-11-11) point 2. Implementer: Grok Build (xAI), grok-4.7.

`scripts/generate_agentic_risk_inventory.py` reads the repository registers
and contracts and writes `docs/security/OCOR_AGENTIC_RISK_MAP.md`,
`docs/security/agentic_risk_inventory.json` and the decision request
`reports/development/decision_requests/AGENTIC-RISK-MAP-PARTIAL-GAPS.md`.
The map is not evidence and is not a conformance claim. It does not change
the criteria of OCOR-DEV-0062, OCOR-DEV-0064, OCOR-DEV-0068 or
OCOR-DEV-0069. Claims stay E1=0, E2=0, Verified=0, runtime
NOT_ESTABLISHED, PoC and Production NO-GO.

`red.log` is the failing run recorded before the generator existed.
`green.log` is the later unittest run of
`reports.tests.test_agentic_risk_inventory`. The regression suites of
OCOR-DEV-0005, OCOR-DEV-0050 and OCOR-DEV-0082 are not in this change set:
they have not been run for this allowlist edit.
