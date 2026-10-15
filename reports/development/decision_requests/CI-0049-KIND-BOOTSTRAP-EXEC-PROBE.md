# CI-0049-KIND-BOOTSTRAP-EXEC-PROBE

Stato: `OPEN_PO_DECISION_REQUIRED`. Apertura: 2026-10-15. Autore della richiesta: Claude Code
di riserva (quota Codex esaurita).

## Contesto e fatti

Dopo l'integrazione della PR #169 (merge `1ee05b1`) il job non obbligatorio
`conditional-infrastructure-0049` gira su ogni PR verso `main`. Sulla PR di state sync #273
(HEAD `38d259a08580efd78ee621cb3ce91b65f370570d`, run `38667351904`, job `116202218769`)
la parte 1/5 (caso Helm) è FAIL con rifiuto v2 `WINDOW_EXPIRED_NODE_PRESENT`:

- alle 01:48:26.229Z il primo `docker exec <nodo> systemctl show containerd
  --property=ActiveState,MainPID,NRestarts` sul nodo kind appena comparso esce con codice 1
  in 39 ms (stderr non catturato dal probe);
- il percorso v2 (`scripts/observe_kind_teardown.py`, `inspect_kubernetes_runtimes`) esegue
  59 `docker inspect`, tutti con exit 0: nodo presente, `running`, `OOMKilled=false`,
  `RestartCount=0` per l'intera finestra di 30 s; a finestra scaduta rifiuta, fail-closed come
  previsto;
- lo stesso `docker exec` ripetuto alle 01:48:56.65Z restituisce 0 per containerd e kubelet
  (containerd PID 118, zero restart); il journal del nodo mostra kubeadm in avvio (kubelet
  fermato e riavviato alle 01:48:37, API server non ancora raggiungibile): il primo probe ha
  corso contro l'avvio di systemd/del nodo;
- pytest è interrotto dal supervisore dopo 70,24 s: nessun caso completato, nessuna asserzione
  fallita; teardown PASS, zero residui;
- gli stessi alberi di esecuzione (workflow, harness, candidato 0049 `beab1b4`) hanno superato
  la parte Helm su `022585a` (run `38657398743`, `OWNED_KIND_TEARDOWN_OBSERVED`) e
  sull'HEAD sigillato `5115e2e`.

Riferimenti precisi: `scripts/run_qualifying_campaign.py:649` (`inspect_kubernetes_runtimes_raw`,
`check=True` sul probe `systemctl show`) e `scripts/observe_kind_teardown.py`
(`inspect_kubernetes_runtimes`, finestra 30 s). Diagnosi riproducibile:
`reports/assurance/OCOR-DEV-REM-0017-RCCAD/ci-38d259a-kind-bootstrap-exec-diagnosis.json`
(digest dell'artifact `11943371100` e del log del job).

Applicazione delle regole vigenti: esito 3 di `REM-0017-CI-KIND-INSPECT-TIMEOUT` (rifiuto v2
nella parte Helm), quindi nessun rerun eseguito. Non è stabilita la causa esatta dell'exit 1:
manca lo stderr del probe.

## Opzioni e raccomandazione

1. **Correzione governata dell'osservazione, raccomandata.** Nel solo harness
   (`scripts/run_qualifying_campaign.py`, `scripts/observe_kind_teardown.py`, test in
   `reports/tests/`): (a) catturare stderr ed exit code di ogni probe `docker exec` fallito;
   (b) un probe `systemctl show` fallito su un nodo posseduto che, all'interno della stessa
   finestra di 30 s, resta presente, `running`, senza OOM né restart e con PID invariato,
   viene rieseguito una volta per ciclo di polling. Il nodo è accettato soltanto se lo
   stesso probe torna a 0 con `ActiveState=active` entro la finestra; con zero `NRestarts`
   se il nodo era già ammesso. Restano FAIL: finestra scaduta, OOM, restart, PID cambiato,
   identità diversa, evento destroy o remover mancanti. Cadenza, timeout del probe, finestra,
   tetti, comando pytest e gate invariati. Servono RED/GREEN deterministici, prova AST
   dell'invarianza dell'esecuzione, full locale e regressione 0050 secondo «Cambio di harness»;
   rimane il budget CI ordinario.
2. Nessuna modifica: il job resta non obbligatorio e si registra ogni ricorrenza come
   diagnostica, senza rerun. Ne segue che un FAIL di questa firma non qualifica né squalifica
   le PR, ma il caso Helm resta senza prova CI su quell'HEAD.
3. Solo raccolta diagnostica (punto (a) dell'opzione 1) per una ricorrenza, poi nuova decisione.

Esclusi: aumento della finestra o dei timeout, catch che produce PASS senza prova, skip o
deselezioni, cambio di immagine o versione, rerun fino al verde.

## Impatto

Non blocca nessuna PR: i 13 check obbligatori del ruleset `23412233` restano l'unico criterio
di merge (`LOOP-NONINTERACTIVE-WAITS`). Indebolisce la lettura qualificante di
`conditional-infrastructure-0049` sulle prossime PR (0049 PR #176, REM-0019 PR #254, dismissione
del pin `TEST-INFRA-006`): un FAIL con questa firma non può essere né rieseguito né
considerato qualificante finché il PO non decide. Nessun nuovo `DEC-*`. Inputs intatti, E1=0,
E2=0, Verified=0 e tutti i NO-GO invariati.

Questa PR è DRAFT di sola richiesta: nessuna estensione dell'allowlist del piano in questo
branch, quindi il gate del piano può rifiutare i nuovi path.
