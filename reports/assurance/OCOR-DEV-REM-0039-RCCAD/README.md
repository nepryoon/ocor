# OCOR-DEV-REM-0039-RCCAD — adapter Temporal di C6

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 0.
  Implementatori del task: Claude Code (Anthropic, `claude-opus-5-5`) e Codex (OpenAI, contato dal loop).
  Revisore preventivo: Antigravity CLI / `gemini-4-argon-high` (Google), escluso dalla
  verifica finale. Verifier richiesto al loop: né Anthropic, né OpenAI, né Google.
- **Fonte**: decisione normativa del PO `OCOR-DEV-0060-BA-SELECTED-COMPONENTS (2026-10-26)`, opzione 2,
  change set b (adapter runtime di `C6` su Temporal, dietro i port esistenti; licenza e benchmark `DEP-011`).
- **Branch**: `governed/ocor-dev-rem-0039-temporal-c6-adapter`; commit di codice `95e89f7a16e5339f2bcd9e1b2a9fd4eec632b311`.

## Modifica

| File | Modifica |
|---|---|
| `ocor-runtime/src/ocor_runtime/c6/temporal_adapter.py` | `TemporalC6Runtime`, `TemporalLeaseState` (implementa `kernel.governance.LeaseStatePort`, un workflow per scope) e `TemporalEffectSink` (implementa `c6.fsm.EffectSink`, un workflow per azione) |
| `ocor-runtime/src/ocor_runtime/c6/temporal_workflows.py` | workflow deterministici: precedenza dello stop epoch, fencing del worker stale, revoca, finestra fidata, consumo al più una volta, ogni tentativo di consegna conservato; effetti deduplicati per chiave di idempotenza, ri-consegna in conflitto rifiutata |
| `ocor-runtime/tests/tasks/test_ocor_dev_rem_0039.py` | 19 casi: 5 senza rete, 14 sul server Temporal reale dello stack |
| `ocor-runtime/pyproject.toml`, `ocor-runtime/uv.lock` | `temporalio==1.34.0` nell'extra `test`; lock riscritto dallo uv del lock (0.12.5), versioni e hash dei wheel cp312/any dei pacchetti esistenti invariati |
| `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json` | allowlist dei percorsi esatti di REM-0039 e self-hash |

Invariati: `LeaseStatePort`, `InMemoryLeaseState`, `EffectSink`, tabella delle 44 transizioni, contratti, schemi,
SDK, provisioning di Temporal (REM-0038), test, casi, timer, timeout, soglie, partizioni e gate.

## Dipendenze (`NFR-073`, `DEP-011`)

| Pacchetto | Versione | Licenza | Tipo |
|---|---|---|---|
| `nexus-rpc` | 1.4.0 | MIT | transitiva |
| `temporalio` | 1.34.0 | MIT | diretta (extra `test`) |
| `types-protobuf` | 7.35.1.20260906 | Apache-2.0 | transitiva |

Benchmark `DEP-011` (nessuna soglia dichiarata, solo misura): 200 operazioni `consume_if_current`
sequenziali sul server 1.32.1, 1,405 s, 142.4 op/s, latenza p50
6.74 ms, p95 9.46 ms, max 12.58 ms. La misura viene dalla fase C
(stack nuovo dopo la campagna, stesso head, modulo eseguito con `-s`), perché il reporting `-rfEs` delle tre corse
qualificanti nasconde lo stdout dei casi passati.

## TDD

- RED su `origin/main` `251f406778bb`: 5 failed e 14 errors su 19 (modulo dell'adapter assente),
  fingerprint `ddedd300ffd7e19197bc194f6ffa094e0408ae5b08b7b5bf8158ef0e19912663`.
- GREEN al commit di codice: modulo del task tre volte nella campagna (19/19 ciascuna), riqualifiche, portfolio dei
  report e suite completa.
- Mutation probe sui workflow: 8/8 mutanti uccisi.

## Inventario e riqualifiche

Al commit di codice il validatore della deriva elenca 21 task. Riqualifiche `.requalified-rem0039` con
`supersedes` esplicito del record più recente, record sigillati intatti, test dei task invariati:

- sostanziali (19): 0002, 0003, 0004, 0005, 0006, 0007, 0008, 0009, 0010, 0011, 0012, 0013, 0014, 0015, 0019, 0020, 0022, 0023, 0071 — input `ocor-runtime/uv.lock` e/o
  `pyproject.toml`; per 0071 l'ambiente congelato è ricontrollato (`uv lock --check`, `uv sync --frozen`,
  `uv pip check`, `verify_external_services.py --manifest-only`);
- di sola regressione (2): 0050, 0082 — allowlist del piano.

## Gate e revisione preventiva

- `PRE-CAMPAIGN-GATE` al commit di codice: 42 passi ricavati dai workflow, tutti PASS
  salvo il drift, che elenca esattamente le 21 riqualifiche (atteso) ed è 0 all'head dell'evidenza.
- `PRE-CAMPAIGN-REVIEW`: `OCOR-DEV-REM-0039-ee8bb20b16ac-pre` sull'head `ee8bb20b16ac`, esito `NO_BLOCKING_FINDINGS`, due finding
  consultivi, entrambi accolti nel commit `95e89f7` (asserzioni sui pacchetti transitivi; docstring sul retry di
  `persist_effect`). Sha256 dell'esito `3fd3daa22abdd909f86105f6c26c6d426573b1607695fd2bc266b4746032eb66`.

## Campagna

- Shell pulita (`env -i`, PATH del lock verificato per sha256), `scripts/bootstrap_ci_environment.py --execute
  --timeout 600`, stack a 15 container, 11 servizi tipizzati READY prima e dopo il reset.
- Suite completa seriale: 3243/3243, zero skip, unione JUnit esatta, 3640,805 s
  (sopra la notifica di 3600 s di 40,805 s; margine calcolato dal tetto di 5400 s:
  1759,195 s). Smontaggio con zero residui. Alimentazione: rete elettrica per tutta la corsa (una lettura al minuto).
- Nessun tentativo non qualificante.

## Vincoli rispettati

- `inputs/` intatto; nessun nuovo `DEC-*`; nessun port, contratto o schema cambiato; nessun test indebolito.
- Temporal resta `Candidate Implementation` fino alla qualifica di `OCOR-DEV-0060`.
- `E1=0`, `E2=0`, nessun requisito `Verified`; runtime conformance `NOT_ESTABLISHED`, PoC-GO e Production
  readiness `NO-GO`.

## Sigillo (dopo GO indipendente)

- **Verdetto**: `OCOR-DEV-REM-0039-6251115923cd-0`, `GO_FOR_EVIDENCE_SEAL`, zero finding, nulla `NOT_EXECUTED`
  (file sha256 `cbbd672cb4244b366558de420cc0079086be7ffc13dd32decdcfbfee8d77741d`). Verifier: Cursor CLI /
  grok-4.7-high / xAI, contesto separato. Suite del task 19/19 su Temporal reale (server 1.32.1); riqualifiche
  568/568; suite completa seriale del verifier 3243/3243, zero skip, 3986,774 s: 386,774 s sopra la notifica di
  3600 s, margine calcolato dal tetto di 5400 s 1413,226 s, dalla soglia di decision request di 5100 s 1113,226 s.
  DEP-011 misurato dal verifier: 127,2 op/s, p95 10,38 ms, nessuna soglia dichiarata. Rete elettrica a inizio e
  fine suite (dato del verifier).
- **Allineamento**: HEAD verificato `6251115` unito in modo non distruttivo con `origin/main` `7f335fc`
  (`5a34b2f`); cambiano soltanto i tre file di stato, albero non di stato identico.
- **Sigillo**: `OCOR-DEV-REM-0039.json` e le 21 riqualifiche `.requalified-rem0039` (`OCOR-DEV-0002`–`0015`,
  `0019`, `0020`, `0022`, `0023`, `0050`, `0071`, `0082`) passano a `SEALED`; i manifest G0, G1, G2 e G5 puntano
  agli hash sigillati. In `OCOR-DEV-REM-0039.json` i `record_sha256` delle riqualifiche restano gli hash candidati
  verificati; gli hash sigillati sono affiancati in `independent_verification.sealed_requalification_records`.
  Raw log invariati; nessun record sigillato precedente modificato.
- **Ruoli**: implementatore e integrazione Claude Code (Anthropic, `claude-opus-5-5`); Codex (OpenAI) contato dal
  loop; revisore preventivo Antigravity/Gemini (Google). Temporal resta `Candidate Implementation` fino alla
  qualifica di `OCOR-DEV-0060`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e
  Production `NO-GO`.
