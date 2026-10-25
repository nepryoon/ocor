# REM-0033-LOCAL-FULL-DURATION — rimisurazione REM-0018 sul nuovo host

Status: `OPEN_PO_DECISION_REQUIRED` — notifica non bloccante, nessuna deroga applicata.
Data UTC: 2026-10-25T05:22:47.530596+00:00.

## Contesto e autorita

La decisione PO REM-0017-CI-CAMPAIGN-BUDGET (2026-10-07) mantiene il limite
locale di 75 minuti e richiede notifica oltre 60 minuti. HOST-MIGRATION
(2026-10-24) richiede una misura nuova: le durate del vecchio host non sono
confrontabili. Questa occorrenza aggiorna la richiesta esistente soltanto
con dati della campagna REM-0018, senza modificare documenti storici.

## Misura riproducibile

- Host: Intel Core Ultra 9 275HX, 24 thread, RAM 32504823808 byte;
  kernel 7.0.0-38-generic (nuovo host del mandato HOST-MIGRATION).
- Codice/test: `7fc59409aebf3f632e2dff8925b98f78a2facc11`; branch
  `governed/ocor-dev-rem-0018-anonymous-volume-teardown`.
- Campagna versionata: `scripts/run_qualifying_campaign.py --execute`,
  shell pulita, bootstrap `scripts/bootstrap_ci_environment.py --execute --timeout 600`,
  reset preventivo e stack fissato dai lock; nessun source di bootstrap.env.
- Durata misurata: **3965.363 s**
  (66.089 minuti), sopra 3600 s e sotto 4500 s.
- Conteggi qualificanti: `{"errors": 0, "failures": 0, "skipped": 0, "tests": 3066}`.
  La campagna e' conclusa: `PASS`. Nessun conteggio trasferito da altri run.
- Nessun test, caso, timer, soglia, partizione o gate e' stato cambiato.
  La nuova occorrenza non giustifica un incremento del tetto.
- Evidenza completa e raw nel candidato REM-0018:
  `reports/evidence/G2/OCOR-DEV-REM-0018.json` e `.log`;
  hash dei raw originali della campagna:

```json
{
  "full/campaign_result.json": "2c467b427eca08fe6a83b9954836f0dc4cff0eb0d98c56b7a448283271831695",
  "full/kind-teardown-observations.json": "5929704a134b70d65ceebaeec9ca18094fb86a9d9ec7002739ff831e285d1876",
  "full/post_remediation_runtime.log": "dd08cd931aeb56b842dcdeaedd2515b17690de83deb13934f262fd7622c30637",
  "full/runtime_junit_post_approval.xml": "e805d86ff526d5a9eb9159d8d8d5fe0c8f0431c0130f218da3c92f0637491b3d"
}
```

## Opzioni e raccomandazione

1. Raccomandata: prendere atto della misura e mantenere il tetto locale di
   75 minuti, il monitoraggio e la notifica a 60 minuti invariati. Profilare
   in sola lettura eventuali future ricorrenze prima di proporre interventi.
2. Autorizzare in seguito un change set specifico per ridurre il tempo di
   preparazione o migliorare l'osservazione, con prova di equivalenza e senza
   rimuovere casi o cambiare limiti. Nessuna implementazione di questa opzione
   e' avviata da questa richiesta.

## Impatto e disposizione attesa

Task bloccati: **nessuno**. La campagna e' entro il tetto vigente;
REM-0018 prosegue alla verifica indipendente e ai gate ordinari. Questa
notifica resta su branch governato dedicato in attesa della disposition PO;
non modifica l'allowlist del piano e non viene integrata implicitamente.
La decisione riguarda soltanto questa notifica, non i claim del sistema.

Inputs immutabili; E1=0, E2=0, Verified=0; runtime NOT_ESTABLISHED,
PoC/Production NO-GO. Nessun nuovo DEC o chiusura normativa.

## Disposition PO (2026-10-25)

Decisioni `REM-0033-LOCAL-FULL-DURATION (2026-10-25)` e
`REM-0033-LOCAL-FULL-DURATION-PROFILING-SCOPE (2026-10-25)`: scelta
l'**opzione 2 del PO** (opzione 1 della richiesta con profilazione
anticipata). Copre tutte le occorrenze pubblicate sui branch
`governed/decision-request-*`, ultima questa rimisurazione REM-0018.

- Tetto locale 75 minuti e notifica oltre 60 minuti invariati; nessuna deroga,
  nessun cambio di test, casi, timer, timeout, soglie, partizioni o gate.
- Profilazione in sola lettura, dopo l'integrazione di REM-0018 e prima
  dell'ultimo ciclo di REM-0027, soltanto da artefatti gia esistenti.
- Occorrenze future sopra 60 minuti registrate come finora; nuova richiesta
  soltanto entro 5 minuti dal tetto di 75 minuti.
- Interventi soltanto come decision request separate; questa decisione non
  autorizza alcuna implementazione. Claim invariati.

## Esito della profilazione (2026-10-25, sola lettura)

Esecutore: Claude Code (Anthropic, claude-opus-5-5, CLI 2.1.310),
implementatore del loop secondo LOOP-IMPLEMENTER-ORDER. Nessuna campagna,
nessun test, nessun container avviato: soltanto lettura di JUnit con tempi per
caso, `campaign_result.json`, `health-observer.jsonl` (campioni ogni 5 s di
`/proc/stat` e `/proc/meminfo`), log di bootstrap/teardown e artifact CI gia
acquisiti. Script e risultati fuori dal repository in
`~/.ocor-codex/rem0033-profiling-20261025/` (`profile.py`
`df002a887dc5adae7ae1516d5704b17774a58db855218d055eea19311196cdaa`,
`units.py` `06343de2152fa4d71612e435d4e2509d16b07e11560aedc9f0855f724ee3d956`,
`profile.json` `f700496b5d301255564b9d1080f93698ee7412000ae0b33b34eb9a5e99a00bc3`,
`units.json` `c75bba8fc76df28115eec6600ab34b59735e4d18e08a272835aece49330f849b`).

Host diversi, dichiarati: nuovo host Intel Core Ultra 9 275HX, 24 thread,
RAM 32504823808 byte; vecchio host con `cpu_count` 14 registrato
dall'osservatore (non 12) e MemTotal 31830360 kB. I confronti sono
descrittivi e non motivano cambi di tetto.

### Campagne analizzate (SHA-256 di JUnit e campaign_result)

| Campagna | Host | Head | Test | Durata s | Helm s | Resto s |
|---|---|---|---|---|---|---|
| REM-0018 impl | nuovo | 7fc59409aebf | 3066 | 3965.4 | 1008.0 | 2949.5 |
| REM-0036 impl | nuovo | 4a79d2961d57 | 3053 | 3784.9 | 834.3 | 2942.9 |
| REM-0030 impl | nuovo | aa8f36c9be5d | 3043 | 3807.9 | 826.9 | 2971.8 |
| REM-0030 verifier | nuovo | 3a30104866ef | 3043 | 3790.4 | 845.2 | 2936.7 |
| 0059 impl c0 | vecchio | ea0193b182cc | 3002 | 3511.7 | 363.1 | 3138.3 |
| 0059 verifier c0 | vecchio | e226fc7d127c | 3002 | 4238.1 | 1098.9 | 3128.3 |
| 0059 impl c1 | vecchio | 5abf97104498 | 3043 | 4076.3 | 928.8 | 3139.4 |
| 0059 verifier env-recheck | vecchio | 28173a069bee | 3043 | 3930.1 | 718.1 | 3203.4 |

```json
{
  "REM-0018-impl": {"junit": "e805d86ff526d5a9eb9159d8d8d5fe0c8f0431c0130f218da3c92f0637491b3d", "result": "2c467b427eca08fe6a83b9954836f0dc4cff0eb0d98c56b7a448283271831695", "health": "8d65d3dc8b031b9e6455a2e3cd2ebe55b6c39c24cc35636814765865690d27f8"},
  "REM-0036-impl": {"junit": "3b39c961691a1fefebea76ec6fc163b6767531b40fad67a34403c302ac8525c6", "result": "303bd45e2b474aadd22d90a66b7496352861aa73bcf7752012ba829e074836b0", "health": "e71cc6038c8bf0287f7d3624ca10dca3d49cc63f1cfab84e83df45649b0346aa"},
  "REM-0030-impl": {"junit": "20d7fd238603b9b6e0c23ca9f6963bb894ca3c9e1b703463c3904aba37102c96", "result": "56a77ac5f3ef45900b6dafe47fef27674587f6a500d0e4ada7072a673a8c9f8c", "health": "20033d3c4e5fde7247229c1f5b2ee3c4016bd0c971d6abbe6aa8d47a7d8e439a"},
  "REM-0030-verifier": {"junit": "22ef437b72cc207ec476d2748edc12d1b5e4b55acebfd834ef6a3d39a1a7c083", "result": "18fb839f4c75a9ea60fbb0331c29ff5f0502e2a03920b12347f6f0a7bffa6178", "health": "74ae4d59a0bf68f8a61efbaa6ae8363007d7b0e56004de8fa689daabb119b9d4"},
  "0059-impl-c0": {"junit": "b4b5b4aa3536b4a8231bf5aa3ff7aeca1dbfcff5d1f6050d51772a4b5f13055b", "result": "fe2147abceb9b52d1ee8edb06892ac385804e92b4779db36b1d343e91d7ffe5d", "health": "e7caa77a0fa59a3b5442454bc030e3f436ff24ad7b7212bfc0dcbb526cabb8f0"},
  "0059-verifier-c0": {"junit": "75c11d68d31206b125e47d8745a0aef107e71202743a9f32cba774ebc3954657", "result": "85d2c81e35f6ba03d40d9f7910cecd1a7d71fbf0cbcbde556dd0790222d14ef3", "health": "a9fdc60bd1f406bc7f980f76f91591401bd42872f7ca61fdd6b35e6a39ff0bed"},
  "0059-impl-c1": {"junit": "9e9bbcd4b1c84bcd9397916daf831e39d2cf002ad7f9337d2e4870d745784c89", "result": "dca512129824c5befbd3d415983a5905f502b232e2c33c40e661d6c37e47fdda", "health": "c7511ab9585ad5433bdc86e78efcadac7b1e966442832418416fefc25b89e4db"},
  "0059-verifier-env-recheck": {"junit": "1686ca6a89e4b2171396cb0dc585826cc76beedbabe5b86497659ca4fa4b33d2", "result": "810f92b0f8700208ec2d28c476a46e4db03b5c2b615a349ba0353d8bc782b5c1", "health": "df900e2a9aa48dab1c304be6d6aeb09eec4c9b81bb97d21e6a20ffe0856fc1fc"}
}
```

### Ripartizione del tempo (riferimento REM-0018, nuovo host)

- **Preparazione e smontaggio dello stack**: fuori dalla durata misurata della
  campagna. `provisioning_seconds` 41.7 (REM-0018), 47.1 (REM-0036), 45.1
  (verifier REM-0018): circa 1.1-1.2% della campagna. La durata del teardown
  non e registrata nei log: `NOT_MEASURED`.
- **Raccolta e overhead fuori dai casi**: durata campagna meno somma dei tempi
  per caso = 7.8 s (7.7-11 s in tutte le campagne). Raccolta, avvio
  dell'interprete e scrittura della coverage sono trascurabili.
- **Primi 10 moduli** (s): `test_ocor_dev_0049` 2859.7 (72.3%), `rem_0026` 147.0,
  `0048` 128.4, `rem_0025` 105.0, `0056` 83.8, `rem_0020` 74.5, `rem_0022`
  65.2, `0041` 50.5, `0040` 47.5, `0053` 46.5.
- **Primi 30 casi**: 1894.4 s (47.9%). Il primo e il caso Helm di 0049
  (1008.0 s, 25.5%), poi i due `seal_and_restore_tied_epoch_tombstones`
  [9-7] 206.9 s e [7-7] 152.3 s; gli altri 27 sono fra 12.6 e 32.5 s (0049
  restore/readiness, 0025 TypeDB in pausa, 0053, 0019 Kafka, 0048 SVID,
  mission thread con restart Kafka, rem_0026). Elenco completo in
  `profile.json`.
- **Distribuzione**: 70 casi >= 10 s valgono 2332.9 s (59%); 2739 casi < 1 s
  valgono 213.9 s (5.4%).
- **Attese e timeout consumati**: i casi con pausa/timeout/restart/expiry/
  cron/helm/recover nel nome valgono 1535.9 s (38.8%). La parte dominante e
  l'attesa del tick reale `*/15` della CronJob nel caso Helm: 363-1099 s
  nelle otto campagne, mentre il resto della suite e stabile
  (2936.7-2971.8 s sul nuovo host, 3128.3-3203.4 s sul vecchio). La varianza
  fra campagne dello stesso host e quasi interamente il caso Helm (0059 c0
  impl contro verifier: +726 s totali, +736 s di Helm).
- **Quota seriale e parallelizzabile**: il caso Helm e indivisibile (25.5%,
  fino a 1200 s nel peso di caso peggiore di `MEASURED_WEIGHTS`); il resto
  (74.5%) e divisibile a moduli interi, con i casi di 0049 come unita
  indipendenti come gia fa la CI. Modulo non-0049 piu grande: 147 s.

### Perche la suite non accelera con 24 thread

Il limite e la **serializzazione con attese fisse**, non CPU ne I/O. La
campagna locale e un solo processo pytest senza parallelismo. Dai campioni
dell'osservatore: core occupati in media 1.02 (p95 2.14) su 24 nel nuovo host
e 1.31-1.51 (p95 2.8-3.7) su 14 nel vecchio; iowait medio 0.06-0.08%; il
60-80% dei campioni sotto 1.5 core occupati. Sul nuovo host la parte senza
Helm e circa il 6% piu veloce (2949.5 s per 3066 test contro 3139.4 s per 3043
test), coerente con un guadagno di velocita single-thread. Le durate totali
non migliorano perche dominano il caso Helm, che dipende dall'allineamento al
tick della CronJob, e le attese reali dei casi di guasto e ripristino.

### Esecuzioni complete per unita

Unita dalla fusione dello state sync dell'unita precedente alla fusione del
proprio state sync integrato. CI: tempo dalla creazione al merge delle PR
dell'unita, ognuna con le parti CI obbligatorie (4 workflow a 4 parti e la
parte 0049 a 5).

| Unita | Host | Full locali | Esecutori | Durate s | Quota full locali | PR CI | Quota CI |
|---|---|---|---|---|---|---|---|
| 0057 | vecchio | 2 | impl Claude Code; verifier Cursor/Grok | 3508, 3924 PASS | 45.9% di 16207 s | 3 | 36.3% |
| 0058 | vecchio | 6 | impl Claude Code c0, Codex c1, Codex c2 (ripresa Claude Code); verifier c0/c1/c2 | 3484, 3646, 3649, 3900, 4109, 4404 PASS (verdetti NO_GO, NO_GO, GO) | 47.3% di 49037 s | 5 | 20.7% |
| 0059 | vecchio | 4 | impl Claude Code c0, Codex c1; verifier c0, env-recheck | 3512, 4238, 4076, 3930 PASS (verdetti NO_GO, GO) | 43.2% di 36448 s | 6 | 33.1% |
| REM-0036 | nuovo | 2 | impl Claude Code; verifier Cursor/Grok | 3785, 3334 PASS | 46.0% di 15469 s | 3 | 36.9% |
| REM-0018 | nuovo | 2 | impl Codex (lancio) e Claude Code (chiusura); verifier Cursor/Grok | 3965, 4094 PASS | 49.1% di 16408 s | 3 | 36.2% |

Non contate: la campagna di 0058 c2 interrotta per quota, la campagna del
verifier 0059 c1 non avviata per stack SPIRE non PASS, la campagna REM-0036
`aborted-hostpath-full` interrotta prima dell'esito. Le full locali valgono il
43-49% del tempo di ogni unita; con le PR CI la quota supera l'80%.

### Fattibilita di 2 parti con stack isolati

- **Stima del tempo** (somma dei tempi per caso piu overhead):
  - con le regole di `partition()` attuali, che riservano Helm da solo nella
    prima parte, 2 parti danno circa 2950 s (REM-0018: 2957 s, -25%);
  - con una partizione per tempi misurati in cui Helm condivide la parte con
    altre unita: circa 1900-1990 s sul nuovo host (REM-0018: 1987 s, -50%);
    con il caso peggiore di Helm a 1200 s circa 2080 s. Limite inferiore
    di ogni partizione: max(Helm, totale/2).
  - La contesa e attesa bassa: circa 1 core per parte su 24, iowait
    trascurabile.
- **Memoria**: durante le campagne locali del nuovo host la memoria usata
  (agenti piu uno stack) va da 10.2-11.7 GiB all'avvio a 14.4-15.1 GiB di
  picco, con MemAvailable minimo 15.2-15.9 GiB su 30.3 GiB. Le uniche
  istantanee per container sono indicative e di altri contesti: allo stadio
  Helm del 2026-10-07, vecchio host, 2704 MiB per gli 11 container
  `ocor-bootstrap` e 1600 MiB per kind e relay `ocor-poc`
  (`helm-stage-docker-stats.log`
  `0fdf6be2cedc2acd357b2d5834416ed5a636a627cd2da07f92d502adfc5b983d`); stack
  inattivo in CI 1633 MiB (`docker-stats.log`
  `ff49a6d8a10ac7e45f46aa595c714cf24834f82b6913a92b57c12757c5b7017c`).
  Stima per parte: 5.1-6.2 GiB fra stack, relay, pytest e coverage, con kind
  (circa 1.6 GiB) in una sola parte. Un secondo stack porterebbe il picco a
  circa 20-21 GiB usati, con circa 9-10 GiB disponibili contro la guardia
  di 3 GB. Soglia d'avvio da confermare in REM-0037 con misura diretta:
  MemAvailable >= 18 GiB prima del bootstrap dei due stack, pari a
  2 x 6.2 + 3 di guardia + 2 di margine.
- **Cosa impedisce oggi due stack contemporanei**:
  - `name: ocor-bootstrap` fisso in `deploy/bootstrap/compose.yaml`, rete
    `ocor-bootstrap_ocor-bootstrap` e filtro
    `com.docker.compose.project=ocor-bootstrap` in `inspect_stack()`;
  - porte host fisse su 127.0.0.1 (6363, 1729/8000, 3030, 8181, 8080, 8200,
    55433, 19092, 16333/16334) richiamate letteralmente da 5-16 file per
    porta fra test, sorgenti, script e deploy;
  - cluster kind `ocor-poc` e filtro `io.x-k8s.kind.cluster=ocor-poc` (17
    file) e rete Docker condivisa `kind` (vedi VF-001 di REM-0018);
  - volumi nominati del progetto, directory `.ocor`, CA e registrazioni SPIRE,
    file credenziali e `OCOR_BOOTSTRAP_ENV`/`OCOR_LIVE_POSTGRES_DSN` unici;
  - la guardia della memoria uccide per nome tutti i container `ocor-poc`.
- **Test non divisibili**: il caso Helm (unico cluster kind); i moduli diversi
  da 0049 restano interi (ordine e stato condiviso dei fixture di modulo); i
  casi di 0049 sono gia unita indipendenti qualificate (REM19 GO,
  REM-0017-CI-0049-REMAINDER-CAP). Equivalenza dimostrabile con gli strumenti
  esistenti: `collect_nodeids`, selezione esplicita per node ID senza
  deselect, controllo JUnit della parte e `aggregate()` con unione esatta
  contro `--collect-only`, zero skip, digest di partizione.
- **Riuso della partizione CI**: `scripts/run_qualifying_campaign.py` ha gia
  `--shard-count/--shard-index/--aggregate`. In CI ogni parte ha il proprio
  runner e il proprio stack (REM-0018, run 40172921389: parti 4/4 fra 1046 e
  1522 s, parte 1 col solo Helm 1190-1250 s; 0049 a 5 parti 961-1250 s). Si
  riusano partizione, prova di selezione e aggregazione. Non e riusabile
  l'isolamento, che in CI e fornito dai runner separati.

### Esito e interventi

1. L'intervento utile e la suite locale in 2 parti, gia autorizzata come
   `OCOR-DEV-REM-0037` (LOCAL-SUITE-SPLIT): questo esito ne e l'input di
   progetto. Per il guadagno pieno la partizione locale deve calcolarsi dai
   tempi misurati e lasciare che il caso Helm condivida la parte con altre
   unita; le regole di `partition()` restano invariate per la CI. E una
   scelta operativa entro LOCAL-SUITE-SPLIT punto 4, quindi non serve una
   nuova richiesta. Se richiedesse di cambiare il partizionamento CI o la
   fonte dell'evidenza, REM-0037 si fermera con una decision request.
2. Accorciare l'attesa del tick reale della CronJob nel caso Helm (per
   esempio con un Job creato dalla CronJob) cambierebbe cio che il caso
   prova. Sarebbe **normativo** e **non e raccomandato**: nessuna richiesta.
3. Qualificare l'implementatore tramite le parti della CI cambierebbe la
   fonte dell'evidenza ed e **normativo**. Non lo si propone prima di misurare
   REM-0037: nessuna richiesta ora.
4. La preparazione dello stack vale circa l'1% e non giustifica interventi.

Nessuna nuova decision request e aperta da questo esito. Nessuna
implementazione eseguita, nessun limite toccato. Inputs immutabili; E1=0,
E2=0, Verified=0; runtime NOT_ESTABLISHED, PoC/Production NO-GO; nessun nuovo
DEC.
