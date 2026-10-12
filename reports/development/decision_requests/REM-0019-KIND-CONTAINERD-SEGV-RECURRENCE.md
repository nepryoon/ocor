# REM-0019-KIND-CONTAINERD-SEGV-RECURRENCE

Stato: `OPEN_PO_DECISION_REQUIRED` — 2026-10-12.

## Contesto e fatti

La decisione `REM-0019-KIND-TEARDOWN-OBSERVATION` (opzione 1) è stata eseguita il
2026-10-12 da Claude Code, implementatore di riserva del loop:

- adapter di osservazione v2 (`watchdog_safe.py`) nella campagna
  `/home/luca/.ocor-codex/rem0019-resume-20261012-attempt5/`: la rimozione del nodo kind
  è accettata solo se legata al processo `kind delete cluster --name ocor-poc` del gruppo
  pytest (campionato da `/proc` ogni 0,2 s), allo stesso UUID e all'evento `destroy`,
  entro una finestra dichiarata di 30 s;
- prove deterministiche: RED della v1 (`red-teardown-v1.log`, 4 failure e 4 error su 13),
  GREEN della v2 14/14, negativi della v1 tutti ancora fatali sulla v2; prova reale con
  Docker e binario kind veri, 4/4 (`probe-teardown-real.json`, inventario invariato);
- la prova reale ha trovato un secondo difetto della v1: il CLI Docker 29 stampa
  `error: no such object: <id>` (minuscolo), quindi la v1 non riconosceva mai l'assenza
  del nodo. Corretto con un caso RED/GREEN dedicato;
- `harness-change-record.json` (SHA256
  `14293e2679756745eb7cb6f519900a885d09bffd65e1e85007f6a7813c8e55e5`): cambiano solo
  `watchdog_safe.py` e, in `run_nodes.py`, l'avvio/arresto del campionatore e due campi
  di osservazione. Comando pytest, ambiente, ordini, limiti, controlli di runtime e
  teardown sono identici; la full attempt-3 (2196) resta valida.

Ripetizione di `order-collection` (tentativo 2, unica ripetizione usata su due):
preflight PASS con 11 servizi, collezione identica a quella della full conservata.
Exit 130 dopo 1510 s: **FAIL infrastrutturale, non qualificante**. JUnit ha 386 casi,
zero failure/error/skip; nessuna asserzione fallita. Alle 20:08:58Z `containerd` del nodo
`kindest/node:v1.33.1` (digest `050072256b9a…`) termina con
`code=dumped, status=11/SEGV` durante `kind create` della fixture del caso Helm
(posizione 387 su 390); systemd lo riavvia (`NRestarts=1`) e il controllo di runtime
invariato ferma il run. L'adapter v2 non è coinvolto (nessuna sonda fallita, nessun
rifiuto o rimozione registrati).

È la stessa causa della full attempt-1 di questa campagna (SEGV alle 05:44:57Z, creazione
della sandbox del backup manuale) e di `REM-0017-KIND-CONTAINERD-CRASH`, la cui diagnosi
offline localizza il fault in `runtime.mallocgcSmallNoscan+0xd8` con catena
`mexit -> vgetrandomPutState -> growslice -> mallocgc`, binario compilato con Go 1.24.2.
`QUALIFICATION-CAMPAIGN-INFRA-RERUN` impone di fermarsi quando la stessa causa colpisce
più run: nessuna ulteriore ripetizione è stata avviata.

### Correlazione con un difetto Go noto (fonte esterna, non prova locale)

Il difetto upstream Go #73141/#73144 descrive esattamente questo meccanismo: lo stato
vgetrandom di una M distrutta veniva rilasciato in `mdestroy` dopo il rilascio della P,
quindi con allocazione vietata. Il sintomo è un SIGSEGV senza output né stack trace,
diagnosticabile solo da core. La correzione è stata riportata sul ramo 1.24 dopo la
1.24.2 ed è presente come patch nei pacchetti delle distribuzioni
([patch vgetrandom per Go 1.24](https://ftp.riken.jp/Linux/gentoo-portage/dev-lang/go/files/go-1.24-vgetrandom.patch),
[patch Debian golang-1.24 1.24.2-2](https://sources.debian.org/patches/golang-1.24/1.24.2-2)).
Il percorso richiede il vDSO `getrandom` (kernel Linux ≥ 6.11): l'host locale usa il
kernel 7.0.0-38. Questo spiegherebbe perché il crash compare in locale. La correlazione
è un'inferenza: il fix non è stato provato qui e nessuna mitigazione è stata tentata.

### Residuo osservato (difetto separato, nell'ambito di REM-0019)

Lo SIGINT è arrivato durante `kind create`, nella fase di setup della fixture `kind` di
`test_ocor_dev_0049.py`. Quella fixture cancella il cluster solo nel `finally` dopo lo
`yield`, quindi non lo cancella se il setup viene interrotto. Sono rimasti il nodo
`ocor-poc-control-plane`, il suo volume `/var` e la rete `ocor-bootstrap_ocor-bootstrap`
che il nodo teneva occupata. `reset_test_environment.py` ha riportato PASS anche se la
rete era ancora in uso. Il residuo è stato rilevato da `modules.py` (`ok=false`) e
rimosso con `kind delete cluster --name ocor-poc` e `docker network rm`, entrambi su
risorse OCOR; l'inventario finale è identico a quello iniziale. Correggerlo cambia il
codice di test di 0049, quindi richiede di rifare l'intera campagna.

## Prove riproducibili

- `attempts/order-collection/attempt-2/diagnosis.json`, SHA256
  `45f3c566bcb539843fb0ad559e12716395686cd760326578987ef56030c6cd77`, con hash dei raw,
  journal privato di containerd, inspect ed eventi del nodo residuo, inventario dopo la
  pulizia.
- `attempts/order-collection/attempt-1/diagnosis.json` (osservazione, v1) e
  `attempts/full/attempt-1/diagnosis.json` (SEGV) restano diagnostici e invariati.
- Diagnosi offline REM-0017: `/home/luca/.ocor-codex/rem0017-offline-diagnosis-20261012/diagnosis.json`.

## Opzioni e raccomandazione

1. **Raccomandata:** autorizzare per la sola esecuzione locale della campagna un'immagine
   `kindest/node` con lo stesso Kubernetes v1.33.x e un containerd compilato con Go
   contenente il fix (≥ la patch release 1.24 che include #73141/#73144), fissata per
   digest e verificata (versione Go del binario containerd letta da `go version -m`
   sull'immagine). La modifica cambia `KIND_NODE_IMAGE` nel test di 0049, quindi rientra
   in REM-0019 con un nuovo commit. Nello stesso commit si corregge il residuo: la
   creazione del cluster passa dentro `try/finally`. Poi si rifà l'intera campagna
   (full, 5 ordini, 119 isolati) sul nuovo commit, con l'adapter v2 invariato. Il ciclo
   di riparazione non va consumato, perché il difetto è infrastrutturale.
2. Mitigazione d'ambiente senza cambiare immagine: avviare la campagna su un host o una
   VM con kernel < 6.11 (senza vDSO getrandom), oppure su runner CI, e registrare il
   kernel nell'evidenza. Il residuo della fixture va comunque corretto con un commit
   di test.
3. Correggere soltanto il residuo della fixture e ripetere la campagna con l'immagine
   invariata, accettando una probabilità di SEGV per run che resta non controllata.
   Non raccomandata: i run da 40 minuti continuerebbero a fallire in modo casuale.

Sono escluse: ignorare il riavvio di containerd, considerare PASS l'exit 130, trasferire
conteggi dai tentativi diagnostici, ripetere senza una condizione cambiata.

## Impatto e integrazione

Restano bloccati la qualifica, la verifica e il sigillo di REM-0019, la nuova campagna CI
di REM-0017, l'integrazione di 0049 e la sequenza successiva. Restano eseguibili
indipendentemente gli audit `INFO-A` e `INFO-C` e `REM-0024`. REM-0019 resta al ciclo 1.
La chiusura di `REM-0019-KIND-TEARDOWN-OBSERVATION` (eseguita nella sostanza) e questo
nuovo percorso richiedono l'aggiunta puntuale all'allowlist del piano, con la riqualifica
di regressione di 0050. Si propone un unico change set per entrambi i file.

Implementatore: Claude Code di riserva (quota Codex esaurita). Verifier previsto per
REM-0019: Grok 4.7 tramite Cursor, in un processo separato. `E1=0`, `E2=0`,
`Verified=0`, claim `NO-GO`, input e record sigillati invariati.
