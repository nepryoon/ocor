# OCOR-DEV-REM-0027-RCCAD — C8: kill switch preemptive a ogni dispatch, lease legate allo `stop_epoch`

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`. Verifier: Grok 4.7 via Cursor CLI
  (processo, contesto e fornitore separati); Claude Code, implementatore di riserva, non verifica
  questo change set (`LOOP-ROLES`).
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

Il contratto pubblico (OpenAPI/proto) non cambia: il campo `stop_epoch` è già nel record normativo
della lease (LLD §1.4) e viene aggiunto solo alla dataclass interna. `c6/safety.py` è invariato:
`OCOR-DEV-0044` non è riqualificato e `OCOR-DEV-REM-0024` (in attesa di decisione) non è toccato.

## Vincoli rispettati

- `test_ocor_dev_0047.py` è byte-identico e passa: `OCOR-DEV-0047` è riqualificato con record nuovo e
  `supersedes`; l'allowlist del validator di piano, input della riqualifica sigillata REM-0026 di
  `OCOR-DEV-0050`, cambia, quindi 0050 è riqualificato con ambito di sola regressione. Nessun record
  sigillato modificato.
- Nessun test escluso, saltato o indebolito. `E1=0`, `E2=0`, nessun requisito `Verified`; runtime
  conformance, PoC-GO e Production readiness invariati (`NOT_ESTABLISHED` / `NO-GO`). Nessuna modifica a
  `inputs/`.

## Rischi residui (non dichiarati chiusi)

- Un tool che non chiama `cancellation_checkpoint` non è preemptibile dall'interprete Python: il runtime
  rifiuta subito con `execution_unknown`, ma il thread abbandonato può completare l'effetto. La
  riconciliazione è di C6 e non è collegata qui; tracciato verso `FGM-17`.
- La finestra temporale della lease è ancora valutata sull'istante `at` del chiamante (contratto 0047
  invariato); TTL di 5 s, firma, monouso per `(action_instance_id, emission_attempt)` e binding a
  delega/GCS/GatePackage della lease di LLD §1.4 restano al percorso di dispatch C6 e a G6.

## TDD

Casi scritti per primi (`ocor-runtime/tests/tasks/test_ocor_dev_rem_0027.py`, commit `0249a28`) ed
eseguiti sul codice non corretto in un worktree separato con venv propria: 16 FAIL (12 su asserzioni di
comportamento, 4 per l'API della deadline assente), 2 controlli positivi PASS. GREEN dopo la correzione
(`7075300`). Casi aggiunti dopo: delega (`1c83a98`, RED supplementare: FAIL sul codice non corretto) e
comando recintato prima dello stop con lease nuova (`72ecedd`, guardia di regressione: passa anche sul
codice non corretto), aggiunto perché la prima prova di mutazione (13/14) lasciava vivo il mutante
"epoch del chiamante fidato". Prova di mutazione al commit di campagna: 14 mutanti su 14 uccisi.

## Evidenza

- `OCOR-DEV-REM-0027.json` / `.log`: record della remediation, raw JSONL dell'intera campagna.
- `reports/evidence/G4/OCOR-DEV-0047.requalified-rem0027.json` e
  `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0027.json` (con i rispettivi `.log`, byte-identici al
  raw della campagna): riqualifiche con `supersedes` esplicito; i manifest G4 e G5 puntano ai nuovi record.
- Controllo meccanico riproducibile: vedi `reproducible_check` nel record (non è verifica indipendente).
