# REM-0017-CI-CAMPAIGN-DURATION

Status: RESOLVED_BY_PO_DECISION (2026-10-09, decisione `REM-0017-CI-CAMPAIGN-DURATION`).
Stato precedente: OPEN_PO_DECISION_REQUIRED (non bloccante per run entro il tetto vigente).

## Contesto e misura

La decisione `REM-0017-CI-CAMPAIGN-BUDGET` del 2026-10-07 impone una nuova
richiesta quando una FULL supera 60 minuti; il tetto resta 75 minuti.
Il 2026-10-08T13:41:40Z, il run GitHub Actions `37778117899`, job
`conditional-infrastructure-0049`, sullo SHA sorgente
`fe82366151c424c7f5b51e994ef7c585d6920763`, mostra lo step FULL del candidato
immutabile `df444af855e884d7783612b302e008b90105fe13` ancora in corso:
inizio step 12:39:26Z, durata osservata 3734 s (62m14s).
È una misura dello step tuttora attivo, non un risultato finale o un PASS
pytest. La durata della campagna e i conteggi finali saranno acquisiti dal raw
artifact appena disponibili. Osservazione API conservata nel raw del candidato
REM; nessun incremento di E1/E2/Verified o claim.

La campagna locale iniziale del medesimo candidato è durata 2463.71 s, con
1490 PASS, 1 FAIL e zero skip. È fallita nel job Helm durante un SIGSEGV e
riavvio di containerd nel nodo kind, documentato a 13:15:00Z; non qualifica
il REM. Dopo diagnosi e teardown è stato avviato un solo retry con stack
ricreato e supervisore che osserva anche containerd/kubelet dentro i nodi
OCOR. Questo controllo non cambia il codice né l'evidenza sigillata di 0049.

## Opzioni e raccomandazione

1. Conservare 75 minuti e ottimizzare soltanto provisioning/esecuzione entro
   DEC-211, senza cambiare versioni, tecnologie, casi o criteri. Raccomandata:
   acquisire prima durata finale, risorse e teardown della campagna osservata.
2. Autorizzare una futura variazione del budget soltanto con una decisione
   esplicita, dopo misure riproducibili. Nessuna variazione è eseguita ora.

## Impatto

Nessun test viene escluso, saltato, deselezionato o marcato. La soglia resta
4500 s; su restart/OOM il supervisore interrompe e raccoglie diagnostica.
Un run oltre il tetto o non verde non qualifica REM-0017. La richiesta non
blocca G5; l'integrazione del REM e di 0049 richiede comunque campagne valide,
verifica indipendente e CI verde sull'HEAD esatto. Nessun ciclo9 di 0049.

## Esito acquisito del primo run sorgente

Il raw artifact `ocor-conditional-0049-b31ebdab58d077274e9534bbf3cd5d4aad5b51ed`
(artifact ID11553834543, run37778117899, PR head fe823) riporta durata FULL
**4200.959 s (70m01s)**, `po_decision_required=true`,1491 PASS e zero
FAIL/ERROR/skip. JUnit:0048=196 casi,0049=390 casi; teardown senza
container,volumi o reti residui. Hash SHA256 campaign_result.json: `b37995903b1e24dbcd3b47696b4da98658a4aef2dd41025433bb8e93333c0db3`.
La richiesta resta OPEN: il run è entro75 minuti ma oltre60. Il verde
di questa sorgente non qualifica le successive modifiche del ricevitore
e del monitor Kubernetes; è necessaria la CI dell'HEAD finale.

## Misura aggiuntiva 2026-10-09 — HEAD `bc811afc2bc30023cd64051a638c632263760ecc`

Run `37799916094` (OCOR governance and validation closure, PR169), job
`conditional-infrastructure-0049`: step FULL del candidato immutabile
`df444af855e884d7783612b302e008b90105fe13` 15:23:00Z–16:36:47Z; artifact
`ocor-conditional-0049-aac82eacc7dd8c52b81f65713ab4bbef705979a8` (ID
11563824886), `campaign_result.json` SHA256
`5e8b1cba4780efaf21c9b28ecd72e4f7eb6a8644d7fdfe8f01f3ccf363e76fdb`:
`status=PASS`, 1491 test, zero failure/error/skip, durata **4425.920 s
(73m46s)**, `po_decision_required=true`. Margine sul tetto vigente di 4500 s:
74 s. Le due misure CI disponibili (4200.959 s e 4425.920 s) crescono e
restano entro il tetto ma oltre i 60 minuti: la richiesta resta OPEN.
Nessun tetto modificato, nessun caso escluso o saltato. Un run CI che superi
4500 s è FAIL e non qualifica REM-0017; in quel caso si registra la misura
e si prosegue con il lavoro G5 pronto, senza aumentare il budget.
Registrato da Claude Code (implementatore di riserva del loop).

## Decisione del Product Owner e attuazione — 2026-10-09

Decisione `REM-0017-CI-CAMPAIGN-DURATION` (2026-10-09): ogni job CI che esegue
la suite completa la esegue in N >= 2 parti parallele, con partizione
deterministica e riproducibile, ciascuna su un runner proprio con lo stack
completo fissato e la stessa ricetta (cache dell'archivio inclusa), zero skip,
teardown fail-closed e arresto immediato su riavvio/OOM; un aggregatore con il
nome del check obbligatorio verifica che l'unione dei JUnit coincida
esattamente con `pytest --collect-only` sullo stesso HEAD. Tetti: 45 minuti per
parte in CI (oltre 30 minuti si aumenta N e si ribilancia), 75 minuti per la
suite completa locale. Ruleset 23412233 invariato.

Attuazione sul branch `governed/ocor-dev-rem-0017-ci-provision-spire`:

- `scripts/run_qualifying_campaign.py`: modalità `--shard-index/--shard-count`
  (selezione esplicita di node ID, mai deselezione; prova che pytest raccoglie
  esattamente la selezione prima di eseguire; tetto 2700 s, segnale di
  ribilanciamento oltre 1800 s; dati di coverage conservati) e modalità
  `--aggregate` (parti 1..N tutte presenti e PASS, stessa collezione e stessa
  partizione ricalcolata, nessun caso mancante/duplicato/inatteso, zero
  skip/failure/error per caso, guardie 0048/0049 presenti, JUnit unito e
  coverage combinata per il report di closure invariato).
- Partizione: assegnazione LPT per singolo node ID con pesi misurati (media per
  funzione di test >= 3 s nella PASS CI del candidato su `f55b210`; il caso Helm
  porta il caso peggiore 1200 s per l'attesa del tick `*/15`), spareggio per
  node ID e indice, ordine di collezione preservato in ogni parte. I pesi non
  selezionano né escludono test.
- Workflow: `rccad-methodology`, `delivery-activation`, `validation-closure` in
  3 parti; `conditional-infrastructure-0049` in 4 parti (con 3 parti le due
  parti grandi arrivano a ~1190 s di test, vicino alla soglia dei 30 minuti con
  la variabilità di ~40% dei runner già osservata). Gli aggregatori rifiutano
  parti mancanti, fallite o cancellate (`if: always()` più controllo esplicito
  di `needs.*.result`, così un'aggregazione saltata non diventa verde).
- Test: 26 nuovi casi positivi e negativi in
  `reports/tests/test_qualifying_campaign_guard.py` (RED dimostrato, poi GREEN).

Nessun test escluso, saltato o deselezionato; nessun gate, tetto o criterio
indebolito. La coppia di run CI autorizzata si esegue sull'HEAD finale del REM.
Registrato da Claude Code (implementatore di riserva del loop); verifier
previsto Grok 4.7 via Cursor CLI.

## Addendum — vincolo d'ordine del modulo 0049 (presa d'atto richiesta, non bloccante)

Status dell'addendum: OPEN_PO_DECISION_REQUIRED — blocca la qualifica di REM-0017
(vedi la misura CI del 2026-10-09 in fondo); non blocca G5.

Il primo run CI dell'HEAD `4e97cd3` (run `37952580435`) ha diviso
`test_ocor_dev_0049.py` per singolo test: la parte con il solo caso Helm è PASS
(995 s), le altre tre sono FAIL (`IndexError` su `restore-receipts/*.json`,
precondizioni di readiness). I test del candidato immutabile `df444af`
consumano stato prodotto da test precedenti dello stesso modulo. Gli
aggregatori hanno rifiutato le parti fallite (fail-closed confermato); il run
non è qualificante.

Correzione (`12836ed`): unità di partizione = modulo intero in ordine di
collezione; unica eccezione dichiarata il caso Helm (cluster kind proprio,
PASS da solo). Il job 0049 usa 3 parti: resto del modulo 0049, caso Helm,
tutti gli altri moduli. In locale, sulla ricetta CI: resto di 0049 389 PASS in
1780 s; altri moduli 1101 PASS in 453 s; la parte Helm non è eseguibile su
questo host (`REM-0017-KIND-CONTAINERD-CRASH`).

Conseguenza: il resto del modulo 0049 è una parte indivisibile. Dai JUnit CI
precedenti vale 2013–2797 s di test sui runner, quindi può superare la soglia
dei 30 minuti senza che aumentare N la accorci, e avvicinarsi al tetto dei 45.
Opzioni:

1. Prendere atto che per questo modulo la regola "oltre 30 minuti aumenta N"
   non è applicabile; tetto 45 minuti invariato; un run oltre 45 minuti resta
   FAIL. Raccomandata: nessuna modifica a test, tetti o criteri.
2. Autorizzare una correzione dell'isolamento dei test di 0049 (nuovo ciclo
   su 0049 con riqualifica), che renderebbe il modulo divisibile.
3. Autorizzare un tetto specifico per questa parte.

Nessuna di queste opzioni è eseguita. Registrato da Claude Code
(implementatore di riserva del loop).

### Misura CI sull'HEAD corretto `99f9ee5` — 2026-10-09

Run `37961535016` (closure), `37961535129` (RCCAD), `37961535168` (delivery),
tentativo 1. `rccad-methodology`, `delivery-activation` e tutte le parti di
`validation-closure` PASS. Job 0049 in 3 parti:

- parte 2 (caso Helm da solo) PASS, 1 caso, 1106 s;
- parte 3 (tutti gli altri moduli) PASS, 1101 casi, 445 s;
- parte 1 (resto del modulo 0049, 389 casi in ordine) **FAIL al tetto**:
  388 PASS, zero fail/error/skip, fermata dal supervisore a 2716 s con
  "45-minute campaign limit reached"; un caso non eseguito.
  `campaign_result.json` SHA256 `d469b6a502a0557d3c1ab74b9674504cdb44e8cd37cfb029fb3ab5c14709075d`,
  log SHA256 `72a3622347f6ecb53a6da3ea5153ca19c972c10447e947e83e3b178af66e739a`,
  check-runs SHA256 `d42ed8dc331543be3218c8c9c0d2f953252c5930a6912d24b5dd13ecdb74f533`.

Gli aggregatori `conditional-infrastructure-0049` e `validation-closure` hanno
rifiutato la parte fallita (fail-closed). Il run non è qualificante. Non è un
guasto infrastrutturale, quindi non si usa il rerun.

Il resto del modulo 0049 dura circa 45 minuti sul runner (in locale 1780 s) ed è
indivisibile senza toccare il candidato sigillato: la regola "oltre 30 minuti
aumenta N" non può ridurlo e il tetto di 45 minuti lo boccia. Decisione richiesta
(opzioni dell'addendum, aggiornate):

1. Tetto specifico per l'unità indivisibile `test_ocor_dev_0049` (resto del
   modulo), per esempio 60 minuti, restando 45 per ogni altra parte e 75 per la
   suite locale; arresto su riavvio/OOM e zero skip invariati. Raccomandata:
   l'unica che non tocca test o candidato sigillato; misura 2716 s per 388/389.
2. Autorizzare la correzione dell'isolamento dei test di 0049 (nuovo ciclo su
   0049 e riqualifica), che rende il modulo divisibile.
3. Escluso: runner più veloci a pagamento (vietati dal mandato).

Impatto: REM-0017 resta non qualificato; integrazione di 0049 e task G6
restano bloccati come oggi. G5 prosegue (`OCOR-DEV-0052`). Nessun tetto,
test o criterio cambiato. Registrato da Claude Code (implementatore di riserva).


## 2026-10-14 — attuazione REM-0017-CI-0049-REMAINDER-CAP, opzione 2

La decisione PO del 2026-10-10 risolve l'addendum con opzione 2: nessun tetto speciale. REM-0019 ha GO indipendente su 90b30fff981935cb48f63a890ec13f33190591e8 e sigillo in PR254; il task stage a0ee43d4e502f3589cd857cfec4238eab13fe8e7 conserva i soli test accettati per la CI. Nessun record storico viene riscritto. Il pin CI viene sostituito con quel task stage. I 390 casi sono indivisibili soltanto all'interno del singolo node ID parametrizzato: Helm ha una parte esclusiva, gli altri 389 si distribuiscono con gli altri moduli in quattro parti complete. Tetto2700s per parte, soglia1800s per ribilanciamento, unione esatta, zero skip, teardown fail-closed invariati. La presa d'atto sull'indivisibilità del modulo (2026-10-09) è superata.

Status: RESOLVED_PO_DECISION_IMPLEMENTED_PENDING_EXACT_HEAD_CI. Prove RED/GREEN e acquisizione Apache/cache reale presenti nel nuovo candidato REM17. La campagna locale del branch non sostituisce le quattro parti CI del candidato0049. Il precedente NO_GO e i timeout restano diagnostici. Nessun rerun identico di7d8e0fd. Verifier pianificato Cursor/Grok per0049 e per il change set REM17 toccato dal Claude Code di riserva negli addenda storici; nuova implementazione Codex. Nessun verifier avviato. E1=0,E2=0,Verified=0,NO-GO invariati.
