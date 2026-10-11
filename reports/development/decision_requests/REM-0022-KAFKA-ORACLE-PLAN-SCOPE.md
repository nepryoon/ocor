# REM-0022-KAFKA-ORACLE-PLAN-SCOPE

Status: `RESOLVED_WITHIN_EXISTING_MANDATE` — 2026-10-11.

Il primo gate contro `origin/main@63184cb` ha respinto il solo sorgente
`spikes/kafka_delivery/oracle.py` (36 PASS, 1 FAIL, 2 NOT_EXECUTED opzionali).
Il diagnostico e il WIP `26dbf7a` restano storici; la PR #214 di solo stato è
stata chiusa senza merge. Il fallimento non è rietichettato come PASS.

L'interpretazione iniziale della clausola locale «new remediation test/evidence
paths only» era troppo restrittiva. Il mandato corrente del Product Owner
`CC-OCOR-DELIVERY-COMPLETION` §7 autorizza le riparazioni CI che non indeboliscono
alcun gate, e il sorgente respinto è già nominato nelle `expected_file_areas`
di REM-0022 su main. È una registrazione meccanica del perimetro autorizzato,
non una variazione di semantica né una nuova autorizzazione normativa.

L'allowlist aggiunge esclusivamente il sorgente esatto e questo record di
disposition, oltre ai test/evidenze già registrati. Nessuna wildcard, nessun
cambio del predicato di ammissione, del base di integrazione, del ruleset o
dei controlli. La verifica resta sul vero base `63184cb`. È richiesta una nuova
riqualifica di 0050 sul validator finale, con supersession e record storici
immutati; nessuna evidenza precedente viene dichiarata eseguita sul nuovo HEAD.

La richiesta di decisione al PO è ritirata prima dell'integrazione. REM-0022
procede entro il mandato esistente, con gate verdi e due ambiti di verifica sullo
stesso HEAD: Claude Code per REM-0022/0019/0040; Grok 4.7 (Cursor CLI) per 0050,
toccato dall'implementatore di riserva Claude Code. Il loop avvia i verifier.
Nessun sigillo, chiusura o claim è anticipato. `inputs/` immutabile;
E1=0, E2=0, Verified=0; runtime conformance e PoC/Production NO-GO invariati.
