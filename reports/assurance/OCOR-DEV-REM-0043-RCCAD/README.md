# OCOR-DEV-REM-0043-RCCAD — revoca live a ogni autorizzazione di `ToolCallRuntime` (C8)

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 0.
  Verifier scelto dal loop (fornitore né Anthropic né OpenAI), processo e contesto separati. Implementatori del task:
  Claude Code (Anthropic, `claude-opus-5-5`) e Codex (OpenAI, contato dal loop). Revisione preventiva `SKIPPED`
  dal loop: nessun revisore di un fornitore ammesso disponibile (`PRE-CAMPAIGN-REVIEW`, punto 6).
- **Fonte**: remediation autonoma di un difetto runtime (`CC-OCOR-DELIVERY-COMPLETION` §7, primo `REM-*` libero
  verificato), emerso dal caso FGM-17 di `OCOR-DEV-0062` dopo la revisione preventiva
  `OCOR-DEV-0062-1e7693727633-pre`. Base normativa: ADD v1.3 Parte II §2.12; LLD v1.1 §7.2, riga FGM-17.
- **Branch**: `governed/ocor-dev-rem-0043-c8-dispatch-live-revocation`; commit di codice `b8875b44464a55e0d6df21775a47b037d29e6dcc`.
- Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Difetto

`ToolCallRuntime` riautorizzava ogni dispatch all'istante d'invocazione presentato dal chiamante, mentre
`CapabilityLease.is_active` considera una revoca efficace solo dal suo `revoked_at`: una lease revocata mentre
l'espressione era in corso lasciava passare il dispatch del tool successivo (l'effetto era poi rifiutato solo dentro
il tool, come `SandboxViolation`, non come rifiuto `CAPABILITY_DENIED` prima del dispatch).

## Modifica

| File | Modifica |
|---|---|
| `ocor-runtime/src/ocor_runtime/c8/tool_runtime.py` | ogni autorizzazione (la chiamata, ogni tool chiamato, ogni dispatch e il canale `authorize_effect`) legge anche il record live della lease e la sua catena di delega sulla `CapabilityAuthority` vincolata (`_require_live`); una revoca registrata rifiuta con `CAPABILITY_DENIED` prima del dispatch successivo, qualunque istante presenti il chiamante; il controllo dello stop epoch resta il primo e prevale (`STOP_BOUND_DENIED`); la chiamata verifica la vivacità prima di consumare un uso |
| `ocor-runtime/tests/tasks/test_ocor_dev_rem_0043.py` | nuovo modulo, 12 casi sui collaboratori reali; RED prima del codice a `81a8b760ef48` |
| `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json` | allowlist dei percorsi esatti e self-hash |

Invariati: `c6_capabilities.py`, `c8_agent.py`, sandbox sigillata, reason code, `ToolCallReceipt`; contratti, schemi;
test sigillati (`test_ocor_dev_0047.py`, `test_ocor_dev_rem_0027.py` byte-identici); `deploy/`, lock, `uv.lock`; script
di campagna, controllo dei residui delle corsie, workflow, limiti, timeout, soglie e gate.

Interpretazione fail-closed registrata: la rivalutazione "live" legge il record corrente dell'autorità, quindi ogni
revoca registrata rifiuta l'uso di un tool, anche se il suo `revoked_at` è successivo all'istante presentato (nessuna
semantica di revoca programmata sul percorso dei tool).

## Casi qualificanti

| Caso | Requisito citato | Casi passati | Esito |
|---|---|---|---|
| `OCOR-DEV-REM-0043-LIVE-REVOCATION-REFUSES-THE-NEXT-DISPATCH` | NFR-047 | 9 | PASS |
| `OCOR-DEV-REM-0043-LIVE-REVOCATION-BEFORE-CHARGE-AND-ON-THE-EFFECT-CHANNEL` | NFR-047 | 9 | PASS |
| `OCOR-DEV-REM-0043-POSITIVE-CONTROLS` | NFR-047 | 6 | PASS |
| `OCOR-DEV-REM-0043-STOP-EPOCH-PRECEDENCE` | NFR-081 | 12 | PASS |
| `OCOR-DEV-REM-0043-SEALED-C8-MODULES-UNCHANGED-AND-GREEN` | NFR-047 | 156 | PASS |
| `OCOR-DEV-REM-0043-VALIDATION-CLOSURE-GUARDS-LOCAL` | NFR-073 | 428 | PASS |
| `OCOR-DEV-REM-0043-STACK-LIFECYCLE` | NFR-073 | 9 | PASS |
| `OCOR-DEV-REM-0043-FULL-SUITE` | NFR-073 | 3346 | PASS |

I requisiti sono citati soltanto per il comportamento del rifiuto, la precedenza dello stop e la procedura di
qualifica: nessuna promozione. Il caso qualificante FGM-17 appartiene a `OCOR-DEV-0062`.

## Suite completa

- Modalità `TWO_LANE` (`scripts/run_local_lane_campaign.py --execute`, ammissione di memoria all'avvio).
- 3346/3346 PASS, zero skip, unione JUnit uguale alla raccolta
  (`ca4571b6186fc506…`).
- Durata complessiva 2464,478 s; margine dal tetto di 5400 s: 2935,522 s;
  margine dalla notifica di 3600 s: 1135,522 s.
  Soglia di decision request (5100 s) non raggiunta.
- Memoria: MemAvailable all'avvio 25658,3 MiB (soglia 14340,6 MiB), minimo 14490,5 MiB;
  guardia di 3000 MiB rispettata.
- Alimentazione: rete elettrica all'avvio e alla fine; a batteria in 25 letture su 47 (una al minuto: 2026-10-29T21:34:14Z-2026-10-29T21:58:15Z, batteria 79%->45%; capacità 80% all'avvio, 55% alla fine). Solo un dato da registrare: criteri, limiti ed esiti invariati.

| Corsia | Casi | Durata della corsia (s) | Tempo dall'avvio della campagna (s) | Esito |
|---|---|---|---|---|
| 1 | 1034 | 1434,141 | 1561,324 | PASS |
| 2 | 2312 | 2316,541 | 2452,692 | PASS |

## Riqualifiche

| Task | Record | Supersede | Tipo |
|---|---|---|---|
| `OCOR-DEV-0047` | `reports/evidence/G4/OCOR-DEV-0047.requalified-rem0043.json` | `OCOR-DEV-0047-requalified-rem0027-3832b9178a3f` | funzionale (input cambiato) |
| `OCOR-DEV-0005` | `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0043.json` | `OCOR-DEV-0005-requalified-rem0041-overlay-621c0a41ffe1` | sola regressione |
| `OCOR-DEV-0050` | `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0043.json` | `OCOR-DEV-0050-requalified-rem0041-overlay-621c0a41ffe1` | sola regressione |
| `OCOR-DEV-0082` | `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0043.json` | `OCOR-DEV-0082-requalified-rem0041-overlay-621c0a41ffe1` | sola regressione |

`OCOR-DEV-0047` ha fra gli input `c8/tool_runtime.py`: riqualifica funzionale, con ogni caso del record superato
riabbinato al terzo run del task e il caso di regressione alla suite completa. `0005`, `0050` e `0082` hanno fra gli
input `scripts/validate_ocor_development_plan.py` (allowlist): sola regressione (punto 4 di
`LOCAL-FULL-SUITE-CAP-90-AMENDMENT`). `OCOR-DEV-REM-0027` non è un `completed_evidence_task`: il suo modulo sigillato
gira come regressione. Test invariati; record sigillati intatti; inserimenti chirurgici nei `MANIFEST.json`.

## TDD, mutazioni, gate e revisione preventiva

- RED a `81a8b760ef48` (solo il test, runtime non corretto): 7 falliti, 4 passati
  (controllo positivo e guardie della precedenza dello stop); fingerprint `550812c2c1b3`.
- Sonda di mutazione (fuori da Git, stack di sviluppo): 6/6 mutanti uccisi; M2 è ucciso dal
  caso d'interleaving aggiunto nel commit di codice.
- Modulo FGM di `OCOR-DEV-0062` a `fb7117a07c65` con il solo `tool_runtime.py` corretto: 22/22, test invariato
  (sonda non qualificante).
- `PRE-CAMPAIGN-GATE` sull'head di codice: 41/42 PASS; `drift` atteso
  (0005, 0047, 0050, 0082) prima delle riqualifiche, 0 all'head dell'evidenza.
- Revisione preventiva `OCOR-DEV-REM-0043-b8875b44464a-pre`: `SKIPPED` (nessun revisore disponibile di fornitore diverso dagli implementatori (claude,codex) e dal verifier previsto (cursor)).

## Rollback

Revert dei commit di REM-0043: `tool_runtime.py` torna al comportamento di REM-0027, spariscono il modulo di test e le
voci dell'allowlist; i record precedenti di 0005, 0047, 0050 e 0082 tornano i più recenti. Nessun consumer,
contratto, lock o migrazione coinvolti.
