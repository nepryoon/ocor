# OCOR-DEV-REM-0059-RCCAD — NCP-U11, memoria governata

Unità NCP-U11 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2 e 5), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-MEMORY-001` … `NCR-MEMORY-005`
del registro, con il criterio aggiuntivo del punto 2: gli adapter reali della memoria di
`test_ocor_dev_0051.py` passano nel pacchetto (`ocor_runtime/memory/adapters.py`, `9074905`) con lo stesso
comportamento.

Stato: `CANDIDATE_IN_PROGRESS` (iterazione 3 di stima 3, stop a 9), prima della revisione preventiva.

- `NCR-MEMORY-001` (FR-119, LLD v1.1 :214, :397): la partizione di policy pre-query arriva all'item; gli item
  negati sono esclusi dentro le query PostgreSQL e Qdrant e non influenzano pagina, lavoro, rank né errore
  (RED `7b930a8`, GREEN `ab65f96`).
- `NCR-MEMORY-002` (LLD v1.1 :206, :400): `admitMemory` verifica la quota sotto la serializzazione di
  partizione prima dell'unico append atomico; l'output della consolidazione è contato all'ammissione
  (RED `a837a53`, GREEN `f527ca4`).
- `NCR-MEMORY-003` (contratto :273, LLD v1.1 :421, ADD v1.3 :3836, FR-118): i quattro `deletion_scope`
  dichiarati sono eseguiti dalla saga (RED `50fdb6e`, GREEN `2a017be`); i tre casi di `test_ocor_dev_0055.py`
  passano al test positivo per scelta del PO (punto 5).
- `NCR-MEMORY-004` (contratto :21-29, ADD v1.3 :3761, :3789): `getMemoryItemVersion` è una lettura governata,
  filtrata dalla policy e auditata (RED `2dd02ec`, GREEN `8725b61`).
- `NCR-MEMORY-005` (ADD v1.3 :3763, :3797-3799, LLD v1.1 :202): le proiezioni full-text e vettoriali committate
  sono ricostruibili da metadata, contenuto e journal di ammissione (RED `e374937`, GREEN `f73b341`).
- Guard REM-0023: esteso secondo `NCP-U11-REM0023-CONSUMER-GUARD (2026-11-09)`, opzione 1, decisa su delega
  completa del PO (`8d7fee6`); il file della decision request entra con l'allowlist (`17bddd8`).
- `SELF-CHECK-CHECKLIST (2026-11-08)`: autocontrollo dell'intero `adapters.py` e delle classi toccate di
  `retrieval.py`, `model.py`, `operations.py`, `lifecycle.py` e `stores.py`, 28 righe nel record; RED `573ca0b`
  (94 casi falliti sulle lacune), GREEN `c5952e8` (100 casi passati; consumer della memoria 1357 passati,
  0 falliti, 0 skip sul PostgreSQL reale con Qdrant e OpenBao per modulo).

Riqualifiche previste, tutte di sola regressione (`NCP-UNBINDABLE-REQUALIFICATIONS`,
`NCP-U01-SUPERSESSION-REQUALIFICATIONS` punto 3, `REM-0046-REGRESSION-REQUALIFICATION-RECORDS`):
`OCOR-DEV-0005`, `0050`, `0051`, `0052`, `0054`, `0055`, `0059`, `0061`, `0082`.

Nessun nuovo `DEC-*`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e
Production `NO-GO`. Il record non è evidenza finché la campagna qualificante, la verifica indipendente e il
sigillo non sono completati.
