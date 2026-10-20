# OCOR-DEV-REM-0019-RCCAD — OCOR-DEV-0049: ogni test eseguibile da solo e in qualsiasi ordine

- **Status**: `SEALED` (2026-10-14T00:47:35.529232+00:00), dopo `GO_FOR_EVIDENCE_SEAL` `OCOR-DEV-REM-0019-90b30fff9819-1` su `90b30fff981935cb48f63a890ec13f33190591e8`, verifier Grok 4.7 via Cursor CLI. Sigillo su branch dedicato; integrazione su `main` pendente dopo REM-0017 e check obbligatori verdi. Le campagne precedenti riportate sotto restano diagnostiche; la campagna qualificante finale è nel record `.r1-marker.json`.
- **Fonte**: presa d'atto PO del 2026-10-09 sul vincolo d'ordine di `test_ocor_dev_0049.py` e decisione
  PO `REM-0017-CI-0049-REMAINDER-CAP` (2026-10-10, opzione 2: nessun tetto speciale, si correggono prima i
  test di 0049). Identificativo verificato libero il 2026-10-09 (`git grep` su tutti i ref).
- **Branch**: `governed/ocor-dev-rem-0019-0049-test-isolation`, radicato sul candidato sigillato di `OCOR-DEV-0049`
  (`df444af855e884d7783612b302e008b90105fe13`, GO `b14e4bf`, PR #176 aperta): il modulo non esiste su `main` e 0049 si
  integra dopo la chiusura verificata di `OCOR-DEV-REM-0017`, che fisserà l'HEAD verificato di questo branch
  al posto di `df444af`.
- **Commit di codice**: `4c21be312bebd80f2d30f37c7a2febd5afb1aa5b` — cambia soltanto `ocor-runtime/tests/tasks/test_ocor_dev_0049.py`;
  il codice di produzione di 0049 (`deploy/helm/ocor-poc/`) è invariato.

## Ambito chiuso

Solo il codice di test di 0049 (modulo e fixture). Stessi 390 casi (corrispondenza uno a uno per node id:
nessun caso rimosso, unito, spezzato, rinominato o aggiunto) e stesse asserzioni: per ciascuna delle 72
funzioni di test il multiset di `assert`, `pytest.fail/raises` e helper che asseriscono è identico; nei 2
test che ora osservano un carrier proprio cambia solo il nome dell'oggetto osservato (`stack.ops` → `ops`).

## Analisi delle dipendenze (sul candidato `df444af`)

| Test | Casi | Dipendenza | Correzione |
|---|---|---|---|
| `test_ops_process_serves_health_and_blocks_readiness_until_restore_is_tested` | 1 | osservava il carrier ops condiviso prima di ogni restore: falliva se un test precedente aveva gia' prodotto una receipt | fixture untested_ops: carrier Compose proprio su vault vuoto |
| `test_backup_seals_an_encrypted_signed_immutable_recovery_point` | 1 (produttore) | produttore, non dipendente (passa da solo su df444af): sigillava il recovery point del vault condiviso (len == 1) consumato dai test successivi | sigilla in un vault proprio; il recovery point condiviso lo produce la fixture tested |
| `test_isolated_restore_replays_tombstones_and_passes_the_recovery_gate` | 1 | richiedeva il recovery point del test di backup e produceva la receipt e replay_digest usati dai test successivi | fixture tested; restore in una copia del vault condiviso senza receipt; replay_digest fissato da tested |
| `test_readiness_turns_ready_only_with_a_signed_passed_restore_receipt` | 1 | richiedeva la receipt del test di restore e un recovery point piu' recente dell'RPO (15 min), vero solo subito dopo il backup | fixture fresh_tested_ops: carrier proprio, sigillato e testato subito prima |
| `test_mutative_path_reopens_only_by_a_human_bound_to_the_passed_receipt` | 1 | richiedeva il percorso mutativo ancora chiuso: falliva dopo una riapertura umana precedente | fixture reopen_pending: un nuovo restore testato chiude il percorso (comportamento asserito dal test di replay) |
| `test_restore_replay_is_deterministic` | 1 | richiedeva receipt e replay_digest del test di restore | fixture tested |
| `test_tampered_recovery_point_is_rejected_before_restore` | 2 | richiedeva il recovery point del test di backup | fixture tested |
| `test_tampered_restore_receipt_blocks_readiness` | 1 | richiedeva la receipt del test di restore | fixture tested |
| `coherence_ops (fixture) e i 7 test che la usano` | 97 | copia del vault condiviso: richiedeva la receipt del test di restore | coherence_ops dipende da tested |
| `test_restart_under_another_release_profile_or_pins_blocks_readiness_reopen_and_admission` | 3 | richiedeva la receipt del test di restore | fixture tested |
| `test_restart_under_the_tested_release_is_ready_and_reopenable` | 1 | richiedeva la receipt del test di restore | fixture tested |
| `test_new_release_is_ready_only_after_its_own_backup_and_tested_restore` | 1 | copia del vault condiviso con la receipt del test di restore | fixture tested |
| `test_dependency_fault_blocks_readiness_and_degrades_posture` | 5 | richiedeva il carrier condiviso READY e riaperto da un umano (mutative ammesso per qdrant e kafka) | fixture reopened |
| `test_emergency_stop_denies_mutative_capabilities_within_10_seconds` | 1 | richiedeva il carrier condiviso READY e riaperto (mutative 200 prima dello stop) | fixture reopened |
| `test_open_public_egress_blocks_readiness` | 1 | governed_reopen sulla receipt del vault condiviso | fixture tested |
| `test_public_network_dependency_prevents_the_process_from_starting` | 1 | montava stack.work/agent.py scritto dal primo agente standalone di un altro test | agent.py scritto dalla fixture stack |
| `test_logs_and_traces_carry_governed_fields_and_no_secrets` | 1 | richiedeva nei log del carrier condiviso un DEPENDENCY_DOWN (prodotto dai test di fault) e un READY | fixture fault_observed: pausa e ripresa di qdrant, poi READY |

Lo stato live condiviso è ora prodotto da fixture esplicite e idempotenti richieste dal test che ne ha
bisogno (`tested`, `reopen_pending`, `reopened`, `fault_observed`, `untested_ops`, `fresh_tested_ops`), mai
da un altro test. I restanti 271 casi non avevano stato live condiviso.

## TDD — RED sul candidato sigillato

Copia non tracciata del modulo di `df444af` (stesso `ROOT`), un processo pytest per gruppo; rimossa dopo il RED.

| Gruppo | Ordine | Casi falliti |
|---|---|---|
| `ready-alone` | test_readiness_turns_ready_only_with_a_signed_passed_restore_receipt | test_readiness_turns_ready_only_with_a_signed_passed_restore_receipt |
| `publicdep-alone` | test_public_network_dependency_prevents_the_process_from_starting | test_public_network_dependency_prevents_the_process_from_starting, test_public_network_dependency_prevents_the_process_from_starting |
| `logs-alone` | test_logs_and_traces_carry_governed_fields_and_no_secrets | test_logs_and_traces_carry_governed_fields_and_no_secrets |
| `estop-alone` | test_emergency_stop_denies_mutative_capabilities_within_10_seconds | test_emergency_stop_denies_mutative_capabilities_within_10_seconds |
| `fault-alone` | test_dependency_fault_blocks_readiness_and_degrades_posture[qdrant] | test_dependency_fault_blocks_readiness_and_degrades_posture[qdrant] |
| `coherent-alone` | test_custodian_signed_coherent_receipt_is_accepted | test_custodian_signed_coherent_receipt_is_accepted |
| `untested-after-restore` | test_backup_seals_an_encrypted_signed_immutable_recovery_point, test_isolated_restore_replays_tombstones_and_passes_the_recovery_gate, test_ops_process_serves_health_and_blocks_readiness_until_restore_is_tested | test_ops_process_serves_health_and_blocks_readiness_until_restore_is_tested |
| `reopen-after-replay` | test_backup_seals_an_encrypted_signed_immutable_recovery_point, test_isolated_restore_replays_tombstones_and_passes_the_recovery_gate, test_restore_replay_is_deterministic, test_mutative_path_reopens_only_by_a_human_bound_to_the_passed_receipt | test_mutative_path_reopens_only_by_a_human_bound_to_the_passed_receipt |

## Prova di indipendenza (commit di codice, stack `ocor-bootstrap` reale, zero skip, nessun residuo)

| Run | Seed | Posizione del caso Helm | Esito | Durata |
|---|---|---|---|---|
| `order-collection` | - | 386 | 390/390 | 2356.6 s |
| `order-reverse` | - | 3 | 390/390 | 2407.3 s |
| `order-seed-190001` | 190001 | 268 | 390/390 | 2387.9 s |
| `order-seed-190002` | 190002 | 237 | 390/390 | 2417.4 s |
| `order-seed-190003` | 190003 | 158 | 390/390 | 2392.7 s |

Ordine eseguito = ordine richiesto (verificato sul JUnit di ogni run); stesso insieme dei 390 node id
raccolti. Esecuzioni isolate: 119 processi pytest, uno per ciascun caso dell'analisi, tutti PASS
senza residui. Partenza dei run allineata al tick `*/15` del caso Helm (ritardo soltanto, dichiarato per run).

Tentativo non qualificante registrato e rieseguito: `attempt1-order-reverse` (389/390 PASS, fallito `test_helm_profile_on_kubernetes_backs_up_restores_and_gates_readiness`): containerd del nodo kind terminato da SIGSEGV (status=11/SEGV) alle 14:45:00Z, al tick */15 della CronJob, mentre girava il pod del backup manuale: capture-kafka exit 255, job fallito (backoffLimit 0). Difetto locale dell'host gia' registrato come REM-0017-KIND-CONTAINERD-CRASH (decisione PO REM-0017-CI-CAMPAIGN-DURATION: diagnosi nel change set REM-0017, nessun cambio di immagine o versione). Nello stesso run gli altri 389 casi in ordine inverso sono PASS. Anche nel run order-collection containerd e' crashato (14:14:57Z) senza colpire container in esecuzione. L'ordine inverso e' stato rieseguito.


## Evidenza

- `OCOR-DEV-REM-0019.json` / `.log`: record della remediation e raw JSONL dell'intera campagna (credenziali
  locali generate redatte).
- `reports/evidence/G4/OCOR-DEV-0049.requalified-rem0019.json` / `.log` (raw byte-identico): riqualifica di
  `OCOR-DEV-0049` con `supersedes` esplicito del record sigillato `OCOR-DEV-0049.json`, che resta storico e
  invariato insieme al GO `b14e4bf`; il manifest G4 punta al nuovo record.
- Controllo meccanico riproducibile: `reproducible_check` nel record (non è verifica indipendente).

## Vincoli e claim

Nessun test escluso, saltato o indebolito; nessuna modifica a `inputs/`, a gate, workflow o ruleset.
`E1=0`, `E2=0`, nessun requisito `Verified`; runtime conformance `NOT_ESTABLISHED`, PoC-GO e Production
readiness `NO-GO`.


## Ripresa 2026-10-13 — immagine kind e cleanup del setup

Decisione PO `REM-0019-KIND-CONTAINERD-SEGV-RECURRENCE`, opzione 1. Codice di test
`6e1c4b050ac610a22673d6f559e424a01705189c`: stessa minor Kubernetes v1.33, immagine ufficiale
v1.33.4 fissata a `sha256:25a6018e48dfcaee478f4a59af81157a437f15e6e140bf103f85a2e7cd0cbbf2`,
containerd v2.1.3 compilato con Go1.24.4 (lettura diretta `go version -m`; backport
upstream #73144 in Go1.24.3). Creazione e intero setup della fixture nel try/finally.
Prove locali RED 5 FAIL/3 PASS, GREEN 8/8; prova live con interruzione dopo l'attacco
alla rete: RED lascia nodo/volume, GREEN ripristina l'inventario iniziale.
Sorgenti delle prove, versioni, digest e hash dei raw nel campo `kind_node_repair`
del record WIP. Produzione 0049 e 390 casi/asserzioni immutati da questa correzione.

Tutte le tabelle e i conteggi precedenti in questa pagina sono storia diagnostica
per il nuovo commit: nessun conteggio trasferito. Campagna nuova full (2224 raccolti),
cinque ordini e 119 isolati in corso; nessun PASS finale o candidato sigillabile.
Adapter di osservazione v2 byte-identico, 14/14 prove deterministiche verdi.
Ciclo 1 invariato. Difetto del reset con rete occupata fuori scope: REM-0029 separata.

Implementatore di questa correzione: Codex (OpenAI); precedenti contributi di
Claude Code di riserva conservati. Verifier: Grok 4.7 tramite Cursor CLI, avviato
soltanto dal loop esterno dopo il completamento dell'evidenza e dei gate.
E1=0, E2=0, Verified=0 e claim NO-GO invariati.

## Sigillo 2026-10-14 — campagna finale e verdetto indipendente

Verdetto `OCOR-DEV-REM-0019-90b30fff9819-1`, SHA256 `ab73c069a892b5f189a5f865f5bd9370572e00e105be5582919f0a15ba625d30`. Campagna qualificante su `6e1c4b050ac610a22673d6f559e424a01705189c`: full 2224/2224, cinque ordini 390/390 ciascuno e 119 isolati, zero skip e zero residui. Riqualifica 0050 di sola regressione (198 casi invariati), difetto audit di diniego ancora REM-0023. Codex e Claude Code di riserva hanno contribuito alla riparazione; verifier Grok 4.7 (Cursor), contesto separato. In questa unità Codex modifica soltanto metadati di sigillo, README e hash dei manifest; raw log, prove e record storici invariati. Il run completo iniziale del verifier con problemi di PATH/SPIRE resta diagnostico, con i successivi controlli registrati integralmente nel verdetto. Integrazione task prima, governance dopo; mai governance nel branch task prima dello scope CI. E1=0, E2=0, Verified=0 e NO-GO invariati.

## Ciclo 3 (2026-10-20) — diagnosi di VF-001 e RED

Ciclo eccezionale 3 di `REM-0019-INTEGRATION-REPAIR-BUDGET` (opzione 1), eseguito fuori
dal loop da Claude Code (Anthropic, Opus 5.5) sotto supervisione del PO secondo
`REM-0019-INTEGRATION-REPAIR-CYCLE3-INTERACTIVE`. Candidato di partenza
`712fc2b799774281321c04209bfb6910b91f0941`, verdetto `OCOR-DEV-REM-0019-712fc2b79977-2`
(SHA256 `f2c98370867331e3399e74961cd6b5130aae10276b097455f3d34069276fdbc5`), VF-001
`NO_OWNED_REMOVER_IN_PYTEST_GROUP`. Osservatore non modificato prima della diagnosi.

### Causa: ipotesi (c), identità di `argv[0]` per symlink

- Il verifier ha eseguito la campagna da un worktree in `/tmp/ocor-verify-*/wt` privo di
  `.ocor/tools/bin`; prima delle campagne del verdetto vi ha creato
  `.ocor/tools/bin/kind` come **symlink** al binario ufficiale del checkout principale.
- `test_ocor_dev_0049.tool("kind")` restituisce il percorso **non risolto**: la fixture
  lancia `kind delete` con `argv[0]` = percorso del symlink.
- `run_qualifying_campaign.qualification_kind_binary()` restituisce il percorso
  **risolto**: `KIND_BINARY` = file reale.
- `observe_kind_teardown.owned_remover()` accetta il processo solo se
  `/proc/<pid>/exe` risolve a `KIND_BINARY` (vero: il kernel risolve il link) **e**
  `argv == [str(KIND_BINARY), 'delete', 'cluster', '--name', 'ocor-poc']` (falso: confronto
  di stringa su `argv[0]`). Nessun campione: `remover_observations` vuoto per l'intera
  durata di entrambe le campagne del verifier (pgid pytest 2630803 e 3665447).
- Nella full locale del ciclo 2 `argv[0]` era il file reale del checkout e il remover è
  stato osservato, vivo per circa 2,6 s (13 periodi da 0,2 s).

### Ipotesi discriminate

- (a) remover breve perso dal campionamento: **esclusa**. Nella riproduzione il remover
  resta vivo ≥ 7,6 s (≥ 38 periodi) e non è osservato nel layout symlink; nel layout
  reale lo è.
- (b) gruppo/sessione diversi per il lancio via `agent -p`: **esclusa**. Il supervisore
  crea comunque una nuova sessione per pytest (`start_new_session=True`); in entrambe le
  modalità pgid e sid del remover coincidono con il leader.
- (c) **confermata**: unico predicato v2 che diverge è `argv` esatto.

### Riproduzione sulla workstation

Sonda con osservatore e `qualification_kind_binary` del candidato invariati, binario kind
reale, `/proc` reale, leader in nuova sessione come pytest nella campagna; kind tenuto
vivo da un `docker` fittizio nel solo PATH di kind (nessun oggetto Docker toccato). Due
esecuzioni con esito identico:

| Layout | pgid/sid = leader | exe = KIND_BINARY | argv esatto | Vivo | Campioni |
|---|---|---|---|---|---|
| checkout reale (locale) | sì | sì | sì | ≥ 7,6 s | 1 |
| symlink in worktree (verifier) | sì | sì | **no** | ≥ 7,6 s | **0** |

Output privati della sonda (scratch di sessione, nessun dato di fixture): run 1
SHA256 `4d90324f5200501ac83963eec7ce45e5819e574eb5012eea753aa6be97e4a20a`, run 2
`06bfd6cdd7e3a90cfe61cb8a885ddb08551bf1a5fc0ababa66c53b932c4e0ebd`, sonda
`5fb1f9da0c1359a680dd8ac1e125f07c75303297a825ea2cc88a3509fddf6188`. Lo strumento
versionato e riproducibile è il RED sotto.

Versioni: kind v0.29.0 (go1.24.2, linux/amd64), Docker client/server 29.9.1, Python
3.12.11 (venv `ocor-runtime`), kernel 7.0.0-38-generic.

Suite completa in modalità verifier sul candidato non modificato: `NOT_EXECUTED` per
disposizione del PO; rifiuto già riprodotto due volte in modo deterministico con
osservatore, kind e `/proc` reali.

### RED

`reports/tests/test_qualifying_campaign_guard.py`, sei casi con campionatore reale, kind
reale e `argv[0]` prodotto dal vero `tool("kind")` di 0049 nel layout del verifier; ogni
caso verifica che il remover sia vivo per almeno cinque periodi, quindi un rifiuto non è
mai un campione perso.

- positivo, lancio via symlink del verifier: **FAIL** sul candidato (`AssertionError: []`);
- controllo, lancio dal file reale del checkout: PASS (lo strumento osserva);
- negativi che devono restare rifiuti: symlink verso un binario diverso, `argv[0]`
  relativo, cluster diverso, processo fuori dal gruppo pytest: PASS (zero osservazioni).

Fingerprint RED (SHA256 del JSON canonico `[nome, esito, messaggio]` ordinato):
`07cafaa2cba4b84f2a55d45666f9395986de780d102b770a1022c2c4a1f52358`. File di test intero:
1 failed, 134 passed.

E1=0, E2=0, Verified=0 e claim NO-GO invariati; nessun sigillo, merge o GO.
