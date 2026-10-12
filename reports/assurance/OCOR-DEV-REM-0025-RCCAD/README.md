# OCOR-DEV-REM-0025-RCCAD — C5: deduplica e ordinamento indicizzati dal contesto di isolamento

- **Status**: `SEALED` (2026-10-12T23:50:28.981451+00:00) dopo il verdetto `GO_FOR_EVIDENCE_SEAL`
  `OCOR-DEV-REM-0025-4e9f51a16664-0` (verifier: Grok 4.7 via Cursor CLI, processo, contesto e fornitore
  separati; Claude Code, implementatore di riserva, non verifica questo change set — `LOOP-ROLES`),
  nessun finding e nessun `NOT_EXECUTED` sull'HEAD `4e9f51a166644685831a46cc6204719df88acc35`; SHA256 del verdetto `b2629746008a134b05074bf9267c09f2e01fb526653179ef4bdd194ecc7ec950`.
  Sigillate anche le riqualifiche 0040/0050: cambiano soltanto i metadati del sigillo e gli hash
  nei manifest G4/G5 e nel record.
- **Fonte**: decisione del Product Owner `INFO-A` (2026-10-05, opzione 1 più verifica di
  conformità) e audit del 2026-10-12 in `reports/development/decision_requests/INFO-A.md`, che ha
  registrato `OCOR-DEV-REM-0025` come primo identificativo libero
  (`EXECUTION_STATE` → `remediation_status.REM_0025_C5_ISOLATION_SCOPED_DEDUP`).
- **Branch**: `governed/ocor-dev-rem-0025-c5-isolation-scoped-dedup`

## Ambito

| Osservazione | Correzione |
|---|---|
| P1 — un evento del contesto B con la stessa `idempotency_key` del contesto A era scartato in silenzio | `_seen_idempotency_keys` indicizzato da `(governed_context_digest, idempotency_key)` |
| P2 — lo stesso scarto attraverso `EventOperationsCoordinator` (backpressure e replay da DLQ), senza dead letter | stessa correzione: il coordinator delega a `CanonicalEventBackbone.publish`; `operations.py` invariato |
| P3 — un evento del contesto B messo in quarantena `OUT_OF_ORDER` per la sequenza del contesto A sullo stesso `aggregate_ref` | `_last_sequence` indicizzato da `(governed_context_digest, aggregate_ref)` |
| Criterio negativo — contesto non determinabile | `governed_context_digest` vuoto o non stringa: quarantena `MISSING_CONTEXT` prima di qualsiasi lookup di deduplica o ordinamento, nessuna pubblicazione |

Chiave scelta (ADD v1.3 §1.4, §3.2): l'envelope del PoC porta il contesto soltanto come
`governed_context_digest`, digest dell'intero `GovernedContext` (che include la tupla di
isolamento). Due digest diversi con la stessa tupla sono trattati come contesti diversi: il caso
limite produce al più una pubblicazione duplicata, mai una perdita o una quarantena tra contesti.

## Vincoli rispettati

- Nessun rilevamento "stessa chiave / payload diverso" e nessun'altra modifica della semantica di
  replay (`INFO-A` opzione 1): il replay nello stesso contesto resta un no-op, la sequenza non
  crescente nello stesso contesto resta `OUT_OF_ORDER`; chiave Kafka e partizionamento invariati.
- Deduplica durable non introdotta (assegnata a `OCOR-DEV-REM-0026` da `INFO-C`).
- `EventOperationsCoordinator` indicizza tentativi, poison e rilascio per `event_id`, che ADD v1.3
  §3.2 definisce `format: uuid` (identità del singolo evento): nessuna modifica, quindi nessuna
  riqualifica di `OCOR-DEV-0041` (`validate_evidence_input_drift.py` lo conferma).
- `c5/backbone.py` cambia, quindi `OCOR-DEV-0040` è riqualificato; l'allowlist del validator di
  piano, input sigillato della riqualifica REM-0022 CI di `OCOR-DEV-0050`, cambia, quindi 0050 è
  riqualificato con ambito di sola regressione. Nessun record sigillato è stato modificato;
  `test_ocor_dev_0040.py` e `test_ocor_dev_0041.py` sono byte-identici.
- Nessun test escluso, saltato o indebolito. `E1=0`, `E2=0`, nessun requisito `Verified`;
  runtime conformance, PoC-GO e Production readiness invariati (`NOT_ESTABLISHED` / `NO-GO`).
  Nessuna modifica a `inputs/`.

## TDD

Casi scritti per primi (`ocor-runtime/tests/tasks/test_ocor_dev_rem_0025.py`, commit `2116ec6`) ed
eseguiti sul codice non corretto in un worktree separato con venv propria: 10 casi falliscono per il
difetto (record del contesto B assente dal topic, `OUT_OF_ORDER` dalla sequenza dell'altro contesto,
`DID NOT RAISE` sul contesto mancante), il caso positivo del replay nello stesso contesto passa.
GREEN dopo la correzione (`aee560d`). Prova di mutazione: 5 mutanti su 5 uccisi, sorgente
ripristinato byte-identico.

## Evidenza

- `OCOR-DEV-REM-0025.json` / `.log`: record della remediation, raw JSONL dell'intera campagna.
- `reports/evidence/G4/OCOR-DEV-0040.requalified-rem0025.json` e
  `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0025.json` (con i rispettivi `.log`,
  byte-identici al raw della campagna): riqualifiche con `supersedes` esplicito; i manifest G4 e G5
  puntano ai nuovi record.
- Controllo meccanico riproducibile: vedi `reproducible_check` nel record (non è verifica
  indipendente).
