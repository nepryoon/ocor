# CI-0049-KIND-BOOTSTRAP-EXEC-PROBE

Stato: `RESOLVED` (decisione del PO del 2026-10-15, opzione 1; vedi «Risoluzione»). Apertura: 2026-10-15. Autore della richiesta: Claude Code
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


## Addendum 2026-10-15 — ricorrenza su PR #280 e impatto sul gate obbligatorio

Nessuna nuova domanda normativa: le opzioni già aperte restano invariate.
Nuova occorrenza sullo state sync REM-0019, HEAD
`b50dd030c32ed6476ed31fa63993a06448d5fb4a`, run `38695636096`, parte Helm
`conditional-infrastructure-0049 part 1/5`, job `116291443520`, artifact
`11953484622`. Il primo probe `docker exec … systemctl show containerd` sul nodo
`3d93a821ec8746bc2457bfe837c923272793654452565f6b777144ce41c613a8`
fallisce con exit 1 alle 07:01:19Z in 36,6 ms. Il percorso v2 rileva il nodo
ancora presente, running, senza OOM o restart, e rifiuta con
`WINDOW_EXPIRED_NODE_PRESENT` alle 07:01:49Z (finestra 30 s). Nessuna rimozione
qualificante; teardown del progetto e inventario finale PASS, zero residui.
Nessun rerun, come previsto per questa firma di rifiuto v2.

**Erratum sull'impatto:** il fatto che il job condizionale abbia un nome non
incluso nei 13 check del ruleset non lo rende non bloccante. In
`.github/workflows/ocor-validation-closure.yml`, `validation-closure` dipende
anche da `conditional-infrastructure-0049` (riga 158) e ne richiede il risultato
success (riga 178). Su questo HEAD le quattro parti di validation sono success,
ma il check obbligatorio `validation-closure`, job `116300760193`, è FAIL sul
confronto `test "failure" = success`. Questa dipendenza smentisce la precedente
lettura del record di stato secondo cui la richiesta non bloccava i merge.
La PR #280 resta non integrabile: nessun gate ignorato o modificato, nessun
risultato globale PASS dichiarato. Le unità non dipendenti possono procedere in
worktree isolati, ma anche le loro integrazioni richiederanno lo stesso gate.

Prove SHA256:

- log parte Helm: `331e9562fb9e3c2ed4443a4dbe74ba838902ca559f9408e544bb49c75a02b0e4`;
- `kind-teardown-observations.json`: `247227a25e7e820e29f92addc6ad434c735c4e7ad2f8d9e9aeadc940142b97e1`;
- log aggregatore obbligatorio: `a7c7000c0fa6cb0c0403e12937950cc346d5b59a45663ec740269a5376b36297`.

Resta invariato l'ambito delle opzioni della richiesta: nessuna correzione del
probe, aumento di timer, esclusione di test o modifica del workflow applicata.
E1/E2/Verified/NO-GO e tutti i sigilli storici invariati. Autore dell'addendum:
Codex, implementatore del loop. La nuova domanda sui marcatori sintetici di un
record sigillato è separata (`REM-0019-SEALED-SYNTHETIC-SECRET-SCANNER`, PR #279).

## Risoluzione — decisione del PO del 2026-10-15 (opzione 1)

Il PO ha risolto la richiesta con l'opzione 1, alle condizioni seguenti, eseguite nel change set
`governed/ocor-dev-rem-0033-kind-bootstrap-exec-probe` con l'identificativo `OCOR-DEV-REM-0033`
(primo `REM-*` libero, verificato in sola lettura su tutti i ref remoti e sui file del loop il
2026-10-15: zero occorrenze di `REM-0033`).

- **Priorità.** La correzione precede ogni altra unità: `validation-closure`, check obbligatorio,
  dipende da `conditional-infrastructure-0049`. Poi: change set dello scanner → integrazione di
  REM-0019 → REM-0023 → 0056 → … → REM-0030.
- **Ambito, solo harness:** `scripts/run_qualifying_campaign.py`, `scripts/observe_kind_teardown.py`,
  test in `reports/tests/`, record ed evidenze, allowlist del piano, file di stato. Nessuna modifica a
  workflow, codice o test di 0049, immagini, versioni.
- **Correzione:** (1) ogni probe `docker exec` fallito registra stderr limitato e redatto ed exit
  code; (2) un probe `systemctl show` fallito su un nodo posseduto che, dentro la stessa finestra di
  30 s, resta presente, `running`, senza OOM né restart e con lo stesso PID del container, viene
  ripetuto a ogni giro di polling; accettato solo se lo stesso probe torna a 0 con
  `ActiveState=active` entro la finestra e, se il nodo era già ammesso, con `NRestarts` zero;
  (3) restano fatali finestra scaduta con probe ancora fallito, OOM, restart, PID cambiato, identità
  diversa e, per un nodo che scompare, evento `destroy` o remover mancanti; (4) invariati cadenza,
  timeout del probe, finestra di 30 s, tetti, comando pytest, partizione, selezione, gate.
- **Prove:** RED/GREEN deterministici, prova AST dell'invarianza dell'esecuzione, full locale e
  regressione 0050 secondo «Cambio di harness» di `QUALIFICATION-CAMPAIGN-INFRA-RERUN`.
- **Qualifica:** 13 check obbligatori verdi sull'HEAD esatto della PR della correzione, con la parte
  Helm accettata. Rifiuto v2 della parte Helm per un motivo diverso dal probe di avvio: nessun rerun,
  nuova decision request con stderr e dati. Le ricorrenze su #273 e #280 restano diagnostiche.
- **Ruoli e budget:** implementatore Claude Code di riserva (quota Codex esaurita), verifier Grok 4.7
  via Cursor, fornitori diversi; budget ordinario di due cicli di riparazione.

Nessun nuovo `DEC-*`. E1, E2, `Verified` e claim invariati. La draft PR #274 è superata dalla PR del
change set REM-0033.
