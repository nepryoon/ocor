# REM-0019-KIND-TEARDOWN-OBSERVATION

Stato: `OPEN_PO_DECISION_REQUIRED` — 2026-10-12.

## Contesto e fatti

La campagna seriale di REM-0019, ciclo di riparazione 1, usa il commit
`8842ab2658b9eee201fa1bd26d267a9f23c22df5`. Il full attempt-3 è una componente
valida conservata: 2196 casi, zero failure/error/skip, unione JUnit esatta e zero
residui. I due tentativi full precedenti restano diagnostici, senza conteggi
qualificanti trasferiti.

Il run `order-collection` del 2026-10-12 termina con exit 130 dopo 2419,44 secondi.
JUnit contiene esattamente i 390 casi richiesti, nell'ordine richiesto, con zero
failure/error/skip. Il log riporta `390 passed`, seguito da `KeyboardInterrupt`
durante il teardown della fixture `coherence_ops`. **Il run è FAIL diagnostico,
non PASS qualificante**, perché il watchdog ha interrotto il processo.

Il watchdog fallisce `docker exec <node UUID> systemctl show containerd` durante
la rimozione del nodo kind owned `5c4a35360270771bb6e28a8ce78d0a9c51d5add23f1dc0f35474c71a7e3aa76b`.
Gli eventi Docker registrano `die` (exit 137) alle 17:54:04,475715312 UTC e
`destroy` alle 17:54:05,936134330 UTC: intervallo 1,460419 secondi, nome
`ocor-poc-control-plane` e label del cluster `ocor-poc`. Nell'intervallo acquisito
non ci sono eventi OOM/restart; 95 snapshot privati precedenti mostrano il nodo
running, OOM false e RestartCount 0. Il processo preciso di rimozione non è stato
registrato nel ramo di errore: questo controllo è `NOT_EXECUTED`; non si afferma
una prova più forte dell'attribuzione.

Il comportamento è compatibile con la classe di race fra osservazione e teardown
già diagnosticata nel full storico attempt-4. L'adapter locale di osservazione
invariato non ha registrato un'eccezione valida di rimozione (`owned_node_observation_removals=[]`).
La ricorrenza su più run richiede stop e decision request secondo
`QUALIFICATION-CAMPAIGN-INFRA-RERUN` del 2026-10-12; nessun retry è stato avviato.

Il teardown finale del supervisor ha exit 0. Il confronto con l'inventario
immediatamente precedente agli ordini prova zero nuove risorse residue: rimosse
11 risorse container, una rete e quattro volumi dello stack di sessione;
preservati 23 container, cinque reti e 364 volumi preesistenti. Non è un motivo
per qualificare il run interrotto. Gli altri quattro ordini e i 119 isolati sono
`NOT_EXECUTED` in questa campagna.

## Prove riproducibili

- Archivio diagnostico immutabile:
  `/home/luca/.ocor-codex/rem0019-resume-20261012-attempt5/attempts/order-collection/attempt-1/`.
- `diagnosis.json` SHA256:
  `4cee2086930f8fca1ab751399d1f87a09a708dea2810bd96a15a7ff5d0c10547`;
  contiene hash dei raw, JUnit, comando, exit, durate, inventari e limiti della prova.
- Full valido:
  `attempts/full/attempt-3/valid-component.json`, già collegato allo stato versionato.
- Diagnostico storico per confronto:
  `attempts/historic-attempt4-full/diagnosis.json`.
- Ricontrollare SHA256 dei file elencati in `raw_sha256`, conteggi/identità/ordine
  JUnit e `watchdog_error` nei metadati; confrontare gli inventari con
  `full-resources-after.json` e `session-resources-after.json`.

## Opzioni e raccomandazione

1. **Raccomandata:** autorizzare una correzione limitata alla sola osservazione del
   teardown, con prove deterministiche positive/negative prima dell'uso. Legare
   l'intento di rimozione al processo kind del gruppo pytest, allo stesso UUID e
   all'evento destroy; la finestra di osservazione deve essere bounded. Nodo
   esistente senza intento provato, crash, OOM, restart, cambio PID o timeout
   continuano a fallire chiusi. Nessuna modifica a codice/test di produzione,
   criteri, immagini, versioni, timer o check obbligatori.
   Conservare il full verde solo se un confronto dimostra che la modifica tocca
   esclusivamente osservazione/smontaggio e non l'esecuzione dei test; altrimenti
   ricominciare l'intera campagna. Ripetere il solo ordine fallito al massimo due
   volte, mantenendo questo tentativo diagnostico; poi gli ordini residui e gli isolati.
2. Risolvere prima l'orchestrazione nel change set governato di REM-0017 e riprendere
   la campagna quando esiste una condizione infrastrutturale materialmente nuova,
   con la stessa dimostrazione di scope e conservazione delle prove.

Non si raccomanda di considerare PASS l'exit 130, ignorare il watchdog,
riclassificare i conteggi diagnostici o ripetere senza una condizione cambiata.

## Impatto e integrazione

Bloccati la qualifica/verifica/sigillo di REM-0019, la nuova campagna CI di
REM-0017, l'integrazione di 0049 e la sequenza successiva subordinata alla loro
chiusura. Resta eseguibile la diagnosi infrastrutturale di REM-0017 già autorizzata
con l'opzione 1 di `REM-0017-KIND-CONTAINERD-CRASH`, senza modifica di immagini o
versioni e senza avviare la campagna bloccata. Non consumato un nuovo ciclo di
riparazione: REM-0019 resta al ciclo 1.

Questo nuovo percorso della decision request non è nell'allowlist esatta del piano
su main. La richiesta è pubblicata su un branch governato separato; il gate del
piano rimane FAIL sul percorso nuovo. Lo stato/handoff principali riportano
integralmente disposizione e riferimento al commit della richiesta con un change
set di soli metadati. Nessuna allowlist o evidenza sigillata viene modificata per
far passare il controllo. La futura aggiunta puntuale richiede riqualifica 0050;
il difetto di denial audit resta REM-0023.

Implementatore: Codex; isolamento/VF-001 storici: Claude Code di riserva; verifier
previsto: Grok 4.7 tramite Cursor, processo e contesto separati. Nessuna verifica
indipendente richiesta durante il blocco. `E1=0`, `E2=0`, `Verified=0`, claim
`NO-GO`, input e record sigillati invariati.
