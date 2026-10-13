# Decision request — INFO-C (concorrenza delle classi in-memory)

- **Status**: `RESOLVED` — decisione del Product Owner `INFO-C` (2026-10-05); audit di conformità
  eseguito il 2026-10-12; remediation registrate come `OCOR-DEV-REM-0026` (C5) e `OCOR-DEV-REM-0027`
  (C8).
- **Fonte**: `reports/review/OCOR_FULL_CODE_REVIEW_2026-09-15.md` (osservazione INFO-C)

## Risoluzione (2026-10-05, eseguita il 2026-10-12)

Il Product Owner ha risolto la richiesta con un audit di conformità mirato: nessuna thread-safety
generica e nessuna modifica semantica. LLD v1.1 §6 ("Concorrenza e failure semantics") e §4.3 fissano
invarianti specifici, quindi il requisito non è "non confermato". Per ciascuna classe l'audit stabilisce
(a) se è nel percorso reale del PoC o è solo implementazione di riferimento per i test e (b) se
l'invariante può essere violato; la remediation si apre solo dove entrambe le condizioni valgono.

## Oggetto e testo normativo

Codice su `origin/main` `78d297c12cbd0c6f14ef3a9f831658e9c50d3d0f`:

| File | SHA-256 |
|---|---|
| `ocor-runtime/src/ocor_runtime/c5/backbone.py` | `d34a3609907905001a6780242f88e257d7707d05a1a20ade791b6880bf75c914` |
| `ocor-runtime/src/ocor_runtime/c5/operations.py` | `922a9984d263cf8bd4a316781d88307b9668248962491799fd017f2effbb95b5` |
| `ocor-runtime/src/ocor_runtime/c8/tool_runtime.py` | `2055f82ee14e5d65d4fa06ec70df3e69ebd25be33124f3110a8fa4e23e0b26ea` |

Testo normativo:

- LLD v1.1 §6: "C4/C5: ordering per aggregate/partition; watermark monotono; deduplica durable"; "C8:
  [...] cancellation cooperativa e kill switch preemptive".
- LLD v1.1 §2.5: "Backpressure applica quote per tenant e priority class"; replay "non pubblica due
  volte un canonical effect".
- LLD v1.1 §4.3: "L'accettazione dello stop incrementa atomicamente `stop_epoch`, revoca lease e
  impedisce nuovi DeliveryAttempt [...] Reset richiede dual control [...] nuovo epoch e non riabilita
  lease precedenti".
- ADD v1.3 §5.5 (baseline approvata in
  `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md`): l'attivazione dello stop
  "nega nuove tool call mutative" e "revoca Delegation e capability lease nel boundary locale"; "Ogni
  mutative call presenta una capability lease con `stop_epoch` corrente [...] target `≤10 s` [...]
  dall'accettazione locale dell'evento firmato all'ultimo nuovo command accettato". ADD v1.3 §2.2
  (riga C5): "Consumer idempotenti e replay"; (riga C8): "revoca impedisce nuove tool call".
- LLD v1.1 §7 (`FGM-17`): "race kill switch/revoca delega — nessuna retrieval o tool influence
  successiva".

## Classificazione (a): percorso reale del PoC

Nessuna delle tre classi ha chiamanti in `ocor-runtime/src` (consumer: `test_ocor_dev_0040.py`,
`test_ocor_dev_0041.py`, `test_ocor_dev_rem_0022.py` per C5; `test_ocor_dev_0047.py` per C8). Non sono
però double di test che sostituiscono un backend: sono l'unica implementazione PoC della funzione
normativa (C5 su Kafka reale; il boundary dei tool di C8), quella che la qualifica G6 eserciterà (`BA-07`
per C5; `BA-08`, `NFR-047` e `FGM-17` per C8). Con l'interpretazione fail-closed più restrittiva
(RCCAD, ambiguità senza impatto semantico) e in coerenza con il record `INFO-A`, sono trattate come
percorso reale del PoC ai fini della remediation, con la precisazione che oggi nessuna composizione
applicativa le invoca.

## Prove eseguibili

Prove in sola lettura sul codice invariato, fuori dal repository e non qualificanti, in
`~/.ocor-codex/infoc-audit-20261012/`. Sono osservazioni del comportamento attuale, non evidenza
`E1`/`E2`.

| Prova | SHA-256 script | Esito | SHA-256 esito |
|---|---|---|---|
| C5, broker Kafka reale auto-provisionato da `CanonicalEventBackbone.provision` e smontato da `destroy` | `probe_c5.py` `d8a619866382d41f93542607aa898331558758f808ed8bcd6f463475c1461dce` | `probe-c5-result.json` | `b41d78dbab065fc0f06de932a7475d0d5a639d9526f8fff52226d02142200d39` |
| C8, collaboratori reali in processo come nei fixture di 0047; stop attivato da un thread separato | `probe_c8.py` `fa02e6ff0109367130427d6a99efef907b25f33dd5665959913242516029bf75` | `probe-c8-result.json` | `762da6c655d68d1e837601c213da79b33687eb7f0796e2268dd038e093691042` |

Inventario di container e volumi Docker identico prima e dopo la prova C5 (`inventory-*.txt`). Restano
nella cartella, con i loro hash, il primo tentativo della prova C5 (scenari di riavvio mal costruiti:
il replay di R1 reimpostava lo stato usato da R2; `attempt1-*`) e la prima versione della prova C8
senza lo scenario C8-3 (`v1-*`, stessi esiti per C8-0–C8-2).

## Esito per classe

### 1. `c5/backbone.py` — stato in memoria, "deduplica durable" e "watermark monotono"

`_seen_idempotency_keys: set[str]` e `_last_sequence: dict[str, int]` (righe 172–173) vivono solo
nell'istanza: il costruttore li crea vuoti e nulla li ricostruisce dal topic. In `publish` il controllo
(righe 312 e 317–318) e l'aggiornamento (righe 341–342) sono separati dalla scrittura su Kafka (righe
325–340, un `docker exec` di circa un secondo) senza alcun lock.

| Invariante | Esito | Prova |
|---|---|---|
| Deduplica durable al riavvio | **Violato.** Un'istanza nuova sullo stesso broker e topic ripubblica un evento già durevole | `R1`: stesso envelope ripubblicato dopo il riavvio, 2 record sul topic |
| Ordering/watermark per aggregate al riavvio | **Violato.** Dopo il riavvio una sequenza più vecchia è accettata | `R2`: sequenza 5, riavvio, sequenza 4 pubblicata (controllo: la stessa istanza la rifiuta `OUT_OF_ORDER`) |
| Deduplica sotto publish concorrenti | **Violato.** Due worker con lo stesso envelope passano entrambi il controllo | `K1`: 2 record per la stessa `idempotency_key` |
| Watermark monotono sotto publish concorrenti | **Violato.** Le sequenze 5 e 4 sono entrambe accettate e il valore registrato regredisce da 5 a 4 | `K2`: topic `[3, 5, 4]`, `_last_sequence` finale 4 |

La chiave di isolamento della stessa deduplica è già assegnata a `OCOR-DEV-REM-0025` (record `INFO-A`)
e non è ripetuta qui.

### 2. `c5/operations.py` — backpressure read-modify-write

Il testo "watermark monotono" non riguarda il contatore di backpressure, che non è un watermark: il
watermark di C5 è lo stato di sequenza del punto 1. L'invariante applicabile è la quota per tenant di
LLD v1.1 §2.5, che la classe dichiara come limite agli in-flight *concorrenti* e che quindi ha senso solo
sotto accesso concorrente. Lettura (riga 81), confronto (riga 82) e scrittura (riga 86) non sono
atomici; il decremento (riga 90) è un read-modify-write separato.

| Invariante | Esito | Prova |
|---|---|---|
| Quota per tenant limitata | **Violato.** Con quota 1 due publish concorrenti sono entrambi ammessi e arrivano al broker | `Q1`: 2 record, nessun `BACKPRESSURE_EXCEEDED`; l'interleaving fra lettura e scrittura è forzato da uno strumento di osservazione sul dizionario privato, interleaving che il codice ammette perché non c'è lock |
| Contatore coerente | **Violato.** Dopo `Q1` il contatore resta a −1, quindi la quota effettiva del tenant è da quel momento 2 | `Q1`: `final_counter` −1 |

Con lo scheduling naturale (`Q2`, 8 publish concorrenti, quota 1, intervallo di switch del GIL 1 µs) la
corsa non si è presentata (1 ammesso, 7 rifiutati): la violazione dipende dall'interleaving, ma il codice
non la impedisce.

### 3. `c8/tool_runtime.py` — finestra fra controllo dello stop ed esecuzione

`ToolCallRuntime.invoke` controlla lo stop una sola volta (`guard_dispatch`, riga 119, sotto il lock del
controller che viene rilasciato all'uscita) e poi addebita il budget (riga 123) ed esegue l'intera
espressione nella sandbox (riga 125). La sandbox limita il numero di operazioni ma non il tempo e può
chiamare in sequenza più tool registrati; nessun punto ricontrolla lo stop, e una chiamata in corso non è
interrompibile.

| Invariante | Esito | Prova |
|---|---|---|
| Stop già accettato prima della chiamata | **Conforme.** `STOP_BOUND_DENIED`, nessun effetto | `C8-0`; test 0047 `test_an_active_emergency_stop_produces_no_tool_effect` |
| Nessun nuovo dispatch dopo l'accettazione dello stop (§4.3) | **Violato.** Uno stop accettato dopo `guard_dispatch` non impedisce l'effetto; la ricevuta riporta l'epoch 0 mentre il controller è a 1 in `STOPPING` | `C8-1` |
| Kill switch preemptive e target `≤10 s` (§6, ADD §5.5) | **Violato.** Un secondo tool della stessa espressione produce il suo effetto 10,5 s dopo l'accettazione dello stop; il ritardo è limitato solo dalla durata del tool precedente | `C8-2` |
| Reset che non riabilita lease precedenti (§4.3) | **Violato.** Una lease emessa all'epoch 0 è accettata dopo stop e reset con dual control all'epoch 2: `CapabilityLease` non porta `stop_epoch` e l'epoch passato a `invoke` è scelto dal chiamante, mentre lo stop non revoca le lease | `C8-3` |

Osservazione emersa nello stesso punto di dispatch: la lease autorizza `tool:<tool_name>`, ma
l'espressione può invocare qualunque tool registrato nella sandbox (`C8-2` chiama `slow_lookup` con una
lease emessa solo per `restart_service`). Il vincolo di capability vale quindi per il nome dichiarato, non
per ogni tool effettivamente chiamato. È registrata come controllo di classe di `OCOR-DEV-REM-0027`,
perché la correzione del dispatch per singolo tool lo coinvolge.

## Remediation registrate

Identificativi verificati liberi il 2026-10-12 su tutti i ref locali e remoti, sui file di
`~/.ocor-codex` e sulle PR (ultimo usato: `OCOR-DEV-REM-0025`). Ambito, criteri, file attesi e
dipendenze sono in `reports/development/EXECUTION_STATE.json` → `remediation_status`. Entrambe sono
dipendenze obbligatorie dei task G6 (`OCOR-DEV-0060` e successivi) e non bloccano `OCOR-DEV-0049` né
G5.

- **`OCOR-DEV-REM-0026`** (`REM_0026_C5_DURABLE_ATOMIC_DEDUP_AND_QUOTA`): deduplica e stato di sequenza
  durable al riavvio e atomici sotto publish concorrenti (watermark per aggregate mai regressivo); quota
  per tenant atomica, con contatore che non può superare la quota né scendere sotto zero. Si esegue dopo
  `OCOR-DEV-REM-0025` sugli stessi file, conservandone lo scoping per contesto. Riqualifica 0040 e 0041
  (e ogni altro task il cui record più recente ha i file modificati fra gli input).
- **`OCOR-DEV-REM-0027`** (`REM_0027_C8_PREEMPTIVE_KILL_SWITCH`): stop ricontrollato in modo atomico a
  ogni dispatch di tool, anche all'interno della stessa espressione; nessun effetto dopo l'accettazione
  dello stop; chiamate in corso cancellate dove il contratto lo consente o limitate così che l'ultimo
  effetto resti entro `≤10 s`; lease legata allo `stop_epoch` e non riabilitata dal reset; ogni tool
  chiamato coperto dalla lease. Riqualifica 0047 (e 0044 se cambia `c6/safety.py`). Se il legame
  lease–epoch richiedesse una modifica di contratto pubblico, l'implementatore scrive una decision
  request invece di inventarla.

`E1=0`, `E2=0`, `Verified=0`, claim `NO-GO` e record sigillati invariati. Nessun `DEC-*`, nessuna
modifica di codice, test o evidenza in questa unità.

## Contesto originale

Classi in-memory (`c5/operations.py` backpressure RMW, `c8/tool_runtime.py` finestra
TOCTOU sullo stop, stato in-memory di `c5/backbone.py`) presentano finestre di race solo
sotto accesso multi-thread. Il requisito di thread-safety per queste classi di
riferimento non è confermato (le vie reali passano da Kafka/backend).

## Opzioni originali

1. **Lasciare invariato** — nessun requisito di thread-safety confermato.
2. **Introdurre thread-safety** — richiede conferma normativa del requisito e un REM
   dedicato.

## Raccomandazione originale

Raccomandavo l'opzione 1 finché il requisito di thread-safety non fosse confermato in LLD. La decisione
del 2026-10-05 ha stabilito che LLD v1.1 §6 e §4.3 fissano invarianti specifici e ha disposto l'audit
mirato qui sopra.

## Impatto

Originale: nessuno sul flusso previsto. Dopo l'audit: `OCOR-DEV-REM-0026` e `OCOR-DEV-REM-0027` sono
dipendenze dei task G6.

## Task bloccati

Nessuno da questa richiesta. `OCOR-DEV-REM-0026` e `OCOR-DEV-REM-0027` bloccano i task G6 fino alla
loro chiusura verificata.
