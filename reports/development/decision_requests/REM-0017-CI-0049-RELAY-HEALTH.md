# REM-0017-CI-0049-RELAY-HEALTH

Stato: `OPEN_PO_DECISION_REQUIRED` — 2026-10-14.

## Contesto e fatti

CI sull'HEAD esatto `f438098c17a392948b8d0158019fb924837a6c68` della PR #169 (draft,
`governed/ocor-dev-rem-0017-ci-provision-spire`), run `38503096173`, `38503096215`,
`38503096559`, `38503096585`, `38503096600`, `38503096923`, `38503097088`:

- la correzione degli import della campagna (`de63f41`, Codex) è confermata: tutte le
  parti 1–4 di `rccad-methodology`, `delivery-activation` e `validation-closure` sono
  PASS e i loro aggregatori sono verdi; anche gli altri check obbligatori sono PASS;
- `conditional-infrastructure-0049` parti 1, 2 e 4 PASS; **parte 3/4 FAIL**: 621 casi,
  620 PASS, 0 failure, 0 skip, **1 error in setup** (1764,44 s, sotto il tetto di 2700 s).
  Gli aggregatori `validation-closure` e `conditional-infrastructure-0049` falliscono
  solo per questa parte.

Il caso è `test_readiness_turns_ready_only_with_a_signed_passed_restore_receipt`. L'errore
è nella fixture `fresh_tested_ops` → `_seal_and_restore`, stage `backup`, con
`docker compose`: `dependency failed to start: container
ocor-poc-tested-47bc3a-ocor-relay-fuseki-1 is unhealthy`. Il codice sotto test non ha
nessuna asserzione fallita.

Diagnosi:

- l'healthcheck dei relay (`deploy/helm/ocor-poc/compose.profiles.yaml`, ancora `x-relay`,
  comando `relay-probe`) apre soltanto `127.0.0.1:<porta>` dentro il container del relay
  (connect 2 s; timeout 3 s, intervallo 2 s, 15 tentativi). Non dipende dal servizio a monte. Il
  relay aveva già registrato `relay_start ALLOWLIST_ACTIVE`;
- Fuseki dello stack era partito al bootstrap (03:14:18Z) e alle 03:16:06Z rispondeva
  ancora. Il supervisore della campagna non ha osservato riavvii né OOM e non ha
  interrotto il run;
- una contesa di CPU del runner è plausibile (alle 03:30:22Z il broker Kafka dello stack
  ha subito un timeout di sessione), ma **non è provata**: `stack.down(project)` precede
  l'asserzione e il log dell'healthcheck viene distrutto con il progetto Compose;
- **ricorrenza**: la stessa firma compare nel run CI del 2026-10-09 su `4e97cd3`
  (parte 4 di 0049), con sette relay diversi unhealthy (keycloak, openbao, opa ×2,
  typedb, terminusdb, kafka). Nelle campagne locali REM-0019 non è mai comparsa.

Raw e diagnosi content-addressed fuori dal repository:
`/home/luca/.ocor-codex/rem0017-ci-diagnosis-20261014/attempts/ci-f438098c17a3-0049-part3/`
(`diagnosis.json` SHA256 `b560aa72884dcc0f9c8ed729b64abc704b4a66385460deaae8f24175894f9752`;
log del job part 3 `bd7216e27f749d990424e9b76aa6fb117caa3e6fe72b774e780c53891dcae2fd`;
artifact `b348e1254486daafea4127c889e3e676ec49bb4d380114e72b85850914ff1c13`).

`QUALIFICATION-CAMPAIGN-INFRA-RERUN` ammette la ripetizione solo con una causa
infrastrutturale provata dai log. Qui la causa non è provata e la stessa firma ha colpito
più run: quindi nessun rerun e nessun nuovo HEAD con soli metadati per ottenere una CI
nuova. Una correzione dell'healthcheck toccherebbe il codice di deploy di 0049, che
REM-0019 vieta di modificare e che è coperto dal GO sigillato.

## Opzioni

1. **Osservazione, poi decisione.** Il harness di campagna (`scripts/run_qualifying_campaign.py`,
   change set REM-0017) si iscrive agli eventi Docker `health_status: unhealthy` dei container
   `ocor-poc-*` e ne salva subito `.State.Health.Log`, insieme a `docker stats` e al load del
   runner, prima che il progetto venga rimosso. La modifica è di sola osservazione: comando
   pytest, partizione, timer e gate restano invariati, con prove RED/GREEN deterministiche.
   Poi segue una nuova CI sull'HEAD esatto. Se la firma ricompare con una causa provata
   (timeout del probe per contesa di CPU), si applica `QUALIFICATION-CAMPAIGN-INFRA-RERUN`
   oppure, se la causa è nel relay, la remediation dell'opzione 2.
2. **Remediation del deploy 0049.** Si apre una REM con il prossimo identificativo libero
   per rendere robusta la readiness dei relay (per esempio `start_period` e un budget del
   probe dichiarato e coerente con i tempi del profilo PoC). Servono un RED riproducibile
   sotto CPU limitata, la riqualifica di 0049 con supersession e il sigillo storico
   invariato. È una modifica al codice di produzione di 0049 coperto dal GO.
3. **Risorse del runner.** Si aumenta N per il solo job 0049 (per esempio 5 parti) per
   ridurre il carico di ogni parte, senza toccare il codice di 0049. Non è garantito che
   elimini la contesa, perché ogni parte avvia comunque lo stack completo.

## Raccomandazione

Opzione 1. È l'unica che produce la prova mancante senza toccare codice sigillato né
criteri. Decide poi in modo fondato tra un rerun infrastrutturale e la remediation
(opzione 2). La modifica di sola osservazione ricade nella clausola "Cambio di harness" di
`QUALIFICATION-CAMPAIGN-INFRA-RERUN`. Viene comunque chiesta l'approvazione perché
produce un nuovo HEAD e una nuova coppia di run CI di REM-0017.

## Impatto e task bloccati

- Bloccati: chiusura verificata di `OCOR-DEV-REM-0017` (nessuna richiesta di verifica senza
  CI verde sull'HEAD esatto) e, a valle, merge di `OCOR-DEV-0049`, integrazione di REM-0019
  (PR #254), REM-0023 e 0056.
- Non bloccati: REM-0024, REM-0028, REM-0029 e REM-0027 (ultimo ciclo), eseguibili prima di G6.

Implementatore: Claude Code (Anthropic, claude-opus-5-5), implementatore di riserva del loop.
Verifier previsto per REM-0017: Grok 4.7 via Cursor. E1=0, E2=0, Verified=0, NO-GO
invariati; nessuna modifica a `inputs/`, al codice, ai test o ai record sigillati.
