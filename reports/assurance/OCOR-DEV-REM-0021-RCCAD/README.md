# OCOR-DEV-REM-0021-RCCAD — MemorySearchService: idoneità rivalidata dopo ogni lettura di contenuto

- **Status**: `SEALED` (2026-10-10T09:17:13.104114+00:00) dopo il verdetto `GO_FOR_EVIDENCE_SEAL`
  `OCOR-DEV-REM-0021-3845e4af0fc1-0` (verifier: Grok 4.7 via Cursor CLI, processo, contesto e fornitore
  separati; Claude Code non verifica questo change set), nessun finding e nessun `NOT_EXECUTED`
  sull'HEAD `3845e4af0fc110aa3cc571e4517533d507c124c1`; SHA256 del verdetto `9c8c01387ff21cc2e6238baea77882904555373bf1af53a08782d2160c0f8d67`.
  Sigillate anche le riqualifiche 0050/0052: cambiano soltanto i metadati del sigillo e gli hash
  nel manifest G5 e nel record.
- **Fonte**: finding `VF-002` (alta, bloccante) del verdetto indipendente
  `OCOR-DEV-0055-38b7734bd97f-0` (`NO_GO`, 2026-10-10): durante una ricerca `FULL_TEXT`, una
  revoca committata mentre veniva letto il contenuto di `x` lasciava comunque
  `urn:ocor:memory:x:v1` tra gli hit. Remediation entro il mandato `CC-OCOR-DELIVERY-COMPLETION`
  (§7, primo `REM-*` libero verificato: `0021`).
- **Perché un change set separato**: `memory/retrieval.py` non è tra le `expected_file_areas` di
  `OCOR-DEV-0055` ed è input sigillato di `OCOR-DEV-0052` (riqualificato da REM-0020). Il ciclo di
  riparazione 1 di `OCOR-DEV-0055` (VF-001, VF-003, VF-004 e il caso live di VF-002 al livello del
  lifecycle) segue dopo il merge di questo change set.
- **Branch**: `governed/ocor-dev-rem-0021-retrieval-post-read-eligibility`

## Ambito

| Finding | Severità | Correzione |
|---|---|---|
| VF-002 | alta | `_materialize` rivaluta l'idoneità completa (`_eligible`: head esatta committata, `ACTIVE`, senza deletion epoch, partizione, kind/scope, validità, scadenza, compartimenti, marking, filtri, policy di materializzazione live) e lo stage digest prima della lettura (invariato), dopo la lettura di ogni hit e su tutti gli hit subito prima della ricevuta; una versione cambiata fallisce chiusa con `REPRESENTATION_NOT_READY`/`CANDIDATE_CHANGED`, come il controllo pre-lettura, con diniego auditato `searchMemory.denied` |

## Vincoli rispettati

- Contratto OpenAPI pubblico, query contract, `RankingProfile` e relativi digest invariati;
  nessun port cambia; ordine dei controlli dello stop epoch invariato (uno stop prevale su un
  cambio di candidato).
- `retrieval.py` cambia, quindi 0052 è riqualificato; l'allowlist del validator di piano, input
  sigillato della riqualifica REM-0020 di 0050, cambia, quindi 0050 è riqualificato. Nessun record
  sigillato è stato modificato; `test_ocor_dev_0052.py` è byte-identico.
- Nessun test escluso, saltato o indebolito. `E1=0`, `E2=0`, nessun requisito `Verified`;
  runtime conformance, PoC-GO e Production readiness invariati (`NOT_ESTABLISHED` / `NO-GO`).
  Nessuna modifica a `inputs/`.

## TDD

Casi scritti per primi (`tests/tasks/test_ocor_dev_rem_0021.py`) ed eseguiti sul codice non
corretto (commit dei soli test su `origin/main` `0662051`, worktree separato con venv propria): i
casi negativi falliscono (`DID NOT RAISE`: la versione cambiata veniva restituita con una
ricevuta di successo), i positivi passano. GREEN dopo la correzione.

## Evidenza

- `OCOR-DEV-REM-0021.json` / `.log`: record della remediation, raw JSONL dell'intera campagna.
- `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0021.json` e
  `OCOR-DEV-0052.requalified-rem0021.json` (con i rispettivi `.log`, byte-identici al raw della
  campagna): riqualifiche con `supersedes` esplicito; il manifest G5 punta ai nuovi record.
- Controllo meccanico riproducibile: vedi `reproducible_check` nel record (non è verifica
  indipendente).
