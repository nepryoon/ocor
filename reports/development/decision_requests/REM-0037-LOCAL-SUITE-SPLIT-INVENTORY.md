# REM-0037-LOCAL-SUITE-SPLIT-INVENTORY

Status: OPEN — PO decision required (`OPEN_PO_DECISION_REQUIRED`).
Autorità: `LOCAL-SUITE-SPLIT (2026-10-25)`, punto 2 («Se le riqualifiche
necessarie riguardano più di 3 task, o toccano 0049 o 0050, fermati e apri una
decision request con l'inventario»). DEC-210/211. Nessun nuovo `DEC-*`.

Esecutore: Claude Code (Anthropic, `claude-opus-5-5`, CLI 2.1.310),
implementatore principale secondo `LOOP-IMPLEMENTER-ORDER (2026-10-25)`.
Unità in sola lettura: nessun codice, test, harness, workflow o record di
evidenza modificato; nessuna campagna, nessun container avviato.

## Contesto

`OCOR-DEV-REM-0037` deve eseguire la suite completa locale in 2 parti parallele,
ognuna con progetto Compose, porte, cluster kind, volumi, directory `.ocor`, CA
SPIRE e credenziali propri, con il comportamento predefinito identico per CI,
verifier e ogni altro uso. Input di progetto: la profilazione
`REM-0033-LOCAL-FULL-DURATION` (branch
`governed/decision-request-rem0018-local-full-duration-20261025`, commit
`539b9b6f092e977afec331826e1a8559a2b43cb1`, `profile.json`
`f700496b5d301255564b9d1080f93698ee7412000ae0b33b34eb9a5e99a00bc3`).

Prima del codice il punto 2 impone l'inventario dei file da toccare e dei record
sigillati che li hanno fra gli input. L'inventario mostra che l'isolamento
richiesto supera la soglia di 3 riqualifiche e tocca 0049 in ogni variante che
produce un guadagno significativo. Il loop si ferma su REM-0037 e prosegue con la
coda indipendente.

## Metodo dell'inventario

Script in sola lettura fuori dal repository,
`~/.ocor-codex/rem0037-inventory-20261025/inventory.py`
(`21890d2cbf1c466a51ad62429ef8dcecb9246b7599d86adbcbc6828cd0805aac`), eseguito
con `python3 -I` su `main` `bb9dab7` (risultato `inventory.json`
`c1f0163c89dfb69c4990e93ae4450b0dd42be6aec64e37694608bdd8b4116041`).

- `git grep` dei letterali delle risorse condivise in `ocor-runtime/src`,
  `ocor-runtime/tests`, `scripts`, `deploy`, `reports/tests`,
  `.github/workflows`: porte host `127.0.0.1` (6363, 1729, 8000, 3030, 8181,
  8080, 8200, 55433, 19092, 16333, 16334), progetto e nomi container
  `ocor-bootstrap`, cluster `ocor-poc`, directory `.ocor/`.
- Per ognuno dei 74 task in `completed_evidence_tasks`, il record **più
  recente** scelto con la stessa funzione di
  `scripts/validate_evidence_input_drift.py` (`select_most_recent`), e le
  chiavi del suo campo `inputs`.
- Inventario statico: è un limite inferiore. Accessi indiretti non letterali
  potrebbero aggiungere file.

## Risultato: dove sono fissate le risorse condivise

Endpoint fissi nel codice sorgente (usati dai test tramite gli adapter):

| File | Letterale | Record sigillato più recente |
|---|---|---|
| `ocor-runtime/src/ocor_runtime/c4/jena_adapter.py:39` | `http://127.0.0.1:3030` | 0038 |
| `ocor-runtime/src/ocor_runtime/c4/typedb_adapter.py:42` | `http://127.0.0.1:8000` | 0037 |
| `ocor-runtime/src/ocor_runtime/c5/backbone.py:36` | `127.0.0.1:29092` | 0040 |

Porte e nomi container fissi nei test:

| File | Letterali | Record |
|---|---|---|
| `tests/tasks/test_ocor_dev_0025.py:48` | `127.0.0.1:8000`; pausa `typedb` via fault inject | 0025 |
| `tests/tasks/test_ocor_dev_0048.py:83-109,457,1784,1898,2027` | 8080, 8181, 8200; `ocor-bootstrap-spire-agent-1`, `ocor-bootstrap-spire-server-1`; pausa `opa`/`keycloak` | 0048 |
| `tests/tasks/test_ocor_dev_0049.py` | 8181, 8080, 8200, 55433, 16333; `ocor-bootstrap-qdrant-1`, `ocor-bootstrap-postgresql-1`, label `com.docker.compose.project`; `ocor-poc`; `.ocor/` | 0049 |
| `tests/tasks/test_ocor_dev_0058.py:496-549` | `http://127.0.0.1:8181` | 0058 |
| `tests/tasks/test_ocor_dev_0021.py:94`, `0024.py:208` | pausa servizi via `fault_inject_test_environment.py` (`-p ocor-bootstrap`) | 0021, 0024 (indiretto) |

Procedura di stack (bootstrap, inizializzazione, fixture, verifica, guasti):

| File | Record |
|---|---|
| `deploy/bootstrap/compose.yaml` (`name: ocor-bootstrap`, porte letterali) | 0073, 0074, 0075, 0077, 0078, 0079 |
| `deploy/bootstrap/init/initialize_services.py` | 0080 |
| `deploy/bootstrap/fixtures/load_fixtures.py` | 0081 |
| `scripts/verify_external_services.py` | 0073, 0075, 0079 |
| `scripts/fault_inject_test_environment.py` | 0073, 0075, 0083 |
| `scripts/reset_test_environment.py` | 0082 |
| `scripts/bootstrap_development_environment.py` (`.ocor/`, SPIRE) | 0072 |
| `scripts/bootstrap_ci_environment.py`, `scripts/run_qualifying_campaign.py`, `scripts/observe_kind_teardown.py` | nessuno |

Il chart Helm `deploy/helm/ocor-poc/**` (cluster `ocor-poc`) è input di 0049;
`.github/workflows/ocor-validation-closure.yml` è input di 0005 e 0050.

## Perché ogni variante utile supera la soglia

Tempi della campagna di riferimento REM-0018 (nuovo host, 3066 casi, somma dei
casi 3957.5 s): `test_ocor_dev_0049` 2859.7 s (72.3%), di cui il caso Helm
1008.0 s; tutti gli altri moduli insieme 1097.8 s.

1. **Senza toccare 0049** l'intero modulo 0049 resta nella parte con lo stack
   predefinito. La seconda parte può contenere al massimo 1097.8 s di casi, e
   soltanto quelli che non usano porte, nomi o adapter fissi. Durata minima
   della campagna circa 2867 s contro 3965 s seriali: guadagno massimo 28%,
   realisticamente minore. Anche così il secondo stack va avviato, inizializzato,
   caricato e verificato su porte diverse: servono modifiche, con default
   invariato, a `initialize_services.py`, `load_fixtures.py`,
   `verify_external_services.py` e alla procedura SPIRE/`.ocor`. Sono già almeno
   6 task da riqualificare (0072, 0073, 0075, 0079, 0080, 0081): oltre la soglia.
2. **Guadagno pieno (stima della profilazione circa 1990 s, -50%)**: richiede di
   spostare nella seconda parte circa 900 s di casi 0049 diversi da Helm, quindi
   di rendere parametriche le porte e i nomi in `test_ocor_dev_0049.py`, negli
   adapter sorgente e negli altri test con endpoint fissi. Insieme minimo di
   riqualifiche: 0025, 0037, 0038, 0040, 0048, 0049, 0058, 0072, 0073, 0075,
   0079, 0080, 0081, 0082, 0083 (15 task, 0049 compreso; 0021 e 0024 se
   cambia l'interfaccia di `fault_inject`).
3. **Isolamento per namespace di rete senza cambiare porte** (pytest della
   seconda parte eseguito in un container che condivide la rete del proprio
   stack): evita di toccare test e sorgenti, ma esegue metà della suite in un
   ambiente diverso dall'host della qualifica, cioè cambia la fonte
   dell'evidenza (normativo per `LOCAL-SUITE-SPLIT` punto 7). I moduli che
   manipolano container per nome (0021, 0024, 0025, 0048, 0049) restano
   comunque nella parte predefinita: guadagno vicino al caso 1. Non
   raccomandato.

Il cluster kind non va duplicato in nessuna variante: il caso Helm e i casi che
usano `ocor-poc` restano nella parte con lo stack predefinito, e la seconda parte
non crea alcun cluster. Si chiede al PO di confermare che questo soddisfa il
requisito «cluster kind propri» del punto 3.

## Opzioni

1. **Raccomandata.** Autorizzare per REM-0037 la parametrizzazione degli
   endpoint e dei nomi delle risorse condivise nei soli file inventariati sopra,
   tramite variabili d'ambiente generate dalla procedura versionata, con
   **valore predefinito byte-identico** a quello attuale.
   - Prova obbligatoria: confronto AST prima/dopo per ogni file che dimostri che
     le differenze sono limitate alla sostituzione del letterale con una lettura
     d'ambiente che ha come default lo stesso letterale; stessi test, stesse
     asserzioni, stesse parametrizzazioni; un test che fallisca se il diff tocca
     altro.
   - Riqualifica con nuovi record e supersession esplicita dei 15 task
     inventariati (0049 compreso), registri e sigilli storici intatti.
   - Una sola esecuzione seriale della suite completa sull'head candidato serve
     da base comune delle riqualifiche e da metà della prova d'equivalenza.
   - Compose: preferire un file di override aggiuntivo per porte e nome di
     progetto della seconda parte, lasciando `deploy/bootstrap/compose.yaml`
     invariato (Docker Compose v5.6.1 sul nuovo host).
   - Kind solo nella parte predefinita, come sopra.
   - Restano invariati tutti i vincoli di `LOCAL-SUITE-SPLIT` (partizione,
     unione JUnit esatta, zero skip, memoria, tetto 75/60 minuti sul tempo
     complessivo, uso come evidenza solo dopo GO, sigillo e merge; verifier
     sulla procedura seriale).
   - Impatto: guadagno stimato circa 33 minuti per ogni suite completa locale
     (2-6 per unità nelle ultime unità) al costo di una remediation con 15
     riqualifiche e una campagna CI 0049.
2. Autorizzare solo la variante senza modifiche a 0049 e ai sorgenti
   (caso 1): riqualifiche di 0072, 0073, 0075, 0079, 0080, 0081; seconda parte
   limitata ai moduli che non usano endpoint o nomi fissi. Guadagno massimo 28%,
   probabilmente molto meno; complessità quasi pari all'opzione 1.
3. Sospendere REM-0037 e mantenere la suite seriale, rinviando la decisione a
   dopo G6 o a una nuova misura. Nessun costo e nessun rischio sui record
   sigillati; resta il costo attuale (43-49% del tempo di unità in full locali).

Raccomandazione: **opzione 1**, perché è l'unica che realizza il guadagno per cui
`LOCAL-SUITE-SPLIT` è stata autorizzata; le modifiche sono meccaniche e
verificabili con prova AST, e il default resta identico per CI e verifier. Se il
PO preferisce non riqualificare 0049 prima di G6, l'opzione 3 è preferibile alla
2, il cui rapporto costo/beneficio è sfavorevole.

## Impatto e task bloccati

- Bloccato: soltanto `OCOR-DEV-REM-0037`.
- Non bloccati: l'ultimo ciclo di `OCOR-DEV-REM-0027`
  (`REM-0027-REPAIR-2-SCOPE-AND-VF001-DISPOSITION`), poi `OCOR-DEV-REM-0031`;
  il loop prosegue con questi usando la procedura seriale vigente.
- Nessun test, caso, limite, timeout, soglia, partizione CI o gate cambiato.

Inputs immutabili; E1=0, E2=0, Verified=0; runtime NOT_ESTABLISHED,
PoC/Production NO-GO. Nessun nuovo DEC o chiusura normativa.

## Disposition PO (2026-10-25)

Decisione `REM-0037-LOCAL-SUITE-SPLIT-INVENTORY (2026-10-25)`: scelta
l'**opzione 3**. `OCOR-DEV-REM-0037` è **sospesa fino a dopo la chiusura di
G6**. Stato della richiesta: risolta con sospensione.

- Nessuna implementazione: niente parametrizzazione di endpoint o nomi, nessun
  file di override Compose, nessuna riqualifica, nessuna modifica a codice,
  test, harness, workflow o record sigillati per la suite divisa in parti. La
  suite completa locale resta **seriale** con la procedura vigente, per
  l'implementatore e per il verifier.
- `LOCAL-SUITE-SPLIT (2026-10-25)` resta registrata con esecuzione sospesa;
  questa decisione supersede soltanto il suo punto 1 (ordine nella coda):
  REM-0037 esce dalla coda pre-G6 e non si riprende d'iniziativa. Dopo la
  chiusura di G6 si potrà aprire una nuova decision request con misure
  aggiornate; resta aperta per quella rivalutazione la domanda sul cluster kind
  solo nella parte predefinita.
- Coda: ultimo ciclo di `OCOR-DEV-REM-0027`, poi `OCOR-DEV-REM-0031`, poi G6
  (QUEUE-TO-G6-ORDER).
- Gli artefatti dell'inventario fuori da Git
  (`~/.ocor-codex/rem0037-inventory-20261025/`) restano invariati come
  riferimento.
- Nessun test, caso, limite, timeout, soglia, partizione CI o gate cambiato.

Registrazione: Claude Code (Anthropic, claude-opus-5-5, CLI 2.1.310),
implementatore del loop secondo LOOP-IMPLEMENTER-ORDER. `OCOR-DEV-REM-0037` è
registrata come sospesa dal PO, non chiusa e non verificata. Claim invariati:
E1=0, E2=0, Verified=0; runtime NOT_ESTABLISHED, PoC/Production NO-GO.

## Disposition PO (2026-10-26/27): riattivazione

Decisione normativa `LOCAL-SUITE-SPLIT-REACTIVATION (2026-10-26)`, con istruzione
esplicita del PO: la sospensione disposta il 2026-10-25 (opzione 3) è
**revocata** e `OCOR-DEV-REM-0037` è **riattivata**. Stato della richiesta: da
risolta con sospensione a **risolta, riattivata**. La disposition del
2026-10-25 resta come storia.

- Ordine: integrazione di `OCOR-DEV-REM-0038` e `OCOR-DEV-REM-0042` (entrambe
  avvenute), poi `OCOR-DEV-REM-0037`, poi `0039`, `0040`, `0041`, poi
  `OCOR-DEV-0060`.
- L'inventario del 2026-10-25 (stack a 11 container) è superato: va rifatto in
  sola lettura sull'`origin/main` corrente con lo stack a 15 container e
  registrato nell'evidenza di REM-0037.
- Per REM-0037 non si applica la soglia «più di 3 task, oppure 0049 o 0050»:
  sono autorizzate le riqualifiche di tutti i record sigillati toccati,
  compresi `OCOR-DEV-0049` e `OCOR-DEV-0050`, con supersession esplicita.
- Ammesse soltanto modifiche che rendono configurabili le risorse condivise
  con valore predefinito identico; asserzioni, casi, timer, timeout, soglie,
  attese, semantica, contratti, port e schemi invariati.
- I casi kind possono stare in corsie diverse; il modulo di `OCOR-DEV-0049` va
  distribuito fra le corsie. Guard di invarianza secondo
  `REM-0038-CAMPAIGN-GUARD-ADMISSION`, condizione a, o decision request.
- Memoria (punto 8), come modificato da `LOCAL-SUITE-SPLIT-MEMORY-DEFERRAL
  (2026-10-27)`: se due stack, due cluster kind e gli agenti non stanno nella
  memoria con la guardia invariata, nessuna decision request e nessun arresto
  del loop: misure registrate, REM-0037 sospesa in attesa di memoria con
  branch e artefatti preservati e non integrati, e si passa a
  `OCOR-DEV-REM-0039`; ripresa automatica quando `MemTotal` aumenta o la
  memoria disponibile all'avvio supera la soglia misurata.

Registrazione: Claude Code (Anthropic, claude-opus-5-5), implementatore del
loop, all'avvio dell'unità REM-0037 (2026-10-27). Nessun nuovo `DEC-*`: il
mandato `CC-OCOR-DELIVERY-COMPLETION` non attiva l'eccezione di baseline
promotion. Claim invariati: E1=0, E2=0, Verified=0; runtime NOT_ESTABLISHED,
PoC/Production NO-GO.
