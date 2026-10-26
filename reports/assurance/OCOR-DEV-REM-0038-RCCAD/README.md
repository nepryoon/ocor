# OCOR-DEV-REM-0038-RCCAD — provisioning di Temporal e SeaweedFS nello stack di bootstrap e in CI

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 0.
  Verifier richiesto: Cursor CLI / Grok (xAI), oppure Antigravity / Gemini (Google), processo e contesto
  separati. Implementatori del task: Claude Code (Anthropic, `claude-opus-5-5`) e Codex (OpenAI, contato dal
  loop); nessun verifier Anthropic o OpenAI (`LOOP-IMPLEMENTER-ORDER-AUTH-FALLBACK`, 2026-10-26).
- **Fonte**: decisione normativa del PO `OCOR-DEV-0060-BA-SELECTED-COMPONENTS` (2026-10-26), opzione 2,
  change set **a** (provisioning nello stack di bootstrap e nella CI, pinned per digest, con lo stesso
  trattamento dei servizi esistenti). Decision request su
  `governed/decision-request-ocor-dev-0060-ba-selected-components`, commit
  `803abee616cef879b0c9dfe1218bfaa50200de96`, sha256
  `84cdd936ef6f2999497ebe3f50cb0b05e56f128ffbe0acab77bc78fff40c7574`, PR #351.
- **Branch**: `governed/ocor-dev-rem-0038-ba-services`.

## Ambito

| Componente | Provisioning |
|---|---|
| `BA-05` Temporal | `temporalio/server` 1.32.1 (MIT) con il proprio PostgreSQL (immagine `postgres` del lock, mai pubblicata sull'host, tmpfs) e `temporalio/admin-tools` 1.32.1 (MIT), che applica lo schema PostgreSQL v12 pinned prima dell'avvio del server e porta la CLI ufficiale per le sonde. Frontend solo su `127.0.0.1:17233` |
| `BA-06` SeaweedFS | `chrislusf/seaweedfs` 4.51 (Apache-2.0), modalità `mini` su tmpfs; pubblicato solo il gateway S3 su `127.0.0.1:18333`; identità admin S3 con segreto generato; richieste non firmate o con segreto errato negate. Bucket con S3 Object Lock e versioning verificati dalla sonda di qualifica |
| `BA-01` TerminusDB | già fornito e qualificato da `OCOR-DEV-0073` (12.0.7-noroot, digest pinned); invariato, riqualificato sullo stack a 15 container |

Stesso trattamento dei servizi esistenti: digest nel lock e nel Compose, policy condivisa (`restart: "no"`,
`init`, `no-new-privileges`, rete dedicata), limiti di memoria e CPU, healthcheck, verifica tipizzata con
moduli di qualifica fail-closed (`deploy/bootstrap/services/temporal`, `deploy/bootstrap/services/seaweedfs`),
fault recovery limitata (pausa/ripresa e riavvio), reset invariato (nulla di nuovo viene inizializzato),
smontaggio con il progetto Compose senza residui. La CI usa lo stesso profilo tramite
`scripts/bootstrap_ci_environment.py`, senza modifiche ai workflow; la guardia della campagna richiede ora i
15 servizi del Compose come container obbligatori.

Le dipendenze client Python (Temporal, S3, TerminusDB) appartengono agli adapter dei change set b, c, d.
Il benchmark di Temporal per `DEP-011` richiede il worker dell'SDK ed è `NOT_EXECUTED` qui, portato come
obbligo di `OCOR-DEV-REM-0039`; la licenza (MIT) è verificata.

## TDD

- RED su `origin/main` `72b2f9e` con lo stack reale a 11 servizi fornito dal bootstrap versionato di quel
  commit e il solo modulo `tests/tasks/test_ocor_dev_rem_0038.py` copiato: 18/18 FAIL.
- GREEN al commit di codice: modulo del task tre volte, regressione, suite completa seriale.
- Due difetti trovati dalla campagna e corretti nel change set, ciascuno con un caso che lo fissa:
  la guardia a 11 container di `scripts/run_qualifying_campaign.py` (consumer mancato dall'inventario) e
  l'esaurimento degli slot di volume di SeaweedFS (un bucket per sonda). I tentativi non qualificanti sono
  elencati nel record con gli sha256 dei loro artefatti, mai contati come PASS o FAIL.
- Un terzo difetto trovato dallo scanner di supply chain prima del push: il key id `AKIA…` dell'esempio
  SigV4 pubblicato da AWS nel contratto di `seaweedfs/test_qualify.py` è rifiutato dallo scanner dei
  segreti (check obbligatorio). Corretto in `36e6151` con un key id neutro: il key id non entra nella
  stringa da firmare, quindi la firma pubblicata resta invariata e verificata. Lo scanner non è stato
  toccato. La campagna intera, già passata sul commit `b81630a`, è stata rieseguita al commit `36e6151`
  (tentativo `a6`, superato).

## Riqualifiche

Record nuovi con `supersedes` esplicito, nessun record sigillato modificato, manifest estesi in testa:
`OCOR-DEV-0070`, `0072`, `0073`, `0074`, `0075`, `0076`, `0077`, `0078`, `0079` (input di provisioning
cambiati) e, per l'allowlist del validator di piano, `0005`, `0050`, `0082` (sola regressione; `0082`
anche reset e smontaggio).

## Vincoli rispettati

- Nessun test escluso, saltato o indebolito; nessun limite, timeout o soglia cambiato.
- `inputs/` intatto; nessun nuovo `DEC-*`; contratti, port, schemi e semantica invariati.
- `E1=0`, `E2=0`, nessun requisito `Verified`; runtime conformance `NOT_ESTABLISHED`, PoC-GO e Production
  readiness `NO-GO`. Temporal, SeaweedFS e TerminusDB restano `Candidate Implementation` fino alla qualifica
  di `OCOR-DEV-0060`.
