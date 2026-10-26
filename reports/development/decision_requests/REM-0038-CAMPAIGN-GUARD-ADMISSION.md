# REM-0038-CAMPAIGN-GUARD-ADMISSION

Status: `OPEN_PO_DECISION_REQUIRED`. Riguarda l'ammissione, nei guard di invarianza
dell'harness di campagna, delle modifiche già autorizzate da decisioni del PO.
Nessuna variazione di limiti, timeout, finestre, cadenze, partizioni o casi.
Autorità corrente: decisione normativa del PO
`OCOR-DEV-0060-BA-SELECTED-COMPONENTS (2026-10-26)`, opzione 2, change set a
(`OCOR-DEV-REM-0038`); `REM-0019-INTEGRATION-REPAIR-BUDGET (2026-10-20)`, punto 4;
`LOCAL-FULL-SUITE-CAP-90 (2026-10-26)`; DEC-210/211.

## Contesto

`OCOR-DEV-REM-0038` (provisioning di Temporal con il proprio PostgreSQL e
admin-tools, e di SeaweedFS) ha ricevuto il verdetto esterno
`OCOR-DEV-REM-0038-dc5a404b350f-0` = `GO_FOR_EVIDENCE_SEAL` (Cursor CLI /
grok-4.7-high / xAI) ed è stata sigillata sul branch
`governed/ocor-dev-rem-0038-ba-services` al commit
`03edc31a8ced808259290bb055b807f2d97af562` (PR #357). La CI sull'HEAD esatto ha
11 check obbligatori su 13 verdi e due fallimenti reali, non infrastrutturali: nessun
rerun, nessun merge. Il branch sigillato e la PR restano preservati.

1. `tooling-policy` (run `40375838054`, passo «Validate manifests and Compose
   rendering» di `.github/workflows/ocor-tooling-bootstrap.yml`): il passo rende
   `deploy/bootstrap/compose.yaml` con segnaposto soltanto per le variabili
   obbligatorie preesistenti. Mancano `OCOR_LOCAL_SEAWEEDFS_PASSWORD` e
   `OCOR_LOCAL_TEMPORAL_POSTGRES_PASSWORD`. La correzione è in perimetro: due righe di
   segnaposto `x`, come le altre.
2. `validation-closure` (run `40375837616`, aggregato, passo «Execute conditional
   report guards and campaign supervisor tests»):
   `reports/tests/test_kind_teardown_observation.py` fallisce in due test,
   `test_bootstrap_probe_change_is_observation_only_against_main` e
   `test_execution_ast_and_workflows_are_identical`.

Il secondo fallimento è il quesito di questa richiesta. Quei due test applicano gli
invarianti del PO su finestra, timeout, cadenza, timer, partizione, selezione e gate
(`REM-0019-INTEGRATION-REPAIR-BUDGET`, punto 4, e `CI-0049-KIND-BOOTSTRAP-EXEC-PROBE`).
Confrontano `scripts/run_qualifying_campaign.py` e **tutti** i file
`.github/workflows/*.yml` con due baseline fisse:

- `9b4d3be8ec5bd785b02072a99037dd801b53d9a5`: AST dell'intero file, al netto della
  sola chiave esportata `bootstrap_recoveries`;
- `7cd5f7a30e04d1671fe122eff58dfb5f54fb58b0`: AST di ogni funzione e di tutte le
  assegnazioni a livello di modulo.

Ammettono soltanto le normalizzazioni esatte già enumerate nel test
(`retire_integrated_0049_pin`, `normalize_rem0034_secret_scanner`, il pin 0049 a 5
parti, lo spostamento dello scope gate). Ogni altra differenza fallisce, per
costruzione.

## Fatti

Artefatti fuori da Git, in `~/.ocor-codex/integrate-rem0038-20261026/`:

| Artefatto | sha256 |
|---|---|
| `red-ast-guard.log` (guard sull'HEAD sigillato: 2 falliti, 37 passati) | `b27282741c520862d6af55a34a8b046a33ef4f1a181899a22ab895600b8e41f3` |
| `probe-guard-workflow-only.log` (`origin/main` più i soli due segnaposto: 2 falliti) | `6f69cdcb00bf768d29a0e208c07b35f886b3c70f67b26774b9f40dae28a571bd` |
| `red-compose-config.log` (comando esatto del workflow, exit 1) | `376550e61bfcdccf8faed6645f2264d2723c9e6fa567b25514d0eda0601cffaf` |
| `green-probe-compose-config.log` (con i due segnaposto, exit 0) | `19eaf43821a7660ec323a87c8457bf74823beb296c39f5e01aa8a683aa50f061` |
| `repair1-workflow-placeholders.patch` | `9f21728bcb1f214dc66d9d951cff393b68119d28e95cfb899695bba94a942ac7` |
| `checkruns.json` (check run di `03edc31` dall'API GitHub) | `d6a4844b9a8acb6984f3b623ee51d038aef702e4c806e810407a7ec3d1ea3cff` |

- Sull'HEAD sigillato, con la sola `scripts/run_qualifying_campaign.py` riportata alla
  versione di `origin/main`, il modulo passa 39/39. La causa unica è quindi la modifica
  di REM-0038 a quel file:
  - nuova costante `MANDATORY_CONTAINERS = 15`;
  - in `main`, `len(initial) != 11` diventa `!= MANDATORY_CONTAINERS`;
  - in `observe_health_event`, `ids[:11]` diventa `ids[:MANDATORY_CONTAINERS]`. Questa
    funzione è già esclusa dal confronto, perché è diagnostica.

  Lo stack di bootstrap ha ora 15 container: il controllo di campagna con 11 rifiuterebbe
  ogni campagna sullo stack vigente.
- Anche la sola correzione di `tooling-policy` fa fallire gli stessi due test, perché
  modifica un workflow (`probe-guard-workflow-only.log`).
- Anche `OCOR-DEV-REM-0042` (`LOCAL-FULL-SUITE-CAP-90`) li farà fallire, perché cambia
  `FULL_SUITE_LIMIT_SECONDS` («Campaign constants drift»). Lo stesso vale per ogni futura
  modifica autorizzata a quel file o ai workflow, per esempio il provisioning CI dei
  servizi di REM-0039–0041.
- Perché non è emerso prima del push: le suite locali di REM-0038 e del verifier non
  comprendevano questo modulo di `reports/tests/`, che gira soltanto nell'aggregato di
  `validation-closure`. Non è un difetto del verdetto, ma una lacuna di copertura dei
  gate locali, da chiudere nella riparazione eseguendo i guard dell'aggregato prima
  della campagna.
- Riqualifiche: il modulo di test e lo script compaiono soltanto in record di
  assurance di REM-0017, REM-0019, REM-0029, REM-0030 e REM-0033, non negli `inputs`
  del record più recente di alcun task completato. Il validator di deriva resta a 0 sia
  sull'HEAD sigillato sia con la patch.
- Dato registrato, non un quesito: sulla PR #357 il job più lungo è
  `delivery-activation part 4/4`, 1859 s; seguono `validation-closure part 4/4`, 1844
  s, e `rccad-methodology part 4/4`, 1729 s, con `timeout-minutes: 75` per le parti.
  Sulla PR #354, prima dei servizi nuovi, il massimo era 1881 s
  (`rccad-methodology part 4/4`). Nessun job è stato cancellato al limite e non risulta
  un aumento attribuibile ai container nuovi.

## Opzioni

1. **Normalizzazione esatta ed enumerata per ogni modifica autorizzata.** Nel solo
   `reports/tests/test_kind_teardown_observation.py` si aggiunge una funzione di
   normalizzazione per REM-0038, sul modello di `retire_integrated_0049_pin`. Riporta
   esattamente la nuova costante e le due sostituzioni di `11` (in `main` e nel
   comando diagnostico) alla forma della baseline e aggiunge i due segnaposto al
   workflow di tooling. Ogni sostituzione si applica con un conteggio verificato.
   - Aggiunge test negativi che dimostrano che qualunque altra differenza continua a
     fallire: un'altra costante, un'altra funzione, `MANDATORY_CONTAINERS` diverso da
     15, una riga di workflow in più.
   - Le baseline, i controlli su `WINDOW_SECONDS`, `POLL_SECONDS`, `SAMPLE_SECONDS`,
     `KIND_BINARY`, i timeout delle sonde a 10 s e l'esclusione di
     `observe_health_event` restano invariati.
   - `OCOR-DEV-REM-0042` e le REM successive aggiungeranno ciascuna la propria
     normalizzazione esatta nello stesso modo, ognuna citando la decisione che la
     autorizza.
   - Rientra nella riparazione 1 di REM-0038 e nella verifica esterna ordinaria.
2. **Nuova baseline.** Le due baseline del test passano al merge di REM-0038, con gli
   stessi controlli. È più semplice, ma cancella dalla prova la catena di
   normalizzazioni che lega l'attuale harness alle revisioni qualificate da
   REM-0019/REM-0033. Inoltre ogni futura modifica autorizzata richiederebbe un nuovo
   cambio di baseline, con lo stesso quesito.
3. **Nessuna modifica al guard.** Si lascia invariato il controllo di campagna a 11
   container e si toglie la modifica da REM-0038. È impraticabile: la campagna
   rifiuterebbe lo stack a 15 container che la decisione
   `OCOR-DEV-0060-BA-SELECTED-COMPONENTS` richiede. Bloccherebbe REM-0038–0042 e
   OCOR-DEV-0060.

## Raccomandazione

Opzione 1. Conserva l'invarianza fail-closed del guard e la catena di prova verso le
revisioni qualificate. Ammette soltanto le differenze esatte già autorizzate dal PO,
dimostrate da test negativi, e non allenta alcun limite, timeout o gate.

## Impatto

- Bloccati fino alla decisione: riparazione 1 di `OCOR-DEV-REM-0038` (e quindi la sua
  integrazione), `OCOR-DEV-REM-0042`, `OCOR-DEV-REM-0039`–`0041` e `OCOR-DEV-0060`, che
  ne dipendono in sequenza.
- Non bloccati: `OCOR-DEV-0062`, `OCOR-DEV-0063`, `OCOR-DEV-0064`.
- Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e
  Production `NO-GO`. Nessun nuovo `DEC-*`.

## Disposition PO (2026-10-26)

Decisione **normativa** `REM-0038-CAMPAIGN-GUARD-ADMISSION (2026-10-26)`, presa dal PO con
istruzione esplicita: scelta l'**opzione 1** con tre condizioni (file della richiesta letto
con sha256 `7f01089c5a887dbf381b754a8369d3d7499caf2a54b7792f9825f846d931d943`, commit
`fdb2704762697dbe74a34c8a44670b11d86e6924`). Stato della richiesta: risolta.

- Opzione 1: nel solo `reports/tests/test_kind_teardown_observation.py` una normalizzazione
  per REM-0038 sul modello di `retire_integrated_0049_pin`, che riporta alla forma della
  baseline `MANDATORY_CONTAINERS = 15`, le due sostituzioni di `11` (in `main` e in
  `observe_health_event`) e i due segnaposto `OCOR_LOCAL_SEAWEEDFS_PASSWORD` e
  `OCOR_LOCAL_TEMPORAL_POSTGRES_PASSWORD` del workflow di tooling, ciascuna con conteggio
  verificato; test negativi per ogni altra differenza (un'altra costante, un'altra funzione,
  `MANDATORY_CONTAINERS` diverso da 15, una riga di workflow in più). Invariati le baseline
  `9b4d3be` e `7cd5f7a`, i controlli su `WINDOW_SECONDS`, `POLL_SECONDS`, `SAMPLE_SECONDS`,
  `KIND_BINARY`, i timeout delle sonde a 10 s, l'esclusione di `observe_health_event` e le
  normalizzazioni esistenti. Rientra nella riparazione 1 di `OCOR-DEV-REM-0038`, con verifica
  esterna ordinaria, sigillo, CI sull'HEAD esatto e merge.
- Condizione a: lo stesso schema è autorizzato preventivamente soltanto per
  `OCOR-DEV-REM-0042` (`FULL_SUITE_LIMIT_SECONDS` da 4500 a 5400, `LOCAL-FULL-SUITE-CAP-90`) e
  per `OCOR-DEV-REM-0039`–`0041` (modifiche a workflow e `run_qualifying_campaign.py`
  strettamente necessarie ai servizi di `OCOR-DEV-0060-BA-SELECTED-COMPONENTS`). Una
  differenza che cambia limiti, timeout, finestre, cadenze, timer, partizioni, selezione dei
  casi o gate richiede una nuova decision request.
- Condizione b: prima di ogni campagna e di ogni push di un candidato, l'implementatore esegue
  in locale i moduli di guardia dell'aggregato `validation-closure` e ne registra l'esito
  nell'evidenza.
- Condizione c: dopo l'integrazione di `OCOR-DEV-REM-0041`, una decision request separata
  valuta il consolidamento delle normalizzazioni in una nuova baseline, con prova di
  equivalenza; fino ad allora le baseline non si spostano.
- Chiarimento: i timeout vigenti dei job della CI restano invariati (oggi `timeout-minutes: 75`
  per le parti); `MAIN-CI-30MIN-JOB-CAP` non è riattivato.
- Ordine: riparazione 1 e integrazione di REM-0038, poi REM-0042, poi REM-0039, 0040, 0041,
  poi `OCOR-DEV-0060`; `OCOR-DEV-0062`–`0064` quando le remediation attendono una verifica.

`DEC-*`: nessun nuovo identificativo. La procedura vigente non lo richiede: il mandato
`CC-OCOR-DELIVERY-COMPLETION` non attiva l'eccezione di baseline promotion di `AGENTS.md`,
che sola autorizza nuovi `DEC-*`. La decisione è registrata come decisione normativa del PO in
questo file, nel registro `blockers` e nell'`ITERATION_LOG.md`. Registrazione: Claude Code
(Anthropic, claude-opus-5-5), implementatore del loop. Claim invariati: E1=0, E2=0,
Verified=0; runtime NOT_ESTABLISHED, PoC/Production NO-GO.
