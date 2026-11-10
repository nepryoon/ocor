# REM-0060-LANE-IMAGE-PROVISIONING

Status: `DECIDED_BY_PO`. Livello: operativo.
Unità bloccata: `OCOR-DEV-REM-0060` (NCP-U12), iterazione 9 di stima 3,
estensione fino alla tredicesima. Implementatori: Claude Code (Anthropic) e
Codex (OpenAI); revisore preventivo Codex (OpenAI); verifier finale ammesso di
fornitore xAI o Google. Nessuna verifica indipendente richiesta.

## Contesto e prove

La campagna completa locale a quattro corsie ha esaurito due volte il budget
immutato di provisioning di 600 s, sullo stesso HEAD di codice e test
`4be4bdd14773de0522e65b960c2bb64043f52ece`. Le immagini sono quelle fissate da
`infra/services.lock.json`. Non sono stati osservati fallimenti di asserzioni:
i conteggi parziali sono esclusivamente diagnostici e non qualificano nulla.

| Run | Avvio UTC | Durata campagna | Firma dell'arresto |
|---|---|---|---|
| full-1 | 2026-11-10 17:33:40 | 647,846 s | Corsia 4: build Fuseki, exit 124, 57 s residui dopo l'acquisizione delle immagini |
| full-2 | 2026-11-10 18:43:19 | 645,202 s | Corsia 1: `total provisioning budget exhausted` dopo acquisizione delle immagini |

Il processo del pull Kafka è stato osservato ancora attivo dopo 478 s nel
secondo run, seguito dall'acquisizione di SeaweedFS. Non si attribuisce il tempo
restante a una singola causa di rete non misurata. La quota ufficiale Docker Hub
prima del secondo run era 100/100: la sola attesa del ripristino della quota non
ha eliminato la ricorrenza. Le altre tre corsie sono state fermate
dall'orchestratore; tutti e quattro i teardown sono PASS e il controllo finale
riporta zero container, reti, volumi e immagine sandbox residui. Alimentazione
MAINS all'inizio e alla fine di entrambi i run.

Provenienza riproducibile, pubblicata sul branch
`governed/ocor-dev-rem-0060-ncp-u12-tests`, commit
`b869cc9c0e92b6d23b386cf5162c07d3ebc12aec`:

- `reports/assurance/OCOR-DEV-REM-0060-RCCAD/OCOR-DEV-REM-0060.json`,
  sezione `qualification_infrastructure`;
- `reports/assurance/OCOR-DEV-REM-0060-RCCAD/OCOR-DEV-REM-0060.log`,
  SHA256 `f257405580e90b46cc2e983b02aab5a968b6993764e7e9ac213d8c1dd044930c`:
  JSONL con entrambi i tentativi, log originali con credenziali generate redatte,
  digest originali e dei contenuti archiviati;
- diagnosis full-1 SHA256
  `d774bd8dd5f4ce352fc3bd1443050bd2a1e436c8786cb296aa6510205f3ae929`;
- diagnosis full-2 SHA256
  `733f292b2c56bbf0284d3add72fcf40182e2bfc455b5e45465509917985a8c85`.

Le righe decisive sono riproducibili estraendo con `git show` il log al commit
citato e selezionando i record JSONL `attempt=2`,
`path=lanes/lane-1/out/bootstrap.log` e `path=lanes/campaign_result.json`.
La durata del wrapper del secondo run è 645,281 s; quella dell'orchestratore,
usata in tabella, è 645,202 s. Non sono durate alternative della suite completa.

## Perimetro e vincoli vigenti

- `scripts/run_local_lane_campaign.py:480-500` prepara ogni clone; `:1215-1230`
  crea i quattro demoni privati e avvia i runner; `:857-858` fissa il bootstrap
  CI a 600 s; `:917-925` lo esegue in ogni corsia.
- `scripts/bootstrap_ci_environment.py:312-351` applica il budget totale,
  esegue i pull pinned e la build Fuseki. Questo file non cambia nelle opzioni.
- `LOCAL-SUITE-FOUR-LANES (2026-11-07)`, punti 1, 3 e 6: quattro corsie se
  ammesse dalla memoria, stack isolati, nessuna variazione dei timeout;
  `QUALIFICATION-CAMPAIGN-INFRA-RERUN (2026-10-12)`: la ricorrenza della stessa
  causa su più run richiede una decisione, non un ulteriore tentativo.
- NCP-U12 è un'unità di test: cambiare l'acquisizione delle immagini
  nell'orchestratore non appartiene al suo perimetro approvato. Non si adotta
  un'esecuzione seriale forzata né un limite più alto per aggirare il problema.
- I 55 controlli rapidi, 630 test mirati con 1007 subtest e 214 regressioni
  erano PASS sul medesimo albero; la suite completa resta NOT_COMPLETED.

L'inventario in sola lettura individua fra gli input sigillati interessati
`scripts/run_local_lane_campaign.py` e `reports/tests/test_local_lane_campaign.py`:
`reports/assurance/OCOR-DEV-REM-0037-RCCAD/OCOR-DEV-REM-0037.json`,
`reports/evidence/G2/OCOR-DEV-REM-0037.requalified-rem0056.json` e
`reports/assurance/OCOR-DEV-REM-0056-RCCAD/OCOR-DEV-REM-0056.json`.
I pesi `reports/assurance/OCOR-DEV-REM-0037-RCCAD/lane_weights.json` non cambiano.

## Opzioni

1. **Remediation separata per cache locale verificata delle immagini (raccomandata).**
   Autorizzare una remediation governata, con primo identificativo libero
   verificato, prima di riprendere la campagna di NCP-U12. Aree chiuse:
   `scripts/run_local_lane_campaign.py`, un eventuale nuovo aiuto
   `scripts/local_lane_image_cache.py`, `reports/tests/test_local_lane_campaign.py`,
   eventuali nuovi test della cache in `reports/tests/`, record e raw log della
   remediation e delle riqualifiche, soli percorsi necessari nell'allowlist di
   `scripts/validate_ocor_development_plan.py` e relativi hash del piano,
   file di stato. Nessun altro file di esecuzione cambia.
   Usare solo immagini già presenti nel demone host e verificate contro i digest
   di `infra/services.lock.json`, inclusa la base ufficiale della build Fuseki;
   nessun nuovo pull preparatorio fuori dal budget di bootstrap. Trasferire solo
   immagini, mai stato di servizi, container, volumi, CA o credenziali: archivio
   locale `docker image save`, manifest con riferimenti pinned, image ID e SHA256
   dell'archivio, copia privata o montaggio in sola lettura e `docker image load`
   in ciascun demone isolato. Verificare SHA256 e image ID prima dell'uso.
   Il bootstrap versionato e i suoi `docker pull <image@digest>` e
   `docker build --pull` restano invariati e riconfermano i manifest ufficiali:
   un tag o il solo ID locale non sostituiscono mai il digest del lock.
   Cache mancante: percorso freddo esistente; archivio o identità incoerenti:
   errore fail-closed, nessuna accettazione silenziosa. La preparazione e il
   trasferimento contano nel tempo complessivo di 5400 s e nei limiti esistenti
   dell'orchestratore; il bootstrap conserva i suoi 600 s. Nessun timer si
   sposta o riparte per effetto della cache. Nessuna variazione a servizi,
   immagini, lock, CI, supervisore, casi, partizione, unione JUnit, memoria,
   guardia, probe o teardown. RED/GREEN deterministici per cache valida,
   mancante, archivio alterato, image ID/digest errato e errore di load;
   prova su Docker reale che i pull pinned invariati consumano le immagini
   trasferite e che un digest diverso resta rifiutato. Qualifica a quattro
   corsie reali e controllo dei residui pulito. Riqualifiche di sola regressione
   di REM-0037, REM-0056 e di 0005, 0050, 0082; inventario aggiornato prima del
   codice e nuova richiesta se servono altri cambi. Ciclo completo con controlli
   rapidi, revisione preventiva, campagna, verifier indipendente, sigillo e merge.
   Poi allineamento non distruttivo di NCP-U12 a main, nuovi controlli e nuova
   campagna qualificante sul nuovo HEAD; entrambi i run qui citati restano
   diagnostici. Non si trasferiscono conteggi. Nessun ciclo di riparazione
   aggiuntivo di NCP-U12 è autorizzato da questa opzione.
2. **Sospendere fino a una disponibilità esterna dimostrata.**
   Nessuna modifica dell'orchestratore. Conservare NCP-U12 e i due tentativi;
   autorizzare una nuova sola ripetizione soltanto dopo una misura riproducibile
   che dimostri un cambiamento rilevante della disponibilità dei registry o
   del trasferimento delle immagini, sufficiente a rispettare i 600 s invariati.
   Fino a tale misura nessun nuovo tentativo, nessuna qualifica e nessuna
   integrazione di NCP-U12. Non risolve strutturalmente i download duplicati.

## Raccomandazione

Opzione 1. Riduce il trasferimento duplicato dei medesimi layer verificati
mantenendo manifest ufficiali, isolamento e tutti i controlli esistenti.
La decisione autorizza un change set separato, non una modifica implicita al
candidato di NCP-U12. Se il meccanismo richiede altro oltre al perimetro
indicato, si applica la regola vigente per le decision request.

## Impatto

Blocca `OCOR-DEV-REM-0060`; i task successivi mantengono le loro dipendenze
già vigenti. Nessun runtime modificato, nessuna verifica simulata e nessun
sigillo prodotto. E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED,
PoC e Production NO-GO invariati. Nessun nuovo DEC.

## Disposition del Product Owner — 2026-11-10

`REM-0060-LANE-IMAGE-PROVISIONING (2026-11-10)` adotta l'opzione 1. Decisa su delega completa del PO, modello grok-4.7, effort xhigh. Vale come decisione del PO a ogni effetto. Il testo delle opzioni non è stato modificato. La richiesta decisa è il file al commit `05531507319e217032bafd475538e65b7cb12def`, sha256 `fae0821796e40064f4913dda4e5dd6f379e4c1bb610d3f3083308ae288653734`, prima di questa disposition. Stato: `DECIDED_BY_PO`.

L'opzione 1 autorizza la remediation governata `OCOR-DEV-REM-0061` prima di riprendere la campagna di `OCOR-DEV-REM-0060`. I due run citati restano diagnostici e i loro conteggi non si trasferiscono. Nessun nuovo `DEC-*`. Claim invariati: E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC e Production NO-GO.
