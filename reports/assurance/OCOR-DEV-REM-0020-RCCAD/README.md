# OCOR-DEV-REM-0020-RCCAD — MemorySearchService: predicati nell'indice, fattori HYBRID reali, stop epoch, dinieghi auditati

- **Status**: `SEALED` (2026-10-10T03:26:23.212571+00:00) dopo il verdetto `GO_FOR_EVIDENCE_SEAL`
  `OCOR-DEV-REM-0020-4f1c4ef439a1-0` (verifier: Grok 4.7 via Cursor CLI, processo, contesto e fornitore
  separati; Claude Code non verifica questo change set), nessun finding e nessun `NOT_EXECUTED`
  sull'HEAD `4f1c4ef439a1c0fc6c2a42742c8069756373af8e`; SHA256 del verdetto `9f7c58a8ef2957e7bbcf46ea4f52996233f0268972bf85c57bc391464c29e970`.
  Sigillati anche le tre riqualifiche 0050/0051/0052: cambiano soltanto i metadati del sigillo e
  gli hash nel manifest G5 e nel record
- **Fonte**: decisione del Product Owner `OCOR-DEV-0052-INDEPENDENT-REVIEW` (2026-10-09),
  revisione indipendente del merge `ae296eb` (PR #192). Il GO e il sigillo di `OCOR-DEV-0052`
  restano storici: la correzione avviene con supersession esplicita.
- **Dipendenza**: obbligatoria per `OCOR-DEV-0057` e per la chiusura di G5.
- **Branch**: `governed/ocor-dev-rem-0020-memory-search-pushdown`

## Ambito

| Finding | Severità | Correzione |
|---|---|---|
| F1 | alta | (a) kind, scope, filtri strutturati, versione head, `ACTIVE`, validità a `valid_at` e scadenza sul clock del boundary valutati dentro la query (WHERE PostgreSQL, payload filter Qdrant) con rivalidazione post-query completa; (b) un commit ritira le proiezioni del predecessore: è ricercabile solo la head `ACTIVE`; (c) `STRUCTURED` restituisce il top-k deterministico; (d) backpressure solo sul limite dichiarato `max_candidates`, applicato ai candidati scartati dopo la query |
| F3 | media | in `HYBRID` ogni candidato dell'unione dei due pool riceve il fattore reale dall'altro backend; un candidato senza la rappresentazione fissata non è classificabile e viene escluso |
| F4 | media | stop epoch ricontrollato prima del ciclo, dopo ogni hit materializzato e prima della ricevuta |
| F5 | bassa | ogni rifiuto successivo alla pianificazione produce un evento `searchMemory.denied` |
| F6 | bassa | casi positivi e negativi per `ENVELOPE_INVALID`, `GCS_INVALID`, `POLICY_DECISION_INVALID` pre e post query, `STOP_STATE_INVALID`, `MATERIALIZED_DIGEST_MISMATCH`, `STALE_POLICY` in materializzazione, deadline dopo il ranking, hit senza explanation, `valid_at` storico |

Fuori ambito, tracciato verso `FGM-16`: **F2** (influenza degli item negati dalla policy dentro
una partizione autorizzata su errore e lavoro svolto). Misura dopo la correzione: 0, 40 e 130
item negati costano 1, 6 e 15 lookup all'indice, come la baseline della revisione, e a 130 la
ricerca fallisce ancora con backpressure: F1 non lo peggiora.

## Vincoli rispettati

- Contratto OpenAPI pubblico invariato; profili di ranking e query contract invariati.
- Port interni evoluti con adapter versionati (port versione 2 di indici e metadata); gli adapter
  di 0051 implementano la versione 2. `stores.py` e gli adapter di 0051 cambiano, quindi 0051 è
  riqualificato; `retrieval.py` cambia, quindi 0052 è riqualificato; l'allowlist del validator di
  piano, input sigillato della riqualifica di 0050, cambia, quindi 0050 è riqualificato. Nessun
  record sigillato è stato modificato.
- Nessun test escluso, saltato o indebolito: nei test 0052 cambiano soltanto le asserzioni che
  codificavano i difetti (tre `audit.events == []` dopo un rifiuto post-pianificazione; la
  backpressure prodotta da item `QUARANTINED`), come richiesto dalla decisione.
- `E1=0`, `E2=0`, nessun requisito `Verified`; runtime conformance, PoC-GO e Production
  readiness invariati (`NOT_ESTABLISHED` / `NO-GO`). Nessuna modifica a `inputs/`.

## TDD

Scenari R2–R6 della decisione scritti per primi (`tests/tasks/test_ocor_dev_rem_0020.py`,
commit `07f7dbf`) ed eseguiti sul codice non corretto (`origin/main` `2c110c1`, worktree
separato con venv propria): R2b, R3, R4 (top_k 20 e 10), R5 e R6 falliscono. L'R2 letterale
**passa** anche sul codice non corretto in questo ambiente (la query FULL_TEXT richiede tutti i
termini e "patrol report" non corrisponde; in VECTOR la finestra di risultati di Qdrant termina
prima del limite): è mantenuto e affiancato da R2b, che riproduce la classe di difetto di F1 con
item di altro kind che corrispondono alla query. GREEN dopo la correzione (commit `408eb1c`).

## Evidenza

- `OCOR-DEV-REM-0020.json` / `.log`: record della remediation, raw JSONL dell'intera campagna.
- `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0020.json`, `OCOR-DEV-0051.requalified.json`,
  `OCOR-DEV-0052.requalified.json` (con i rispettivi `.log`, byte-identici al raw della campagna):
  riqualifiche con `supersedes` esplicito; il manifest G5 punta ai nuovi record.
- Controllo meccanico riproducibile: vedi `reproducible_check` nel record (non è verifica
  indipendente).
