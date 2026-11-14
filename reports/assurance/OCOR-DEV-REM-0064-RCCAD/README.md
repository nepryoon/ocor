# OCOR-DEV-REM-0064

Governed register write for claim admission, identity resolution and the
mission-thread view, authorised by FABLE52-EXTENSION-NCP-U15-ID-COLLISION
(2026-11-13) point 4. Implementer: Grok Build (xAI), grok-4.7.

This unit writes the register entries, plan unit NCP-U16, the decision file
and the regression-only requalifications forced by the plan allowlist. It does
not implement AdmitClaim or identity resolution. Claims stay E1=0, E2=0,
Verified=0, runtime NOT_ESTABLISHED, PoC and Production NO-GO.

`scripts/probe_ncr_claim_identity_mission.py` is the read-only verification
command of NCR-C3-008, NCR-C3-009 and NCR-PLAN-007.
