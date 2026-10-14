# OCOR-DEV-REM-0032-RCCAD — 0049: healthcheck dei relay senza saturazione della CPU

- **Status**: `SEALED` (repair cycle 1; task stage, CI REM-0017 e integrazione ancora da eseguire). Verifier: Grok 4.7 via Cursor CLI (processo, contesto e fornitore separati);
  Codex (riparazione 1) e Claude Code (ciclo 0) non verificano questo change set (`LOOP-ROLES`).
- **Fonte**: decisione del Product Owner `REM-0017-CI-0049-RELAY-PROBE-REMEDIATION` (2026-10-14), che
  risolve `REM-0017-CI-0049-RELAY-HEALTH-OPTION2` con l'opzione 1 e anticipa `OCOR-DEV-REM-0032` (già
  registrata) prima del merge di 0049.
- **Branch**: `governed/ocor-dev-rem-0032-relay-probe`, radicato nel task stage
  `a0ee43d4e502f3589cd857cfec4238eab13fe8e7` senza riscriverlo. Commit: test `3c7f8c5`, correzione
  `7632bc9`, campagna `04b9dcb`.

## Difetto

L'healthcheck dei relay (`x-relay` in `deploy/helm/ocor-poc/compose.profiles.yaml`) avviava ogni 2 s
un interprete Python che compilava l'intero agente ops e rivalidava il profilo prima di aprire un
socket. Misura su un relay inattivo: 231.25 ms di CPU per probe e
117.66 ms di CPU al secondo per relay. Con tre progetti PoC (30 relay)
su 4 core i soli probe occupano tutta la CPU disponibile e, con altro carico, i relay diventano
unhealthy nel setup dei casi di 0049: è la firma della CI `fad37b4` (run `38548656297`).

## Correzione

Solo l'healthcheck dei relay e una variabile d'ambiente per relay:

- probe `bash -c 'exec 3<>"/dev/tcp/127.0.0.1/${OCOR_RELAY_FLOW_PORT:?}"'`: connessione TCP alla
  porta del flusso autorizzato del relay, come prima, senza avviare l'agente né rivalidare il profilo;
- `OCOR_RELAY_FLOW_PORT` per ciascun relay, uguale alla porta della sua voce in
  `isolation.allowedFlows` (verificato da test); variabile assente → probe fallito;
- `interval: 3s`, `timeout: 3s`, `retries: 5`, `start_period: 60s`: relay morto dopo lo start period
  unhealthy entro 15 s (connessione rifiutata) o 30 s (probe appeso).

Invariati, con prova: agente ops e profilo (configs byte-identici), readiness di `ocor-ops` e gate
`RESTORE_UNTESTED`, allowlist e flussi dei relay, `depends_on`, reti e isolamento, immagini e digest,
chart Helm (non contiene relay: il difetto non vi è presente), test di 0049 e di REM-0019, timer, tetti
e gate di campagna e CI. Il digest SHA256 del documento Compose canonico senza l'healthcheck dei relay e
senza `OCOR_RELAY_FLOW_PORT` coincide con quello del task stage.

## Prove del ciclo 0 (diagnostiche per VF-001)

Metodo di limitazione della CPU: every scenario container pinned with cpuset 0-3 (4 host cores); healthcheck execs inherit the relay cgroup; synthetic load = 8 single-thread busy loops, one container each, same cpuset; three Compose projects x 10 relays started concurrently with up --wait.

| Prova | Task stage (`a0ee43d`) | Correzione |
|---|---|---|
| CPU per probe (relay inattivo, 40 exec) | 231.25 ms | 20.91 ms |
| Durata per probe | 256.14 ms | 41.2 ms |
| Scenario: relay unhealthy | 4 | 0 |
| Scenario: exit `up --wait` dei tre progetti | [0, 1, 1] | [0, 0, 0] |
| Scenario: CPU dei relay (core) | 2.768 | 0.214 |

- **RED** (`3c7f8c5`, worktree separato): 5 casi falliscono sul probe del task
  stage — tre criteri statici, lo scenario GREEN (14 relay unhealthy) e
  il controllo del relay morto (start period assente); il caso di invarianza passa per costruzione.
- **GREEN** (`7632bc9`): 7/7 PASS,
  compreso il RED riprodotto come test sul probe del task stage.
- **Controlli negativi**: relay ucciso dopo lo start period → unhealthy in
  15.3 s
  (limite 30 s), container ancora in esecuzione e `Connection refused` nel Health.Log; porta di flusso
  errata → mai healthy; relay intatto → healthy.

## Riqualifiche (HEAD `04b9dcb8cc77`, stack reale, ricetta di bootstrap CI)

- Suite completa: 2224 PASS, 0 FAIL, 0 skip, 3504 s.
- `OCOR-DEV-0049`, tre suite del task consecutive: 390 PASS, 0 FAIL, 0 skip, 2241 s; 390 PASS, 0 FAIL, 0 skip, 2241 s; 390 PASS, 0 FAIL, 0 skip, 2246 s.
  Record `reports/evidence/G4/OCOR-DEV-0049.requalified-rem0032.json`, `supersedes` il record sigillato
  `OCOR-DEV-0049.json` di questa linea; il record REM-0019 della linea sorella (PR #254) è dichiarato
  in `concurrent_lineage`.
- `OCOR-DEV-0050`, sola regressione (l'allowlist del validator di piano è un suo input sigillato):
  record `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0032.json`, `supersedes`
  `OCOR-DEV-0050-requalified-rem0026-5e1935e93126`.
- Suite della REM del ciclo 0: 7 PASS, 0 FAIL, 0 skip, 441 s; diagnostica per VF-001, sostituita dalla prova della riparazione 1. Residui delle risorse Docker: zero dopo ogni run.

## Rischi residui e limiti

- The scenario emulates the runner load with a declared synthetic load on 4 pinned cores of a 14-core host; dockerd/containerd/runc work outside the container cgroups is not limited to those cores. The qualifying proof on GitHub runners is the next REM-0017 CI pair, with outcomes fixed by the PO decision.
- docker exec itself costs ~20 ms CPU per probe: it is the floor of any Docker healthcheck.
- `NOT_EXECUTED`: CI exact-head run of the REM-0017 candidate with the new pin (next step after GO and seal).

Nessun record sigillato modificato. Nessun nuovo `DEC-*`. `E1=0`, `E2=0`, nessun requisito `Verified`;
runtime conformance `NOT_ESTABLISHED`, PoC-GO e Production readiness `NO-GO`. Nessuna modifica a `inputs/`.

## Riparazione 1 — VF-001 (Codex)

Il NO_GO `OCOR-DEV-REM-0032-5645ac703362-0` resta storico. Il verifier ha riprodotto
due volte timeout senza raggiungere i 15 fallimenti consecutivi del probe originale.
Le prove della suite REM del ciclo 0 sono diagnostiche rispetto a questo finding.

La priorità relativa dei soli carichi sintetici è ora dichiarata: otto processi,
CPU shares 8192 ciascuno, stessi quattro core dei trenta relay. Docker e cgroup
sono letti per tutti i container; nessun timer, peso o comando dei relay cambia.
Questo è un confine di contesa sostenuta sintetica, non una stima del carico esatto CI.

- `red2-red`: 30 relay unhealthy, up [1, 1, 1], CPU 1.26 core, zero residui.

- `red3-red`: 30 relay unhealthy, up [1, 1, 1], CPU 1.21 core, zero residui.

- `rem-red`: 30 relay unhealthy, up [1, 1, 1], CPU 1.208 core, zero residui.

- `rem-green`: 0 relay unhealthy, up [0, 0, 0], CPU 0.203 core, zero residui.

Le due riproduzioni RED consecutive e la suite REM sono sul commit `9b76eb5e3df07d3774eec15634ff1abce8a7c1c3`.
La campagna runtime (2224 casi; tre suite 0049 da 390 casi) resta quella di Claude Code
a `04b9dcb`, con hash degli alberi di esecuzione identici, comandi, log ed ambiente
originali conservati; i file di riqualifica e i manifest non cambiano. Il nuovo
instrumento è usato soltanto dalla suite REM, rieseguita integralmente. Nessun test
0049 o REM-0019 cambia. Verifier richiesto: Grok 4.7 via Cursor, contesto separato.

## Verifica indipendente e sigillo

GO `OCOR-DEV-REM-0032-4f0bd4d63e8b-1` del 2026-10-14, HEAD esatto
`4f0bd4d63e8bc4260f39fb2cae9cc6f6b285bcba`: Grok 4.7 via Cursor CLI,
processo e contesto separati e fornitore diverso da entrambi gli implementatori.
Ciclo 0 e campagna runtime: Claude Code di riserva; riparazione 1 e sigillo: Codex.
Il verifier ha riprodotto due RED consecutive, la suite REM (7 PASS), il costo CPU
e la suite completa (2224 PASS, zero skip), senza finding. I risultati originali
restano attribuiti ai propri commit, log, ambiente ed esecutore.

Il sigillo aggiorna soltanto metadati di verifica, stato di questi tre record nuovi,
README e hash dei due record di riqualifica nei manifest; raw log, implementazione,
test, harness, workflow, lock e sigilli storici byte-identici all'HEAD verificato.
Resta `NOT_EXECUTED` la coppia CI REM-0017 con il nuovo pin: viene eseguita
nella prossima unità separata, con il ribilanciamento N già autorizzato e gli esiti
fissati dalla decisione PO. Nessuna integrazione su main o chiusura di REM-0017/0049
è inferita da questo sigillo. Il recinto delle evidenze resta invariato.
