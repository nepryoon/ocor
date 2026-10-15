# REM-0017-KIND-CONTAINERD-CRASH

Status: OPEN_PO_DECISION_REQUIRED — limitata a un eventuale cambio del profilo
qualificante/immagine o a modifiche di 0049; diagnosi entro DEC-211 resta autonoma.

## Evidenza riproducibile e confine del blocco

Nel candidato immutabile `df444af855e884d7783612b302e008b90105fe13`, sul nodo
`kindest/node:v1.33.1@sha256:050072256b9a903bd914c0b2866828150cb229cea0efe5892e2b644d5dd3b34f`,
containerd è terminato due volte con `code=dumped, status=11/SEGV`:

- 2026-10-08T13:15:00Z: prima FULL locale,1490 PASS/1 FAIL/zero skip,
  errore del job backup manuale Helm (seal255), containerd riavviato alle13:15:01Z.
- 2026-10-08T14:59:57Z: nuova FULL dopo reset/bootstrap/health,1379 PASS
  parziali e112 casi NOT_EXECUTED. Journal: RunPodSandbox del backup manuale,
  EOF CRI e SIGSEGV; riavvio systemd alle14:59:58Z. Il nuovo supervisore ha
  sospeso immediatamente il gruppo pytest posseduto, acquisito statistiche/journal
  e interrotto la campagna. Non è un PASS. Teardown senza risorse OCOR residue.

Un ulteriore run intermedio è stato interrotto a1379 PASS per un errore del
supervisore sulla normale inizializzazione kubelet (PID241->749,NRestarts0,
stop pulito prima del collegamento alla retebootstrap). Quel difetto è corretto
con casi positivi/negativi; il monitor mantiene il rigetto dei crash anche durante
l'avvio e dei cambi PID/ActiveState dopo l'ammissione. Non viene confuso col SIGSEGV.

La FULL del branch REM sul codice finale ha1101 PASS/zero skip/error/fail,
424.337s. Il primo HEAD CI sorgente `fe82366151c424c7f5b51e994ef7c585d6920763`
ha13/13 check verdi: il candidato ha1491 PASS/zero skip in4200.959s,196 casi0048
più390 casi0049, teardownzero. È evidenza sorgente storica, non dell'HEAD successivo.
La causa profonda del SIGSEGV non è stabilita: non è provata una responsabilità
del prodotto, della concorrenza dei backup, né una specifica correzione upstream.
Journal, JUnit, transizioni runtime e raw log con hash sono nel record WIP
`reports/assurance/OCOR-DEV-REM-0017-RCCAD/repair-1-archive.json` e relativo `.log`.
Il journal conservato documenta il segnale; non è un backtrace completo del core.

## Opzioni e raccomandazione

1. Diagnosi bounded nel solo ambiente disposable: riproduttore del sandbox/backup
   e acquisizione del backtrace prima del teardown; tentare soltanto configurazioni
   dentro DEC-211 con le stesse versioni e gli stessi byte approvati. Questa parte
   non richiede nuova autorizzazione, ma nessun run fallito è qualificante.
2. Se serve un'immagine/versione diversa del nodo/runtime, autorizzare esplicitamente
   un change set governato separato e la sua riqualifica, senza sostituire tecnologie
   né indebolire i criteri. Nessun nuovo valore del lock o override è eseguito ora.
3. Se la correzione richiede modificare 0049, occorre una nuova decisione:
   il ciclo8 è concluso e il mandato corrente vieta un ciclo9.

Raccomandazione: prima diagnosi1, poi eventuale decisione2 fondata su backtrace e
confronto di ambienti. Nessuna ripetizione della FULL nelle stesse condizioni.
Non aumentare75/45 minuti, escludere casi o trattare restart/OOM come tollerati.

## Impatto e lavoro pronto

REM-0017 resta OPEN/WIP e non si richiede il sigillo con qualifica locale incompleta.
PR169draft e PR176 restano aperte; il GO indipendente già acquisito per0049 non
viene riscritto. G6/G7 e integrazione0049 restano soggetti alle dipendenze esistenti.
G5 è pronto:0050 e successivi raggiungibili possono proseguire. La riacquisizione
locale Fuseki già autorizzata resta un'unità governata distinta dopo il Dockerfile.
E1=0,E2=0,zero Verified; nessuna modifica inputs/ o promozione di claim.

## Terza occorrenza e diagnosi bounded — 2026-10-09

Contesto mutato rispetto alle occorrenze precedenti: HEAD REM riallineato a
`origin/main` `7b63f61` (merge `730759b`, riqualifiche 0050/0075), stack
ricreato da zero, nuovo cluster kind, stesse versioni e stessi byte approvati
(`kindest/node:v1.33.1@sha256:0500722…`, helm/kind/kubectl del lock). Candidato
immutabile `df444af855e884d7783612b302e008b90105fe13`: **1379 PASS, zero
fail/skip prima dell'interruzione, 2531 s**; il supervisore ha rilevato il
riavvio di containerd (`restarts: 1`, PID 111→8957) alle **05:30:01Z** nel test
`test_helm_profile_on_kubernetes_backs_up_restores_and_gates_readiness`,
ha raccolto diagnostica e interrotto la campagna: **FAIL, non qualificante**.
`campaign_result.json` SHA256 `79e79ab0eefd02099b2c229171ff6ef3eb55c51f1fe30eb286374e0337d4ab38`,
diagnostica SHA256 `d771bd43c09fc55d7a7c5b2ed38e64c1ca7a78eb7f8e18d37e61c79c645cdaeb`;
raw nel record `reports/assurance/OCOR-DEV-REM-0017-RCCAD/repair-1-realign.json`.
Teardown senza cluster kind né container/volumi `ocor-bootstrap` residui.

Correlazione osservata (non causa provata): tutte e tre le terminazioni cadono
sul confine del tick `*/15` del CronJob di backup, con il `RunPodSandbox` del pod
schedulato in corso mentre il job di backup manuale del test è attivo:
13:15:00Z (`ocor-poc-backup-29857755`), 14:59:57Z (pod del backup manuale a 3 s
dal tick delle 15:00) e 05:30:00Z (`ocor-poc-backup-29858730`). Il journal del
kernel dell'host non registra segfault (il segnale è interno al nodo kind); il
backtrace completo del core resta NOT_EXECUTED. Lo stesso candidato passa in CI
sui runner GitHub (`fe82366`: 1491 PASS/4200.959 s; `bc811af`: 1491 PASS/4425.920 s,
zero skip), quindi il difetto è riprodotto solo su questo host
(kernel 7.0.0-38-generic, Docker locale).

La riproduzione 3/3 nello stesso punto rende inutile un'ulteriore FULL locale
nelle stesse condizioni. Resta riservato al Product Owner (opzione 2) un cambio
di immagine/runtime del nodo kind o di profilo qualificante; nessuna modifica
di 0049, del monitor o dei criteri è stata fatta per evitare il crash.
La qualifica di REM-0017 è richiesta sulla CI dell'HEAD esatto (oggetto del REM)
con questo limite locale dichiarato come NOT_EXECUTED/FAIL, non come PASS.
Registrato da Claude Code (implementatore di riserva del loop).

## Decisione del Product Owner — 2026-10-09

La decisione `REM-0017-CI-CAMPAIGN-DURATION` stabilisce che la diagnosi di
questo crash prosegue secondo l'opzione 1 (diagnosi bounded nel solo ambiente
disposable, senza cambi di immagine o versione). L'opzione 2 resta riservata al
Product Owner. Con la suite in parti, in CI il caso Helm gira in una parte
propria, su un runner e uno stack propri; questo non cambia il caso, i criteri
o il monitor di containerd. Nessuna diagnosi aggiuntiva eseguita in questa
iterazione: backtrace del core ancora NOT_EXECUTED.
