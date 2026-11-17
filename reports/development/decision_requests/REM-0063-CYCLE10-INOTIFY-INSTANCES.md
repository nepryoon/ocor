# REM-0063-CYCLE10-INOTIFY-INSTANCES

Stato: `OPEN_PO_DECISION_REQUIRED`.
Livello: operativo. Unità: `OCOR-DEV-REM-0063`, ciclo 10.
Branch di produzione: `governed/ocor-dev-rem-0063-mcp-profile`, ancora a `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.
Head del gate e della campagna: `3ae284727c9829902e72bea25c2f07373e60d969`.

## Contesto e perimetro

`REM-0063-CALCOLO-UNICO (2026-11-17)` punto 6 ferma la riparazione quando deve uscire dai file ammessi per l'unità e chiede una sola richiesta. Il punto 7 lascia invariati gate, campagna, controllo distinto, soglie e limiti. I file di produzione ammessi restano `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py` e gli helper `_mcp` di `ocor-runtime/src/ocor_runtime/c1/codegen.py`. Questa iterazione non modifica quei file.

`REM-0063-CYCLE10-LANE-ARGV-LIMIT (2026-11-17)` ha già scelto l'opzione 1. Quel change set è su `main` (PR #664, commit `364f853cfe41f2dd5413c78a2b2b0ce665b77b34`, merge `49ec6ed27e093142cf63d0343a6b40a509b6a5bf`) e tocca solo `scripts/run_local_lane_campaign.py` e `reports/tests/test_local_lane_campaign.py`. Non è stato committato sul branch di produzione. L'head di questa campagna discende da quel merge e dal tip di prodotto `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`, senza riscrivere la storia del branch di produzione.

Il gate pre-campagna su `3ae284727c9829902e72bea25c2f07373e60d969` è PASS. 51 passi PASS, 0 fallimenti, 6 `NOT_EXECUTED`. `gates.json` sha256 `50ee856e76341d1cc1528a02e20c7ea9e2977e693a303d035815920862c6ed7b`. Il gate sullo head `5a1a8aaff6af95470171c1add7f9e85f1ec997a8` non è stato rieseguito e resta il PASS già registrato. Non è il gate di questo head.

Tre campagne restano FAIL diagnostiche e non sono un PASS. Non si rilanciano.

La campagna `5a1a8aaff6af-1794907944` è fallita con `Errno 7 Argument list too long` prima di pytest. È il caso già deciso dall'opzione 1 dell'argv.

La campagna `8037040f14cc-1794928763` è fallita perché la raccolta della corsia 1 ha deselezionato 41953 item: pytest ha letto `-m` come marcatore. Il commit `3ae284727c9829902e72bea25c2f07373e60d969` consegna a pytest gli identificativi senza quel marcatore. Quella campagna non si rilancia.

La campagna `3ae284727c98-1794931254` è il fatto di questa richiesta.

## Prove

Campagna `3ae284727c98-1794931254`. Head `3ae284727c9829902e72bea25c2f07373e60d969`. Selezione `tests/`, ambito `FULL_SUITE`, `qualifying_scope` true, modo `FOUR_LANE`. Avvio dell'alimentazione e della campagna `2026-11-17T16:00:54Z`, fine `2026-11-17T16:09:13Z`, durata 498.974 s, exit 1, stato `FAIL`. Prima dell'avvio il residuo di pull Docker Hub è passato da `51;w=3600` (osservazioni `2026-11-17T15:45:52Z`, `2026-11-17T15:50:53Z`, `2026-11-17T15:55:53Z`) a `100;w=3600` alle `2026-11-17T16:00:54Z`, sopra la soglia 95. `MemAvailable` all'ammissione 58353928 KiB su 64199668 KiB, soglia FOUR_LANE 25681.2 MiB, ammissione `FOUR_LANE`. Alimentazione di rete all'inizio e alla fine: sorgente `MAINS`, `ADP0` online, `BAT0` Full. Raccolti 47779, sha256 della raccolta `be9e0ca21a0e0e9ce0c0944180de94d32c9cad41c56d111c0a76318917bbe2fb`. Casi per corsia: 41953, 972, 2423, 2431. Sha256 della partizione `ad0d34b86ba5bbd5225010ad59f5106ce1af83bbfeeddf86c6a3a8c053ddcff0`. Teardown delle quattro sandbox PASS. Residuo host dopo il teardown: nessun contenitore, nessuna rete, nessun volume, immagine root assente. Il flag `po_decision_required` del risultato è false.

Errore registrato: `lane 1 failed: lane 1 stopped by the orchestrator: lane 2 failed (exit 1)`. Le corsie 1, 3 e 4 sono state fermate perché la corsia 2 è uscita con codice 1. Non è un fallimento di asserzione. Il log di pytest della corsia 2 termina con `338 passed, 8 warnings in 254.26s` e poi `KeyboardInterrupt`: l'orchestratore ha interrotto la corsia. Quei 338 passaggi non sono l'esito della corsia intera e non sono un PASS di campagna.

Causa della corsia 2. `check_kubernetes_runtimes` in `scripts/run_qualifying_campaign.py`, righe 680-687 sul commit `3c11b6125fc22f4d2af81eca73a4c7503237fff1`, solleva `CampaignError` se `restarts` è diverso da zero. L'osservazione che ha fatto scattare il controllo, nodo `d658ba79d6b52b65a74d7c60cc8292a75eba1c44d38a4458568586e863aaaaee`, è: containerd `active`, pid 124, `restarts` 0; kubelet `active`, pid 296, `restarts` 2, `admitted` false. Il messaggio è `Kubernetes service restarted or failed: d658ba79d6b52b65a74d7c60cc8292a75eba1c44d38a4458568586e863aaaaee:kubelet`.

Nel journal dello stesso nodo, containerd non carica il plugin CRI: `failed to create fsnotify watcher: too many open files`. Subito dopo kubelet ripete `error creating fsnotify watcher: too many open files` sul file della CA. Il contatore di restart di kubelet arriva a 2. Il limite di descrittori del processo della campagna osservato in questa sessione è 65536 (`ulimit -n`). Il tetto che manca è un altro: `/proc/sys/fs/inotify/max_user_instances` vale 128 e non è scrivibile dal processo della campagna. Quattro cluster kind condividono quel tetto del kernel della postazione. `scripts/run_qualifying_campaign.py` non contiene un riferimento a inotify: il tetto non è un parametro del programma.

Non sono correzioni ammesse da questa richiesta, e non sono opzioni: ridurre il numero di corsie; indebolire o saltare il controllo delle righe 684-687; trattare `3ae284727c98-1794931254` come PASS; modificare `scripts/run_qualifying_campaign.py`, `partition_units`, soglie, tetti, timer, workflow, diagramma, config Puppeteer, matrice o codice di prodotto; scrivere il sysctl senza che il valore letto diventi almeno 1024.

## Effetto

La campagna di qualifica del ciclo 10 e il controllo distinto dipendono da questa richiesta. Il controllo distinto non è stato eseguito. Il codice del profilo e del generatore già pubblicato non ne dipende e non si modifica. Nessuna seconda revisione preventiva. Nessuna richiesta di verifica. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Opzioni

1. **Tetto inotify della postazione, poi la stessa campagna.** Chi amministra la postazione imposta `fs.inotify.max_user_instances` a 1024. Nessun file del repository cambia per ottenere quel valore. Il processo della campagna non può scriverlo oggi: `/proc/sys/fs/inotify/max_user_instances` non è scrivibile e un `sudo` non interattivo chiede una password. La ripetizione parte solo quando una lettura di quel file è l'intero 1024 o un intero maggiore. Si ripetono, sullo stesso commit `3ae284727c9829902e72bea25c2f07373e60d969` e senza modificare file, il gate pre-campagna dell'unità e la campagna locale a quattro corsie, con gli stessi tetti, gli stessi timer e lo stesso controllo `check_kubernetes_runtimes`. Il controllo distinto si esegue solo se quella campagna nuova termina con stato `PASS`. Le campagne `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` restano FAIL diagnostiche. Non si modifica `scripts/run_local_lane_campaign.py`, `reports/tests/test_local_lane_campaign.py`, `scripts/run_qualifying_campaign.py`, `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py` né `ocor-runtime/src/ocor_runtime/c1/codegen.py`. Non si sposta il branch di produzione. Raccomandata.

2. **Stesso commit su una postazione che ha già il tetto.** Su questa postazione `fs.inotify.max_user_instances` resta 128 e la campagna non si rilancia. Lo stesso commit `3ae284727c9829902e72bea25c2f07373e60d969` si qualifica solo su una postazione in cui quel valore è già un intero almeno 1024, con le stesse quattro corsie, lo stesso gate, lo stesso controllo dei restart e gli stessi file. Le tre campagne già fallite restano FAIL diagnostiche. Nessun file del repository cambia. Non raccomandata: la postazione di qualifica è questa, e il fallimento è il suo tetto di kernel.

## Raccomandazione

L'opzione 1. Alza il tetto di istanze inotify della postazione e ripete gate, campagna e, solo se verde, controllo distinto sullo stesso commit. Non cambia il programma, il numero di corsie né il controllo che ha fermato la corsia 2.

## Impatto

Task bloccato: `OCOR-DEV-REM-0063`. Gli altri task non sono bloccati. Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate o ai claim. L'estensione dell'allowlist del validatore del piano per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione.

## Disposition

Decisa dal PO di persona il 2026-11-17. Opzione 1. L'opzione 2 non è applicata.
La lettura di `/proc/sys/fs/inotify/max_user_instances` il 2026-11-17T20:18:05Z è l'intero 1024. Il file non è scrivibile dal processo della campagna e questa esecuzione non lo ha scritto.
Il gate pre-campagna è stato ripetuto sullo stesso commit `3ae284727c9829902e72bea25c2f07373e60d969`, base `3c11b6125fc22f4d2af81eca73a4c7503237fff1`, senza modificare file del repository. Esito PASS: 51 passi, 0 fallimenti, 6 `NOT_EXECUTED` (mandatory-gates, integration-postgresql, qualifying-campaign-shards, fuseki-actions-cache, conditional-0049-aggregator, auto-merge). `gates.json` sha256 `b6ec2f7215f5de2c830158398707e388d8318c815a3553085dfaeea745667389`. Il gate precedente, sha256 `50ee856e76341d1cc1528a02e20c7ea9e2977e693a303d035815920862c6ed7b`, è conservato a parte e non è il risultato di questa ripetizione.
La campagna nuova `3ae284727c98-1794946686` è PASS. Head `3ae284727c9829902e72bea25c2f07373e60d969`. Selezione `tests/`, ambito `FULL_SUITE`, `qualifying_scope` true, modo `FOUR_LANE`. Avvio `2026-11-17T20:18:06Z`, fine `2026-11-17T21:16:05Z`, durata 3478.948 s, exit 0. Prima dell'avvio il residuo di pull è `100;w=3600`, sopra la soglia 95, attesa 0.85 s. `MemAvailable` all'ammissione 49139036 KiB su 64199668 KiB, soglia FOUR_LANE 25681.2 MiB. Alimentazione `MAINS` all'inizio e alla fine. Raccolti 47779, sha256 della raccolta `be9e0ca21a0e0e9ce0c0944180de94d32c9cad41c56d111c0a76318917bbe2fb`, lo stesso della campagna diagnostica. Casi per corsia: 41953, 972, 2423, 2431, tutte PASS (durate di corsia 3059.416 s, 1034.700 s, 1841.764 s, 1953.575 s). Errori 0, fallimenti 0, skipped 0. Teardown delle quattro sandbox PASS. `po_decision_required` false. `check_kubernetes_runtimes` non ha sollevato errore. Nel log `kubernetes-runtime.log` della corsia 2 ogni campione di `restarts` è 0 (178 campioni). `campaign_result.json` sha256 `20b15c1ba7739396ab1f4fb72c3de1278853574511b7aea91762e177f6cac346`.
Il controllo distinto `3ae284727c98-1794950166` è eseguito solo perché la campagna è uscita con codice 0. Esito PASS, `qualifying_scope` false, ambito `EXPLICIT_NON_QUALIFYING`, 410 test, 0 errori, 0 fallimenti, 0 skipped, durata 360.058 s, dal 2026-11-17T21:16:06Z al 2026-11-17T21:22:06Z. Selezione: `tests/tasks/test_ocor_dev_0048.py`, `tests/tasks/test_ocor_dev_0005.py`, `tests/tasks/test_ocor_dev_0050.py`, `tests/tasks/test_ocor_dev_0082.py`. Quattro corsie PASS, teardown PASS. `campaign_result.json` sha256 `b35cd4299bcb16b0efa3a3a1d4a4356b6eacc7a1c652258c33e7929e23eb4a17`.
Non sono stati modificati `scripts/run_local_lane_campaign.py`, `reports/tests/test_local_lane_campaign.py`, `scripts/run_qualifying_campaign.py`, `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py` né `ocor-runtime/src/ocor_runtime/c1/codegen.py`. Il branch di produzione `governed/ocor-dev-rem-0063-mcp-profile` resta `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.
Le campagne `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` restano FAIL diagnostiche e non sono un PASS. `3ae284727c98-1794931254` non è trattata come PASS.
L'estensione dell'allowlist del validatore del piano non fa parte di questa pubblicazione. Il testo della richiesta sopra questa sezione resta quello del commit `3b1ecc02b8e732ee8d2bdc5c9a5c8b64385aa56c`, sha256 `2445e7351dedbeac8a8f62579ca0a8aeecf2e030b0d1c88373a14d58b1233233`.
