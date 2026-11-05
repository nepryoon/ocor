# OCOR-DEV-REM-0052-RCCAD — NCP-U05, proiezioni C4

Unità NCP-U05 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2, 5 e 8), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C4-001`, `NCR-C4-002`,
`NCR-C4-003`, `NCR-C4-004`, `NCR-C4-005` e `NCR-C2-013` del registro (le ultime due registrate dall'opzione B1 di
`NCP-U05-ITERATION-LIMIT (2026-11-05)`).

Stato: `CANDIDATE_IN_PROGRESS`. La proiezione TypeDB dichiara la release che proietta, deduplica per store, branch
e `commitId`, sostituisce il watermark nella transazione di proiezione e lo conferma in un ledger durevole su
PostgreSQL fuori dallo store; ogni risposta riporta branch, commit servito, watermark, release e staleness misurata,
e una proiezione irraggiungibile risponde `PROJECTION_NOT_READY` dal ledger. Ogni transazione TypeDB si chiude su
ogni percorso d'errore. Una sandbox TypeDB disposable serve `EXACT_AT_COMMIT(Cn)` per un commit superato; senza
emulazione la risposta è `UNSUPPORTED_CAPABILITY`, mai `AT_LEAST_COMMIT` (`BA-03`). Il rilevatore di drift
confronta con lo store canonico TerminusDB, mette in quarantena durevole e ricostruisce da un checkpoint firmato con
replay limitato. La proiezione Jena porta il commit canonico e l'oggetto di marking canonico di ADD v1.3 §3.2,
valutato con la `MarkingSchemeDefinition` (join conservativo in export, errori tipizzati); una pubblicazione di
provenienza è validata dal servizio SHACL di Fuseki sulle shape di ADD v1.3 §3.6 prima di diventare visibile
(`NCP-U05-FUSEKI-SHACL-SERVICE (2026-11-05)`, opzione 1: `deploy/bootstrap/fuseki/config.ttl`). RED `0d22acc`,
`67da95d`, GREEN `fb9e20a` (NCR-C4-001, NCR-C4-003); RED `49b7616`, GREEN `5af48a9` (NCR-C4-004); RED `36cc66a`,
GREEN `2547123` (drift); RED `a0f52ae`, GREEN `7d5c4c1` (Jena); RED `7a39c51`, GREEN `437852a` (SHACL).
Con `NCP-U05-FUSEKI-CONFIG-LANGUAGE-POLICY (2026-11-05)`, opzione 1, il gate della policy dei linguaggi autorizza
il solo percorso esatto `deploy/bootstrap/fuseki/config.ttl` (RED `d7c21f1`, GREEN `a7e859f`). Con
`NCP-U05-ITERATION-LIMIT (2026-11-05)`, opzione B1, la proiezione degli oggetti irraggiungibile risponde
`PROJECTION_NOT_READY` e il Gateway costruisce `PROJECTION_NOT_READY` con il contesto servito dal watermark
confermato, anche per la `TypeDBUnavailableError` della porta del watermark (RED `5a07eb0`, con il riallineamento
autorizzato di `test_ocor_dev_rem_0049.py` riga 1425, GREEN `599e865`); con l'opzione C1 le sei operazioni sugli
oggetti non sono query logiche nominate di `BA-03` e il pianificatore continua a rispondere `PROJECTION_NOT_READY`
a un `EXACT_AT_COMMIT(Cn)` superato.

Il record `OCOR-DEV-REM-0052.json` contiene criteri, test, ancore, test riallineati o adattati con il confronto
dell'albero sintattico, scelte di prodotto, ambiguità risolte in modo fail-closed, punti aperti, gli esiti
dell'inventario dei consumer e la classificazione delle riqualifiche: tutte di sola regressione (`0037`, `0038`,
`0039` senza requisiti legabili secondo `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`; `0034` per
`ocor-runtime/src/ocor_runtime/c2/gateway.py`; `0073`, `0074`, `0075`, `0077`, `0078`, `0079` per
`deploy/bootstrap/compose.yaml`; `0005`, `0050`, `0082`). Seguono PRE-CAMPAIGN-GATE, revisione preventiva,
campagna con le riqualifiche e verifica indipendente, da un fornitore diverso da Anthropic, entro le iterazioni
concesse dall'opzione A1 di `NCP-U05-ITERATION-LIMIT`.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, slice legacy, guard o workflow è modificato; il documento `OCOR_LANGUAGE_POLICY.md` resta invariato. `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`,
PoC e Production `NO-GO`.
