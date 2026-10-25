# OCOR-DEV-REM-0027-RCCAD — C8: kill switch preemptive a ogni dispatch, lease legate allo `stop_epoch`

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo di riparazione 2 (ultimo del budget).
  Verifier richiesto: Grok 4.7 via Cursor CLI (xAI), processo e contesto separati. Implementatori del task:
  Claude Code (Anthropic, cicli 0, 1 e 2) e Codex (OpenAI, contato dal loop); nessun verifier Anthropic o
  OpenAI (`LOOP-AGENT-ROTATION`, `LOOP-IMPLEMENTER-ORDER`).
- **Verdetti precedenti**: `OCOR-DEV-REM-0027-f48452c64777-0` (`NO_GO`, VF-001–VF-003, corretti nella
  riparazione 1) e `OCOR-DEV-REM-0027-5cb0f629d084-1` (`NO_GO`, VF-001), disposto dal PO con
  `REM-0027-REPAIR-2-SCOPE-AND-VF001-DISPOSITION` (2026-10-14) ed eseguito nella riparazione 2.
- **Fonte**: decisione del Product Owner `INFO-C` (2026-10-05) e audit del 2026-10-12 in
  `reports/development/decision_requests/INFO-C.md`, che ha registrato `OCOR-DEV-REM-0027`
  (`EXECUTION_STATE` → `remediation_status.REM_0027_C8_PREEMPTIVE_KILL_SWITCH`). Nessuna dipendenza.
- **Branch**: `governed/ocor-dev-rem-0027-c8-preemptive-kill-switch`
- **Testo normativo**: LLD v1.1 §1.4 (`stop_epoch` nel record `CapabilityLease`), §4.3 (lo stop
  incrementa atomicamente `stop_epoch`, revoca lease, il reset non riabilita lease precedenti), §6
  ("cancellation cooperativa e kill switch preemptive"); ADD v1.3 §5.5 (nega nuove tool call mutative,
  revoca lease nel boundary locale, lease con `stop_epoch` corrente, target `≤10 s`).

## Ambito

| Osservazione (INFO-C, collaboratori reali in processo) | Correzione |
|---|---|
| C8-1 — uno stop accettato dopo `guard_dispatch` non impedisce l'effetto | ogni dispatch di tool è ri-autorizzato e recintato sull'epoch corrente del controller immediatamente prima dell'esecuzione: `STOP_BOUND_DENIED`, nessun effetto |
| C8-2 — il secondo tool della stessa espressione produce l'effetto 10,5 s dopo lo stop | ogni chiamata gira su un thread supervisionato ogni 10 ms: stop accettato o deadline (5 s di default, al massimo 10 s) rifiutano subito con `execution_unknown`; un tool cooperante è cancellato da `cancellation_checkpoint` prima dell'effetto; nessun tool successivo viene eseguito |
| C8-3 — una lease emessa all'epoch 0 è accettata dopo stop e reset all'epoch 2 | `ToolCallRuntime` lega la propria `CapabilityAuthority` al proprio `EmergencyStopController`: ogni lease registra l'epoch attendibile all'emissione; lease di altro epoch o senza epoch rifiutata; l'epoch presentato dal chiamante è solo confrontato con quello della lease; nessuna emissione durante lo stop; nessuna delega da una lease pre-stop |
| Controllo di classe — la lease autorizza `tool:<tool_name>` ma l'espressione può chiamare qualunque tool registrato | ogni tool registrato chiamato dall'espressione deve essere coperto dalla lease: verifica statica prima di addebito ed esecuzione (nessun effetto parziale) e di nuovo a ogni dispatch (revoca durante l'espressione) |

## Riparazione 1 (verdetto `OCOR-DEV-REM-0027-f48452c64777-0`)

| Finding | Correzione |
|---|---|
| VF-001 — un tool lento non cooperante produce l'effetto mutativo 11,7 s dopo lo stop; il test qualificante registrava il tool lento come non mutativo | dopo una tolleranza cooperativa di 0,25 s il runtime programma `ToolPreempted` (una `BaseException`, che un `except Exception` del tool non intercetta) nel thread del tool tramite `PyThreadState_SetAsyncExc`, serializzato con la chiusura del thread: il tool si ferma al passo successivo dell'interprete, prima dell'effetto. I test qualificanti registrano un effetto mutativo con timestamp e falliscono se arriva oltre 10 s dallo stop; nuovo caso con tool che inghiotte le eccezioni ordinarie |
| VF-002 — una lease genitore senza `stop_epoch` (emessa prima del binding) delega dopo stop e reset | su un'authority legata al controller la delega richiede l'epoch del genitore presente e uguale a quello del figlio |
| VF-003 — `CapabilityAuthority.authorize()` accetta la lease pre-stop dopo il reset; il ledger la lascia attiva | `authorize()` dell'authority legata rifiuta lease senza epoch o di epoch diverso dal corrente e ogni lease con controller non `NORMAL` (`StopEpochDenied`, mappato da C8 su `STOP_BOUND_DENIED`); tutti i chiamanti che condividono l'authority ereditano il fence (provato con `AgentKernel.execute_sandboxed`); il ledger registra le lease superate come revocate all'istante dello stop accettato |

Il contratto pubblico (OpenAPI/proto) non cambia: il campo `stop_epoch` è già nel record normativo
della lease (LLD §1.4) e viene aggiunto solo alla dataclass interna. `c6/safety.py` è invariato:
`OCOR-DEV-0044` non è riqualificato e `OCOR-DEV-REM-0024` (in attesa di decisione) non è toccato.

## Riparazione 2 (verdetto `OCOR-DEV-REM-0027-5cb0f629d084-1`, disposition del PO del 2026-10-14)

Criterio riallineato dal PO al testo di ADD v1.3 §5.5: dall'accettazione dello stop nessun nuovo dispatch
è accettato e nessuna lease pre-stop è utilizzabile (≤ 10 s); una chiamata in volo è cancellata ai
checkpoint cooperativi o chiusa dalla deadline con `execution_unknown`; ogni esito `execution_unknown`
produce un record di riconciliazione. VF-001 è fondato nei fatti ma non bloccante come formulato.

| Punto dell'ambito chiuso | Correzione |
|---|---|
| 1 — riconciliazione | prima di sollevare ogni rifiuto `execution_unknown` (stop durante il tool, deadline, stop osservato al completamento) `ToolCallRuntime` registra presso l'`OutcomeReconciler` reale di C6 un esito `EXECUTION_UNKNOWN`, mai idempotente, con nota JSON canonica di lease, tool, `stop_epoch`, reason code, correlazione, istanti di dispatch e di rifiuto; il record viaggia con il rifiuto (`ToolRuntimeError.reconciliation`) ed è nel journal del runtime; `require_may_auto_retry` lo blocca. Riconciliatore indisponibile → `RECONCILIATION_UNAVAILABLE`, fail-closed, nessuna receipt. `c6/safety.py` invariato (API `mark_ambiguous` esistente) |
| 2 — attesa nativa + `finally` | caso qualificante con `time.sleep(12)` e l'effetto tentato nel `finally`, registrato lì: `invoke` rifiuta entro 10 s (`STOP_BOUND_DENIED`, `execution_unknown`, record di riconciliazione); l'effetto tardivo tentato sul canale con lease (`ToolCallRuntime.authorize_effect`, authority legata) è rifiutato `STOP_BOUND_DENIED`; l'effetto su canale non governato è stampato come residuo misurato (`RESIDUAL_MEASURED_NOT_PASS`, 11,5 s dopo lo stop in ogni esecuzione) e non è mai asserito come contenuto |
| 3 — docstring ed evidenza | la docstring di `c8/tool_runtime.py` dichiara la preemption asincrona best-effort fra passi dell'interprete, chiamate native in corso e `finally` non interrompibili, il residuo tracciato verso FGM-17 e la qualifica G6 |
| 4 — nient'altro | suite del task tre volte, suite completa seriale una volta, zero skip; riqualifiche con `supersedes` |

Allineamento a `main` (merge non distruttivo `f34b46e` di `40ae60f`): conflitti solo su manifest G4/G5,
stato del piano (presi da `main`) e allowlist del piano (unione); l'harness del test REM-0027 adotta l'API
di reset di REM-0028 (requester e attributi del registry) senza cambiare alcuna asserzione.

## Vincoli rispettati

- `test_ocor_dev_0047.py` è byte-identico e passa: `OCOR-DEV-0047` è riqualificato (input
  `c8/tool_runtime.py` cambiato) con record nuovo e `supersedes` del record sigillato più recente
  (`requalified-rem0024`). L'allowlist del validator di piano, input sigillato di `OCOR-DEV-0005`, `0050` e
  `0082`, cambia soltanto per i percorsi esatti di questo change set: i tre task sono riqualificati con
  ambito di sola regressione. Nessun record sigillato modificato; i file candidati del ciclo 1, mai
  sigillati, sono sostituiti in posto e restano nella storia del branch.
- Nessun test escluso, saltato o indebolito. `E1=0`, `E2=0`, nessun requisito `Verified`; runtime
  conformance, PoC-GO e Production readiness invariati (`NOT_ESTABLISHED` / `NO-GO`). Nessuna modifica a
  `inputs/`.

## Rischi residui (non dichiarati chiusi)

- La preemption in processo è best-effort fra passi dell'interprete: una chiamata nativa in corso e il
  `finally` che la segue non sono interrompibili; il `finally` gira al ritorno della chiamata nativa
  (misurato 11,5 s dopo lo stop per un'attesa di 12 s). Il runtime resta limitato (rifiuto ≤ 10 s, nessun
  nuovo dispatch, record di riconciliazione) e il canale con lease rifiuta l'effetto tardivo, ma un effetto
  su canale non governato arriva tardi: residuo misurato, tracciato verso `FGM-17` e la qualifica G6.
  L'esecuzione dei tool fuori processo con terminazione allo stop è un'opzione di design per FGM-17, non
  autorizzata in questo ciclo.
- Senza stop, una chiamata chiusa dalla deadline lascia valida la lease: un effetto tardivo sul canale con
  lease è ancora autorizzato; l'esito è riconciliato come `EXECUTION_UNKNOWN`. Revoca o fence alla deadline
  sono fuori dall'ambito chiuso.
- L'`OutcomeReconciler` di C6 è in memoria (contratto sigillato 0044): la persistenza della riconciliazione
  appartiene al percorso di dispatch C6 e a G6. Gli istanti del record usano l'orologio UTC locale.
- Un tool che intercetta `BaseException` non è fermato; un worker bloccato in una chiamata nativa infinita
  occupa un thread per la vita del processo.
- La finestra della lease è valutata sull'istante `at` del chiamante (contratto 0047 invariato); la lease
  resta la `CapabilityLease` in processo (firma, monouso e binding di LLD §1.4 al percorso C6 e a G6).
- `ToolCallRuntime` non è ancora invocato da altri moduli (classificazione INFO-C); la qualifica G6
  (BA-08, NFR-047, FGM-17) ne dipende.

## TDD

Casi scritti per primi (`ocor-runtime/tests/tasks/test_ocor_dev_rem_0027.py`, commit `0249a28`) ed
eseguiti sul codice non corretto in un worktree separato con venv propria: 16 FAIL (12 su asserzioni di
comportamento, 4 per l'API della deadline assente), 2 controlli positivi PASS. GREEN dopo la correzione
(`7075300`). Casi aggiunti dopo: delega (`1c83a98`, RED supplementare: FAIL sul codice non corretto) e
comando recintato prima dello stop con lease nuova (`72ecedd`, guardia di regressione: passa anche sul
codice non corretto), aggiunto perché la prima prova di mutazione (13/14) lasciava vivo il mutante
"epoch del chiamante fidato". Prova di mutazione del ciclo 0: 14 mutanti su 14 uccisi.

Riparazione 1: casi scritti per primi (commit `b3c923e`), rafforzati in `a5d77f1` e `d577c62`, ed
eseguiti sui sorgenti del candidato `NO_GO` `f48452c` in un worktree separato con il file di test finale:
9 FAIL (VF-001: effetto mutativo oltre 10 s dallo stop; VF-002: deleghe da genitore senza epoch; VF-003:
`authorize()` ed `execute_sandboxed` accettano lease superate), 23 PASS. GREEN dopo la correzione
(`57fc18c`). Prova di mutazione al commit di codice `d577c62` con 22 mutanti (i 14 del ciclo 0 più 8 della
riparazione): 20 uccisi; M1 e M3 sono dichiarati equivalenti nel record (controlli ridondanti: il fence di
`authorize()` dell'authority legata verifica lo stesso epoch per primo). Una prima prova a `a5d77f1`
(18/22) lasciava vivi anche M8 (segnale cooperativo della deadline mascherato dalla preemption) e M14
(confronto di epoch nella delega mascherato dallo sweep del ledger salvo emissione retrodatata): i due casi
di `d577c62` li uccidono.

Riparazione 2: casi scritti per primi (commit `eea5c32`, solo il file di test sui sorgenti del merge
`f34b46e`): 9 FAIL (riconciliazione, riconciliatore indisponibile, canale con lease, attesa nativa +
`finally`), 32 PASS; fingerprint nel record. GREEN dopo la correzione (`a57d243`); `3832b91` sposta la
misura del residuo da `record_property` (ignorato da xunit2) a una riga su stdout, senza cambiare
asserzioni. Prova di mutazione della riparazione 2 su `3832b91`: 9 mutanti, tutti uccisi.

## Evidenza

- `OCOR-DEV-REM-0027.json` / `.log`: record della remediation (ciclo 2), raw JSONL dell'intera campagna
  (suite del task ×3, reset e bootstrap con la procedura CI versionata da shell pulita, regressione sullo
  stack reale, suite completa seriale con unione esatta, RED, prova di mutazione, diagnostica non
  qualificante del primo bootstrap fallito per la CA SPIRE usa-e-getta scaduta del worktree e del primo
  tentativo di suite completa, rifiutato dal guard della campagna perché l'implementatore aveva modificato
  questo README durante l'esecuzione: pytest 3107 PASS, ma il tentativo non conta né come PASS né come
  FAIL; reset, bootstrap e suite completa ripetuti sullo stesso head).
- Riqualifiche con `supersedes` esplicito, ciascuna con il raw della campagna byte-identico:
  `reports/evidence/G4/OCOR-DEV-0047.requalified-rem0027.json`,
  `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0027.json`,
  `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0027.json`,
  `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0027.json`; i manifest G0, G2, G4 e G5 sono estesi in
  testa, senza riscrivere voci esistenti.
- Nessuna dichiarazione di verifica indipendente: la verifica è del loop esterno.
