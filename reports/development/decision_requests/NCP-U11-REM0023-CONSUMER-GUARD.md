# NCP-U11-REM0023-CONSUMER-GUARD

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0059`
(NCP-U11 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, memoria governata; branch
`governed/ocor-dev-rem-0059-ncp-u11-governed-memory`) e la voce `NCR-MEMORY-003` di
`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`. Aperta secondo il punto 7 di
`NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)` («Se fallisce un altro test, fermati e apri una decision
request») e il punto 1 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`. Implementatore: Claude Code (Anthropic),
implementatore di riserva del loop.

## Contesto

- `NCR-MEMORY-003` (gravità `HIGH`, requisito `FR-118`, `plan_unit` `NCP-U11`): `requestMemoryDeletion`
  deve eseguire i quattro valori di `deletion_scope` del contratto
  (`ocor-runtime/docs/governance_dossier/contracts/ocor-governed-memory.openapi.yaml` riga 273; LLD v1.1
  `docs/OCOR_LLD_v1.1.md` riga 421). Il punto 5 di `NORMATIVE-CONFORMANCE-PLAN`, tabella, riga NCP-U11, ha già
  deciso la scelta per `ocor-runtime/tests/tasks/test_ocor_dev_0055.py` righe 481-483: «I tre casi passano a un
  test positivo di cancellazione, con almeno lo stesso numero di casi».
- L'unità ha eseguito quella scelta (commit `50fdb6e` del branch dell'unità, RED; commit `2a017be`, GREEN): i
  casi `latest only`, `project scope` e `principal scope` escono da `INVALID_DELETIONS` (le quattro voci
  restanti e le asserzioni di `test_invalid_deletion_requests_change_nothing_and_are_audited` non cambiano) ed
  entrano in `DECLARED_DELETIONS`, parametrizzazione del nuovo test positivo
  `test_declared_deletion_scopes_forget_the_item_through_the_saga` (tre casi, stessi identificativi). Con la
  correzione, i tre casi passano.
- Il guard della decisione `REM-0023-DENIAL-AUDIT-CONSUMER-FIXTURES (2026-10-22)`,
  `reports/tests/test_rem0023_consumer_fixture_scope.py` (eseguito anche da
  `ocor-runtime/tests/tasks/test_ocor_dev_rem_0023.py::test_consumer_fixture_scope_and_durable_sink`, righe
  406-419), confronta `test_ocor_dev_0054.py` e `test_ocor_dev_0055.py` con il commit `7cfb60d` e ammette come
  sola differenza il cablaggio del port di audit (`StripWiring`, righe 36-71; `compare`, righe 75-107):
  stesso elenco di funzioni di test, stesse asserzioni, stessi `pytest.raises` e decorator, stesso albero a
  meno del cablaggio. Lo spostamento autorizzato dei tre casi cambia l'elenco dei test, le parametrizzazioni e
  l'albero di `test_ocor_dev_0055.py`, quindi i due test del guard falliscono (`test/assert/pytest.raises/
  decorator changed`). Nessun'altra differenza: sul branch dell'unità passano 562 casi di unità, 0055, 0056,
  0059 e REM-0023, tranne questi due.
- Il guard non è fra i guard di invarianza della CI della definizione di `NORMATIVE-CONFORMANCE-PROGRAMME`
  (non compare nei workflow), ma è un test esistente che né il piano né il punto 5 elencano per NCP-U11; il suo
  valore fissato è la struttura di un file che l'unità modifica, non una sha256 (caso 2 del punto 5).

## Opzioni

1. **Il guard ammette esattamente la differenza autorizzata (raccomandata).** NCP-U11 estende
   `reports/tests/test_rem0023_consumer_fixture_scope.py` in modo che, per `test_ocor_dev_0055.py`, il
   confronto con `7cfb60d` tolga dall'albero nuovo, oltre al cablaggio di audit, soltanto la differenza della
   scelta del punto 5 per NCP-U11: le tre voci tolte da `INVALID_DELETIONS` (confrontate per valore con quelle di
   `7cfb60d`), l'assegnazione `DECLARED_DELETIONS` con gli stessi tre identificativi e gli stessi
   `deletion_scope`, e la funzione `test_declared_deletion_scopes_forget_the_item_through_the_saga` con la sua
   parametrizzazione, confrontata byte per byte con un testo fissato nel guard. Ogni altro controllo resta:
   funzioni, asserzioni, `pytest.raises`, decorator e albero di `test_ocor_dev_0054.py` e del resto di
   `test_ocor_dev_0055.py` invariati, mutazioni rifiutate (con un caso negativo in più: una quarta voce tolta da
   `INVALID_DELETIONS`, o un caso tolto da `DECLARED_DELETIONS`, fa fallire il guard). Il record dell'unità lo
   elenca come adattamento, con il confronto dell'albero sintattico. Effetto: la scelta del PO si applica e il
   guard resta stretto su tutto il resto.
2. **Nessuno spostamento: i tre casi restano in `INVALID_DELETIONS` con un input non dichiarato.** Si applica
   l'alternativa (b) che il piano aveva proposto: i tre casi restano dove sono, con un `deletion_scope` non
   dichiarato di pari severità, e il nuovo test positivo si aggiunge senza toccare `INVALID_DELETIONS`. Cambia
   comunque l'albero del file (le tre voci e il nuovo test), quindi serve la stessa estensione del guard
   dell'opzione 1; contraddice inoltre la scelta (a) già decisa dal PO nella tabella del punto 5.
3. **Il test positivo in un modulo nuovo, `test_ocor_dev_0055.py` invariato.** I tre casi restano in
   `INVALID_DELETIONS` con l'attesa attuale (`UNSUPPORTED_CAPABILITY`), che però contraddice
   `NCR-MEMORY-003`: la voce non si risolve finché quei casi asseriscono il rifiuto. Effetto: il guard passa,
   `NCR-MEMORY-003` resta aperta e `OCOR-DEV-0062`, bloccato dalla voce, resta bloccato.

## Raccomandazione

Opzione 1: realizza la scelta del PO già decisa, limita la nuova tolleranza del guard alla sola differenza
autorizzata, confrontata per valore, e aggiunge un caso negativo; il guard resta fail-closed per ogni altra
modifica di `test_ocor_dev_0054.py` e `test_ocor_dev_0055.py`.

## Impatto e lavoro bloccato

- Bloccati in attesa della decisione: la chiusura di `NCR-MEMORY-003` in NCP-U11 (il guard fallisce sul branch
  dell'unità) e quindi la campagna qualificante e la verifica indipendente di `OCOR-DEV-REM-0059`.
- Non bloccati: il resto di NCP-U11 (`NCR-MEMORY-001`, `002`, `004`, `005`), l'inventario dei consumatori e le
  riqualifiche.
- Nessun nuovo `DEC-*`; ADD, LLD, contratti, schemi, registri normativi, limiti e claim invariati
  (`E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`).
