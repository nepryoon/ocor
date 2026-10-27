# OCOR-DEV-REM-0038-RCCAD — provisioning di Temporal e SeaweedFS nello stack di bootstrap e in CI

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 0.
  Verifier richiesto: Cursor CLI / Grok (xAI), oppure Antigravity / Gemini (Google), processo e contesto
  separati. Implementatori del task: Claude Code (Anthropic, `claude-opus-5-5`) e Codex (OpenAI, contato dal
  loop); nessun verifier Anthropic o OpenAI (`LOOP-IMPLEMENTER-ORDER-AUTH-FALLBACK`, 2026-10-26).
- **Fonte**: decisione normativa del PO `OCOR-DEV-0060-BA-SELECTED-COMPONENTS` (2026-10-26), opzione 2,
  change set **a** (provisioning nello stack di bootstrap e nella CI, pinned per digest, con lo stesso
  trattamento dei servizi esistenti). Decision request su
  `governed/decision-request-ocor-dev-0060-ba-selected-components`, commit
  `803abee616cef879b0c9dfe1218bfaa50200de96`, sha256
  `84cdd936ef6f2999497ebe3f50cb0b05e56f128ffbe0acab77bc78fff40c7574`, PR #351.
- **Branch**: `governed/ocor-dev-rem-0038-ba-services`.

## Ambito

| Componente | Provisioning |
|---|---|
| `BA-05` Temporal | `temporalio/server` 1.32.1 (MIT) con il proprio PostgreSQL (immagine `postgres` del lock, mai pubblicata sull'host, tmpfs) e `temporalio/admin-tools` 1.32.1 (MIT), che applica lo schema PostgreSQL v12 pinned prima dell'avvio del server e porta la CLI ufficiale per le sonde. Frontend solo su `127.0.0.1:17233` |
| `BA-06` SeaweedFS | `chrislusf/seaweedfs` 4.51 (Apache-2.0), modalità `mini` su tmpfs; pubblicato solo il gateway S3 su `127.0.0.1:18333`; identità admin S3 con segreto generato; richieste non firmate o con segreto errato negate. Bucket con S3 Object Lock e versioning verificati dalla sonda di qualifica |
| `BA-01` TerminusDB | già fornito e qualificato da `OCOR-DEV-0073` (12.0.7-noroot, digest pinned); invariato, riqualificato sullo stack a 15 container |

Stesso trattamento dei servizi esistenti: digest nel lock e nel Compose, policy condivisa (`restart: "no"`,
`init`, `no-new-privileges`, rete dedicata), limiti di memoria e CPU, healthcheck, verifica tipizzata con
moduli di qualifica fail-closed (`deploy/bootstrap/services/temporal`, `deploy/bootstrap/services/seaweedfs`),
fault recovery limitata (pausa/ripresa e riavvio), reset invariato (nulla di nuovo viene inizializzato),
smontaggio con il progetto Compose senza residui. La CI usa lo stesso profilo tramite
`scripts/bootstrap_ci_environment.py`, senza modifiche ai workflow; la guardia della campagna richiede ora i
15 servizi del Compose come container obbligatori.

Le dipendenze client Python (Temporal, S3, TerminusDB) appartengono agli adapter dei change set b, c, d.
Il benchmark di Temporal per `DEP-011` richiede il worker dell'SDK ed è `NOT_EXECUTED` qui, portato come
obbligo di `OCOR-DEV-REM-0039`; la licenza (MIT) è verificata.

## TDD

- RED su `origin/main` `72b2f9e` con lo stack reale a 11 servizi fornito dal bootstrap versionato di quel
  commit e il solo modulo `tests/tasks/test_ocor_dev_rem_0038.py` copiato: 18/18 FAIL.
- GREEN al commit di codice: modulo del task tre volte, regressione, suite completa seriale.
- Due difetti trovati dalla campagna e corretti nel change set, ciascuno con un caso che lo fissa:
  la guardia a 11 container di `scripts/run_qualifying_campaign.py` (consumer mancato dall'inventario) e
  l'esaurimento degli slot di volume di SeaweedFS (un bucket per sonda). I tentativi non qualificanti sono
  elencati nel record con gli sha256 dei loro artefatti, mai contati come PASS o FAIL.
- Un terzo difetto trovato dallo scanner di supply chain prima del push: il key id `AKIA…` dell'esempio
  SigV4 pubblicato da AWS nel contratto di `seaweedfs/test_qualify.py` è rifiutato dallo scanner dei
  segreti (check obbligatorio). Corretto in `36e6151` con un key id neutro: il key id non entra nella
  stringa da firmare, quindi la firma pubblicata resta invariata e verificata. Lo scanner non è stato
  toccato. La campagna intera, già passata sul commit `b81630a`, è stata rieseguita al commit `36e6151`
  (tentativo `a6`, superato).

## Riqualifiche

Record nuovi con `supersedes` esplicito, nessun record sigillato modificato, manifest estesi in testa:
`OCOR-DEV-0070`, `0072`, `0073`, `0074`, `0075`, `0076`, `0077`, `0078`, `0079` (input di provisioning
cambiati) e, per l'allowlist del validator di piano, `0005`, `0050`, `0082` (sola regressione; `0082`
anche reset e smontaggio).

## Vincoli rispettati

- Nessun test escluso, saltato o indebolito; nessun limite, timeout o soglia cambiato.
- `inputs/` intatto; nessun nuovo `DEC-*`; contratti, port, schemi e semantica invariati.
- `E1=0`, `E2=0`, nessun requisito `Verified`; runtime conformance `NOT_ESTABLISHED`, PoC-GO e Production
  readiness `NO-GO`. Temporal, SeaweedFS e TerminusDB restano `Candidate Implementation` fino alla qualifica
  di `OCOR-DEV-0060`.

## Riparazione 1 (ciclo 1)

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 1. Record distinti
  `repair-1.json`/`.log` e riqualifiche `OCOR-DEV-0005`, `OCOR-DEV-0050` e `OCOR-DEV-0082`
  `.requalified-rem0038-repair1`, con `supersedes` esplicito. I record sigillati di questo
  change set al commit `03edc31a8ced808259290bb055b807f2d97af562` (sopra compreso questo file fino a
  questa sezione) restano immutati; il GO `OCOR-DEV-REM-0038-dc5a404b350f-0` non si riusa.
- **Causa**: CI sull'HEAD esatto sigillato (PR #357), due fallimenti reali, zero rerun, nessun merge:
  `tooling-policy` (run `40375838054`), il passo di rendering del Compose non aveva i segnaposto di
  `OCOR_LOCAL_SEAWEEDFS_PASSWORD` e `OCOR_LOCAL_TEMPORAL_POSTGRES_PASSWORD`; `validation-closure`
  (run `40375837616`), i guard di invarianza di `reports/tests/test_kind_teardown_observation.py`
  rifiutavano la costante `MANDATORY_CONTAINERS = 15`.
- **Autorità**: decisione normativa del PO `REM-0038-CAMPAIGN-GUARD-ADMISSION (2026-10-26)`, opzione 1
  (decision request `governed/decision-request-rem0038-campaign-guard-admission`, commit
  `fdb2704762697dbe74a34c8a44670b11d86e6924`, sha256
  `7f01089c5a887dbf381b754a8369d3d7499caf2a54b7792f9825f846d931d943`, verificato).
- **Correzione**: due righe di segnaposto nel workflow di tooling; nel guard, normalizzazione esatta con
  conteggi verificati (costante e sue due sostituzioni riportate a `11`; i due segnaposto) e test negativi
  (`Rem0038GuardAdmission`): un'altra costante, un'altra funzione modificata o aggiunta,
  `MANDATORY_CONTAINERS = 16`, il controllo d'inventario indebolito, la costante usata altrove, il limite
  della suite, un segnaposto in più, mancante, duplicato o in un altro workflow e un'altra riga di tooling
  continuano a fallire. Baseline `9b4d3be`/`7cd5f7a`, controlli su finestra, cadenza, campionamento,
  `KIND_BINARY`, timeout di 10 s ed esclusione di `observe_health_event` invariati. Due test del task
  rendono `compose.yaml` con esattamente l'ambiente del workflow (lacuna locale della PR #357).
- **TDD**: RED al commit `f6eefce` (HEAD sigillato unito a `origin/main`) con i soli test nuovi: 6 test
  falliti, tutti per i segnaposto mancanti; GREEN al commit di codice `12659a1cd847f53991e96991033104326abf1cda`. Tentativi non qualificanti, elencati
  nel record (`non_qualifying_attempts`, aggiunto dalla riparazione 2) con commit, sha256 degli artefatti
  e `counted: false`, mai contati come PASS o FAIL: `a0` su `6f748b3`, fermato
  prima di ogni test perché l'allowlist di piano non era ancora dichiarata; `a1` su `1b1160f`, campagna
  intera passata (3224/3224 in 4146,3 s) ma superata, perché l'estensione dell'allowlist fa derivare anche
  il record sigillato di `0082`; percorsi di `0082` dichiarati in `12659a1` e campagna rieseguita.
- **Gate locali prima della campagna** (condizione b): i sei moduli di guardia dell'aggregato
  `validation-closure` (239 PASS, zero skip), lo scanner di supply chain 1.1.0 (0 bloccanti), il passo esatto di
  rendering del Compose del workflow di tooling e i gate di codice. I moduli di guardia girano anche nella
  campagna (`reports-portfolio`).
- **Campagna** (stack reale a 15 container, shell pulita, PATH del lock): fasi A (bootstrap, verifica tipizzata 11 servizi
  READY prima e dopo fault e reset, qualifiche e fault injection) PASS; modulo del task 22/22 tre volte;
  regressione 325; portfolio dei report 362; suite completa seriale 3224/3224, zero skip, 4007,0 s
  (66,8 min: 407,0 s sopra la notifica di 3600 s; margine dal tetto vigente di 4500 s: 493,0 s);
  smontaggio senza residui. Alimentazione: rete elettrica a inizio e fine corsa (79%).
- **Riqualifiche**: `0005` e `0050` (modulo di guardia e allowlist di piano, input sigillati) e `0082`
  (allowlist di piano; anche reset e smontaggio), tutte di sola regressione; le riqualifiche sigillate di
  `0070` e `0072`–`0079` restano le più recenti (deriva 0).
- **Ruoli**: implementatore Claude Code (Anthropic, `claude-opus-5-5`); Codex (OpenAI) contato dal loop.
  Verifier richiesto di fornitore diverso: Cursor CLI / Grok (xAI) oppure Antigravity / Gemini (Google).
- Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
  Nessun nuovo `DEC-*`; nessun limite, timeout o gate cambiato.

## Riparazione 2 (ciclo 2, solo evidenza)

- **Causa**: verdetto `NO_GO` `OCOR-DEV-REM-0038-15ca445f50e6-1` (Cursor CLI, grok-4.7-high, xAI) sull'HEAD
  `15ca445`. `VF-001` (medium, bloccante): nel record mancava l'esito della revisione preventiva.
  `VF-002` (low, non bloccante): questo README diceva che i tentativi `a0`/`a1` erano nel record, ma non c'erano.
- **Correzione**: in `repair-1.json`, ancora non sigillato, si aggiungono tre campi: `preventive_review`,
  `non_qualifying_attempts` ed `evidence_corrections`. Nessun campo esistente viene rimosso.
  - `preventive_review` vale `SKIPPED`. Il motivo: `PRE-CAMPAIGN-REVIEW (2026-10-26)` non era nelle
    istruzioni dell'iterazione che ha eseguito la campagna. Il loop ha attivato la revisione preventiva
    solo al riavvio delle 2026-10-27T00:21:45+01:00, quando la campagna era finita e il candidato
    `15ca445` era già committato. Il punto 7 esclude una revisione retroattiva. Le prove sono gli sha256
    del prompt dell'iterazione e delle righe del log del loop.
  - `non_qualifying_attempts` riporta i commit, il manifest sha256 e gli sha256 degli artefatti principali.
- **Invariato**: codice, test, workflow, allowlist di piano, raw log, riqualifiche e manifest restano
  byte-identici a `15ca445`. La campagna al commit `12659a1` non si riesegue, perché nessun input
  qualificante cambia.
- **Ruoli**: implementatore Claude Code (Anthropic); Codex (OpenAI) contato dal loop. È l'ultimo ciclo di
  riparazione: un nuovo `NO_GO` porta all'escalation.
