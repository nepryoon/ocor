# OCOR-DEV-REM-0063

MCP profile for FABLE52-POST-POC-PROGRAMME (2026-11-11) point 1.
Protocol revision 2026-07-28. The Tool Contract schema in ADD v1.3 section 3.5 is unchanged.
FR-047, FR-169 and NFR-022 are not verified by this unit; OCOR-DEV-0065 verifies them.
Claims stay E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC NO-GO, Production NO-GO.

The cycle-2 decoder commit is `3dd37e29222ae2c85f400f4fc7573def127f6a53`.
The class-coverage execution commit is `a284c11238063760c471d80cd9e0f7b6c957e42b`.
This record supersedes `OCOR-DEV-REM-0063-d215c7d2c1dc`.
The four-lane campaign at `c28cd9c411c466f38e9671d2774939bb9a910a30` does not qualify the cycle-2 head.
The class-coverage pre-campaign gate ran on `a284c11238063760c471d80cd9e0f7b6c957e42b`: 51 PASS, 6 NOT_EXECUTED, 97.897 s.
The same gate ran on the evidence commit `a756fb9faf6860d218096d39fb10678dc9135b08`: 51 PASS, 6 NOT_EXECUTED, 99.195 s. That log is the current pre-campaign.log.
The evidence commits do not change the execution-commit inputs.
The plan validator is unchanged, so the regression requalifications stay on their declared commit.

Preventive review OCOR-DEV-REM-0063-9dc963f40644-pre found that the malformed-fragment rows do not plant the undecoded token, so they pass on the resolver before the decoder. The class-coverage tests at a284c11238063760c471d80cd9e0f7b6c957e42b plant that key. red.log keeps the previous RED as a byte prefix (sha256 67868a1e29c59e4e42c5197874e15d89c2e3f0094c97b35c8d1dcbabbb511bec) and appends the planted-key RED and the identity-decode mutation. GREEN is 188 passed. The four-lane campaign at c28cd9c411c466f38e9671d2774939bb9a910a30 still does not qualify this head.
