# OCOR-DEV-REM-0024-RCCAD — C6: break-glass conforme ad ADD v1.3 §5.4–5.5 e LLD v1.1 §4.2

- **Status**: `SEALED` (integrazione subordinata ai check obbligatori sullo stesso HEAD). Verifier: Grok 4.7 via Cursor CLI
  (processo, contesto e fornitore separati); Claude Code, implementatore di riserva, non verifica
  questo change set (`LOOP-ROLES`).
- **Fonte**: decisione del Product Owner `RVW-03` (2026-10-05) e audit del 2026-10-12 in
  `reports/development/decision_requests/RVW-03.md`, che ha registrato `OCOR-DEV-REM-0024` come primo
  identificativo libero (`EXECUTION_STATE` → `remediation_status.REM_0024_BREAK_GLASS_CONFORMANCE`);
  decisione del Product Owner `REM-0024-BREAK-GLASS-PRINCIPAL-AUTHORITY` (2026-10-13): Q1, Q2 e Q3
  opzione 1, con la condizione su Q1.
- **Branch**: `governed/ocor-dev-rem-0024-break-glass-conformance`

## Ambito

| Osservazione (sonda RVW-03) o punto della decisione | Correzione |
|---|---|
| P1 / punto 1 — un grant costruito fuori da `grant()`, con approvatori mai registrati, autorizzava | il controller registra ogni grant che emette; `authorize` e `revoke` accettano solo il grant registrato e non alterato (`BREAK_GLASS_GRANT_NOT_ISSUED`) |
| P2 / punto 2 — un principal workload accettato come approvatore; nessun richiedente | richiedente obbligatorio, risolto, `ACTIVE`, mai approvatore; due approvatori distinti, risolti, `HUMAN`, `ACTIVE`; rivalidazione contro il registry a ogni uso |
| Quorum ADD §5.4 — "Security Duty Officer + affected Domain Owner" | ruoli `SECURITY_DUTY_OFFICER` e `DOMAIN_OWNER:<dominio del grant>` su due approvatori distinti (`BREAK_GLASS_ROLE_QUORUM_UNMET`) |
| P3 / punto 3 — istanti del chiamante retrodatati o futuri accettati | `TrustedClock` iniettato; `grant` e `authorize` non accettano istanti; istante ingenuo o precedente all'emissione rifiutato |
| X1 — capability fuori dallo scope autorizzata | capability nominate nel grant; le altre rifiutate (`BREAK_GLASS_CAPABILITY_NOT_GRANTED`); le vietate rifiutate anche all'emissione |
| Punto 4 — TTL ≤ 15 minuti, nessun rinnovo | già soddisfatto: mantenuto e riprovato; un `grant_id` non è mai riemesso |
| Punto 5 — revoca e scadenza fail-closed | riprovato con tempo attendibile; la scadenza revoca in modo definitivo, anche con orologio riportato indietro |
| ADD §5.5 / LLD §4.2 — audit sincrono, alert immediato | grant, usi, rifiuti e revoche registrati in modo sincrono su un audit sink iniettato; grant e usi segnalati subito su un alert sink; guasto di audit o alert: operazione rifiutata, revoca comunque efficace |

Convenzione Q1 (interpretazione PoC, non estensione del contratto): chiavi riservate degli
`attributes` scalari di `identity-record` v1.2, lette soltanto dal record del registry —
`principal_kind` (`HUMAN`|`WORKLOAD`), `status` (solo `ACTIVE` è attivo), `roles` (token ordinati,
unici, separati da uno spazio). Attributo assente o malformato: rifiuto fail-closed.

## Vincoli rispettati

- Condizione Q1: nessun parametro di `grant` porta attributi, ruoli o natura (`TypeError`); i token di
  ruolo nel testo della richiesta sono ignorati; un richiedente o approvatore non può aggiornare il proprio
  record immutabile (`IdentityConflictError`); il controller non scrive mai nel registry.
  `GateSignature.role` riguarda lo Human Gate (`OCOR-DEV-REM-0028`). L'assenza di autorità di scrittura
  per i record nuovi resta la decision request aperta `REM-0024-IDENTITY-REGISTRY-WRITER-AUTHORITY`
  (draft PR #262): rischio residuo dichiarato, non chiuso qui.
- Q2: in `test_ocor_dev_0044.py` cambiano solo le nove funzioni break-glass e le loro fixture, con gli
  stessi casi, le stesse asserzioni e gli stessi reason code; corrispondenza uno a uno nel record
  (`test_adaptation_0044`). Test di stop e riconciliazione e fixture `identities` byte-identici.
- `c2_identity.py`, `human_gate.py` ed `EmergencyStopController` invariati (`request_reset` è
  REM-0028). `c6/safety.py` cambia, quindi `OCOR-DEV-0044` è riqualificato; `OCOR-DEV-0047`, che importa
  il modulo, è riqualificato come regressione, come previsto dalla registrazione; l'allowlist del
  validator di piano, input della riqualifica sigillata REM-0026 di `OCOR-DEV-0050`, cambia, quindi 0050
  è riqualificato con ambito di sola regressione. Nessun record sigillato modificato.
- Nessun test escluso, saltato o indebolito. `E1=0`, `E2=0`, nessun requisito `Verified`; runtime
  conformance, PoC-GO e Production readiness invariati (`NOT_ESTABLISHED` / `NO-GO`). Nessuna modifica a
  `inputs/`.

## TDD

Casi scritti per primi (`ocor-runtime/tests/tasks/test_ocor_dev_rem_0024.py`, commit `1a09bce`) ed
eseguiti sul codice non corretto in un worktree separato: tutti i 99 casi falliscono, perché
l'interfaccia conforme (orologio, audit, alert, richiedente, dominio, capability) non esiste. Poiché un
errore d'interfaccia da solo non mostra il difetto di comportamento, lo stesso raw log riporta la sonda
RVW-03 rieseguita sullo stesso sorgente: P1, P2, P3 e X1 `AUTHORIZED`. Adattamento dei test 0044
(`8bb22ae`), correzione (`5292054`), refactor senza cambi di comportamento (`f2b091d`), allowlist del
piano (`9faac98`). Prova di mutazione: 15 mutanti su 15 uccisi al commit della campagna, ciascuno
eseguito su una copia del sorgente; la prima prova (13 su 15) ha portato al refactor `f2b091d`.

## Evidenza

- `OCOR-DEV-REM-0024.json` / `.log`: record della remediation, raw JSONL dell'intera campagna.
- `reports/evidence/G4/OCOR-DEV-0044.requalified-rem0024.json`,
  `reports/evidence/G4/OCOR-DEV-0047.requalified-rem0024.json` e
  `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0024.json` (con i rispettivi `.log`, byte-identici al
  raw della campagna): riqualifiche con `supersedes` esplicito; i manifest G4 e G5 puntano ai nuovi record.
- Controllo meccanico riproducibile: vedi `reproducible_check` nel record (non è verifica indipendente).

## Verifica indipendente e sigillo

GO `OCOR-DEV-REM-0024-22b93473024c-0` del 2026-10-14, su
`22b93473024cfabb3d013f3516a57eff289c8c0a`: Grok 4.7 via Cursor CLI, processo, contesto
e fornitore separati da Claude Code, implementatore di riserva. Nessun finding bloccante.
Il verifier ha riprodotto la suite completa: 1.933 PASS, zero skip; 0048: 196 PASS,
0050: 198 PASS. Codex ha applicato soltanto i metadati di sigillo e aggiornato gli hash
dei nuovi record nei manifest. Sorgenti, test, raw log e sigilli storici invariati.
Il rischio del primo writer del registry resta aperto; la decisione del PO
`REM-0024-IDENTITY-REGISTRY-WRITER-AUTHORITY` (2026-10-14, opzione 1) ne autorizza una
remediation separata dopo REM-0028, obbligatoria prima di G6. Nessun claim promosso.
