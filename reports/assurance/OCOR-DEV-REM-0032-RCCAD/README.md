# OCOR-DEV-REM-0032-RCCAD — 0049: healthcheck dei relay senza saturazione della CPU

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`. Verifier: Grok 4.7 via Cursor CLI (processo, contesto e fornitore separati);
  Claude Code, implementatore di riserva, non verifica questo change set (`LOOP-ROLES`).
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

## Prove

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
- Suite della REM nella campagna: 7 PASS, 0 FAIL, 0 skip, 441 s. Residui delle risorse Docker: zero dopo ogni run.

## Rischi residui e limiti

- The scenario emulates the runner load with a declared synthetic load on 4 pinned cores of a 14-core host; dockerd/containerd/runc work outside the container cgroups is not limited to those cores. The qualifying proof on GitHub runners is the next REM-0017 CI pair, with outcomes fixed by the PO decision.
- docker exec itself costs ~20 ms CPU per probe: it is the floor of any Docker healthcheck.
- `NOT_EXECUTED`: CI exact-head run of the REM-0017 candidate with the new pin (next step after GO and seal).

Nessun record sigillato modificato. Nessun nuovo `DEC-*`. `E1=0`, `E2=0`, nessun requisito `Verified`;
runtime conformance `NOT_ESTABLISHED`, PoC-GO e Production readiness `NO-GO`. Nessuna modifica a `inputs/`.
