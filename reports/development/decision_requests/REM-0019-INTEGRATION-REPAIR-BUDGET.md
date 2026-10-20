# REM-0019-INTEGRATION-REPAIR-BUDGET

Status: `OPEN_PO_DECISION_REQUIRED`. Data: 2026-10-20T07:01:28.376081+00:00.

## Contesto e autorità

`OCOR-DEV-REM-0019`, integrazione PR #254, candidato `712fc2b799774281321c04209bfb6910b91f0941`, branch `governed/ocor-dev-rem-0019-evidence-stage`. Ultimo ciclo ordinario: `repair_cycle=2`; budget residuo zero. RCCAD e mandato §8 vietano un terzo ciclo senza decisione esplicita. Il GO storico e i sigilli restano storici, senza trasferimento al candidato rifiutato.

Implementatori dal GO precedente: Codex (OpenAI), riparazione 2 e integrazione; contributi storici Claude Code (Anthropic) conservati. Verifier effettivo indipendente: Grok 4.7 (xAI), Cursor CLI, processo e contesto separati, avviato soltanto dal loop esterno.

## Finding e prove

Verdetto `NO_GO`: `OCOR-DEV-REM-0019-712fc2b79977-2`; SHA256 `f2c98370867331e3399e74961cd6b5130aae10276b097455f3d34069276fdbc5`. VF-001 (`high`, BLOCKER) riguarda `scripts/observe_kind_teardown.py:340`.

Due campagne esterne del 2026-10-20, iniziate alle 05:16:37Z e 06:11:40Z, si interrompono dopo 1780 PASSED, zero FAILED/ERROR/SKIPPED registrati fino all'interruzione. Nessun conteggio parziale vale come suite completa o PASS. In entrambe il supervisore rifiuta con `NO_OWNED_REMOVER_IN_PYTEST_GROUP`: evento Docker `destroy` del medesimo UUID presente, prova del processo `kind delete` nel gruppo pytest assente, zero rimozioni accettate. Il verdetto riporta bootstrap running, nessun OOM/restart. La causa della mancata osservazione del remover non è accertata; il rifiuto resta fail-closed. La full locale 2323 PASS resta nella sua storia e non annulla la mancata riproduzione esterna.

Campagna 1: UUID `061d5c1e353b96b44561d8849986bd313abdbf3a6a14a7eeb11e0b708659c69c`; osservazioni SHA256 `93fab2ee2b9ba8daaf7e31508d93a5a6e5921dafc01d851c96cbd3aef19e8cba`; risultato SHA256 `9c1c90ac65d98cd0971222ca7f33771abf1428635397cc2d158153e183d9b81f`.

Campagna 2: UUID `31461cced467ac808c2f529ed9d24ef34745682a8a016ea223583097268f7e7a`; osservazioni SHA256 `6c3e7063a56aab28ab50186fc8ae1d9359324b68f84336016a81f006e2bea6ad`; risultato SHA256 `d5a4c76c11c9f185cdc96e2f55e5c4a5660d364b2963b670b75f469d50ea530f`.

Verdetto originale immutato in `~/.ocor-codex/verdicts/`; copie private dei raw e inventario completo SHA256 in `~/.ocor-codex/rem0019-escalation-20261020/`, riepilogo `escalation.json`. I raw non sono pubblicati perché includono identificativi parametrizzati con fixture di credenziali; nessuna stringa di fixture è riprodotta in questa richiesta.

## Opzioni e raccomandazione

1. Autorizzare un solo ciclo eccezionale 3, esplicitamente esteso all'harness necessario a VF-001, dopo una diagnosi riproducibile. Richiedere RED prima del codice, GREEN positivi/negativi, prova invarianti AST, qualifica richiesta dal cambio harness e nuova verifica indipendente sull'HEAD esatto. Finestra 30 s, timeout, cadenza, timer, partizione, selezione e gate invariati; nessun nodo distrutto accettato senza prova completa destroy/remover. Questa è la raccomandazione; non è attiva prima della decisione PO.
2. Lasciare REM-0019 bloccata e conservare PR #254 draft. Proseguire solo con le unità indipendenti già autorizzate; nessun nuovo candidato o run volto ad aggirare il budget.

## Impatto e prossima azione

Nessuna riparazione 3, modifica dell'osservatore, nuova campagna, sigillo o merge del candidato è stata eseguita in questa iterazione. REM-0019 e il percorso ordinato REM-0023 → 0056 restano bloccati; G6 non parte. REM-0028 è eseguibile dopo REM-0024 e REM-0033 già integrate: riprendere il WIP `19747383d3d570b2ffbb503a1878c49d140b8032` senza riscriverne la storia, poi la coda indipendente del PO. Nessun blocco globale del loop e nessun nuovo REM assegnato per aggirare il budget.

`inputs/` intatto; nessun nuovo DEC, nessuna modifica a sigilli storici; E1=0, E2=0, zero Verified e claim NO-GO invariati.
