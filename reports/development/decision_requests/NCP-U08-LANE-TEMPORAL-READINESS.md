# NCP-U08-LANE-TEMPORAL-READINESS

Status: `OPEN_PO_DECISION_REQUIRED`. Livello: operativo. Riguarda la suite completa dell'unità
`OCOR-DEV-REM-0054` (NCP-U08 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, sicurezza e policy di C6; branch
`governed/ocor-dev-rem-0054-ncp-u08-c6-safety-policy`, commit di codice `f22de614311f3e8cd3453152e64adca963e07dfa`).
Aperta secondo `QUALIFICATION-CAMPAIGN-INFRA-RERUN (2026-10-12)` («se la stessa causa colpisce più run, fermati e
apri una decision request»): la stessa causa infrastrutturale ha fermato due volte il run a due corsie della
campagna. Implementatore: Claude Code (Anthropic), implementatore di riserva, unico implementatore dell'unità.

## Contesto

- Campagna dell'unità al commit di codice `f22de614311f`, da shell pulita, il 2026-11-06. Sono già `PASS` allo
  stesso commit: bootstrap CI dello stack dell'host (15 container, 11 servizi tipizzati `READY` tre volte, anche
  dopo le fault injection e dopo il reset), qualifiche dei servizi, suite di contratto dei servizi (78 casi),
  modulo d'unità tre volte (1298 casi per esecuzione), moduli adattati di `0030`, `0034`, `0035`, `0044`,
  `0047`, `0048` (267 casi), 33 moduli consumatori (2441 casi), regressione di `0005`, `0009`, `0014`, `0050`,
  `0082` (300 casi), comando del job di evidenza di `0004`, portfolio di `reports/tests` (1626 casi); zero skip.
- Il run a due corsie (`scripts/run_local_lane_campaign.py --execute`, ammissione di memoria `TWO_LANE`) è
  fallito due volte, alle 11:13 UTC (tentativo 1) e alle 11:40 UTC (ripetizione 1, stesso harness), **prima di
  qualsiasi test**: in entrambe le corsie `scripts/bootstrap_ci_environment.py --execute` (riga 395, passo
  `typed service health`) esce con codice 1 dopo che ogni passo precedente è riuscito. Nessuna asserzione è
  fallita, nessun caso è stato raccolto; smontaggio delle corsie `PASS` e residuo sull'host vuoto in entrambi i
  tentativi.
- Causa, provata da quattro riproduzioni diagnostiche non qualificanti con le stesse funzioni dell'harness (una
  sandbox di corsia, stesso commit, stessi strumenti): l'unico servizio non `READY` è Temporal, `DEGRADED` con
  «Temporal cluster health is not SERVING» oppure «describing an absent Temporal namespace did not fail closed»;
  ogni altro servizio è `READY`. Nella sandbox il container del server Temporal parte e registra l'avvio dei
  servizi entro un secondo, poi non risponde al CLI per circa 45-55 s (nella riproduzione 4: avvio 11:46:04 UTC,
  nessun log per 48 s, sonda fallita alle 11:46:36, riuscita alle 11:47:01, circa 57 s dopo l'avvio; nella
  riproduzione 3: riuscita circa 59 s dopo l'avvio). Il controllo tipizzato del bootstrap interroga Temporal una
  sola volta, circa 30-35 s dopo l'avvio.
- Righe interessate:
  - `deploy/bootstrap/compose.yaml` righe 235-240: l'healthcheck del servizio `temporal` verifica solo l'apertura
    della porta TCP 7233, quindi Compose dichiara il servizio sano prima che il frontend risponda.
  - `deploy/bootstrap/services/temporal/qualify.py` righe 167-187 (`probe`, una sola interrogazione con
    `--command-timeout 5s`) e righe 190-201 (`wait_ready`, attesa limitata a 90 s, usata solo dopo le fault
    injection); `scripts/verify_external_services.py` righe 367-371 (`check_temporal` esegue `qualify.py` senza
    attesa).
  - `scripts/run_local_lane_campaign.py` righe 530-531 e 586-597: il bootstrap di ogni corsia è quello versionato,
    senza ritentativi.
- Sull'host, con le immagini già presenti, lo stesso bootstrap è riuscito alla prima esecuzione della campagna.
  Le campagne a due corsie di `OCOR-DEV-REM-0050` … `OCOR-DEV-REM-0053` (dal 2026-11-03 al 2026-11-05) sono
  riuscite con lo stesso harness; la causa del rallentamento di Temporal nella sandbox non è identificata oltre i
  tempi misurati. I tentativi falliti e le riproduzioni sono conservati fuori dal repository con la loro diagnosi
  e gli hash dei raw; entreranno nel raw log del record dell'unità come tentativi diagnostici, senza conteggi.
- Vincoli vigenti: `QUALIFICATION-CAMPAIGN-INFRA-RERUN` consente al massimo due ripetizioni dello stesso run;
  `LOCAL-SUITE-SPLIT (2026-10-25)` punto 5 e `LOCAL-SUITE-SPLIT-REACTIVATION (2026-10-26)` punto 7 prevedono la
  suite seriale solo quando la memoria all'avvio non basta per due corsie; `LOCAL-FULL-SUITE-CAP-90 (2026-10-26)`
  fissa il tetto di 5400 s e la notifica oltre 3600 s. La suite seriale più recente (`OCOR-DEV-REM-0049`, 3546
  casi) è durata 4233 s; la somma delle due corsie di `OCOR-DEV-REM-0053` (4743 casi) è 4507 s.

### Opzioni del quesito A

Quesito A: come ottenere la suite completa qualificante di `OCOR-DEV-REM-0054`.

A1. **Suite completa seriale sullo stack dell'host (raccomandata).** Per questa unità la suite completa gira in
modalità seriale con `scripts/run_qualifying_campaign.py --execute` sullo stack `ocor-bootstrap` dell'host,
provisionato da `scripts/bootstrap_ci_environment.py --execute` da credenziali nuove, allo stesso commit di
codice e con le stesse etichette già verdi della campagna, che restano valide. I due tentativi a due corsie sono
registrati nel record come tentativi diagnostici, senza conteggi. Nessuno script, test, limite o soglia cambia.
Effetto: circa 75-80 minuti stimati, vicino alla soglia di 5100 s oltre la quale serve una decision request
(`LOCAL-FULL-SUITE-CAP-90`); se la suite supera il tetto, il run non qualifica e si apre una nuova decision
request.

A2. **Seconda e ultima ripetizione del run a due corsie, invariata.** Si usa la seconda ripetizione ammessa da
`QUALIFICATION-CAMPAIGN-INFRA-RERUN`, con lo stesso harness. Effetto: circa 45 minuti se riesce; con la causa
riprodotta otto volte su otto nella sandbox (quattro bootstrap di corsia e quattro riproduzioni), è probabile un nuovo arresto, che richiederebbe una nuova decision
request.

A3. **Attesa della remediation del quesito B.** L'unità resta ferma fino all'integrazione della remediation del
quesito B (se scelta), poi ripete l'intera campagna al commit di codice dell'unità ribasato, con le riqualifiche
che la remediation impone. Effetto: nessuna deroga alla modalità a due corsie; ritardo di più iterazioni
sull'unità e su NCP-U09 … NCP-U12.

### Opzioni del quesito B

Quesito B: come trattare la corsa fra l'healthcheck di Temporal e il controllo tipizzato.

B1. **Remediation governata dopo l'integrazione di NCP-U08 (raccomandata).** Il primo `OCOR-DEV-REM-*` libero,
dopo l'integrazione di `OCOR-DEV-REM-0054` e prima di NCP-U09, rende il controllo tipizzato di Temporal
tollerante all'avvio con un'attesa limitata (riuso di `wait_ready` di
`deploy/bootstrap/services/temporal/qualify.py` righe 190-201, 90 s, nel percorso di
`scripts/verify_external_services.py` righe 367-371), senza cambiare l'esito richiesto (`SERVING`, versione del
lock, namespace assente rifiutato) né altri servizi, timeout dei test o criteri; RED che riproduce la sonda
anticipata, GREEN, riqualifiche dei record sigillati che hanno fra gli input i file toccati, verifica
indipendente. Effetto: il bootstrap delle corsie torna affidabile; una o due iterazioni in più.

B2. **Nessuna remediation ora.** La causa resta registrata come limite noto dell'ambiente delle corsie; ogni nuova
occorrenza segue `QUALIFICATION-CAMPAIGN-INFRA-RERUN`. Effetto: nessun lavoro aggiuntivo ora; le prossime unità
possono fermarsi di nuovo per la stessa causa.

## Raccomandazione

A1 e B1: la suite seriale sullo stack dell'host usa il bootstrap versionato che oggi riesce, senza alcuna
modifica a harness, test o limiti, e lascia l'unità avanzare; la remediation B1 elimina la corsa con un'attesa
limitata che non cambia l'esito richiesto dal controllo, così le unità successive tornano alle due corsie.

## Impatto

- Task e unità bloccati: solo `OCOR-DEV-REM-0054` (NCP-U08), nella fase della suite completa; dopo di essa, per
  l'ordine del piano, NCP-U09 … NCP-U12.
- Iterazioni: iterazione 7 di stima 3 (stop a 9, `NCP-THROUGHPUT-RULES (2026-11-05)` punto 2).
- Nessuna modifica a `inputs/`, ADD, LLD, contratti, schemi, registri normativi, test, validatori, workflow o
  limiti; nessun nuovo `DEC-*`. `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production
  `NO-GO` invariati.
