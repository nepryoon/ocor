# OCOR-DEV-REM-0031-RCCAD — C2: autorità di scrittura dell'IdentityRegistry (Q1)

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 0.
  Verifier richiesto: Grok 4.7 via Cursor CLI (xAI), oppure Antigravity/Gemini (Google), processo e
  contesto separati. Implementatori del task: Claude Code (Anthropic, `claude-opus-5-5`) e Codex (OpenAI,
  contato dal loop); nessun verifier Anthropic o OpenAI (`LOOP-AGENT-ROTATION`, `LOOP-IMPLEMENTER-ORDER`,
  `REM-0031-REGISTRY-CONSUMER-SCOPE` punto 6).
- **Fonte**: decisione del PO `REM-0024-IDENTITY-REGISTRY-WRITER-AUTHORITY` (2026-10-14), opzione 1, estesa
  da `REM-0031-REGISTRY-CONSUMER-SCOPE` (2026-10-25), opzione 1 (decision request su
  `governed/decision-request-rem0031-registry-consumer-scope`, commit `4daecbf19c07f88b88edc1a1e16bd2d08701caac`,
  sha256 `4efd0f22c1c0bb13ee8f9fe48644bf0f3e2528cc5f131ea3c1307b8d7ea12c67`, PR #345).
- **Branch**: `governed/ocor-dev-rem-0031-identity-registry-writer-authority`.

## Ambito

| Punto della disposition | Implementazione |
|---|---|
| 1 — `register()` | il controllo di immutabilità resta il primo (`IdentityConflictError` invariato, replay identico senza effetto); poi ogni record **nuovo** con una chiave Q1 (`principal_kind`, `status`, `roles`, qualunque valore) è rifiutato con `IdentityRegistrationDenied`, reason code `IDENTITY_PRIVILEGED_RECORD_REQUIRES_PROVISIONING`, registry invariato. Record senza chiavi Q1, schema `identity-record` e convenzione Q1 invariati |
| 2 — ingressi ammessi | seeding alla costruzione (`IdentityRegistry(records)`), prima della condivisione; a runtime solo `IdentityProvisioningBoundary` (WIP `6f98a15`, controlli invariati: writer autenticato da Keycloak reale, autorizzato da OPA reale con bundle firmato su mTLS SPIFFE, auto-attribuzione, writer registrati e aggiornamenti negati, fail-closed), che scrive tramite il percorso riservato `_admit_provisioned`. Nessun metodo pubblico ammette record Q1 dopo la costruzione |
| 3 — reason code | definito in `c2_identity.py` come i codici `PROVISIONING_*` e `BREAK_GLASS_*`: nessun registro, contratto o schema sigillato dei reason code né artefatto normativo modificato; `errors.py` invariato |
| 4 — consumer di test | soltanto i sei moduli autorizzati (`0043`, `0044`, `0058`, `REM-0024`, `REM-0027`, `REM-0028`): le scritture del registry diventano seeding alla costruzione. Guardia AST `reports/tests/test_rem0031_consumer_registry_scope.py`: stesso elenco di funzioni di test, nodi `assert`, `pytest.raises` e decorator di parametrizzazione identici, espressioni `IdentityRecord` seminate identiche, funzioni modificate entro un elenco esplicito, diff esatto fissato per sha256; i test di mutazione della guardia (8 mutazioni per file più una scrittura post-costruzione reintrodotta: 47 sottocasi) falliscono tutti. `test_a_requester_cannot_update_its_record_into_an_approver` è byte-identico e attende ancora `IdentityConflictError` |
| 5 — riqualifiche | record nuovi con `supersedes` esplicito per `OCOR-DEV-0043`, `0044`, `0058` (test cambiati, ambito funzionale) e, perché l'allowlist del validator di piano è loro input sigillato, `0005`, `0050`, `0082` (sola regressione); regressione documentata di `REM-0024`, `REM-0027`, `REM-0028` (e `0048`) senza record nuovi; manifest estesi in testa, nessun record sigillato modificato |
| 6 — verifica | suite del task e suite completa seriale da shell pulita (`scripts/bootstrap_ci_environment.py --execute --timeout 600`, `bootstrap.env` mai caricato); verifier esterno di fornitore diverso |

## TDD

- Boundary (WIP `6f98a15`, 2026-10-25): RED 48/48 `NotImplementedError` sullo scheletro dell'API, GREEN
  sullo stack reale, serie di mutazioni per clausola e controllo; i casi per clausola `actor_chain` sono un
  rafforzamento dopo il GREEN, dichiarato come tale.
- Chiusura di `register()`: casi scritti per primi (commit `8dc56bd`: scheletro con costruttore di seeding,
  tipo `IdentityRegistrationDenied` e percorso riservato, `register()` ancora aperto): 11 FAIL con
  `DID NOT RAISE`, 6 controlli positivi PASS; fingerprint nel record. GREEN `d0b9e1c`. Prova di mutazione
  al commit di codice: 6 mutanti (controllo Q1 assente, Q1 prima dell'immutabilità, solo `roles` riservato,
  tutte le chiavi richieste, seeding tramite `register()`, boundary tramite `register()`), tutti uccisi;
  baseline non mutata senza fallimenti.

## Vincoli rispettati

- Nessun test escluso, saltato o indebolito; nessun caso, limite, timeout o soglia cambiato.
- `E1=0`, `E2=0`, nessun requisito `Verified`; runtime conformance `NOT_ESTABLISHED`, PoC-GO e Production
  readiness `NO-GO`. Nessuna modifica a `inputs/`. La prova resta in processo e non dimostra runtime
  conformance (punto 8).

## Rischi residui (non dichiarati chiusi)

- Prova in processo: un chiamante con accesso al processo può invocare metodi privati; la garanzia è sulla
  superficie dell'API, non un confine di isolamento.
- `add_alias` continua a legare alias nuovi a un record esistente (comportamento invariato, fuori ambito):
  non crea record né attributi Q1; il resolver si astiene sull'ambiguità.
- I record senza chiavi Q1 restano scrivibili da `register()`: non portano autorità di principal.
- L'elenco delle autorità di provisioning della regola firmata è un parametro di composizione; la sua
  governance è fuori da questa remediation.

## Evidenza

- `OCOR-DEV-REM-0031.json` / `.log`: record della remediation, raw JSONL dell'intera campagna (reset e
  bootstrap versionati da shell pulita, guardia, suite del task, regressione sullo stack reale, suite
  completa seriale con unione esatta, RED del boundary e della chiusura, mutazioni, gate).
- `consumer-registry-scope.json`: output della guardia AST al commit di codice.
- Riqualifiche (`reports/evidence/G4/OCOR-DEV-0043.requalified-rem0031.json`, `…/G4/OCOR-DEV-0044…`,
  `…/G5/OCOR-DEV-0058…`, `…/G0/OCOR-DEV-0005…`, `…/G5/OCOR-DEV-0050…`, `…/G2/OCOR-DEV-0082…`), ciascuna con
  il raw della campagna byte-identico.
- Nessuna dichiarazione di verifica indipendente: la verifica è del loop esterno.

## Qualifica (commit di codice `f1e9e6e`, host Intel Core Ultra 9 275HX, 24 thread, 32 GB)

- Reset e bootstrap versionati da shell pulita: 11 container running, zero OOM e restart.
- Guardia AST: 3 test, 47 sottocasi, PASS. Suite del task `test_ocor_dev_rem_0031.py`: 73/73, zero skip.
- Regressione sullo stack reale (`0005`, `0043`, `0044`, `0048`, `0050`, `0058`, `0082`, `REM-0024`,
  `REM-0027`, `REM-0028`, `REM-0031`): 852/852, zero skip.
- Suite completa seriale (`scripts/run_qualifying_campaign.py`): 3180/3180, zero failure, error o skip,
  unione JUnit esatta con la raccolta, 3487,8 s (sotto la notifica dei 60 minuti e il tetto dei 75).
- Gate: digest normativi 8/8, ruff, mypy strict (85 file), `validate_rccad`, `validate_language_policy`,
  `validate_ocor_change_scope`, `validate_ocor_development_plan --authorized-extension` (37 PASS, 2
  opzionali `NOT_EXECUTED` non contati), `verify.py` 14 PASS.
- Nota sulla prova di mutazione: eseguita in un worktree separato senza credenziali dello stack mentre la
  suite completa girava; i 13 casi con fixture reali vi falliscono in setup (token admin Keycloak rifiutato)
  identicamente nella baseline non mutata e non sono contati come uccisioni. Le richieste rifiutate non hanno
  influito sulla campagna (3180/3180).
