# OCOR-DEV-REM-0051-RCCAD — NCP-U06, backbone C5 su canonical-ingestion-envelope:1.2

Unità NCP-U06 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2, 5 e 7), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C5-001`, `NCR-C5-002` e
`NCR-C5-003` del registro.

Stato: `CANDIDATE_IN_PROGRESS`. Il backbone C5 ammette solo envelope `canonical-ingestion-envelope:1.2` chiusi
(schema di ADD v1.3 §3.2 alla lettera), con il principal di trasporto legato a `effective_principal_id`, la firma
Ed25519 del produttore su envelope e digest del payload, il `marking_digest` verificato sull'oggetto del marking
(altrimenti `DENY`, quarantena `GOVERNED_CONTEXT_MISMATCH` e Audit Record), la seconda validazione del payload
contro lo schema content-addressed, la policy, le quote per tenant e `ResourceClass` (`AUDIT` mai rifiutato), la
deduplica durevole e la revisione crescente per aggregato. La tassonomia `TRANSIENT`/`PERMANENT`/`POLICY_DENIED`/
`POISON` usa backoff esponenziale con jitter e budget di retry; DLQ, quarantena, rilasci, sottoscrizioni e
checkpoint sono tabelle PostgreSQL append-only. `Subscribe` consegna per `subscription_id` e cursore opaco, senza
partizioni né offset; `Replay` dichiara finestra e motivo, è autorizzato e non ripubblica. Kafka è parlato in
processo con `confluent-kafka`; il ciclo di vita del broker sta nello strumento di qualifica dei test. Il relay C3
produce envelope 1.2 firmati in modalità CDC e il projector C4 li consuma. RED `99c1308`, GREEN `69dba37`;
composizione C3 -> C5 (RED `1eda7c3`, GREEN `9f801de`, refactor `019bd2b`); adattamento dei consumer (RED
`da91548`, GREEN `8d087a5`); controllo del marking in admission (RED `5a1720c`, GREEN `2000ee0`). Dipendenze del
punto 7 in `48eb6fe` (46 pacchetti, licenze e scansione delle vulnerabilità nel record).

Il record `OCOR-DEV-REM-0051.json` contiene criteri, test, ancore, test riallineati o adattati con il confronto
dell'albero sintattico, scelte di prodotto, ambiguità risolte in modo fail-closed, il punto aperto sulla
riproduzione del `governed_context_digest` in admission e la classificazione delle riqualifiche: tutte di sola
regressione (`0002`–`0015`, `0019`, `0020`, `0022`, `0023`, `0071` per `uv.lock`/`pyproject.toml`; `0040` e `0041`
senza requisiti legabili secondo `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`; `0005`, `0050`, `0082`).
Seguono PRE-CAMPAIGN-GATE, revisione preventiva, campagna con le riqualifiche e verifica indipendente, da un
fornitore diverso da Anthropic.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, slice legacy, guard o workflow è modificato; dipendenze aggiunte solo come autorizza il punto 7.
`E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
