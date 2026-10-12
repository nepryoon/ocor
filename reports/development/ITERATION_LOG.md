# OCOR RCCAD iteration log

## 2026-09-02 — CC-RCCAD-METHODOLOGY-ADOPTION / DEC-210

- Baseline: `69652a3c4bd6cdd13d54c0a7e326c9d44958f985`; isolated branch/worktree verified clean.
- Reconciliation: normative SHA256 `PASS`; prescribed root venv absent, document harness `NOT_EXECUTED`; no retry or install performed.
- Existing evidence: G0 tasks 0001–0006, G1 tasks 0007–0014 and G2 tasks 0015/0019/0020/0022/0023 are content-addressed in gate manifests. This reconciliation does not re-accept or promote them.
- External blockers: G2 tasks 0016/0017/0018/0021 require unavailable real services; branch protection remains under compensating controls.
- Conflict resolution: the pre-existing AI-first plan/backlog and DAG remain authoritative planning sources. RCCAD refines execution and points to them rather than duplicating task truth.
- RED: methodology acceptance suite exited 1 with 5 non-green tests because all required artifacts and validator were absent; failure was expected and captured before implementation.
- Branch control: `governed/DEC-210-rccad-adoption` è stato rifiutato dal validator per lettere maiuscole; il branch è stato rinominato `governed/dec-210-rccad-adoption` prima dell'integrazione.
- Plan validators: `NOT_EXECUTED` localmente perché il Python di sistema non dispone di `jsonschema`; nessuna dipendenza è stata installata e i gate pinned di CI restano obbligatori.
- GREEN/REFACTOR: 5/5 acceptance test `PASS`; RCCAD validator `PASS` su 16 artefatti e zero finding; scope validator `PASS` su 19 path; JSON parse dello schema, diff check e immutable-input check `PASS`.
- Verifier pass 1: `NO-GO` sul commit `347f65a3…` per indici DEC-210, TDD evidence e fitness incomplete. Remediation: registri append-only v1.4 legati ai digest v1.3, evidence JSON inclusa e validator esteso con risultati espliciti `AFF-001`–`AFF-010`; nuovo local run `PASS` su 18 artefatti e tutti i dieci fitness gate.
- Verifier pass 2: `NO-GO` sul commit `96f056db…`: i token scan non qualificano dinamicamente le AFF e la TDD evidence non era verificata semanticamente. Remediation: esiti locali rinominati `PASS_STATIC_PRECHECK`, `dynamic_assurance=CI_REQUIRED`, fingerprint/commit TDD verificati, comandi AFF distinti e portfolio CI pinned con PostgreSQL reale. La Docker API locale è inaccessibile: riproduzione dinamica locale `NOT_EXECUTED`, senza retry.
- Verifier pass 3: `GO_FOR_REMOTE_CI` sul commit locale `cad0047f…`. La PR #37 ha materializzato lo stesso tree nel commit remoto `96cbaee6…`; il primo run RCCAD ha fallito fail-closed in `AFF-008` perché il commit TDD locale non esiste nel clone remoto. Remediation: l'evidence registra il commit di materializzazione remoto e il validator accetta soltanto l'ancestry locale verificabile oppure, esclusivamente in GitHub Actions, l'ancestry del parent remoto verificabile.
- Remote CI pass 2: supply-chain e layered mandatory gates `PASS`; il run RCCAD `33715519982` ha superato schema, manifest, evidence e acceptance test, poi ha fallito sul validator storico deliberatamente `planning-only`, che rifiuta correttamente ogni diff estraneo a `docs/development_plan/` e `reports/planning/`. Remediation circoscritta: il workflow RCCAD mantiene il runner autoritativo `--validate`/`--dry-run` e rimuove soltanto l'invocazione fuori contesto del validator planning-only; il finding baseline non viene riclassificato né occultato.
- Remote CI pass 3 sul commit `d4c54a876bfb3cc60531596982be04b283d20615`: `PASS` per supply-chain `33715707667`, layered mandatory gates `33715707617`, governance/validation closure `33715707574`, RCCAD methodology gates `33715707590` e autonomous delivery controls `33715707689`. Il sigillo documentale successivo deve ripetere gli stessi controlli sul proprio HEAD prima del merge.
- Evidence fence: `E1=0`, `E2=0`, zero global `Verified`; runtime, PoC and Production remain `NO-GO`.

## 2026-09-03 — OCOR-DEV-REM-0007-RCCAD

- Baseline autoritativa remota: `a09d1a6e573895e716b147c8046ea97b73b2e3a8`; la worktree locale usa il tree equivalente del merge DEC-210. Digest normativi `PASS`; harness locale e pytest locale `NOT_EXECUTED` per venv assente, senza installazioni o retry.
- Reconciliation: nessun nuovo task del DAG è ready perché `OCOR-DEV-0016/17/18/21` restano bloccati su servizi reali; le PR draft #26/#29/#31 sono divergenti. Selezionata soltanto #26, da supersedere con una portabilità RCCAD pulita.
- CHARACTERIZATION: il commit test-only remoto `133ac489141f1186650fc57f459298d482f3f18c` ha superato tutti i cinque workflow (`33716385268/289/292/299/286`) prima dell'aggiunta dei casi che espongono il difetto.
- RED: il commit test-only remoto `79d18cf76c771ca724fa7037a5d3f659addd2e77` ha prodotto 15 failure mirate: round-trip RFC 8785/Appendix B, safe-range binary64, assenza di `DigestProviderError`, errori non bounded e rifiuto errato di `2**53`. Fingerprint SHA-256 `2a136b5dcd53ec4bcb7455fa47c86d48b00bcd20cb72e681340bd5e3ed9772ce`.
- GREEN: applicati soltanto i tre file runtime della remediation già revisionata. Il commit remoto `d15324375dcb63d2cd024bfe1648f529a7683a8c` ha superato RCCAD e layered gates; i due portfolio legacy hanno esposto esclusivamente Node `v22.23.2` contro l'oracle obbligatorio `v20.20.2`.
- REFACTOR/CI: Node `20.20.2` è stato pinning anche nei due workflow legacy, senza cambiare i test. Il commit remoto `8a9a2280750282af156ebb3c026ca0730c53bb27` ha superato tutti i workflow `33716881688/607/556/600/636`.
- Independent verifier: `GO_FOR_EVIDENCE_SEAL`, zero `BLOCKER`, `HIGH` e `MEDIUM`; modello/effort `NOT_ATTESTABLE`. Il merge resta vietato fino al CI verde sull'HEAD del sigillo.
- Claim fence invariato: `E1=0`, `E2=0`, zero global `Verified`; G1 non è ripromosso, runtime conformance non è stabilita, PoC e Production restano `NO-GO`.

## 2026-09-03 — OCOR-DEV-REM-0008-RCCAD

- Baseline remota: `698590511d2a48f5f09083af47f75734ceacc750`; PR #29 divergente selezionata per supersessione dopo il merge qualificato di REM-0007. Digest normativi `PASS`; harness e pytest locali `NOT_EXECUTED` per venv/uv assenti.
- RED test-only `dde7e3e24dcaa5e68175763eebf9126b6df5bfb6`: cinque failure mirate per correlation ID schema-valid, tuple non-array e binding Proto non verificato dereferenziato.
- GREEN `ce717f113e7b736238df7cc7ce0d471e09fa6790`: tutti i cinque workflow `33723246471/584/620/467/447` `PASS`.
- Independent verifier: `GO_FOR_EVIDENCE_SEAL`, zero `BLOCKER`, `HIGH`, `MEDIUM`; scope esatto kernel+test, nessuna modifica a `inputs/`, ADD, LLD o contratti.
- Claim fence invariato: `E1=0`, `E2=0`, zero global `Verified`; runtime conformance, PoC e Production restano `NO-GO`.

## 2026-09-03 — OCOR-DEV-REM-0009-RCCAD

- Baseline remota: 5a5ca88a6ce2aeffe01ba8a35b43487dad810753, tree 974c5ba3 coincidente con la worktree locale; PR #31 divergente selezionata per supersessione dopo il merge qualificato di REM-0008.
- Digest normativi PASS; harness e pytest locali NOT_EXECUTED per .venv/uv assenti, senza installazioni o retry.
- RED test-only 9f215b8dd36bb9d83079098768b56f7231ff7f9d: collection failure mirata perché il port autorevole InMemoryLeaseState non era presente. Fingerprint SHA-256 ef1165dc3083f7e9f1ba9a6832a7425a2b6a5ed7bd293e1062952fc1c552777e.
- GREEN 5404f32c75c98bf1899d4caebf5dc0197228c988: tutti i cinque workflow 33737997879/940/911/908/959 PASS, inclusi full runtime e PostgreSQL reale pinned.
- Independent verifier: GO_FOR_EVIDENCE_SEAL, zero BLOCKER, HIGH, MEDIUM, LOW; scope esatto kernel+test, nessuna modifica a inputs/, ADD o LLD.
- Assurance boundary: consumo atomico e concorrenza sono qualificati solo process-local; restart durability, serializzazione multi-processo e co-transazione DeliveryAttempt restano NOT_ESTABLISHED.
- Claim fence invariato: E1=0, E2=0, zero global Verified; G1 non è promosso, runtime conformance non è stabilita, PoC e Production restano NO-GO.

## 2026-09-03 — RCCAD terminal reconciliation

- REM-0009 integrato dalla PR #40 con merge 6afa0d962580a039f1903797dc304eacc9fcaea8 dopo cinque gate verdi sul seal esatto 846c0966500cf210a929c572057831145cb60061; PR draft #31 chiusa senza merge.
- Riconciliazione GitHub: zero pull request aperte. Le PR divergenti #26, #29 e #31 sono state supersedute rispettivamente da #38, #39 e #40 con evidence seal e verifier puliti.
- Analisi del DAG: 19 task hanno evidenza content-addressed; restano 50 task. I soli task direttamente ready sono OCOR-DEV-0016, OCOR-DEV-0017, OCOR-DEV-0018 e OCOR-DEV-0021.
- Tutti i quattro task ready sono WAITING_EXTERNAL_SERVICE con test obbligatori NOT_EXECUTED: TerminusDB, TypeDB, Apache Jena/Fuseki, SPIFFE/SPIRE e OpenBao non sono disponibili come artefatti pinned approvati o endpoint autorizzati.
- Escludendo i quattro root blocker, il fixed point del DAG non contiene alcun altro task indipendente raggiungibile. Lo stato terminale è pertanto BLOCKED, non COMPLETE.
- Il runner autoritativo locale --status è NOT_EXECUTED perché jsonschema non è disponibile; il controllo non è stato ritentato. Il DAG è stato riconciliato in sola lettura dal backlog e dai manifesti.
- Minimal unblock: fornire i servizi reali approvati e riprendere da OCOR-DEV-0016. Nessuna tecnologia sostitutiva è autorizzata.
- Independent verifier terminale: GO_FOR_BLOCKED_STATE_MERGE, zero BLOCKER, HIGH, MEDIUM e LOW; modello/effort NOT_EXPOSED.
- Claim fence invariato: E1=0, E2=0, zero global Verified; G2 non è chiuso, runtime conformance non è stabilita, PoC e Production restano NO-GO.

## 2026-09-03 — CC-AUTONOMOUS-TOOLING-INFRASTRUCTURE-BOOTSTRAP / DEC-211

- Baseline remota autoritativa verificata con Git e GitHub:
  `d93e8870e975b2aeec715778f3c490ece0e0216f`. Il checkout obsoleto è preservato
  integralmente nel commit `b3960a93efd94100420c856e66c1bf035c3850d9` sul
  branch `archive/stale-reconciliation-20260903T152830Z`.
- `DEC-210` è integrata. La ricerca su ref e PR ha confermato `DEC-211` come primo
  identificativo libero; nessun file in `inputs/` è stato modificato.
- RED test-only commit `605504fe3fd9b2aa3153f703accb72c9f5c15916`:
  3 failure e 2 error attesi per policy, lock, strumenti, task e record assenti;
  fingerprint SHA-256 `01bd89685cc2c1af54984dc52546cbe1e30cc9879b19ce3d5604ce4be4c1a3e4`.
- Toolchain ripristinata con Python 3.12.11 e dipendenze locked; `ruff==0.13.1`
  installato in user space e registrato nel lock.
- Ambiente reale disposable avviato con 11 servizi pinned: TerminusDB, TypeDB,
  Apache Jena/Fuseki, OPA, Keycloak, SPIRE server/agent, OpenBao, PostgreSQL,
  Kafka e Qdrant. Tutti gli endpoint applicabili sono `READY`.
- Un token OpenBao disposable è comparso durante una diagnostica locale; è stato
  immediatamente ruotato e il container è stato ricreato. Nessun valore segreto è
  persistito nel repository o nell'evidence.
- GREEN locale: acceptance 10/10, RCCAD `AFF-001`–`AFF-010` static precheck PASS,
  planning validator 37 PASS e 2 controlli opzionali `NOT_EXECUTED`, harness
  documentale 14 PASS/0 FAIL/0 NOT_EXECUTED, lock schema PASS e service probe PASS.
- Reset distruttivo limitato al progetto e clean rebuild `PASS`; fault injection
  TypeDB `pause` rilevata fail-closed e ritorno a `READY` dopo `unpause` entro il
  retry budget. La regressione runtime completa con PostgreSQL reale è 512/512 PASS.
- Evidence fence invariato: `E1=0`, `E2=0`, runtime conformance
  `NOT_ESTABLISHED`, PoC e Production `NO-GO`. La readiness infrastrutturale non
  accetta automaticamente i quattro spike funzionali G2.
- Independent verifier pass 1: `NO-GO` con DEC211-B01/B02/B03, H01/H02/H03 e
  M01. Remediation: raw log RED/GREEN/REFACTOR content-addressed con comandi
  esatti; lock/schema strict e 10 test negativi; preflight byte/version per tutti
  i tool; Fuseki image-ID fail-closed; Actions pinned a commit; checkout e prova
  exact-head; allowlist change-set esatta; readiness esplicitamente preliminare.
- Evidence rerun qualificante sul commit `4a061dbc9497dfec10925db755dbd05954e9dcf5`
  `PASS`; manifest SHA-256
  `8ccb2f686d07f7af642fc9e064a7b3997288c179dc8e7f72bfdaec1230bc4bb2`.
- Independent verifier pass 3 `dec211_final_verify`: `GO`, zero `BLOCKER`,
  `HIGH` e `MEDIUM`; exact command/raw hash, strict operational schema, preflight,
  Fuseki ID, exact-file scope, immutable inputs e workflow exact-head verificati.

## 2026-09-12 — Riconciliazione autoritativa (Fase 0, CC-LANGUAGE-POLICY-AND-GAP-CLOSURE)

- Mandato esplicito del Product Owner del 2026-09-12: attiva la modalità di
  implementazione autorizzata (`DEC-210`) e il tooling autonomo (`DEC-211`), già
  entrambi integrati in `main`, per una nuova policy dei linguaggi e la chiusura di
  tre lacune note. Nessuna modifica a `inputs/`; nessun nuovo `DEC-*` allocato in
  questa iterazione, che è pura riconciliazione di stato.
- Allineamento esatto a `origin/main` `a8f44364d74c4e5953954f8cf4997032ccc68f05`;
  `sha256sum -c inputs/normative/SHA256SUMS` `PASS` 8/8; `uv sync --project
  ocor-runtime --frozen --extra test` `PASS`.
- `EXECUTION_STATE.json` e `MODEL_HANDOFF.json` dichiaravano ancora 19 task completati
  e `DEC-211` come ultima iterazione; l'evidenza sigillata in
  `reports/evidence/G2/MANIFEST.json` ne conta realmente 28
  (`OCOR-DEV-0015/0019/0020/0022/0023` e `OCOR-DEV-0070`–`0078`), integrati dai merge
  `88a525d3` (PR #42, `DEC-211`) e `PR #48`–`#53` (provisioning reale dei servizi).
  Dettaglio completo in `reports/development/RECONCILIATION_2026-09-12_STATE.md`.
- Stato locale del runner autoritativo ricostruito da zero (file gitignored, mai
  committato) con `scripts/ocor_autonomous_delivery.py --accept-evidence <task>
  --execute` per ciascuno dei 28 task sigillati: 28/28 `PASS`. Esito:
  `dependency_ready = ["OCOR-DEV-0079"]`, `external_blockers = []`.
- I quattro spike `OCOR-DEV-0016/0017/0018/0021` non attendono più un servizio
  esterno: `OCOR-DEV-0073`–`0078` hanno qualificato provisioning reale per
  TerminusDB, TypeDB, Fuseki, OPA/Keycloak, SPIFFE/SPIRE e OpenBao. Restano tuttavia
  sequenziati dietro altri task `PENDING` per ordinaria dipendenza di backlog
  (incluso `OCOR-DEV-0084` per `OCOR-DEV-0016`), non per blocco esterno.
- `reports/development/TERMINAL_BLOCKED_REPORT.json` e
  `reports/evidence/G2/blockers/MANIFEST.json` sono marcati `SUPERSEDED` con motivo
  e commit di superamento, senza essere cancellati.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`. Nessun
  requisito promosso, nessuna capability differita attivata.
- Prossima azione: Fase 1 del mandato — allocare il prossimo `DEC-*` libero e
  autorare `docs/development_methodology/OCOR_LANGUAGE_POLICY.md` con
  `scripts/validate_language_policy.py` (RED poi GREEN), cablato in CI.

## 2026-09-12 — Chiusura Fase 1 (CC-LANGUAGE-POLICY-AND-GAP-CLOSURE / DEC-212)

- PR #54 (Fase 0, riconciliazione di stato) integrata: merge
  `b698f6b847f1afcd429e2dd7b7d72ab01d425a02`. Tutti i 12 check CI verdi
  sull'HEAD esatto; un check (`tooling-policy`) inizialmente rosso per
  allowlist troppo stretta in `scripts/validate_ocor_development_plan.py`,
  corretto alla radice estendendo `extension_paths` con i percorsi di questo
  change set, non aggirato.
- PR #55 (Fase 1, `DEC-212`) integrata: merge
  `7c7f9b5b6a5135aa2583445697f54e9ff1dfcf3e`. Allocato `DEC-212` dopo verifica
  in sola lettura che nessun ref/tag/PR/registro lo referenziasse già (ultimo
  libero dopo `DEC-211`). Autorato
  `docs/development_methodology/OCOR_LANGUAGE_POLICY.md` (tabella normativa
  per kernel, C1-C8, harness/validatori e spike G2, qualificatori `deploy/`,
  generatore di contratti, SDK generati, adapter, policy OPA, infra/CI, formati
  dichiarativi) e `scripts/validate_language_policy.py` (gate fail-closed).
  RED su stub pre-implementazione, GREEN sull'implementazione reale,
  REFACTOR dopo pulizia `ruff`. Durante RED/GREEN è emerso che `spikes/**`
  (oracoli G2) mancava dalla bozza iniziale della policy: aggiunto prima di
  dichiarare GREEN. Gate cablato nei tre workflow che già eseguono validazione
  di processo (`ocor-tooling-bootstrap`, `ocor-rccad`, `ocor-delivery-activation`).
- `DEC-212` non supersede alcuna decisione precedente e lascia invariato il
  profilo SDK di `DEC-075`/`FR-047`/`FR-048` (Python e TypeScript generati,
  Rust differito): la distinzione fra i due piani è esplicita nel documento.
- Un job CI (`rccad-methodology`) è fallito una volta per un flake di rete
  transitorio verso Docker Hub durante il pull dell'immagine Kafka pinnata
  (`confluentinc/cp-kafka:7.6.0`), non correlato al diff; il rerun dello stesso
  commit è risultato verde.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`.
- Prossima azione: Fase 2.1 del mandato — mypy strict su `ocor-runtime/src` e
  `scripts/`, configurazione `ruff` per l'intero repository, entrambi pinnati
  alla patch, cablati come job CI bloccanti.

## 2026-09-12 — Fase 1B: tre correzioni dalla verifica indipendente (§4 del mandato)

- Nuovo mandato esplicito del Product Owner del 2026-09-12 (CC-OCOR-DELIVERY-COMPLETION):
  riconciliato HEAD reale `50c3bbbe41e4c9cbc1a7112847decd37e80405df` (`origin/main`,
  PR #56), coincidente con quanto il mandato assumeva. Nessuna divergenza da
  riconciliare oltre a quanto già registrato il 2026-09-12 in Fase 0/1.
- §4.1: `docs/development_methodology/OCOR_LANGUAGE_POLICY.md` §3 ancorava le
  quattro soglie di migrazione a un "budget ipotetico p95 < 50 ms" attribuito a
  `NFR-076` (che classifica solo L0/L1/L2, senza fissare alcun numero) e a `OI-024`.
  Verifica sui registri normativi (`inputs/normative/OCOR_Registers_v0.9.md`,
  `OCOR_Requirement_Register_v0.9.md`): `OI-024` governa le soglie di
  rischio/costo per l'autorità dual-control su azioni critiche
  (`DEC-131`/`FR-136`/`FR-137`), non le soglie di latenza; l'open item corretto
  per soglie numeriche di accettazione è `OI-008`, con il processo di
  fissazione descritto in `ASM-010`/`DEC-170`/`NFR-080`. Corretto il riferimento
  a `OI-008` (non a `OI-024`, mai citato come fosse quello giusto), dichiarato
  esplicitamente il valore come ipotesi di lavoro non approvata, e ribadito che
  `NFR-080` impone comunque classe di servizio/percentile/finestra/workload/
  ambiente/comportamento al superamento per ogni SLO. Non chiuso `OI-008`, non
  creato alcun nuovo identificativo di baseline.
- §4.2: `EXECUTION_STATE.json.latest_ci_evidence` era `PENDING_EXACT_HEAD_CI`
  con `candidate_commit: null` nonostante tre PR mergiate con check verdi.
  Popolato con i dati reali via `gh pr checks 56`: head `de3bcac74959caa71d7c0d647abc5578ea0d4bfb`,
  12/12 check `pass` su 6 run id GitHub Actions distinti
  (`34701203516/523/528/530/535/562`), merge `50c3bbbe41e4c9cbc1a7112847decd37e80405df`.
  `baseline_commit` e `active_iteration` risincronizzati a HEAD e al branch di
  questa iterazione in entrambi `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`
  dopo che `scripts/validate_rccad.py` ha rilevato `RCCAD-STATE-HANDOFF-DRIFT`
  fra i due file.
- §4.3: `infra/toolchain.lock.json` non conteneva alcuna voce TypeScript.
  Verificato prima sul registry ufficiale npm che `typescript@7.0.2` esiste
  davvero ed è il dist-tag `latest` corrente (non un'assunzione del mandato);
  installato in un ambiente isolato (`npm install typescript@7.0.2`), confermato
  `tsc --version` → `Version 7.0.2` e calcolato l'hash SHA-256 reale
  dell'eseguibile risolto (`node_modules/typescript/bin/tsc`,
  `2219f428a7e55aaf1f7ad85b9b0f0cf5078aeb76ccc9a7c6036c92d48f492ffd`), verificato
  anche il checksum SHA-1 del tarball npm contro quello pubblicato dal registry
  prima di fidarsi del contenuto. Aggiunta una voce `provider: host` conforme a
  `infra/toolchain.lock.schema.json`, stesso pattern di `node`/`ruff`.
- Gate locali: `sha256sum -c inputs/normative/SHA256SUMS` `PASS` 8/8;
  `scripts/validate_language_policy.py` `PASS`; `scripts/validate_rccad.py`
  `PASS_LOCAL_PRECHECK` (0 finding dopo le due correzioni sopra);
  `scripts/validate_ocor_change_scope.py --base origin/main` `PASS`, 4 percorsi
  cambiati, superfici immutabili intatte, ledger dei task stabile;
  `scripts/validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` `PASS` 37/2/0; `scripts/verify.py --json` `PASS` 11/0,
  3 `NOT_EXECUTED` per dipendenze Python opzionali assenti in questa shell
  locale (`openapi-spec-validator`, `grpcio-tools`, `rdflib`) — `reports/verify_report.json`
  lasciato intatto (non sovrascritto con un risultato localmente degradato) perché
  questo change set non tocca alcun file che quel referto copre.
  `mypy`/`tsc --strict`/`ruff` repo-wide/regressione pytest completa: `NOT_APPLICABLE`
  (nessun sorgente Python o TypeScript toccato) e comunque `NOT_EXECUTED` in
  questa shell perché la toolchain pinnata byte-per-byte (`ruff==0.13.1`,
  `uv==0.12.5`, `python==3.12.11` con hash esatto) non è quella osservata
  localmente (`ruff 0.16.1`, `uv 0.5.9`); il gate qualificante resta la CI
  sull'exact-head al push, come per le tre PR precedenti.
- Evidenza sigillata: `reports/evidence/local-gates/phase1b-independent-review-corrections-20260912.json`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`. Nessun
  `OI-*`/`ASM-*`/`RSK-*` chiuso, nessuna capability differita attivata.
- Prossima azione: aprire la PR di questa correzione, attendere CI verde
  sull'HEAD esatto, merge, verifica SHA post-merge, poi Fase 2.1 del mandato —
  mypy strict su `ocor-runtime/src` e `scripts/`, configurazione `ruff` per
  l'intero repository, entrambi pinnati alla patch, cablati come job CI
  bloccanti.

## 2026-09-12 — Chiusura Fase 1B

- PR #57 aperta e integrata: merge `3911228e7b657bf1bd2b1fc17f49fcad9bef3e5c`.
  Il primo push (`1fddb4f`) ha fatto fallire il check `tooling-policy` per lo
  stesso motivo già osservato in Fase 0/PR #54: il nuovo file di evidenza
  `reports/evidence/local-gates/phase1b-independent-review-corrections-20260912.json`
  non era ancora nell'allowlist `extension_paths` di
  `scripts/validate_ocor_development_plan.py`. Corretto alla radice
  (allowlist estesa, self-hash di `OCOR_PLAN_RUN_STATE.json` fatto assestare
  con una seconda esecuzione locale prima del push), non aggirato. Secondo
  push (`040275f`): 12/12 check verdi sull'HEAD esatto
  (run id `34707732916/919/927/931/939/980`).
- Verifica pre-merge: `origin/main` invariato a `50c3bbbe` dal momento della
  creazione del branch; `gh pr view 57` → `mergeStateStatus: CLEAN`,
  `mergeable: MERGEABLE`. Nessun rebase necessario.
- Verifica post-merge: SHA di `origin/main` = `3911228e7b657bf1bd2b1fc17f49fcad9bef3e5c`,
  coincidente con il merge commit riportato da GitHub.
- `EXECUTION_STATE.json` e `MODEL_HANDOFF.json` risincronizzati al nuovo HEAD;
  `latest_ci_evidence` aggiornato ai run reali del secondo push.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`.
- Prossima azione: Fase 2.1 del mandato — mypy strict su `ocor-runtime/src` e
  `scripts/`, configurazione `ruff` per l'intero repository, entrambi pinnati
  alla patch, cablati come job CI bloccanti. Task del backlog ordinario
  indipendente dal mandato, sempre dependency-ready: `OCOR-DEV-0079`.

## 2026-09-12 — Fase 2.1: gate bloccante mypy strict + ruff repo-wide

- Nuovo `pyproject.toml` alla radice del repository con `[tool.mypy]`
  (`strict = true`, `files = ["ocor-runtime/src", "scripts"]`) e `[tool.ruff]`
  (`extend-exclude` per i cinque file frozen/content-addressed sotto). `mypy`
  pinnato alla patch (`mypy==2.3.1`) in un nuovo gruppo `lint` di
  `ocor-runtime/pyproject.toml`, insieme a `types-jsonschema==4.26.0.20260518`
  e `types-PyYAML==6.0.12.20260906`: tutte e tre le versioni verificate reali
  sul registry PyPI ufficiale prima del pin, non assunte. `ocor-runtime/uv.lock`
  rigenerato con `uv lock`.
- Prova iniziale `mypy --strict ocor-runtime/src scripts`: 43 errori in 10 file,
  ridotti a 34 dopo l'installazione degli stub mancanti. Corretti con
  annotazioni di tipo precise, cast puntuali o rinomina di variabili in 9 file
  (`ocor_runtime/c3_store.py`, `c4_marking.py`, `c8_agent.py`,
  `scripts/verify.py`, `scripts/ocor_autonomous_delivery.py`,
  `scripts/validate_language_policy.py`, `scripts/validate_rccad.py`,
  `ocor-runtime/tests/backend_assumptions/test_ba01_atomic_outbox.py`,
  `ocor-runtime/tests/schemas/test_schema_integrity.py`); nessun comportamento
  a runtime modificato. Due commenti `# type: ignore` risultati non più
  necessari (`c4_marking.py`, `c8_agent.py`) sono stati rimossi solo dopo aver
  verificato che il comportamento sottostante restava invariato.
  `grpc_tools`/`grpcio-tools` non pubblica stub né `py.typed`: unica eccezione
  concessa, un override puntuale per quel solo modulo di terze parti, non un
  ignore generalizzato del codice proprio.
- Prova iniziale `ruff check --isolated .` (regola di default E4/E7/E9/F, come
  già in uso): 125 errori. Corretti 11 in file attivi non sigillati (import
  inutilizzati, una `lambda` sostituita con `def`, `E401`/`E741` in
  `scripts/verify.py`, una variabile inutilizzata in
  `reports/tests/test_rccad_methodology.py`).
- **Audit dell'evidenza sigillata prima di ogni modifica**: analizzati
  programmaticamente tutti i campi `inputs`/`artifact_hashes` di
  `reports/evidence/**/*.json` e `reports/development/*.json` per ogni file
  `.py` nello scope del nuovo gate. Trovate e **annullate prima del commit**
  tre modifiche che avrebbero invalidato evidenza già accettata:
  - `scripts/preflight_environment.py` è input sigillato di `OCOR-DEV-0072`
    (`reports/evidence/G2/OCOR-DEV-0072.json`) e dell'evidenza ambientale
    `DEC-211` (`reports/development/environment-evidence-dec-211.json`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0004.py` e `test_ocor_dev_0015.py`
    sono input sigillati rispettivamente di `OCOR-DEV-0004`
    (`reports/evidence/G0/OCOR-DEV-0004.json`) e `OCOR-DEV-0015`
    (`reports/evidence/G2/OCOR-DEV-0015.json`).
  Tutti e tre sono stati esclusi dal gate nuovo con motivazione puntuale in
  linea nella configurazione, invece di essere modificati.
- **Scoperta e escalation** (non bloccante per questa fase): rieseguire
  `scripts/build_ocor_development_plan.py` per far assestare il proprio
  self-hash in `reports/planning/OCOR_PLAN_RUN_STATE.json` ha **cancellato
  silenziosamente `OCOR-DEV-0070`–`0084`** dal backlog rigenerato, perché la
  lista `TASK_SPECS` dello script non è mai stata aggiornata quando quei 15
  task sono stati aggiunti al backlog reale. Nessuno script referenzia
  `OCOR-DEV-0070` o superiore, confermando che non esiste un secondo
  generatore che li copra. La rigenerazione è stata scartata (`git checkout
  --`) prima di qualunque commit; il file è escluso anche dal nuovo gate
  mypy (già pulito per `ruff`). Escalation registrata in
  `reports/evidence/local-gates/phase2-1-mypy-ruff-gates-20260912.json`
  (`PHASE2-4-BACKLOG-GENERATOR-DRIFT`): va risolta prima che la Fase 2.4
  rigeneri il DAG, non prima.
- Cinque file esclusi dal nuovo gate `ruff` con motivazione in linea nel
  `pyproject.toml`: i tre artefatti frozen della review ADD v1.1/v1.2
  (`test_v12_candidate.py` e `test_v12_semantics.py`, content-addressed in
  `reports/OCOR_ADD_v1.2_SHA256SUMS`; `test_schema_conformance.py`, sibling
  v1.1 dello stesso corpus storico) e i due file di evidenza sigillata sopra
  (`test_ocor_dev_0004.py`, `test_ocor_dev_0015.py`).
  `scripts/preflight_environment.py` e `scripts/build_ocor_development_plan.py`
  erano già puliti per `ruff`, quindi esclusi solo dal gate `mypy`.
  Nessuna delle esclusioni promuove evidenza o requisiti.
- Nuovo job bloccante `type-and-lint-gate` in
  `.github/workflows/ocor-tooling-bootstrap.yml`: stesso pattern di checkout
  exact-head, Python 3.12.11 + uv 0.12.5 pinnati, `uv sync --extra test --extra
  lint`, poi `ocor-runtime/.venv/bin/python -m mypy` e `ruff check .`.
- Gate locali: `sha256sum -c` `PASS` 8/8; `ocor-runtime/.venv/bin/python -m
  mypy` `PASS` 44/44 file; `ruff check .` (0.13.1 pinnato) `PASS`;
  `validate_rccad.py` `PASS_LOCAL_PRECHECK` 0 finding; `validate_ocor_change_scope.py`
  `PASS` 14 percorsi; `validate_ocor_development_plan.py --authorized-extension`
  `PASS` 37/2/0 dopo self-hash settle; `validate_language_policy.py` `PASS`;
  regressione pytest completa su `ocor-runtime/tests/` (stessa invocazione
  della CI) `498 passed, 5 skipped, 10 errors` — gli errori sono lo stesso gap
  pre-esistente `OCOR_LIVE_POSTGRES_DSN` di `test_ocor_dev_0015.py` osservato
  in ogni iterazione precedente, non una regressione; `reports/verify_report.json`
  bit-identico alla baseline committata dopo un run con l'ambiente reale
  completo.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`. Nessuna
  evidenza sigillata invalidata; nessun requisito promosso.
- Prossima azione: aprire la PR, attendere CI verde sull'HEAD esatto (in
  particolare il nuovo job `type-and-lint-gate`), merge, verifica SHA
  post-merge, poi Fase 2.2 del mandato — pin dell'interprete alla patch.

## 2026-09-12 — Chiusura Fase 2.1

- PR #59 aperta e integrata al primo tentativo: merge
  `1cfa0a787ee620e462adfd0d25378f752c74af28`. Tutti i 12 check verdi
  sull'HEAD esatto `5123650e` al primo push, incluso il nuovo job
  `type-and-lint-gate` (run id `34710650062/063/066/069/077/090`).
- Verifica pre-merge: `mergeStateStatus: CLEAN`, `mergeable: MERGEABLE`.
  Verifica post-merge: SHA di `origin/main` coincidente con il merge commit
  riportato da GitHub.
- `EXECUTION_STATE.json` e `MODEL_HANDOFF.json` risincronizzati al nuovo HEAD;
  `latest_ci_evidence` aggiornato ai run reali.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`.
- Prossima azione: Fase 2.2 del mandato — pin dell'interprete alla patch in
  `requires-python`, `uv.lock`, `.python-version` e in tutti i workflow, più
  un test che fallisca se l'interprete in esecuzione diverge dal pin.

## 2026-09-12 — Fase 2.2: pin dell'interprete alla patch

- `ocor-runtime/pyproject.toml`: `requires-python` da `>=3.11` a `==3.12.11`.
  Nuovo `ocor-runtime/.python-version` con `3.12.11`. Header di
  `ocor-runtime/uv.lock` allineato allo stesso valore. Dodici occorrenze di
  `python-version: "3.12"` (pin di sola minor) corrette a `"3.12.11"` in
  cinque workflow (`ocor-rccad`, `ocor-poc-ci` ×6, `ocor-supply-chain`,
  `ocor-delivery-activation`, `ocor-validation-closure`);
  `ocor-tooling-bootstrap.yml` era già esatto. Nuovo
  `ocor-runtime/tests/test_interpreter_pin.py`: fallisce chiuso se
  l'interprete in esecuzione diverge dal pin, letto da `.python-version`
  invece di essere ripetuto in chiaro nel test.
- **Limite di verifica locale, dichiarato esplicitamente**: questo sandbox
  non possiede l'interprete esatto `3.12.11` (né come build standalone di
  `uv`, né altrove) e non può scaricarlo. Di conseguenza `uv lock`, `uv sync
  --frozen` e `uv run` rifiutano categoricamente di eseguire non appena
  `requires-python` diventa `==3.12.11`. Tutta la verifica locale ha quindi
  invocato l'interprete della venv esistente direttamente
  (`ocor-runtime/.venv/bin/python`), bypassando il wrapper di `uv`. La riga
  `requires-python` nell'header di `uv.lock` è stata corretta a mano come
  eccezione documentata — è una copia letterale del campo già dichiarato in
  `pyproject.toml`, non una decisione di risoluzione delle dipendenze; nessuna
  versione di pacchetto o `resolution-markers` è stata toccata a mano.
- Confermato che il pin non è fittizio: `infra/toolchain.lock.json` fissa già
  Python `3.12.11` con hash di integrità reale, e ogni run CI di questa
  sessione (PR #54–60) ha già usato `actions/setup-python` con `"3.12.11"`
  con successo (il dump d'ambiente di un job precedente mostrava
  `pythonLocation: /opt/hostedtoolcache/Python/3.12.11/x64`). Il gate
  qualificante reale per questa modifica resta quindi la CI, non questo
  sandbox.
- Regressione pytest completa (invocazione diretta della venv):
  `2 failed, 499 passed, 5 skipped, 10 errors`. Le due nuove failure
  condividono la stessa unica causa già dichiarata sopra, non un difetto
  logico: `test_interpreter_pin.py::test_running_interpreter_matches_the_pin`
  fallisce esattamente come previsto (`3.12.14 != 3.12.11`);
  `test_ocor_dev_0002.py::test_two_clean_environments_resolve_identical_lock_and_image_digests`
  fallisce nel suo stesso sottoprocesso `uv lock --check` con l'identico
  errore di interprete assente. I 10 errori pre-esistenti restano il gap
  `OCOR_LIVE_POSTGRES_DSN` già dichiarato. Entrambe le nuove failure sono
  attese verdi in CI.
- Audit di sicurezza prima della modifica: `ocor-runtime/pyproject.toml` e
  `ocor-runtime/uv.lock` sono già referenziati come input in 15+ evidenze di
  task precedenti (`OCOR-DEV-0002`..`0071`), ma come manifest di progetto
  condivisi e in evoluzione continua — non il deliverable unico e sigillato
  di un singolo task — esattamente come confermato dal precedente già
  accettato in Fase 2.1 (PR #59, che ha già modificato entrambi con successo).
  Stesso ragionamento per `ocor-poc-ci.yml`/`ocor-supply-chain.yml` rispetto
  al precedente `ocor-tooling-bootstrap.yml` già modificato in Fase 2.1.
  Nessun file di evidenza sigillata a task singolo è stato toccato.
- Gate locali: `sha256sum -c` `PASS` 8/8; `ocor-runtime/.venv/bin/python -m
  mypy` `PASS` 44/44; `ruff check .` `PASS`; `verify.py --json` `PASS` 14/0/0;
  `validate_rccad.py` `PASS_LOCAL_PRECHECK` 0 finding; `validate_language_policy.py`
  `PASS`; `validate_ocor_change_scope.py` `PASS` 9 percorsi;
  `validate_ocor_development_plan.py --authorized-extension` `PASS` 37/2/0
  dopo self-hash settle; sintassi YAML valida su tutti i workflow.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`.
- Prossima azione: aprire la PR, seguire la CI con particolare attenzione al
  primo passo `uv` di ogni workflow (rischio di risoluzione dell'interprete
  dichiarato sopra); se rosso, correggere alla radice (mai allentare il pin);
  se verde, merge, verifica SHA post-merge, poi Fase 2.3 — SDK TypeScript
  reale e suite di conformità cross-SDK.

## 2026-09-12 — Chiusura Fase 2.2

- PR #61 aperta e integrata: merge `47ca9017c8f8f5f89d5155daea13f05314f1025f`.
  **Il rischio dichiarato sulla risoluzione dell'interprete non si è
  concretizzato**: `type-and-lint-gate`, `unit`, `integration-postgresql` e
  `validation-closure` (tutti basati su `uv`) sono passati puliti sul pin
  esatto `3.12.11` già al primo push, confermando che l'interprete fornito
  su `PATH` da `actions/setup-python` soddisfa il vincolo `requires-python`
  esatto senza bisogno di download da parte di `uv`.
  Il primo push è comunque fallito su `tooling-policy`, ma per una causa
  diversa e già nota: un self-hash di `scripts/validate_ocor_development_plan.py`
  non assestato dopo una terza modifica al file nella stessa iterazione (le
  prime due erano state assestate correttamente, la terza — l'aggiunta del
  percorso di evidenza Fase 2.2 — no). Corretto e ripushato (`7b97e96`):
  12/12 check verdi.
- Verifica pre-merge: `mergeStateStatus: CLEAN`. Verifica post-merge: SHA di
  `origin/main` coincidente con il merge commit.
- `EXECUTION_STATE.json` e `MODEL_HANDOFF.json` risincronizzati; `latest_ci_evidence`
  aggiornato ai run reali.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`.
- Prossima azione: Fase 2.3 del mandato — SDK TypeScript reale sotto
  `ocor-runtime/sdk/typescript`, generato dal generatore esistente, mai
  scritto a mano; `tsconfig` strict; compilazione `tsc` in CI; suite di
  conformance cross-SDK `NFR-022` su fixture condivise fra SDK Python, SDK
  TypeScript e descrittore MCP.
## 2026-09-12 — Fase 2.3: SDK TypeScript reale + remediation OCOR-DEV-REM-0010

- Nuovo `ocor-runtime/sdk/typescript/`: `package.json` (`typescript==7.0.2`,
  `@types/node==20.19.43`, entrambe verificate reali sul registry ufficiale),
  `tsconfig.json` (`strict: true` più `noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes`, `noUnusedLocals/Parameters`), `src/errors.ts`
  ed `src/canonical.ts` (kernel di supporto scritto a mano — la stessa
  distinzione che il runtime Python traccia fra il proprio `canonical.py`
  scritto a mano e `ocor_contracts.py` generato — porting di
  `ocor_runtime.canonical`/`errors.py` che sfrutta il fatto che
  `String(number)` e l'ordinamento di default delle stringhe in ECMAScript
  **sono già** l'algoritmo che RFC 8785 richiede, invece di re-derivarli come
  fa la porta Python), `src/generated/ocor_contracts.ts` (generato dal
  generatore esistente, mai scritto a mano — bit-identico a una sua
  esecuzione fresca, verificato meccanicamente da entrambe le nuove suite).
- **Scoperta un difetto reale e non rilevato in precedenza**: la prima vera
  compilazione `tsc --strict` dell'output del generatore (mai eseguita
  prima — la suite sigillata `test_ocor_dev_0010.py` verifica solo che la
  riga di dichiarazione di ogni modello sia presente, mai che il file nel
  suo insieme risolva o compili) ha prodotto 19 errori `TS2304: Cannot find
  name` distinti. La risoluzione dei `$ref` in
  `ocor-runtime/tools/generate_contracts.py` prendeva l'ultimo segmento del
  percorso senza conoscenza del prefisso `Gateway`/`Memory` che `_models()`
  applica ai record oggetto di origine OpenAPI, e non gestiva affatto i
  `$ref` verso componenti non-oggetto (una stringa digest SHA-256, un array
  `Refs`/`NonEmptyRefs`, un alias `GovernedContext` che inoltra a un intero
  documento JSON Schema esterno). Raw log sigillato con fingerprint SHA-256
  in `reports/tests/evidence/rem_generate_contracts_refs/red.log`.
- **Remediation OCOR-DEV-REM-0010**: `ocor-runtime/tools/generate_contracts.py`
  è input sigillato di `OCOR-DEV-0010`
  (`reports/evidence/G1/OCOR-DEV-0010.json`), così come la sua suite
  `test_ocor_dev_0010.py`. Corretta la sola risoluzione dei riferimenti
  (nuova `_build_reference_index()`), aggiornati i `PINNED_GENERATED_HASHES`
  al nuovo output corretto; l'inventario dei modelli (54, stessi nomi) resta
  invariato. La suite sigillata `test_ocor_dev_0010.py` è stata lasciata
  **completamente non modificata** e riverificata verde 15/15 contro il
  generatore corretto, dimostrando che la correzione è compatibile con il
  significato storico dell'evidenza sigillata, non lo invalida. Nuova suite
  `reports/tests/test_generate_contracts_reference_resolution.py` (13 test):
  fingerprint del log RED, verifica che ogni `$ref` del set di contratti
  pinnati risolva ora a un modello dichiarato o a un primitivo riconosciuto,
  controlli puntuali sui 9 casi precedentemente rotti, verifica che
  l'inventario dei modelli sia invariato, e (quando `tsc` è su `PATH`)
  ricompila da zero l'intero SDK committato.
- Nuova suite `ocor-runtime/tests/sdk/test_typescript_sdk_conformance.py`
  (NFR-022, 4 test): identità byte-per-byte del testo canonico e del digest
  SHA-256 fra Python e TypeScript su 23 fixture (ordinamento delle chiavi,
  escaping di stringhe unicode/di controllo, confine `MAX_SAFE_INTEGER`,
  soglie di notazione scientifica ±21/-7); identità del modello di errore
  (codice `CANONICALIZATION_INVALID`) su fixture con surrogati UTF-16 non
  accoppiati; parità dei campi generati fra una generazione Python fresca e
  l'SDK TypeScript committato; identità del binding di idempotenza (la
  semantica di idempotenza del descrittore MCP lega una richiesta al proprio
  digest canonico: richieste con campi riordinati producono lo stesso
  digest in entrambi gli SDK, un campo cambiato no). La suite pilota l'SDK
  TypeScript compilato come sottoprocesso, lo stesso schema con cui
  `DEC-166`/`REM-0007` usa già Node.js come oracolo cross-language per i
  valori limite dell'implementazione Python.
- Due nuovi controlli di skip condizionale (`tsc`/`node` non disponibili in
  locale, sempre disponibili in CI) registrati in
  `reports/development/METHOD_COMPLIANCE.json.test_exceptions`
  (`TEST-INFRA-002`, `TEST-INFRA-003`), stesso schema del guard PostgreSQL
  già esistente (`TEST-INFRA-001`); `validate_rccad.py` falliva
  `RCCAD-UNJUSTIFIED-SKIP` prima della registrazione.
- Nuovo step `tsc --strict` e le due nuove suite pytest cablati nel job
  `type-and-lint-gate` di `.github/workflows/ocor-tooling-bootstrap.yml`
  (`actions/setup-node@v4`, stesso pin `20.20.2` già in uso altrove nel
  repository).
- Gate locali: `sha256sum -c` `PASS` 8/8; `npm run build` da stato pulito
  (`rm -rf node_modules dist`) `PASS` zero errori; le due nuove suite pytest
  `PASS` 17/17 contro l'SDK ricompilato da zero; `ocor-runtime/.venv/bin/python
  -m mypy` `PASS` 44/44 (invariato, `ocor-runtime/tools/` è fuori scope);
  `ruff check .` `PASS`; `validate_rccad.py` `PASS_LOCAL_PRECHECK` 0 finding
  dopo la registrazione degli skip; `validate_language_policy.py` `PASS`;
  `validate_ocor_change_scope.py` `PASS` 11 percorsi;
  `validate_ocor_development_plan.py --authorized-extension` `PASS` 37/2/0
  dopo self-hash settle; regressione pytest completa `2 failed, 516 passed,
  5 skipped, 10 errors` — le due failure e i dieci errori sono
  esclusivamente i gap sandbox già dichiarati nelle Fasi 2.2 e precedenti
  (interprete `3.12.11` esatto assente, PostgreSQL live assente), non una
  regressione.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`.
  Nessuna evidenza sigillata invalidata; profilo SDK `DEC-075`/`FR-047`/`FR-048`
  invariato.
- Prossima azione: aprire la PR, attendere CI verde sull'HEAD esatto (in
  particolare i nuovi step `tsc`/conformance nel job `type-and-lint-gate`),
  merge, verifica SHA post-merge, poi Fase 2.4 del mandato — prima risolvere
  l'escalation `PHASE2-4-BACKLOG-GENERATOR-DRIFT`, poi correggere
  l'allocazione di `FR-047`, aggiungere i task mancanti al backlog e
  rigenerare il DAG.


## 2026-09-12 — Chiusura Fase 2.3

- PR #63 aperta e integrata al primo tentativo: merge
  `b4510123dee21c054876ecca97b02d33b971318a`. Tutti i 12 check verdi
  sull'HEAD esatto `5428ab37` al primo push, incluso il nuovo step `tsc` e
  le due nuove suite pytest nel job `type-and-lint-gate`.
- Verifica pre-merge: `mergeStateStatus: CLEAN`. Verifica post-merge: SHA di
  `origin/main` coincidente con il merge commit.
- `EXECUTION_STATE.json` e `MODEL_HANDOFF.json` risincronizzati; `latest_ci_evidence`
  aggiornato ai run reali.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`.
- Prossima azione: Fase 2.4 del mandato. Prima risolvere l'escalation
  `PHASE2-4-BACKLOG-GENERATOR-DRIFT` (riconciliare `TASK_SPECS` del
  generatore con `OCOR-DEV-0070`–`0084` e verificare che una rigenerazione
  riproduca l'84-task backlog reale senza perdite), poi correggere
  l'allocazione di `FR-047` in `OCOR_TRACEABILITY_PLAN.csv`, aggiungere i
  task mancanti al backlog e rigenerare il DAG. Nessuna promozione a
  Verified.

## 2026-09-12 — Fase 2.4 (parziale): correzione allocazione FR-047

- Confermata la denuncia esatta del mandato: `OCOR_TRACEABILITY_PLAN.csv`
  allocava `FR-047` ("SDK e tool MCP generati" — il sistema DEVE generare SDK
  Python e TypeScript e contratti MCP tipizzati) a `OCOR-DEV-0047`
  ("Implement C8 tool boundary sandbox budgets and kill switch", WS-09, G4)
  — un task sul sandbox di invocazione tool dell'agent kernel, senza alcuna
  relazione con la generazione di SDK. `OCOR-DEV-0047.requirement_ids`
  raggruppa una ventina di requisiti includendo `FR-047`, quasi certamente
  per uno scambio numero-task/numero-requisito (047 con 047) piuttosto che
  per una relazione semantica reale.
- Identificato `OCOR-DEV-0010` ("Materialize contract-first SDK boundaries
  and drift checks", WS-01, G1) come il task corretto: è quello che possiede
  `ocor-runtime/tools/generate_contracts.py`, già accettato
  (`completed_evidence_tasks`), ed esteso proprio in questa sessione (Fase
  2.3) con l'SDK TypeScript reale e la suite di conformance cross-SDK che il
  criterio di accettazione di `FR-047` nomina esplicitamente ("lo stesso
  mission scenario è invocabile da entrambi gli SDK e tramite MCP").
- Corretto `docs/development_plan/OCOR_TRACEABILITY_PLAN.csv`: riga `FR-047`
  con `owning_workstream` `WS-09`→`WS-01`, `implementation_task`
  `OCOR-DEV-0047`→`OCOR-DEV-0010`, `qualifying_test`/`required_backend`/
  `expected_evidence` estesi per nominare la suite reale e l'evidenza
  sigillata di `OCOR-DEV-0010`; `verification_task` (`OCOR-DEV-0065`, prova
  di integrazione a mission-thread completo) e `target_gate`/
  `current_baseline_status` lasciati invariati perché ancora corretti.
  Aggiornati coerentemente i due `requirement_ids` nel backlog (rimosso
  `FR-047` da `OCOR-DEV-0047`, aggiunto a `OCOR-DEV-0010`) — diff di sole 4
  righe, nessuna riformattazione incidentale. Nessun task nuovo aggiunto:
  è una pura riallocazione a un task esistente e già corretto. Nessuna
  `hard_dependencies` è cambiata, quindi nessuna rigenerazione del DAG era
  necessaria né è stata eseguita.
- `reports/planning/OCOR_PLAN_RUN_STATE.json.artifact_hashes` per i due file
  di pianificazione toccati aggiornato a mano (calcolo diretto dello
  sha256, non una decisione di risoluzione) come eccezione documentata: la
  sola via sanzionata (rieseguire `scripts/build_ocor_development_plan.py`)
  resta non sicura finché l'escalation `PHASE2-4-BACKLOG-GENERATOR-DRIFT`
  (`TASK_SPECS` privo di `OCOR-DEV-0070`–`0084`) non è risolta — non
  necessaria per QUESTA correzione, perché nessuna rigenerazione è stata
  eseguita.
- Gate locali: `sha256sum -c` `PASS` 8/8; `validate_ocor_development_plan.py
  --authorized-extension` `PASS` 37/2/0 dopo assestamento (allowlist,
  self-hash, artifact-hash), inclusi `285 requirement allocation` `PASS`
  (rows: 285, missing: []) e `qualifying trace assignments` `PASS`;
  `validate_rccad.py` `PASS_LOCAL_PRECHECK` 0 finding; `verify.py --json`
  `PASS` 14/0/0 (`reports/verify_report.json` invariato);
  `validate_language_policy.py` `PASS`; `validate_ocor_change_scope.py`
  `PASS` 5 percorsi; `ruff check .`/`mypy` `PASS` invariati; regressione
  pytest completa `2 failed, 516 passed, 5 skipped, 10 errors` — stessi gap
  sandbox già dichiarati, nessuna nuova failure.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`
  (`FR-047` resta `PARTIALLY_IMPLEMENTED`, in attesa della verifica a
  mission-thread completo di `OCOR-DEV-0065`), `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`.
- Prossima azione: aprire la PR, attendere CI verde, merge, verifica SHA
  post-merge, poi risolvere l'escalation `PHASE2-4-BACKLOG-GENERATOR-DRIFT`
  come task a sé stante (estendere `TASK_SPECS`/la logica di generazione di
  `scripts/build_ocor_development_plan.py` per coprire `OCOR-DEV-0070`–`0084`
  e verificare che una rigenerazione riproduca l'84-task backlog reale prima
  di rigenerare mai il DAG per davvero). Solo allora la Fase 2.4 è chiusa;
  segue la Fase 3.

## 2026-09-12 — Chiusura parziale Fase 2.4 (FR-047)

- PR #65 aperta e integrata: merge `dcfca5086ac20ed1b99548c4eb02b57f92dee66c`.
  Il primo push ha fatto fallire di nuovo `tooling-policy` per lo stesso
  self-hash di `scripts/validate_ocor_development_plan.py` non assestato
  dopo l'ultima di due modifiche nella stessa iterazione — terza occorrenza
  di questo esatto errore in questa sessione. Corretto e ripushato
  (`f4eda68`): 12/12 check verdi.
- Verifica pre-merge: `mergeStateStatus: CLEAN`. Verifica post-merge: SHA di
  `origin/main` coincidente con il merge commit.
- `EXECUTION_STATE.json` e `MODEL_HANDOFF.json` risincronizzati;
  `latest_ci_evidence` aggiornato ai run reali.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti globali `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC` e `Production` `NO-GO`.
- **Fase 2.4 non ancora completamente chiusa**: resta l'escalation
  `PHASE2-4-BACKLOG-GENERATOR-DRIFT`. Prossima azione: risolverla come task a
  sé stante — estendere `scripts/build_ocor_development_plan.py` con un
  percorso di generazione dedicato al workstream `WS-12` (template diverso da
  quello dei task 1-69: `objective`/`rationale`/`normative_references`/
  `validation_commands`/`bounded_agent_context_pack` specifici per il
  bootstrap di infrastruttura), verificare in una directory di scratch che
  una rigenerazione riproduca esattamente backlog/DAG/context-manifest reali
  per `OCOR-DEV-0070`–`0084`, e solo allora considerare la Fase 2.4 chiusa.

## 2026-09-12 — Chiusura Fase 2.4: risolta PHASE2-4-BACKLOG-GENERATOR-DRIFT

- Branch `governed/phase2-4-backlog-generator-drift` da `main`
  (`3caf7a68bfdee11eb1abc4dec857cf130c89f912`, merge PR #66).
- Causa radice confermata: `TASK_SPECS` in
  `scripts/build_ocor_development_plan.py` descriveva solo 69 task; i 15 task
  `OCOR-DEV-0070`–`0084` (catena WS-12 di riparazione del bootstrap
  infrastrutturale) erano stati adottati nel backlog committato fuori banda,
  senza mai aggiornare il generatore. Una rigenerazione reale li avrebbe
  cancellati in silenzio, insieme agli archi di dipendenza che li usano
  (`OCOR-DEV-0016/0017/0018/0021 -> OCOR-DEV-0084`).
- Correzione: aggiunto `WS12_TASK_SPECS` (15 tuple) e un ramo dedicato in
  `build_tasks()`; aggiunta la dipendenza `84` ai task 16/17/18/21 (il
  backlog reale la richiede); aggiunto un override post-hoc per
  `requirement_ids` di FR-047 che riproduce la correzione manuale della PR
  #65 (il matching a parola chiave di `requirement_owner()` per WS-09
  intercetta la sottostringa "tool" dentro il titolo stesso di FR-047 —
  esattamente il difetto già corretto a mano — così una rigenerazione futura
  ora riproduce, invece di annullare, la correzione); riscritta
  `context_manifest()` con un helper `_task_context_entry()` che assegna ai
  task 70–84 il ruolo reale "Infrastructure and Operations Agent" con
  `paths`/token-budget dedicati, distinguendoli dai task 6 e 49 (che usano
  `workstream=WS-12` ma la formula generica).
- Verifica: confronto in memoria (mai scritto su disco prima della verifica,
  come richiesto dal mandato) di `build_tasks()`/`dag_text()`/
  `context_manifest()` contro i file committati reali —
  **0 mismatch su tutti gli 84 task e ogni campo**, DAG e context-manifest
  byte-identici. `build_trace()`/`OCOR_TRACEABILITY_PLAN.csv` lasciato
  volutamente fuori scope: ha una propria staleness distinta e preesistente
  (2/285 righe, `BR-003` e `FR-047`, causata da un'euristica di ownership
  "vince l'ultimo task nell'ordine di iterazione" sensibile all'ordine —
  mai stata corretta per costruzione, solo accidentalmente stabile prima
  dell'aggiunta di WS-12) — registrata come nuova escalation separata,
  non bloccante, non confusa con questa.
- Aggiunto test di non-regressione permanente
  `reports/tests/test_backlog_generator_reality_parity.py` (RED/GREEN, RED
  sigillato in `reports/tests/evidence/rem_backlog_generator_drift/red.log`,
  fingerprint `94c2781e8c0072dd4e7c1b84c9772aeedd7159fa78e00f521efb946bc7748841`)
  che blocca in CI qualunque futura regressione di questo tipo.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (44 file, scope
  invariato), `validate_rccad.py` PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (7 percorsi), pytest completo
  `2 failed, 521 passed, 5 skipped, 10 errors` (stessi gap sandbox noti,
  +5 rispetto alla fase precedente = i nuovi test di questa iterazione),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo il
  consueto doppio-run di assestamento self-hash (modificato
  `scripts/validate_ocor_development_plan.py` per l'ultima volta prima di
  eseguirlo, come da lezione appresa dalle 3 occorrenze precedenti).
  `OCOR_PLAN_RUN_STATE.json.artifact_hashes` aggiornato a mano per
  `scripts/build_ocor_development_plan.py` (unica eccezione documentata: il
  percorso di rigenerazione reale invocherebbe anche `build_trace()`, non
  sicuro per la staleness nota sopra).
- Evidenza sigillata:
  `reports/evidence/local-gates/phase2-4-backlog-generator-drift-20260912.json`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- **Fase 2.4 ora completamente chiusa** (in attesa di merge PR). Prossima
  azione: Fase 3 (harness di benchmark riproducibile e content-addressed per
  i 4 componenti candidati, contro le soglie di migrazione già corrette in
  `OCOR_LANGUAGE_POLICY.md` §3), poi esecuzione backlog via
  `./.venv/bin/python3 scripts/ocor_autonomous_delivery.py --next` a partire
  da `OCOR-DEV-0079`.

## 2026-09-12 — PR #67 mergiata: Fase 2.4 definitivamente chiusa

- PR #67 aperta e integrata senza correzioni: tutti e 13 i check verdi al
  primo push (commit `fbdec46`). `mergeStateStatus: CLEAN`,
  `mergeable: MERGEABLE`. Merge: `9bd2821464339f406df26cc3b2dd8579330c80fb`.
  Verifica post-merge: `git fetch origin main` conferma
  `origin/main == 9bd2821` (fast-forward pulito da `3caf7a6`).
- `EXECUTION_STATE.json`/`MODEL_HANDOFF.json` risincronizzati su branch
  `governed/phase2-4-close-state-generator-drift`, `baseline_commit` ==
  `9bd2821...`, `latest_ci_evidence` aggiornato ai 6 run id reali della PR
  #67 (`34716799046/061/068/075/087/109`). `current_task` avanzato a
  `CC-OCOR-DELIVERY-COMPLETION__PHASE-3-BENCHMARK-HARNESS`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- **Fasi 2.1–2.4 del mandato ora tutte chiuse e mergiate** (PR #54–#67).
  Prossima azione: Fase 3 — harness di benchmark riproducibile e
  content-addressed per i 4 componenti candidati rispetto alle soglie di
  migrazione OI-008/ASM-010/NFR-080 già corrette in
  `OCOR_LANGUAGE_POLICY.md` §3; esito atteso `NO_MIGRATION_JUSTIFIED` oppure
  una decisione di migrazione scoperta al solo componente coinvolto con
  protocollo differenziale completo prima di ogni merge. Solo dopo,
  esecuzione backlog via
  `./.venv/bin/python3 scripts/ocor_autonomous_delivery.py --next` a partire
  da `OCOR-DEV-0079`.

## 2026-09-12 — Fase 3: harness di benchmark eseguito, esito reale per il componente 1

- PR #68 mergiata (chore(state): close Phase 2.4 tracking): tutti e 13 i
  check verdi, merge `5a08f78c9e429c2e80ec93b9d05c029e9e46cfb9`, verifica
  post-merge con `git fetch origin main` conferma `origin/main == 5a08f78`.
  Un piccolo commit di assestamento (`a19c321`) ha corretto il base-ref
  auto-embedded di `OCOR_PLANNING_VALIDATION_REPORT.md`, prodotto dalla
  stessa esecuzione del validator già usata per i gate — nessun problema
  nuovo, solo output mecc anico del tool.
- Branch `governed/phase3-language-migration-benchmark` da `main`
  (`5a08f78c9e429c2e80ec93b9d05c029e9e46cfb9`).
- Costruito `scripts/run_language_migration_benchmark.py` (harness
  riproducibile e content-addressed) e un nuovo CLI Node dedicato,
  `ocor-runtime/sdk/typescript/src/cli/benchmark_canonicalize.ts`
  (timing interno con `process.hrtime.bigint()`, distinto dal CLI di
  conformità NFR-022 il cui contratto di stdout è già asserito byte per
  byte e non è stato toccato).
- Corpus sigillato: 200 documenti deterministici (LCG proprio, seed
  `20260912`), ciascuno ~10 KB serializzato (10000–10121 byte, esattamente
  il payload di riferimento di `OCOR_LANGUAGE_POLICY.md` §3) —
  `reports/benchmarks/fixtures/phase3_canonical_corpus.json`,
  `sha256=2ce8879bc8e5697a4f51e37a3ae1262da4995c2fdba7f2ba23e6e3e775da80b7`.
- **Componente 1 (kernel di canonicalizzazione RFC 8785) — misurato per
  davvero**: mediana Python / mediana Node = **4.24×** (range su 3 run
  consecutive con lo stesso corpus sigillato: 4.24×–4.77×, stabile, non
  rumore), soglia >3× — **superata**. p95 assoluto Python: 1.77–1.96 ms,
  soglia >2 ms — non superata (ma la clausola è un OR, quindi la soglia
  è comunque superata). Esito: **`MIGRATION_THRESHOLD_EXCEEDED`**.
- Per `OCOR_LANGUAGE_POLICY.md` §3, il superamento autorizza l'apertura di
  una nuova decisione di migrazione per il solo componente — non
  l'esecuzione autonoma della migrazione, che sostituirebbe
  un'architettura approvata (`AFF-001`) ed è una delle condizioni di
  escalation esplicite del mandato (§5.4). Registrata l'escalation
  `PHASE3-COMPONENT1-CANONICAL-KERNEL-MIGRATION-THRESHOLD-EXCEEDED`,
  riservata al Product Owner sotto dual control (`NFR-081`/`DEC-174`).
  Dettaglio completo e raccomandazione in
  `reports/development/PHASE3_LANGUAGE_MIGRATION_DECISION.md`.
- **Componenti 2–4 (percorso di commit C3, backbone eventi C5, proiezione
  C4) — `NOT_YET_MEASURABLE`**, ciascuno con motivo concreto e non
  fabbricato: componente 2 richiede PostgreSQL reale (stesso gap già
  documentato della suite live di `test_ocor_dev_0015.py`); componenti 3 e
  4 non hanno ancora un'implementazione reale in `ocor_runtime` (solo FSM
  obsoleta / reticolo di marking), per
  `docs/planning/OCOR_CURRENT_STATE_BASELINE.json`. Questo è un esito
  parziale onesto, non un sostituto di `NO_MIGRATION_JUSTIFIED`.
- Aggiunto `reports/tests/test_language_migration_benchmark_harness.py`
  (11 test): soglie del harness allineate a `OCOR_LANGUAGE_POLICY.md` §3
  per tutti e 4 i componenti, hash del corpus sigillato invariato,
  determinismo del generatore, payload ~10 KB, componenti 2–4 mai
  fabbricati, smoke test end-to-end (guardia `TEST-INFRA-004`), nessun
  claim proibito nell'evidenza sigillata.
- **Trovato e corretto un gap della PR #67**: `test_backlog_generator_reality_parity.py`
  non era mai stato cablato in nessun job CI (solo eseguito localmente) —
  corretto insieme al nuovo test, entrambi ora nel job `type-and-lint-gate`
  di `ocor-tooling-bootstrap.yml`.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file, 1 fix
  `no-any-return`), `tsc --strict` (nuovo CLI compilato pulito),
  `validate_rccad.py` PASS (dopo aver registrato `TEST-INFRA-004` in
  `METHOD_COMPLIANCE.json`), `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (12 percorsi), pytest completo
  `2 failed, 532 passed, 5 skipped, 10 errors` (stessi gap sandbox noti, +11
  rispetto alla fase precedente = i nuovi test di questa iterazione),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo il
  consueto doppio-run di assestamento self-hash.
- Evidenza sigillata:
  `reports/evidence/local-gates/phase3-language-migration-benchmark-20260912.json`,
  `reports/benchmarks/phase3_language_migration_benchmark_20260912.json`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- **Fase 3 chiusa come processo** (misura reale per tutto ciò che è oggi
  misurabile, escalation registrata per il solo componente 1, esito onesto
  e non bloccante per i componenti 2–4). Prossima azione: esecuzione
  backlog via `./.venv/bin/python3 scripts/ocor_autonomous_delivery.py --next`
  a partire da `OCOR-DEV-0079` — l'escalation del componente 1 non blocca
  questo passo.

## 2026-09-12 — PR #69 mergiata: Fase 3 definitivamente chiusa

- PR #69 aperta e integrata senza correzioni: tutti e 13 i check verdi al
  primo push (commit `6d19ca5`). `mergeStateStatus: CLEAN`,
  `mergeable: MERGEABLE`. Merge: `4532dded147f77f025f65fd45d53b6a8043671e9`.
  Verifica post-merge: `git fetch origin main` conferma
  `origin/main == 4532dde` (fast-forward pulito da `5a08f78`).
- `EXECUTION_STATE.json`/`MODEL_HANDOFF.json` risincronizzati su branch
  `governed/phase3-close-state`, `baseline_commit` == `4532dde...`,
  `latest_ci_evidence` aggiornato ai 6 run id reali della PR #69
  (`34720091571/578/580/586/589/603`). `current_task` avanzato a
  `CC-OCOR-DELIVERY-COMPLETION__BACKLOG-EXECUTION-OCOR-DEV-0079`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- **Fasi 2.1–2.4 e 3 del mandato ora tutte chiuse e mergiate** (PR #54–#69).
  L'escalation `PHASE3-COMPONENT1-CANONICAL-KERNEL-MIGRATION-THRESHOLD-EXCEEDED`
  resta aperta, riservata al Product Owner, e non blocca il passo
  successivo. Prossima azione: esecuzione del backlog via
  `./.venv/bin/python3 scripts/ocor_autonomous_delivery.py --next` a
  partire da `OCOR-DEV-0079`, sbloccando la catena WS-12 fino a `0084` e
  poi gli spike G2 `0016`/`0017`/`0018`/`0021`, poi il resto di G2–G7
  nell'ordine del DAG.

## 2026-09-13 — Backlog: OCOR-DEV-0079 (typed service health checks, reale)

- PR #70 mergiata (chore(state): close Phase 3 tracking): tutti e 13 i
  check verdi, merge `1dc3a0824b08b446ffb07598dded9f526b02d008`, verifica
  post-merge con `git fetch origin main` conferma
  `origin/main == 1dc3a08`.
- `scripts/ocor_autonomous_delivery.py --status`/`--next` confermano
  `OCOR-DEV-0079` come unico task dependency-ready (28 `ACCEPTED`,
  56 `PENDING`).
- **Scoperta**: Docker è realmente disponibile in questo sandbox (porte dei
  10 servizi tutte libere, nessun conflitto con i container preesistenti
  non-ocor-bootstrap `eci-dev-control-plane`/`open-webui`, mai toccati).
  Bootstrap completo dello stack reale da zero: 9 servizi
  (TerminusDB/TypeDB/Fuseki/OPA/Keycloak/OpenBao/PostgreSQL/Kafka/Qdrant)
  avviati direttamente con segreti generati solo per questa sessione (mai
  committati); SPIRE con il flusso a due fasi (server su, join token reale
  generato via `docker exec spire-server ... token generate`, poi agent su
  con attestazione riuscita) usando una CA auto-firmata usa-e-getta appena
  generata per `OCOR_SPIRE_BOOTSTRAP_DIR` — sequenza non documentata prima
  passo-passo altrove nel repo. Verificati i 4 moduli `qualify.py`/
  `qualify_security_services.py` già esistenti (typedb, openbao, spire,
  policy-identity) contro lo stack appena avviato: tutti `PASS` reali,
  prima di scrivere qualunque codice nuovo.
- Estesa `scripts/verify_external_services.py` con stato tipizzato
  (`ServiceStatus`: `READY`/`DEGRADED`/`UNREACHABLE`/`NOT_PROVISIONED`,
  `ServiceHealth` dataclass) al posto del precedente `READY`/`NOT_READY`
  non tipizzato che confondeva "controllato e rotto" con "mai
  provisionato". I 4 servizi già coperti sono guidati come sottoprocessi
  dei moduli esistenti; aggiunti 5 controlli tipizzati inline per i
  servizi senza modulo dedicato (TerminusDB, Fuseki, PostgreSQL, Kafka,
  Qdrant): validazione lock, ispezione Docker reale, prova di protocollo
  positiva e — sotto `--execute` — negativa reale (credenziale errata su
  TerminusDB/PostgreSQL, dataset Fuseki assente, topic Kafka assente,
  collezione Qdrant assente: tutte verificate `FAIL_CLOSED`).
  Retrocompatibilità preservata (`--manifest-only` e la scansione
  porta/container precedente invariate).
- **Fault injection reale**: `docker pause`/`unpause` su TerminusDB e
  Kafka — rilevati `DEGRADED` durante la pausa, tornati `READY` entro la
  finestra limitata dopo l'unpause; stack completo confermato integro con
  `docker compose ps` al termine.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0079.py` (17 test
  unit/negative/contract sulla logica tipizzata pura, nessuna dipendenza
  live, eseguiti sempre in CI).
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file, 1 fix
  `no-any-return`), `validate_rccad.py` PASS, `validate_language_policy.py`
  PASS, pytest completo `2 failed, 549 passed, 5 skipped, 10 errors`
  (stessi gap sandbox noti, +17 rispetto alla fase precedente = i nuovi
  test di questa iterazione).
- Evidenza sigillata contro lo stack live reale:
  `reports/evidence/G2/OCOR-DEV-0079.json` +
  `reports/evidence/G2/OCOR-DEV-0079.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo, nessuna
  riformattazione). `scripts/validate_runtime_evidence.py --task
  OCOR-DEV-0079 --non-skipped` PASS.
- Rischio residuo dichiarato: i 5 test PostgreSQL live restano
  `NOT_EXECUTED` localmente perché `ocor-runtime/.venv` non ha `psycopg`
  installato — non più per assenza di un vero PostgreSQL (che ora è
  realmente in esecuzione e raggiungibile, verificato direttamente), ma
  per un gap del venv locale, fuori scope per questo task e segnalato come
  opportunità futura distinta.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: `OCOR-DEV-0080` ("Implement deterministic service
  initialization"), che dipende solo da `OCOR-DEV-0079`.

## 2026-09-13 — Backlog: OCOR-DEV-0080 (inizializzazione deterministica, reale)

- PR #71 mergiata (typed service health checks): tutti e 13 i check verdi,
  merge `751836ef2cb836ee77e7908bbdeba0dd1846678e`, verifica post-merge con
  `git fetch origin main` conferma `origin/main == 751836e`. Lo stack Docker
  reale a 11 servizi da `OCOR-DEV-0079` è rimasto in esecuzione e riusato
  direttamente per questa iterazione, senza un nuovo bootstrap.
- Implementato `deploy/bootstrap/init/initialize_services.py`: 5 passi
  ordinati e idempotenti come da `deploy/bootstrap/init/README.md` (trust
  SPIRE, realm Keycloak, policy OPA, path OpenBao, database grafo). Ogni
  passo verifica prima lo stato esistente: se assente lo crea
  (`CREATED`), se presente e conforme non tocca nulla (`ALREADY_INITIALIZED`),
  se presente ma diverso dall'atteso fallisce chiuso (`DRIFT_DETECTED`,
  mai sovrascrittura silenziosa). Nessun contenuto di policy di sicurezza
  reale viene inventato: OPA riceve solo un placeholder `default allow =
  false` (fail-closed, ambito WS-11 differito), il realm Keycloak è un
  guscio vuoto, i database grafo sono vuoti senza schema.
- **Verifica reale contro lo stack live**: RUN 1 (stato pulito) →
  `CREATED` per Keycloak/OPA/OpenBao/database grafo, `ALREADY_INITIALIZED`
  per SPIRE (passo di sola verifica, trust già stabilito a `OCOR-DEV-0079`);
  RUN 2 (ri-esecuzione) → `ALREADY_INITIALIZED` su tutti i 5 passi, zero
  chiamate mutanti; RUN 3 (drift reale: policy OPA mutata esternamente via
  API) → `DRIFT_DETECTED`, script fallito chiuso (`exit=1`), nessuna
  sovrascrittura; RUN 4 (ripristino contenuto corretto) → recupero
  completo a `PASS`. Un vero drill di rollback eseguito, non solo
  descritto.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0080.py` (16 test
  unit/negative/contract, ogni chiamata di rete/sottoprocesso sostituita
  con un doppio deterministico, nessuna dipendenza live).
- Corretto `scripts/validate_language_policy.py`: aggiunta
  `deploy/bootstrap/init` alle aree autorizzate per `.py` e `.rego`
  (mancava, bloccava il nuovo file e la policy OPA seminale).
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file,
  `deploy/bootstrap/` resta fuori scope mypy come i moduli `qualify.py`
  esistenti), `validate_rccad.py` PASS, `validate_language_policy.py` PASS
  dopo la correzione, pytest completo `2 failed, 565 passed, 5 skipped,
  10 errors` (stessi gap sandbox noti, +16 rispetto alla fase precedente),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo il
  consueto doppio-run di assestamento self-hash.
- Evidenza sigillata contro lo stack live reale, incluso il drill di
  drift/rollback: `reports/evidence/G2/OCOR-DEV-0080.json` +
  `reports/evidence/G2/OCOR-DEV-0080.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo).
  `scripts/validate_runtime_evidence.py --task OCOR-DEV-0080 --non-skipped`
  PASS.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: `OCOR-DEV-0081` ("Load deterministic synthetic test
  fixtures"), che dipende solo da `OCOR-DEV-0080`.

## 2026-09-13 — Backlog: OCOR-DEV-0081 (fixture sintetiche deterministiche, reali)

- PR #72 mergiata (inizializzazione deterministica): tutti e 13 i check
  verdi, merge `79084dd7be841bee0b36b92b939e9abea0e37362`, verifica
  post-merge con `git fetch origin main` conferma `origin/main == 79084dd`.
  Lo stack Docker a 11 servizi è rimasto in esecuzione, ma `fuseki` era
  stato terminato (`exit 137`, verosimilmente OOM da un container
  preesistente non-ocor-bootstrap che occupa molta memoria host) —
  riavviato con `docker compose up -d fuseki`, tornato sano in pochi
  secondi; nessun altro servizio toccato.
- Esplorazione manuale reale delle API TerminusDB (`/api/document`, schema
  + istanza) e TypeDB (transazioni HTTP v1: `open`/`query`/`commit`/`close`,
  `define`/`insert`/`match`/`undefine`) prima di scrivere codice, per
  imparare le forme esatte di richiesta/risposta/conflitto. Trovata una
  vera stranezza di TerminusDB: una GET su un documento assente risponde
  con HTTP 200 reale ma un corpo prefissato dal testo letterale
  `"Status: 404\nContent-type: ...\n\n"` prima del JSON — documentata nel
  codice e coperta da un test dedicato.
- Implementato `deploy/bootstrap/fixtures/synthetic_fixtures.json`
  (manifest versionato) e `deploy/bootstrap/fixtures/load_fixtures.py`:
  carica la stessa fixture sintetica minima (un'entità/documento) sia in
  TerminusDB sia in TypeDB, con lo stesso pattern check-prima-di-mutare di
  `OCOR-DEV-0080` — assente crea, presente e conforme non tocca nulla
  (`ALREADY_INITIALIZED`), presente ma diverso fallisce chiuso
  (`DRIFT_DETECTED`). `postgresql`/`kafka`/`qdrant` dichiarati esplicitamente
  fuori scope: già provisionati ed evidenziati da task precedenti e
  indipendenti (`OCOR-DEV-0006`/`0015`/`0019`/`0023`), non parte della
  catena di riparazione WS-12.
- **Verifica reale contro lo stack live**: RUN 1 (database puliti) →
  `CREATED` per entrambi i target, digest di verifica post-caricamento
  identico fra TerminusDB e TypeDB per lo stesso contenuto semantico; RUN 2
  (ri-esecuzione) → `ALREADY_INITIALIZED` per entrambi, zero chiamate
  mutanti; RUN 3 (drift reale: istanza TerminusDB mutata esternamente via
  API) → `DRIFT_DETECTED`, script fallito chiuso (`exit=1`); RUN 4
  (ripristino) → recupero completo a `PASS`. Un vero drill di
  drift/rollback eseguito, non solo descritto.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0081.py` (12 test
  unit/negative/contract, ogni chiamata di rete sostituita con un doppio
  deterministico).
- Corretto `scripts/validate_language_policy.py`: aggiunta
  `deploy/bootstrap/fixtures` alle aree autorizzate per `.py` (stessa
  lezione di `OCOR-DEV-0080`, verificata questa volta PRIMA di aprire la
  PR).
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file),
  `validate_rccad.py` PASS, `validate_language_policy.py` PASS, pytest
  completo `2 failed, 577 passed, 5 skipped, 10 errors` (stessi gap
  sandbox noti, +12 rispetto alla fase precedente),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo il
  consueto doppio-run di assestamento self-hash.
- Evidenza sigillata contro lo stack live reale, incluso il drill di
  drift/rollback: `reports/evidence/G2/OCOR-DEV-0081.json` +
  `reports/evidence/G2/OCOR-DEV-0081.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo).
  `scripts/validate_runtime_evidence.py --task OCOR-DEV-0081 --non-skipped`
  PASS.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: `OCOR-DEV-0082` ("Implement service reset and
  teardown"), che dipende da `OCOR-DEV-0080`.

## 2026-09-13 — Backlog: OCOR-DEV-0082 (reset e teardown, reale)

- PR #73 mergiata (fixture sintetiche): tutti e 13 i check verdi, merge
  `48b6d01a254d0ceb78fb9ad4ec96088e1835c5fb`, verifica post-merge con
  `git fetch origin main` conferma `origin/main == 48b6d01`. Stack Docker
  ancora attivo e sano (11/11 container), riusato senza nuovo bootstrap.
- Trovato che `scripts/reset_test_environment.py` esisteva già ma
  implementava solo il "teardown" completo (`docker compose down
  --volumes --remove-orphans`), non il "reset" più leggero richiesto dal
  titolo del task. Aggiunta una modalità `--reset` distinta: annulla
  esattamente i 4 passi mutanti di `OCOR-DEV-0080`
  (`initialize_services.py`) — realm Keycloak, policy OPA, mount OpenBao,
  database `ocor_default` su TerminusDB e TypeDB — senza fermare alcun
  container. Il trust SPIRE resta intoccato: `OCOR-DEV-0080` lo verifica
  soltanto, non lo crea, quindi non c'è nulla da annullare senza rompere
  l'identità di ogni servizio. `--teardown` (comportamento preesistente)
  resta invariato.
- **Verifica reale contro lo stack live**: confermato lo stato
  inizializzato prima del reset (typed health check `PASS`); RUN 1
  (`--reset --execute` reale) → `RESET` per tutti e 4 i target; RUN 2
  (ri-esecuzione) → `ALREADY_RESET` per tutti, zero chiamate mutanti;
  `docker compose ps` subito dopo conferma tutti gli 11 container ancora
  `Up`/`healthy` — il reset non tocca mai i container; RUN 3
  (**round-trip reset → re-init reale**) → l'inizializzatore di
  `OCOR-DEV-0080` ricrea da zero tutti e 4 i target (`CREATED`),
  dimostrando che il reset è un vero inverso completo, non parziale o
  con perdita di stato. Fixture sintetiche di `OCOR-DEV-0081` ricaricate
  al termine per lasciare lo stack nello stato atteso dai prossimi task.
  `--teardown` verificato solo in dry-run: eseguirlo per davvero
  avrebbe distrutto lo stack live da cui dipendono gli altri task WS-12
  in corso.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0082.py` (10 test
  unit/negative/contract, ogni chiamata di rete sostituita con un doppio
  deterministico).
- `scripts/validate_language_policy.py` verificato PRIMA di aprire la PR
  (lezione da `OCOR-DEV-0080`/`0081`): nessuna nuova area necessaria,
  `scripts/` era già autorizzato per `.py`.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file),
  `validate_rccad.py` PASS, `validate_language_policy.py` PASS, pytest
  completo `2 failed, 587 passed, 5 skipped, 10 errors` (stessi gap
  sandbox noti, +10 rispetto alla fase precedente),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo il
  consueto doppio-run di assestamento self-hash.
- Evidenza sigillata contro lo stack live reale, incluso il round-trip
  reset→re-init: `reports/evidence/G2/OCOR-DEV-0082.json` +
  `reports/evidence/G2/OCOR-DEV-0082.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo).
  `scripts/validate_runtime_evidence.py --task OCOR-DEV-0082 --non-skipped`
  PASS.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: `OCOR-DEV-0083` ("Implement bounded fault injection"),
  che dipende da `OCOR-DEV-0079`.

## 2026-09-13 — Backlog: OCOR-DEV-0083 (fault injection bounded, reale)

- PR #74 mergiata (reset e teardown): tutti e 13 i check verdi, merge
  `6a7d51ef7534f0cbd2f3519d9e92f2441c5f8aa2`, verifica post-merge con
  `git fetch origin main` conferma `origin/main == 6a7d51e`. `fuseki`
  nuovamente terminato per OOM da un container host non correlato
  (pattern ricorrente, host sotto pressione di memoria per un container
  preesistente da ~7 GiB) — riavviato senza toccare altro.
- Trovato che `scripts/fault_inject_test_environment.py` esisteva già
  (pause/unpause/restart/disconnect/reconnect grezzi, dry-run di default)
  ma senza alcuna nozione di "bounded" — nessun rilevamento del guasto né
  recupero automatico garantito. Aggiunta una modalità `--bounded`: applica
  il guasto, attende (con timeout) la condizione di rottura attesa, poi —
  in un blocco `finally`, quindi il recupero viene tentato anche se il
  rilevamento non si completa mai — applica l'azione di recupero
  corrispondente e attende (con un secondo timeout) il ritorno alla
  normalità. File già referenziato come input sigillato in
  `reports/evidence/G2/OCOR-DEV-0073.json`/`OCOR-DEV-0075.json`, ma solo
  come record storico descrittivo (nessun validatore ne applica l'hash
  come invariante continuo) — modifica diretta sicura, verificato.
- **Scoperta tecnica reale e corretta durante l'iterazione**: il primo
  tentativo di rilevare `disconnect` tramite una semplice connessione TCP
  al servizio pubblicato (`socket.create_connection`) risultava sempre
  "raggiungibile" anche a container scollegato — su questo host Docker
  Desktop il proxy di port-forwarding completa l'handshake TCP
  indipendentemente dall'attacco di rete del container. Verificato con una
  prova diretta (connessione TCP grezza riuscita vs richiesta HTTP reale
  fallita durante lo stesso disconnect). Corretto sostituendo l'oracolo con
  un vero round-trip HTTP per servizio (`HEALTH_URLS`), che rileva
  correttamente sia il guasto sia il recupero. `--bounded disconnect`
  resta non supportato per `spire-server`/`spire-agent` (nessuna porta
  pubblicata da verificare dall'host).
- **Verifica reale contro lo stack live**: RUN 1 (`pause`/`unpause` reale
  su typedb) → rilevato e recuperato entro la finestra limitata; RUN 2
  (`disconnect`/`reconnect` reale su fuseki, oracolo HTTP corretto) →
  rilevato e recuperato; RUN 3 (`restart` reale su keycloak) →
  autorecupero confermato; RUN 4 (negativi) → `--bounded` rifiuta
  `reconnect`/`unpause` come guasto primario e rifiuta `disconnect` per
  `spire-server` senza endpoint pubblicato.
- **Bug reale trovato e corretto ripristinando lo stato dello stack**:
  `deploy/bootstrap/fixtures/load_fixtures.py` (da `OCOR-DEV-0081`)
  tollerava solo la stranezza "TerminusDB risponde 200 con prefisso
  testuale Status: 404" per il caso "documento assente", ma TerminusDB è
  stato osservato restituire anche un vero HTTP 404 per la stessa identica
  condizione in invocazioni diverse — corretto per accettare entrambe le
  forme; aggiunto un test di regressione dedicato al file di test già
  esistente di `OCOR-DEV-0081` (`ocor-runtime/tests/tasks/test_ocor_dev_0081.py`).
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0083.py` (12 test
  unit/negative/contract, ogni chiamata subprocess/HTTP sostituita con un
  doppio deterministico).
- `scripts/validate_language_policy.py` verificato PRIMA di aprire la PR:
  nessuna nuova area necessaria.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file),
  `validate_rccad.py` PASS, `validate_language_policy.py` PASS, pytest
  completo `2 failed, 600 passed, 5 skipped, 10 errors` (stessi gap
  sandbox noti, +13 rispetto alla fase precedente: 12 nuovi test più 1 di
  regressione per il bug TerminusDB),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo il
  consueto doppio-run di assestamento self-hash.
- Evidenza sigillata contro lo stack live reale, inclusi tutti e 3 i cicli
  bounded reali e la scoperta tecnica TCP-vs-HTTP:
  `reports/evidence/G2/OCOR-DEV-0083.json` +
  `reports/evidence/G2/OCOR-DEV-0083.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo).
  `scripts/validate_runtime_evidence.py --task OCOR-DEV-0083 --non-skipped`
  PASS.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: `OCOR-DEV-0084` ("Capture reproducible environment
  evidence"), che dipende da `OCOR-DEV-0081`, `OCOR-DEV-0082` e
  `OCOR-DEV-0083` — l'ultimo task della catena WS-12 di riparazione
  dell'infrastruttura, dopo il quale gli spike G2
  `OCOR-DEV-0016`/`0017`/`0018`/`0021` diventano eseguibili.
- `OCOR-DEV-0083`: PR #75 mergiata (`e1b4fe1657d7222bc17b41b04feff8658a1cc6d1`),
  tutti e 13 i check verdi al primo push, SHA post-merge verificata.

## 2026-09-13 — Backlog: OCOR-DEV-0084 (Capture reproducible environment evidence)

- Ultimo task della catena WS-12 di riparazione dell'infrastruttura
  (`OCOR-DEV-0070`..`0084`). Dipende da `OCOR-DEV-0081`/`0082`/`0083`,
  tutti già mergiati.
- `scripts/capture_environment_evidence.py` esisteva già ma catturava solo
  l'inventario grezzo `docker compose ps` (container esistente +
  healthcheck Docker), senza dire nulla sul contratto governato che ogni
  servizio deve soddisfare. Aggiunto un campo tipizzato
  `environment_status` che integra `typed_health_checks()` di
  `scripts/verify_external_services.py` (immagine pinnata, pubblicazione
  solo loopback, probe di protocollo reale, controlli negativi
  fail-closed). Mantenuto deliberatamente separato dal campo `status`
  preesistente (successo del processo di cattura, non salute
  dell'ambiente), così un servizio degradato resta visibile in evidenza
  invece di essere assorbito silenziosamente in un generico "captured OK".
- Aggiunti `ARTIFACT_PATHS` (4 nuovi deliverable WS-12),
  `_load_typed_health_checks()` (import dinamico dello script di verifica,
  stesso pattern `sys.modules[SPEC.name] = module` usato in tutta la
  sessione) e `capture_environment_status()`.
- Bug reale trovato e corretto durante la cattura positiva: l'auto-discovery
  preesistente di `--env-file` controllava solo `.ocor/bootstrap.env`, che
  non corrisponde al percorso reale dei secret di questa sessione
  (`~/.ocor-bootstrap-secrets/ocor-bootstrap.env`); senza un env-file
  corrispondente `docker compose ps` falliva l'interpolazione della
  password Keycloak e l'intera cattura riportava `PARTIAL` anche quando
  ogni servizio era realmente sano. Corretto aggiungendo un argomento CLI
  esplicito `--env-file` che sovrascrive l'auto-discovery.
- Provato per reale contro lo stack live a 11 servizi: RUN 1 (positivo,
  tutti sani) → `environment_status=PASS`; RUN 2 (negativo, `typedb` in
  pausa) → `environment_status=DEGRADED`, exit code non zero, mai un PASS
  silenzioso; RUN 3 (recupero, `typedb` riattivato) → ricatturato fino al
  ritorno a `PASS` (tentativo 4, ~8s di assestamento dell'health-check,
  correttamente riflesso e non ingoiato).
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0084.py` (4 test
  unit/negative/contract, health check tipizzato sostituito con un doppio
  deterministico, nessuna dipendenza Docker live).
- `scripts/validate_language_policy.py` verificato PRIMA di aprire la PR:
  nessuna nuova area necessaria (`scripts/` già autorizzato).
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file),
  `validate_rccad.py` PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (9 percorsi), pytest completo
  `2 failed, 604 passed, 5 skipped, 10 errors` (stessi gap sandbox noti,
  +4 rispetto alla fase precedente: i 4 nuovi test),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo il
  consueto doppio-run di assestamento self-hash (aggiunti
  `ocor-runtime/tests/tasks/test_ocor_dev_0084.py`,
  `reports/evidence/G2/OCOR-DEV-0084.{json,log}` a `extension_paths`).
- Evidenza sigillata contro lo stack live reale, incluso il ciclo completo
  positivo/negativo/recupero:
  `reports/evidence/G2/OCOR-DEV-0084.json` +
  `reports/evidence/G2/OCOR-DEV-0084.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo, 46 righe).
  `scripts/validate_runtime_evidence.py --task OCOR-DEV-0084 --non-skipped`
  PASS.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: push del branch
  `governed/ocor-dev-0084-capture-environment-evidence`, apertura PR,
  polling CI, merge a gate verdi, verifica SHA post-merge. Con questo si
  chiude l'intera catena WS-12 (`OCOR-DEV-0070`..`0084`); diventano
  eseguibili gli spike G2 `OCOR-DEV-0016`/`0017`/`0018`/`0021` (le cui
  `hard_dependencies` sono state estese a includere `OCOR-DEV-0084` dalla
  correzione del generator-drift di Fase 2.4).
- `OCOR-DEV-0084`: PR #76 mergiata (`cbf53da9be6d13e77d545679dacebc2398f5af97`),
  tutti e 13 i check verdi al primo push, SHA post-merge verificata. Catena
  WS-12 (`OCOR-DEV-0070`..`0084`) chiusa.

## 2026-09-13 — Backlog: OCOR-DEV-0016 (SPIKE selected C3 backend behaviour)

- Primo spike G2 eseguibile dopo la chiusura della catena WS-12. Dipende
  da `OCOR-DEV-0006`, `OCOR-DEV-0013`, `OCOR-DEV-0015`, `OCOR-DEV-0084`,
  tutti già mergiati. `scripts/ocor_autonomous_delivery.py --status`
  riportava uno stato interno non allineato (proprio state file separato,
  mai aggiornato dall'esecuzione manuale di questa sessione); confermata
  invece la reale prontezza dei quattro spike G2 (`0016`/`0017`/`0018`/`0021`,
  tutti wave 11) direttamente da `docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json`
  e da `completed_evidence_tasks`; selezionato `OCOR-DEV-0016` per primo
  (ordine numerico, stessa convenzione usata per tutta la catena WS-12).
- **Scoperta significativa**: lo stack Docker `ocor-bootstrap` include un
  PostgreSQL reale (`127.0.0.1:55433`) già provisionato dalla catena WS-12;
  per la prima volta in questa sessione è stato possibile impostare
  `OCOR_LIVE_POSTGRES_DSN` anche in locale (non solo in CI), riqualificando
  per reale in locale i 10 test live-Postgres di `OCOR-DEV-0015`
  (precedentemente `errors` per gap noto di sandbox) e i 5 nuovi test di
  `OCOR-DEV-0016`.
- Riutilizzato senza modifiche l'oracolo sigillato di `OCOR-DEV-0015`
  (`spikes/c3_atomicity/oracle.py::PostgreSQLAtomicCommitOracle`); aggiunto
  `spikes/c3_backend/concurrency_oracle.py` (nuovo) con l'harness di race
  reale (`race_distinct_commands`, due comandi DISTINTI sulla stessa
  `expected_revision`, ciascuno con una propria connessione PostgreSQL
  reale) e due probe indipendenti fuori-banda: `observe_lock_contention`
  (prova diretta sul wire della mutua esclusione del lock consultivo reale,
  non solo inferita dall'esito) e `sample_revision_during` (lettura
  continua da una connessione indipendente durante una race live, per
  provare l'assenza di dirty read).
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0016.py` (5 test, tutti
  contro PostgreSQL reale, nessun mock):
  locking (due comandi distinti in race, uno vince, l'altro riceve un vero
  conflitto di revisione, verificato ripetendo 5 volte senza flakiness);
  prova diretta del lock su wire; isolamento (lettore concorrente non
  osserva mai un valore di revisione fuori dal set valido durante una
  race); fallimento sotto concorrenza reale (crash di processo reale via
  subprocess, sincronizzato deterministicamente — non a tempo — con un
  probe che attende l'osservazione reale del lock consultivo prima di
  rilasciare il writer superstite, che completa con successo e il ledger
  riconciliato accetta correttamente un ulteriore commit); riconciliazione
  (falsificazione sintetica di un'anomalia `phantom_receipt`, tipo diverso
  da quello già coperto da `OCOR-DEV-0015`).
- **Bug del primo tentativo, corretto prima di sigillare**: la prima
  versione del test di fallimento-sotto-concorrenza avviava crash e
  writer superstite come una race "a freddo" senza sincronizzazione,
  genuinamente non deterministica (in alcune esecuzioni il writer
  superstite vinceva il lock per primo, facendo fallire il worker di
  crash con un conflitto di revisione invece di farlo effettivamente
  crashare) — corretto bloccando il thread principale su
  `observe_lock_contention` finché il subprocess di crash non viene
  osservato detenere realmente il lock, prima di rilasciare il writer
  superstite; verificato deterministico su 5 esecuzioni consecutive.
- `scripts/validate_language_policy.py` verificato: nessuna nuova area
  necessaria (`spikes/` e `scripts/` già autorizzati dalla Fase 0/`0015`).
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file,
  `spikes/` e `tests/` fuori scope per policy, come già per
  `spikes/c3_atomicity/` di `OCOR-DEV-0015`), `validate_rccad.py` PASS,
  `validate_language_policy.py` PASS, `validate_ocor_change_scope.py` PASS
  (9 percorsi), pytest completo con `OCOR_LIVE_POSTGRES_DSN` impostato
  localmente per la prima volta: `2 failed, 624 passed, 0 skipped, 0
  errors` (gli unici 2 fallimenti sono il gap noto e preesistente del pin
  dell'interprete, indipendente da questo task; zero errori, contro i 10
  della baseline precedente senza DSN locale),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo il
  consueto doppio-run di assestamento self-hash.
- Evidenza sigillata contro il backend PostgreSQL reale selezionato:
  `reports/evidence/G2/OCOR-DEV-0016.json` +
  `reports/evidence/G2/OCOR-DEV-0016.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo, 55 righe).
  `scripts/validate_runtime_evidence.py --task OCOR-DEV-0016 --non-skipped`
  PASS.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: push del branch
  `governed/ocor-dev-0016-c3-backend-concurrency-spike`, apertura PR,
  polling CI, merge a gate verdi, verifica SHA post-merge. Poi proseguire
  con uno degli altri spike G2 dello stesso wave 11:
  `OCOR-DEV-0017`/`0018`/`0021`.
- `OCOR-DEV-0016`: PR #77 mergiata (`a2ea8f467cc47891add109fbcd1b2e8567c49399`),
  tutti e 13 i check verdi al primo push, SHA post-merge verificata.

## 2026-09-13 — Backlog: OCOR-DEV-0017 (SPIKE TypeDB exact-at-commit semantics)

- Secondo spike G2 dopo la chiusura di WS-12, selezionato per ordine
  numerico fra `0017`/`0018`/`0021` (stesso wave 11, dipendenze già
  soddisfatte). Dipende da `OCOR-DEV-0006`, `OCOR-DEV-0012`, `OCOR-DEV-0013`,
  `OCOR-DEV-0084`, tutti già mergiati.
- Riutilizzato senza modifiche il contratto sigillato di `OCOR-DEV-0012`
  (`ocor_runtime.c2.ports`: `ConsistencyMode`/`ConsistencyRequirement`/
  `ServedContext`/`NamedQueryRequest.verify_served`); aggiunto
  `spikes/typedb_exact_commit/adapter.py` (nuovo) con un
  `TypeDBExactCommitAdapter` reale che implementa `ProjectionReadPort`/
  `WatermarkPort` contro TypeDB reale (HTTP v1: signin/transazione/query/
  commit/close, stesso pattern già validato in `OCOR-DEV-0081`), modellando
  una proiezione C4 con ritardo asincrono: `ingest`/aggiornamento scrivono
  un fatto marcato con il commit che lo ha prodotto, `advance_watermark` è
  un passo SEPARATO che simula il momento in cui la pipeline di proiezione
  ha applicato quel commit ed è sicuro leggerlo.
- **Probe empirici reali contro TypeDB prima di scrivere l'adapter** (non
  assunti, verificati): un riferimento a un tipo non definito fallisce con
  HTTP 400 `INF2`; ridefinire uno schema identico è idempotente (HTTP 200,
  nessun errore — `initialize()` non necessita quindi di un probe
  check-before-mutate); un secondo insert con lo stesso valore `@key`
  fallisce con HTTP 400 `CNT9` (motiva perché un aggiornamento di un fatto
  esistente deve cancellare-e-reinserire, non un update in-place).
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0017.py` (6 test, tutti
  contro TypeDB reale, nessun mock): corrispondenza esatta quando fatto e
  watermark coincidono; fallimento chiuso (`CONSISTENCY_DOWNGRADE`) quando
  un fatto è ingerito ma il watermark non è ancora avanzato — e il
  watermark non viene mai falsamente avanzato; fallimento chiuso quando la
  riga è stata aggiornata a un commit più recente mentre il watermark resta
  al commit più vecchio richiesto (prova diretta del criterio negativo:
  "restituire fatti più vecchi come exact-at-commit falsifica l'approccio",
  qui nella forma speculare — mai servire contenuto più nuovo etichettato
  come il commit più vecchio richiesto); modalità `AT_LEAST_COMMIT` che
  riporta `PROJECTION_NOT_READY` con un watermark osservabile
  separatamente, poi successo dopo l'avanzamento; progressione reale a due
  commit in cui il commit superato non viene mai servito come esatto in
  nessuna delle due direzioni; `RESULT_NOT_FOUND` raggiunto solo dopo che
  la coerenza è confermata (mai una falsificazione della coerenza usata per
  mascherare una semplice assenza).
- **Bug del primo tentativo, corretto prima di sigillare**: `ServedContext`
  e `Watermark` (contratto sigillato di `OCOR-DEV-0012`) richiedono stringhe
  non vuote per `canonical_commit`/`projection_watermark`; usare `""` come
  sentinella per "nessun watermark ancora" faceva fallire la costruzione
  con `QUERY_CONTRACT_INVALID` prima ancora di raggiungere la verifica di
  coerenza — corretto introducendo la sentinella non vuota
  `urn:ocor:commit:none`, garantita per costruzione a non coincidere mai
  con un commit reale generato dai test.
- `scripts/validate_language_policy.py` verificato: nessuna nuova area
  necessaria (`spikes/` e `scripts/` già autorizzati).
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file,
  `spikes/` e `tests/` fuori scope per policy), `validate_rccad.py` PASS,
  `validate_language_policy.py` PASS, `validate_ocor_change_scope.py` PASS
  (9 percorsi), pytest completo con `OCOR_LIVE_POSTGRES_DSN` locale:
  `2 failed, 630 passed, 0 skipped, 0 errors` (stessi 2 fallimenti noti e
  preesistenti del pin dell'interprete, +6 rispetto alla fase precedente),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo il
  consueto doppio-run di assestamento self-hash.
- Evidenza sigillata contro TypeDB reale:
  `reports/evidence/G2/OCOR-DEV-0017.json` +
  `reports/evidence/G2/OCOR-DEV-0017.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo, 73 righe).
  `scripts/validate_runtime_evidence.py --task OCOR-DEV-0017 --non-skipped`
  PASS.
- Manutenzione ambiente: `fuseki` nuovamente OOM-killed (exit 137) dal
  container host preesistente non correlato; riavviato il solo servizio
  interessato, come nelle iterazioni precedenti, senza toccare il
  container non correlato.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: push del branch
  `governed/ocor-dev-0017-typedb-exact-commit-spike`, apertura PR, polling
  CI, merge a gate verdi, verifica SHA post-merge. Poi proseguire con uno
  degli spike G2 rimanenti dello stesso wave 11: `OCOR-DEV-0018`/`0021`.
- `OCOR-DEV-0017`: primo push, 3 check CI rossi (`delivery-activation`,
  `rccad-methodology`, `validation-closure`) perché quei job eseguono
  l'intera suite `ocor-runtime/tests/` con un container Postgres reale ma
  senza TypeDB — causa radice corretta aggiungendo un container TypeDB
  reale ai 3 workflow (stesso digest immagine di `compose.yaml`) e rendendo
  `initialize()` capace di creare il database `ocor_default` se assente.
  Evidenza aggiornata nello stesso commit/PR. Secondo push: tutti e 13 i
  check verdi. PR #78 mergiata
  (`d573b7e119b195837cc9a7f122369c06ace1523d`), SHA post-merge verificata.

## 2026-09-13 — Backlog: OCOR-DEV-0018 (SPIKE Jena marking-safe projection)

- Terzo spike G2 dopo la chiusura di WS-12, selezionato per ordine numerico
  fra `0018`/`0021` (stesso wave 11). Dipende da `OCOR-DEV-0006`,
  `OCOR-DEV-0008`, `OCOR-DEV-0014`, `OCOR-DEV-0084`, tutti già mergiati.
- Riutilizzato senza modifiche il reticolo di marcatura sigillato di C4
  (`ocor_runtime.c4_marking`: `MarkingEngine`/`MarkingSchemeDefinition`/
  `MarkingSet`/`is_authorized`); aggiunto `spikes/jena_marking/adapter.py`
  (nuovo) con un `JenaMarkingProjectionAdapter` reale contro Fuseki live
  (dataset in-memory preconfigurato `/ocor` dal `CMD ["--mem", "/ocor"]`
  di `infra/fuseki/Dockerfile`, SPARQL 1.1 Query/Update via HTTP).
- Design chiave: `list_authorized` esegue un'UNICA query SPARQL che
  congiunge risorsa e classificazione nello stesso pattern grafico (la
  "marking join" richiesta dai criteri di accettazione — una risorsa priva
  del triplo di classificazione non può mai comparire, nemmeno con la
  clearance più alta); `count_authorized`/`exists_authorized` sono
  deliberatamente derivate dallo stesso risultato filtrato di
  `list_authorized` invece che da query SPARQL COUNT/ASK indipendenti, così
  da non poter mai divergere (soddisfa strutturalmente il criterio negativo
  "count ... leak").
- **Probe empirico reale contro Fuseki, bug trovato e corretto prima di
  sigillare**: interrogare `/ocor/sparql` senza un header `Accept`
  esplicito restituisce SPARQL-XML, non JSON — la prima esecuzione dei
  test falliva con `json.JSONDecodeError`; corretto inviando sempre
  `Accept: application/sparql-results+json`.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0018.py` (6 test, tutti
  contro Fuseki reale, nessun mock): filtro per clearance; count mai
  divergente dalla lista autorizzata; dimostrazione diretta che un COUNT
  SPARQL grezzo e cieco alla marcatura perderebbe informazione (differisce
  dal conteggio autorizzato) mentre l'API pubblica non lo espone mai;
  `exists_authorized` restituisce la stessa forma (`bool` `False`) per una
  risorsa proibita e per una mai esistita, indistinguibili; una risorsa
  senza il triplo di classificazione non è mai divulgata nemmeno con
  `TOP_SECRET`; il payload restituito a una clearance bassa non contiene
  mai, in nessuna forma, contenuto non autorizzato.
- **Lezione applicata proattivamente da `OCOR-DEV-0017`**: prima di aprire
  la PR, verificato che né Fuseki fosse provisionato in CI — aggiunto
  preventivamente uno step "Build and start Fuseki" (build della stessa
  immagine pinnata di `infra/fuseki/Dockerfile` + `docker run` + attesa di
  salute reale) ai 3 workflow già corretti per TypeDB in `OCOR-DEV-0017`
  (`delivery-activation`, `rccad-methodology`, `validation-closure`), dato
  che l'immagine è costruita da sorgente e non può essere dichiarata come
  `services:` con una semplice `image:`. Rieseguita localmente l'intera
  ricetta CI (build, run su porta alternativa, attesa di salute, query
  SPARQL reale, pulizia) prima di aggiungerla ai workflow, senza mai
  toccare lo stack `ocor-bootstrap` live.
- `scripts/validate_language_policy.py` verificato: nessuna nuova area
  necessaria.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file,
  `spikes/` e `tests/` fuori scope per policy), `validate_rccad.py` PASS,
  `validate_language_policy.py` PASS, `validate_ocor_change_scope.py` PASS
  (12 percorsi), `yaml.safe_load` dei 3 workflow modificati PASS, pytest
  completo con `OCOR_LIVE_POSTGRES_DSN` locale: `2 failed, 636 passed, 0
  skipped, 0 errors` (stessi 2 fallimenti noti e preesistenti del pin
  dell'interprete, +6 rispetto alla fase precedente),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo il
  consueto doppio-run di assestamento self-hash.
- Evidenza sigillata contro Fuseki reale, incluso il rehearsal completo
  della ricetta CI: `reports/evidence/G2/OCOR-DEV-0018.json` +
  `reports/evidence/G2/OCOR-DEV-0018.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo, 73 righe).
  `scripts/validate_runtime_evidence.py --task OCOR-DEV-0018 --non-skipped`
  PASS.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: push del branch
  `governed/ocor-dev-0018-jena-marking-safe-projection-spike`, apertura
  PR, polling CI, merge a gate verdi, verifica SHA post-merge. Poi
  proseguire con l'ultimo spike G2 dello stesso wave 11: `OCOR-DEV-0021`
  (SPIKE latenza e semantica di fallimento identity-policy).
- `OCOR-DEV-0018`: tutti e 13 i check verdi al primo push (il fix CI
  proattivo per Fuseki ha funzionato senza alcun ciclo di riparazione). PR
  #79 mergiata (`0b3d855c09f50be583a970868ed19375ef4d0802`), SHA
  post-merge verificata.

## 2026-09-13 — Disposizione del Product Owner: escalation Fase 3 componente 1

- Iterazione a sé, non backlog: esegue la disposizione esplicita e
  verbatim del Product Owner su
  `PHASE3-COMPONENT1-CANONICAL-KERNEL-MIGRATION-THRESHOLD-EXCEEDED`
  (registrata in `reports/development/PHASE3_LANGUAGE_MIGRATION_DECISION.md`
  §5, in attesa di lui dal completamento della Fase 3).
- **Decisione**: `RINVIATA`, non respinta. Nessuna decisione di migrazione
  aperta per il kernel di canonicalizzazione; il candidato e la misura
  sigillata restano registrati e validi.
- Aggiunta una nuova §8 in coda a
  `reports/development/PHASE3_LANGUAGE_MIGRATION_DECISION.md` — le sezioni
  1–7 (misura sigillata, numeri inclusi) lasciate byte-per-byte intatte,
  verificato con `git diff --stat` (105 righe, sole inserzioni). La §8
  riporta: la decisione; la motivazione a 4 punti dettata dal Product
  Owner, trascritta testualmente come richiesto ("da riportare come
  tale"), senza editorializzarla; la condizione di riapertura falsificabile
  a 3 rami (a/b/c); i vincoli osservati; la verifica del record decisionale
  formale; il nuovo stato dell'escalation.
- **Verifica del record decisionale formale** (richiesta esplicitamente dal
  Product Owner, con l'istruzione di non coniare un identificativo se non
  richiesto): confrontato con `DEC-212` (adozione di una nuova politica,
  registrata in `OCOR_Decision_Register_v1.6_APPROVED.md`) e con le
  escalation precedenti di questo mandato già dispositate senza un nuovo
  `DEC-*` (`PHASE2-4-BACKLOG-GENERATOR-DRIFT`, risolta in PR #67;
  `GITHUB-BRANCH-PROTECTION-001`, compensata). Questa disposizione non
  adotta alcuna nuova politica, non cambia alcuna soglia, non autorizza
  alcuna migrazione: rientra nella seconda categoria. **Nessun nuovo
  `DEC-*` coniato**; aggiornati solo i documenti esistenti, come richiesto.
- Aggiornato `reports/development/EXECUTION_STATE.json`:
  `mandate_phase_status.phase_3_benchmark.escalations` passa da `OPEN` a
  `DISPOSED_DEFERRED`, con la stessa motivazione e condizione di
  riapertura.
- Vincoli tassativi rispettati e verificati: soglie del §3 di
  `OCOR_LANGUAGE_POLICY.md` non toccate; `OI-024` non chiuso; nessun
  `ASM-*`/`RSK-*` modificato; nessuna modifica al codice del kernel di
  canonicalizzazione (`ocor-runtime/src/ocor_runtime/canonical.py`);
  nessuna promozione di `E1`/`E2`/requisiti a `Verified`, nessun claim di
  conformità runtime.
- Nota di trasparenza (non una correzione della disposizione, che resta
  quella dettata dal Product Owner e riportata testualmente): il punto 2
  della motivazione cita `OI-024` come l'open item collegato al budget
  ipotetico di latenza; il §3 dello stesso documento
  `OCOR_LANGUAGE_POLICY.md` contiene già una nota di correzione secondo cui
  l'open item che governa effettivamente le soglie numeriche di
  performance è `OI-008`, mentre `OI-024` governa le soglie di
  rischio/costo per l'autorità dual-control (`DEC-131`/`FR-136`/`FR-137`).
  La motivazione è stata trascritta come dettata, per istruzione esplicita
  ("da riportare come tale"); questa nota segnala la tensione testuale
  senza alterare la decisione, che è comunque conservativa (nessuna
  migrazione aperta) e indipendente da quale identificativo `OI-*` sia
  citato in questo punto.
- Questa iterazione non tocca codice sorgente né test: gate locali e
  regressione completa rieseguiti comunque per protocollo standard,
  confermati invariati.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file),
  `validate_rccad.py` PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS, pytest completo con
  `OCOR_LIVE_POSTGRES_DSN` locale invariato rispetto alla baseline nota,
  `validate_ocor_development_plan.py --authorized-extension` PASS.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: push del branch
  `governed/phase3-component1-escalation-disposition-deferred`, apertura
  PR, polling CI, merge a gate verdi, verifica SHA post-merge. Il referto
  finale del mandato dovrà riportare questa disposizione fra gli esiti.
  Poi riprendere il backlog da dove era: l'ultimo spike G2 del wave 11,
  `OCOR-DEV-0021` (SPIKE latenza e semantica di fallimento
  identity-policy).
- Disposizione Fase 3: PR #80 mergiata
  (`59521ae00218ea84e8b74a9cee483b172cdfd8ec`), tutti i check verdi, SHA
  post-merge verificata.

## 2026-09-13 — Backlog: OCOR-DEV-0021 (SPIKE identity-policy latency and failure semantics)

- Ultimo spike G2 del wave 11. Dipende da `OCOR-DEV-0006`, `OCOR-DEV-0014`,
  `OCOR-DEV-0084`, tutti già mergiati.
- Riutilizzati senza modifiche i port di sicurezza sigillati di
  `OCOR-DEV-0014` (`ocor_runtime.security.ports`:
  `ControlName`/`ControlStatus`/`SecurityControlError`/
  `require_available`) e l'harness di fault-injection sigillato di
  `OCOR-DEV-0083` (`fault_command`/`http_reachable`/`_poll`); aggiunto
  `spikes/control_plane_latency/probe.py` (nuovo) con `bounded_probe`
  (round-trip HTTP reale con deadline dichiarata, restituisce sempre uno
  `ControlStatus` più un `AuditEvent` correlato, sia per successo che per
  fallimento) e `decide_with_fail_closed_default` (delega interamente a
  `require_available` — un controllo non disponibile può solo sollevare,
  mai concedere).
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0021.py` (7 test, tutti
  contro OPA/Keycloak/OpenBao reali, nessun mock): successo entro la
  deadline per i tre controlli; `require_available` non concede mai per
  nessun controllo incluso `WORKLOAD_IDENTITY`; due cicli reali di
  fault-injection pausa/ripresa (OPA, OpenBao) che provano negazione entro
  la deadline dichiarata con evidenza di audit correlata, poi recupero;
  evidenza di audit correlata su entrambi i percorsi successo/fallimento.
- **Prima iterazione CI (PR #81, primo push)**: 3 check rossi
  (`delivery-activation`, `rccad-methodology`, `validation-closure`) con
  `"No such container: ocor-bootstrap-opa-1"` — causa radice: i container
  CI erano nominati `opa`/`keycloak`/`openbao`, ma `fault_command()`
  sigillato (`OCOR-DEV-0083`) costruisce il nome atteso come
  `ocor-bootstrap-<service>-1`, la convenzione di `docker compose`.
  Corretto rinominando ogni `docker run --name` nei 3 workflow
  (`fuseki`/`opa`/`keycloak`/`openbao`) alla convenzione attesa — nessuna
  modifica a test o adapter, il disallineamento era solo nel
  provisioning CI. Evidenza aggiornata nello stesso commit/PR.
- **Provisioning CI proattivo**: aggiunti OPA/Keycloak/OpenBao reali ai 3
  workflow PRIMA di aprire la PR (tutte e 3 immagini pre-costruite e
  pinnate, a differenza di Fuseki), con ricetta rehearsed localmente su
  porte alternative (8182/8081/8201) prima dell'aggiunta ai workflow.
- Secondo push: tutti e 13 i check verdi. PR #81 mergiata
  (`9e97e1c19c7ac82bdfe074e28991493ac798b1c1`), SHA post-merge verificata.
  Con questo si chiude l'intero wave 11 degli spike G2
  (`OCOR-DEV-0016`/`0017`/`0018`/`0021`).
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file),
  `validate_rccad.py` PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS, `yaml.safe_load` dei 3 workflow
  PASS, pytest completo con `OCOR_LIVE_POSTGRES_DSN` locale:
  `2 failed, 643 passed, 0 skipped, 0 errors` (stessi 2 fallimenti noti e
  preesistenti del pin dell'interprete), `validate_ocor_development_plan.py
  --authorized-extension` PASS dopo il consueto doppio-run.
- Evidenza sigillata contro OPA/Keycloak/OpenBao reali, incluso il fix CI:
  `reports/evidence/G2/OCOR-DEV-0021.json` +
  `reports/evidence/G2/OCOR-DEV-0021.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo, 64 righe).
  `scripts/validate_runtime_evidence.py --task OCOR-DEV-0021 --non-skipped`
  PASS.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.

## 2026-09-13 — Backlog: OCOR-DEV-0024 (SPIKE cross-compartment non-interference)

- Prossimo task eseguibile determinato direttamente da
  `docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json` e
  `completed_evidence_tasks` (lo stato interno di
  `scripts/ocor_autonomous_delivery.py --status` resta inaffidabile, mai
  aggiornato dall'esecuzione manuale di questa sessione). Con la chiusura
  del wave 11, il wave 12 diventa pronto: `OCOR-DEV-0024`/`0025`/`0028`/
  `0029`. Selezionato `OCOR-DEV-0024` per ordine numerico. Dipende da
  `OCOR-DEV-0018`, `OCOR-DEV-0021`, `OCOR-DEV-0023`, tutti già mergiati.
- **Design**: questo spike compone TRE spike già sigillati invece di
  costruirne uno nuovo da zero — la proiezione marking-safe di Jena
  (`OCOR-DEV-0018`), il probe bounded del control-plane identity/policy
  (`OCOR-DEV-0021`), e l'oracolo di partizionamento vettoriale Qdrant
  (`OCOR-DEV-0023`, che già includeva un harness Qdrant reale
  auto-provisionato e test di non-interferenza per singolo backend) —
  tutti riutilizzati senza modifiche. L'unica astrazione nuova è
  `spikes/non_interference/equivalence.py`
  (`assert_observationally_equivalent`), un confronto a coppie con
  messaggio di fallimento preciso per asse, riutilizzato su ogni asse
  (content/existence/rank/count) e ogni backend.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0024.py` (7 test, tutti
  contro backend reali, nessun mock): vista Jena a bassa clearance
  invariata (content/count/esistenza) dopo l'ingest di una risorsa
  `TOP_SECRET`; rank e count di una ricerca Qdrant sulla partizione bassa
  invariati dopo l'upsert di 200 vettori estranei sulla partizione alta;
  la finestra di timing bounded di Qdrant ammette ancora il tempo
  osservato dopo la popolazione della partizione alta; l'accesso a una
  partizione alta reale e a una fabbricata/inesistente vengono negati con
  lo stesso errore identico; la disponibilità e il timing del probe OPA
  non sono influenzati da un ciclo reale di fault-injection
  pausa/ripresa sull'OpenBao non correlato; query ripetute a bassa
  clearance su Jena e Qdrant restano identiche dopo la popolazione alta
  in entrambi i backend; `assert_observationally_equivalent` solleva
  realmente su una divergenza costruita (non vacuamente vera).
- Nessun nuovo provisioning CI necessario: OPA/OpenBao/Fuseki sono già
  servizi reali da `OCOR-DEV-0018`/`0021`; Qdrant si auto-provisiona con
  un vero `docker run` all'interno del test stesso, lo stesso meccanismo
  già usato con successo da `OCOR-DEV-0023` negli stessi job CI.
- Corretto un disallineamento nei file di stato scoperto all'inizio di
  questa iterazione: `MODEL_HANDOFF.json` non era stato aggiornato al
  merge di `OCOR-DEV-0021` (PR #81) nell'iterazione precedente —
  `scripts/validate_rccad.py` ha rilevato `RCCAD-STATE-HANDOFF-DRIFT`
  (baseline_commit e branch disallineati fra `EXECUTION_STATE.json` e
  `MODEL_HANDOFF.json`); corretto aggiornando `MODEL_HANDOFF.json` con il
  completamento di `OCOR-DEV-0021` prima di proseguire.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file,
  `spikes/` e `tests/` fuori scope per policy), `validate_rccad.py` PASS
  (dopo la correzione del drift), `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (11 percorsi), pytest completo con
  `OCOR_LIVE_POSTGRES_DSN` locale: `2 failed, 650 passed, 0 skipped, 0
  errors` (stessi 2 fallimenti noti e preesistenti, +7 rispetto alla fase
  precedente), `validate_ocor_development_plan.py --authorized-extension`
  PASS dopo il consueto doppio-run di assestamento self-hash.
- Evidenza sigillata contro backend reali compositi (Fuseki, Qdrant
  auto-provisionato, OPA/OpenBao con fault-injection reale):
  `reports/evidence/G2/OCOR-DEV-0024.json` +
  `reports/evidence/G2/OCOR-DEV-0024.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo, 82 righe).
  `scripts/validate_runtime_evidence.py --task OCOR-DEV-0024 --non-skipped`
  PASS.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: push del branch
  `governed/ocor-dev-0024-cross-compartment-non-interference-spike`,
  apertura PR, polling CI, merge a gate verdi, verifica SHA post-merge.
  Poi determinare il prossimo task pronto del wave 12 in ordine numerico:
  `OCOR-DEV-0025` (SPIKE distributed deletion saga).
- `OCOR-DEV-0024`: tutti e 13 i check verdi al primo push (l'auto-
  provisioning di Qdrant ha funzionato senza problemi in CI). PR #82
  mergiata (`e003fdc453420f8d5942dd9c39261d1ccf0a73ea`), SHA post-merge
  verificata.

## 2026-09-13 — Backlog: OCOR-DEV-0025 (SPIKE distributed deletion saga)

- Secondo task del wave 12. Dipende da `OCOR-DEV-0016`, `OCOR-DEV-0017`,
  `OCOR-DEV-0018`, `OCOR-DEV-0019`, `OCOR-DEV-0023`, tutti già mergiati.
- Aggiunto `spikes/memory_deletion/saga.py` (nuovo) con
  `run_deletion_saga`: tenta un tombstone su ogni target, poi — a
  prescindere dall'esito di `tombstone()` — riverifica sempre
  indipendentemente con `contains()` come unico arbitro fra riconosciuto
  e rimanente. Nessun target è mai creduto sulla parola; un target
  irraggiungibile fallisce chiuso. Target reali: PostgreSQL (metadata),
  TypeDB (contenuto), Qdrant auto-provisionato via `QdrantHarness`
  (`OCOR-DEV-0023`, sigillato, riutilizzato senza modifiche) per
  cache/indice.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0025.py` (4 test,
  tutti contro backend reali, nessun mock): cancellazione completa sui 3
  backend con stato `DELETED`; un ciclo reale di fault-injection
  pausa/ripresa su TypeDB durante la cancellazione, che riporta
  `DELETION_INCOMPLETE` con il contenuto genuinamente ancora presente,
  poi recupera e un retry successivo riporta `DELETED`; un target
  "bugiardo" che dichiara successo senza cancellare nulla, dimostrando
  che la saga non si fida mai del segnale del backend; un target
  irraggiungibile classificato correttamente come rimanente.
- **Provisioning CI proattivo applicato PRIMA di aprire la PR**: scoperto
  che il provisioning CI di TypeDB usava un blocco nativo `services:` di
  GitHub Actions, che nomina il container internamente e non come
  `ocor-bootstrap-typedb-1` — la stessa categoria di problema già
  incontrata reattivamente in `OCOR-DEV-0021` per OPA/Keycloak/OpenBao.
  Convertito a un passo `docker run --name ocor-bootstrap-typedb-1`
  esplicito (stessa immagine pinnata) nei 3 workflow, rehearsed
  localmente su porte alternative prima dell'aggiunta.
- Tutti e 13 i check verdi al primo push. PR #83 mergiata
  (`c13a634b94bd1b6f6aed52e54d252746242e050d`), SHA post-merge
  verificata.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (45 file),
  `validate_rccad.py` PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS, `yaml.safe_load` dei 3 workflow
  PASS, pytest completo con `OCOR_LIVE_POSTGRES_DSN` locale: `2 failed,
  654 passed, 0 skipped, 0 errors` (stessi 2 fallimenti noti e
  preesistenti), `validate_ocor_development_plan.py --authorized-extension`
  PASS dopo il consueto doppio-run.
- Evidenza sigillata contro PostgreSQL/TypeDB/Qdrant reali, incluso il
  fix CI proattivo: `reports/evidence/G2/OCOR-DEV-0025.json` +
  `reports/evidence/G2/OCOR-DEV-0025.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo, 55
  righe). `scripts/validate_runtime_evidence.py --task OCOR-DEV-0025
  --non-skipped` PASS.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.

## 2026-09-13 — Backlog: OCOR-DEV-0028 (Build retained C1 compiler slice)

- Prossimo task pronto del wave 12 determinato direttamente dal backlog:
  con `OCOR-DEV-0025` chiuso, gli unici task pronti rimasti del wave 12
  sono `OCOR-DEV-0028` e `OCOR-DEV-0029`, **entrambi gate `G3`** (non
  `G2`) — il primo passaggio da spike a componente runtime *retained* di
  questa sessione. Selezionato `OCOR-DEV-0028` per ordine numerico.
  Dipende da `OCOR-DEV-0011`, `OCOR-DEV-0016`, entrambi già mergiati.
- **Componente puro, nessun servizio esterno necessario**: implementata
  la porzione minima conforme al contratto dei port C1 già sigillati
  (`OCOR-DEV-0011`, `ocor_runtime.c1.ports`, riutilizzati senza
  modifiche) in `ocor-runtime/src/ocor_runtime/c1/compiler.py` (nuovo):
  `RetainedOacParser` (parsing YAML/JSON reale), `RetainedSemanticValidator`
  (contratto di forma minimo id/fields del DSL), `RetainedCanonicalIrBuilder`
  (assembla un documento core deterministico più un artefatto di
  metadati di migrazione). `signature_envelope_ref` è un placeholder non
  firmato dichiarato onestamente come tale; la firma reale (`IrSigner`)
  resta un Protocol sigillato non ancora implementato, task futuro
  separato.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0028.py` (8 test, puri
  in-memory, deterministici, nessun servizio esterno): fixture DSL mista
  YAML/JSON che compila con successo con metadati di migrazione;
  verifica di digest riproducibile tramite l'oracolo sigillato
  `verify_deterministic_build`; rifiuto di un import non risolto (già
  imposto dal costruttore sigillato di `CompilerRequest`); rifiuto di
  YAML malformato, chiavi richieste mancanti, `fields` non-mapping, e
  mismatch dell'id dichiarato, ciascuno con il `DiagnosticCode` corretto;
  prova diretta che nessun percorso di rifiuto restituisce mai un
  `CanonicalIrRelease` parziale.
- Creato `reports/evidence/G3/MANIFEST.json` **da zero** — il primo
  manifest di evidenza gate `G3` sigillato da questa sessione.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (46 file,
  `ocor-runtime/src` pienamente in scope per questo gate, a differenza
  degli spike), `validate_rccad.py` PASS, `validate_language_policy.py`
  PASS, `validate_ocor_change_scope.py` PASS (8 percorsi), pytest
  completo con `OCOR_LIVE_POSTGRES_DSN` locale: `2 failed, 662 passed, 0
  skipped, 0 errors` (stessi 2 fallimenti noti e preesistenti),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo
  il consueto doppio-run di assestamento self-hash.
- Evidenza sigillata: `reports/evidence/G3/OCOR-DEV-0028.json` +
  `reports/evidence/G3/OCOR-DEV-0028.log`.
  `scripts/validate_runtime_evidence.py --task OCOR-DEV-0028 --non-skipped
  --manifest reports/evidence/G3/MANIFEST.json` PASS.
- Aggiornamento dei tre file di stato eseguito in un'unica passata,
  recuperando anche i merge non ancora sincronizzati di `OCOR-DEV-0024`
  (PR #82) e `OCOR-DEV-0025` (PR #83) dalle iterazioni precedenti, per
  evitare un nuovo `RCCAD-STATE-HANDOFF-DRIFT`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- Prossima azione: push del branch
  `governed/ocor-dev-0028-c1-compiler-slice`, apertura PR, polling CI,
  merge a gate verdi, verifica SHA post-merge. Poi proseguire con
  `OCOR-DEV-0029` (Build retained C3 canonical commit slice, gate `G3`,
  dipende solo da `OCOR-DEV-0016`, già mergiato).
- `OCOR-DEV-0028`: tutti e 13 i check verdi al primo push. PR #84
  mergiata (`b8170f3c5ca9500d38faf95d2b2d01c7ded41850`), SHA post-merge
  verificata.

## 2026-09-13 — Backlog: OCOR-DEV-0029 (Build retained C3 canonical commit slice)

- Ultimo task del wave 12. Dipende solo da `OCOR-DEV-0016`, già mergiato
  (`OCOR-DEV-0013`, che definisce i port C3 sigillati riutilizzati qui,
  è un task G1 già chiuso in una fase precedente a questa sessione).
- Implementati tutti e 5 i port C3 sigillati (`ocor_runtime.c3.ports`,
  riutilizzati senza modifiche) come `PostgresC3Service`:
  `GovernedCommitPort` (`commit`), `CanonicalReadPort` (`read`),
  `RevisionPort` (`current_revision`), `OutboxRelayPort`
  (`claim_batch`/`acknowledge`), `RecoveryPort` (`reconcile`). Backend
  reale PostgreSQL, generalizzando la tecnica di locking/atomicità a
  concorrenza reale già provata dagli spike C3 sigillati
  (`spikes.c3_atomicity.oracle`, `OCOR-DEV-0015`; `spikes.c3_backend`,
  `OCOR-DEV-0016`) in un'implementazione a forma di produzione che parla
  direttamente le dataclass sigillate, non dict ad-hoc.
- **Violazione architetturale reale trovata e corretta prima di
  sigillare**: la prima versione di `service.py` importava `psycopg`
  direttamente; `scripts/validate_rccad.py` ha correttamente segnalato
  `AFF-002`/`AFF-006` ("infrastructure client leaked outside adapters"),
  la regola di fitness architetturale già sigillata (riga 8 di
  `OCOR_LANGUAGE_POLICY.md`) mai innescata prima in questa sessione,
  dato che ogni precedente task su backend reale viveva sotto `spikes/`
  e non sotto `ocor-runtime/src/`. Corretto estraendo ogni riferimento a
  `psycopg` in un nuovo `ocor-runtime/src/ocor_runtime/c3/adapters/postgres.py`
  (`PostgresC3Adapter`), che espone a `service.py` solo tipi Python
  semplici privi di `psycopg` — il primo sotto-albero `adapters/` che
  questa consegna abbia mai avuto bisogno di creare.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0029.py` (9 test,
  tutti contro PostgreSQL reale, nessun mock): conformità `isinstance` a
  ogni Protocol sigillato; commit atomico che persiste stato/revisione/
  outbox insieme; replay idempotente; rifiuto per conflitto di
  idempotenza e conflitto di revisione; due comandi distinti in race
  sulla stessa revisione (vince esattamente uno); un vero crash di
  processo (subprocess) a metà commit — zero visibilità parziale, retry
  riuscito; una vera corruzione simulata (una riga outbox derivata
  cancellata direttamente contro il database, riparata da `reconcile()`);
  claim/acknowledge dell'outbox.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (49 file),
  `validate_rccad.py` PASS (dopo la correzione della violazione
  architetturale), `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (10 percorsi), pytest completo
  con `OCOR_LIVE_POSTGRES_DSN` locale: `2 failed, 671 passed, 0 skipped,
  0 errors` (stessi 2 fallimenti noti e preesistenti),
  `validate_ocor_development_plan.py --authorized-extension` PASS dopo
  il consueto doppio-run.
- Evidenza sigillata: `reports/evidence/G3/OCOR-DEV-0029.json` +
  `reports/evidence/G3/OCOR-DEV-0029.log`, aggiunta a
  `reports/evidence/G3/MANIFEST.json` (diff puramente additivo, 100
  righe). `scripts/validate_runtime_evidence.py --task OCOR-DEV-0029
  --non-skipped --manifest reports/evidence/G3/MANIFEST.json` PASS.
- Aggiornamento dei tre file di stato eseguito SUBITO in questa stessa
  iterazione (non rimandato), recuperando anche il merge di
  `OCOR-DEV-0028` (PR #84) non ancora sincronizzato, per istruzione
  esplicita del Product Owner.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0029`: `gh pr create` ha incontrato due errori transitori
  dell'API di GitHub (502 Bad Gateway, poi un errore GraphQL di classe
  500), entrambi non correlati al contenuto del repository; riuscito al
  terzo tentativo come PR #85. Tutti e 13 i check verdi al primo push.
  PR #85 mergiata (`7e1cf57bfe98c314f2cfb1ae0469249428e0ab8f`), SHA
  post-merge verificata. Con questo si chiude l'intero wave 12
  (`OCOR-DEV-0024`/`0025`/`0028`/`0029`).

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0029 (post-merge)

- Per istruzione esplicita del Product Owner ("aggiorna i tre file di
  stato SUBITO... non rimandare"), sincronizzazione immediata dei tre
  file di stato subito dopo il merge della PR #85, su un branch
  dedicato (`governed/state-sync-ocor-dev-0029`), invece di rimandarla
  al commit dell'iterazione successiva come accaduto in precedenza per
  `OCOR-DEV-0024`/`0025` e per `OCOR-DEV-0028`.
- `baseline_commit` aggiornato a
  `7e1cf57bfe98c314f2cfb1ae0469249428e0ab8f` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `branch` allineato al
  branch di questa stessa iterazione di sincronizzazione. Verificata
  l'assenza di `RCCAD-STATE-HANDOFF-DRIFT` tramite
  `scripts/validate_rccad.py --root .`.
- Nessun codice sorgente toccato: gate locali (sha256sum, ruff, mypy,
  RCCAD, language-policy, change-scope, plan-validator, pytest
  completo) rieseguiti comunque per protocollo standard e confermati
  invariati.
- Prossima azione: determinare la prontezza del wave 13 direttamente da
  `docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json` e
  `completed_evidence_tasks`. Candidati noti con dipendenze già
  soddisfatte: `OCOR-DEV-0026` (SPIKE restore without resurrection) e
  `OCOR-DEV-0027` (SPIKE deterministic context-assembly replay).

## 2026-09-13 — Backlog: OCOR-DEV-0026 (SPIKE restore without resurrection)

- Ricalcolata la prontezza del wave 13 dopo il merge di `OCOR-DEV-0029`:
  ready set = `{OCOR-DEV-0026, OCOR-DEV-0027, OCOR-DEV-0030}` —
  `OCOR-DEV-0030` è diventato pronto solo ora, dato che la sua
  dipendenza `OCOR-DEV-0029` è appena stata mergiata. Selezionato
  `OCOR-DEV-0026` per ordine numerico.
- Verifica proattiva del provisioning CI prima di scrivere codice:
  confermato che PostgreSQL, TypeDB e Qdrant sono già backend reali
  già provisionati nei 3 workflow CI (da `OCOR-DEV-0016`/`0017`/`0025`)
  — nessun gap, nessuna modifica CI necessaria.
- Composto lo spike sigillato `OCOR-DEV-0025`
  (`spikes.memory_deletion.saga`: `DeletionStatus`/`DeletionTarget`/
  `run_deletion_saga` più i tre target concreti Postgres/TypeDB/Qdrant,
  tutti riutilizzati senza modifiche) con un nuovo
  `spikes/restore_no_resurrection/journal.py`: un `TombstoneJournal`
  durevole, sostenuto da PostgreSQL reale; `record_deletion()`, che
  tombstona il journal solo quando la saga conferma indipendentemente
  la cancellazione completa su ogni target; `restore_from_backup()`,
  che consulta il journal PRIMA di toccare qualunque target — un
  elemento tombstonato viene rifiutato, e un journal irraggiungibile
  viene rifiutato allo stesso modo (fail-closed, mai trattato come
  "sicuro da ripristinare").
- Decisione progettuale deliberata: per il test di fault-injection
  "journal irraggiungibile" non è stato scelto un vero pause/unpause
  del container Postgres condiviso `ocor-bootstrap-postgresql-1` (usato
  concorrentemente da molti altri task sigillati, e provisionato in CI
  tramite un blocco nativo `services:` che `fault_command()` non può
  bersagliare), ma un vero rifiuto di connessione TCP a livello di
  sistema operativo contro una porta locale genuinamente chiusa — un
  guasto di rete reale, non un'eccezione simulata, a un raggio
  d'impatto molto più basso rispetto a un più ampio refactoring CI.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0026.py` (6 test,
  tutti contro backend reali, nessun mock): restore di un elemento mai
  cancellato riesce su tutti e 3 i backend; restore di un elemento
  tombstonato viene rifiutato e il contenuto non riappare mai;
  `record_deletion` tombstona il journal solo quando ogni target
  conferma la cancellazione completa (un target che mente ma resta
  incompleto non genera mai una scrittura nel journal); il restore
  consulta il journal prima di toccare qualunque target (dimostrato con
  una spia sull'ordine delle chiamate); un journal irraggiungibile
  fallisce in modo chiuso e non risuscita mai nulla; il restore di un
  elemento diverso, mai tombstonato, non è influenzato dal tombstone di
  un elemento non correlato.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (49 file,
  invariato — `spikes/` e `ocor-runtime/tests/` restano fuori dallo
  scope di mypy), `validate_rccad.py` PASS, `validate_language_policy.py`
  PASS, `validate_ocor_change_scope.py` PASS (7 percorsi), pytest
  completo con `OCOR_LIVE_POSTGRES_DSN` locale: `2 failed, 648 passed,
  0 skipped, 0 errors` (stessi 2 fallimenti noti e preesistenti) più
  `29 passed` per le 3 suite `reports/tests/`,
  `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run
  (`FAIL` poi `PASS`), sempre con `--base-ref origin/main` per
  rispecchiare esattamente la CI (non il `BASE_COMMIT` di default,
  molto vecchio).
- Evidenza sigillata: `reports/evidence/G2/OCOR-DEV-0026.json` +
  `reports/evidence/G2/OCOR-DEV-0026.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo, 73
  righe, inserimento chirurgico per preservare lo storico esistente).
- Aggiornamento dei tre file di stato eseguito in questa stessa
  iterazione (non rimandato).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0026`: tutti e 13 i check verdi al primo push. PR #87
  mergiata (`a78d054d22ac85839181c833a0acc8deed8aa9c8`), SHA
  post-merge verificata.

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0026 (post-merge)

- Per istruzione esplicita del Product Owner, sincronizzazione
  immediata dei tre file di stato subito dopo il merge della PR #87,
  su un branch dedicato (`governed/state-sync-ocor-dev-0026`),
  rispecchiando lo stesso schema già usato per `OCOR-DEV-0029`/PR #86.
- `baseline_commit` aggiornato a
  `a78d054d22ac85839181c833a0acc8deed8aa9c8` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `branch` allineato al
  branch di questa iterazione di sincronizzazione. Verificata l'assenza
  di `RCCAD-STATE-HANDOFF-DRIFT`.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- Prossima azione: determinare il prossimo task del wave 13
  direttamente dal backlog JSON. Candidati noti: `OCOR-DEV-0027`
  (SPIKE deterministic context-assembly replay) e `OCOR-DEV-0030`
  (Build retained governed-action slice, gate G3, diventato pronto dopo
  il merge di `OCOR-DEV-0029`).

## 2026-09-13 — Backlog: OCOR-DEV-0027 (SPIKE deterministic context-assembly replay)

- Ricalcolata la prontezza del wave 13 dal backlog JSON: ready set =
  `{OCOR-DEV-0027, OCOR-DEV-0030}`. Selezionato `OCOR-DEV-0027` per
  ordine numerico.
- Verifica proattiva del provisioning CI: confermato che Qdrant si
  autoprovisiona già nei 3 workflow CI (da `OCOR-DEV-0023`/`0024`/
  `0025`) — nessun gap, nessuna modifica CI necessaria.
- Implementato `spikes/context_replay/replay.py`: dimostra che il
  digest di ricevuta di un context-assembly è funzione pura e
  deterministica di esattamente cinque dimensioni pinnate — versioni
  degli item, ordinamento (una vera ricerca di similarità coseno
  contro Qdrant, riusando senza modifiche `QdrantHarness` da
  `OCOR-DEV-0023`), redazioni, troncamento e rappresentazione. Il
  digest di ricevuta usa `ocor_runtime.kernel.canonical.canonical_digest`
  (canonicalizzazione RFC 8785 sigillata), mai un hash fatto a mano.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0027.py` (8 test,
  tutti contro un vero container Qdrant autoprovisionato, nessun
  mock): input pinnati identici riproducono un digest identico;
  cambiare la versione di un item cambia il digest; cambiare la
  redazione cambia il digest; cambiare il vettore di query cambia sia
  il vero ordinamento di ranking sia il digest; cambiare il
  troncamento cambia il digest e imposta il flag `truncated`; cambiare
  solo la versione di rappresentazione cambia il digest anche con
  ordinamento identico; due assemblaggi indipendenti sono provati
  equivalenti tramite l'helper sigillato `assert_observationally_equivalent`
  di `OCOR-DEV-0024` (riusato senza modifiche); un vero rifiuto di
  connessione TCP su una porta locale chiusa durante il ranking
  fallisce in modo chiuso (`ContextReplayError`) invece di restituire
  un contesto parziale silenzioso — stesso pattern a basso raggio
  d'impatto stabilito in `OCOR-DEV-0026`.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (49 file,
  invariato), `validate_rccad.py` PASS, `validate_language_policy.py`
  PASS, `validate_ocor_change_scope.py` PASS (7 percorsi), pytest
  completo con `OCOR_LIVE_POSTGRES_DSN` locale: `2 failed, 656 passed,
  0 skipped, 0 errors` (stessi 2 fallimenti noti) più `29 passed` per
  le 3 suite `reports/tests/`, `validate_ocor_development_plan.py
  --base-ref origin/main --authorized-extension` PASS dopo il consueto
  doppio-run (`FAIL` poi `PASS`).
- Evidenza sigillata: `reports/evidence/G2/OCOR-DEV-0027.json` +
  `reports/evidence/G2/OCOR-DEV-0027.log`, aggiunta a
  `reports/evidence/G2/MANIFEST.json` (diff puramente additivo, 91
  righe, inserimento chirurgico).
- Aggiornamento dei tre file di stato eseguito in questa stessa
  iterazione (non rimandato).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0027`: tutti e 13 i check verdi al primo push. PR #89
  mergiata (`53ad2e5bb76f7b59a5ffae9863b685338027edbe`), SHA
  post-merge verificata.

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0027 (post-merge)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #89, su un branch dedicato
  (`governed/state-sync-ocor-dev-0027`).
- `baseline_commit` aggiornato a
  `53ad2e5bb76f7b59a5ffae9863b685338027edbe` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0027`
  aggiunto a `completed_evidence_tasks`. Verificata l'assenza di
  `RCCAD-STATE-HANDOFF-DRIFT`.
- **Correzione**: `OCOR-DEV-0030` ha `parallel_wave=13` nel backlog
  JSON, la stessa wave di `OCOR-DEV-0026`/`0027` — il wave 13 NON è
  ancora chiuso interamente, contrariamente a quanto scritto in una
  bozza precedente di questo stesso commit prima della correzione.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- `OCOR-DEV-0027`: PR #90 mergiata (`c783d7c2b8b3e6824176764cbda0a683dd44c105`)
  sul commit corretto (13/13 check verdi), SHA post-merge verificata.

## 2026-09-13 — Backlog: OCOR-DEV-0030 (Build retained governed-action slice)

- Confermato dal backlog JSON: unico task pronto, gate `G3`,
  dipendente da `OCOR-DEV-0020`/`0021`/`0029` (tutti mergiati).
- Prima di scrivere codice, letto `docs/OCOR_LLD_v1.1.md` §§2.6/3.1/
  3.2/4: il workflow C6 completo è una FSM normativa a 44 transizioni
  (`ACT-T01`..`ACT-T31b`); questo task è la slice contract-compliant
  più piccola del percorso rappresentativo che un'azione a rischio
  attraversa — non l'intera FSM (di cui lo spike sigillato
  `OCOR-DEV-0020` prova già la fedeltà esecutiva strutturale).
- Scoperto, prima di scrivere qualunque cosa, che
  `ocor_runtime.c6_capabilities.CapabilityAuthority` (Authority) e
  `ocor_runtime.c7_emission.EmissionFence` (EMISSION-FENCE) esistono
  già come codice retained sigillato da una fase precedente della
  delivery — riusati direttamente senza modifiche. `Approval` e
  `Decision` sono gli unici due nuovi record realmente necessari,
  poiché nessun record Human Gate o Decision esisteva ancora.
- Implementato `ocor-runtime/src/ocor_runtime/c6/engine.py`:
  `GovernedActionEngine.execute()` attraversa, in ordine stretto,
  Authority (`G-AUTHORITY`), Human Gate (`G-APPROVAL`), Decision
  (`G-DECISION`) ed EMISSION-FENCE prima di qualunque effetto
  simulato, fail-closed a ogni gate. Componente puro, in-memory,
  deterministico — nessun backend esterno necessario (come la slice
  compilatore C1 di `OCOR-DEV-0028`), quindi nessuna preoccupazione
  `AFF-002`/`AFF-006` (zero import di client di backend diretti,
  verificato con `validate_rccad.py`).
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0030.py` (9 test):
  percorso felice completo attraverso tutti e quattro i gate fino
  all'effetto simulato; diniego all'Authority (lease con capability
  sbagliata); diniego all'Human Gate (approvazione mancante o
  esplicitamente rifiutata) per un'azione a rischio; un'azione non a
  rischio salta interamente l'Human Gate (`ACT-T07`, `NOT_REQUIRED`);
  diniego alla Decision (mancante o rifiutata, con rationale
  preservato); un sink che fallisce lascia il commit canonico durevole
  ma non rilasciato, con un retry sicuro sullo stesso fence; un test
  di fedeltà che traccia i quattro nomi dei gate fino alla tabella
  sigillata a 44 transizioni di `OCOR-DEV-0020` (verificata contro il
  digest LLD approvato), a riprova che i nomi non sono stati inventati
  indipendentemente.
- Gate locali tutti verdi: `sha256sum` 8/8, `ruff`, `mypy` (50 file,
  +1 rispetto a prima), `validate_rccad.py` PASS (tutti i 10 AFF
  `PASS_STATIC_PRECHECK`), `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (7 percorsi), pytest completo
  con `OCOR_LIVE_POSTGRES_DSN` locale: `2 failed, 665 passed, 0
  skipped, 0 errors` (stessi 2 fallimenti noti) più `29 passed` per le
  3 suite `reports/tests/`, `validate_ocor_development_plan.py
  --base-ref origin/main --authorized-extension` PASS dopo il
  consueto doppio-run.
- Evidenza sigillata: `reports/evidence/G3/OCOR-DEV-0030.json` +
  `reports/evidence/G3/OCOR-DEV-0030.log`, aggiunta a
  `reports/evidence/G3/MANIFEST.json` (diff puramente additivo, 100
  righe, inserimento chirurgico).
- Aggiornamento dei tre file di stato eseguito in questa stessa
  iterazione (non rimandato).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0030`: tutti e 13 i check verdi al primo push. PR #91
  mergiata (`c9ac9ca4615337193202846d06a4b5f6e38afcbc`), SHA
  post-merge verificata. Con questo si chiude l'intero wave 13
  (`OCOR-DEV-0026`/`0027`/`0030`).

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0030 (post-merge, chiusura wave 13)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #91, su un branch dedicato
  (`governed/state-sync-ocor-dev-0030`).
- `baseline_commit` aggiornato a
  `c9ac9ca4615337193202846d06a4b5f6e38afcbc` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0030`
  aggiunto a `completed_evidence_tasks`. Verificata l'assenza di
  `RCCAD-STATE-HANDOFF-DRIFT`.
- Ricalcolata la prontezza del prossimo wave dal backlog JSON
  (verificando `parallel_wave` su ogni candidato, come da lezione
  appresa in questa iterazione): ready set = `{OCOR-DEV-0031}`,
  `parallel_wave=14`, "Integrate first real C1-C8 synthetic mission
  thread", gate `G3`, dipendente da `OCOR-DEV-0017`/`0018`/`0019`/
  `0022`/`0024`/`0027`/`0028`/`0029`/`0030` (tutti mergiati) — un
  task di integrazione significativamente più ampio delle recenti
  slice a singolo componente.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- Prossima azione: leggere per intero la voce di `OCOR-DEV-0031` nel
  backlog JSON (expected_file_areas, acceptance criteria, backend
  reali richiesti) prima di progettare qualunque cosa, dato che è un
  task di integrazione multi-componente, non una slice singola.

## 2026-09-13 — Backlog: OCOR-DEV-0031 (Integrate first real C1-C8 synthetic mission thread)

- Letta per intero la voce del backlog: un unico file atteso
  (`ocor-runtime/tests/mission_thread/test_first_governed_slice.py`),
  nessun nuovo codice di produzione — un vero indizio che il task è
  puramente un test di integrazione.
- Letto per intero `docs/OCOR_LLD_v1.1.md` §§2.1-2.9/3/4 e il codice
  sorgente completo di ogni componente C1-C8 nominato come dipendenza
  dura, prima di progettare qualunque cosa. Confermato che ogni
  componente necessario esiste già come codice retained sigillato o
  spike sigillato: C1 → `ocor_runtime.c1.compiler` (`0028`); C2/C8 →
  `ocor_runtime.c2_identity`/`ocor_runtime.c8_agent` (retained,
  preesistenti a questa sessione); C3 →
  `ocor_runtime.c3.service.PostgresC3Service` (`0029`); C4 → TypeDB
  reale (`spikes.typedb_exact_commit.adapter`, `0017`), Fuseki reale
  (`spikes.jena_marking.adapter`, `0018`), context assembly su Qdrant
  reale (`spikes.context_replay.replay`, `0027`); C5 → Kafka reale
  autoprovisionato (`spikes.kafka_delivery.oracle`, `0019`); C6 →
  `ocor_runtime.c6.engine.GovernedActionEngine` (`0030`); C7 →
  `spikes.causal_reproducibility.oracle` (`0022`).
- **Scoperta rilevante**: `ocor_runtime.c5_actions.py` ("the complete
  ACT-T01…ACT-T31b action state machine") è la FSM generica OBSOLETA a
  32 stati (`DRAFT`/`PROPOSED`/`VALIDATED`, non gli stati reali
  `PROPOSAL_RECORDED`/`CONTROL_CHECK`/ecc. della LLD approvata) già
  documentata come tale altrove in questa sessione — confermato che
  non va riusata e che il lavoro appena fatto in `OCOR-DEV-0030` non è
  duplicativo.
- Implementato `ocor-runtime/tests/mission_thread/test_first_governed_slice.py`
  (5 test, tutti contro backend reali, nessun mock): un unico fixture
  content-addressed, identificato da un `correlation_id`, attraversa
  PostgreSQL/TypeDB/Fuseki/Qdrant/Kafka reali e produce ricevute
  correlate canonical/projection/event/causal/agent/action; il
  `causation_id` della query causale (C7) È l'`event_id` reale
  dell'azione governata (C6) — una vera catena causale, non
  un'etichetta condivisa. Test aggiuntivi: riproducibilità del
  ricevuta causale con gli stessi pin; un diniego all'Authority che
  blocca l'intero thread prima di qualunque effetto; l'applicazione
  reale della consistenza `EXACT_AT_COMMIT` su TypeDB contro un vero
  commit C3; un vero riavvio del broker Kafka autoprovisionato
  (isolato per-test, mai il container condiviso) che preserva la
  consegna durevole e ordinata.
- Due bug reali trovati e corretti durante la prima esecuzione: (1)
  la chiave di riga di Jena è `resource`, non `resource_id`; (2) un
  `EventSink` come funzione semplice viene chiamato come `sink(event)`
  senza `idempotency_key` nel percorso di fallback — corretto usando
  una classe che implementa il Protocol `emit()` sigillato, come nel
  pattern già stabilito da `OCOR-DEV-0030`. Un terzo bug: i digest dei
  pin causali devono usare la funzione `canonical_digest` LOCALE dello
  spike causale (hex grezzo, no prefisso), non quella RFC 8785 del
  kernel — altrimenti `MODEL_PIN_MISMATCH`.
- Verifica proattiva del provisioning CI: confermato che PostgreSQL/
  TypeDB/Fuseki sono già reali e provisionati nei 3 workflow CI;
  Kafka e Qdrant si autoprovisionano — nessun gap, nessuna modifica
  CI necessaria.
- Gate locali tutti verdi: `ruff`, `mypy` (50 file, invariato — il
  file mission-thread è fuori dallo scope di mypy), `validate_rccad.py`
  PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (6 percorsi), pytest completo
  con `OCOR_LIVE_POSTGRES_DSN` locale: `2 failed, 670 passed, 0
  skipped, 0 errors` (stessi 2 fallimenti noti) più `29 passed` per le
  3 suite `reports/tests/`, `validate_ocor_development_plan.py
  --base-ref origin/main --authorized-extension` PASS dopo il
  consueto doppio-run.
- Evidenza sigillata: `reports/evidence/G3/OCOR-DEV-0031.json` +
  `reports/evidence/G3/OCOR-DEV-0031.log`, aggiunta a
  `reports/evidence/G3/MANIFEST.json` (diff puramente additivo, 64
  righe, inserimento chirurgico).
- Aggiornamento dei tre file di stato eseguito in questa stessa
  iterazione (non rimandato).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0031`: al primo push, 3 job CI (`delivery-activation`,
  `rccad-methodology`, `validation-closure`) hanno fallito con
  `ModuleNotFoundError: No module named 'spikes'` durante la raccolta
  di `test_first_governed_slice.py`. Causa radice: il file si basava
  implicitamente su un side-effect `sys.path.insert` di un altro
  modulo di test già raccolto nella stessa sessione pytest — una
  dipendenza cross-file non documentata condivisa da 13 file di test
  esistenti. `mission_thread/` viene raccolta alfabeticamente PRIMA di
  `tasks/`, quindi il nuovo file veniva importato prima che quei
  side-effect fossero eseguiti; i test locali con `python -m pytest`
  (che antepone automaticamente la CWD a `sys.path`) non avevano mai
  rivelato il problema, a differenza dello script `pytest` nudo che la
  CI invoca davvero. Corretto aggiungendo un proprio
  `sys.path.insert(0, REPOSITORY_ROOT)` esplicito, riverificato con lo
  script `pytest` nudo (non `python -m pytest`): 5/5 test passano,
  l'intero albero si raccoglie senza errori, regressione invariata.
  Evidenza risigillata con i nuovi hash e la scoperta della causa
  radice. Commit di correzione pushato come nuovo commit sullo stesso
  branch. Tutti e 13 i check verdi sul commit corretto. PR #93
  mergiata (`47df17176f050c644105b73c3ae7aae085e86a76`), SHA
  post-merge verificata. Con questo si chiude l'intero wave 14 e si
  apre il gate **G4**.

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0031 (post-merge, apertura G4)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #93, su un branch dedicato
  (`governed/state-sync-ocor-dev-0031`).
- `baseline_commit` aggiornato a
  `47df17176f050c644105b73c3ae7aae085e86a76` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0031`
  aggiunto a `completed_evidence_tasks`. Verificata l'assenza di
  `RCCAD-STATE-HANDOFF-DRIFT`.
- Ricalcolata la prontezza del prossimo wave dal backlog JSON: ready
  set = `{OCOR-DEV-0032, 0034, 0036, 0037, 0038, 0040, 0042, 0046,
  0048}`, 9 task, tutti `parallel_wave=15`, gate **G4**, tutti
  dipendenti solo da `OCOR-DEV-0031`. Selezionato `OCOR-DEV-0032`
  ("Complete C1 parser type-checker and semantic validation") per
  ordine numerico.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- `OCOR-DEV-0031`: `OCOR-DEV-0031` aggiunto a `completed_evidence_tasks`;
  PR #94 mergiata (`947b2b2586fb89c1d5342199bba2f091b061ef9c`), SHA
  post-merge verificata.

## 2026-09-13 — Backlog: OCOR-DEV-0032 (Complete C1 parser type-checker and semantic validation)

- Letto per intero `ocor_runtime.c1.ports` (l'intero enum sigillato
  `DiagnosticCode`) e `ocor_runtime.c1.compiler` (`OCOR-DEV-0028`)
  prima di progettare qualunque cosa: confermato che `0028` copre già
  `SOURCE_INVALID`, `UNKNOWN_SYNTAX`, `UNRESOLVED_REFERENCE`/
  `DUPLICATE_RESOURCE` (solo import esterni via dependency-lock),
  `TYPE_ERROR`, `CONSTRAINT_ERROR`, `RELEASE_REJECTED`; scoperti come
  NON coperti: `MULTIPLE_EXECUTION_OWNERS`, `UNSUPPORTED_CAPABILITY`,
  e qualunque risoluzione/rilevamento di cicli tra riferimenti
  semantici (non di import) tra risorse.
- Implementato `ocor-runtime/src/ocor_runtime/c1/frontend.py`: una
  nuova implementazione parallela e più completa degli stessi
  Protocol sigillati `OacParser`/`SemanticValidator`/
  `CanonicalIrBuilder`, che NON modifica il `compiler.py` sigillato di
  `OCOR-DEV-0028`. Aggiunge: una grammatica di tipi chiusa (string/
  integer/number/boolean/list) che richiede a ogni campo di
  dichiarare e soddisfare un tipo; il rifiuto di una risorsa che
  dichiara più di un `execution_owner` distinto come ambigua; e la
  risoluzione/rilevamento di cicli su un nuovo campo semantico
  `references` (distinto dagli import esterni già gestiti da
  `CompilerRequest`), riusando l'helper sigillato
  `require_resolved_references` per la risoluzione e un DFS a tre
  colori per i cicli.
- **Bug reale trovato e corretto durante la prima esecuzione**:
  l'helper sigillato `require_resolved_references` (tramite il suo
  `_unique_strings` interno) rifiuta i duplicati nella lista
  `referenced` — ma un grafo a diamante (due risorse che condividono
  lo stesso target referenziato) è legittimo e NON deve essere
  rifiutato come duplicato. Corretto passando solo l'insieme distinto
  dei target referenziati, mai una lista piatta con ripetizioni.
- Aggiunto `ocor-runtime/tests/tasks/test_ocor_dev_0032.py` (15 test,
  puro in-memory, nessun backend esterno): compilazione deterministica
  di un corpus valido; tipi di campo mancanti/non dichiarati; tipo
  dichiarato non supportato; valore non conforme al tipo dichiarato
  (incluso un booleano contro un tipo intero dichiarato, dato che
  `bool` è una sottoclasse di `int` in Python); proprietà d'esecuzione
  ambigua vs. non ambigua; riferimento non risolto; cicli diretti e
  più lunghi; un grafo a diamante non ciclico legittimo che compila
  con successo; sintassi malformata; mismatch dell'id dichiarato;
  nessun rilascio parziale su rifiuto.
- Gate locali tutti verdi: `ruff`, `mypy` (51 file, +1), `validate_rccad.py`
  PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (5 percorsi), pytest completo
  via lo script `pytest` nudo (non `python -m pytest`): `2 failed, 685
  passed, 0 skipped, 0 errors` (stessi 2 fallimenti noti) più `29
  passed` per le 3 suite `reports/tests/`,
  `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0032.json` +
  `reports/evidence/G4/OCOR-DEV-0032.log`. **Primo task a sigillare
  evidenza sotto il gate G4**: `reports/evidence/G4/MANIFEST.json`
  creato da zero, rispecchiando lo schema del primo manifest G3
  (`OCOR-DEV-0028`).
- Aggiornamento dei tre file di stato eseguito in questa stessa
  iterazione (non rimandato).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0032`: tutti e 13 i check verdi al primo push. PR #95
  mergiata (`00b51e710c24832d09cf87a8f139edfa74f37a1d`), SHA
  post-merge verificata.

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0032 (post-merge, apertura wave 16)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #95, su un branch dedicato
  (`governed/state-sync-ocor-dev-0032`).
- `baseline_commit` aggiornato a
  `00b51e710c24832d09cf87a8f139edfa74f37a1d` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0032`
  aggiunto a `completed_evidence_tasks`. Verificata l'assenza di
  `RCCAD-STATE-HANDOFF-DRIFT`.
- Ricalcolata la prontezza dal backlog JSON: `OCOR-DEV-0033`
  ("Complete C1 releases semantic diff migration and generators",
  wave 16) è appena diventato pronto, dipendente solo da
  `OCOR-DEV-0032` — numericamente più basso degli 8 task rimanenti
  del wave 15, quindi selezionato per ordine numerico sull'intero
  insieme pronto (non limitato a un singolo wave), secondo la
  convenzione già stabilita in questa sessione.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- Prossima azione: leggere per intero la voce di `OCOR-DEV-0033` nel
  backlog JSON prima di progettare qualunque cosa (già fatto:
  richiede `ocor-runtime/src/ocor_runtime/c1/releases.py`,
  implementando i Protocol sigillati rimanenti `SemanticDiffEngine`/
  `CompatibilityChecker`/`MigrationPlanner`/`ArtifactGenerator` su
  coppie di `CanonicalIrRelease`, puro in-memory, nessun backend).

## 2026-09-13 — OCOR-DEV-0033: completamento C1 releases (semantic diff, migrazione, generatori)

- Implementati i Protocol sigillati rimanenti di C1 (OCOR-DEV-0011,
  `ocor_runtime.c1.ports`, riusato invariato) in
  `ocor-runtime/src/ocor_runtime/c1/releases.py`:
  `RetainedSemanticDiffEngine.compare` (digest strutturale
  content-addressed su risorse aggiunte/rimosse/cambiate, direzionale),
  `RetainedCompatibilityChecker.check` (`IDENTICAL`/`COMPATIBLE`/
  `BREAKING` — una risorsa rimossa, una dichiarazione di tipo di campo
  rimossa, o un tipo di campo esistente cambiato sono tutti `BREAKING`),
  `RetainedMigrationPlanner.plan` (piano di migrazione content-addressed
  con proprio `plan_digest`, passi ordinati retire/expand-migrate-contract/
  introduce), `RetainedArtifactGenerator` (`generate()` incondizionato
  come da Protocol sigillato; nuovo `generate_governed()` che rende
  eseguibile il criterio di accettazione negativo di questo task — un
  cambiamento `BREAKING` non può mai raggiungere la generazione senza un
  piano di migrazione governato esplicito e non vuoto).
- Riusa `ocor_runtime.c1.frontend` (OCOR-DEV-0032, invariato) per
  costruire fixture `CanonicalIrRelease` reali per i 14 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0033.py` — tutti passati al
  primo tentativo, nessun bug trovato nel nuovo codice di questo task
  (a differenza di ogni altro task di questa wave).
- Rilevamento ambientale non bloccante: un OOM transitorio e non
  correlato di Fuseki (`ocor-bootstrap-fuseki-1`, causato da un
  container host di grandi dimensioni non correlato che condivide lo
  stesso demone Docker — pattern ricorrente in questa sessione) ha
  causato 15 errori non correlati nel primo tentativo di regressione
  completa; diagnosticato via `docker compose -p ocor-bootstrap ps` e
  risolto riavviando solo il servizio fuseki; confermato non correlato
  con una seconda esecuzione pulita (`699 passed`, 2 fallimenti noti
  preesistenti).
- Gate locali tutti verdi: `ruff`, `mypy` (52 file, +1),
  `validate_rccad.py` PASS (10/10 AFF `PASS_STATIC_PRECHECK`, nessun
  finding), `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (7 percorsi), pytest completo
  via lo script `pytest` nudo: `2 failed, 699 passed, 0 skipped, 0
  errors` (stessi 2 fallimenti noti) più `29 passed` per le 3 suite
  `reports/tests/`, `validate_ocor_development_plan.py --base-ref
  origin/main --authorized-extension` PASS dopo il consueto
  doppio-run (FAIL poi PASS).
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0033.json` +
  `reports/evidence/G4/OCOR-DEV-0033.log`. `reports/evidence/G4/
  MANIFEST.json` esteso con inserimento chirurgico (2 nuovi artifact,
  11 nuovi requirement_results), preservando la formattazione delle
  voci preesistenti.
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task (pattern OCOR-DEV-0032/PR #96),
  non incluso nel commit del task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0033`: tutti e 13 i check verdi al primo push. PR #97
  mergiata (`305772453f25223d8c01e83a70ad944d1e7ac7a6`), SHA
  post-merge verificata (`git fetch origin main` +
  `git rev-parse origin/main`).

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0033 (post-merge)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #97, su un branch dedicato
  (`governed/state-sync-ocor-dev-0033`).
- `baseline_commit` aggiornato a
  `305772453f25223d8c01e83a70ad944d1e7ac7a6` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0033`
  aggiunto a `completed_evidence_tasks`.
- Prossima azione: ricalcolare la prontezza direttamente dal backlog
  JSON (mai fidarsi di `--status`). Wave 15 ha ancora 8 task pronti
  (`OCOR-DEV-0034/0036/0037/0038/0040/0042/0046/0048`); verificare se
  `OCOR-DEV-0033` ha sbloccato un task numericamente più basso prima
  di procedere, poi selezionare per ordine numerico sull'intero
  insieme pronto.

## 2026-09-13 — OCOR-DEV-0034: C2 named-query gateway e identity resolution

- Nuovo `ocor_runtime.c2.gateway`: `NamedQueryGateway` (implementa il
  `NamedQueryPort` sigillato, OCOR-DEV-0012) garantisce che solo le
  named query registrate vengano eseguite, e solo dopo che identità,
  scopo, marking e policy siano tutti dispositivi. Lo scopo è già
  fail-closed dentro il costruttore sigillato di `NamedQueryRequest`;
  questo task fornisce le PRIME implementazioni reali dei port
  sigillati `AuthorityResolutionPort` (`IdentityBackedAuthority`,
  delega al retained `c2_identity.IdentityRegistry`, invariato) e
  `PolicyDecisionPort` (`RegistrationAndMarkingPolicy`, combina un
  allow-list esplicito nome/versione con un controllo reale di
  marking-join contro `spikes.jena_marking.adapter` di OCOR-DEV-0018,
  invariato), poi delega a un `ProjectionReadPort` iniettato
  (`spikes.typedb_exact_commit.adapter` di OCOR-DEV-0017, invariato)
  per la lettura vera e propria.
- Design deliberato: un contratto non registrato, una versione non
  registrata e un diniego di marking restituiscono tutti lo stesso
  codice `ARBITRARY_QUERY_FORBIDDEN` — un chiamante non può distinguere
  quale barriera è stata attraversata dal solo errore; nessuna
  risposta, parziale o meno, viene mai restituita su alcun percorso di
  diniego.
- Aggiunti 14 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0034.py`, tutti contro
  Fuseki e TypeDB reali, nessun mock: conformità ai Protocol per le 3
  nuove classi; percorso positivo completo fino a una lettura TypeDB
  reale; diniego per contratto non registrato, versione non
  registrata, identità mai registrata (abstain), risorsa fuori
  clearance, risorsa priva del tutto della propria marcatura, e
  riferimento di clearance non risolvibile; una query registrata senza
  parametro risorsa che salta il marking join; rifiuto di scopo
  mancante e di forma di query arbitraria al confine del costruttore
  sigillato; un test di fault-injection reale (una vera porta TCP
  locale chiusa, stesso pattern a basso raggio d'impatto già stabilito
  in OCOR-DEV-0026/0027) che prova che un guasto del backend di
  marking si propaga invece di ripiegare silenziosamente su un
  permesso.
- Un bug di scrittura del test trovato e corretto prima della
  sigillatura: un test si aspettava `C2Error` da un `GovernedContext`
  con scopo mancante, ma il costruttore sigillato di `GovernedContext`
  solleva il proprio `GovernedContextError` distinto — corretto il
  tipo di eccezione atteso nel test, nessuna modifica al codice di
  produzione necessaria.
- Verificato proattivamente, prima di aprire la PR, che TypeDB e
  Fuseki fossero già forniti in tutti e 3 i workflow CI che eseguono
  l'intera suite di test (già risolto durante OCOR-DEV-0017/0018).
- Gate locali tutti verdi: `ruff`, `mypy`, `validate_rccad.py` PASS
  (nessun import diretto di client backend in `gateway.py`, tutte le
  porte sono iniettate), `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (7 percorsi), pytest completo
  via lo script `pytest` nudo con `OCOR_LIVE_POSTGRES_DSN` impostato
  contro il PostgreSQL reale di ocor-bootstrap: `2 failed, 713 passed`
  (stessi 2 fallimenti noti) più `29 passed` per le 3 suite
  `reports/tests/`, `validate_ocor_development_plan.py --base-ref
  origin/main --authorized-extension` PASS dopo il consueto
  doppio-run.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0034.json` +
  `reports/evidence/G4/OCOR-DEV-0034.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 15 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0034`: tutti e 13 i check verdi al primo push. PR #99
  mergiata (`1af39d6feefbec7a21edeff4c635cf4c406919d8`), SHA
  post-merge verificata.

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0034 (post-merge, wave 16 OCOR-DEV-0035 pronto)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #99, su un branch dedicato
  (`governed/state-sync-ocor-dev-0034`).
- `baseline_commit` aggiornato a
  `1af39d6feefbec7a21edeff4c635cf4c406919d8` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0034`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: `OCOR-DEV-0035` ("Implement
  C2 policy-filtered planning consistency and watermarks", wave 16) è
  appena diventato pronto, dipendente solo da `OCOR-DEV-0034` —
  numericamente più basso dei 7 task rimanenti del wave 15
  (`0036/0037/0038/0040/0042/0046/0048`), quindi selezionato per
  ordine numerico sull'intero insieme pronto, secondo la convenzione
  già stabilita in questa sessione.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- Prossima azione: implementare `ocor-runtime/src/ocor_runtime/c2/planner.py`
  riusando i port sigillati `WatermarkPort`/`ConsistencyRequirement`
  (OCOR-DEV-0012) e la composizione di OCOR-DEV-0034 dove utile;
  criterio di accettazione negativo: "silent stale fallback or backend
  query leakage is rejected".

## 2026-09-13 — OCOR-DEV-0035: C2 policy-filtered planning consistency e watermarks

- Nuovo `ocor_runtime.c2.planner`: `ConsistencyPlanner` pianifica se la
  consistenza richiesta da una richiesta già autorizzata dalla policy
  può essere onorata, usando SOLO i port sigillati `PolicyDecisionPort`
  (OCOR-DEV-0012/0034, invariato) e `WatermarkPort` (OCOR-DEV-0012,
  invariato) — mai la query reale sui dati della projection
  (`ProjectionReadPort.read`). La policy viene valutata per prima: una
  query non registrata o comunque negata non raggiunge mai nemmeno il
  controllo del watermark.
- `BEST_AVAILABLE` restituisce un piano senza commit richiesto ma con
  il watermark reale osservato allegato (così un chiamante può sempre
  mostrare il proprio lavoro, mai un successo nudo senza evidenza);
  `EXACT_AT_COMMIT`/`AT_LEAST_COMMIT` confrontano il watermark reale
  con il commit richiesto e sollevano `PROJECTION_NOT_READY` nominando
  il watermark reale osservato quando non ha ancora raggiunto il
  commit — mai un fallback silenzioso a `BEST_AVAILABLE`, mai una
  query reale al backend solo per calcolare il piano. Il confronto
  per uguaglianza rispecchia deliberatamente la stessa semantica già
  stabilita dal `ConsistencyRequirement.verify_served` sigillato e
  dall'adapter di OCOR-DEV-0017, invece di inventare un nuovo ordine
  per `AT_LEAST_COMMIT`.
- Aggiunti 8 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0035.py`, tutti contro
  TypeDB reale (per il watermark), nessun mock: conformità al Protocol
  per il wrapper di test dell'adapter TypeDB come `WatermarkPort`;
  `BEST_AVAILABLE` con watermark reale allegato; `EXACT_AT_COMMIT` che
  procede quando il watermark corrisponde; `EXACT_AT_COMMIT` e
  `AT_LEAST_COMMIT` che riportano `PROJECTION_NOT_READY` con il
  watermark reale finché non lo raggiunge; uno spy `WatermarkPort` che
  PROVA, non solo asserisce per commento, che un diniego di policy
  interrompe il flusso prima del controllo del watermark; un diniego
  che non trapela mai alcun piano; e un test di fault-injection reale
  (una vera porta TCP locale chiusa) che prova che un guasto del
  backend di watermark si propaga invece di ripiegare silenziosamente
  su un esito permissivo.
- Nessun bug trovato nel nuovo codice di questo task: tutti e 8 i test
  sono passati al primo tentativo.
- Gate locali tutti verdi: `ruff`, `mypy`, `validate_rccad.py` PASS
  (nessun import diretto di client backend in `planner.py`, tutte le
  porte sono iniettate), `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (7 percorsi), pytest completo
  via lo script `pytest` nudo con `OCOR_LIVE_POSTGRES_DSN` impostato
  contro il PostgreSQL reale di ocor-bootstrap: `2 failed, 721 passed`
  (stessi 2 fallimenti noti) più `29 passed` per le 3 suite
  `reports/tests/`, `validate_ocor_development_plan.py --base-ref
  origin/main --authorized-extension` PASS dopo il consueto
  doppio-run.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0035.json` +
  `reports/evidence/G4/OCOR-DEV-0035.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 9 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0035`: tutti e 13 i check verdi al primo push. PR #101
  mergiata (`bfd928d2036f37ecf7a09658b45a3b0848afbea5`), SHA
  post-merge verificata. Chiude interamente il wave 16
  (`OCOR-DEV-0033/0034/0035`).

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0035 (post-merge, wave 16 chiuso)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #101, su un branch dedicato
  (`governed/state-sync-ocor-dev-0035`).
- `baseline_commit` aggiornato a
  `bfd928d2036f37ecf7a09658b45a3b0848afbea5` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0035`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: nessun nuovo task
  numericamente più basso è stato sbloccato da `OCOR-DEV-0035`, quindi
  i 7 task rimanenti del wave 15
  (`0036/0037/0038/0040/0042/0046/0048`) tornano ad essere il fronte
  di lavoro; selezionato `OCOR-DEV-0036` ("Complete C3 single-writer
  recovery and reconciliation") per ordine numerico.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- Prossima azione: implementare `ocor-runtime/src/ocor_runtime/c3/recovery.py`,
  riusando `PostgresC3Service` (OCOR-DEV-0029) e il pattern di
  composizione di OCOR-DEV-0031; criterio di accettazione: scrittori
  concorrenti, ACK perso, outbox corrotto e fixture di riavvio
  convergono senza effetti canonici duplicati.

## 2026-09-13 — OCOR-DEV-0036: C3 single-writer recovery e reconciliation

- Nuovo `ocor_runtime.c3.recovery.SingleWriterRecoveryCoordinator`,
  che compone il `PostgresC3Service` sigillato (OCOR-DEV-0029, invariato)
  esclusivamente tramite i suoi metodi pubblici sigillati (`reconcile`,
  `claim_batch`, `acknowledge`). Prima di scrivere qualunque cosa,
  verificato che `c3/service.py` e `c3/adapters/postgres.py` sono
  hash-referenziati come deliverable unico e sigillato di
  OCOR-DEV-0029 già accettato — esclusi entrambi dalla modifica per
  protocollo standard, aggiungendo invece un NUOVO adapter separato
  (`ocor_runtime.c3.adapters.recovery_lock.PostgresAdvisoryLock`) per
  l'unica capability nuova necessaria (un vero lock advisory
  PostgreSQL a livello di sessione via `pg_advisory_lock`/
  `pg_advisory_unlock`, la stessa primitiva `hashtextextended` già
  usata per davvero da `commit_transaction` di OCOR-DEV-0029),
  mantenendo AFF-002/AFF-006 soddisfatto senza toccare i file
  sigillati di OCOR-DEV-0029.
- `run_recovery_pass` avvolge `reconcile()` nel lock reale, così
  processi concorrenti o riavviati si serializzano sullo stesso lock
  reale e non corrono mai lo stesso repair (`reconcile()` ripara già
  ENTRAMBE le direzioni di orfani — riga di idempotency mancante e
  riga di outbox mancante — quindi la convergenza dell'"outbox
  corrotto" era già coperta dal contratto sigillato; lo scope di
  questo task è la serializzazione single-writer e l'health-gate
  attorno ad essa).
- `claim_and_deliver` avvolge claim+consegna+acknowledge nella stessa
  sezione critica, così due worker di relay concorrenti non possono
  mai reclamare la stessa riga non confermata prima che uno dei due
  la confermi; un ACK perso (un crash tra consegna e acknowledge)
  lascia la riga di nuovo reclamabile, ed è l'idempotenza del sink del
  chiamante (per `event_id`) a prevenire un effetto canonico
  duplicato alla riconsegna — il consueto contratto at-least-once
  dell'outbox, mai silenziosamente elevato a exactly-once da questo
  coordinator.
- `assert_healthy` usa il conteggio di riparazioni di `reconcile()`
  stesso come segnale di salute pre-flight, dato che `RecoveryPort`
  non espone un conteggio senza effetti collaterali nel contratto
  sigillato: solleva `UNRECONCILED_DURABLE_INTENT` per il passaggio in
  cui qualcosa necessitava riparazione, e ha successo una volta che
  non resta nulla.
- Aggiunti 8 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0036.py`, tutti contro
  PostgreSQL reale, nessun mock, incluse prove di concorrenza reale
  con threading: un vero lock advisory che serializza davvero due
  detentori concorrenti (provato con timestamp monotoni reali, non
  inferito); due passaggi di recovery concorrenti reali che corrono
  la stessa corruzione simulata reale convergono a esattamente una
  riparazione reale; un test di ACK perso che prova che il sink
  idempotente del chiamante assorbe un vero tentativo di consegna
  duplicata; due worker di relay concorrenti che corrono lo stesso
  singolo evento non confermato senza mai reclamarlo entrambi; un
  coordinator/service nuovo che simula un vero riavvio di processo e
  converge senza ripetere una riparazione già completata; e un test
  di fault-injection reale (un DSN PostgreSQL irraggiungibile) che
  prova che un guasto del backend del lock si propaga e il passaggio
  di recovery non gira mai senza lock.
- Tre bug genuini di scrittura del test trovati e corretti prima della
  sigillatura: (1) `make_command` indovinava inizialmente un campo del
  costruttore `GovernedCanonicalCommitCommand` inesistente
  (`command_digest`) invece di riusare il pattern dell'helper
  `from_mapping` di OCOR-DEV-0029; (2) valori di `idempotency_key`
  sotto i 16 caratteri violano il vincolo di lunghezza minima
  sigillato `COMMIT_CONTRACT_INVALID`; (3) il test di fault-injection
  si aspettava `OSError`, ma `psycopg.OperationalError` non è una
  sua sottoclasse.
- Test ripetuti 6 volte per escludere flakiness nei test di
  concorrenza reale: tutti deterministici.
- Gate locali tutti verdi: `ruff`, `mypy`, `validate_rccad.py` PASS
  (l'unico import di `psycopg` vive nel nuovo `c3/adapters/recovery_lock.py`),
  `validate_language_policy.py` PASS, `validate_ocor_change_scope.py`
  PASS (8 percorsi), pytest completo via lo script `pytest` nudo con
  `OCOR_LIVE_POSTGRES_DSN` impostato contro il PostgreSQL reale di
  ocor-bootstrap: `2 failed, 729 passed` (stessi 2 fallimenti noti)
  più `29 passed` per le 3 suite `reports/tests/`,
  `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0036.json` +
  `reports/evidence/G4/OCOR-DEV-0036.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 9 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0036`: tutti e 13 i check verdi al primo push. PR #103
  mergiata (`ab06c8fc7fd996c40e8728dc5c55c6a4be56967c`), SHA
  post-merge verificata.

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0036 (post-merge)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #103, su un branch dedicato
  (`governed/state-sync-ocor-dev-0036`).
- `baseline_commit` aggiornato a
  `ab06c8fc7fd996c40e8728dc5c55c6a4be56967c` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0036`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: nessun nuovo task
  numericamente più basso è stato sbloccato da `OCOR-DEV-0036`, quindi
  i 6 task rimanenti del wave 15 (`0037/0038/0040/0042/0046/0048`)
  restano il fronte di lavoro; selezionato `OCOR-DEV-0037` ("Implement
  C4 TypeDB projection adapter") per ordine numerico.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- Prossima azione: implementare `ocor-runtime/src/ocor_runtime/c4/typedb_adapter.py`,
  riusando lo spike `spikes.typedb_exact_commit.adapter` (OCOR-DEV-0017)
  e `PostgresC3Service` (OCOR-DEV-0029); criterio di accettazione:
  fatti/relazioni e watermark si committano atomicamente e il
  comportamento exact-at-commit rispetta il port; criterio negativo:
  una projection stantia non può mai spacciarsi per esatta.

## 2026-09-13 — OCOR-DEV-0037: C4 TypeDB projection adapter

- Nuovo `ocor_runtime.c4.typedb_adapter.TypeDBProjectionAdapter`,
  versione retained (non-spike) di
  `spikes.typedb_exact_commit.adapter` (OCOR-DEV-0017): un
  `ProjectionReadPort`/`WatermarkPort` sigillato (OCOR-DEV-0012,
  invariato) contro TypeDB reale, reimplementando la stessa superficie
  API HTTP v1 reale già provata dallo spike invece di importare il
  codice dello spike nel codice retained (`spikes/` è fuori dal
  pythonpath di ocor-runtime in produzione, stesso precedente già
  stabilito da OCOR-DEV-0028).
- L'unica vera differenza comportamentale: `apply_commit()` inserisce
  un fatto E avanza il watermark a quel commit atomicamente, in UNA
  sola transazione di scrittura TypeDB reale (lo spike mantiene
  `ingest()`/`advance_watermark()` deliberatamente separati apposta
  per modellare ed esercitare le race fra un fatto e il suo watermark
  nei propri test — questo adapter retained è il percorso di
  produzione reale che un consumer C5 userebbe, dove la deriva fra
  fatto e watermark non deve mai essere possibile in condizioni
  normali). `read()`/`current()` riusano lo stesso identico
  `NamedQueryRequest.verify_served` fail-closed già provato dallo
  spike: una projection stantia non può mai spacciarsi per esatta.
- Confermato che la regex `DIRECT_CLIENTS` di AFF-002/AFF-006
  rileva solo import letterali di `psycopg`/`kafka`/`qdrant_client`/
  `terminusdb_client`/`typedb`, non `urllib` — quindi le chiamate HTTP
  reali di questo file non richiedono un sottoalbero `adapters/`,
  rispecchiando esattamente il layout a file singolo dello spike.
- Aggiunti 8 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0037.py`, tutti contro
  TypeDB reale, nessun mock.
- Due bug genuini trovati e corretti prima della sigillatura: (1) la
  prima bozza rispecchiava il metodo `watermark()` dello spike stesso
  (senza argomenti), che NON rispetta davvero la firma sigillata
  `WatermarkPort.current(projection_id, branch)` —
  `isinstance(adapter, WatermarkPort)` falliva genuinamente; corretto
  rinominando in `current(self, projection_id, branch)`, chiudendo un
  vero gap di conformità che lo spike stesso non aveva mai chiuso; (2)
  il test di fault-injection si aspettava `TypeDBAdapterError` da un
  host irraggiungibile, ma un vero guasto di connessione solleva
  direttamente `urllib.error.URLError` (non catturato da `_request`,
  che traduce solo le risposte di errore a livello HTTP) — corretto il
  tipo di eccezione atteso nel test invece di aggiungere un except
  generico nel codice di produzione.
- Gate locali tutti verdi: `ruff`, `mypy`, `validate_rccad.py` PASS,
  `validate_language_policy.py` PASS, `validate_ocor_change_scope.py`
  PASS (7 percorsi), pytest completo via lo script `pytest` nudo con
  `OCOR_LIVE_POSTGRES_DSN` impostato contro il PostgreSQL reale di
  ocor-bootstrap: `2 failed, 737 passed` (stessi 2 fallimenti noti)
  più `29 passed` per le 3 suite `reports/tests/`,
  `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0037.json` +
  `reports/evidence/G4/OCOR-DEV-0037.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 9 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0037`: tutti e 13 i check verdi al primo push. PR #105
  mergiata (`7fa50fcc40a15cdad46a6c0c1b24bec630744d68`), SHA
  post-merge verificata.

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0037 (post-merge)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #105, su un branch dedicato
  (`governed/state-sync-ocor-dev-0037`).
- `baseline_commit` aggiornato a
  `7fa50fcc40a15cdad46a6c0c1b24bec630744d68` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0037`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: nessun nuovo task
  numericamente più basso è stato sbloccato da `OCOR-DEV-0037`, quindi
  i 5 task rimanenti del wave 15 (`0038/0040/0042/0046/0048`) restano
  il fronte di lavoro; selezionato `OCOR-DEV-0038` ("Implement C4 Jena
  RDF SHACL adapter") per ordine numerico.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- Prossima azione: implementare `ocor-runtime/src/ocor_runtime/c4/jena_adapter.py`,
  riusando lo spike `spikes.jena_marking.adapter` (OCOR-DEV-0018) e
  `PostgresC3Service` (OCOR-DEV-0029); criterio di accettazione:
  output RDF/JSON-LD supera fixture SHACL e di non-interferenza del
  marking; criterio negativo: triple non autorizzate o provenance
  lossy bloccano la pubblicazione.

## 2026-09-13 — OCOR-DEV-0038: C4 Jena RDF SHACL adapter

- Nuovo `ocor_runtime.c4.jena_adapter.JenaSHACLProjectionAdapter`,
  estende il pattern di marking reale di OCOR-DEV-0018 (Fuseki,
  invariato) con un vero percorso di pubblicazione. Confermato che
  nessun `pyshacl` (o processore SHACL generico) è dipendenza di
  progetto — implementato lo SHACL-equivalent minimo direttamente:
  una shape chiusa a required-property/closed-predicate applicata
  PRIMA di qualunque scrittura SPARQL, invece di aggiungere una nuova
  dipendenza esterna (che avrebbe richiesto modifiche a
  pyproject.toml/uv.lock fuori dallo scope di questo task).
- Un predicato non autorizzato (`ALLOWED_PREDICATES`) o una
  `provenanceRef` mancante/lossy bloccano la pubblicazione per intero
  — i due criteri di accettazione negativi del task, resi strutturali;
  una risorsa rifiutata non diventa mai parzialmente visibile.
- Le letture (`list_authorized`/`exists_authorized`) riusano lo stesso
  identico pattern di marking-join reale già provato da OCOR-DEV-0018.
  `to_json_ld` è negato via `exists_authorized` per qualunque
  clearance non autorizzata, altrimenti serializza JSON-LD reale e
  ben formato via `rdflib` (già dipendenza di progetto, 7.1.4) su un
  vero risultato SPARQL CONSTRUCT.
- Aggiunti 8 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0038.py`, tutti contro
  Fuseki reale, nessun mock — tutti e 8 passati al primo tentativo,
  nessun bug trovato (la lezione di OCOR-DEV-0037 su
  `urllib.error.URLError` non tradotto da `_request` è stata applicata
  proattivamente al tipo di eccezione atteso nel test di
  fault-injection).
- Gate locali tutti verdi: `ruff`, `mypy`, `validate_rccad.py` PASS,
  `validate_language_policy.py` PASS, `validate_ocor_change_scope.py`
  PASS (7 percorsi), pytest completo via lo script `pytest` nudo con
  `OCOR_LIVE_POSTGRES_DSN` impostato contro il PostgreSQL reale di
  ocor-bootstrap: `2 failed, 745 passed` (stessi 2 fallimenti noti)
  più `29 passed` per le 3 suite `reports/tests/`,
  `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0038.json` +
  `reports/evidence/G4/OCOR-DEV-0038.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 9 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0038`: tutti e 13 i check verdi al primo push. PR #107
  mergiata (`80962a15fd677cbca610c8382639443d5f70c1c2`), SHA
  post-merge verificata.

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0038 (post-merge, wave 16 OCOR-DEV-0039 pronto)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #107, su un branch dedicato
  (`governed/state-sync-ocor-dev-0038`).
- `baseline_commit` aggiornato a
  `80962a15fd677cbca610c8382639443d5f70c1c2` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0038`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: `OCOR-DEV-0039` ("Implement
  C4 rebuild and drift reconciliation", wave 16) è appena diventato
  pronto, dipendente da `OCOR-DEV-0037` e `OCOR-DEV-0038` (entrambi
  appena mergiati) — numericamente più basso dei 4 task rimanenti del
  wave 15 (`0040/0042/0046/0048`), quindi selezionato per ordine
  numerico sull'intero insieme pronto.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- Prossima azione: implementare `ocor-runtime/src/ocor_runtime/c4/rebuild.py`,
  riusando `TypeDBProjectionAdapter` (OCOR-DEV-0037) e
  `JenaSHACLProjectionAdapter` (OCOR-DEV-0038); criterio di
  accettazione: il rebuild della projection dal log canonico riproduce
  digest/watermark e la deriva viene messa in quarantena; criterio
  negativo: servire una projection divergente dopo una riconciliazione
  fallita è vietato.

## 2026-09-13 — OCOR-DEV-0039: C4 rebuild e drift reconciliation

- Nuovo `ocor_runtime.c4.rebuild.ProjectionDriftDetector`, implementa
  direttamente il `ProjectionDriftDetector` nominato in LLD v1.1 §2.4.
  Verificato che `c3/service.py` e `c4/typedb_adapter.py` sono
  hash-referenziati come deliverable sigillati di task già accettati
  (OCOR-DEV-0029, OCOR-DEV-0037) — composti ENTRAMBI esclusivamente
  tramite i loro metodi pubblici sigillati esistenti
  (`PostgresC3Service.read`, `TypeDBProjectionAdapter.apply_commit`/
  `read`), senza mai toccare nessuno dei due file sigillati.
- `rebuild()` legge lo snapshot canonico da C3 (autoritativo),
  "sbircia" il digest della projection attualmente servita tramite il
  `ProjectionReadPort.read()` sigillato dell'adapter (una richiesta di
  sistema sintetica e deterministica in `BEST_AVAILABLE`) PRIMA di
  sovrascriverla mai, e confronta. Una discrepanza è vera deriva:
  l'aggregato viene aggiunto a un insieme di quarantena in-memory e la
  projection divergente reale viene lasciata intatta invece di essere
  riparata silenziosamente; una corrispondenza (o prima projection in
  assoluto) applica il fatto ricostruito e rimuove qualunque quarantena
  residua. `read_if_healthy()` rende eseguibile il criterio di
  accettazione negativo: solleva `PROJECTION_QUARANTINED` prima di
  delegare mai alla lettura della projection per un aggregato in
  quarantena.
- Una prima bozza di design "sbirciava" la projection servita tramite
  il metodo privato con underscore `_lookup_fact` dell'adapter —
  individuato e respinto prima della sigillatura come un vero difetto
  di design (accedere agli interni di un altro modulo sigillato invece
  del suo contratto pubblico) e sostituito con il percorso `read()`
  sigillato.
- Aggiunti 6 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0039.py`, tutti contro
  PostgreSQL e TypeDB reali, nessun mock — tutti e 6 passati al primo
  tentativo, nessun bug nel nuovo codice di questo task. Un singolo
  blip ambientale transitorio è stato osservato durante l'iterazione
  esplorativa locale (tutti e 6 i test hanno dato errore in
  un'esecuzione) ma non si è più riprodotto in 7 ripetizioni
  consecutive successive; documentato come un problema ambientale non
  bloccante sotto carico locale concorrente (coerente con altri
  ritrovamenti transitori di questa sessione, es. l'OOM ricorrente di
  Fuseki), non un difetto reale.
- Gate locali tutti verdi: `ruff`, `mypy`, `validate_rccad.py` PASS
  (nessun import diretto di client backend — `rebuild.py` compone due
  adapter già sigillati esclusivamente tramite i loro metodi
  pubblici), `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (7 percorsi), pytest completo
  via lo script `pytest` nudo con `OCOR_LIVE_POSTGRES_DSN` impostato
  contro il PostgreSQL reale di ocor-bootstrap: `2 failed, 751 passed`
  (stessi 2 fallimenti noti) più `29 passed` per le 3 suite
  `reports/tests/`, `validate_ocor_development_plan.py --base-ref
  origin/main --authorized-extension` PASS dopo il consueto
  doppio-run.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0039.json` +
  `reports/evidence/G4/OCOR-DEV-0039.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 7 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0039`: tutti e 13 i check verdi al primo push. PR #109
  mergiata (`02859b0e3dd36824975414b19ee213af2bf2043d`), SHA
  post-merge verificata. Chiude interamente il wave 16
  (`OCOR-DEV-0033/0034/0035/0039`).

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0039 (post-merge, wave 16 chiuso)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #109, su un branch dedicato
  (`governed/state-sync-ocor-dev-0039`).
- `baseline_commit` aggiornato a
  `02859b0e3dd36824975414b19ee213af2bf2043d` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0039`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: nessun nuovo task
  numericamente più basso è stato sbloccato da `OCOR-DEV-0039`, quindi
  i 4 task rimanenti del wave 15 (`0040/0042/0046/0048`) tornano ad
  essere il fronte di lavoro; selezionato `OCOR-DEV-0040` ("Implement
  C5 canonical event backbone") per ordine numerico.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- Prossima azione: implementare `ocor-runtime/src/ocor_runtime/c5/backbone.py`,
  riusando lo spike `spikes.kafka_delivery.oracle` (OCOR-DEV-0019) e
  `PostgresC3Service` (OCOR-DEV-0029); criterio di accettazione: eventi
  vincolati a schema preservano ordine di partizione, correlation,
  causation, marking e idempotency su Kafka; criterio negativo: schema
  sconosciuto, contesto mancante o effetto fuori ordine su un aggregato
  vanno in quarantena.

## 2026-09-13 — OCOR-DEV-0040: C5 canonical event backbone

- Nuovo `ocor_runtime.c5.backbone.CanonicalEventBackbone`, primo
  componente C5 retained: un `CanonicalIngestionEnvelope` chiuso (LLD
  v1.1 §2.5) pubblicato su un broker Kafka reale, con chiave
  `aggregate_ref` così che il partitioner nativo di Kafka preserva
  l'ordine per aggregato.
- Correzione di design genuina scoperta a metà implementazione:
  `grep -l kafka .github/workflows/*.yml` ha confermato che NESSUN
  workflow CI fornisce un servizio Kafka condiviso (a differenza di
  TypeDB/Fuseki, aggiunti a 3 workflow da task precedenti); l'unico
  uso di Kafka in tutta la CI è il test mission-thread di
  OCOR-DEV-0031, che auto-provisiona il proprio broker isolato.
  Ridisegnato `CanonicalEventBackbone` per auto-provisionare un vero
  broker KRaft single-node isolato per istanza
  (`provision()`/`destroy()`), reimplementando la stessa reale
  configurazione e ciclo di vita del broker già provati per davvero da
  `spikes.kafka_delivery.oracle.KafkaCli` (OCOR-DEV-0019), invece di
  importare lo spike, dato che `spikes/` è fuori dal pythonpath di
  ocor-runtime in produzione.
- `publish()` controlla l'allow-list degli schemi registrati e
  l'ultima sequenza pubblicata dell'aggregato PRIMA di chiamare mai il
  vero CLI produttore, mettendo in quarantena (mai pubblicando) uno
  schema sconosciuto o una sequenza fuori ordine; `publish_from_mapping()`
  cattura anche un campo di governed-context mancante o malformato al
  momento della costruzione e lo mette in quarantena a sua volta.
- Aggiunti 7 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0040.py`, tutti contro un
  broker reale auto-provisionato per test, nessun mock — tutti e 7
  passati, nessun bug nella nuova logica di envelope/publish/consume.
- Un finding AFF-009 genuino auto-rilevato e corretto prima della
  sigillatura: il `try/except KafkaBackboneError: pass` originario di
  `reset()` inghiottiva silenziosamente il fallimento di cancellare un
  topic non ancora esistente — corretto aggiungendo un controllo
  esplicito `topic_exists()` prima di tentare mai la cancellazione,
  rimuovendo del tutto l'except vuoto.
- Gate locali tutti verdi: `ruff`, `mypy`, `validate_rccad.py` PASS
  (dopo la correzione AFF-009), `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py` PASS (7 percorsi), pytest completo
  via lo script `pytest` nudo con `OCOR_LIVE_POSTGRES_DSN` impostato
  contro il PostgreSQL reale di ocor-bootstrap: `2 failed, 758 passed`
  (stessi 2 fallimenti noti) più `29 passed` per le 3 suite
  `reports/tests/`, `validate_ocor_development_plan.py --base-ref
  origin/main --authorized-extension` PASS dopo il consueto
  doppio-run.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0040.json` +
  `reports/evidence/G4/OCOR-DEV-0040.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 8 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0040`: tutti e 13 i check verdi al primo push, incluse le
  3 job lunghe dell'intera suite che per prime hanno esercitato
  l'auto-provisioning Kafka in CI. PR #111 mergiata
  (`916446c03c22317dd928d8bc89bed87f34e6a83d`), SHA post-merge
  verificata.

## 2026-09-13 — Sincronizzazione stato: OCOR-DEV-0040 (post-merge, wave 16 OCOR-DEV-0041 pronto)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #111, su un branch dedicato
  (`governed/state-sync-ocor-dev-0040`).
- `baseline_commit` aggiornato a
  `916446c03c22317dd928d8bc89bed87f34e6a83d` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0040`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: `OCOR-DEV-0041` ("Implement
  C5 registry replay backpressure DLQ and quarantine", wave 16) è
  appena diventato pronto, dipendente solo da `OCOR-DEV-0040` (appena
  mergiato) — numericamente più basso dei 3 task rimanenti del wave 15
  (`0042/0046/0048`), quindi selezionato per ordine numerico
  sull'intero insieme pronto.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.
- Prossima azione: implementare `ocor-runtime/src/ocor_runtime/c5/operations.py`,
  riusando `CanonicalEventBackbone` (OCOR-DEV-0040) esclusivamente
  tramite i suoi metodi pubblici; criterio di accettazione: fixture di
  replay e di eventi poison sono bounded, osservabili e non bypassano
  mai i controlli di compatibilità; criterio negativo: un replay dalla
  DLQ con schema incompatibile o marking perso viene bloccato.

## 2026-09-14 — OCOR-DEV-0041: C5 replay backpressure DLQ e quarantine

- Implementato `ocor-runtime/src/ocor_runtime/c5/operations.py`:
  `EventOperationsCoordinator` avvolge il `CanonicalEventBackbone`
  sigillato (OCOR-DEV-0040), riusato immutato e composto
  esclusivamente tramite il suo metodo pubblico `publish()`. Quota di
  ammissione bounded per tenant (`publish_with_backpressure`), record
  `DeadLetter` immutabile per ogni fallimento reale di publish,
  classificazione `POISON` dopo 3 fallimenti dello stesso evento,
  quarantena dietro un gate esplicito
  (`release_for_operator_replay`), e `replay()` che ricostruisce
  sempre l'envelope e richiama il `publish()` reale del backbone — uno
  schema incompatibile o un marking perso vengono bloccati in replay
  esattamente come in un publish nuovo, mai bypassati; una chiave di
  idempotenza già durevole è un no-op sicuro grazie alla gestione di
  idempotenza propria del backbone.
- **Incidente ambientale genuino diagnosticato e risolto prima di
  fidarsi della regressione**: la regressione completa mostrava
  cluster di errori crescenti; `df -h /` ha rivelato il disco host al
  99% di capacità (2.9GB liberi su 234GB), dominato da immagini Docker
  di grandi dimensioni preesistenti e non correlate ad altri progetti
  sulla stessa macchina condivisa (non causato da questa sessione); i
  due comandi di pulizia sicuri (`docker builder prune -f`, `docker
  image prune -f`) hanno liberato 0B. La causa reale dei 33 errori
  era invece `ocor-bootstrap-fuseki-1` e `ocor-bootstrap-spire-agent-1`
  uccisi per OOM (exit 137) ore prima, non correlato al codice di
  questo task — riavviati entrambi (`docker start`), manutenzione di
  routine reversibile sullo stack bootstrap del progetto (mai toccato
  `eci-dev-control-plane` o `open-webui`); la regressione completa è
  poi passata pulita.
- Presa una decisione tecnica poi corretta: era stato avviato un
  redesign in-flight di `backbone.py` sigillato (Kafka data directory
  da volume Docker a `tmpfs`, per ridurre l'impronta su disco), ma
  riconosciuto a metà modifica che sia `backbone.py` sia
  `test_ocor_dev_0040.py` sono deliverable sigillati di OCOR-DEV-0040
  già mergiato — annullata la modifica (`git checkout --`) prima di
  procedere, secondo la regola propria di questa sessione di escludere
  i deliverable già sigillati dalla modifica anziché emendarli. La
  causa reale (ambientale) non richiedeva comunque alcuna modifica al
  sorgente sigillato.
- Aggiunti 8 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0041.py`, tutti contro un
  broker reale auto-provisionato per test tramite il backbone
  sigillato, nessun mock — tutti e 8 passati, ripetuti 3 volte per
  determinismo.
- Gate locali tutti verdi: `ruff`, `mypy` PASS, `validate_rccad.py`
  PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py --base origin/main` PASS (7
  percorsi), `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run, pytest
  completo via lo script `pytest` nudo con `OCOR_LIVE_POSTGRES_DSN`
  impostato contro il PostgreSQL reale di ocor-bootstrap (dopo il
  riavvio di fuseki/spire-agent): `2 failed, 766 passed` (stessi 2
  fallimenti noti) più `29 passed` per le 3 suite `reports/tests/`.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0041.json` +
  `reports/evidence/G4/OCOR-DEV-0041.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 9 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0041`: tutti e 13 i check verdi al primo push. PR #113
  mergiata (`600b1aa1e95123e0194af13d973637d9d0999231`), SHA
  post-merge verificata anche per `backbone.py` e
  `test_ocor_dev_0040.py` (invariati byte-per-byte rispetto al hash
  sigillato di OCOR-DEV-0040).

## 2026-09-14 — Sincronizzazione stato: OCOR-DEV-0041 (post-merge, OCOR-DEV-0042 pronto)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #113, su un branch dedicato
  (`governed/state-sync-ocor-dev-0041`).
- `baseline_commit` aggiornato a
  `600b1aa1e95123e0194af13d973637d9d0999231` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0041`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: insieme pronto =
  {`OCOR-DEV-0042` (wave 15), `OCOR-DEV-0045` (wave 16),
  `OCOR-DEV-0046` (wave 15), `OCOR-DEV-0048` (wave 15)};
  `OCOR-DEV-0042` selezionato per ordine numerico sull'intero insieme
  pronto — "Implement exact approved 44-transition C6 FSM".
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.

## 2026-09-14 — OCOR-DEV-0042: FSM completa a 44 transizioni approvate

- Implementato `ocor-runtime/src/ocor_runtime/c6/fsm.py`:
  `GovernedActionFSM` copre tutte e 44 le transizioni approvate della
  LLD v1.1 sezione 3.2, in complemento (non duplicazione) della slice
  eseguibile del percorso rappresentativo di OCOR-DEV-0030
  (`engine.py`, lasciato completamente intatto, verificato
  byte-per-byte invariato rispetto al proprio hash sigillato sia
  prima sia dopo questo task). La tabella runtime è ri-analizzata
  (non importata) dallo stesso formato a cinque colonne chiuso della
  LLD che lo spike sigillato di OCOR-DEV-0020
  (`spikes.c6_fsm_fidelity.generator`) ha già dimostrato fedele —
  precedente di ri-implementazione anziché importazione già stabilito
  da OCOR-DEV-0028/0037/0040, dato che `spikes/` è fuori dal pythonpath
  di produzione di `ocor-runtime`. `TRANSITIONS` è calcolata
  eagerly all'import del modulo: qualsiasi transizione mancante, in
  eccesso, duplicata o alterata semanticamente (source/evento-guardia/
  effetto durevole/destinazione) solleva `FSMTableIntegrityError`
  prima ancora che il modulo finisca di essere importato, facendo
  fallire sia l'avvio locale sia la CI — il criterio di accettazione
  negativo reso strutturale anziché solo testato.
- `GovernedActionFSM.apply()` persiste durevolmente un record
  immutabile (`PersistedEffect`) dell'effetto dichiarato di qualunque
  transizione venga applicata, tramite un sink iniettato (un oggetto
  Protocol o una semplice funzione, rispecchiando il parametro `sink`
  flessibile già usato da `GovernedActionEngine.execute`) — dimostra
  che ognuno dei 44 effetti dichiarati è persistibile, non solo i
  quattro gate che il percorso rappresentativo di OCOR-DEV-0030 già
  esercita end-to-end. Un fallimento del sink si propaga anziché
  essere silenziosamente inghiottito; un nuovo tentativo sulla stessa
  istanza dell'FSM recupera correttamente.
- Aggiunti 15 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0042.py`, puri in-memory,
  nessun backend esterno — incluso un cross-check diretto che il
  parser ri-implementato da questo task riproduce l'output dello
  spike sigillato di OCOR-DEV-0020 bit-per-bit sullo stesso documento
  LLD approvato (lo spike è importato solo in questo file di test,
  mai nel codice runtime sigillato). Tutti e 15 passati al primo
  tentativo, ripetuti 4 volte per determinismo, nessun bug trovato.
- Gate locali tutti verdi: `ruff`, `mypy` PASS, `validate_rccad.py`
  PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py --base origin/main` PASS (7
  percorsi), `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run, pytest
  completo via lo script `pytest` nudo con `OCOR_LIVE_POSTGRES_DSN`
  impostato contro il PostgreSQL reale di ocor-bootstrap: `2 failed,
  781 passed` (stessi 2 fallimenti noti) più `29 passed` per le 3
  suite `reports/tests/`.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0042.json` +
  `reports/evidence/G4/OCOR-DEV-0042.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 13 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0042`: tutti e 13 i check verdi al primo push. PR #115
  mergiata (`6e60235e89fb3eb7f88cf6f82d432f61a4b97007`), SHA
  post-merge verificata anche per `engine.py` (invariato
  byte-per-byte rispetto al hash sigillato di OCOR-DEV-0030).

## 2026-09-14 — Sincronizzazione stato: OCOR-DEV-0042 (post-merge, OCOR-DEV-0043 pronto)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #115, su un branch dedicato
  (`governed/state-sync-ocor-dev-0042`).
- `baseline_commit` aggiornato a
  `6e60235e89fb3eb7f88cf6f82d432f61a4b97007` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0042`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: insieme pronto =
  {`OCOR-DEV-0043` (wave 16, appena pronto, dipende solo da
  OCOR-DEV-0042), `OCOR-DEV-0045` (wave 16), `OCOR-DEV-0046` (wave 15),
  `OCOR-DEV-0048` (wave 15)}; `OCOR-DEV-0043` selezionato per ordine
  numerico sull'intero insieme pronto — "Implement Human Gate Decision
  Approval and dual control" (quorum, separation-of-duties, firme,
  scope e TTL rivalidati sia alla risoluzione sia al dispatch).
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.

## 2026-09-14 — OCOR-DEV-0043: Human Gate decision approval e dual control

- Implementato `ocor-runtime/src/ocor_runtime/c6/human_gate.py`:
  `HumanGateCoordinator` fornisce la logica reale di quorum,
  separation-of-duties, firma, scope e TTL che le transizioni Human
  Gate della tabella sigillata di OCOR-DEV-0042
  (`ACT-T06`/`T07`/`T08`/`T09a`/`T09b`) richiedono davvero.
  `validate()` filtra l'insieme di `GateSignature` presentate solo a
  quelle non escluse, risolte tramite l'`IdentityRegistry` sigillato
  (riusato invariato), con lo scope corretto ed entro il TTL della
  policy al momento della chiamata; la separation of duties è
  applicata non permettendo mai a un singolo `principal_id` di
  soddisfare due `required_roles` distinti. Poiché `validate()` è una
  funzione pura di (firme, scope, istante), chiamarla una volta alla
  risoluzione e di nuovo, invariata, subito prima del dispatch è ciò
  che dà al dual control il suo significato reale — una firma ancora
  entro il TTL alla risoluzione può essere scaduta al momento del
  dispatch, e il controllo identico nega allora esattamente come farebbe
  per una valutazione nuova, senza mai fidarsi di una risoluzione
  ormai stantia. In caso di successo restituisce l'identico
  `Approval` sigillato di OCOR-DEV-0030 che
  `GovernedActionEngine.execute` già accetta, tramite il suo
  costruttore pubblico — `engine.py` verificato invariato
  byte-per-byte sia prima sia dopo questo task.
- `validate()` accetta anche un `control_check` opzionale, così un
  chiamante può collegare una sonda reale e live del control plane
  (il pattern fail-closed sigillato di OCOR-DEV-0021/0014,
  `ControlStatus`/`SecurityControlError`) senza che questo modulo
  dipenda da alcun backend concreto specifico.
- Aggiunti 13 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0043.py`: scenari di
  quorum/copertura-ruoli/SoD/TTL/scope/esclusione/identità-non-risolta,
  un test di dual control che dimostra che la stessa approvazione
  nega di nuovo a un istante di dispatch successivo una volta scaduto
  il TTL, un vero test di fault-injection contro una porta locale
  genuinamente irraggiungibile tramite il `bounded_probe` sigillato di
  OCOR-DEV-0021 (importato solo in questo file di test), e un test di
  integrazione che collega l'output di `HumanGateCoordinator`
  direttamente nel vero `GovernedActionEngine` end-to-end.
- Due bug genuini di scrittura dei test trovati e corretti prima
  della sigillatura: due test lasciavano solo 1 firmatario valido
  distinto dopo aver escluso il proponente/l'identità non risolta,
  quindi `QUORUM_NOT_MET` scattava prima che `MISSING_REQUIRED_ROLE`
  potesse mai essere raggiunto — corretto aggiungendo un terzo
  firmatario valido e distinto per isolare specificamente il
  comportamento di copertura-ruoli previsto.
- Gate locali tutti verdi: `ruff`, `mypy` PASS, `validate_rccad.py`
  PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py --base origin/main` PASS (7
  percorsi), `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run, pytest
  completo via lo script `pytest` nudo con `OCOR_LIVE_POSTGRES_DSN`
  impostato contro il PostgreSQL reale di ocor-bootstrap: `2 failed,
  794 passed` (stessi 2 fallimenti noti) più `29 passed` per le 3
  suite `reports/tests/`.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0043.json` +
  `reports/evidence/G4/OCOR-DEV-0043.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 14 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0043`: tutti e 13 i check verdi al primo push. PR #117
  mergiata (`3c89c90c1c870159564c8573ff7c5793da86061a`), SHA
  post-merge verificata anche per `engine.py` e `fsm.py` (invariati
  byte-per-byte rispetto ai rispettivi hash sigillati).

## 2026-09-14 — Sincronizzazione stato: OCOR-DEV-0043 (post-merge, OCOR-DEV-0044 pronto)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #117, su un branch dedicato
  (`governed/state-sync-ocor-dev-0043`).
- `baseline_commit` aggiornato a
  `3c89c90c1c870159564c8573ff7c5793da86061a` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0043`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: insieme pronto =
  {`OCOR-DEV-0044` (wave 17, appena pronto, dipende da OCOR-DEV-0042 e
  OCOR-DEV-0043), `OCOR-DEV-0045` (wave 16), `OCOR-DEV-0046` (wave
  15), `OCOR-DEV-0048` (wave 15)}; `OCOR-DEV-0044` selezionato per
  ordine numerico sull'intero insieme pronto — "Implement compensation
  reconciliation break-glass and emergency stop" (esiti sconosciuti,
  compensazione, precedenza dello stop e break-glass producono
  evidenza immutabile e stato fail-safe; negativo: una race sullo
  stop non può emettere dopo il proprio stop epoch, un effetto
  ambiguo non idempotente non può essere ritentato automaticamente).
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.

## 2026-09-14 — OCOR-DEV-0044: compensation reconciliation, break-glass, emergency stop

- Implementato `ocor-runtime/src/ocor_runtime/c6/safety.py` con tre
  meccanismi di sicurezza reali, tutti nuovi file, che compongono ma
  non toccano mai i file sigillati `engine.py` (OCOR-DEV-0030),
  `fsm.py` (OCOR-DEV-0042) e `human_gate.py` (OCOR-DEV-0043) —
  verificati invariati byte-per-byte sia prima sia dopo il task.
  `EmergencyStopController` implementa la macchina approvata
  `NORMAL -> STOPPING -> STOPPED -> RESET_PENDING -> NORMAL` (LLD
  4.3) sotto un vero `threading.RLock`; `guard_dispatch` nega a meno
  che il sistema sia `NORMAL` E l'epoch di fencing presentato sia
  esattamente quello corrente, e `confirm_reset` emette sempre un
  epoch nuovo di zecca, così un reset non riabilita mai un lease o un
  command fenced all'epoch pre-stop; il reset stesso richiede due
  approvatori umani distinti e risolti (tramite l'`IdentityRegistry`
  sigillato, riusato invariato). `BreakGlassController` implementa la
  concessione eccezionale limitata e dual-human di LLD 4.2 (TTL
  massimo 15 minuti per ADD 5.5); `authorize()` è una funzione pura di
  (grant, capability, istante) rieseguita a ogni uso — scaduta,
  revocata, capability proibita (denylist fissa: creare una Decision,
  ridurre il marking, disabilitare provenance/audit, ignorare
  l'emergency stop, cambiare il release pin, autorizzare R3 senza
  quorum, accedere fuori compartment) o stop attivo negano sempre,
  mai solo al momento della concessione; ogni uso richiede un
  riferimento di review obbligatorio. `OutcomeReconciler` implementa
  il percorso di riconciliazione degli esiti ambigui e della
  compensazione `ACT-T18a`/`T18b`/`T20a-c`/`T21`-`T21e`/`T24`/`T25`:
  un timeout ambiguo sospende il retry e apre la riconciliazione;
  un'Evidence reale la risolve; nessuna Evidence prima della
  deadline non fa alcuna inferenza ed esegue l'escalation a
  `INDETERMINATE` con adjudication aperta solo una volta che la
  deadline è realmente trascorsa; `require_may_auto_retry` è la
  claim negativa centrale del task resa eseguibile — un esito
  ambiguo o indeterminato il cui effetto non è provato idempotente
  non può mai essere ritentato automaticamente.
- Aggiunti 29 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0044.py`, inclusi un vero
  test di fault-injection multi-thread (thread OS reali che
  competono su 8 tentativi di dispatch contro un'attivazione
  concorrente dello stop, a dimostrare che il lock reale rende
  atomica la cattura-e-verifica dell'epoch) ripetuto 5 volte
  aggiuntive da solo più l'intera suite altre 3 volte per ulteriore
  fiducia nel determinismo, e un test di integrazione che combina la
  precedenza dello stop con la riconciliazione end-to-end.
- Un genuino finding di `mypy` auto-rilevato e corretto prima della
  sigillatura: `tuple(sorted(distinct))` ha tipo inferito
  `tuple[str, ...]`, non il `tuple[str, str]` dichiarato dal campo
  `BreakGlassGrant.approvers` — corretto scomponendo esplicitamente
  il set ordinato di 2 elementi in una coppia `(first, second)`.
- Gate locali tutti verdi: `ruff`, `mypy` PASS (dopo la correzione),
  `validate_rccad.py` PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py --base origin/main` PASS (7
  percorsi), `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run, pytest
  completo via lo script `pytest` nudo con `OCOR_LIVE_POSTGRES_DSN`
  impostato contro il PostgreSQL reale di ocor-bootstrap: `2 failed,
  823 passed` (stessi 2 fallimenti noti) più `29 passed` per le 3
  suite `reports/tests/`.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0044.json` +
  `reports/evidence/G4/OCOR-DEV-0044.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 16 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0044`: tutti e 13 i check verdi al primo push. PR #119
  mergiata (`cd8ad4ffbc942d10aabd9bbb40332427795316cf`), SHA
  post-merge verificata anche per `engine.py`, `fsm.py` e
  `human_gate.py` (tutti invariati byte-per-byte rispetto ai
  rispettivi hash sigillati).

## 2026-09-14 — Sincronizzazione stato: OCOR-DEV-0044 (post-merge, OCOR-DEV-0045 pronto)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #119, su un branch dedicato
  (`governed/state-sync-ocor-dev-0044`).
- `baseline_commit` aggiornato a
  `cd8ad4ffbc942d10aabd9bbb40332427795316cf` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0044`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: insieme pronto =
  {`OCOR-DEV-0045` (wave 16), `OCOR-DEV-0046` (wave 15),
  `OCOR-DEV-0048` (wave 15)}; `OCOR-DEV-0045` selezionato per ordine
  numerico sull'intero insieme pronto — "Implement C7 scenario and
  causal runtime" (branch non possono scrivere main; interventi,
  controfattuali, incertezza e sensitivity producono risultati
  sigillati e riproducibili; negativo: un'identificazione non
  supportata restituisce abstain e nessuna claim causale
  autorevole).
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.

## 2026-09-14 — OCOR-DEV-0045: C7 scenario e causal runtime

- Implementato `ocor-runtime/src/ocor_runtime/c7/runtime.py` (nuova
  directory pacchetto `c7/`), completamente separato e mai a contatto
  con il sigillato `ocor_runtime.c7_emission.py` (un concern C7
  diverso — emissione durevole e ordinata degli effetti). Ri-implementa
  il gate di identificazione fail-closed identify-or-abstain dello
  spike sigillato di OCOR-DEV-0022
  (`spikes.causal_reproducibility.oracle`, già riusato invariato dal
  mission thread di OCOR-DEV-0031) come codice di produzione
  (verifica dei pin dichiarati dal chiamante su model/data/
  intervention; requisito di branch `scenario/` con `main` sempre in
  abstain `MAIN_CONTAMINATED`; corrispondenza del digest di release;
  set fattuale non vuoto; nessun confounding non risolto; valore di
  intervento in dominio; positività) — condiviso da tutte e quattro
  le operazioni pubbliche, così ognuna va in abstain esattamente
  nelle stesse condizioni del sigillato stimatore ATE dello spike.
  `estimate_intervention` ri-implementa lo stesso
  `STRATIFIED_BACKDOOR_ATE` già dimostrato dallo spike. Tre nuove
  operazioni che lo spike stesso non calcolava mai:
  `estimate_counterfactual` imputa l'esito di una specifica unità
  sotto il trattamento opposto tramite la differenza di media
  entro-strato; `estimate_uncertainty` calcola un intervallo di
  confidenza bootstrap deterministico, seminato dal `query.seed`
  sigillato, così input pinnati identici riproducono sempre gli
  stessi bound; `estimate_sensitivity` ricalcola l'ATE dopo uno shift
  additivo di confounding su ogni osservazione del braccio di
  controllo, riportando se il segno dell'effetto sopravvive — una
  tecnica di sensitivity "tipping point" reale, standard e
  onestamente etichettata, non inventata.
- Aggiunti 27 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0045.py`, puri in-memory,
  nessun backend esterno — incluso un cross-check diretto che il
  percorso di intervention ri-implementato riproduce l'oracle
  sigillato di OCOR-DEV-0022 bit-per-bit sugli stessi dati di
  fixture (effect=-4, method=STRATIFIED_BACKDOOR_ATE). Tutti e 27
  passati al primo tentativo, ripetuti 4 volte per determinismo.
- Due genuini finding di `mypy` e uno di `ruff` auto-rilevati e
  corretti prima della sigillatura: import `dataclasses.field` non
  usato; l'argomento `effect` di `CausalOutcome` che inferiva un
  tipo union indicizzando un dict `body` a valori misti (corretto
  calcolando prima un locale dedicato `formatted_effect`); una
  variabile Decimal che ombreggiava un'altra variabile intera
  `treated` nello stesso scope di funzione (corretto rinominando in
  `control_mean`/`treated_mean`).
- Gate locali tutti verdi: `ruff`, `mypy` PASS (dopo le correzioni),
  `validate_rccad.py` PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py --base origin/main` PASS (7
  percorsi), `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run, pytest
  completo via lo script `pytest` nudo con `OCOR_LIVE_POSTGRES_DSN`
  impostato contro il PostgreSQL reale di ocor-bootstrap: `2 failed,
  850 passed` (stessi 2 fallimenti noti) più `29 passed` per le 3
  suite `reports/tests/`.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0045.json` +
  `reports/evidence/G4/OCOR-DEV-0045.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 11 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0045`: tutti e 13 i check verdi al primo push. PR #121
  mergiata (`c6406feeddbad4ca6f778fdaeca9f89110856738`), SHA
  post-merge verificata anche per `c7_emission.py` (invariato
  byte-per-byte rispetto al proprio hash sigillato).

## 2026-09-14 — Sincronizzazione stato: OCOR-DEV-0045 (post-merge, OCOR-DEV-0046 pronto)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #121, su un branch dedicato
  (`governed/state-sync-ocor-dev-0045`).
- `baseline_commit` aggiornato a
  `c6406feeddbad4ca6f778fdaeca9f89110856738` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0045`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: insieme pronto =
  {`OCOR-DEV-0046` (wave 15), `OCOR-DEV-0048` (wave 15)};
  `OCOR-DEV-0046` selezionato per ordine numerico sull'intero insieme
  pronto — "Implement C8 AgentRun Task Assignment Commitment Handoff
  and Dissent" (le transizioni di stato di agent/team preservano
  authority, commitment, handoff e dissent come record espliciti;
  negativo: un agent non può auto-concedersi una capability,
  sopprimere il dissent o mutare lo stato canonico).
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.

## 2026-09-14 — OCOR-DEV-0046: C8 AgentRun assignment, commitment, handoff, dissent

- Implementato `ocor-runtime/src/ocor_runtime/c8/orchestrator.py`
  (nuova directory pacchetto `c8/`), costruito attorno al sigillato
  `ocor_runtime.c8_agent.AgentKernel` (preesistente a questa sessione,
  lasciato completamente intatto) e a `CapabilityAuthority`/
  `AtomicOutboxStore` (sigillati, riusati invariati, composti solo
  tramite i loro metodi pubblici `issue()`/`authorize()`/`write()`/
  `get()`). `assign()`/`commit()`/`handoff()`/`register_dissent()`
  richiedono ciascuno una vera capability lease autorizzata
  dall'authority sigillata prima di qualsiasi altra cosa, e scrivono
  il record risultante attraverso il commit a scrittore singolo dello
  store sigillato, con l'orchestrator come unico `writer_id`
  autoritativo dello store — rendendo strutturali, non solo testate,
  le tre claim negative del task: un agent non può auto-concedersi
  una capability (`authorize()` accetta solo una lease già emessa
  dall'authority stessa); un agent non può mutare direttamente lo
  stato canonico (il vincolo di scrittore singolo dello store
  sigillato, `SingleWriterViolation`, rifiuta qualunque `writer_id`
  diverso da quello dell'orchestrator); un dissent non può mai essere
  soppresso (`Dissent` è un dataclass frozen, `dissents` è una tupla
  di sola lettura e append-only, nessun metodo di rimozione esiste).
- Aggiunti 12 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0046.py`, inclusa una vera
  prova di fault-injection del vincolo di scrittore singolo e un
  intero ciclo di vita handoff-poi-recommit.
- Un genuino bug di design trovato e corretto prima della
  sigillatura: la idempotency key di `commit()` necessitava di un
  vero contatore di tentativi per-aggregate (derivato dalla versione
  del documento nello store tramite `store.get()`) per distinguere
  correttamente un recommit legittimo da parte di un nuovo agent
  (dopo un handoff reale) da una replay idempotente dello stesso
  commit — lo store sigillato ha correttamente sollevato
  `ConcurrencyConflict` sul design originale a chiave fissa, un bug
  genuino nel nuovo codice, non nello store sigillato; corretto con
  un versionamento a concorrenza ottimistica appropriato, applicato
  sia ad `assign()` sia a `commit()`.
- Gate locali tutti verdi: `ruff`, `mypy` PASS, `validate_rccad.py`
  PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py --base origin/main` PASS (7
  percorsi), `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run, pytest
  completo via lo script `pytest` nudo con `OCOR_LIVE_POSTGRES_DSN`
  impostato contro il PostgreSQL reale di ocor-bootstrap: `2 failed,
  862 passed` (stessi 2 fallimenti noti) più `29 passed` per le 3
  suite `reports/tests/`.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0046.json` +
  `reports/evidence/G4/OCOR-DEV-0046.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 9 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0046`: tutti e 13 i check verdi al primo push. PR #123
  mergiata (`fc9f75bbd8326c22b46573abd0ac3ce11b4591a8`), SHA
  post-merge verificata anche per `c8_agent.py` (invariato
  byte-per-byte rispetto al proprio hash sigillato).

## 2026-09-14 — Sincronizzazione stato: OCOR-DEV-0046 (post-merge, OCOR-DEV-0047 pronto)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #123, su un branch dedicato
  (`governed/state-sync-ocor-dev-0046`).
- `baseline_commit` aggiornato a
  `fc9f75bbd8326c22b46573abd0ac3ce11b4591a8` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0046`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: insieme pronto =
  {`OCOR-DEV-0047` (wave 18, appena pronto), `OCOR-DEV-0048` (wave
  15)}; `OCOR-DEV-0047` selezionato per ordine numerico sull'intero
  insieme pronto — "Implement C8 tool boundary sandbox budgets and
  kill switch" (ogni chiamata a model/tool è vincolata da capability,
  purpose, marking, budget e stop, con receipt; negativo: sintassi di
  escape, lavoro fuori budget o capability revocata non producono
  alcun effetto sul tool). 23 dei 84 task totali restano non ancora
  completati.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.

## 2026-09-14 — OCOR-DEV-0047: C8 tool boundary sandbox, budget, kill switch

- Implementato `ocor-runtime/src/ocor_runtime/c8/tool_runtime.py`:
  `ToolCallRuntime` collega cinque vincoli reali fail-closed intorno
  a ogni chiamata a un tool, tutti applicati prima di qualsiasi
  effetto: capability (`CapabilityAuthority.authorize`, mai
  auto-concessa), purpose (il sigillato `GovernedContext`, già
  fail-closed su un purpose mancante alla propria costruzione),
  marking (`MarkingEngine.require_authorized` contro la clearance
  reale del chiamante), stop (il `guard_dispatch` sigillato di
  `EmergencyStopController` da OCOR-DEV-0044), e budget
  (`TokenBudget.consume`, addebitato prima che il tool venga mai
  tentato, mai rimborsato dopo). Solo una volta che tutti e cinque
  sono superati l'espressione reale raggiunge il sigillato
  `StrictSandbox` per l'esecuzione con whitelist AST — un tentativo
  di sintassi di escape viene rifiutato lì, prima che la funzione
  tool registrata venga mai chiamata. Tutti i componenti sigillati
  riusati (`c8_agent.py`, `c8/orchestrator.py`, `c6_capabilities.py`,
  `c4_marking.py`, `c6/safety.py`, `kernel/governed_context.py`) sono
  verificati invariati byte-per-byte sia prima sia dopo questo task.
- Aggiunti 11 nuovi test in
  `ocor-runtime/tests/tasks/test_ocor_dev_0047.py`, inclusa una prova
  di integrazione che esegue in sequenza una chiamata legittima e
  quattro distinti scenari di diniego (capability revocata, clearance
  insufficiente, sintassi di escape, fuori budget) contro una lista
  condivisa di effetti, dimostrando che esattamente un solo effetto
  reale viene mai prodotto, indipendentemente da quanti modi diversi
  si tenti e si neghi una chiamata. Tutti e 11 passati al primo
  tentativo, ripetuti 4 volte per determinismo, nessun bug trovato.
- Gate locali tutti verdi: `ruff`, `mypy` PASS, `validate_rccad.py`
  PASS, `validate_language_policy.py` PASS,
  `validate_ocor_change_scope.py --base origin/main` PASS (7
  percorsi), `validate_ocor_development_plan.py --base-ref origin/main
  --authorized-extension` PASS dopo il consueto doppio-run, pytest
  completo via lo script `pytest` nudo con `OCOR_LIVE_POSTGRES_DSN`
  impostato contro il PostgreSQL reale di ocor-bootstrap: `2 failed,
  873 passed` (stessi 2 fallimenti noti) più `29 passed` per le 3
  suite `reports/tests/`.
- Evidenza sigillata: `reports/evidence/G4/OCOR-DEV-0047.json` +
  `reports/evidence/G4/OCOR-DEV-0047.log`.
  `reports/evidence/G4/MANIFEST.json` esteso con inserimento
  chirurgico (2 nuovi artifact, 8 nuovi requirement_results).
- Aggiornamento dei tre file di stato eseguito come PR dedicata
  immediatamente dopo il merge del task, non incluso nel commit del
  task.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
- `OCOR-DEV-0047`: tutti e 13 i check verdi al primo push. PR #125
  mergiata (`355ff68cc65053f55b26812843b4a7cb19e9b177`), SHA
  post-merge verificata per tutti i file sigillati riusati.

## 2026-09-14 — Sincronizzazione stato: OCOR-DEV-0047 (post-merge, OCOR-DEV-0048 pronto)

- Sincronizzazione immediata dei tre file di stato subito dopo il
  merge della PR #125, su un branch dedicato
  (`governed/state-sync-ocor-dev-0047`).
- `baseline_commit` aggiornato a
  `355ff68cc65053f55b26812843b4a7cb19e9b177` in entrambi
  `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`; `OCOR-DEV-0047`
  aggiunto a `completed_evidence_tasks`.
- Ricalcolata la prontezza dal backlog JSON: insieme pronto =
  {`OCOR-DEV-0048` (wave 15)} — l'UNICO task pronto rimasto dalla
  frontiera visibile attuale (22 degli 84 task totali non ancora
  completati). "Integrate OPA Keycloak SPIFFE OpenBao and mTLS" —
  a differenza degli ultimi sette task (0041-0047, tutti slice C6/C7/
  C8 puramente in-memory), questo è un task a backend reale: servizi
  reali (OPA, Keycloak, SPIFFE, OpenBao, mTLS) devono applicare least
  privilege, workload identity, policy bundle, delegation e
  isolamento dei secret; negativo: un'interruzione del control plane
  o un bundle di policy stantio devono fallire in modo chiuso con
  diagnostica correlata.
- Nessun codice sorgente toccato: gate locali rieseguiti comunque per
  protocollo standard e confermati invariati.

## 2026-09-15 — Remediation governate della revisione codice (REM-0010/0011/0012)

- Su mandato esplicito del Product Owner ("procedi autonomamente come
  consigliato"), implementati come change set di remediation i finding
  della revisione `reports/review/OCOR_FULL_CODE_REVIEW_2026-09-15.md`,
  in modalità implementazione DEC-210, branch `cursor/code-review-remediation-1935`,
  baseline `b1eefb3cc2b67383596a6b2a6801d2c3b6ba424d`.
- `OCOR-DEV-REM-0010` (RVW-01/-02): escape dei literal TypeQL in
  `c4/typedb_adapter.py` e validazione fail-closed degli IRI in
  `c4/jena_adapter.py`. TDD RED `a12857a` → GREEN `bd1c00e`.
- `OCOR-DEV-REM-0011` (RVW-04): `c1/frontend.py` rigetta un
  `execution_owner` malformato con diagnostica `TYPE_ERROR` invece di
  crashare. TDD RED `75e1ffd` → GREEN `a252096`.
- `OCOR-DEV-REM-0012` (RVW-05): `scripts/validate_rccad.py` include le
  modifiche staged nel precheck di immutabilità. TDD RED `da482c5` →
  GREEN `64db341`.
- Gate locali verdi al tip: `verify.py` 14/0, `ruff`, `mypy --strict`,
  language-policy, change-scope, `validate_rccad` `PASS_LOCAL_PRECHECK`;
  suite runtime 778 passed (era 765; +13 test REM) con gli stessi
  residui dipendenti da Docker (TypeDB/Fuseki/Kafka/OpenBao), che sono
  `NOT_EXECUTED` in locale e validati in CI.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`.
  `inputs/` invariato. Record di assurance:
  `reports/assurance/OCOR-DEV-REM-001{0,1,2}-RCCAD/`.
- Prossima azione: verifica indipendente + CI verde sull'HEAD esatto
  prima di seal/merge governato; poi ripresa dello sviluppo su
  `OCOR-DEV-0048`. Nota: il check `ocor-delivery-activation`
  `validate_ocor_change_scope --branch` fallisce solo per il prefisso
  `cursor/` del branch (accetta `task/`/`governed/`); l'integrazione
  avviene via branch `governed/` come per la PR #126.

## 2026-10-01 — Governed change set: identità immagine Fuseki (cambio macchina di sviluppo)

- Mandato esplicito del Product Owner (2026-10-01): aggiornare in un change set
  `governed/` dedicato soltanto `build.output_sha256` dell'entry `fuseki` in
  `infra/services.lock.json`, con l'identificativo dell'immagine
  `ocor/jena-fuseki:6.2.0` ricostruita su questa macchina.
- Host: `nepryoon`. Motivazione: cambio della macchina di sviluppo; l'identificativo
  dell'immagine registrato sulla macchina precedente non è riproducibile qui.
- Condizioni di autorizzazione tutte verificate e registrate:
  - `infra/fuseki/Dockerfile` invariato rispetto a `origin/main` (`git diff` vuoto);
  - `build.base_image` invariato (`eclipse-temurin@sha256:db168953…`) e la build ha
    usato davvero quella base: i 5 layer dell'immagine base sono prefisso dei layer
    dell'immagine Fuseki locale;
  - checksum SHA-512 del pacchetto sorgente scaricato indipendentemente da
    `archive.apache.org` = `build.source_sha512` = `ba65f586…` (MATCH);
  - il controllo di identità in `scripts/bootstrap_development_environment.py` resta
    invariato (nessuna modifica al codice di verifica).
- Valore precedente: `output_sha256 = 7a55d816b0031cae6f2e2c5262f0bd1bcd247ccbe8cf8c027347083227c574b7`.
- Nuovo identificativo: `output_sha256 = a1eb484a7d056a897c7bc832fb735b06136fc876aa90da3055d9882bc1b8d9e3`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`; `inputs/` invariato.

## 2026-09-16 — OCOR-DEV-0048 BLOCKED (ambiente, non normativo)

- Ripresa autonoma (heartbeat orario) al baseline `1aaef13885ed142646d0ed35c995078c30d9f174`
  (== `origin/main` dopo il merge di #128/#129/#130). Ricalcolato il ready set
  direttamente dal backlog JSON: `{OCOR-DEV-0048}` (wave 15) è l'UNICO task pronto
  (22 di 84 non completati).
- `OCOR-DEV-0048` (WS-11, G4) è un task a **backend reale**: richiede che
  OPA/Keycloak/SPIFFE/OpenBao/mTLS applichino davvero i controlli, con evidenza
  qualificante **content-addressed e NON-SKIPPED** (`validate_runtime_evidence.py --non-skipped`).
- Verifica dell'ambiente: **nessun Docker** e **nessun backend raggiungibile**
  (porte 8181/8080/8200/1729/6363 tutte chiuse); la venv di review non ha `cryptography`
  (solo la CLI `openssl`). La CI (`ocor-delivery-activation`/`ocor-rccad`/`ocor-validation-closure`)
  provisiona **solo** OPA/Keycloak/OpenBao — niente SPIRE, niente mTLS — e **non**
  committa file di evidenza content-addressed. Il precedente a backend reale
  `OCOR-DEV-0021`/`0043` ha sigillato l'evidenza da un run **locale** sullo stack
  `docker compose -p ocor-bootstrap`, qui impossibile.
- Decisione fail-closed conforme al mandato PO ("nessuna attestazione falsa"):
  il task è **HELD BLOCKED**, non marcato completo; nessuna evidenza fabbricata.
  Registrato il blocker `OCOR-DEV-0048-LIVE-BACKEND-UNAVAILABLE-IN-ENV` in
  `EXECUTION_STATE.json`/`MODEL_HANDOFF.json` con l'azione successiva esatta.
  Poiché è l'unico task pronto, il fronte del backlog non può avanzare in questo
  ambiente senza un runner con Docker e lo stack `ocor-bootstrap` completo.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione (su runner con Docker): `deploy/bootstrap/compose.yaml` +
  `deploy/bootstrap/init/initialize_services.py`, poi implementare `control_plane.py`
  e `test_ocor_dev_0048.py` su branch `task/OCOR-DEV-0048-<slug>`, eseguire la suite
  sullo stack live e sigillare `reports/evidence/G4/OCOR-DEV-0048.{json,log}`+`MANIFEST`
  con il `raw_output_sha256` reale.

## 2026-10-01 — Remediation R1: riallineamento dello stato

- Change set `governed/` di state sync; la PR #131 (draft
  `governed/ocor-dev-0048-control-plane-1935`) è stata chiusa come **superseded**:
  falliva `rccad-methodology` e `tooling-policy` per `RCCAD-NONCANONICAL-JSON` su
  `EXECUTION_STATE.json` (JSON non canonico). La sua voce di `ITERATION_LOG.md`
  (evento storico reale del 2026-09-16) è riportata integralmente qui sopra.
- `baseline_commit` portato all'HEAD di `main` = `276fc6510cb2340a41335f4b12cac864a7299573`,
  allineato in `EXECUTION_STATE.json` e `MODEL_HANDOFF.json`.
- Registrati i merge di #128 (REM-0010/0011/0012), #129 (bounded retry sui pull delle
  immagini di servizio), #130 (auto-merge-on-green label-gated) e #132 (identità
  immagine Fuseki, cambio macchina di sviluppo).
- `GITHUB-BRANCH-PROTECTION-001` aggiornato come **risolto lato server** dal ruleset
  `23412233` ("Require status checks to pass before merging"), attivo dal 2026-09-15:
  `enforcement=active`, 13 check di stato obbligatori, nessun attore di bypass.
  Evidenza: `gh api repos/nepryoon/ocor-detailed-design/rulesets/23412233`.
- Il blocco di `OCOR-DEV-0048` registrato dalla PR #131 era specifico dell'ambiente
  cloud senza Docker. Preflight locale su questa macchina: tutti gli 11 servizi
  `ocor-bootstrap` READY (`scripts/verify_external_services.py --execute --typed`
  → `PASS`), SPIRE incluso. Il task resta pronto e non è bloccato.
- Ready set ricalcolato dal backlog JSON: {`OCOR-DEV-0048` (wave 15)} — unico task
  pronto (22 di 84 non completati).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: R2 — verifica indipendente mancante di REM-0010/0011/0012.

## 2026-10-01 — Remediation R2: processazione del verdetto indipendente (REM-0010/0011/0012)

- Change set `governed/` (branch `governed/remediation-r2-verdict-processing`, basato su
  `8f4d2aa168018e950ad3b85f1a6a78af81fb2fb6` = HEAD di `main` post-R1).
- Il verdetto indipendente richiesto da R2 (`request_id`
  `OCOR-DEV-REM-0010-0011-0012-1aaef13885ed-0`, `review_type=REMEDIATION`,
  `base_sha=6f8b8e6673f4ffe16370934a94ed6be9695fc6d7`,
  `head_sha=1aaef13885ed142646d0ed35c995078c30d9f174`) è **`NO_GO`** con quattro finding
  bloccanti: `VF-001` (high, TypeDB commit_id/watermark senza safe literal rendering),
  `VF-002` (medium, validate_rccad `line.split("\n")` sui path), `VF-003` (high, record
  di evidenza non content-addressed), `VF-004` (medium, re-verifica su HEAD post-Fuseki).
- Il risultato è stato **appeso in append** (senza riscrivere i campi storici) ai tre
  record `reports/assurance/OCOR-DEV-REM-001{0,1,2}-RCCAD/evidence.json` nel campo
  `independent_verification_result`. I record restano
  `CANDIDATE_PENDING_INDEPENDENT_VERIFICATION` e **non** sono sigillati.
- **Erratum di collisione ID**: `OCOR-DEV-REM-0010` è doppiamente assegnato (correzione
  `$ref` del generatore, PR #63 2026-09-12; hardening adapter C4, PR #128 2026-09-15).
  Al secondo è assegnato il primo `OCOR-DEV-REM-*` libero — `OCOR-DEV-REM-0013` — come
  **alias canonico**, senza rinominare la storia (campo `id_alias` nel record).
- **REM aperte**: `OCOR-DEV-REM-0014` (TypeDB commit_id/watermark), `OCOR-DEV-REM-0015`
  (validate_rccad path NUL-delimited), `OCOR-DEV-REM-0016` (record content-addressed),
  registrate come record README-only `REGISTERED_OPEN_FOR_IMPLEMENTATION`.
- **Richieste di decisione** (riservate al PO, non bloccanti): `RVW-03`, `INFO-A`,
  `INFO-C` in `reports/development/decision_requests/` con blocker
  `OPEN_PO_DECISION_REQUIRED` in `EXECUTION_STATE.json`.
- Allowlist `extension_paths` di `scripts/validate_ocor_development_plan.py` estesa per i
  6 nuovi file; self-hash riallineato in `reports/planning/OCOR_PLAN_RUN_STATE.json`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: implementare `OCOR-DEV-REM-0014` (TDD su TypeDB reale), poi
  `OCOR-DEV-REM-0015` e `OCOR-DEV-REM-0016`, poi ri-richiedere la verifica indipendente
  su un HEAD che include l'aggiornamento Fuseki autorizzato e i fix.

## 2026-10-01 — Remediation R2: merge OCOR-DEV-REM-0014 (state sync)

- Change set `governed/state-sync-ocor-dev-rem-0014` (docs/state), basato sull'HEAD di
  `main` = `a8c5e5d92513b1a333593bbc56c411b61773f29b` (merge commit di PR #135).
- `OCOR-DEV-REM-0014` (TypeDB commit_id/watermark safe literal rendering + identifier
  contract) **mergiata** con PR #135: 13 check verdi sull'HEAD esatto `0820fec…`,
  verdetto indipendente `GO_FOR_EVIDENCE_SEAL` (repair cycle 1), zero finding.
- Evidenza content-addressed sigillata in
  `reports/assurance/OCOR-DEV-REM-0014-RCCAD/`: record `04f60e45…`, raw log `8733c7c2…`;
  hash verificati invariati post-merge (nessuna riscrittura dei record sigillati).
- `baseline_commit` → `a8c5e5d…`; `latest_ci_evidence` aggiornato con i 6 run ID della
  CI di PR #135 (13 check: unit, contract, integration-postgresql, evidence, supply-chain,
  rccad-methodology, tooling-policy, type-and-lint-gate, validation-closure,
  backend-compatibility, fgm-contract-readiness, mandatory-gates, delivery-activation).
- `remediation_status.R2_independent_verification`: `rems_completed += [OCOR-DEV-REM-0014]`;
  `next_actions` ridotto a REM-0015, REM-0016 e ri-verifica indipendente.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: implementare `OCOR-DEV-REM-0015` (validate_rccad NUL-delimited path
  handling), poi `OCOR-DEV-REM-0016` (record content-addressed), poi ri-richiedere la
  verifica indipendente su un HEAD che include l'aggiornamento Fuseki autorizzato e i fix.

## 2026-10-01 — Remediation R2: escalation OCOR-DEV-REM-0015 (VF-001 toolchain lock)

- Change set `governed/state-sync-ocor-dev-rem-0015-escalation` (docs/state), basato
  sull'HEAD di `main` = `dbf06498bb1222674eed72e0794dc673bc473c3f`.
- `OCOR-DEV-REM-0015` (validate_rccad NUL-delimited path handling) ha esaurito **2 cicli
  di riparazione**. Il verdetto indipendente del repair cycle 1
  (`request_id` `OCOR-DEV-REM-0015-92e194e2965f-1`, `head_sha` `92e194e2965f…`) è
  **`NO_GO`** con un solo finding bloccante: `VF-001` (severity medium).
- `VF-001` non è una regressione del codice: il fix `git_changed()` è corretto (il
  verifier dichiara "nessuna correzione funzionale richiesta"). È una **identità della
  toolchain non riproducibile**: `infra/toolchain.lock.json` registra versioni/digest
  (`docker` 29.7.2, `git` 2.55.0, `gh` 2.99.0, `node` 20.20.2, `uv` 0.12.5) acquisiti
  sulla macchina precedente; sulla macchina attuale la toolchain host differisce e il
  binario ufficiale di `node` 20.20.2 ha digest `62954886…` diverso dal lock `4446eb8e…`
  (non riproducibile dalle sorgenti ufficiali). La suite completa passa (905/905, zero
  skip) ma non attesta la riproduzione con la toolchain approvata.
- **Riservato al PO**: il verifier richiede o la toolchain conforme al lock o un
  aggiornamento governato del toolchain lock con autorità esplicita. L'autorizzazione
  Fuseki del 2026-10-01 copre solo `infra/services.lock.json` e non si estende al
  toolchain. Registrata **decision request `TOOLCHAIN-LOCK-UPDATE`** (bloccante) in
  `reports/development/decision_requests/`.
- **Escalation** (§8, 2 cicli esauriti): `remediation_status.R2_independent_verification`
  → `rem_0015_escalation` (`BLOCKED`), blocker `TOOLCHAIN-LOCK-UPDATE` in
  `EXECUTION_STATE.json` (`OPEN_PO_DECISION_REQUIRED`), `blocked_tasks` =
  [`OCOR-DEV-REM-0015`, `OCOR-DEV-REM-0016`]. L'evidenza resta
  `CANDIDATE_PENDING_INDEPENDENT_VERIFICATION` e **non** è sigillata.
- `baseline_commit` → `dbf06498…` (HEAD di `main` alla base di questo change set).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: R3 (validator fail-closed `scripts/validate_evidence_input_drift.py`,
  TDD RED-first) come change set `governed/` con gate locali + CI (nessuna verifica
  indipendente), poi fase di implementazione di `OCOR-DEV-0048`.

## 2026-10-01 — Governed: ri-acquisizione toolchain lock (decisione PO TOOLCHAIN-LOCK-UPDATE)

- Change set `governed/toolchain-lock-update` basato sull'HEAD di `main`
  (`84d7706…`). Esegue la decisione del Product Owner del 2026-10-01
  (`TOOLCHAIN-LOCK-UPDATE`): ri-acquisisce sulla macchina attuale le voci di
  `infra/toolchain.lock.json` che non corrispondono, a versione invariata e digest
  verificato contro i checksum ufficiali. **Nessuna modifica** a validator, schema o
  codice di verifica (`scripts/ocor_bootstrap_lib.py`, `scripts/preflight_environment.py`,
  `infra/toolchain.lock.schema.json` invariati).
- **Oggetto misurato dichiarato**: `integrity` = SHA-256 del **binario installato**
  (risolto via `PATH` per i tool `host`, via `ocor-runtime/.venv/bin` per `repository`),
  derivato dall'artefatto ufficiale verificato. Motivazione: cambio della macchina di
  sviluppo; host `nepryoon`; acquisizione del 2026-10-01.
- Voci aggiornate (valore precedente → nuovo, tutti a **versione invariata**):
  - `node` 20.20.2: `4446eb8e…` → `62954886…` — binario ufficiale
    `node-v20.20.2-linux-x64` (archivio `df770b2a…` verificato contro `SHASUMS256.txt`
    e firma GPG valida, chiave `CC68F5A3106FF448322E48ED27F5E38D5B0A215F`
    "marco-ippolito"); il valore precedente non era riproducibile dalle sorgenti ufficiali.
  - `gh` (github-cli) 2.99.0: `be795719…` → `d0a90152…` — binario ufficiale
    `gh_2.99.0_linux_amd64` (archivio `ed496022…` verificato contro
    `gh_2.99.0_checksums.txt`).
  - `docker` 29.7.2: `d62dfea0…` → `e4538110…` — binario statico ufficiale
    `docker-29.7.2.tgz` da `download.docker.com` (Docker non pubblica un file checksum
    per il tarball statico: registrata la fonte ufficiale e il metodo di verifica
    SHA-256 del binario statico ufficiale).
- `uv` 0.12.5: **invariato** — l'`integrity` `b65f23a4…` corrisponde già al binario
  ufficiale `uv-x86_64-unknown-linux-gnu` (archivio `68a509da…` verificato contro il file
  `.sha256` ufficiale); la divergenza è solo la versione installata sulla macchina
  (0.12.21), non il lock.
- `git` 2.55.0 e `typescript` (tsc) 7.0.2: **non aggiornati** — nessun binario ufficiale
  verificabile (git) / indisponibile e dipendente da `node` (tsc). Registrata decision
  request **`TOOLCHAIN-LOCK-RESIDUAL`** (`OPEN_PO_DECISION_REQUIRED`) in
  `reports/development/decision_requests/`, secondo la clausola fail-closed della
  decisione.
- Allowlist del validator di piano estesa (non un indebolimento): aggiunto
  `reports/development/decision_requests/TOOLCHAIN-LOCK-RESIDUAL.md` a `extension_paths`
  in `scripts/validate_ocor_development_plan.py` per il nuovo file di decision request;
  il codice di verifica del lock resta invariato. Self-hash di
  `reports/planning/OCOR_PLAN_RUN_STATE.json` riallineato.
- `acquired_at` → `2026-10-01T16:38:05Z`; `architecture` invariata `x86_64`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: ri-richiedere la verifica indipendente di `OCOR-DEV-REM-0015` su un
  HEAD che include questo change set (§6), e riallineare la toolchain locale (installare
  `node` 20.20.2, `uv` 0.12.5, `gh` 2.99.0, `docker` 29.7.2 in ambiente isolato secondo
  DEC-211).

## 2026-10-01 — Governed: ri-acquisizione toolchain lock (merge PR #138, state sync)

- Change set `governed/state-sync-toolchain-lock` (docs/state), basato sull'HEAD di
  `main` = `749a88f7fb4b96aa00fc83fd1097fb12274a70f7` (merge commit di PR #138).
- La ri-acquisizione governata di `infra/toolchain.lock.json` (decisione PO
  `TOOLCHAIN-LOCK-UPDATE`) è **mergiata** con PR #138: 13 check verdi sull'HEAD esatto
  `39e8153…`; `node`/`gh`/`docker`/`uv` ri-acquisiti a **versione invariata** con digest
  verificati contro checksum ufficiali.
- Blocker `TOOLCHAIN-LOCK-UPDATE` → `RESOLVED` in `EXECUTION_STATE.json` (con
  `resolution`); `blocked_tasks` svuotato. Registrato il nuovo blocker
  **`TOOLCHAIN-LOCK-RESIDUAL`** (`OPEN_PO_DECISION_REQUIRED`) per `git` 2.55.0 e
  `typescript` 7.0.2 (non ri-acquisibili: git distribuisce solo sorgenti, tsc dipende da
  `node`), con decision request in `reports/development/decision_requests/`.
- `baseline_commit` → `749a88f…`; `latest_ci_evidence` aggiornato con i 6 run ID della
  CI di PR #138 (13 check). `active_iteration.branch` e `MODEL_HANDOFF.branch` →
  `governed/state-sync-toolchain-lock`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: ri-richiedere la verifica indipendente di `OCOR-DEV-REM-0015` su un
  HEAD che include la ri-acquisizione del toolchain lock (§6), poi R3 e `OCOR-DEV-0048`.

## 2026-10-01 — Governed: verdetto cycle-2 REM-0015 (NO_GO, residuo git 2.55.0) + state sync

- Change set `governed/state-sync-ocor-dev-rem-0015-cycle2-verdict` (docs/state), basato
  sull'HEAD di `main` = `eddd83cb0dbc284bec5ca708ae275c7d2225d27e` (merge commit PR #139).
- Processato il verdetto indipendente `OCOR-DEV-REM-0015-6790a7fe0343-2` (repair_cycle 2,
  ri-verifica dopo la ri-acquisizione del toolchain lock PR #138): **`NO_GO`** con un
  singolo finding medium **`VF-001`** — `git: executable integrity mismatch` (osservato
  2.53.0 `sha256 5516c9f3…` vs lock 2.55.0 `sha256 c1bc685b…`).
- Il verifier ha confermato che la correzione `git_changed()` (NUL-delimited path) è
  **funzionalmente corretta**: 14 test focalizzati, 154 casi indipendenti sui path
  Unicode/tab/newline/CR/quote/backslash/byte non-UTF-8, suite completa **905/905** con
  servizi live, e **8/9** voci della toolchain ora coincidono con il lock (`tsc` 7.0.2 e
  `node` 20.20.2 ri-acquisiti con checksum firmato). Resta **soltanto** `git` 2.55.0
  (nessun binario Linux ufficiale pubblicato dal progetto).
- `OCOR-DEV-REM-0015` resta **`BLOCKED`** esclusivamente su `TOOLCHAIN-LOCK-RESIDUAL`
  (`OPEN_PO_DECISION_REQUIRED`, riservata al Product Owner). Evidenza invariata
  `CANDIDATE_PENDING_INDEPENDENT_VERIFICATION`, non sigillata. Nessun workaround del
  verifier e nessun preflight convertito in `PASS`.
- `EXECUTION_STATE.json`: `baseline_commit` → `eddd83c…`; `rem_0015_escalation.verdicts`
  esteso con il cycle-2; `next_executable_action` ricalcolata. `MODEL_HANDOFF.json`
  riallineato (branch, `current_task`, `exact_next_action`).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: merge di **PR #140** (R3 step (a), `governed/remediation-r3-evidence-input-drift`,
  13/13 check verdi, `MERGEABLE`) con `--match-head-commit`; poi R3 step (b)
  (record di riqualifica) e/o implementazione `OCOR-DEV-0048`.

## 2026-10-01 — Governed: merge R3 step (a) validator (PR #140) + state sync

- Change set `governed/state-sync-r3-evidence-input-drift` (docs/state), basato sull'HEAD di
  `main` = `80fcbaa676055e34ac079539806c6093f328f187` (merge commit di PR #140).
- Merge di **PR #140** (`governed/remediation-r3-evidence-input-drift`) con
  `--match-head-commit d2b36f4…`: 13 check verdi sull'HEAD esatto; post-merge verificato
  `origin/main` == merge commit.
- R3 step (a) chiuso: nuovo validator fail-closed `scripts/validate_evidence_input_drift.py`
  + 5 test ermetici (`reports/tests/test_evidence_input_drift.py`) + RED log
  (`reports/tests/evidence/rem_evidence_input_drift/red.log`). RED verificato sull'HEAD:
  `checked_tasks=62`, `checked_inputs=165`, `drifted_inputs=51`, `drifted_tasks=32`.
- Il validator **non** è ancora cablato in CI/preflight: sarà collegato come step bloccante
  in R3 step (c), dopo che lo step (b) avrà prodotto i record di riqualifica e riportato il
  validator a GREEN.
- `EXECUTION_STATE.json`: `remediation_status.R3_evidence_input_drift` aggiunto
  (`STEP_A_MERGED`); `baseline_commit` → `80fcbaa…`; `latest_ci_evidence` aggiornato con i
  6 run ID della CI di PR #140; `next_executable_action` → R3 step (b). `MODEL_HANDOFF.json`
  riallineato (branch, `current_task`, `exact_next_action`).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: R3 step (b) — record di riqualifica per i 32 task con input di evidenza
  sigillati in deriva (rieseguire i test sullo stack reale, nuovi raw log/hash, inserimento
  chirurgico in `MANIFEST.json` con `supersedes`); `OCOR-DEV-REM-0015`/`REM-0016` restano
  `BLOCKED` su `TOOLCHAIN-LOCK-RESIDUAL` (`git` 2.55.0).

## 2026-10-01 — Governed: merge R3 step (b) part 1 requalification (PR #143) + state sync

- Change set `governed/state-sync-r3b-requalification` (docs/state), basato sull'HEAD di
  `main` = `362e1a598ce3438d44207b05b9b35dbcd08273af` (merge commit di PR #143).
- Merge di **PR #143** (`governed/remediation-r3-evidence-requalification`) con
  `--match-head-commit f0c8483…`: 13 check verdi sull'HEAD esatto; post-merge verificato
  `origin/main` == merge commit.
- R3 step (b) part 1 chiuso: 12 task G0/G1 in deriva riqualificati all'HEAD
  (`OCOR-DEV-0002..0006`, `0008..0014`) con record content-addressed nuovi
  (`*.requalified.json` + `*.requalified.log`), ognuno con campo `supersedes` esplicito al
  record originale; inserimento chirurgico nei `MANIFEST.json` di G0 e G1; i record sigillati
  originali non sono stati modificati.
- Deriva residua post-merge (validator `scripts/validate_evidence_input_drift.py`):
  `checked_inputs=165`, `checked_tasks=62`, `drifted_inputs=29`, `drifted_tasks=20`
  (da 51/165 e 32/62 al RED dello step (a)).
- `EXECUTION_STATE.json`: `remediation_status.R3_evidence_input_drift` →
  `STEP_B_IN_PROGRESS` con `requalification_part1` (12 requalificati / 20 residui);
  `baseline_commit` → `362e1a5…`; `latest_ci_evidence` aggiornato con i 6 run ID della CI di
  PR #143; `next_executable_action` → R3 step (b) part 2. `MODEL_HANDOFF.json` riallineato
  (branch, worktree, `current_task`, `exact_next_action`).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: R3 step (b) part 2 — record di riqualifica per i 20 task residui
  (`OCOR-DEV-0007`, `0015`, `0019`, `0020`, `0022`, `0023`, `0032`, `0037`, `0038`,
  `0070..0079`, `0081`); poi R3 step (c) — cablare il validator come step CI bloccante.
  `OCOR-DEV-REM-0015`/`REM-0016` restano `BLOCKED` su `TOOLCHAIN-LOCK-RESIDUAL` (`git` 2.55.0).

## 2026-10-01 — Governed: merge R3 step (b) part 2 requalification (PR #145) + state sync

- Change set `governed/state-sync-r3b-part2-requalification` (docs/state), basato sull'HEAD di
  `main` = `168665f8fc5942086f6390896c8ab3e76a927772` (merge commit di PR #145).
- Merge di **PR #145** (`governed/remediation-r3b-part2-evidence-requalification`) con
  `--match-head-commit fb18866…`: 13 check verdi sull'HEAD esatto; post-merge verificato
  `origin/main` == merge commit `168665f…`.
- R3 step (b) part 2 chiuso: 20 task G1/G2/G4 in deriva riqualificati all'HEAD
  (`OCOR-DEV-0007`, `0015`, `0019`, `0020`, `0022`, `0023`, `0032`, `0037`, `0038`,
  `0070..0079`, `0081`) con record content-addressed nuovi (`*.requalified.json` +
  `*.requalified.log`), ognuno con campo `supersedes` esplicito al record originale;
  inserimento chirurgico nei `MANIFEST.json` di G1, G2 e G4; i record sigillati originali
  non sono stati modificati. Allowlist del plan-validator estesa per i 40 nuovi path e
  self-hash di planning riallineato.
- Deriva post-merge (validator `scripts/validate_evidence_input_drift.py`): GREEN —
  `checked_inputs=165`, `checked_tasks=62`, `drifted_inputs=0`, `drifted_tasks=0`
  (da 29/165 e 20/62 dopo lo step (b) part 1, e 51/165 e 32/62 al RED dello step (a)).
- `EXECUTION_STATE.json`: `remediation_status.R3_evidence_input_drift` → `STEP_B_MERGED`
  con `requalification_part2` (20 requalificati / 0 residui) e `next_step=STEP_C_WIRE_VALIDATOR`;
  `baseline_commit` → `168665f…`; `latest_ci_evidence` aggiornato con i 6 run ID della CI di
  PR #145; `next_executable_action` → R3 step (c). `MODEL_HANDOFF.json` riallineato
  (branch, worktree, `current_task`, `exact_next_action`).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: R3 step (c) — cablare `scripts/validate_evidence_input_drift.py` come
  step CI bloccante e nel preflight (fail-closed). `OCOR-DEV-REM-0015`/`REM-0016` restano
  `BLOCKED` su `TOOLCHAIN-LOCK-RESIDUAL` (`git` 2.55.0).

## 2026-10-01 — Governed: state sync after git toolchain-lock resolution (PR #147)

- Change set `governed/state-sync-toolchain-lock-residual-git` (docs/state), basato sull'HEAD di
  `main` = `e74afa6f1cbd714d9fc5c8e45272cfc7773d869c` (merge commit di PR #147).
- La parte `git` di `TOOLCHAIN-LOCK-RESIDUAL` è **risolta**: PR #147
  (`governed/toolchain-lock-residual-git`) ha aggiornato la voce `git` di
  `infra/toolchain.lock.json` da `2.55.0` (digest `c1bc685b…`) a `2.53.0` (pacchetto Ubuntu
  ufficiale, binario installato `/usr/bin/git`, digest `5516c9f3…`), con provenienza verificata
  (`apt-cache policy git`, `dpkg -s git`) e controlli di verifica del lock invariati. I task
  `OCOR-DEV-0070/0071/0072` (unici la cui evidenza riferisce quel lock) riqualificati con record
  `*.requalified2.*` e `supersedes` espliciti; validator di deriva GREEN.
- `TOOLCHAIN-LOCK-RESIDUAL` in `EXECUTION_STATE.json` → `RESOLVED` (parte git); la parte
  `typescript`/`node` resta aperta e viene trasferita alla nuova decision request
  `TOOLCHAIN-LOCK-TYPESCRIPT` (`OPEN_PO_DECISION_REQUIRED`, **non bloccante**: il verifier
  acquisisce `node` 20.20.2 e `tsc` 7.0.2 in isolamento).
- `baseline_commit` → `e74afa6…`; `latest_ci_evidence` aggiornato con i 6 run ID della CI di
  PR #147 (13 check verdi sull'HEAD esatto `5f7ea44…`); `next_executable_action` → ri-verifica
  indipendente di `OCOR-DEV-REM-0015` su un HEAD con il fix git, poi implementazione
  `OCOR-DEV-REM-0016`, poi R3 step (c).
- `MODEL_HANDOFF.json` riallineato (branch, worktree, `current_task`, `exact_next_action`,
  `unresolved_blockers` = [`TOOLCHAIN-LOCK-TYPESCRIPT`]).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: ri-richiedere la verifica indipendente di `OCOR-DEV-REM-0015` su un HEAD che
  include il fix git (PR #147); poi implementare `OCOR-DEV-REM-0016` (record content-addressed);
  poi R3 step (c) — cablare `scripts/validate_evidence_input_drift.py` come step CI bloccante.

## 2026-10-01 — Governed: OCOR-DEV-REM-0015 merged (PR #149) + state sync

- Change set `governed/state-sync-ocor-dev-rem-0015` (docs/state), basato sull'HEAD di `main` =
  `54ec7d13d7e954b4264efdb2d4965b6f8957b2a7` (merge commit di PR #149).
- Merge di **PR #149** (`governed/remediation-rem0015-rccad-nul-paths`) con `--match-head-commit
  0f98a5d0f29801e0a2c7aabe1f0dbbe999d5447d`: 13 check verdi sull'HEAD esatto; post-merge verificato
  `origin/main` == merge commit `54ec7d13…`.
- `OCOR-DEV-REM-0015` (finding VF-002, `scripts/validate_rccad.py` gestione path NUL-delimited di
  `git diff`) implementato con TDD, ri-verificato `GO_FOR_EVIDENCE_SEAL` al ciclo 3 (dopo il fix git
  del lock, PR #147), sigillato content-addressed e mergiato: record `f165975a…`, raw log `3d59fbee…`.
- `EXECUTION_STATE.json`: `remediation_status.R2_independent_verification.rems_completed` include
  `OCOR-DEV-REM-0015`; `rem_0015_escalation.status` → `RESOLVED_SEALED_AND_MERGED` con verdetto
  ciclo-3 `GO_FOR_EVIDENCE_SEAL`; `baseline_commit` → `54ec7d13…`; `latest_ci_evidence` aggiornato
  con i 6 run ID della CI di PR #149; `next_executable_action` → implementazione `OCOR-DEV-REM-0016`.
- `MODEL_HANDOFF.json` riallineato (branch, worktree, `current_task`, `exact_next_action`;
  `completed_tasks` e `commands_run` aggiornati; `unresolved_blockers` = [`TOOLCHAIN-LOCK-TYPESCRIPT`]).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: implementare `OCOR-DEV-REM-0016` (record content-addressed per
  REM-0010/0011/0012); poi R3 step (c) — cablare `scripts/validate_evidence_input_drift.py` come
  step CI bloccante; poi `OCOR-DEV-0048` (fase di implementazione).

## 2026-10-02 — Governed: OCOR-DEV-REM-0016 merged (PR #151) + state sync

- Change set `governed/state-sync-ocor-dev-rem-0016` (docs/state), basato sull'HEAD di `main` =
  `5e1e601431a2ecab15869cdfb4775a39c145cc4f` (merge commit di PR #151).
- Merge di **PR #151** (`governed/remediation-rem0016-content-addressed`) con `--match-head-commit
  8174019fe803b24f0fc00dc8a7efe8a727a1a87c`: 13 check verdi sull'HEAD esatto; post-merge verificato
  `origin/main` == merge commit `5e1e6014…`; hash sigillati del record invariati.
- `OCOR-DEV-REM-0016` (finding VF-003, record content-addressed per REM-0010/0011/0012) implementato
  con TDD, ri-verificato `GO_FOR_EVIDENCE_SEAL` al ciclo 2 (ciclo-1 NO_GO VF-001/VF-002 risolti),
  sigillato content-addressed e mergiato: record `0d4fcfea…`, raw log `b0d7876c…`.
- `EXECUTION_STATE.json`: `remediation_status.R2_independent_verification.rems_completed` include
  `OCOR-DEV-REM-0016`; `baseline_commit` → `5e1e6014…`; `latest_ci_evidence` aggiornato con i 6 run
  ID della CI di PR #151; `next_executable_action` → R3 step (c).
- `MODEL_HANDOFF.json` riallineato (branch, worktree, `current_task`, `exact_next_action`;
  `completed_tasks` e `commands_run` aggiornati; `unresolved_blockers` = [`TOOLCHAIN-LOCK-TYPESCRIPT`]).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: R3 step (c) — cablare `scripts/validate_evidence_input_drift.py` come step CI
  bloccante e nel preflight (aggiornare le allowlist dei validator di piano per i nuovi file e
  riallineare il self-hash di `OCOR_PLAN_RUN_STATE.json`); poi `OCOR-DEV-0048` (fase di implementazione).

## 2026-10-02 — Governed: R3 step (c) merged (PR #153) + state sync

- Change set `governed/state-sync-r3c-wire-drift-validator` (docs/state), basato sull'HEAD di `main` =
  `7d833606756203f28c50913871f6ae6d66c790ee` (merge commit di PR #153).
- Merge di **PR #153** (`governed/remediation-r3c-wire-drift-validator`) con `--match-head-commit
  af61453cfae010dd8b68c82692cb42fbc3e9e678`: 13 check verdi sull'HEAD esatto; post-merge verificato
  `origin/main` == merge commit `7d833606…`.
- R3 step (c) chiuso: `scripts/validate_evidence_input_drift.py` cablato come step CI bloccante
  (`.github/workflows/ocor-tooling-bootstrap.yml`: job `type-and-lint-gate` esegue la suite di regressione
  `reports/tests/test_evidence_input_drift.py`; job `tooling-policy` esegue il validator contro HEAD
  `scripts/validate_evidence_input_drift.py --root .`) e come step di preflight (`AGENTS.md`). Nessun nuovo
  file: allowlist dei validator di piano e self-hash di `OCOR_PLAN_RUN_STATE.json` non richiedono
  riallineamento. Validator GREEN all'HEAD: `checked_inputs=165`, `checked_tasks=62`,
  `drifted_inputs=0`, `drifted_tasks=0`.
- `EXECUTION_STATE.json`: `remediation_status.R3_evidence_input_drift` → `COMPLETE` (step (a), (b), (c)
  tutti chiusi) con `pr_step_c=153` e `merge_commit_step_c=7d833606…`; `baseline_commit` → `7d833606…`;
  `latest_ci_evidence` aggiornato con i 6 run ID della CI di PR #153; `next_executable_action` →
  `OCOR-DEV-0048` (fase di implementazione). `MODEL_HANDOFF.json` riallineato (branch, worktree,
  `current_task`, `exact_next_action`).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: `OCOR-DEV-0048` (fase di implementazione) — task a backend reale (OPA, Keycloak,
  SPIFFE/SPIRE, OpenBao, mTLS); leggere per intero lo spike `OCOR-DEV-0021` e i port riusati, poi TDD
  RED→GREEN→REFACTOR con criteri eseguibili prima del codice. `RVW-03`/`INFO-A`/`INFO-C` e
  `TOOLCHAIN-LOCK-TYPESCRIPT` restano riservati al Product Owner (non bloccanti).

## 2026-10-02 — Governed: OCOR-DEV-0048 escalation (repair budget exhausted) + state sync

- Change set `governed/state-sync-ocor-dev-0048-escalation` (docs/state), basato sull'HEAD di `main` =
  `5e2a0909e842fa0cc550a5b6b2da23ad42b8fa63` (merge commit di PR #155, `governed/ocor-dev-0048-conditional-backend-guard`,
  che registra `test_ocor_dev_0048.py` come guard infrastrutturale condizionale).
- **Escalation di `OCOR-DEV-0048`** ai sensi di RCCAD §8 (harness): il task a backend reale (OPA, Keycloak,
  SPIFFE/SPIRE, OpenBao, mTLS) ha esaurito il budget di 2 cicli di riparazione materialmente diversi. Tre verdetti
  indipendenti `NO_GO`:
  - ciclo 0 `OCOR-DEV-0048-587e4a8485c4-0` (head `587e4a84…`): 8 finding (`VF-001`…`VF-008`);
  - ciclo 1 `OCOR-DEV-0048-de9e7cd429f6-1` (head `de9e7cd4…`): 7 finding (`VF-001`…`VF-007`);
  - ciclo 2 `OCOR-DEV-0048-eda08db30ca2-2` (head `eda08db3…`): 2 finding bloccanti `high`.
- Finding finali (ciclo 2): `VF-001` — bypass della finestra temporale via offset timezone (serializzazione firmata
  `strftime` con `Z` senza conversione UTC mentre i guard confrontano istanti offset-aware; `DELEGATION_EXPIRED`
  diventa `ACCEPTED` alterando solo `tzinfo`; contraddice ADD v1.3 §§5.1–5.2). `VF-002` — delega non cablata nel
  percorso Keycloak→OPA (`verify_signed_delegation` invocato da nessun provider; i 7 test di delega esercitano solo
  l'helper in isolamento; contraddice ADD v1.3 §5.2 regole 4–5 e il primo `acceptance_criteria`).
- Record di escalation: `reports/development/OCOR_DEV_0048_ESCALATION.md`. `OCOR-DEV-0048` marcato
  `BLOCKED_REPAIR_BUDGET_EXHAUSTED`; tutti i 21 task residui (`OCOR-DEV-0049`…`OCOR-DEV-0069`) bloccati
  transitivamente. Azione minima di sblocco: correggere `VF-001` (UTC canonico con identica precisione per
  firma+enforcement) e `VF-002` (cablaggio della validazione di grant/revoca nel percorso dei provider autorizzati)
  e richiedere una terza verifica indipendente — eccede il budget di 2 cicli, richiede l'autorizzazione del Product
  Owner o una disposition governata alternativa.
- `EXECUTION_STATE.json`: `baseline_commit` → `5e2a0909…`; nuovo blocker `OCOR-DEV-0048`; nuova sezione
  `backlog_escalations`; `current_gate` → `G4_WAVE_15_BLOCKED_OCOR_DEV_0048_ESCALATED`; `next_executable_action`
  → stato terminale `TERMINAL_BLOCKED`.
- `MODEL_HANDOFF.json` riallineato (branch, worktree, `current_task`, `exact_next_action`; `unresolved_blockers`
  = [`TOOLCHAIN-LOCK-TYPESCRIPT`, `OCOR-DEV-0048`]).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance` `NOT_ESTABLISHED`,
  `PoC`/`Production` `NO-GO`. `inputs/` invariato.
- Prossima azione: nessuna — `TERMINAL_BLOCKED` in attesa della disposition del Product Owner.

## 2026-10-02 — Governed: OCOR-DEV-0048 repair cycle 3 (PO decision OCOR-DEV-0048-REPAIR-3) + state sync

- Change set `governed/state-sync-ocor-dev-0048-repair-cycle-3`, basato sull'HEAD di `main` =
  `4452d70ecc170eefd44a328ffa897380cca0a761` (merge di PR #156, escalation state sync).
- **Decisione del Product Owner** `OCOR-DEV-0048-REPAIR-3` (2026-10-02): autorizzato UN SOLO terzo ciclo di
  riparazione per `OCOR-DEV-0048`, in deroga puntuale al budget di 2 cicli (RCCAD §8); il budget resta 2 per
  ogni altro task. Ambito esclusivamente `VF-001` e `VF-002` del verdetto `OCOR-DEV-0048-eda08db30ca2-2`.
- **Branch task**: `task/OCOR-DEV-0048-integrate-opa-keycloak-spiffe-openbao-mtls`, a partire da head
  `eda08db30ca20c722a1cc11d25e4b34d7c590227`; nessuna riscrittura di ciò che è già stato accettato. Head
  riparato: `7f2fff555621424c8c89764aba16810f038ef509` (2 commit).
- **VF-001**: istanti canonici UTC con identica precisione per firma ed enforcement; aggiunti 2 casi di
  finestra (`BUNDLE-OFFSET-EQUIVALENT-STABLE`, `BUNDLE-OFFSET-SHIFTED-REJECTED`).
- **VF-002**: `verify_signed_delegation` e stato di revoca consumati da `OpaPolicyDecisionProvider.evaluate`;
  aggiunti 7 casi sulla stessa operazione (`DELEGATED-REQUEST-{VALID-PERMIT, ABSENT-GRANT, EXPIRED, REVOKED,
  OUT-OF-SCOPE, OUT-OF-PURPOSE, ALTERED-CHAIN}`) sui backend reali, senza mock del boundary.
- Gate locali verdi: `50 passed` su `test_ocor_dev_0048.py` (stack `ocor-bootstrap` reale), `ruff check` e
  `mypy --strict` puliti, `validate_runtime_evidence.py` `PASS`, `validate_rccad.py` `PASS_LOCAL_PRECHECK`,
  `validate_language_policy.py`, `validate_ocor_change_scope.py` e `validate_evidence_input_drift.py` verdi,
  `sha256sum` normativo `PASS` (8/8).
- Richiesta di verifica indipendente: `OCOR-DEV-0048-7f2fff555621-3` (`TASK_EVIDENCE`, `repair_cycle: 3`).
- `EXECUTION_STATE.json`: `baseline_commit` → `4452d70e…`; blocker `OCOR-DEV-0048` →
  `IN_PROGRESS_REPAIR_CYCLE_3_AWAITING_VERIFICATION`; `backlog_escalations.OCOR-DEV-0048` aggiornato con la
  decisione PO e il ciclo 3; `current_gate` → `G4_WAVE_15_OCOR_DEV_0048_REPAIR_CYCLE_3_AWAITING_VERIFICATION`;
  `next_executable_action` → attesa del verdetto indipendente.
- `MODEL_HANDOFF.json` riallineato (branch, worktree, `current_task`, `exact_next_action`,
  `unresolved_blockers`, `commands_run`).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance` `NOT_ESTABLISHED`,
  `PoC`/`Production` `NO-GO`. `inputs/` invariato. L'evidenza di `OCOR-DEV-0048` resta
  `CANDIDATE_PENDING_INDEPENDENT_VERIFICATION` (non sigillata).
- Prossima azione: attendere il verdetto `OCOR-DEV-0048-7f2fff555621-3`. Con `GO_FOR_EVIDENCE_SEAL`: sigillare
  e integrare `OCOR-DEV-0048`; con `NO_GO`: nessuna ulteriore riparazione (decisione PO), escalation e
  `TERMINAL_BLOCKED`.

## 2026-10-02 — Governed: OCOR-DEV-0048 terminal (cycle-3 NO_GO, PO decision OCOR-DEV-0048-REPAIR-3) + state sync

- Change set `governed/state-sync-ocor-dev-0048-terminal-no-go`, basato sull'HEAD di `main` =
  `792842d91ae12d64756ff133f763c6ace6c7734f` (merge di PR #157, state sync del ciclo 3).
- **Verdetto indipendente (ciclo 3)** `OCOR-DEV-0048-7f2fff555621-3` = `NO_GO`, 2 finding bloccanti `high`
  diversi dai precedenti (suite completa `955 passed` sullo stack reale, backend reali healthy):
  - `VF-001` — `control_plane.py:1212`: finestra della delega rivalidata con `request.at` invece del
    tempo corrente del boundary; delega scaduta ⇒ `PERMIT` (contraddice ADD v1.3 §5.1, fail-closed/FR-128).
  - `VF-002` — `control_plane.py:1259-1261`: `valid_until` fissato a 300s limitato solo dal bundle;
    decisione delegata che sopravvive alla propria Authority (contraddice ADD v1.3 §5.1/§5.2, FR-128).
- **Decisione del Product Owner** `OCOR-DEV-0048-REPAIR-3`: nessuna ulteriore riparazione dopo `NO_GO`.
  `OCOR-DEV-0048` è terminale `BLOCKED_REPAIR_BUDGET_EXHAUSTED`; tutti i 21 task residui
  (`OCOR-DEV-0049`…`OCOR-DEV-0069`) bloccati transitivamente.
- `EXECUTION_STATE.json`: `baseline_commit` → `792842d91ae12d64756ff133f763c6ace6c7734f`; blocker
  `OCOR-DEV-0048` → `BLOCKED_REPAIR_BUDGET_EXHAUSTED`; `backlog_escalations.OCOR-DEV-0048` con verdetto
  ciclo 3 `NO_GO`, `final_findings_cycle_3` e `terminal_disposition`; `current_gate` →
  `G4_WAVE_15_OCOR_DEV_0048_TERMINAL_BLOCKED`; `next_executable_action` → chiusura di
  `TOOLCHAIN-LOCK-TYPESCRIPT` (decisione PO 2026-10-02, Opzione 1) e registrazione di
  `TERMINAL_BLOCKED_REPORT.json`.
- `MODEL_HANDOFF.json` riallineato (branch, worktree, `current_task`, `exact_next_action`,
  `unresolved_blockers` = [`OCOR-DEV-0048`, `TOOLCHAIN-LOCK-TYPESCRIPT`], `commands_run`).
- `OCOR_DEV_0048_ESCALATION.md`: aggiunto verdetto ciclo 3 `NO_GO` e stato finale `TERMINAL_BLOCKED`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato. L'evidenza di `OCOR-DEV-0048`
  resta `CANDIDATE_PENDING_INDEPENDENT_VERIFICATION` (non sigillata).
- Prossima azione: chiudere `TOOLCHAIN-LOCK-TYPESCRIPT` come risolta (decisione PO 2026-10-02, Opzione 1)
  in un change set `governed/` separato, poi `TERMINAL_BLOCKED_REPORT.json` e `TERMINAL_BLOCKED`.

## 2026-10-02 — Governed: chiusura decision request TOOLCHAIN-LOCK-TYPESCRIPT (Opzione 1) + state sync

- Change set `governed/state-sync-toolchain-lock-typescript-resolved`, basato sull'HEAD di `main` =
  `f0f88d906e2c7cc5a57ec1c0c1bd616f63982e18` (merge di PR #158, terminal state sync di OCOR-DEV-0048).
- **Decisione del Product Owner** `TOOLCHAIN-LOCK-TYPESCRIPT` (2026-10-02), **Opzione 1**: nessuna
  variazione di `infra/toolchain.lock.json`; `node` 20.20.2 e `typescript@7.0.2` (`bin/tsc`) usati in
  ambiente isolato (DEC-211) per i gate locali dell'implementatore; il lock e i suoi controlli di
  validazione/verifica restano invariati.
- `reports/development/decision_requests/TOOLCHAIN-LOCK-TYPESCRIPT.md` chiusa come `RESOLVED`, con
  sezione di risoluzione che cita la decisione PO (Opzione 1, nessuna variazione del lock).
- `EXECUTION_STATE.json`: `baseline_commit` → `f0f88d90…`; blocker `TOOLCHAIN-LOCK-TYPESCRIPT` →
  `RESOLVED` con `resolution` (Opzione 1); `active_iteration` riallineato al nuovo branch; `updated_at`;
  `next_executable_action` → registrazione/riallineamento di `TERMINAL_BLOCKED_REPORT.json` allo stato
  terminale ciclo 3 e `TERMINAL_BLOCKED`.
- `MODEL_HANDOFF.json` riallineato (branch, worktree, `current_task`, `exact_next_action`,
  `unresolved_blockers` = [`OCOR-DEV-0048`], `commands_run`).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato. Nessuna modifica a codice,
  validator o workflow: solo `reports/development/` (decision request + stato + handoff + log).
- Prossima azione: registrare/riallineare `reports/development/TERMINAL_BLOCKED_REPORT.json` allo stato
  terminale ciclo 3 (`OCOR-DEV-0048` `BLOCKED_REPAIR_BUDGET_EXHAUSTED`) in un change set `governed/`,
  poi terminare con `TERMINAL_BLOCKED`.

## 2026-10-02 — Governed: refresh TERMINAL_BLOCKED_REPORT.json to cycle-3 terminal state + final state sync

- Change set `governed/state-sync-terminal-blocked-report-cycle3`, basato sull'HEAD di `main` =
  `7cac163e960cb86a3a780b42b65a96d518453791` (merge di PR #159, chiusura `TOOLCHAIN-LOCK-TYPESCRIPT`).
- `reports/development/TERMINAL_BLOCKED_REPORT.json` riallineato allo stato terminale ciclo 3:
  `baseline_commit` → `7cac163e96…`; `independent_verifier.identity` →
  `OCOR-DEV-0048-7f2fff555621-3` (verdetto `NO_GO`, 2 finding `high`); `blocking_tasks[0].reason`
  aggiornato ai finding del ciclo 3 (`VF-001` finestra della delega rivalidata con `request.at`
  invece del tempo corrente del boundary; `VF-002` `valid_until` non limitato dalla scadenza della
  delega); `supersedes` → report ciclo 2; `recorded_at` e
  `local_controls.remote_ci_on_last_integrated_change` aggiornati (PR #159).
  `terminal_state` resta `BLOCKED`; `claims` invariato (`E1=0`, `E2=0`,
  `runtime_conformance` `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`).
- `EXECUTION_STATE.json`: `baseline_commit` → `7cac163e96…`; `active_iteration` → nuovo branch;
  `latest_ci_evidence` → PR #159 (6 run verde, head `c94c072e…`, merge `7cac163e…`);
  `current_gate` → `TERMINAL_BLOCKED_REPORT_CYCLE3`; `next_executable_action` → `TERMINAL_BLOCKED`
  (nessun lavoro eseguibile residuo); `updated_at`.
- `MODEL_HANDOFF.json` riallineato (branch, worktree, `current_task`, `exact_next_action`,
  `unresolved_blockers` = [`OCOR-DEV-0048`], `completed_tasks`, `commands_run`).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`. `inputs/` invariato. Nessuna modifica a codice,
  validator o workflow: solo `reports/development/` (report terminale + stato + handoff + log).
- Prossima azione: nessuna — il ciclo termina con `TERMINAL_BLOCKED`. Tutto il residuo
  (`OCOR-DEV-0049`…`OCOR-DEV-0069`) è bloccato transitivamente su `OCOR-DEV-0048`
  (`BLOCKED_REPAIR_BUDGET_EXHAUSTED`); le decisioni PO non bloccanti `RVW-03`/`INFO-A`/`INFO-C`
  restano aperte.

## 2026-10-04 — OCOR-DEV-0048: quarto ciclo Codex, sola implementazione candidata

- Decisione PO `OCOR-DEV-0048-REPAIR-4-CODEX` (2026-10-03): un solo quarto ciclo; supersede il divieto terminale precedente esclusivamente per questa riparazione. HEAD iniziale `7f2fff555621424c8c89764aba16810f038ef509`, baseline main `366a66d40a2b98c2df8f4c5d51ebcbbcb4c8e8fa`. Nessuna riscrittura della storia.
- Branch task `task/OCOR-DEV-0048-integrate-opa-keycloak-spiffe-openbao-mtls`, worktree `.ocor/worktrees/ocor-dev-0048`, HEAD candidato `c6cbcd3282161aafd404e73bec49acffb1ffb011`, source/test commit `5571086b3e0e3dc9ad128fd13682db4bc1f2455f`. Solo cinque percorsi del task. Stato/handoff/escalation su `governed/state-sync-ocor-dev-0048-repair-cycle-4` in worktree separato; nessun merge, nessuna PR, nessun altro task.
- VF-001: rivalidazione corrente della delega e del Principal prima/dopo I/O; timestamp richiesta/parametro legacy non forniscono il clock. VF-002: `valid_until` limitato alla scadenza canonica UTC della delega.
- Classe temporale: finestre bundle, token Keycloak, Principal, SVID e catene locale/peer verificate; intersezione delle autorità per ogni validità emessa. OpenBao emette al tempo del boundary e limita il lease a token/SVID/deletion time verificati. Port sigillati e lock invariati.
- RED finale `23 failed / 3 passed` sulla base autorizzata con i nuovi test identici; GREEN `76 passed` sul task (26 nuovi casi), `981 passed` nella suite runtime completa con PostgreSQL reale, `82 passed` nei test reports CI. Zero skip qualificanti, nessun mock del boundary. Ritardi su risposte di backend reali; client Keycloak ed entry SPIRE temporanei rimossi nei finally.
- Preflight: toolchain conforme per versione/digest, 11 servizi READY. CA disposable SPIRE scaduta rinnovata per due giorni con medesima chiave locale; ricreati solo SPIRE server/agent OCOR e riavviato Fuseki. Nessun lock/config tracciato modificato, nessuna risorsa non OCOR toccata.
- Gate locali obbligatori verdi: ruff repo, mypy strict, RCCAD, language policy, task scope, runtime evidence non-skipped, drift (62 task/165 input/zero deriva), digest normativi 8/8, harness 14 PASS. Piano validato all'HEAD committato senza delta di planning, scope task verificato separatamente contro origin/main e base autorizzata; Markdown/Mermaid esterni opzionali `NOT_EXECUTED`, fallback deterministici eseguiti. Output generati non pertinenti ripristinati.
- Primo run completo non qualificante: DSN configurato sulla porta errata 5432, invece della pubblicazione OCOR 55433; 4 fallimenti e 51 setup error. Corretto solo il DSN e rieseguita integralmente la suite. Il tentativo fallito è conservato nel raw candidato; nessun test/gate indebolito.
- Implementatore della riparazione e verifier usano **lo stesso modello in contesti separati**; nessuna diversità di modello dichiarata. Identificatore esatto/effort `NOT_EXPOSED_BY_RUNTIME`. Verifier esterno non avviato e nessun verdetto scritto.
- Richiesta `OCOR-DEV-0048-c6cbcd328216-4`, `repair_cycle: 4`, `TASK_EVIDENCE`; raw candidato `8945eb1c9031066c8e384bd6fccc00dd72c744f6aa21c31aa570903d91f82aed`. Evidenza `CANDIDATE_PENDING_INDEPENDENT_VERIFICATION`, non sigillata.
- Source di verità dei completati invariata (62 task); 0048 in attesa di verifica, downstream non avanzato. `E1=0`, `E2=0`, zero `Verified`, runtime conformance `NOT_ESTABLISHED`, PoC/Production `NO-GO`; `inputs/` invariato.
- Prossima azione: Attendere esclusivamente il verifier esterno per OCOR-DEV-0048-c6cbcd328216-4, head c6cbcd3282161aafd404e73bec49acffb1ffb011. Nessuna verifica indipendente avviata dall'implementatore. Con GO_FOR_EVIDENCE_SEAL: futura sessione di integrazione; con NO_GO: TERMINAL_BLOCKED senza quinta riparazione, decisione OCOR-DEV-0048-REPAIR-4-CODEX.

## 2026-10-04 — OCOR-DEV-0048: verifier esterno VERIFIER_ERROR, richiesta ripetuta una volta (§6)

- Il verifier indipendente per `OCOR-DEV-0048-c6cbcd328216-4` (head `c6cbcd3282161aafd404e73bec49acffb1ffb011`, `repair_cycle: 4`, `TASK_EVIDENCE`) non ha prodotto un verdetto valido dopo 3 tentativi: `codex exec` è uscito con `rc=1` per un flag di moderazione del modello ("possible cybersecurity risk") sul contenuto di verifica avversariale dei backend di sicurezza (mTLS/SPIFFE/OpenBao). Il verdetto registrato è `VERIFIER_ERROR` (`~/.ocor-codex/verdicts/OCOR-DEV-0048-c6cbcd328216-4.json`).
- Per OCOR-RCCAD §6 (`VERIFIER_ERROR`: ripetere la richiesta una volta) la richiesta di verifica è stata riemessa identica (stesso `head_sha`, `repair_cycle: 4`, `request_id`). Rimossa la worktree residua del verifier in `/tmp/ocor-verify-OCOR-DEV-0048-c6cbcd328216-4/wt` per consentire un retry pulito.
- Nessuna modifica al codice, ai test, ai gate o all'evidenza candidata; nessun PR/merge. Il candidato resta `CANDIDATE_PENDING_INDEPENDENT_VERIFICATION` (non sigillato). La disclosure same-model-in-separate-contexts è già nella richiesta.
- Prossima azione: rieseguire il verifier a contesto pulito. Con `GO_FOR_EVIDENCE_SEAL`: integrazione in una sessione successiva; con `NO_GO` o nuovo `VERIFIER_ERROR`: `TERMINAL_BLOCKED` senza quinta riparazione (decisione `OCOR-DEV-0048-REPAIR-4-CODEX`).
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance` `NOT_ESTABLISHED`, PoC/Production `NO-GO`; `inputs/` invariato.

## 2026-10-04 — OCOR-DEV-0048: verdetto ciclo 4 NO_GO → TERMINAL_BLOCKED (decisione OCOR-DEV-0048-REPAIR-4-CODEX)

- Il verifier indipendente ha prodotto il verdetto `OCOR-DEV-0048-c6cbcd328216-4` (head
  `c6cbcd3282161aafd404e73bec49acffb1ffb011`, `repair_cycle: 4`, `TASK_EVIDENCE`): `NO_GO` con 2
  finding bloccanti `high`, diversi dai precedenti.
  - `VF-001` (`security/control_plane.py:654`): `SignedDelegation` firma solo delegator/delegatee,
    `resource_scopes`, `purpose` e finestra; non firma `tenant_id`/`domains`/`compartments` richiesti
    da ADD v1.3 §5.2 (rr. 3169–3190). Le quattro varianti di scope cambiano il GCS ricalcolando il
    digest, ma la stessa firma è accettata e produce `PERMIT` in tutti i casi; il controllo di policy
    non applica i limiti che il grant omette.
  - `VF-002` (`security/control_plane.py:1243`): `evaluate` verifica lista/digest dei moduli OPA prima
    del POST e rivalida solo le finestre temporali (rr. 1330–1343); un proxy mTLS trasparente inietta
    un modulo non firmato prima del POST reale, OPA restituisce `true` e il provider emette `PERMIT`
    con il vecchio digest firmato anziché `STALE_BUNDLE` (viola «stale bundle fails closed» e il
    version fence di ADD §5.1).
- Per la decisione PO `OCOR-DEV-0048-REPAIR-4-CODEX` (2026-10-03): nessuna quinta riparazione,
  `TERMINAL_BLOCKED`. Il verifier indica per una futura candidatura sotto nuovo mandato: rappresentare
  e verificare i vincoli firmati del `DelegationGrant` (tenant, domini, compartimenti,
  capability/effect/risk ceiling, binding a policy/workload) rifiutando grant incompleti; legare
  atomicamente valutazione OPA e `PolicyDecision` allo snapshot/revisione verificato del bundle.
- Stato: `OCOR-DEV-0048` `BLOCKED_REPAIR_BUDGET_EXHAUSTED` terminale; downstream
  `OCOR-DEV-0049`…`OCOR-DEV-0069` transitivamente bloccato. Evidenza
  `CANDIDATE_PENDING_INDEPENDENT_VERIFICATION` (non sigillata).
- `EXECUTION_STATE.json`, `MODEL_HANDOFF.json` riallineati (ciclo 4 `NO_GO`, terminal disposition);
  `TERMINAL_BLOCKED_REPORT.json` riallineato allo stato terminale ciclo 4.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`; `inputs/` invariato. Nessuna modifica a codice,
  validator o workflow: solo `reports/development/` (report terminale + stato + handoff + log).
- Prossima azione: nessuna — il ciclo termina con `TERMINAL_BLOCKED`. Tutto il residuo
  (`OCOR-DEV-0049`…`OCOR-DEV-0069`) è bloccato transitivamente su `OCOR-DEV-0048`
  (`BLOCKED_REPAIR_BUDGET_EXHAUSTED`); le decisioni PO non bloccanti `RVW-03`/`INFO-A`/`INFO-C`
  restano aperte.


## 2026-10-04 — OCOR-DEV-0048: verdetto ciclo 5 NO_GO → TERMINAL_BLOCKED (decisione OCOR-DEV-0048-REPAIR-5-CLAUDE)

- Il verifier indipendente ha prodotto il verdetto `OCOR-DEV-0048-4d9a0644cdd1-5` (head
  `4d9a0644cdd1553ae899409f76e7839bd03e26b8`, `repair_cycle: 5`, `TASK_EVIDENCE`): `NO_GO` con 2
  finding bloccanti, uno `high` e uno `medium`.
  - `VF-001` (`high`, `security/control_plane.py:1802`): `KeycloakIdentityProvider` include il claim
    `act` firmato nella `principal.actor_chain`; nel ramo `delegation=None` `evaluate` controlla
    soltanto un subset insiemistico e salta `_verify_grant_chain`. Con un token `act` realmente
    firmato da Keycloak e la delega revocata, presentando grant/capability si ottiene
    `DELEGATION_REVOKED`, ma omettendo entrambi si ottiene comunque `PERMIT`. Il claim autentica gli
    attori ma non sostituisce scope, ceilings, binding e revoca del grant.
  - `VF-002` (`medium`, `reports/evidence/G4/OCOR-DEV-0048.json:1775`): `inputs.inputs_tree` registra
    `d9d827619d9c0215f5edbd4d372b1f0b52558f84` mentre l'HEAD verificato è
    `60a73de8e47b38e94aeb0e2b8dedc689fab6eb35`; gli hash per-file, il commit sorgente, il manifest e i
    24 raw log coincidono, ma il digest tree registrato è errato.
- Per la decisione PO `OCOR-DEV-0048-REPAIR-5-CLAUDE` (2026-10-04): nessuna sesta riparazione senza
  nuova decisione, `TERMINAL_BLOCKED`. Implementatore della riparazione Claude Code (Anthropic),
  verifier Codex (OpenAI): modelli di fornitori diversi in processi separati.
- Stato: `OCOR-DEV-0048` `BLOCKED_REPAIR_BUDGET_EXHAUSTED` terminale; downstream
  `OCOR-DEV-0049`…`OCOR-DEV-0069` transitivamente bloccato. Evidenza
  `CANDIDATE_PENDING_INDEPENDENT_VERIFICATION` (non sigillata).
- `EXECUTION_STATE.json`, `MODEL_HANDOFF.json` riallineati (ciclo 5 `NO_GO`, terminal disposition);
  `TERMINAL_BLOCKED_REPORT.json` riallineato allo stato terminale ciclo 5.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`; `inputs/` invariato. Nessuna modifica a codice,
  validator o workflow: solo `reports/development/` (report terminale + stato + handoff + log).
- Prossima azione: nessuna — il ciclo termina con `TERMINAL_BLOCKED`. Tutto il residuo
  (`OCOR-DEV-0049`…`OCOR-DEV-0069`) è bloccato transitivamente su `OCOR-DEV-0048`
  (`BLOCKED_REPAIR_BUDGET_EXHAUSTED`); le decisioni PO non bloccanti `RVW-03`/`INFO-A`/`INFO-C`
  restano aperte.

## 2026-10-05 — OCOR-DEV-0048: ciclo 7 GO_FOR_EVIDENCE_SEAL → evidenza sigillata e mergiata (decisione OCOR-DEV-0048-REPAIR-CLAUDE-AUTO)

- La decisione PO `OCOR-DEV-0048-REPAIR-CLAUDE-AUTO` (2026-10-04) supersede il divieto terminale
  del ciclo 5 autorizzando fino a TRE ulteriori cicli di riparazione (implementatore Claude Code
  /Anthropic, verifier Codex/OpenAI, fornitori diversi in processi separati).
- Ciclo 6: verdetto indipendente `OCOR-DEV-0048-feb83b0c3a68-6` (head `feb83b0c3a684929a09b8684e8a334cb86c77efc`)
  `NO_GO` con 1 finding `high` — `VF-001`: il ramo HTTP non-200 di `evaluate()` perde la
  correlazione della richiesta.
- Ciclo 7: corretto `VF-001` del ciclo 6 mantenendo la correlazione richiesta nel ramo OPA non-200;
  verdetto indipendente `OCOR-DEV-0048-618875eff62a-7` (head `618875eff62a43c524180596f680cafb0b4a1d02`)
  `GO_FOR_EVIDENCE_SEAL` con 0 finding. I 196 casi real-backend restano qualificanti (nessun mock
  del boundary).
- Evidenza G4 sigillata (`status: SEALED`, `result: PASS`, `repair_cycle: 7`) e mergiata in
  PR #163 con 13 check verdi sull'HEAD esatto `61b7dcdb190426aefb6212e62a7408613d3ca506`
  (merge `45e4a6f66209af3136d79980c00c41d79fb9ae8a`).
- PR #164 mergiata in precedenza: scope della campagna runtime di `validation-closure` escluso il
  guard `SPIRE conditional-infrastructure` (nessun indebolimento dei gate; i 196 casi real-backend
  restano eseguiti). Il controllo `validation-closure` di PR #163 e' passato SUCCESS.
- Stato: `OCOR-DEV-0048` in `completed_evidence_tasks`; downstream `OCOR-DEV-0049` e `OCOR-DEV-0050`
  pronti (hard_dependencies soddisfatte); prossima azione `OCOR-DEV-0049:implementation`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`; `inputs/` invariato. Le decisioni PO non bloccanti
  `RVW-03`/`INFO-A`/`INFO-C` restano `OPEN_PO_DECISION_REQUIRED`.
- `EXECUTION_STATE.json`, `MODEL_HANDOFF.json` riallineati (0048 sigillato e mergiato).

## 2026-10-05 — CI-0048-REAL-BACKEND: registrazione deviazione PR #164 e apertura OCOR-DEV-REM-0017

- Decisione PO `CI-0048-REAL-BACKEND` (2026-10-05): la PR #164 ha escluso
  `ocor-runtime/tests/tasks/test_ocor_dev_0048.py` dal job `validation-closure` (`--ignore`);
  accettata SOLO come misura temporanea, da non estendere ad altri file/job e da annullare con la
  remediation qui sotto.
- Registrata la deviazione PR #164 in `reports/development/METHOD_COMPLIANCE.json`
  (campo `deviations`, id `CI-0048-REAL-BACKEND`, remediation `OCOR-DEV-REM-0017`).
- Aperto il task di remediation `OCOR-DEV-REM-0017` (primo `REM-*` libero verificato con grep
  sull'intero repository): eseguire in CI lo stack `ocor-bootstrap` completo (SPIRE server/agent,
  credenziali di bootstrap, immagini digest-pinned da `infra/services.lock.json`), far girare
  `test_ocor_dev_0048.py` con zero skip e rimuovere l'`--ignore`. Record in
  `reports/assurance/OCOR-DEV-REM-0017-RCCAD/README.md` (status `OPEN`).
- Vincolo registrato: `OCOR-DEV-REM-0017` è dipendenza obbligatoria di ogni task G6
  (`OCOR-DEV-0060`…`OCOR-DEV-0066`), non blocca `OCOR-DEV-0049` né i task G5
  (`EXECUTION_STATE.json` → `blockers`, `blocked_tasks` = task G6).
- Regola permanente: vietato escludere, deselezionare o marcare test per far passare un check e
  togliere `skipped` dai conteggi; se un check fallisce per infrastruttura mancante in CI, scrivere
  una decision request e proseguire con altro lavoro pronto.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`; `inputs/` invariato. Nessuna modifica a codice di
  prodotto o workflow; nessun indebolimento di gate. Aggiornata SOLO l'allowlist dei nuovi file del
  validator di piano (`scripts/validate_ocor_development_plan.py`: +1 voce
  `reports/assurance/OCOR-DEV-REM-0017-RCCAD/README.md`, R3) con self-hash settle in
  `reports/planning/OCOR_PLAN_RUN_STATE.json` e `reports/planning/OCOR_PLANNING_VALIDATION_REPORT.md`
  (PASS 37/0/2 NOT_EXECUTED).
- Prossima azione: `OCOR-DEV-0049:implementation` (task più basso pronto; `OCOR-DEV-0050` anche
  pronto).

## 2026-10-05 — OCOR-DEV-0049: verdetto ciclo 2 NO_GO → escalation (budget ordinario esaurito)

- Il verifier indipendente ha prodotto il verdetto `OCOR-DEV-0049-7fd4f7728801-2` (head
  `7fd4f77288010b98330f74a4da455fa1b6e9e321`, `repair_cycle: 2`, `TASK_EVIDENCE`): `NO_GO` con 3
  finding bloccanti `high`, diversi dai cicli precedenti.
  - `VF-001` (`compose.profiles.yaml:1069`): ammissione non fail-closed — con scanner indisponibile
    o restore non verificato, `/admit?class=mutative|dispatch` risponde `200 ADMIT`; `Handler.do_GET`
    usa solo `denied_operation_classes`, `scanner error` e restore non verificato non entrano in
    `State.faults` (viola LLD §5.3–5.4).
  - `VF-002` (`compose.profiles.yaml:1180`): default-deny di rete non enforce — tutti i nomi dei
    servizi sono alias dello stesso relay (`0.0.0.0` per ogni porta ammessa, upstream scelto dalla
    sola porta): `GET postgresql:8181` raggiunge il vero OPA pur essendo assente da
    `isolation.allowedFlows` (viola ADD §6.1 / LLD §5.1).
  - `VF-003` (`compose.profiles.yaml:1500`): il gate GCS di restore non verifica il binding
    tenant/compartment per item — metadati autorevoli `tenant-a/c1` vs payload ripristinato
    `tenant-b/c2` producono `outcome PASSED` e `recovery_gate.gcs.pass=true` (viola LLD §5.4 e
    ADD Part II §2.13).
- Budget ordinario di 2 cicli di riparazione esaurito (decisione PO `OCOR-DEV-0049-IMPLEMENTER-CLAUDE`:
  il ciclo 2 è l'ultimo; implementatore Claude Code/Anthropic, verifier Codex/OpenAI, fornitori
  diversi in processi separati). OpenHands non ripara `OCOR-DEV-0049`: esegue escalation.
- Escalation registrata in `reports/development/OCOR_DEV_0049_ESCALATION.md`; `OCOR-DEV-0049`
  marcato `BLOCKED_REPAIR_BUDGET_EXHAUSTED`. Task bloccati transitivamente: `OCOR-DEV-0059`,
  `OCOR-DEV-0060`, `OCOR-DEV-0063`, `OCOR-DEV-0064`, `OCOR-DEV-0066`. `OCOR-DEV-0050` resta pronto
  (hard_dependencies soddisfatte, non dipende da 0049).
- Prossima azione: `OCOR-DEV-REM-0017:implementation` (decisione PO `REM-0017-PRIORITY`), poi
  `OCOR-DEV-0050`.
- Claim fence invariato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance`
  `NOT_ESTABLISHED`, `PoC`/`Production` `NO-GO`; `inputs/` invariato. L'evidenza di `OCOR-DEV-0049`
  resta `CANDIDATE_PENDING_INDEPENDENT_VERIFICATION` (non sigillata). Nessuna modifica a codice di
  runtime, test o workflow: solo `reports/development/` (stato + escalation) e l'allowlist del
  validator di piano (`scripts/validate_ocor_development_plan.py`, +1 voce
  `reports/development/OCOR_DEV_0049_ESCALATION.md`) con il relativo self-hash settle in
  `reports/planning/`.

## 2026-10-05 — OCOR-DEV-0049: NO_GO ciclo 3, passaggio autorizzato a Claude Code

- Unità: solo sincronizzazione dopo `OCOR-DEV-0049-02ac643eb3c7-3` (`02ac643eb3c770361f2f1b67eb0f4ab2bc049097`), verificato contro l’HEAD remoto. Due finding high: receipt non vincolata alla release/profilo corrente (VF-001), receipt firmata con recovery gate incoerente accettata (VF-002); un medium: race del test Helm tra backup manuale e CronJob (VF-003). Nessuna riparazione di prodotto/test e nessuna sigillatura.
- PO `OCOR-DEV-0049-REPAIR-CLAUDE-AUTO` supersede il blocco ordinario registrato dalla PR #168: ciclo 3 consumato, restano 4 e 5. Implementatore riparazione Claude Code (Anthropic), verifier Codex (OpenAI); implementatore loop Codex. Prossima azione esatta: «ciclo di riparazione Claude Code su OCOR-DEV-0049».
- Baseline `origin/main`: `25ee8e3bea7cf5e88630df06cb44a2fc35159494`; checkout principale pulita su main; worktree `.ocor/worktrees/state-sync-ocor-dev-0049-cycle3`, branch `governed/state-sync-ocor-dev-0049-cycle3`. Ready set dal backlog: 0049 e 0050; ordine speciale del PO conservato. PR #169 REM-0017 concorrente non modificata (HEAD 7562d3c48015f45a0b518fde622ca4304e9468ca, validation-closure FAILURE, run 37350619188); nessuna esclusione o gate indebolito.
- Preflight: inputs 8/8; harness 14 PASS/0 FAIL/0 NOT_EXECUTED; drift 63 task/167 input, zero deriva; toolchain 9/9 conforme per versione/digest usando copie ufficiali isolate preesistenti, lock invariati. Log esterni in `~/.ocor-codex/state-sync-0049-cycle3/`; gate successivi riportati nell’handoff.
- Decisioni RVW-03/INFO-A/INFO-C ricevute il 2026-10-05: audit/remediation e chiusure documentali demandate a unità distinte; non sono più decisioni PO pendenti. Scope esteso e priorità REM-0017 registrati, nessuna implementazione REM in questa iterazione.
- I risultati qualificanti del verifier (suite task/full e riproduttori dei finding) restano nel verdetto esterno; qui nessuna nuova qualifica runtime. Claim invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED e PoC/Production NO-GO. Arresto del loop `TERMINAL_BLOCKED` per il passaggio a Claude Code imposto dal PO; non perché 0050 sia bloccato.
- Gate finali locali: RCCAD PASS_LOCAL_PRECHECK; scope PASS; language/ruff PASS; mypy PASS su 69 file; runtime-evidence 0048 PASS; piano 37 PASS/0 FAIL/2 NOT_EXECUTED con `--base-ref origin/main` come CI; tutti i servizi READY. Tentativi iniziali falliti e motivazioni conservati in handoff/log esterni, nessun PASS attribuito loro. Suite runtime locale in questa unità: NOT_EXECUTED (solo state sync). Report di piano generati ripristinati: non appartengono al change set.
- CI PR #170, HEAD `8e48303e404a78de26f5e58b351ae505f0c9b1cd`: prima esecuzione con 7 job non acquisiti da hosted runner e mandatory-gates FAIL per risultati abandoned; unico rerun effettuato. Anche il secondo tentativo cancella validation-closure/supply-chain/type-and-lint/integration-postgresql per la stessa annotazione di GitHub; RCCAD ancora in esecuzione nell’osservazione delle 2026-10-05T20:48:36Z. Merge NON eseguito; retry esaurito nelle stesse condizioni.
- Registrata `GITHUB-HOSTED-RUNNER-AVAILABILITY` in `reports/development/decision_requests/GITHUB-HOSTED-RUNNER-AVAILABILITY.md` (condizione esterna, non nuova semantica): attendere hosted capacity, senza bypass/spesa. Solo aggiunta puntuale del nuovo record all’allowlist di piano, logica/soglie dei gate invariati, self-hash riallineato; report di piano incluso per questo aggiornamento. Lo stato sync resta WIP pubblicato su PR #170; main invariata. Passaggio a Claude Code ciclo 4 tramite loop_status TERMINAL_BLOCKED.
- Gate dopo la registrazione del blocco: piano 37 PASS/2 NOT_EXECUTED; drift 63 task/167 input senza deriva; scope 8 percorsi; RCCAD PASS_LOCAL_PRECHECK; ruff/language PASS; mypy 69 file PASS. Nuovo commit solo documentale/allowlist di piano: nessun PASS CI precedente riusato sul nuovo HEAD e nessun ulteriore rerun; eventuali check automatici restano da attendere dopo disponibilità del runner.

## 2026-10-06 — OCOR-DEV-0049: NO_GO ciclo 4, passaggio all’ultimo ciclo Claude Code

- Unità: sincronizzazione di stato/handoff/escalation dopo `OCOR-DEV-0049-aefabf91777d-4`, HEAD `aefabf91777d311b95cad0c60de0ffa61357ea19` verificato uguale al branch remoto. PR #170 ripresa senza riscrivere i commit del ciclo 3. Quattro finding: VF-001 high (override immagini Helm non vincolati ai pin); VF-002 high (detail GCS contraddittorio accettato); VF-003 medium (NaN nella finestra receipt); VF-004 medium (inventory OPA grande trasformata in digest vuoto). Nessuna riparazione o sigillatura di 0049.
- Decisione PO `OCOR-DEV-0049-REPAIR-CLAUDE-AUTO`: consumati due dei tre ulteriori cicli (3 e 4), resta ciclo 5. Implementatore riparazione Claude Code/Anthropic; verifier Codex/OpenAI; implementatore loop Codex/OpenAI. Prossima azione esatta: «ciclo di riparazione Claude Code su OCOR-DEV-0049». Con ulteriore NO_GO: escalation, nessuna altra riparazione.
- Baseline `origin/main` `25ee8e3bea7cf5e88630df06cb44a2fc35159494`, checkout principale main pulita; ready set da backlog/completed_evidence_tasks: 0049 e 0050. Ordine speciale REM-0017-PRIORITY conservato. PR #169 concorrente (REM-0017, HEAD 7562d3c48015f45a0b518fde622ca4304e9468ca) non modificata. Nessuna decisione PO pendente: RVW-03/INFO-A/INFO-C ricevute, audit/remediation e chiusura dei record da eseguire in unità separate.
- Preflight corrente: inputs 8/8; harness 14 PASS/0 FAIL/0 NOT_EXECUTED; drift 63 task/167 input, zero deriva; toolchain conforme tramite ambiente isolato preesistente; tutti gli 11 servizi READY. Log raw e SHA-256 in `~/.ocor-codex/state-sync-0049-cycle4/`. Suite runtime di questa unità NOT_EXECUTED (solo state sync), nessun esito del verifier attribuito al loop.
- CI preesistente PR #170 su c1efbfd7f348036673f9c34419f62b3edfdace78: contract SUCCESS, altri check richiesti CANCELLED con zero step; annotazione RCCAD «The job was not acquired by Runner of type hosted even after multiple attempts». Run 37372145609, 37372145614, 37372145637, 37372145661, 37372145679, 37372145719, 37372146998. Rerun precedente già esaurito; nessun nuovo retry nelle stesse condizioni. Aggiornamento dell’HEAD documentale non riusa alcun PASS storico; merge soltanto dopo tutti i 13 gate verdi.
- Inputs, candidato 0049, record sigillati, test, workflow e lock immutati. E1=0/E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. TERMINAL_BLOCKED del loop richiesto dal PO per il passaggio a Claude Code, non blocco globale del ready set.
- Gate locali dopo le scritture: RCCAD PASS_LOCAL_PRECHECK (assurance dinamica CI richiesta); scope 8 percorsi rispetto a origin/main; language/ruff PASS; mypy 69 file PASS; runtime evidence 0048 PASS; piano 37 PASS/0 FAIL/2 NOT_EXECUTED. Nessun file di planning riscritto oltre quelli già presenti nella PR #170; nessuna modifica ulteriore ai validator.
- Ripristino capacità hosted osservato il 2026-10-06T00:03:28.126548Z: tutti i 13 check richiesti SUCCESS sull’HEAD sorgente `bda5fb1294398c43f0ee37b915896e669c1745f0` della PR #170. Run 37391068857, 37391068870, 37391068871, 37391069169, 37391069581, 37391070279; raw `ci-source-green.json`, SHA-256 `a62916010830d4689c8c6522268550c0a804357a0daad89bfb6a60417e901769`. Risolto soltanto il blocco esterno GITHUB-HOSTED-RUNNER-AVAILABILITY, conservata la storia dei run cancellati. Commit finale di stato/handoff registra questo esito; un nuovo controllo dei 13 gate sull’HEAD finale è obbligatorio prima del merge, nessun riuso del PASS sorgente. Candidato 0049 invariato e ancora NO_GO; next_action resta ciclo di riparazione Claude Code su OCOR-DEV-0049.

## 2026-10-06 — OCOR-DEV-0049: riallineamento ciclo 5 e verifier fallback

Unità coerente: state sync e richiesta di verifica fallback, senza riparazioni Codex. Baseline `d33ae207105648799ac11479cca5b9eb9bf619ca`, branch `governed/state-sync-ocor-dev-0049-verifier-fallback`, worktree `.ocor/worktrees/state-sync-ocor-dev-0049-verifier-fallback`. PR #170 osservata MERGED con 13 check richiesti verdi sull’HEAD finale `1055be76acc43213f665cd2f2b4502d617267e9b`; non si riusano i risultati del precedente HEAD documentale. PR #169 concorrente invariata (validation-closure FAILURE).

Candidato ciclo 5 Claude Code: `b40aa8a6908b02d95cdf8138200f99f2e8aea8b1`, sorgente `49cd235473c2105bc54a37b47708135234246651`, digest check 83/83 PASS. Codex verifier interrotto tre volte dal filtro del fornitore: `OCOR-DEV-0049-b40aa8a6908b-5` = VERIFIER_ERROR, SHA-256 `882ee290ade051a6827b0f26776afbe3064005fe9885e2fd65b1f5e4f9b9f109`; non è una verifica conclusa. Decisione PO `OCOR-DEV-0049-VERIFIER-FALLBACK (2026-10-06)` applicata al nuovo request ID `OCOR-DEV-0049-b40aa8a6908b-5-claude-fallback-1` sullo stesso HEAD/ciclo. Riparazioni OCOR-DEV-0049: Claude Code (Anthropic); verifier fallback: Claude Code (Anthropic), stesso modello in processo e contesto separati. Implementazione originale di un altro modello. Variante esatta non attestata dal runtime; nessuna diversità di modello dichiarata. Implementatore del loop: Codex (OpenAI).

Preflight: main pulita/allineata; inputs 8/8, harness 14 PASS, deriva 0/167 su 63 task, toolchain isolata conforme ai digest del lock, servizi READY. Interrotto con SIGINT il pytest orfano della verifica: teardown concluso con zero container/reti/volumi del run. Env principale obsoleto rispetto allo stack del verifier; confronto in memoria, backup fuori Git con permessi 0600 e riallineamento al file effettivo del worktree detached. Init/fixture inizialmente FAIL, un solo retry ciascuno dopo diagnosi, entrambi PASS.

Gate documentali: rccad PASS_LOCAL_PRECHECK, scope/language/ruff PASS, mypy 69 sorgenti PASS, evidenza sigillata 0048 PASS, plan 37 PASS/0 FAIL/2 NOT_EXECUTED. Primo controllo plan fallito per cache SQLite di mypy temporanea nel worktree: spostata fuori repo, un solo retry PASS; validator invariato. CI dell’HEAD esatto obbligatoria prima del merge. Suite runtime completa e review indipendente di questa unità restano NOT_EXECUTED. Nessun test o gate indebolito; candidato e log preservati. Stato completed_evidence_tasks invariato (63); claim fence invariato. Ready set ricalcolato: 0049/0050, con ordine PO verifica 0049 → REM-0017 → 0050. Prossima azione: dopo state sync, marker di routing Claude Code e richiesta fallback; CONTINUE. Nessun avvio manuale del verifier, nessun ciclo 6 autorizzato.

## 2026-10-06 — OCOR-DEV-0049: ciclo 5 NO_GO finale, escalation e state sync PR #171

- Unità: ripresa del change set documentale della PR #171, senza riscrivere la storia. Baseline origin/main `d33ae207105648799ac11479cca5b9eb9bf619ca`; checkout principale main pulita. Verdetto `OCOR-DEV-0049-b40aa8a6908b-5` sull’HEAD remoto esatto `b40aa8a6908b02d95cdf8138200f99f2e8aea8b1`, SHA-256 `e1bc2e0662d7323ccf43bc082f13154df7baddbe22be6a6f630c264047abda1a`: NO_GO, VF-001 high BLOCKER (POST snapshot Qdrant HTTP 500 concorrente), VF-002 low ambientale (extra lint mancante). Suite task verifier 294 PASS/1 FAIL/0 skip; suite full verifier 1394 PASS/2 FAIL/0 skip. Risultati del verifier, non run del loop. Entrambi i NOT_EXECUTED del verdetto conservati.
- Implementatore riparazioni Claude Code; verifier finale Claude Code claude-opus-5-5 tramite fallback autorizzato, stesso modello in contesto/processo separati; implementazione originale di un altro modello. Implementatore loop Codex. Designazioni storiche nel candidato preservate; addendum di attribuzione nello stato/escalation.
- Cicli 3/4/5 esauriti, nessun ciclo 6; 0049 BLOCKED_REPAIR_BUDGET_EXHAUSTED. Decision request `OCOR-DEV-0049-REPAIR-BUDGET` e TERMINAL_BLOCKED_REPORT riallineato: arresto puntuale del loop, non blocco globale. Ready set dalle dipendenze: OCOR-DEV-0049, OCOR-DEV-0050; 0050 eseguibile, REM-0017 prioritario alla ripresa e dipendenza G6. PR #169 concorrente non modificata.
- Nessuna riparazione 0049, nessuna sigillatura, nessun record candidato/sigillato modificato. Solo stato/handoff/escalation/pacchetto decisione e singola voce allowlist del validator di piano con self-hash settle, logica e soglie invariate. E1=0/E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO, inputs immutati.
- Preflight inputs 8/8, harness 14 PASS, drift 63 task/167 input/0 deriva; toolchain 9/9 conforme nell’ambiente isolato. Il bootstrap iniziale è fallito perché l’env puntava alla directory SPIRE temporanea rimossa dal verifier: salvata copia locale e riallineato il solo percorso alla CA locale esistente. Esito del singolo retry e gate finali nell’handoff/log content-addressed `/home/luca/.ocor-codex/state-sync-0049-cycle5-final`. Suite runtime locale NOT_EXECUTED per questa unità solo documentale. CI precedente PR #171 ec45d5a verde non riusata sul nuovo HEAD; merge solo con tutti i 13 gate verdi esatti.
- Gate locali finali: RCCAD PASS_LOCAL_PRECHECK (dinamici CI obbligatori); language/ruff PASS; mypy 69 file PASS; evidence 0048 PASS; piano 37 PASS/0 FAIL/2 NOT_EXECUTED. Piano iniziale FAIL per cache mypy generata durante run parallelo, preservata fuori repo prima del singolo retry. Stack bootstrap retry PASS, initialize/fixtures PASS, tutti gli 11 servizi READY e teardown finale PASS. Raw log e hash in handoff. Scope definitivo ricontrollato dopo staging prima del push.
- CI PR #171: 13/13 check richiesti SUCCESS sull’HEAD sorgente `4e60e8799a5b4416ff10726d0ba6a7de88c0b32f`, run 37495921876, 37495921877, 37495921893, 37495922017, 37495922070, 37495922129; osservazione `2026-10-06T16:47:16.383004+00:00`, SHA-256 `e2795733db614d171412dba9f548159981892760bfd052726bf6ce25042c9970`. Registrati in stato/handoff/terminale; il commit finale documentale richiede di nuovo tutti i 13 check verdi esatti prima del merge. Ricalcolata chiusura transitiva completa del DAG: 0049, 0059, 0060–0069; 0050–0058 indipendenti. Nessun riuso del PASS per chiudere 0049.

## 2026-10-07 — OCOR-DEV-0049: escalation ciclo 6, loop CONTINUE

- Unità documentale: `governed/state-sync-ocor-dev-0049-cycle6`, `.ocor/worktrees/state-sync-ocor-dev-0049-cycle6`, baseline `5c57d411a7036d585d431a8030c4816831e7d40c`. Stato main fermo al ciclo 5; recuperati candidato e verdetto ciclo 6 senza modificare runtime/test/evidenza. Tutti i worktree residui osservati CLEAN; nessun lavoro scartato.
- Decisione PO OCOR-DEV-0049-REPAIR-6 ricevuta ed eseguita da Claude Code; richiesta budget precedente risolta. Verdetto `OCOR-DEV-0049-d0ac80a9d1d6-6` su HEAD remoto esatto `d0ac80a9d1d603ca19ddbb2d5291e252b3d6ae2b`, SHA-256 `934e0f032daa67c0f6abee6e379c4569c0394c5e3b0c28dce05d799c005fc18c`: NO_GO, VF-001 medium BLOCKER (ordinamento collation seal/replay), VF-002 low (positivo journal-ahead mancante). Task verifier 321 PASS, full verifier 1422 PASS, zero skip: risultati attribuiti al verifier, non run del loop; il probe bloccante prevale sulle suite verdi. NOT_EXECUTED conservati senza PASS.
- Riparazioni Claude Code; verifier Claude Code claude-opus-5-5, stesso modello in processo/contesto separati secondo fallback; implementazione originale altro modello. Implementatore loop Codex. Nessun ciclo 7, sigillatura o merge 0049. Candidato d0ac80a preservato.
- Disposizione corrente CONTINUE, supera TERMINAL_BLOCKED storico: REM-0017 prioritario, poi 0050; 63 completed invariati. Ready set ricalcolato dal backlog: 0049/0050; eseguibile 0050. Chiusura transitiva bloccata 0049/0059/0060–0069. PR #169 aperta su 7562d3c, validation-closure FAILURE run 37350619188, preservata. Nessuna nuova decision request: quella del ciclo 5 risolta; nessuna richiesta implicita di ciclo 7.
- Preflight e gate correnti nei raw log content-addressed `/home/luca/.ocor-codex/state-sync-0049-cycle6` e MODEL_HANDOFF; suite runtime locale NOT_EXECUTED per unità solo documentale. Merge state sync esclusivamente dopo i check richiesti verdi sull’HEAD esatto. Inputs/E1/E2/Verified/claim fence invariati.
- Gate locali finali: inputs 8/8, harness 14/14, drift 0/167 su 63 task, toolchain 9/9, servizi 11 READY, teardown PASS; RCCAD/static, language, ruff, mypy 69 file, evidence 0048 PASS; piano 37 PASS/0 FAIL/2 NOT_EXECUTED opzionali. Primo mypy FAIL perché bootstrap rimuove extra lint: ripristinati test/lint, singolo retry PASS. Nessun file di prodotto, test, workflow o validator modificato.
- CI PR #172: 13/13 check richiesti SUCCESS sull’HEAD sorgente `fb4376ef4e7d233ae1e6528451acf4b2ae825bfd`; run 37560675911, 37560675919, 37560675932, 37560675942, 37560675945, 37560675971, osservazione `2026-10-07T02:19:09.616673+00:00`, SHA-256 `5b4a817d8716f3fb9a904e2e8d4ec84b21f844f9c01fbcdee2a310cdce62c74d`. Il commit finale documentale richiede nuovamente 13 SUCCESS esatti prima del merge. Candidato 0049: 12/12 input/tree e hash raw PASS meccanico, NO_GO invariato. Read-only REM-0017: run 37350619188 fallita allo step bootstrap SPIRE; raw `--log-failed` vuoto, nessuna causa tecnica presunta.


## 2026-10-07 — OCOR-DEV-0049: ciclo 7 Codex autorizzato, stabilità in corso

- Ripresa da origin/main 33821f315138b90bdae7f940e5327b15f9a19948 e HEAD remoto task d0ac80a9d1d603ca19ddbb2d5291e252b3d6ae2b, entrambi verificati; task worktree CLEAN prima delle modifiche. REM-0017 PR #169 efce339 WIP in attesa del candidato stabile, preservato; nessun processo di riparazione concorrente sullo scope.
- Decisione PO OCOR-DEV-0049-REPAIR-7: implementatore Codex/OpenAI, verifier Claude Code/Anthropic in processo/contesto separati. Riparazioni storiche cicli 2–6 Claude Code, ciclo 7 Codex; nessun ciclo 8. REM-0017 non interrotto: riapertura 0049 ammessa dall’attesa del candidato esterno.
- Unica funzione ordered_deletion_journal al sigillo/replay, capture COLLATE C. Nuovi positivi/negativi unitari e real-backend con due tombstone alla stessa epoch e ID a collation divergente; positivo journal 9/metadata 7 sigillato/restored. Test Helm attende il diniego RESTORE_UNTESTED invece del sleep fisso: NOT_YET_SCANNED non basta e ogni 200/Ready durante l’attesa fallisce.
- RED deterministico: 4 FAIL, 0 error/skip (2 helper assente, 2 checkpoint firmato con last_event_id errato); GREEN mirato 4 PASS, zero skip. Primo tentativo RED live aveva 8 error di fixture per selezione incompleta e parsing di log Compose inadatto: preservato come tentativo non qualificante, corretto soltanto il test nuovo prima di riacquisire il RED pertinente. Nessun test/gate ridotto nelle suite qualificanti.
- Preflight: inputs 8/8, harness 14 PASS, drift 63 task/167 input/0 deriva, toolchain 9/9; ruff/mypy strict 69 file PASS. Bootstrap locale FAIL: ID Fuseki diverso dal lock già registrato nel change set REM; lock/validator invariati. Ricetta CI locked-base/source eseguita separatamente con 11 servizi operativi; questo non risolve l’identità locale. Primo reset senza env locale e health con flag non supportato falliti, diagnosi e singolo retry correttivo preservati.
- Stabilità richiesta IN_PROGRESS: 3 task run consecutivi e 1 full con --extra test --extra lint, reset/bootstrap/health per ciascuno, watchdog sui restart/OOM e 45 minuti. Nessun PASS finale né richiesta di verifica finché i quattro run e i gate non sono acquisiti. Stato/handoff supportati dal branch governato dedicato per rispettare lo scope task; main resta pulita e completed invariati (63).
- Inputs/E1/E2/Verified/runtime/PoC/Production fence invariati. Log raw esterni ~/.ocor-codex/repair0049c7; evidenza candidata non sigillata. Prossima azione: completare stabilità/gate, pubblicare candidato e chiedere verifica Claude Code sull’HEAD esatto; poi REM-0017 e ordine PO.

### Ripresa dopo interruzione manuale — 2026-10-07T09:30:42.558550+00:00

- Commit locale 129cc2a recuperato senza riscrittura; riallineamento non conflittuale a origin/main 33821f3, sorgente a128a622151261d510b332ca93a688912a119197. Runtime/test identici al commit locale; solo stato già approvato di main acquisito. Scope esplicito task PASS: 14 percorsi complessivi, 2 modificati dal ciclo 7.
- Tentativo precedente: task1/task2 325 PASS ciascuno; task3 324 PASS/1 FAIL/0 skip, capture-kafka exit 255 Unknown e sandbox EOF. Driver interrotto manualmente alle 09:48 locali, pytest concluso alle 10:02. OOM o restart daemon host non dimostrati dai journal; nessuna causa non osservata asserita. Sequenza di stabilità azzerata; full precedente NOT_EXECUTED. Raw fallimento /home/luca/.ocor-codex/repair0049c7/resume-20261007T1128/previous-task3-failure.log con SHA256 b049a4d1b378bbfecdd38936a33b64b4a10763423cfd783c4660c1d70fc5a0a0.
- Preflight corrente: main pulita/allineata, inputs 8/8, harness 14 PASS, drift 0/167 su 63 task, toolchain isolata PASS, scope esplicito task/RCCAD precheck PASS. Worktree/task source recuperati, nessun lavoro scartato. Bootstrap con ricetta CI REM pinned continua a essere distinto dal controllo ID Fuseki locale FAIL, lock invariato.
- Collaudo Cursor esterno osservato concluso; 14 container spike preesistenti non toccati. Solo risorse create da questa sessione entrano nel teardown. Nuovi run background con reset/bootstrap/health, watchdog 45 minuti e acquisizione diagnostica kind; nessun PASS attribuito prima della conclusione.
- Implementatore ciclo 7 Codex; cicli 2–6 Claude Code; verifier Claude Code separato. Completare la sequenza di stabilità ripresa del ciclo 7 su a128a622151261d510b332ca93a688912a119197 (3 suite task consecutive e 1 full, zero skip, timeout 45 minuti), gate ed evidenza candidata; richiedere verifica indipendente Claude Code solo sull’HEAD finale pubblicato. REM-0017 repair 1 resta in attesa del candidato; nessun ciclo 8. Inputs/E1/E2/Verified/claim NO-GO invariati.

- Checkpoint ripresa: task1 su a128a62 = 325 PASS/0 fail/error/skip, 2088.53 s, SHA256 a94a71df44e8c8b96647d1d8dcbe41039b497ec11eb0868247cacb34969e1ade. Teardown con delta vuoto; task2/task3/full ancora pending, nessun PASS finale di stabilità.

- CI source PR #173: 13/13 required SUCCESS su 989ab55fa6c5d23b1dfd4700048cb4b091836664, ruleset 23412233 active/no bypass verificato. Run 37601614242, 37601614246, 37601614371, 37601614527, 37601614529, 37601614534; raw SHA256 db520bd90efd8a90cf670ff8855f8a07644457b0e9f7d00c8241184de2f5dbab. Stato finale da ricontrollare sull’HEAD finale: nessun PASS del sorgente riusato per il merge.

- Checkpoint ripresa: task2 su a128a62 = 325 PASS/0 fail/error/skip, 1734.41 s, SHA256 75cd6e19fe5a2fa5a674774282ab4ab5a13349dee81ce8f0880a1d360b43b092. Teardown delta vuoto; task3/full pending. Rilette le 9 righe IRB del registro approvato v1.1 (BR-003, FR-156, NFR-001/041/042/043/065/067/080); scope candidato resta circoscritto, nessun requisito globale Verified.

### Checkpoint task3 — 2026-10-07T11:06:12.672322+00:00

- 325 PASS, zero fail/error/skip; 1752.64 s, source a128a622151261d510b332ca93a688912a119197. Teardown senza nuovi residui. Raw SHA256 23566a8dfb70523b8c37f65215a45482c46f19d4558660c70555bfa946d455dc. Suite completa ancora pending; nessun verdetto o sigillo dichiarato.

### Ripresa full interrotta e routing Cursor — 2026-10-07T13:31:05.574520+00:00

- Tre task run consecutivi su a128a622151261d510b332ca93a688912a119197 confermati con JUnit/log: 325 PASS ciascuno, zero fail/error/skip. La full precedente non ha un risultato finale; log parziale SHA256 e4a2c45ed7ae0596391e3eb281b02e3ead01c00a6a62709c316e5e9c7a45abaa preservato fuori repo e NON qualificante. Nessun processo orfano osservato.
- Nuova full in corso dopo reset/bootstrap/health; 11 servizi avviati e controllo typed READY. Limite 2700 s e stop al primo OOM/restart invariati.
- Ultima decisione PO OCOR-DEV-0049-VERIFIER-CURSOR: verifier Grok 4.7 via Cursor CLI, terzo fornitore; riparazioni cicli 2–6 Claude Code e ciclo 7 Codex. Sostituisce solo il routing corrente 0049, preserva storia/verdetti. Nessuna verifica avviata dall’implementatore.

### Chiusura implementazione ciclo 7 — 2026-10-07T14:11:08.613626+00:00

- Sorgente a128a622151261d510b332ca93a688912a119197; candidato 9d86abebc7626a36115540a2711772c1d2d19e23; task1: 325 PASS/0 skip (2088.5s), task2: 325 PASS/0 skip (1734.4s), task3: 325 PASS/0 skip (1752.6s), full: 1426 PASS/0 skip (2166.9s), reports: 48 PASS/0 skip (10.2s). Run reali con extras test/lint, reset/bootstrap/health separati, watchdog 45 minuti e teardown inventariato.
- Raw candidato SHA256 ba4e1009bdb8a3ddac604da2c1ca574da443caf953c44c780366e47f7228dee3; campi inputs/tree/commit/environment e manifest riacquisiti e da verificare sull’HEAD candidato prima del push. Nessun sigillo, nessuna PR task prima del verdetto.
- Bootstrap locale identity-lock FAIL exit 2 resta dichiarato; ricetta CI dal branch REM efce339 con base/source pinned e ID reale acquisito. Decision request separata già aperta; nessun lock/checker modificato.
- Implementatore ciclo 7 Codex; riparazioni 2–6 Claude Code; verifier Grok 4.7 (Cursor) in processo/contesto separati. Verifica indipendente Grok 4.7 (Cursor) del ciclo 7 di OCOR-DEV-0049 sull’HEAD 9d86abebc7626a36115540a2711772c1d2d19e23; poi riprendere REM-0017 repair 1 con questo candidato, riallineare il pin e la CI senza esclusioni, richiedere verifica indipendente. Integrazione 0049 dopo REM-0017 verificato; con NO_GO escalation solo 0049 e proseguire G5, nessun ciclo 8.
- Inputs immutabili, E1=0/E2=0, zero Verified; NO-GO e capability differite invariati.

- Diagnosi teardown full: pytest 1426 PASS/0 skip in 2165.19 s; primo controllo supervisore FAIL per 14 volumi non osservati dal polling veloce. Attribuzione tramite delta di sessione, label anonymous, CreatedAt e unico join daemon di ocor-c5-backbone entro 2 secondi. Rimozione mirata completata: 18 volumi totali (4 spike Kafka + 14 harness C5); zero nuovi container/reti/volumi. REM-0018 va esteso a C5 backbone.py in unità separata, nessuna modifica fuori scope nel ciclo 7.
- Gate piano sul candidato dirty inizialmente FAIL per superficie planning-only; dopo commit dei soli tre artifact, retry PASS 37/0 FAIL/2 NOT_EXECUTED opzionali. Gate/allowlist invariati. Diff whitespace del bundle raw resta dichiarato, non normalizzato né spacciato per PASS.


## 2026-10-07T16:57:52.731979+00:00 — OCOR-DEV-0049: NO_GO ciclo 7, escalation e prosecuzione REM-0017/G5

- Unità di disposition/integrazione documentale, branch `governed/state-sync-ocor-dev-0049-cycle7-verdict`, worktree `.ocor/worktrees/state-sync-ocor-dev-0049-cycle7-verdict`, baseline `a7dd7525f1670f45d8996298efb167ff1017bbc1`. Main pulita/allineata; HEAD remoto candidato `9d86abebc7626a36115540a2711772c1d2d19e23` e WIP REM `efce339d9fc7a551216c84135e06d39c0488a222` verificati. Nessun lavoro scartato, nessuna riparazione 0049 o modifica al WIP della PR #169.
- Verdetto `OCOR-DEV-0049-9d86abebc762-7` **NO_GO**, SHA-256 `bc8539a202ce6d88e711a7832e71cf78902ea5e6fee2cd3b609ffa8628ed8e7e`: VF-001 high BLOCKER, receipt accetta ID non finale sostituito o permutazione che conserva last_event_id. Azione minima non autorizzata nel record di escalation. Nessun ciclo 8, sigillo o merge 0049. Riparazioni 2–6 Claude Code, ciclo 7 Codex; verifier effettivo Grok 4.7 xAI via Cursor CLI, processo/contesto separati e terzo fornitore.
- Suite del verifier: task 325 PASS/0 skip, full 1426 PASS/0 skip; il probe bloccante prevale. Tentativo full senza DSN non qualificante conservato nel verdetto; NOT_EXECUTED del verdetto vuoto. Risultati attribuiti al verifier, nessuna verifica indipendente simulata o lanciata dal loop. Runtime locale di questa unità NOT_EXECUTED.
- Preflight corrente: inputs 8/8, harness 14 PASS dopo un solo retry del percorso Python assente, drift 63 task/167 input/0 deriva, toolchain 9/9. Bootstrap locale FAIL exit 2 (identità Fuseki), servizi/initialize/fixtures NOT_EXECUTED. Tag precedente non ripristinabile perché ID non più disponibile dopo build, tentativo fallito conservato; nessun retry/bypass/update lock. Nessun container avviato da bootstrap.
- Ready set dal backlog: OCOR-DEV-0049, OCOR-DEV-0050; 0049 bloccato, 0050 eseguibile. Chiusura transitiva bloccata: OCOR-DEV-0049, OCOR-DEV-0059, OCOR-DEV-0060, OCOR-DEV-0061, OCOR-DEV-0062, OCOR-DEV-0063, OCOR-DEV-0064, OCOR-DEV-0065, OCOR-DEV-0066, OCOR-DEV-0067, OCOR-DEV-0068, OCOR-DEV-0069. Prossima unità REM-0017 repair 1, CI run 37580988000 FAILURE da diagnosticare; nuovo pin candidato esplicitamente NO_GO, ciclo di vita e zero skip da qualificare con Claude Code. Se REM bloccato da evento esterno/decisione, proseguire G5. CONTINUE, nessun arresto globale.
- Gate locali finali e check CI esatti da acquisire prima del merge; raw log/hash `/home/luca/.ocor-codex/state-sync-0049-cycle7-verdict`. Inputs, record candidati/sigillati, completed_evidence_tasks (63), E1/E2/Verified/claim e capability differite invariati. Nessun nuovo DEC o chiusura OI/ASM/RSK.

- Gate locali finali: RCCAD PASS_LOCAL_PRECHECK, scope/language/ruff/mypy strict 69 file, evidence 0048 e drift PASS; piano 37 PASS/0 FAIL/2 NOT_EXECUTED opzionali. Generated harness/planning output preservati nei raw e ripristinati fuori change set. Controllo residui bootstrap/PoC vuoto; nessun container/volume creato dalla sessione, spike preesistenti preservati. Il tag Fuseki ricostruito resta diverso dal lock, controllo FAIL esplicito. Candidato 0049 worktree CLEAN e HEAD invariato.

- Pubblicazione: due push Git falliti con Internal Server Error GitHub, nessun terzo tentativo. API Git Data ha pubblicato lo stesso tree `05b69c22f6dee977e89ed2838046e952054734f7`: commit locale `0121d7d` preservato sul branch `governed/state-sync-ocor-dev-0049-cycle7-verdict-local-preapi`, commit API `64468442dd4e9e116e4b5cdd59af7ea0bf4a0439` diverso per la sola omissione della newline finale del messaggio di commit nel payload API; l’API mostra date UTC ma preserva l’offset dei Git header. Worktree allineato al remoto, nessuna riscrittura. Prima PR create GraphQL server error; un solo retry riuscito, PR #174.
- CI sorgente PR #174: **13/13 required SUCCESS** su `64468442dd4e9e116e4b5cdd59af7ea0bf4a0439`, run 37655615572, 37655615668, 37655615679, 37655615745, 37655615845, 37655615933, osservazione `2026-10-07T17:24:29.116971+00:00`, raw SHA-256 `f905f81a6d35d4c4872a2c03f9b142181e1afe1b14687914249f7e68dba2c27e`. Ruleset 23412233 active, 13 required, bypass assente verificato. Il commit finale documentale richiede nuovamente tutti i check verdi sull’HEAD esatto prima del merge; nessun riuso dei PASS sorgenti per il finale.

- Diagnosi della pubblicazione API verificata sul formato Git: La sola omissione della newline riproduce esattamente SHA sorgente 64468442 dal commit locale 0121d7d; tree, parent e istanti invariati. Il primo commit finale locale 41cf5de non era ancora referenziato dal branch remoto quando l’assert SHA ha rilevato la stessa omissione. Payload corretto per preservare la newline e ottenere lo SHA locale esatto; nessun test/gate alterato, nessuna storia riscritta.

## 2026-10-07 — REM-0017: ripresa bootstrap CI e supervisione della campagna (WIP)

- Baseline 33821f315138b90bdae7f940e5327b15f9a19948; source snapshot f8191c52fe5a46df17500670339361b41607551f; branch/worktree dedicati della PR #169 inattiva dal 5 ottobre, ripresi senza interferenza o riscrittura. Implementatore Codex, verifier previsto Claude Code (non avviato).
- Probe UID diverso/CA 0600 riproduce permission denied sul digest SPIRE. Nuovo bootstrap completo: CA owner 1000, pin da lock, workload control-plane/SVID reale, init/fixture e 9 gruppi tipizzati READY (11 container). Build Fuseki CI con ricetta pinnata, ID effettivo registrato; checker locale e lock invariati. Actions commit-pinned, teardown always, suite limitata a 45m con guard restart/OOM/identità/StartedAt e zero skip.
- RED/GREEN: guard inizialmente assente; 17 test finali verdi inclusi restart manuali. Primo full: 913 PASS, 2 FAIL, 186 ERROR, 0 skip per workload SPIRE non registrato; corretti bootstrap e SVID, reset completo, full retry {"tests": 1101, "failures": 0, "errors": 0, "skipped": 0}. 44 test report PASS e 10 script standalone PASS; precedente invocazione pytest sui runner standalone non valida (SystemExit), conservata. Nessuna esclusione per ottenere il verde.
- Gate locali PASS; piano 37 PASS/2 NOT_EXECUTED opzionali dopo settle self-hash, allowlist solo puntuale. Drift 0/167, 63 completed invariati. Supersivisione StartedAt aggiunta dopo avvio del full retry e validata separatamente: limite dichiarato, nessuna qualifica conclusiva o sigillatura.
- TEST-INFRA-006 NOT_EXECUTED: file 0049 assente su main; candidato d0ac80a NO_GO preservato. REM OPEN/WIP; no richiesta indipendente su change set incompleto, no merge. Prossima unità: CI esatta #169 e campagna separata del candidato per il guard 006 senza riparazione/promozione; con risorse insufficienti, misure/decision request e 0050.
- Raw log content-addressed 2b67b5bc64502d37323e98ac536a66f4ab9c1b8c3242a162d04d0b7d72188b45; CI nuova da osservare dopo push; inputs/E1/E2/Verified/runtime/PoC/Production invariati.
- Teardown finale: zero container e volumi del progetto creati dalla sessione; nessuna risorsa non OCOR toccata.
- Prima CI sul WIP 5c0b0a3: supply-chain FAILURE, run 37564144092, artifact 11458446486. Unico finding PRIVATE_KEY sul literal dell’header PEM del test fittizio (payload private-data); stesso caso costruito a runtime, 17/17 PASS, scanner e gate invariati. Head successivo da osservare; nessun rerun del finding reale e nessun PASS CI riusato.

## 2026-10-07 — REM-0017: checkpoint igiene JVM e retry qualificante

- Codice 809f460d7faf1b51fcb72b534edad802489933c7, PR #169 WIP. FULL candidato interrotta al minuto 27 dal supervisore: Fuseki OOMKilled=true/137, 1309 PASS parziali, zero skip; non qualifica. Diagnosi: entrypoint pinned JVM_ARGS=-Xmx4G, cgroup 2 GiB. Raw/statistiche conservati in ~/.ocor-codex/rem0017-resume/failed-candidate-oom/.
- Override del solo bootstrap CI worktree-local: heap 1 GiB, Xms128m; Compose governato, ceiling 2 GiB, immagine, Dockerfile, lock e checker invariati. Misura reale 1073741824/2147483648 byte, processo Java effettivo e probe della JRE pinned. jcmd assente e Docker top senza PID sono errori documentati, non PASS. 29 test supervisore/guard PASS; nuove guard heap RED 4 FAIL/23 PASS prima della funzione.
- Reset e bootstrap completi prima del retry; retry FULL candidato in corso, FULL del branch REM in attesa del suo esito. CI degli HEAD superseduti non riusata come verde finale; nessuna sigillatura/verifica richiesta/integrazione. Checkpoint per ripresa da Git durante eventuale compattazione. 63 completed invariati; 0049 NO_GO, nessun ciclo 7; E1=0/E2=0 e claim fence invariati.

## 2026-10-07 — REM-0017: copertura CI del candidato immutabile e richiesta di verifica

- Unità: completamento implementativo REM-0017, PR #169; codice 4658ad808d41dfdb0b75255837adfd3f9609d071, baseline 33821f315138b90bdae7f940e5327b15f9a19948. Ripresa del WIP versionato, nessuna attività concorrente nel worktree. Job candidato su d0ac80a, FULL suite senza selezioni, HEAD/diff e moduli obbligatori controllati prima/dopo; validation-closure fallisce anche su dipendenza cancellata/non eseguita. Nessuna riparazione o accettazione 0049.
- Run qualificanti locali e CI riportati nel record e nei raw log reali: {"candidate-full": {"errors": 0, "failures": 0, "skipped": 0, "tests": 1422}, "main-full": {"errors": 0, "failures": 0, "skipped": 0, "tests": 1101}, "report_guards": {"errors": 0, "failures": 0, "skipped": 0, "tests": 53}, "report_regression": {"errors": 0, "failures": 0, "skipped": 0, "tests": 24}}. Gate ruff/mypy strict, RCCAD statico, scope, language, drift, evidenza 0048 e inputs verdi; piano 37 PASS/2 NOT_EXECUTED opzionali. RED guard: 4 FAIL/17 PASS; RED lock: 1 FAIL/22 PASS, fingerprint conservati; exit code delle iniziali shell composte non catturato separatamente, nessun codice sintetico attribuito.
- Primo full candidato interrotto dopo 1309 PASS (parziale, non qualificante), Fuseki OOMKilled=true/137 nel cgroup 2 GiB; entrypoint -Xmx4G. Diagnosi e raw conservati; bootstrap CI impone -Xms128m/-Xmx1G e verifica JVM effettiva/probe del runtime pinned. Jcmd assente e comando docker top privo di PID: tentativi bootstrap falliti preservati, metodi sostituiti dopo diagnosi; nessun PASS attribuito. Nuova acquisizione dello stack prima del retry.
- Tooling supplementare ufficiale Helm/kind/kubectl con checksum pubblicati, archive/binary digest distinti dove necessario, installazione worktree-scoped. Nessun cambiamento di infra/toolchain.lock.json, infra/services.lock.json, Dockerfile o checker; sole aggiunte puntuali all’allowlist di piano e self-hash settle. Teardown kind/bootstrap entrambi tentati anche su errore.
- CI sorgente run 37568937953 su 4658ad808d41dfdb0b75255837adfd3f9609d071 SUCCESS, tentativo 2 del solo job principale; candidato PASS al tentativo 1. Prima build del job principale in timeout 300s, cleanup ERROR prima dell’env (nessuno stack creato): causa interna non catturata, raw preservati, un solo rerun senza cambio di pin/timeouts/gate; nessun PASS retroattivo. Evidenza operativa dei sei guard. Il record finale richiede nuovi check esatti prima del merge: non riusa il verde sorgente come verde finale. Implementatore Codex/OpenAI; verifier Claude Code/Anthropic in contesto separato, richiesta al loop, nessun verdetto simulato.
- Completed invariati (63), ready set dalle dipendenze 0049/0050, 0049 escluso per escalation ciclo 6. Priorità REM-0017 poi 0050. Richiesta Fuseki separata pendente e non bloccante per CI; E1=0/E2=0, zero Verified, runtime NOT_ESTABLISHED e PoC/Production NO-GO invariati. CONTINUE.


## 2026-10-07 — OCOR-DEV-REM-0017 repair 1, preparazione e attesa candidato 0049

- Mandato CC-OCOR-DELIVERY-COMPLETION; implementatore Codex/OpenAI,
  verifier Claude Code/Anthropic separato. Ripresa dal main 33821f315138b90bdae7f940e5327b15f9a19948
  e dal verdetto REM-0017-6e2a08b62524-0 NO_GO: VF-001 CI race candidata,
  VF-002 margine/pin, VF-003 teardown senza env, VF-004 volumi spike.
- Worktree isolato e branch della PR #169 ripresi puliti, senza riscrittura.
  Nessun implementatore concorrente attivo sullo scope; wrapper storico
  Claude 0049 presente, candidato remoto d0ac80a invariato, nessun suo file modificato.
- RED: 7 test teardown FAIL prima del codice, fingerprint SHA-256
  0f6ba5aa378bfd28ea5c224ccd053a38e070115e5126873a74b035d4c325b6c4.
  GREEN: 60 guard/report PASS, zero skip. Teardown CI credenziale-free
  accetta solo inventari vuoti; Docker non disponibile o risorse residue
  falliscono. Il reset sigillato 0082 è invariato; nessuna sua riqualifica necessaria.
- VF-004 registrato come REM-0018 (successore libero verificato su repo/worktree),
  nessuna modifica spike nello scope REM-0017; dipendenza G6 e riqualifica futura.
- Bootstrap locale NOT_READY: identità Fuseki diversa dal lock, exit 2,
  fallimento preservato senza retry; il punto resta nella decision request esistente.
  Stack della ricetta CI qualificato tipizzato e 11 servizi pronti all'avvio;
  suite completa e prove Docker catturate nel record WIP e nell'handoff.
- Il primo controllo piano rileva solo self-hash del validator dopo aggiunte
  puntuali all'allowlist; settle previsto senza modifiche alla logica dei gate.
  L'ambiente recuperato manca di mypy: primo type check FAIL, extras lint
  da completare prima del gate strict; esiti finali registrati nell'handoff.
- VF-001/VF-002 REM ancora aperti; nessun rerun intermittente o aumento del
  limite 45 minuti. Nessun sigillo/merge o verifica simulata. Attesa esterna
  del candidato stabile: ora autorizzato ciclo 7 0049 Codex, Claude verifier,
  da d0ac80a remoto. Prossima unità: riparazione 0049 e stabilità richiesta,
  poi nuovo pin e CI completa + verifica REM repair_cycle=1. REM non abbandonato.
- Inputs immutabili, E1=0/E2=0, zero Verified, claim NO-GO invariati.
- Chiusura locale dell'unità: full 1101 PASS in 387.78 s, zero skip; report 60 PASS,
  regression 18 PASS; mypy strict PASS su 72 file dopo sync frozen extras test/lint
  (7 sole aggiunte, nessuna distribuzione preesistente cambiata). Prove Docker
  positive e negativa PASS: no-op senza env solo su assenza verificata, rete
  etichettata presente → rigetto e nessuna rimozione implicita. Normale teardown
  elimina progetto; 18 volumi anonimi dei test rilevati e rimossi individualmente
  sulla sola differenza della sessione, confermando VF-004/REM-0018. Nessun residuo
  bootstrap; nessuna operazione sulle risorse Docker esterne alla sessione.
- Source commit `188f6e9f8aa3d04b92e3c5a0f9668ddd2ffbf611`; record WIP repair-1 preserva record e raw del
  candidato rifiutato. Piano settled 37 PASS/2 NOT_EXECUTED opzionali;
  gli altri gate locali PASS. CI nuova e verifica REM NOT_EXECUTED, in attesa
  del candidato ciclo 7 0049; nessun PASS attribuito all'HEAD CI fallito.


## 2026-10-07T17:57:27.374104+00:00 — REM-0017 repair 1: ripresa qualificazione

- Main 9afbc87, WIP efce339 preservato e merge non riscritto e00ba10. Conflitti risolti preservando stato/verdetto 0049 ciclo 7 di main e append integrale delle voci REM precedenti; nessun codice/task/evidenza 0049 modificato. Verifier REM Claude Code, implementatore Codex.
- CI 37580988000: artifact mostra timeout docker build Fuseki 300s; fase interna non acquisita, nessuna diagnosi inventata. Log build plain salvato anche su exit nonzero/timeout; budget operazione provisioning 600s (massimo già ammesso), suite 2700s invariata. RED 3 FAIL per helper assente, GREEN 39 PASS senza skip; subprocess reali per positivo/failure/timeout locale. Dockerfile/base/source/lock/checker invariati.
- Checkout main anticipata al rigetto della dipendenza CI per rendere eseguibile il teardown stdlib anche se l'ambiente Python non è stato sincronizzato. Pin TEST-INFRA-006 aggiornato al candidato stabile 9d86abe, esplicitamente NO_GO, senza approvarlo né sigillarlo. Ciclo di vita e qualifica infrastrutturale distinti dalla disposition del task.
- Digest 8/8, harness 14/14, drift 0/167, toolchain 9/9 PASS; campagne reali/CI nuove ancora pending, nessun PASS finale. Processo esterno passa-a-claude-0049 osservato in attesa; nessuna interferenza con branch 0049, nessun altro stack attivo.


### 2026-10-07T19:05:20.064154+00:00 — REM-0017 repair 1: candidato completo

- Source 16afae4b493916a0db332311d3dd80211702698b; local main 1101 PASS in 383.35s, candidato 1426 PASS in 2552.41s, zero fail/error/skip; reports 63 PASS. Reset/bootstrap/health separati, extras test/lint, watchdog 2700s e guard restart/OOM.
- Source CI 12/13 required SUCCESS al momento della preparazione, conditional-infrastructure-0049 SUCCESS; validation-closure ancora pending nell’osservazione storica; raw observation SHA256 2f4de6731c0edaf7d7abd6be9bedf7cd9c87de84423f02582e012888d0564cd8. Il commit finale di soli report richiede nuova CI esatta prima della richiesta di verifica; nessun PASS riusato sul finale.
- Nuovo raw repair-1 SHA256 45b47a750f4327a94b228a29bc6a74fd8feed1a931bdc14400ec1de01cb1d5a4; record WIP precedente preservato in Git efce339, evidenza originale rifiutata invariata. Inputs/tree e lock reacquisiti. Implementatore REM Codex, verifier Claude Code separato; nessuna verifica lanciata o simulata.
- CI build: ADD dell’archivio Fuseki 485.8s e checksum SHA512 PASS, compatibile con budget precedente 300s insufficiente; fase storica dei vecchi timeout non retroattribuita.
- 18 volumi anonimi per full local, provenienza OCOR acquisita e rimozione scoped; zero delta finale di sessione. REM-0018 resta OPEN e comprende anche C5 backbone; nessun fix fuori scope nel REM. Bootstrap locale identity FAIL conservato, lock/checker invariati.
- Piano iniziale FAIL per log generato fuori allowlist: archiviato fuori repo, retry 37 PASS/2 NOT_EXECUTED opzionali. Primo controllo DEC208 senza builder prerequisite FAIL, retry in ordine workflow 19/19 PASS; artifact generati ripristinati. Tutti i tentativi preservati.
- 63 completed invariati; 0049 NO_GO cycle7/Cursor preservato, nessun ciclo 8. Inputs/E1/E2/Verified e NO-GO invariati.


## 2026-10-07T20:07:47.087641+00:00 — REM-0017 repair1: CI esatta FAIL e prosecuzione G5

- Final report HEAD11fd3e49, run37672467983: candidato timeout2700s durante Helm; JUnit parziale1314/0 fail/error/skip NON qualificante. Teardown FAIL per risorse residue; identità precise non esportate (NOT_EXECUTED). Main suite NOT_EXECUTED dopo rigetto della dipendenza, main no-env teardown PASS. 12/13 required SUCCESS, validation-closure e conditional job FAILURE.
- Source16afae4 run37663505832 completato SUCCESS, candidato2650.596s/main392.547s, zero skip: risultato storico, non sostituisce il finale. VF-002 materializzato; nessun rerun per cercare il verde, nessun verifier/verdetto simulato. Candidato repair1 ora NOT_QUALIFIED, nuovo rawSHA256 76a63b4dbf4636db04534b4b18d8c7727fd05c7a60576013137b2c136db7aaf3, originale rifiutato invariato e versione11fd preservata.
- Docker stats al timeout runner15.61GiB, Fuseki1.361GiB/2GiB, Keycloak586.6MiB/2GiB; nessuna deduzione di causa OOM senza prova. Decision request REM-0017-CI-CAMPAIGN-BUDGET OPEN conforme a REM-0017-PRIORITY. Main CI artifact storici tracciati non qualificano run non eseguito.
- PR169 resta draft. Stato/handoff: prossimo0050/G5, REM17/G6 aperti; 63 completed, 0049 NO_GO7/no8, input/lock/gate/fence invariati. Allowlist piano aggiunta solo per il nuovo documento richiesto; self-hash settled senza variare controlli. ImplementatoreCodex, verifierREMClaude non richiesto. Nessuno stack locale residuo dalla sessione.


### 2026-10-07T20:09:41.259594+00:00 — state sync separato della diagnosi REM-0017

- WIP/raw preservati e pubblicati su4336137, PR169 draft. Questo branch integra soltanto stato, handoff, log e richiesta PO; nessuno script CI/provisioning/supervisore, lock o codice0049 viene promosso. Allowlist piano aggiunta per il solo nuovo documento richiesto e self-hash aggiornato, senza cambiare la logica dei gate.
- Baseline9afbc87; CI state sync da acquisire sull’HEAD esatto, 13 check richiesti; la deviazione temporanea164 preesistente resta invariata e non qualifica REM. Prossima azione0050/G5; nessun nuovo verifier richiesto, nessun sigillo/claim, 63 completed.

- Gate locali dello state sync: RCCAD PASS_LOCAL_PRECHECK (dynamic CI_REQUIRED), piano37 PASS/2 opzionali NOT_EXECUTED, scope6 percorsi PASS, drift63 task/167 input con zero deriva, language/ruff PASS, checksum8/8 PASS. Nessuna suite aggiuntiva richiesta per il solo aggiornamento documentale/inventory; la qualifica REM resta FAIL.


## 2026-10-08T07:18:03.967776+00:00 — OCOR-DEV-0049 ciclo8: GO indipendente, sigillo e CI di integrazione

- Unità 0049:integration; main `9e5058666ce6c1ea1acbbd434f171d1e98784d92` pulito/allineato. Decisione PO REPAIR-8: riparazioni cicli2–6/8 Claude Code, ciclo7 Codex; verifica ciclo7 e verifier effettivo ciclo8 Grok4.7 (Cursor), fallback dopo due interruzioni di moderazione Codex. Codex integra soltanto; nessun codice0049 riparato, verdetto letto senza scrittura.
- GO_FOR_EVIDENCE_SEAL `OCOR-DEV-0049-b14e4bf59695-8` su `b14e4bf596959de35313dd9a6ee538576432ffd2`, zero finding/not_executed, SHA256 `130a47fc98ed61fc0865079418ff9df3a2877a8d42b140357f3a8d6a1f912d4b`. Verifier: tre task suite390 PASS ciascuna, full1491 PASS, zero skip/fail/error; stack reale. Sigillo `df444af855e884d7783612b302e008b90105fe13` modifica solo record e relativo manifest; raw SHA256 `90e9ebcdfdd2718474ef54c25333a3ba851cbaa4b503f48ee9693ebfb373f5db` e11 input invariati/riacquisiti; nessun record già sigillato modificato.
- PR176 aperta, CI esatta `df444af855e884d7783612b302e008b90105fe13`: 10/13 required SUCCESS, FAIL `rccad-methodology, delivery-activation, validation-closure`, run `[37740936580, 37740936597, 37740936608, 37740936657, 37740936664, 37740936708]`. Raw osservazione SHA256 `18de18caafa3b9f62e7bd16901c1960dd55c8ce8eee8059b79550d067ed73fa9`. Nessun merge, bypass, rerun opportunistico, esclusione o nuova guardia; 63 completed invariati. Dipendenze0049 non soddisfatte fino a merge/state sync. REM-0017-PRIORITY: PR resta aperta, prossimo REM17 separato, poi0049/0050.
- Preflight inputs8/8, harness14 PASS, toolchain9/9, drift0/167; bootstrap standard FAIL identità locale Fuseki differente dal lock, init/fixture/health NOT_EXECUTED. Nessuno stack avviato e nessuna risorsa creata. Evidenza real-backend accettata del candidato preserva limitazione/ricettaCI locked; lock/checker non modificati.
- Gate sigillo locali PASS (evidenza, RCCAD precheck, scope14, language, drift, ruff, mypy strict). Piano37 PASS/2 tool opzionali NOT_EXECUTED sul commit sigillato; tentativi iniziali con baseorigin/main/HEAD sporco FAIL per guard planning-only, log e referti conservati, file generati ripristinati. Primo comando ruff puntava al binario .venv assente (NOT_EXECUTED); corretto con ruff pinned già validato dal preflight. Nessun gate alterato.
- Decision request REM-0017-CI-CAMPAIGN-BUDGET risolta dalla decisione PO2026-10-07: full75m, task45m, richiesta nuova se full>60m, arresto su restart/OOM, export identità residui e teardown fail-closed. Implementazione REM resta WIP4336137/PR169, non toccata da questo state sync; ciclo repair1 in ripresa richiede verifier Claude Code. Interpretazione di scheduling:0049 ha ora chiusura verificata ma CI impedisce il merge; si applica la regola esplicita REM-0017-PRIORITY (PR aperta→REM→integrazione0049), senza promuovere task/completed o aggirare dipendenze.
- Stato/handoff allineati al verdetto8, escalation7 preservata in append; nessun ciclo9. State sync con tutti i check verdi HEAD esatto richiesti. E1=0/E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO invariati. CONTINUE.

- Referti CI esatti: rccad1 FAIL/1164 PASS/189 skip/137 ERROR (433.21s); delivery1/1164/189/137 (430.32s); closure1 FAIL/1157 PASS/0 skip/137 ERROR (470.58s). Tutti non qualificanti. Extras lint/mypy e env stack assenti; nessun finding funzionale nuovo dichiarato o rigetto del GO indipendente. Gate state-sync iniziale AFF-008 FAIL per riferimenti a artifact presenti solo nel branch non mergiato; spostati in source_reference con branch/HEAD/hash, nessuna copia/promozione. Gate finali RCCAD/scope/language/drift/input/piano PASS (2 tool opzionali NOT_EXECUTED), log hash nell’handoff.

- State-sync PR177 CI sorgente:13/13 required SUCCESS su `f583c89d3db220817fa97580efeb54a87821443b`, run `[37742762781, 37742762794, 37742762831, 37742762841, 37742762888, 37742762932]`, osservazione `2026-10-08T07:38:46.547684+00:00`, raw SHA256 `e3b987355be655aae5d505471be7c151714d338c259933105e937dab489b2a7c`. Commit finale aggiorna soli stato/handoff/log; i13 check del finale verranno attesi separatamente prima del merge. Nessun PASS sorgente trasferito al finale; PR176 e ledger63 invariati.


## 2026-10-08T08:12:45.383473+00:00 — REM-0017 repair1: budget e stack in tutti i job full

- Baseline d044aa95328092c1ef9708c05413bafd3c6ddc2e; merge non riscritto c513205 preserva storia WIP4336137 e stato0049 ciclo8 GO/sigillo/PR176 non mergiata. Ready set dalle hard_dependencies:0049/0050; priorità esplicita REM17. Nessun concorrente attivo nel suo scope.
- Decisione PO REM-0017-CI-CAMPAIGN-BUDGET: full4500s/task2700s; soglia3600s segnala decisione; stop restart/OOM invariato. Job budget110m include provisioning e teardown, senza ulteriore estensione della suite.
- RED5 FAIL/39 PASS, fingerprint0be3133ee1a830ff3e9c2a20ead71d9317e59db47d49c2d477307be65bcf8810; GREEN68 PASS/zero skip. Teardown esporta ID anche dopo reset fallito; ledger Docker attribuisce volumi ai soli container OCOR creati dalla campagna, protegge baseline, rifiuta residui. Prova reale PostgreSQL pinned: volume lasciato da rm senza-v attribuito, mount attivo rifiutato, cleanup esatto e sentinel invariato. Nessun fix degli spike nello scope REM; REM18 resta OPEN.
- RCCAD e delivery provisionano ora gli11 servizi pinned, SDK Node/tsc e extras test/lint; regressione FULL supervisionata e zero skip. Pin guard0049 df444af accettato indipendentemente ma ancora non integrato; nessun codice o sigillo0049 modificato.
- Preflight9/9, checksum8/8, harness14 PASS e drift0/167 PASS. Comandi iniziali con nome preflight inesistente e lookup task_id invece di id NOT_EXECUTED/corretti, nessun PASS attribuito. Bootstrap standardFAIL identità Fuseki; lock/checker invariati. Sync frozen aggiunge soli7 package extras lint. Campagne complete locali/CI e nuova verifica ancora pending. Implementatore Codex/OpenAI; verifier REM Claude Code/Anthropic separato.
- E1=0/E2=0, zero Verified, runtime NOT_ESTABLISHED e PoC/Production NO-GO invariati.

- 2026-10-08T08:23:58.465500+00:00: local main1101 PASS/0 skip in359.52s, supervisore362.8s, teardownzero residui bootstrap/sessione. RED aggiuntivo2 FAIL/44 PASS (fingerprinta56a7e7a67fae103f776ef630212ef19fc4c9656e86a96e0da721b310a838207): fine processo oltre deadline e redazione anche su errore del recorder; GREEN46 PASS, mypy strict72 e ruff PASS. Teardown candidato usa stdlibpython3 anche quando sync manca. Correzioni del supervisore prima della qualifica finale, non nuovo ciclo di riparazione indipendente. Source6905 CI pending/superseded da acquisizione nuova; nessuna qualifica trasferita.

- 2026-10-08T08:25:54.535285+00:00: piano iniziale FAIL per reports/tests/ci_fuseki_build.log generato dal bootstrap (fuori allowlist). Log archiviato fuori repo; settle37 PASS/2 opzionali NOT_EXECUTED, nessuna modifica alla logica del gate. Prima snapshot a4c3 includeva FAIL e non qualifica l'HEAD; nuova CI esatta dopo correzione del solo run state. gh pr edit classic-projects ERROR e gh pr checks --json non supportato dal gh host: usati API PATCH e gh pr view con toolchain isolata; nessun controllo dichiarato PASS dal tentativo fallito. CI sorgente6905 CANCELLED come superseduta da due correzioni del supervisore, non rerun per ottenere verde.


## 2026-10-08T09:40:15.212131+00:00 — REM-0017 repair1: qualifica CI bloccata, prosecuzione G5

- Source40c9: delivery37749800685 SUCCESS/FULL1101 zero skip in509.84s; RCCAD37749800723 e closure37749801174 FAIL dopo tentativi1/2, Docker ADD archivio ufficiale Fuseki timeout600s. 11/13 required verdi, candidate/main closure NOT_EXECUTED; nessun terzo tentativo, incremento budget o esclusione. Nuova richiesta REM-0017-CI-ARCHIVE-ACQUISITION; PR169 resta draft e PR176 aperta.
- Locale FULL main1101 zero skip362.80s, candidatoimmutabile df444af1491 zero skip2845.55s. Supervisore iniziale6905, correzioni deadline/finalizzazione/osservatore successive provate in portfolio73 PASS; run FULL/CI storici non qualificano ultimo HEAD `8ff46dbd7cf3b1f44030094c6078772063e34e86`. Ruff0/mypy strict53 file0; RED observer3 FAIL/46 PASS fingerprint `da30c7dd80af0075fcfd453203ed4f97934eb9e36351c76612a1cbf25072f30a`, exit non catturato separatamente. Record riparazione precedente preservato; nuovo WIP repair-1-resume/rawSHA256 `992cb8ef66d9c508afcd27f12e516d53e4e35c45d07d344e3d9356d13962a12c`.
- Teardownmain/candidato PASS e inventario finale zero delta container/volumi/reti, foreign e baseline preservati. Wrapper finale FAIL solo nel ripristino dell'immagine precedente da8504 non più presente; causa rimozione non provata, nessun retry o modifica lock. Richiesta FUSEKI separata conserva FAIL.
- Nessuna nuova verifica lanciata: implementatore Codex/OpenAI, verifier REM Claude Code/Anthropic in contesto separato previsto. Repair1 non consumato da nuovo verdetto; nessuna riparazione0049. Stato63 completed invariato, prossimo0050/G5 secondo REM-0017-PRIORITY. FULL75m/task45m e stopOOM invariati, E1/E2/Verified0 e NO-GO invariati.

- Gate locali finali: RCCAD PASS_LOCAL_PRECHECK/dynamic CI_REQUIRED; scope23 percorsi/language/drift0/167/checksum8/8 PASS; piano37 PASS/2 opzionali NOT_EXECUTED dopo settle del self-hash della sola allowlist DR. Generic runtime validator privo task/manifest NOT_EXECUTED; corretto manifest0048 PASS, senza qualificare REM17. Generatore report errore indice JSON corretto prima della creazione. Hash/log reali nell'handoff.


### 2026-10-08T09:42:51.747071+00:00 — State sync separato della diagnosi archivio CI REM17

- Baseline `d044aa95328092c1ef9708c05413bafd3c6ddc2e`, WIP `23801b08a50d4212acb65bac8b46313b5c62ae95` preservato in PR169 draft; questo branch aggiorna soli stato/handoff/log, nuova richiesta e allowlist esplicita/self-hash. Nessun codice CI/provisioning o record non sigillato REM viene copiato su main.
- Next0050 validato dalle hard_dependencies e63 completed;0049 GO sigillato ma PR176 CI rossa resta aperta; G6/G7 bloccati da REM17. Verifier REM Claude Code non richiesto. CI esatta dello state sync da attendere senza bypass; CI preesistente non qualifica REM17.

- 2026-10-08T09:56:03.754217+00:00: WIP23801b0 CI conclusa,10/13 required PASS, RCCAD/delivery/closure FAIL al timeout600s del provisioning; run37758409850/37758409836/37758409757. BuildlogRCCAD conferma ADDarchivio/base3.1s; full NOT_EXECUTED, nessuna qualifica trasferita da40c9. Hash dei raw nella richiesta/handoff; nessun retry dopo condizione invariata e bounded retry già consumato.

- 2026-10-08T10:09:11.225490+00:00: PR178 sorgente `667a5230e1a10433572cedc85fd858951b80c571`13/13 required PASS, run[37758651103, 37758651124, 37758651135, 37758651149, 37758651177, 37758651179, 37758651284], rawSHA256 `bc1842266282fa78a5b84870c1ca81dda2d2a72f329eda13ce0b65a26a79f78c`. Source CI non trasferita al finale; questo commit aggiorna soltanto stato/log/richiesta alla CI WIP238FAIL esatta. Finale13check da attendere separatamente prima del merge --match-head-commit. Nessuno script/recordREM promosso.


## 2026-10-08T16:04:42.208402+00:00 — Riacquisizione governata identità locale Fuseki

- Unità dedicata FUSEKI-LOCAL-IDENTITY-AFTER-CI-EXERCISE; implementatore Codex/OpenAI, verifier Claude Code/Anthropic separato. Main ef58743adebe717113832da1094224e5117d1c48 pulito; ripreso dallo snapshot REM17bc811af pubblicato dopo interruzione manuale. Nessuna riparazione0049 o promozioneREM17.
- Precedente ID a1eb484a7d056a897c7bc832fb735b06136fc876aa90da3055d9882bc1b8d9e3; nuovo 6534156b8d8f16b28faf0c336096e5c6a751794828525a8ef42c60ef46c9cc2b; host nepryoon, data 2026-10-08T15:31:37.526118+00:00. Base effettiva eclipse-temurin@sha256:db1689535962d757a5adabf57387584ed543d38c0b9d1fe870123ea362ad73b0; SHA512 ba65f5867d2d4741b2ed9e2af5a0d4fbb447909894ab2a0c6bc4dac8997f4fe339c87b13c48d45d054977769f0f8bf763ea346b1f7792d5cdc458041bd43a132; Dockerfile 8704d0e891f232c5f85a2b2cd59ccf3ee14905aeb4862452c92088f816051026. CacheHIT ri-hash prima dell’uso, archivio Apache stesso contenuto; RUN SHA512PASS e layer-base prefix verificati. Motivo: nuova ricetta COPY dopo esercizioCI, non cambio macchina asserito.
- Services lock cambia SOLO output_sha256; schema chiuso invariato, metadati nel companion infra/fuseki/local_identity.lock.json. Ricetta finale archiviata dal branchREM; Dockerfilemain invariato, nessuna uguaglianza di rebuild clean-main dichiarata. Bootstrap/validator identità invariati.
- Qualifica finale FULL{'errors': 0, 'failures': 0, 'skipped': 0, 'tests': 1101} in 378.50s; extras test/lint, tutte tests/ senza esclusioni, guard48 eseguita. Suite positiva/negativa della riacquisizione {'command': ['ocor-runtime/.venv/bin/python', '-m', 'pytest', 'reports/tests/test_fuseki_local_identity.py', '-q'], 'duration_seconds': 0.21437697899818886, 'exit_code': 0, 'label': 'acceptance', 'raw_sha256': '19991ff1b5d6004c54edc99ee9d90444b45855bbc590e2fd911191426511f7fb'}. Typed health, faultbounded e recovery reali; teardown ledger esatto senza residui. RawSHA256 e005ddf77ac399404dbd19532f25bc2b2e4ca765a6e0779fc7014a373c062d50.
- Tentativi storici conservati: reset senza envFAIL; FULL1 913PASS/2FAIL/186ERROR per entrySPIRE assente; FULL2pytest1101PASS ma wrapperFAIL per modalità candidato0049 invocata erroneamente su main. Registrazione workload autorizzata e nuova FULL integrale con guardmain corretta; nessun esito fallito convertito inPASS e nessun test/gate del repo modificato.
- DriftRED8 input su otto task infrastrutturali; riqualifiche nuove con supersession e log reale condiviso, originali sigillati byte-identici. GREEN final da acquisire;63completed e claimsE1/E2/Verified0, runtimeNOT_ESTABLISHED, PoC/ProductionNO-GO invariati.
- Nessuna PR di questa unità prima del verdetto. Richiesta esterna sul finale dopo gate/push; CI esatta successiva obbligatoria. PR169draft/176 aperte; poi0050/G5, REM17 locale restaWIP, nessun nuovo ciclo0049.

- Gate finali: drift0/167 su63task; ruff/mypy strict69file/language/scope/checksum8/8/evidenza principale e8riqualifiche PASS. RCCAD PASS_LOCAL_PRECHECK con CI_REQUIRED; piano37 PASS/2 tool opzionali NOT_EXECUTED dopo settle del solo self-hash della allowlist precisa. Nessun controllo optional trasformato inPASS. Ultima shell dei test linked inizialmente non isolata27PASS/2skip è stata rifiutata e ripetuta con PATHpinned29PASS/0skip. Language guard ha rifiutato anche Dockerfile.txt: ricetta rinominata build_recipe.txt con gli stessi byte; guard invariato. I referti CI preesistenti generati da script sono stati tutti ripristinati, checksum approvato incluso.


## 2026-10-08T16:32:32.334323+00:00 — FUSEKI local identity: integrazione del GO indipendente

- Unità FUSEKI-LOCAL-IDENTITY-AFTER-CI-EXERCISE:integration, baselineef58743adebe717113832da1094224e5117d1c48, worktree isolato. GO esatto1e808f3824a3fae42bf279ea3e05a8f3d71dfe13, requestFUSEKI-LOCAL-IDENTITY-AFTER-CI-EXERCISE-1e808f3824a3-0, SHA256f45427b97fe40cf4d58155324bc925bca0b26176520b3f063f4ef8444e27a970, verifier Claude Code/Anthropic claude-opus-5-5, implementatore Codex/OpenAI; fornitori/processi/contesti separati. Nessun verdetto scritto o modificato.
- Sigillo candidato e otto riqualifiche, raw/input invariati, originali superseduti preservati. Nessun nuovo completed; ledger63,0049PR176 e REM17PR169WIP invariati. CI esatta pending; nessun merge o bypass prima dei13 check verdi.
- Tre finding low non bloccanti conservati: ricettaCOPY REM17 distinta dal Dockerfile main, rawJSON cache da archiviare nelle prossime acquisizioni, sola allowlist planning modificata; checker/validator lock e bootstrap invariati. Companion lock conserva stato al momento dell’acquisizione; sigillo nel record assurance. Nessuna rebuild-equality asserita.
- Preflight digest8/8, harness14 PASS, toolchain9/9, drift0/167; bootstrap/init/fixture/health PASS. Init/fixture avviati prematuramente mentre bootstrap ancora in background: FAIL conservati, retry unico in sequenza dopo completamento PASS. Printerhealth KeyError dopo PASS e lookup iniziale supersedes errato senza scritture registrati, nessun PASS dai tentativi falliti.
- E1=0/E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO invariati. Nessuna riparazione0049 o qualificaREM17.

- Gate del sigillo: RCCAD PASS_LOCAL_PRECHECK/CI_REQUIRED, drift0/167, scope/language/ruff/evidence PASS, mypy strict69 sorgenti PASS dopo sync frozen test/lint (prima modulo assente NOT_EXECUTED), piano37 PASS/2 tool opzionali NOT_EXECUTED. Tutti input e originali superseduti invariati; nessun nuovo test o codice modificato dal sigillo.


## 2026-10-08T16:52:37.764781+00:00 — State sync FUSEKI identity dopo PR179

- PR179 integrata con --merge --match-head-commitb5b54d05ff079fe9fbfa7d3118c2267dd662095e, merge6b407b0f62042ba8eb787948c111b7b50d86967a verificato su origin/main.13/13 check obbligatori SUCCESS esatti, run[37809815786, 37809815847, 37809815865, 37809815872, 37809815873, 37809815950], osservazioneSHA25657ad1baa90363fc6ae344fe2fd845edbad2994c744a45eb55eac840f786baf7f. Regole server attive23412233, nessun bypass. Tutti sigilli/raw/input invariati dopo merge, originali superseduti preservati.
- FUSEKI-LOCAL-IDENTITY-AFTER-CI-EXERCISE RESOLVED, ledger63 invariato. GO Claude Code/Anthropic claude-opus-5-5, implementatore Codex/OpenAI; tre finding low non bloccanti e limiti di ricetta/cache conservati. Nessuna riqualifica o riparazione0049/REM17 qui. Integrazione (attesa CI, merge, state sync) eseguita da Claude Code come implementatore di riserva del loop per quota Codex esaurita: stesso fornitore del verifier di questo change set, operazione meccanica senza modifica di codice o evidenza; sigilli ricontrollati prima del merge (10/10 invariati).
- Teardown scopedPASS, zero container/volumi/retiocor-bootstrap residui. Pronto0050/G5 secondo backlog;0049PR176/REM17PR169 aperte e non completate, G6 resta dipendente da REM17. Primo passo successivo riacquisisce CI e stato dei branch, senza retry invariato. E1/E2/Verified0 e NO-GO invariati. CI di questo state sync da attendere sull’HEAD esatto, nessun PASS trasferito dal sorgente.


## 2026-10-08T18:33:57.384748+00:00 — OCOR-DEV-0050 repair1: replay payload e traceability

- Baseline46ba54c0d1449b8a58f9b9bafda17df47919828e; ripresa worktree0050 pulita da fbe1aa20668742e5000d4350667929419225e9ff. Implementazione originale Claude Code di riserva (codice61e543a, evidenzafbe1aa2, 2026-10-08); verdetto Cursor/Grok4.7 OCOR-DEV-0050-fbe1aa206687-0 NO_GO/VF-001,VF-002high. Questa riparazione è Codex/OpenAI; verifier Cursor/Grok4.7 in processo/contesto separati perché il task è stato toccato dalla riserva. Nessun verdetto scritto/simulato.
- RED10FAIL/2PASS/186deselected, exit1, SHA256fe4780d576b103f44a61069c6b8ba6f483f7867944c896983d06d67607f8c7e8. GREEN finale198PASS/zero skip. Tentativo GREEN iniziale9FAIL/189PASS: errore nel nuovo test (records() assente sul journal), corretto usando byte/righe reali; raw preservato fuori Git. Non è un PASS.
- VF-001: prima della receipt idempotente stesso key/item digest, validazione content class/type/digest/pattern vietati. Positivi e negativi su journal durevole riaperto: payload alterato/vuoto/segreti/chiave/token/hidden reasoning/tipo invalido/registry non ammesso rifiutati, receipt originale su byte identici; zero scritture e journal byte-identico. Key/conflict/lineage invariati. Code29491c8; finale candidato45b5620390729dad9b4c5d647c3a1e7eb923a7cd, ciclo1 di budget2.
- VF-002: matrice kind/scope, unsupported pair e journal immutabile riferiti alla porzione memory FR-140. Nessun PASSBR-003; mission thread G6/BR-003.json NOT_EXECUTED qui. Nuovi hash/raw/meta ricalcolati sul codice finale, candidato storico non sigillato preservato inGit. NFR-025/075 non qualificati; nessuna chiusura di requisiti.
- Primo FULL1299PASS/zero skip377.78s ma wrapperFAIL18volumi anonimi; esito storico non qualificante preservato. Prima rimozione si è fermata senza mutazioni per container storici exited; ri-verificato scope, rimossi solo18ID unmounted creati nella finestra della sessione, baseline preservata. Qualifica ripetuta con recorder continuo create/mount REM17bc811af e teardown esatto; difetto test-level resta REM18OPEN, non risolto da questo task.
- FULL{'errors': 0, 'failures': 0, 'skipped': 0, 'tests': 1299} in372.86s, extras test/lint, tutte tests/ senza esclusioni. Reset→bootstrap→init→fixture→SVID→health11READY; immagini pinned e toolchain9/9 verificati, nessun riavvio/OOM; teardown zero delta container/volumi/reti, foreign preservati. Input8/8, harness14PASS, drift0/167, ruff/mypystrict/linked suites/scope/language/evidenza PASS; RCCAD precheck con dynamicCI_REQUIRED; piano37PASS/2optional NOT_EXECUTED. Nessun checker/workflow/soglia alterato.
- Ready set dalle63completed['OCOR-DEV-0049', 'OCOR-DEV-0050']; ledger invariato. PR169 snapshotbc811af ora13/13required SUCCESS (observationSHA256bea7a0b3b7e96e7c89f3ece0d2d170e32efcd3f975f8ae693c961fb29474a14a), qualifica indipendente REM ancora pending; PR176df444af resta aperta/CI3FAIL. PR180 già integrata in46ba54c con13/13PASS. Nessuna riparazione0049 o chiusuraREM17 eseguita.
- Mypy iniziale exit2 per cwd ocor-runtime incompatibile coi path relativi del pyproject di root; invocazione corretta dalla root, stesso strict/gate, raw storico preservato. Nessun FAIL convertito inPASS.
- Piano iniziale36PASS/1FAIL/2optional NOT_EXECUTED perché referti/checksum rigenerati sporchi fuori scope; patch/raw preservati e byte ripristinati prima del retry37PASS/2NOT_EXECUTED (markdownlint/mmdc). Nessuna allowlist/guard modificata.
- State sync separato limita le scritture a EXECUTION_STATE/MODEL_HANDOFF/ITERATION_LOG; reference candidato nel branch, nessun artifact assente su main dichiarato presente. Nessuna task PR prima del GO. Richiesta esternaOCOR-DEV-0050-45b562039072-1 dopo gate/push e syncCI esatta; E1=0/E2=0/Verified0, runtimeNOT_ESTABLISHED/PoC e ProductionNO-GO invariati. CONTINUE.


## 2026-10-09T02:41:30.901018+00:00 — OCOR-DEV-0050: sigillo indipendente e integrazione bloccata dalla CI

- Baseline a184c344fcbbd667e588b7da2595f5efe2b0b824, candidato accettato 45b5620390729dad9b4c5d647c3a1e7eb923a7cd, sigillo 8e0cc2fdda112a1ab19c42f0570b55179e572812, PR182 aperta e NON mergiata. Verdetto OCOR-DEV-0050-45b562039072-1 GO_FOR_EVIDENCE_SEAL senza finding, SHA256 df26cd0b7157ab6ed65f3d8eae1fcd1ed643178304456a1acff007f5c199e762. Implementazione originale Claude Code di riserva, riparazione1/integrazione Codex; verifier Grok4.7 via Cursor, contesto/processo/fornitore separati. Nessun verdetto scritto o simulato.
- Sigillo cambia soli metadati record e hash manifest; codice, inputs, raw e ogni evidenza preesistente byte-identici. Record sigillato SHA256 b427741be5b7c1b88898dd3400365546f8dde41914ad9c6ba4740942786e1dad. Preflight8/8, harness14PASS, toolchain9/9, bootstrap/init/fixture/health PASS; ruff/mypy strict/scope/language/drift/evidence/RCCAD precheck PASS; piano37PASS/2optionalNOT_EXECUTED. Suite task198/full1299 gia accettate dal verifier, non ripetute per il solo sigillo.
- CI esatta 8e0cc2fdda112a1ab19c42f0570b55179e572812: supply-chainFAIL, run37875427535, tre match su fixture sintetici del test0050 (PRIVATE_KEY rr.670/955, AWS_ACCESS_KEY r.671); scanner reportSHA256 695edaa35844646890c6d2d19b37ab981b589a28b480fa9e66ebd9c4753ac1ee. Nessuna credenziale operativa e nessun secret nuovo. RestoCI nella snapshot: 9/13PASS, pending['delivery-activation', 'rccad-methodology', 'validation-closure'], failed['supply-chain']; nessun check pending dichiaratoPASS. Nessun rerun del difetto deterministico, nessun bypass.
- Correzione non iniziata: prossima unita di riparazione2 con payload generati a runtime byte-identici, medesimi negativi/reason/casi, gate scanner invariato. Nuovo record di riqualifica con supersession su branch governato dedicato per preservare immutabilita dei sigilli e scope; nuova richiestaCursor/Grok sul finale. Non si sovrascrive il record sigillato. Nessuna decisione normativa necessaria, nessuna riparazione0049 o qualificaREM17.
- Invocazioni non qualificanti conservate: primo nohup non concluso; ruff venv assente due tentativi e mypy modulo assente NOT_EXECUTED; frozen extras sync e ruffpinned/mypy strict PASS. Piano dirtysealFAILdue tentativi; dopo commit baseesattaPASS, patch dei referti archiviata e byte ripristinati. Teardown scopedPASS, zero residui bootstrap/sessione; main pulita.
- Ledger63 invariato, ready['OCOR-DEV-0049', 'OCOR-DEV-0050']; G6 resta bloccato daREM17. State sync separato solo3file, gate/CI esatta da attendere. E1=0/E2=0, zeroVerified, runtimeNOT_ESTABLISHED, PoC/ProductionNO-GO invariati. CONTINUE.


## 2026-10-09T03:06:49.489804+00:00 — OCOR-DEV-0050 repair2: fixture sintetiche e riqualifica immutabile

- Baseline mainf0d684a834017614e3437ff08d43648f43fae3b9; unica unità repair2 (ultimo ciclo ordinario), branch governato da sigillo8e0cc2f. Implementatore Codex/OpenAI, originale Claude Code di riserva; verifier Grok4.7 via Cursor, processo/contesto/fornitore separati. Verifica demandata al loop, nessun verdetto scritto o simulato.
- RED dello scanner originale: exit1/3 finding, fingerprint 6de5e7b2f40d4ab0c59214a474a30de52d3210cf7f98f13b688a867e2d53d4f0; GREEN exit0/0 finding. Tre espressioni assemblano i payload a runtime: stessi byte SHA256, reason code e198 node ID. Scanner/workflow/checker lock e model.py invariati; nessuna esclusione, soglia o criterio ridotto.
- Task198 PASS/zero skip; FULL{'errors': 0, 'failures': 0, 'skipped': 0, 'tests': 1299} in367.71s, extras test/lint, Postgres reale, tutte tests/ incluse0048. Reset/bootstrap/init/fixture/SVID/health11READY; toolchain9/9, digest8/8, harness14PASS, portfolio documentale/lint/mypy strict70 file/drift/scope/evidenza PASS. Piano37PASS/2 optional NOT_EXECUTED; RCCAD precheck con dynamicCI_REQUIRED. Stack invariato, nessun OOM/restart, teardown ownership zero delta e baseline/foreign preservati.
- Codeb6b9f141ff0fec56e1fc8598d9ed9b9c8c903720; candidato88ed051dad5448f525680854025e79e4f161bceb, record8c2005e99673260e88d52c913cb51633b4840f1cce4050d271634360bf4de132, raw88f723345441c04c179b767876afc74df38cb0fc19bb21f1f4c8ebe63f6820b0. Nuova riqualifica supersedes29491c874905660314f2fd366fefb64a55ec8775; sigillo0050 b427741be5b7c1b88898dd3400365546f8dde41914ad9c6ba4740942786e1dad e rawstorico byte-identici. Manifest reindirizzato soltanto ai nuovi file; allowlist +3path e self-hash aggiornato, logica dei validator invariata. Checker meccanico self-contained nel record ricalcola input/tree/raw/JUnit/environment/supersession/manifest: non è verifica indipendente.
- PR182 resta aperta,12/13required PASS e solo supply-chainFAIL, run[37875427535, 37875427538, 37875427540, 37875427565, 37875427566, 37875427602, 37875427628]; nessun rerun deterministico o merge. Nessuna nuova PR del candidato prima delGO; state sync separato3file. Ledger63 invariato, ready['OCOR-DEV-0049', 'OCOR-DEV-0050'];0049/REM17 non riparati o chiusi qui.
- Invocazioni non qualificanti: prima shell background terminata senza avviare la campagna (logvuoto), rilancio tramite sessione persistente; primo anchor della patch allowlist assente, riletto e applicato senza mutazioni nel tentativo fallito. NOT_EXECUTED preservati. Il piano finale aveva36PASS/1FAIL/2optionalNOT_EXECUTED per il manifestG5 mancante nella allowlist: FAIL conservato, aggiunta esatta del manifest già autorizzato e retry verde senza alterare la logica. JSON stato canonici; claimsE1/E2/Verified0 e runtimeNOT_ESTABLISHED/PoC/ProductionNO-GO invariati.
- Prossima azione: Attendere il verifier esterno Grok4.7 via Cursor per OCOR-DEV-0050-88ed051dad54-2, HEAD esatto 88ed051dad5448f525680854025e79e4f161bceb. GO: sigillare soltanto la nuova riqualifica su governed/ocor-dev-0050-synthetic-secret-fixtures, aprire PR governata sostitutiva di182 (preservare sigilli storici), attendere13 check richiesti verdi su HEAD esatto, merge --match-head-commit e state sync. NO_GO: budget2 esaurito, escalation del solo0050, proseguire con REM17/lavoro pronto senza nuova riparazione. Poi qualifica REM17bc811af e integrazione0049 subordinata a chiusura verificataREM17; nessuna riparazione0049.

## 2026-10-09T04:22:57Z — OCOR-DEV-0050 integrazione: sigillo e merge (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita; ripresa dallo stato versionato e da `~/.ocor-codex/integrate0050r2` (seal Codex `79a7912`, PR #185 aperta). Verdetto `OCOR-DEV-0050-88ed051dad54-2` GO_FOR_EVIDENCE_SEAL, verifier Grok 4.7 via Cursor CLI (processo/contesto/fornitore separati), sha256 `c55f33c55012dbfd86e2610b037d0c65eca93995e63b56a45da309e3f78ffe21`. Riparazioni 1–2 Codex, implementazione originale Claude Code.
- Fallimento reale osservato: PR #185 `tooling-policy` FAIL (piano 36 PASS/1 FAIL, `authorized planning-only diff` su `model.py`, test, `OCOR-DEV-0050.json/.log`). Causa: sui branch `governed/` il piano confronta con `BASE_SHA` e i file posseduti dal task non sono in allowlist; il precheck locale usava `--base-ref HEAD`. Nessuna modifica a validator o allowlist: avrebbe cambiato un input sigillato della riqualifica.
- Integrazione in due PR, nessun byte verificato modificato: #182 (`task/`) fast-forward a `5660ce6366e214f572fa46daf3a3f2e0141db6ae` (antenato dell'HEAD verificato, solo il test riparato), gate locali verdi (digest 8/8, RCCAD, scope task, language, piano, evidence, drift, scanner supply-chain originale 0 finding, 198 test), 13/13 required, merge `bf33012939fcb6252ca31db136a2db0548eb861f`. Poi #185 sull'HEAD invariato `79a79120a75956f8a479e779fad962b65b77378f`, 13/13 required, merge `e459cd1dc99c9ee9f88e2644b0b7273e2fb44c4f`. Albero `bf33012939fcb6252ca31db136a2db0548eb861f` uguale alla simulazione locale del merge (piano 37 PASS, RCCAD, scope, drift PASS).
- Eventi PR rigenerati con chiusura/riapertura: il `base.sha` del payload restava stale (#182: `a184c34`, `delivery-activation` FAIL per file di stato di main nel three-dot; #185: `4f361c2`). Un riapertura non basta, serve la seconda; run stale annullati, non usati come qualifica. CI #182 [37882091473, 37882091485, 37882091524, 37882091540, 37882091574, 37882091584, 37882091617]; CI #185 [37882797373, 37882797410, 37882797417, 37882797440, 37882797510, 37882797512, 37882797526].
- Su main: sigilli 0048/0050 e Fuseki, riqualifica `3441ba1d36568d296fa64d66c1174c07e832056b2f27f6221dc05ee2acc2a8c6`, raw `88f723345441c04c179b767876afc74df38cb0fc19bb21f1f4c8ebe63f6820b0`, manifest G5 `82adfc919120728935eb2fb368e8567f3d6058e1b13b62ac0f508012202dc765`, input e `inputs_tree` `60a73de8…` invariati. `completed_evidence_tasks` 64 (+OCOR-DEV-0050); blocker `OCOR-DEV-0050-CI-SYNTHETIC-FIXTURES` RESOLVED. Ready: OCOR-DEV-0049 (integrazione subordinata a REM-0017), OCOR-DEV-0051.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, nessuna riparazione 0049, nessuna chiusura REM-0017/REM-0018.
- Prossima azione: OCOR-DEV-REM-0017: qualifica del candidato bc811af (PR #169 draft, governed/ocor-dev-rem-0017-ci-provision-spire) secondo REM-0017-PRIORITY/REM-0017-CI-ARCHIVE-ACQUISITION/REM-0017-CI-CAMPAIGN-BUDGET (coppia di run CI autorizzata, 75/45 min, arresto su OOM/riavvio), poi verifica indipendente; integrazione OCOR-DEV-0049 (GO b14e4bf, PR #176) subordinata alla chiusura verificata di REM-0017, nessuna riparazione 0049. Se REM-0017 resta in attesa di un evento esterno: OCOR-DEV-0051:implementation (pronto: hard_dependencies 0023/0025/0050 completate). RVW-03, INFO-A, INFO-C, REM-0018 restano aperti e non bloccano G5.

## 2026-10-09T11:44:03Z — REM-0017: candidato riallineato oltre il tetto CI su entrambi i tentativi (Claude Code, riserva)

- Implementatore di riserva Claude Code (quota Codex esaurita). Registra l'esito della qualifica del candidato REM-0017 riallineato a main `7b63f61` (merge `730759b`; riqualifiche 0050/0075 sul branch; codice REM repair-1 di Codex). L'iterazione precedente è stata interrotta manualmente il 2026-10-09T08:07Z prima di registrare il secondo tentativo; nessuna richiesta di verifica è stata scritta.
- HEAD intermedio `f55b2107d62bc6614d849e117cc261764326cf32` verde: candidato 0049 `df444af` 1491 PASS/zero skip in 3183.2 s, main 1299 PASS senza l'`--ignore` della PR #164. Non qualifica l'HEAD riallineato.
- HEAD esatto `741279862edae172fd8c1b16b584c1852145f7ae` (PR #169 draft), run `37890969702`: tentativo 1 (2026-10-09T05:56:24Z–2026-10-09T07:15:00Z) e rerun autorizzato (2026-10-09T07:15:55Z–2026-10-09T08:34:48Z) entrambi FAIL con "75-minute campaign limit reached": JUnit parziale 1382/1491 e 1382/1491 PASS, zero fail/error/skip, 4505.97 s e 4511.052 s; nessun riavvio/OOM di containerd/kubelet; `validation-closure` FAIL per dipendenza non riuscita (12 altri required verdi). Casi più lunghi: Helm/CronJob 1155.6 s, tombstone locale-indipendenti [7-7] 389.1 s. Teardown dopo l'arresto al tetto: una rete residua e `docker ps` in timeout (FAIL, registrato; REM-0018 resta aperto).
- Coppia di run autorizzata consumata: nessun ulteriore run, nessuna variazione del tetto, nessun caso escluso. Blocker `REM-0017-CI-CAMPAIGN-DURATION` portato a `OPEN_PO_DECISION_REQUIRED` (misure 4200.959/4425.920/3183.205 s e due FAIL al tetto), blocca REM-0017, integrazione 0049 e G6; `REM-0017-KIND-CONTAINERD-CRASH` OPEN, non bloccante (solo host locale). Le DR restano sul branch `governed/ocor-dev-rem-0017-ci-provision-spire`: aggiungerle a main richiederebbe di modificare l'allowlist di piano, input sigillato della riqualifica di 0050.
- Raw (fuori repository, SHA-256): artifact tentativo 2 `a64d844bca70f9e364258bf0281936c6bcfb1b1fec5df8c9f5dd6290710ee0b6`, log job `d394a92a8906f9a9e02246d234c8d306fe3dd490e1d4382cb8024ccd5a76f730`, rollup `3c998f814823274aeb63c401af4dee6fe321fe717ec96ab1d8da40dd1f045de5`.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a PR #169 o a PR #176.
- Prossima azione: OCOR-DEV-0051:implementation (pronto: hard_dependencies 0023/0025/0050 completate), branch task/ da origin/main in worktree nuovo. OCOR-DEV-REM-0017 fermo su decisione PO REM-0017-CI-CAMPAIGN-DURATION: candidato riallineato 7412798 (PR #169 draft) ha superato il tetto di 4500 s su entrambi i tentativi CI autorizzati (1382/1491 PASS, zero fail/skip, nessun riavvio/OOM); nessun ulteriore run, nessuna variazione del tetto, nessuna verifica richiesta su un HEAD con CI rossa. Integrazione OCOR-DEV-0049 (GO b14e4bf, PR #176) resta subordinata alla chiusura verificata di REM-0017, nessuna riparazione 0049. RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5.

## 2026-10-09T14:40:20Z — OCOR-DEV-0051: implementazione, riparazione 1, sigillo e merge (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita, cicli 0 e 1 e integrazione; verifier Grok 4.7 via Cursor CLI (processo, contesto e fornitore separati). Lo stato su main non era stato aggiornato durante le verifiche per lasciare invariato il remoto: questa voce registra i cicli 0 e 1.
- Ciclo 0: store reali di metadata e indice lessicale (PostgreSQL), contenuto cifrato con OpenBao transit e indirizzato per contenuto, proiezione vettoriale su Qdrant; verdetto `OCOR-DEV-0051-e5c49f2dc7d7-0` NO_GO (sha256 `eb33109211512ff5aeeaeacc2c275dc50f712517316832ed6e3c72e8e9ea9827`): VF-001 read-back limitato al payload del pointer; VF-002 rifiuto del plaintext nel ciphertext solo da 16 byte.
- Ciclo 1 (codice `4eed73f70ea7f27e0dbc4d7edd2ed79dda680812`): read-back del corpo indicizzato (documento con tsvector derivato; vettore binary32 legato a `embedding_digest`) in commit, reconcile e read_version; rifiuto del plaintext a ogni lunghezza con reseal limitato e apertura obbligatoriamente fallita sotto contesto estraneo. RED 15 fail sul codice non riparato; task 64/64 x3 + uv, zero skip, zero residui; mutanti 22/22; suite completa 1363/0 skip (18 volumi cp-kafka REM-0018 attribuiti e rimossi). Verdetto `OCOR-DEV-0051-69d80f2d843e-1` GO_FOR_EVIDENCE_SEAL su `69d80f2d843e48a5f8648b1dba9c4ac6d030409f`, nessun finding e nessun NOT_EXECUTED (sha256 `c2fc97c1de45d87e98d6b4eaf1645ae3850c2caec4382d200b0181b1a59d5b11`).
- Integrazione: sigillo `cc1d53a858469a7a547fe20fd7264eb8d0e299cc` (solo `independent_verification`, `sealed_at`, `status: SEALED` e hash nel manifest G5). Gate locali sul sigillo: digest 8/8, harness 14 PASS, ruff 0.13.1, mypy strict 71 file, RCCAD precheck, scope task 5 path, language, piano `--base-ref HEAD` 37 PASS/2 NOT_EXECUTED opzionali, drift 64 task/0, evidence `--non-skipped`, controllo riproducibile dell'evidenza PASS. PR #188, 13/13 required sull'HEAD esatto (run [37943402246, 37943402250, 37943402254, 37943402259, 37943402262, 37943402286, 37943402376]), merge `0f76347213bc76a5ced53ada485fd5a852b0f8fc` con `--match-head-commit`.
- Su main: record `2c0932a03e2b9e256efa3948d76a42a0c4d2bd82bc817301761cd696dee07e44`, raw `362e334d9e6db432bdae0809efbc4bf8092428317dac953d20f9eef144624e80`, manifest G5 `ae4dd7c4dc791478519e08ac583261817e9c0cc0dc0523743ce0bf4fd3e06c96`; sigilli 0048/0050 invariati. `completed_evidence_tasks` 65 (+OCOR-DEV-0051). Ready: OCOR-DEV-0049 (integrazione subordinata a REM-0017), OCOR-DEV-0052, OCOR-DEV-0053.
- Decisione PO REM-0017-CI-CAMPAIGN-DURATION (2026-10-09) registrata come ricevuta: blocker REM-0017-CI-CAMPAIGN-DURATION, REM-0017-KIND-CONTAINERD-CRASH e OCOR-DEV-REM-0017 portati a PO_DECISION_RECEIVED_EXECUTION_PENDING; esecuzione e chiusura della DR nel change set REM-0017.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a gate o workflow, a PR #169 o #176.
- Prossima azione: OCOR-DEV-REM-0017: implementare la decisione PO REM-0017-CI-CAMPAIGN-DURATION (2026-10-09) sul branch governed/ocor-dev-rem-0017-ci-provision-spire (PR #169 draft, head 7412798): suite completa di rccad-methodology, delivery-activation, validation-closure e conditional-infrastructure-0049 in N>=2 parti parallele (partenza 3) con partizione deterministica, stack completo per parte, zero skip, teardown fail-closed, arresto su riavvio/OOM; job aggregatore con il nome del check obbligatorio che confronta i JUnit con pytest --collect-only (nessun mancante/duplicato, zero skip/fail/error); tetto 45 min per parte in CI (oltre 30 min aumentare N); ruleset 23412233 invariato; chiudere la DR REM-0017-CI-CAMPAIGN-DURATION come risolta; poi la coppia di run CI autorizzata e la verifica indipendente. REM-0017-KIND-CONTAINERD-CRASH: diagnosi secondo l'opzione 1, senza cambi di immagine o versione. Integrazione OCOR-DEV-0049 (GO b14e4bf, PR #176) subordinata alla chiusura verificata di REM-0017. Se REM-0017 resta in attesa di un evento esterno: OCOR-DEV-0052:implementation (pronto: hard_dependencies completate; 0053 pronto). RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5.

## 2026-10-09T17:37:20Z — REM-0017: suite in parti parallele attuata, unità 0049 oltre il tetto per parte (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5; quota Codex esaurita). Decisione PO REM-0017-CI-CAMPAIGN-DURATION attuata sul branch `governed/ocor-dev-rem-0017-ci-provision-spire` (PR #169 draft, head `7d8e0fd`): parti deterministiche con selezione verificata, aggregatori con i nomi dei check obbligatori che confrontano l'unione JUnit con `--collect-only`, 3 parti per job, ruleset invariato. DR chiusa come risolta.
- Primo run CI (`4e97cd3`): lo split per singolo test ha rotto lo stato d'ordine di `test_ocor_dev_0049` (parti 2–4 FAIL, Helm PASS); correzione `12836ed` con moduli interi e solo il caso Helm separabile. Non qualificante.
- Run sull'HEAD corretto `99f9ee5` (37961535016/37961535129/37961535168): tutto verde tranne il job 0049: resto del modulo 0049 388/389 PASS, zero fail/skip, fermato al tetto di 45 minuti (2716 s); Helm 1106 s PASS; altri moduli 445 s PASS; aggregatori fail-closed. Push di sola documentazione `7d8e0fd`: run cancellati.
- Nuovo blocker `REM-0017-CI-0049-REMAINDER-CAP` (OPEN_PO_DECISION_REQUIRED): tetto specifico per l'unità indivisibile 0049 (raccomandato) o correzione dell'isolamento dei test 0049. Nessuna richiesta di verifica inviata; nessun test, tetto o criterio cambiato.
- Locale sulla ricetta CI: suite principale 1363 PASS in 3 parti con unione esatta; candidato parte 1 389 PASS in 1780 s e parte 3 1101 PASS; riqualifica 0050 (allowlist del piano) 198 PASS. Volumi anonimi di sessione (REM-0018) rimossi solo se non montati.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`.
- Prossima azione: OCOR-DEV-0052:implementation (G5, pronto).

## 2026-10-09T18:05:00Z — Presa d'atto PO sul vincolo d'ordine di 0049: registrazione OCOR-DEV-REM-0019 (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5; quota Codex esaurita). Change set di solo stato.
- Presa d'atto PO (2026-10-09) sull'addendum di REM-0017-CI-CAMPAIGN-DURATION registrata: modulo `test_ocor_dev_0049.py` indivisibile in CI in ordine di collezione, caso Helm in parte propria, partizione a 3 parti accettata. La parte "0049 senza Helm" oltre 45 minuti e' FAIL con richiesta di decisione: la misura (2716 s, run 37961535016) e' gia' registrata nel blocker `REM-0017-CI-0049-REMAINDER-CAP`, che resta OPEN_PO_DECISION_REQUIRED; nessun tetto alzato.
- Nuova voce di remediation `OCOR-DEV-REM-0019` (primo ID libero verificato con grep su tutti i ref): dipendenza d'ordine fra i test di 0049, obiettivo test eseguibili da soli e in qualsiasi ordine senza cambiare comportamento, casi o criteri; esecuzione subordinata a decisione PO dedicata; dipendenza dei task G6 (0060-0066), non blocca G5.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, test, gate o PR #169/#176.
- Prossima azione: OCOR-DEV-0052:implementation (G5, pronto).

## 2026-10-09T19:21:21Z — OCOR-DEV-0052: implementazione, sigillo e merge (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita, ciclo 0 e integrazione; verifier Grok 4.7 via Cursor CLI (processo, contesto e fornitore separati). Lo stato su main non era stato aggiornato durante la verifica per lasciare invariato il remoto: questa voce registra anche l'iterazione di implementazione.
- Implementazione (codice `8865203f6a557d4dccb4d2cd60059c37b057e7fe`): `memory/retrieval.py`, MemorySearchService policy-first STRUCTURED/FULL_TEXT/VECTOR/HYBRID: richiesta chiusa OpenAPI, partizioni autorizzate derivate prima del lookup, rivalidazione per candidato prima della materializzazione, fattori hybrid separati, ricontrollo dello stop epoch, ricevuta di audit che fissa query, rappresentazione, ranking, filtri e versioni esatte. Task 65/65 x3 + uv su PostgreSQL/Qdrant/OpenBao reali, zero skip, zero residui; mutanti 23/23; suite completa 1428/0 skip (18 volumi cp-kafka REM-0018 attribuiti e rimossi).
- Verdetto `OCOR-DEV-0052-a0a80c27172e-0` GO_FOR_EVIDENCE_SEAL su `a0a80c27172eb7e25cd6cc5992fb8d7e9dc1e045`, nessun finding e nessun NOT_EXECUTED (sha256 `0c602a649486191161765c84ebce6a7bc772d197fa61c3074efe0c71c627ccfd`). Nota del verifier: 8 fallimenti di test_ocor_dev_0007 nella sua prima suite completa dovuti al node v24 del proprio PATH; 51/51 con il node pinnato v20.20.2.
- Integrazione: sigillo `69542197e3ea67281d690a385ebbb63f658b89c4` (solo `independent_verification`, `sealed_at`, `status: SEALED` e hash nel manifest G5). Gate locali sul sigillo: digest 8/8, ruff 0.13.1, mypy strict 72 file, RCCAD precheck, scope task 5 path, language, piano `--base-ref HEAD` 37 PASS/2 NOT_EXECUTED opzionali, drift, evidence `--non-skipped`, controllo riproducibile dell'evidenza PASS. PR #192, 13/13 required sull'HEAD esatto (run [37978456632, 37978456648, 37978456715, 37978456725, 37978456821, 37978457133, 37978457286]), merge `ae296eb15bcace031ffb14c8f6178522a842d014` con `--match-head-commit`.
- Su main: record `8a86ab09be0d43999187e84acceb98ff29b43380748b4d493290888c7d520209`, raw `acb97fe423eac481e1b51f8fe441015da6d09082f4c82d0f57c795671e18efe2`, manifest G5 `c439c2a19896ff25adb82b7a3ebc462f3f60d1302adfabf7936b05ffafeecc4b`; sigilli precedenti invariati. `completed_evidence_tasks` 66 (+OCOR-DEV-0052). Ready: OCOR-DEV-0049 (integrazione subordinata a REM-0017), OCOR-DEV-0053, OCOR-DEV-0054.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a gate o workflow, a PR #169 o #176.
- Prossima azione: OCOR-DEV-0053:implementation (G5, pronto: hard_dependencies 0023 e 0051 completate; 0054 anch'esso pronto), branch task/ da origin/main in worktree nuovo. OCOR-DEV-REM-0017 fermo su decisione PO REM-0017-CI-0049-REMAINDER-CAP (presa d'atto PO 2026-10-09 registrata; decisione sul tetto ancora richiesta). OCOR-DEV-REM-0019 (isolamento test 0049) aperto, dipendenza G6, esecuzione subordinata a decisione PO dedicata. Integrazione OCOR-DEV-0049 (GO b14e4bf, PR #176) subordinata alla chiusura verificata di REM-0017. RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5.

## 2026-10-10T01:18:02Z — OCOR-DEV-0053: sigillo e merge (implementatore di riserva Claude Code); registrazione di OCOR-DEV-REM-0020

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita, cicli 0, 1, 2 e integrazione; verifier di tutti i cicli Grok 4.7 via Cursor CLI (processo, contesto e fornitore separati). Lo stato su main non era stato aggiornato durante implementazione e riparazioni: questa voce registra anche quelle iterazioni.
- Implementazione e riparazioni: ciclo 0 codice `868b248`, candidato `bb19f79` -> verdetto `OCOR-DEV-0053-bb19f79af9ce-0` NO_GO (VF-001..VF-004: dinieghi non auditati, receipt prima del CAS, finestra di validita degli slot, residual errato); ciclo 1 codice `9ef7b3b`, candidato `1688386` -> `OCOR-DEV-0053-168838648549-1` NO_GO (VF-001..VF-003: attivazione non legata alla receipt, valid_at storico non passato alla lookup, correlazione dei dinieghi); ciclo 2 (ultimo del budget) codice `f6aaec95baaebe0f15fb0ef9a2911a7c2ceb9086`, candidato `69457e9b1b97861fb13f6b3c114f63aa3be73422`.
- Verdetto `OCOR-DEV-0053-69457e9b1b97-2` GO_FOR_EVIDENCE_SEAL su `69457e9b1b97861fb13f6b3c114f63aa3be73422`, nessun finding e nessun NOT_EXECUTED (sha256 `7b993807cacb1282103826630b9506b72b4c97e82c27452a52e26efc1c98335e`). Il verifier ha riprodotto task 90/90 e suite completa 1518/0 skip sullo stack pinned.
- Integrazione: sigillo `2392748c2cc44ed5c6a93d57a5ccd68e952da084` (solo `independent_verification`, `sealed_at`, `status: SEALED` e hash nel manifest G5). Gate locali sul sigillo: digest 8/8, ruff 0.13.1, mypy strict 73 file, RCCAD precheck, scope task, language, piano `--base-ref HEAD` 37 PASS/2 NOT_EXECUTED opzionali, drift, evidence `--non-skipped`, controllo riproducibile dell'evidenza PASS. PR #194, 13/13 required sull'HEAD esatto (run [38011791580, 38011791594, 38011791611, 38011791616, 38011791624, 38011791627, 38011791714]), merge `f40794c02ef88e3b62720621f27706cbd97a66ca` con `--match-head-commit`.
- Su main: record `b2fff2ce1ee2f5432ed24687ab3a1d016b707bd5427ce658bba62ec816a2ceec`, raw `e0b2072bd37ba3803e38f9c7aff21fcb1cc0325e47f24043bb2e2f5c14cc6c46`, manifest G5 `3af6c2c2dc679abacb36dce32b6a6b8d4178319cb66af331627b7768fe3c7d52`; sigilli precedenti invariati. `completed_evidence_tasks` 67 (+OCOR-DEV-0053).
- Registrata `OCOR-DEV-REM-0020` (primo REM libero verificato con git grep su tutti i ref) per la decisione PO `OCOR-DEV-0052-INDEPENDENT-REVIEW`: F1, F3, F4, F5, F6 di MemorySearchService, F2 tracciato verso FGM-16; blocca OCOR-DEV-0057 (e quindi 0058/0059 e la chiusura G5). Ready: OCOR-DEV-0049 (integrazione subordinata a REM-0017), OCOR-DEV-0054; unita selezionata: OCOR-DEV-REM-0020.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a gate o workflow, a PR #169 o #176.
- Prossima azione: OCOR-DEV-REM-0020 (remediation della decisione PO OCOR-DEV-0052-INDEPENDENT-REVIEW: F1, F3, F4, F5, F6 di MemorySearchService con test RED R2-R6 sui backend reali; F2 tracciato verso FGM-16), branch governed/ o task/ da origin/main in worktree nuovo; dipendenza obbligatoria di OCOR-DEV-0057 e della chiusura G5. Poi OCOR-DEV-0054 (pronto). OCOR-DEV-REM-0017 fermo su decisione PO REM-0017-CI-0049-REMAINDER-CAP; integrazione OCOR-DEV-0049 (GO b14e4bf, PR #176) subordinata alla chiusura verificata di REM-0017. OCOR-DEV-REM-0019 aperto (dipendenza G6, decisione PO dedicata). RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5.

## 2026-10-10T03:48:33Z — OCOR-DEV-REM-0020: implementazione, verifica, sigillo e merge (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita, ciclo 0 e integrazione; verifier Grok 4.7 via Cursor CLI (processo, contesto e fornitore separati). Lo stato su main non era stato aggiornato durante l'implementazione: questa voce registra anche quell'iterazione.
- Decisione PO `OCOR-DEV-0052-INDEPENDENT-REVIEW` (2026-10-09). Branch `governed/ocor-dev-rem-0020-memory-search-pushdown`: test RED `07f7dbf` (R2b, R3, R4 x2, R5, R6 falliscono su `2c110c1`; R2 letterale passa, documentato), codice `408eb1cb5c0e664047b025b2b4a42d0371c3ffbc` (port v2 di indici e metadata con predicati di idoneita nel WHERE PostgreSQL e nel payload filter Qdrant, ritiro delle proiezioni del predecessore, STRUCTURED top-k deterministico, backpressure solo sul limite dichiarato; fattori HYBRID reali sull'unione dei pool; stop epoch dopo ogni hit e prima della ricevuta; dinieghi auditati; casi F6), evidenza `4f1c4ef439a1c0fc6c2a42742c8069756373af8e` con riqualifiche 0050/0051/0052 (`supersedes` espliciti, record sigillati invariati). Task 476/476 x3 + uv, suite completa 1577/1577 zero skip, mutanti 19/19. F2 misurato invariato (1/6/15), tracciato verso FGM-16. OpenAPI pubblico invariato.
- Verdetto `OCOR-DEV-REM-0020-4f1c4ef439a1-0` (REMEDIATION) GO_FOR_EVIDENCE_SEAL su `4f1c4ef439a1c0fc6c2a42742c8069756373af8e`, nessun finding e nessun NOT_EXECUTED (sha256 `9f7c58a8ef2957e7bbcf46ea4f52996233f0268972bf85c57bc391464c29e970`); il verifier ha riprodotto task 476 e suite completa 1577/0 skip sullo stack pinned.
- Integrazione: sigillo `acfe06ef0ea123b6f20197cdc19c53c4a0ec9117` (solo `independent_verification`, `sealed_at`, `status: SEALED` dei quattro record, hash nel manifest G5 e nel record di remediation, riga di status del README). Gate locali sul sigillo: digest 8/8, ruff 0.13.1, mypy strict 73 file, RCCAD precheck, language, scope 17 percorsi, piano 37 PASS/2 NOT_EXECUTED opzionali, drift 0, evidence `--non-skipped` 0050-0053, controllo riproducibile PASS. PR #196, 13/13 required sull'HEAD esatto (run [38020615710, 38020615879, 38020615901, 38020616000, 38020617901, 38020618184, 38020618460]), merge `0c51c34a6e03a6ceda3d8c7a4e3749f49c8c18d4` con `--match-head-commit`.
- Su main: REM `0dbb1e40dd8a9e8ce02cf9eb0480f04b33430559d5d479b42a6683e472d1192e`, raw `df93b7d3226b457909195b18d6b262376363f6ea804b79bda10540663fa87286`, manifest G5 `654df681431766d83099ffdd146545baa2077d9a3fc305a90036809ead4f83e7`; sigilli precedenti invariati. `OCOR-DEV-REM-0020` chiusa: non blocca piu OCOR-DEV-0057. `completed_evidence_tasks` invariato (67).
- Ready: OCOR-DEV-0049 (integrazione subordinata a REM-0017), OCOR-DEV-0054; unita selezionata: OCOR-DEV-0054:implementation.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a gate o workflow, a PR #169 o #176.
- Prossima azione: OCOR-DEV-0054:implementation (pronto: hard_dependencies in completed_evidence_tasks), branch task/ da origin/main in worktree nuovo; poi 0055, 0056 e 0057 (sbloccato da OCOR-DEV-REM-0020 chiusa, dipende ancora da 0054 e 0055). OCOR-DEV-REM-0017 fermo su decisione PO REM-0017-CI-0049-REMAINDER-CAP; integrazione OCOR-DEV-0049 (GO b14e4bf, PR #176) subordinata alla chiusura verificata di REM-0017. OCOR-DEV-REM-0019 aperto (dipendenza G6, decisione PO dedicata). RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5. F2 tracciato verso FGM-16.

## 2026-10-10T05:45:43Z — OCOR-DEV-0054: implementazione, sigillo e merge (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita, ciclo 0 e integrazione; verifier Grok 4.7 via Cursor CLI (processo, contesto e fornitore separati). Lo stato su main non era stato aggiornato durante l'implementazione: questa voce registra anche quell'iterazione.
- Implementazione: `memory/consolidation.py` (MemoryConsolidationService consolidate/correct, claim-merge 1.0, ConsolidationProfile approvati, job ledger journal hash-chained, ConsolidationGuardPolicy) e `tests/tasks/test_ocor_dev_0054.py`; codice `fe2d0aa` + `aa3d158b5b3da95226a15b9a48a522a9494996fd`, candidato `058c9c4f7d39d5c88a61c40b8382e19ee7f1f4fa`. RED documentato (modulo assente), task 89/89 x3 + run uv sui backend reali, mutanti 45/45 uccisi, suite completa 1666/0 skip sullo stack pinned. Durante l'implementazione la CA SPIRE disposable della checkout principale risultava scaduta (notAfter 2026-10-08): rigenerata solo nel worktree, env principale non modificato.
- Verdetto `OCOR-DEV-0054-058c9c4f7d39-0` GO_FOR_EVIDENCE_SEAL su `058c9c4f7d39d5c88a61c40b8382e19ee7f1f4fa`, nessun finding e nessun NOT_EXECUTED (sha256 `67f66852ad0e991dc980e4028d400b54428ea063fd95798cb6dc045848499e41`). Il verifier ha riprodotto task 89/89 e suite completa 1666/0 skip.
- Integrazione: sigillo `29cf448d95e51fd13a66080ba719385b2bf5f054` (solo `independent_verification`, `sealed_at`, `status: SEALED` e hash nel manifest G5). Gate locali sul sigillo: digest 8/8, ruff 0.13.1, mypy strict 74 file, RCCAD precheck, scope task, language, piano `--base-ref HEAD` 37 PASS/2 NOT_EXECUTED opzionali, drift (176 input, 0 deriva), evidence `--non-skipped`, controllo riproducibile dell'evidenza PASS. PR #198, 13/13 required sull'HEAD esatto (run [38027741676, 38027741724, 38027741729, 38027741743, 38027741753, 38027741774, 38027741779]), merge `0724978e929b5c4288388a8d5894b125053b5c32` con `--match-head-commit`.
- Su main: record `3016cddfac0fbdc7a3131853462cf43f9d68df8dd7202b8bcbc11993eab869c6`, raw `3b8625382753f711a19e783af94ca7c16d1cbd9190fcdfc95efca7cf467047f1`, manifest G5 `c50bcc3a757f061c22876ed17f9b3fde47d3ad3bcb3499ad0e6940067fb4061d`; sigilli precedenti invariati. `completed_evidence_tasks` 68 (+OCOR-DEV-0054). Ready: OCOR-DEV-0049 (integrazione subordinata a REM-0017), OCOR-DEV-0055; unita selezionata: OCOR-DEV-0055:implementation.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a gate o workflow, a PR #169 o #176.
- Prossima azione: OCOR-DEV-0055:implementation (pronto: hard_dependencies 0050, 0051, 0054 in completed_evidence_tasks), branch task/ da origin/main in worktree nuovo; poi 0056 e 0057. OCOR-DEV-REM-0017 fermo su decisione PO REM-0017-CI-0049-REMAINDER-CAP; integrazione OCOR-DEV-0049 (GO b14e4bf, PR #176) subordinata alla chiusura verificata di REM-0017. OCOR-DEV-REM-0019 aperto (dipendenza G6, decisione PO dedicata). RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5. F2 tracciato verso FGM-16.

## 2026-10-10T09:34:58Z — OCOR-DEV-0055 ciclo 0 (NO_GO) e OCOR-DEV-REM-0021: implementazione, verifica, sigillo e merge (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita; verifier Grok 4.7 via Cursor CLI (processo, contesto e fornitore separati). Lo stato su main non era stato aggiornato durante implementazione e verifica di 0055 e REM-0021: questa voce registra anche quelle iterazioni.
- OCOR-DEV-0055 ciclo 0: candidato `38b7734bd97f6932f5c5f10d3d71047436b54daf` sul branch `task/OCOR-DEV-0055-retention-expiry-revocation-forgetting-legal-hold` (MemoryLifecycleCoordinator, FSM ADD v1.3 Part II §2.10). Verdetto `OCOR-DEV-0055-38b7734bd97f-0` NO_GO (sha256 `ee4f5e68ed6ce4efa8effe77ff66cf6106c731c1ce48d8307b9602eca483bf1a`): VF-001 (alta, stop epoch non ricontrollato subito prima dell'append), VF-002 (alta, revoca committata durante la lettura restituita come hit), VF-003 (media, `environment.branch` errato), VF-004 (bassa, rischio residuo dell'inferenza di appartenenza). Nessuna PR aperta per 0055.
- Decisione PO `OCOR-DEV-0055-VF002-REMEDIATION` (2026-10-10): VF-002 in `memory/retrieval.py`, fuori dalle `expected_file_areas` di 0055 e input sigillato di 0052, quindi remediation `OCOR-DEV-REM-0021` (primo REM libero verificato) su branch `governed/ocor-dev-rem-0021-retrieval-post-read-eligibility`: test RED `7c46daf` (28 `DID NOT RAISE`, 14 pass attesi), fix `ac7541b` (idoneita rivalidata prima e dopo ogni `read_version` e su tutti gli hit prima della ricevuta, `CANDIDATE_CHANGED` con diniego auditato; commento che distingue stop epoch e controllo di idoneita), allowlist piano `0e76db2ac62d9b0225e4badb9ba5d9155cb15b67`, evidenza `3845e4af0fc110aa3cc571e4517533d507c124c1` con riqualifiche 0050/0052 (`supersedes` espliciti, record sigillati invariati). Task 607/607 x3 + uv, suite completa 1708/1708 zero skip, mutanti 6/6. OpenAPI pubblico invariato.
- Verdetto `OCOR-DEV-REM-0021-3845e4af0fc1-0` (REMEDIATION) GO_FOR_EVIDENCE_SEAL su `3845e4af0fc110aa3cc571e4517533d507c124c1`, nessun finding e nessun NOT_EXECUTED (sha256 `9c8c01387ff21cc2e6238baea77882904555373bf1af53a08782d2160c0f8d67`).
- Integrazione: sigillo `7e49b640f01d538ae57f580bcfd72f8dac230f65` (solo `independent_verification`, `sealed_at`, `status: SEALED` dei tre record, hash nel manifest G5 e nel record di remediation, riga di status del README). Gate locali sul sigillo: digest 8/8, ruff 0.13.1, mypy strict 74 file, RCCAD precheck, language, scope 12 percorsi, piano 37 PASS/2 NOT_EXECUTED opzionali, drift 0, evidence `--non-skipped` 0050-0054, controllo riproducibile PASS. PR #200, 13/13 required sull'HEAD esatto (run [38040896375, 38040896379, 38040896383, 38040896385, 38040896395, 38040896403, 38040896427]), merge `98debb35d8e492650b2163e4fe7925d11d924f28` con `--match-head-commit`.
- Su main: REM `918685c8aa040813f2b31580d8990924ec8ab3ac2327671759eac7a648851f81`, raw `9c2720f3fc6e60d07c8f9a3906766db5f00b3c4ea0f73751418a015cd97bdfd8`, manifest G5 `59bedec4e3bcc4b7301f14ef3b02a5c45e74cabce79dc909315a0290b844b98f`; sigilli precedenti invariati. `OCOR-DEV-REM-0021` chiusa. `completed_evidence_tasks` invariato (68).
- Decisione PO `REM-0017-CI-0049-REMAINDER-CAP` (2026-10-10, opzione 2) registrata: nessun tetto speciale; REM-0019 (isolamento dei test di 0049, solo codice di test) prima delle nuove run CI di REM-0017. Blocker REM-0017-CI-0049-REMAINDER-CAP e REM-0019 portati a PO_DECISION_RECEIVED_EXECUTION_PENDING; la DR resta da chiudere sul branch di REM-0017.
- Ordine registrato: la decisione mette REM-0019 dopo l'unita in corso; l'unita in corso e 0055 (NO_GO, non un nuovo task), di cui REM-0021 era prerequisito. Quindi: 0055 riparazione ciclo 1, REM-0019, REM-0017, 0056-0059.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a gate o workflow, a PR #169 o #176.
- Prossima azione: OCOR-DEV-0055:repair cycle 1 (decisione PO OCOR-DEV-0055-VF002-REMEDIATION): sul branch task/OCOR-DEV-0055-retention-expiry-revocation-forgetting-legal-hold (head 38b7734) merge di origin/main con REM-0021 (nessun force-push), VF-001 (ricontrollo dello stop epoch subito prima dell'append, caso negativo live, finestra residua dichiarata verso FGM-17), VF-002 caso live in test_ocor_dev_0055.py con revoca tramite MemoryLifecycleCoordinator durante la lettura, VF-003 (environment.branch e hash), VF-004 (rischio residuo non assegnato, FGM-16 solo tra compartimenti); nuova richiesta di verifica (verifier Cursor/Grok). Poi OCOR-DEV-REM-0019 (decisione PO REM-0017-CI-0049-REMAINDER-CAP, opzione 2), poi OCOR-DEV-REM-0017, poi 0056-0059. Integrazione OCOR-DEV-0049 (GO b14e4bf, PR #176) subordinata alla chiusura verificata di REM-0017. RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5. F2 tracciato verso FGM-16.

## 2026-10-10T11:43:28Z — OCOR-DEV-0055: riparazione ciclo 1, sigillo e merge (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita, ciclo di riparazione 1 e integrazione; verifier Grok 4.7 via Cursor CLI (processo, contesto e fornitore separati). Lo stato su main non era stato aggiornato durante la riparazione: questa voce registra anche quell'iterazione.
- Riparazione ciclo 1 (decisione PO `OCOR-DEV-0055-VF002-REMEDIATION`): merge di origin/main `1584b5e` (REM-0021) nel branch `task/OCOR-DEV-0055-retention-expiry-revocation-forgetting-legal-hold` senza force-push; RED `ac17252`/`f9b1190`, fix `148325c` + `2d414d7bc3e1c770897e69d4a106dc789ed92c3e` in `memory/lifecycle.py` (VF-001: stop epoch riletto dopo la lettura del contenuto, subito prima dell'append; finestra residua non atomica dichiarata verso FGM-17, non chiusa); VF-002 coperto da REM-0021 con casi live del MemoryLifecycleCoordinator (revoca, expiry, supersession durante la lettura della ricerca) in `test_ocor_dev_0055.py`; VF-003 `environment.branch` corretto e hash ricalcolati; VF-004 rischio residuo aperto non assegnato (FGM-16 copre solo il caso tra compartimenti). Candidato `48705277f453d8574eb6fe66c1b035e2f8a506f1`: task 76/76 x3 + uv, mutanti 52/52, suite completa 1784/0 skip.
- Verdetti: `OCOR-DEV-0055-38b7734bd97f-0` NO_GO (sha256 `ee4f5e68ed6ce4efa8effe77ff66cf6106c731c1ce48d8307b9602eca483bf1a`); `OCOR-DEV-0055-48705277f453-1` GO_FOR_EVIDENCE_SEAL su `48705277f453d8574eb6fe66c1b035e2f8a506f1`, nessun finding e nessun NOT_EXECUTED (sha256 `e2f0285547177bc0fba52429f69955edb7f95e65cd68f8f9915909a15dd10474`). Cicli di riparazione consumati: 1 di 2.
- Integrazione: sigillo `73a28c44b3f8570847469d00275135d2c19e4be4` (solo `independent_verification`, `sealed_at`, `status: SEALED` e hash nel manifest G5). Gate locali sul sigillo: digest 8/8, ruff 0.13.1, mypy strict 75 file, RCCAD precheck, scope task 5 path, language, piano `--base-ref HEAD` 37 PASS/2 NOT_EXECUTED opzionali, drift (178 input, 0 deriva), evidence `--non-skipped`, controllo riproducibile dell'evidenza PASS. PR #202, 13/13 required sull'HEAD esatto (run [38048464878, 38048464881, 38048464895, 38048464931, 38048464932, 38048464965, 38048464998]), merge `e6e2add7f8462ade82006771624bfe57e8e94f04` con `--match-head-commit`.
- Su main: record `2154d050c77ae10afdcf7434b15be042c1eb4d8f10f9e633e14829e8c58a9424`, raw `45c6f9fdeec9b8082413fbe228ca77bc202c4f0933052915466f0d2185a7ea2d`, manifest G5 `824461e2001a0ad43dfb8e9c4710393b177bdd9a10138c3c60507ca8aa7e3f4c`; sigilli precedenti invariati. `completed_evidence_tasks` 69 (+OCOR-DEV-0055). Ready per dipendenze: OCOR-DEV-0049 (integrazione subordinata a REM-0017), OCOR-DEV-0056, OCOR-DEV-0057; unita selezionata secondo le decisioni PO: OCOR-DEV-REM-0019.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a gate o workflow, a PR #169 o #176.
- Prossima azione: OCOR-DEV-REM-0019 (decisione PO REM-0017-CI-0049-REMAINDER-CAP, opzione 2): isolamento dei test di OCOR-DEV-0049, solo test_ocor_dev_0049.py e fixture, produzione invariata, stessi 390 casi e asserzioni; prova di indipendenza (ordine di collezione, inverso, >=3 permutazioni con seed, esecuzioni isolate dei test dipendenti); riqualifica 0049 con supersession; branch governed/ da origin/main in worktree nuovo. Poi OCOR-DEV-REM-0017 (run CI con 0049 partizionato, ogni parte entro 45 minuti), poi OCOR-DEV-0056 e 0057 (pronti per dipendenze), 0058, 0059. Integrazione OCOR-DEV-0049 (GO b14e4bf, PR #176) subordinata alla chiusura verificata di REM-0017. RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5. F2 tracciato verso FGM-16; finestra residua VF-001 verso FGM-17; VF-004 rischio residuo aperto non assegnato, da riesaminare alla chiusura di G5.

## 2026-10-10T15:14:31Z — OCOR-DEV-REM-0019: implementazione in corso (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita; verifier dichiarato Grok 4.7 via Cursor CLI. Decisione PO `REM-0017-CI-0049-REMAINDER-CAP` (opzione 2).
- Branch `governed/ocor-dev-rem-0019-0049-test-isolation` radicato sul candidato sigillato di 0049 `df444af855e884d7783612b302e008b90105fe13` (il modulo non e su main; 0049 si integra dopo REM-0017). Commit di codice `4c21be312bebd80f2d30f37c7a2febd5afb1aa5b`: solo `test_ocor_dev_0049.py`; lo stato live condiviso (recovery point, receipt PASSED, riapertura umana, telemetria di fault, agent.py) e prodotto da fixture esplicite invece che da test precedenti; backup e restore nei propri vault; 390 casi, asserzioni identiche (AST, 72 funzioni). Produzione di 0049 invariata.
- RED su `df444af`: 8/8 gruppi isolati o riordinati FAIL. Isolati: 119/119 PASS, zero residui. Run del modulo finora: order-collection PASS 390/390 in 2356.6 s.
- Tentativo non qualificante: ordine inverso 389/390, caso Helm FAIL per SIGSEGV di containerd nel nodo kind al tick */15 (14:45:00Z, capture-kafka exit 255), difetto locale gia registrato come REM-0017-KIND-CONTAINERD-CRASH; registrato e da rieseguire, mai rietichettato.
- Gate locali sul commit di codice tutti exit 0 (inputs 8/8, ruff, mypy strict, language, RCCAD, scope, piano 37 PASS/2 NOT_EXECUTED opzionali, drift, runtime-evidence, harness 14 PASS). Nessuna PR per REM-0019; nessuna richiesta di verifica ancora.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a gate o workflow, a PR #169 o #176.
- Prossima azione: OCOR-DEV-REM-0019:implementation (ripresa): nel worktree .ocor/worktrees/rem-0019 (branch governed/ocor-dev-rem-0019-0049-test-isolation, commit di codice 4c21be3) completare i run del modulo mancanti o falliti per infrastruttura con python3 ~/.ocor-codex/rem-0019/modules.py <label...> (order-seed-190001/190002/190003, order-reverse; un run gia in corso alla fine dell iterazione va atteso: controllare modules.progress e modules.done, non avviare un secondo stack); con i 5 run verdi: python3 ~/.ocor-codex/rem-0019/gates.py code solo se il commit e cambiato, build_evidence.py <worktree> ~/.ocor-codex/rem-0019 4c21be312bebd80f2d30f37c7a2febd5afb1aa5b, make_readme.py, commit dell evidenza, check_evidence.py <worktree> HEAD, gates.py final, push e build_request.py (REMEDIATION, verifier Cursor/Grok). Poi OCOR-DEV-REM-0017 (CI con 0049 partizionato sull HEAD verificato di REM-0019, ogni parte entro 45 minuti), poi 0056-0059. Integrazione OCOR-DEV-0049 (GO b14e4bf, PR #176) subordinata alla chiusura verificata di REM-0017. RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5. F2 verso FGM-16; finestra residua VF-001 di 0055 verso FGM-17; VF-004 di 0055 aperto non assegnato.

## 2026-10-10T18:30:13Z — OCOR-DEV-REM-0019: candidato completo e richiesta di verifica indipendente (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita; verifier Grok 4.7 via Cursor CLI (processo, contesto e fornitore separati). Decisione PO `REM-0017-CI-0049-REMAINDER-CAP` (opzione 2).
- Campagna di indipendenza completata sul commit di codice `4c21be312bebd80f2d30f37c7a2febd5afb1aa5b` (solo `test_ocor_dev_0049.py`, produzione di 0049 invariata): order-collection 390/390 in 2356.6 s; order-seed-190001 390/390 in 2387.9 s; order-seed-190002 390/390 in 2417.4 s; order-seed-190003 390/390 in 2392.7 s; order-reverse 390/390 in 2407.3 s; tutti zero skip, zero fail/error, zero residui. Isolati 119/119 PASS. Il tentativo non qualificante dell'ordine inverso (SIGSEGV di containerd nel nodo kind, REM-0017-KIND-CONTAINERD-CRASH) resta registrato nel record e non e rietichettato.
- Evidenza candidata `9099f7b6a677cc9695dec61150340911271bde5a` su `governed/ocor-dev-rem-0019-0049-test-isolation`: record REM in `reports/assurance/OCOR-DEV-REM-0019-RCCAD/`, riqualifica `reports/evidence/G4/OCOR-DEV-0049.requalified-rem0019.json` con `supersedes` esplicito del record sigillato (GO b14e4bf storico e invariato), manifest G4 reindirizzato. Controllo riproducibile dell'evidenza PASS sull'HEAD; gate locali sull'HEAD tutti exit 0 (inputs 8/8, ruff, mypy strict, language, RCCAD, scope, piano, drift, runtime-evidence, harness).
- Richiesta di verifica `OCOR-DEV-REM-0019-9099f7b6a677-0` (REMEDIATION, base `df444af855e884d7783612b302e008b90105fe13`) scritta per il loop; nessuna PR per REM-0019 (branch radicato sul candidato di 0049).
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a gate o workflow, a PR #169 o #176.
- Prossima azione: OCOR-DEV-REM-0019:integration dopo il verdetto ~/.ocor-codex/verdicts/OCOR-DEV-REM-0019-9099f7b6a677-0.json (head 9099f7b6a677cc9695dec61150340911271bde5a, verifier Cursor/Grok). Con GO_FOR_EVIDENCE_SEAL: sigillo del record REM e del record di riqualifica di 0049 (solo independent_verification, sealed_at, status e hash nel manifest G4) sul branch governed/ocor-dev-rem-0019-0049-test-isolation; il branch non si integra da solo su main (radicato su df444af): REM-0017 fissa l HEAD sigillato di REM-0019 al posto di df444af per la partizione del modulo 0049 e l integrazione di 0049 (PR #176) segue la chiusura verificata di REM-0017. Con NO_GO: ciclo di riparazione 1 di 2 sullo stesso branch. Poi OCOR-DEV-REM-0017 (CI con 0049 partizionato come gli altri moduli, caso Helm in parte propria, ogni parte entro 45 minuti), poi 0056-0059. RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5. F2 verso FGM-16; finestra residua VF-001 di 0055 verso FGM-17; VF-004 di 0055 aperto non assegnato.

## 2026-10-11T05:35:59Z — OCOR-DEV-REM-0019: ciclo di riparazione 1 in corso (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita; verifier dichiarato Grok 4.7 via Cursor CLI.
- Verdetto `OCOR-DEV-REM-0019-9099f7b6a677-0` NO_GO su `9099f7b6a677cc9695dec61150340911271bde5a`: VF-001 (high), la precondizione del caso concorrente degli snapshot Qdrant trattava un HTTPError catturato come nome di snapshot (seed 190001 e 190003 del verifier, DELETE con l'eccezione nell'URL). NOT_EXECUTED del verifier (suite completa per OOM di fuseki; controllo compensativo CI-0048 con SPIRE senza identita' di workload): fuori dal diff e dai criteri, non dichiarati PASS.
- Riparazione nel commit `63a0a939d84402af4ed91acd77de2dac341ee976` su `governed/ocor-dev-rem-0019-0049-test-isolation` (solo `test_ocor_dev_0049.py`): contano solo i nomi restituiti da Qdrant; un tentativo con POST sollevato o senza collisione cancella i propri snapshot e si ritenta entro gli stessi 60 s. RED deterministico con un HTTP 500 iniettato su uno dei quattro POST: FAIL `InvalidURL` sul modulo del ciclo 0; GREEN PASS sul nuovo commit. Gate locali sul commit tutti exit 0.
- Campagna di indipendenza in corso sul nuovo commit (stack ocor-bootstrap ricreato con reset e bootstrap): order-collection PASS 390/390 in 2412.0 s; order-reverse PASS 390/390 in 2411.5 s; order-seed-190001 PASS 390/390 in 2400.4 s; order-seed-190002 PASS 390/390 in 2362.1 s; order-seed-190003 FAIL 389/390 in 2350.8 s; isolati 3/119 (3 PASS).
- Tentativi non qualificanti registrati e mai rietichettati: seed 190002 tentativo 1 interrotto dal watchdog per OOM del cgroup di Fuseki (04:00:37Z, 138 casi PASS), rieseguito 390/390; seed 190003 tentativo 1 389/390 per falso positivo dell'asserzione sigillata di 0049 alla riga 1813 (`PGDMP` comparso per caso nel base64 del ciphertext transit, ~0,94% per esecuzione), da rieseguire. Asserzione non modificata per il vincolo "stesse asserzioni": decision request non bloccante `REM-0019-BACKUP-CIPHERTEXT-MARKER` (fuori dal repository in `~/.ocor-codex/decision_requests/`, blocker in EXECUTION_STATE).
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a gate o workflow.
- Prossima azione: OCOR-DEV-REM-0019:implementation, ciclo di riparazione 1 (ripresa): la campagna sul commit 63a0a93 gira staccata (~/.ocor-codex/rem-0019-r1/campaign_driver2.sh, 119 isolati): attendere DONE in driver.progress senza avviare un secondo stack (se isolated exit != 0: diagnosticare l ultimo iso-NNN, spostarlo in attempts/ e riprendere). Poi rieseguire il seed 190003 (tentativo 1 non qualificante, falso positivo PGDMP): docker restart ocor-bootstrap-fuseki-1 se la sua RSS supera ~1,5 GB, verify_external_services, python3 ~/.ocor-codex/rem-0019-r1/modules.py order-seed-190003. Un run FAIL per infrastruttura (OOM di fuseki, containerd del nodo kind) va registrato in attempts/ (aggiungerlo ad ATTEMPTS in build_evidence.py) e rieseguito, mai rietichettato. Con 5 run del modulo e 119 isolati verdi, nel worktree .ocor/worktrees/rem-0019: python3 ~/.ocor-codex/rem-0019-r1/assertion_identity.py . df444af855e884d7783612b302e008b90105fe13 63a0a939d84402af4ed91acd77de2dac341ee976 > ~/.ocor-codex/rem-0019-r1/assertion-identity.json; python3 ~/.ocor-codex/rem-0019-r1/build_evidence.py <worktree> ~/.ocor-codex/rem-0019-r1 63a0a939d84402af4ed91acd77de2dac341ee976; make_readme.py <worktree>; commit dell evidenza; check_evidence.py <worktree> HEAD > check-final.json (PASS); gates.py final; push; build_request.py (REMEDIATION, repair_cycle 1, verifier Cursor/Grok); state_sync_candidate.py in un branch governed/. Poi OCOR-DEV-REM-0017, poi 0056-0059. RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5.

## 2026-10-11T06:01:11Z — OCOR-DEV-REM-0019: gate di stabilità aperto, richiesta PO versionata e state sync (Codex)

- Unità coerente: diagnosi e disposition del FAIL intermittente già osservato nel ciclo 1, senza modifica del codice. Codice REM-0019 cicli 0/1: Claude Code (riserva); coordinatore della presente iterazione: Codex (OpenAI); verifier del task: Grok 4.7 tramite Cursor CLI. Nessuna verifica indipendente avviata o simulata.
- Baseline riletta e checkout main pulita/allineata: `7fc65b055c1993d75e8f21b157a54102068cfc6f` (PR #206, 13 required SUCCESS). Ready dal backlog e dai 69 completed_evidence_tasks: 0049, 0056, 0057; 0049 resta non integrabile prima di REM-0017. PR #169 e #176 lasciate invariate. Nessun nuovo ID REM o DEC.
- Preflight normativo 8/8; toolchain isolata Python 3.12.11, uv 0.12.5, Node 20.20.2, tsc 7.0.2, ruff 0.13.1, git 2.53.0, gh 2.99.0, docker 29.7.2: versioni e digest dei binari confrontati con infra/toolchain.lock.json. Il primo comando `.venv/bin/python3 scripts/verify.py` era NOT_EXECUTED (path assente); eseguito con ocor-runtime/.venv/bin/python nel worktree REM, 14 PASS. Drift in quel worktree 63 task/167 input, zero deriva. Stack ocor-bootstrap già usato dalla campagna ereditata; nessun reset, bootstrap o seconda suite concorrente. Health typed corrente e suite completa della presente iterazione NOT_EXECUTED; le osservazioni sui container non sono una qualifica.
- Campagna ereditata sul commit `63a0a939d84402af4ed91acd77de2dac341ee976` ancora attiva: snapshot 41/119 isolati, 41 PASS; il driver3 ha accodato il rerun del seed190003. Nessun processo o stack alterato da Codex. Snapshot, non risultato finale: ogni esito successivo va raccolto preservando i fallimenti.
- `order-seed-190003` tentativo 1: 389 PASS, 1 FAIL, 0 skip in 2350.8 s, asserzione riga 1813 di test_backup_seals_an_encrypted_signed_immutable_recovery_point. `PGDMP` trovato all offset 6274804 dentro il base64 di un chunk transit. Il JUnit conservato ha SHA256 `e837866bb29b70a155c7314ef9c013e9b838bed315edb5ef9087d9ce66874303`; il log `e881e0b10abc944e4cad1552f8e897103c0f2a5dd796de2522e5439094d98b13`. L analisi supporta un difetto del predicato lessicale; la decrittazione autenticata del blob specifico non è rieseguita qui. La probabilità ≈0,94% è una stima del modello, non un tasso misurato.
- Rettifica della precedente disposition non bloccante: un test intermittente non è un PASS. Un rerun verde non risolve il difetto e non qualifica REM-0019; nessuna nuova richiesta di verifica/sigillo mentre resta aperto. Non si modifica l asserzione perché la decisione PO REM-0017-CI-0049-REMAINDER-CAP impone «stessi 390 casi e stesse asserzioni». Il ciclo 1 resta in corso, nessun nuovo ciclo consumato.
- Richiesta `REM-0019-BACKUP-CIPHERTEXT-MARKER` completa pubblicata come `governed/decision-request-rem-0019-ciphertext-marker@35b0317fbfe3880690581622732b091953e11563:reports/development/decision_requests/REM-0019-BACKUP-CIPHERTEXT-MARKER.md` (SHA256 `3d3fe2a008a8d70ce166c04afa764a6ec27c30541f335791c8dc6d6f5f0f8591`). Opzione raccomandata da autorizzare: variazione puntuale del test, 390 casi e produzione invariati, controllo strutturale dell envelope e decrittazione autenticata/digest, con RED/GREEN deterministico e verifica indipendente. La ricerca di marcatori nel ciphertext binario decodificato lascia a sua volta una collisione casuale possibile. Alternativa: asserzione invariata e qualifica bloccata; nessun rerun fino al verde.
- Il nuovo file non è nell allowlist del validator di piano: gate del documento FAIL, RCCAD/scope PASS; documento WIP in branch separato, nessuna PR/merge su quel branch, nessun validator indebolito. Il presente state sync usa soltanto i tre path già ammessi e conserva disposizione, commit e digest della richiesta su main. L integrazione futura del documento richiede estensione chirurgica dell allowlist e riqualifica 0050.
- Blocker riguarda la qualifica REM-0019, REM-0017 e integrazione 0049; non blocca G5. E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED e PoC/Production NO-GO invariati. Nessuna modifica a inputs, produzione o record sigillati; nessuna risorsa di stack creata da questa iterazione.
- Prossima azione: OCOR-DEV-0056:implementation appena lo stack ereditato è libero: controllare ~/.ocor-codex/rem-0019-r1/{driver.progress,rerun190003.progress,isolated.progress} e i processi senza avviare un secondo stack; archiviare ogni esito come diagnostico, mai dichiarare chiusa la flake PGDMP con un rerun. REM-0019:repair_cycle 1 bloccato sulla decisione REM-0019-BACKUP-CIPHERTEXT-MARKER (richiesta versionata su governed/decision-request-rem-0019-ciphertext-marker@35b0317fbfe3880690581622732b091953e11563). Nessuna nuova verifica/sigillo REM-0019 finché il vincolo sulle asserzioni non è risolto. Quando libero: worktree isolato task/OCOR-DEV-0056 da origin/main, leggere task e fonti, RED prima del codice; implementatore Codex, verifier Claude Code, salvo interventi dell implementatore di riserva (Cursor/Grok). REM-0017 e integrazione 0049 restano subordinati alla chiusura verificata REM-0019; G6 bloccato. Non modificare produzione 0049, inputs, record sigillati o gate.

- Gate locali dello state sync: digest 8/8, ruff, mypy strict, RCCAD precheck, scope 3 path, language, piano --authorized-extension (37 PASS/2 NOT_EXECUTED opzionali), drift 69 task/180 input zero deriva, evidenza sigillata 0055 --non-skipped e harness 14 PASS/2 INFO: exit 0. Primo runtime-evidence senza task/manifest: NOT_EXECUTED per usage error, poi eseguito con gli argomenti richiesti; non dichiarato PASS il comando incompleto. La suite di prodotto locale non è ripetuta per una modifica di soli stato/log; dinamica demandata ai check CI obbligatori.

## 2026-10-11T06:37:35.266063Z — OCOR-DEV-0056: implementazione WIP di checkpoint e replay metadata (Codex)

- Baseline origin/main `4251b43bbef4db1c8347a14309e4b2ba908bd7b6` (merge PR #207), checkout main pulita. Ready set ricalcolato: 0049, 0056, 0057; 0049 integrazione resta subordinata a REM-0017 e REM-0019. REM-0019 bloccato sulla decisione `REM-0019-BACKUP-CIPHERTEXT-MARKER`; la campagna ereditata resta diagnostica, un rerun verde non elimina la flake. PR #169/#176 lasciate invariate.
- Unità coerente: avvio dell implementazione di 0056, WIP pubblicato su `task/OCOR-DEV-0056-deletion-saga-restore-reconciliation@5edd6cdb526dab1be7d3f71d534b34622f870aee`. Non è qualifica né chiusura del task; `completed_evidence_tasks` resta 69. Implementatore Codex (OpenAI); verifier previsto Claude Code (Anthropic), non richiesto. Nessun verifier avviato o verdetto simulato.
- Letti AGENTS, metodologia, stato e task completo, ADD Part II §§2.3–2.13, LLD memory/deletion/recovery/FGM e spike 0025/0026. Il nucleo riusa i port e participant di 0055 senza modificarli. Nuovi `DeletionJournalSnapshot`, `DeletionRestoreGate`, `MemoryDeletionMetadataReplay` e adapter ai participant esistenti: journal completo ordinato contro checkpoint esterno, servizio inizialmente chiuso, replay dei record originali con epoch/eventi/audit conservati, purge e inventory, ricontrollo prima/dopo materializzazione.
- RED: commit `0d1de3bdc198d4b1398754e4a885236d5e0aaa91`, 26 FAIL/1 PASS (stub fail-open); roster omesso 1 FAIL/36 PASS; replay metadata 7 FAIL/57 PASS. Fingerprint e raw conservati nel log WIP (nessun run fallito rietichettato). GREEN finale 66 unit PASS/zero fail/skip in 1,21 s; regression sui tre test del journal di 0055 3 PASS. Il port adapter è caratterizzato dalla composizione unitaria; restano da completare RED e casi di classe/qualificanti sui backend per la composizione definitiva.
- Preflight: digest 8/8, harness 14 PASS, drift 69 task/180 input zero deriva. Primo PATH host non pinnato (docker 29.8.2, gh 2.46.0, uv 0.12.21): diagnosticato, nessuna modifica del lock. PATH isolato `~/.ocor-codex/c5resume/toolchain/bin` confrontato per versione/digest: tutti gli otto binari corrispondono al lock. Prima sync uv host registrata; sync ripetuta con uv 0.12.5. Java container identity, health typed 11 servizi e suite completa: NOT_EXECUTED, stack occupato da campagna ereditata (snapshot 91/119 isolati PASS, non risultato finale). Nessun reset/secondo stack o teardown concorrente.
- Gate WIP: ruff, mypy strict (76 sorgenti), RCCAD precheck, scope tre path, language, drift e inputs exit 0. Piano con base storico implicito FAIL per diff planning-only; corretta invocazione al `HEAD` del task come nella CI (workflow ocor-tooling-bootstrap): 37 PASS/2 NOT_EXECUTED opzionali. Validator invariato; output generati ripristinati. Qualifica runtime-evidence di 0056 NOT_EXECUTED: record JSON candidato e manifest volutamente assenti finché il task non è qualificato.
- Restano obbligatori: provider autenticato del checkpoint/recovery point; integrazione del gate in ogni entry point di restore; participant/inventario completo di cache/repliche/export/backup e prove live di ogni footprint, inclusi shared content/legal hold e fault/riavvio; suite completa e reports/tests; rollback; record candidato hash-bound e verifica Claude. `capture` verifica integrità, non autenticità. Finestra esterna tra ultimo controllo e ritorno non atomica: rischio residuo, nessun claim FGM-17 chiuso.
- Nessuna modifica a inputs, produzione di 0049, altri input sigillati, gate, workflow o record sigillati; E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO invariati. Nessuna risorsa di stack creata dalla sessione.
- Prossima azione: OCOR-DEV-0056:implementation (ripresa WIP, repair_cycle 0): riprendere il worktree .ocor/worktrees/ocor-dev-0056, branch task/OCOR-DEV-0056-deletion-saga-restore-reconciliation@5edd6cdb526dab1be7d3f71d534b34622f870aee. Leggere remaining_work e limitations in MODEL_HANDOFF.source_reference. Prima di test live/suite: controllare i processi ereditati e ~/.ocor-codex/rem-0019-r1/{driver.progress,isolated.progress,rerun190003.progress}; nessun secondo stack o reset concorrente. Quando libero, reset_test_environment --execute, bootstrap pinned, health 11 READY; completare copie/restore/auth e test RED prima del codice; suite task <=45 min, completa <=75 min, stop immediato su restart/OOM, teardown. Solo con tutti i criteri qualificati preparare record+manifest ed esatta richiesta TASK_EVIDENCE (implementer Codex, verifier claude/Claude Code). REM-0019 resta bloccato su REM-0019-BACKUP-CIPHERTEXT-MARKER: nessun sigillo o nuova verifica grazie a un rerun verde. Se arriva la decisione rendendolo eseguibile, torna prioritario prima di REM-0017; PR #169/#176 e G6 rimangono bloccati. Nessun intervento su inputs o record sigillati.

- Gate dello state sync: tutti i dieci controlli locali exit 0; JSON canonici; outputs di planning ripristinati. Le due verifiche opzionali del piano restano NOT_EXECUTED. La suite di prodotto locale di questa iterazione non è stata eseguita; integrazione dello stato solo dopo CI required sull HEAD esatto.


## 2026-10-11T07:13:55.059040+00:00 — REM-0019: riparazione puntuale dell’oracolo backup (Codex), ciclo 1 WIP

- Baseline main pulita/allineata `d55e2b37170417343f6b8bbdc2aa35d4337323a7`; ready set OCOR-DEV-0049, OCOR-DEV-0056, OCOR-DEV-0057, 69 completed invariati. Priorità REM-0019 resa eseguibile dalla decisione PO `REM-0019-BACKUP-CIPHERTEXT-MARKER` (2026-10-11), opzione 1. 0056 WIP preservato, stack libero; Claude attivo su un altro repository non interferito. PR #169/#176 lasciate invariate.
- WIP pubblicato `governed/ocor-dev-rem-0019-0049-test-isolation@60c859a8c61c541f7bce89ab0b5d6a4e27c62ab1`; sorgente qualificata dal solo caso mirato `9a38548752e56e6239313a9dbe32e5578e638777`. Implementazione test-isolation Claude Code (riserva), oracle repair Codex nel ciclo 1; verifier Grok 4.7 via Cursor CLI, non richiesto. Nessuna verifica autonoma simulata.
- RED `ac71229709fdc0f8f64223725ada0ea4b9999691`: vecchio predicato accetta plaintext base64 camuffato da chunk vault:v1 senza decrittazione. GREEN: envelope JSON canonico chiuso, chiavi uniche, key esatta, numero/forma dei chunk, AES-GCM autentico OpenBao, dimensioni per chunk e digest dell’intero plaintext contro il manifest firmato. Oracle sorgenti su dump PGDMP, CSV fixture tenant-a/evt-del e profilo; corrispondenza AST: 72 funzioni, decoratori invariati e stessi 390 node id; sole 2 asserzioni lessicali sostituite secondo PO.
- Caso live finale 1 PASS/0 skip in 30.4 s; 15 negativi deterministici con reason atteso (incluse alterazione nonce/ciphertext, chunk mancante/duplicato/permutato, plaintext e base64 camuffato). Mutante del writer che salva un dump in chiaro ucciso dall’oracolo, file di produzione invariati. Primo probe con tutti gli artifact in chiaro fallisce prima dell’oracolo per collisione dei dump/digest vuoti: conservato come diagnostico FAIL, non dichiarato mutant kill. Negativo di backend indisponibile non può diventare PASS. Positivo opzionale ciphertext con PGDMP non riprodotto senza alterare il custodian: NOT_EXECUTED.
- Preflight digest 8/8, harness 14 PASS, toolchain 8 binari pinnati con versioni/digest conformi. Reset completato; primo bootstrap FAIL per tag Fuseki divergente, immagine governata disponibile: ripristinato soltanto il tag su ID del lock (nessuna modifica lock/validator), un retry PASS. Init senza --env-file NOT_EXECUTED/usage error, invocazione corretta PASS; fixture e typed health 11 READY.
- Decision request chiusa come risolta nel WIP; 15 path di allowlist esatti per richiesta/evidenza/riqualifica, senza estensione a produzione. Deriva 0050 RED su validator, riqualifica candidata nuova 198 PASS, supersedes esplicito `OCOR-DEV-0050-requalified-rem0021-0e76db2ac62d`; manifest chirurgico, record sigillati intatti. Primo run 0050 con node path errati: NOT_EXECUTED exit 4, poi corretto. Drift finale 69 task/180 input, zero mismatch.
- Gate HEAD precheck: dieci exit 0, ruff/mypy strict inclusi; piano 37 PASS/2 NOT_EXECUTED opzionali. Reports collection indiscriminata non applicabile (script con sys.exit), NOT_EXECUTED. Suite CI corretta iniziale 1 FAIL/46 PASS/1 SKIP per SDK mancante; npm ci/build pinnati, rerun 48 PASS/0 SKIP, cinque harness documentali exit 0. Nessun test rimosso o deselezionato per ottenere PASS; eseguiti i comandi dichiarati in CI.
- Precheck di integrazione `plan --base-ref origin/main` FAIL: il branch ereditato contiene 13 path di produzione/test/evidenza 0049 ancora non uniti, fuori dall’allowlist governata. Il PASS con base HEAD non lo sostituisce. FAIL conservato nel WIP; nessuna PR di implementazione o merge, nessun ampliamento alla produzione autorizzato implicitamente. Prossima iterazione deve risolvere la base/scope mantenendo il diff REM soltanto nei test autorizzati.
- Campagna intera sul candidato finale (collection, reverse, tre seed, 119 isolati, full runtime con DSN/SVID) NOT_EXECUTED in questa iterazione; risultati ereditati, incluso FAIL order-seed-190003, restano storici e non qualificano il codice cambiato. Ripresa necessaria per limite di contesto RCCAD §8, nessun ciclo nuovo consumato. Nuovi record REM e 0049 con supersession soltanto dopo tutti i run obbligatori. Nessuna verify_request finché qualifica/gate incompleti.
- Session teardown: reset_test_environment --execute, inventory container/network/volume OCOR vuoto. Nessun processo di test rimasto. E1=0/E2=0/Verified=0, claim NO-GO invariati; inputs e produzione 0049 invariati; nessun DEC/chiusura normativa.
- Prossima azione esatta: OCOR-DEV-REM-0019:repair_cycle 1 — riprendere .ocor/worktrees/rem-0019, governed/ocor-dev-rem-0019-0049-test-isolation@60c859a8c61c541f7bce89ab0b5d6a4e27c62ab1; rileggere marker-repair-WIP.json. Prima risolvere la base/scope di integrazione che include 0049 non unito: plan --base-ref origin/main FAIL (13 path ereditati), nessuna nuova allowlist di produzione o gate bypass. Poi reset/bootstrap pinned, inizializzazione/fixture, SVID control-plane e 11 READY; campagna intera sul candidato finale: 390 casi collection/reverse/seed 190001/190002/190003, 119 isolati derivati dall analisi, zero skip, <=45 min per modulo; full runtime <=75 min con DSN, stop immediato su restart/OOM, teardown. Appendere nuove evidenze REM-0019 e riqualifica 0049, completare riqualifica 0050 e gate, ricontrollare HEAD/hash, poi verify_request REMEDIATION repair_cycle 1 verifier cursor/Grok. Nessuna verifica prima. 0056 WIP preservato e subordinato alla priorità REM-0019; dopo chiusura verificata REM-0019 riprendere REM-0017, merge 0049, ordine G5 invariato.

- Gate state sync: ruff, mypy, language, scope, drift, evidenza storica 0055 e harness exit 0. Primo RCCAD FAIL per riferimenti WIP non presenti su main: corretti i riferimenti del checkout (evidence_paths vuoto; source_reference/branch_evidence_paths conservano branch, SHA e digest). Piano FAIL per symlink .venv non tracciata: rimossa senza eliminare l ambiente, riuso dell interprete esterno; piano sulla base esatta main PASS 37/2 NOT_EXECUTED, RCCAD PASS. Nessuna allowlist o gate alterati nello state sync.

## 2026-10-11T11:14:51Z — OCOR-DEV-REM-0019: campagna del ciclo marker in corso (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (Anthropic, claude-opus-5-5) per quota Codex esaurita; verifier dichiarato Grok 4.7 via Cursor CLI. Ripresa del lavoro di Codex sulla decisione PO `REM-0019-BACKUP-CIPHERTEXT-MARKER` (opzione 1): oracolo strutturale del backup in `2d6d237` (RED `ac71229`), candidato `60c859a`.
- PR #209 (state sync di Codex) mergiata sull'HEAD esatto `e09a076` con 13/13 required SUCCESS (merge `a32c9bf`).
- Primo avvio della campagna con la ricetta locale di bootstrap: Fuseki con il default `-Xmx4G` nel cgroup da 2 GiB, OOM dopo 289 casi PASS; registrato come `attempt1-order-collection` (FAIL_INFRASTRUCTURE), mai rietichettato. Stack ripreparato con la ricetta CI di REM-0017 usata dai cicli 0 e 1 (`-Xms128m -Xmx1G`), riavvio preventivo di Fuseki prima di ogni run (RSS ~1,25 GB dopo un run).
- Campagna sul candidato finale: order-collection PASS 390/390 in 2463.5 s; order-reverse PASS 390/390 in 2541.3 s; order-seed-190001 PASS 390/390 in 2412.9 s; order-seed-190002 PASS 390/390 in 2429.1 s; isolati 0/119 (0 PASS). Gate locali sul candidato 10/10 exit 0. Script di evidenza (record `.r1-marker` con supersession dei candidati del ciclo 0) pronti e provati a secco.
- Tentativi non qualificanti del ciclo marker: attempt1-order-collection, attempt1-order-seed-190001.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Nessuna modifica a `inputs/`, a gate, workflow o record sigillati.
- Prossima azione: OCOR-DEV-REM-0019:implementation, ciclo marker (riparazione 1), ripresa: seguire /home/luca/.ocor-codex/rem-0019-r1m/HANDOFF.md. La campagna sul candidato 60c859a gira staccata (driver3.sh): attendere DONE in driver.progress senza avviare un secondo stack; un run fallito va spostato in attempts/ con diagnosis.json e rieseguito, mai rietichettato. Con 5 ordini e 119 isolati verdi: assertion_identity.py, build_evidence.py <worktree> 2d6d2370fa1495bd2b23770665696e59cd548e01 60c859a8c61c541f7bce89ab0b5d6a4e27c62ab1, make_readme.py, commit dell evidenza (.r1-marker), check_evidence.py (PASS), gates.py final (10/10), push, build_request.py (REMEDIATION, repair_cycle 1, verifier cursor), ripristino del tag Fuseki governato, state_sync_candidate.py in un branch governed/. Poi OCOR-DEV-REM-0017, merge 0049, 0056 (WIP 5edd6cd) e 0057-0059. RVW-03, INFO-A, INFO-C, REM-0018 aperti e non bloccano G5.

## 2026-10-11T12:13:03.609017+00:00 — REM-0019: ripresa della qualifica e correzione dell'orchestrazione (Codex)

- Baseline pulita/allineata `0aa2076ea8960abb25412b88e85c6d28332f89cd`; PR #210 verificata (13 required SUCCESS, merge 0aa2076). Ready set ricalcolato ['OCOR-DEV-0049', 'OCOR-DEV-0056', 'OCOR-DEV-0057']; 69 completed invariati, 0056 WIP preservato. Unica unità REM-0019 ciclo 1, priorità decisione PO REM-0019-BACKUP-CIPHERTEXT-MARKER. PR #169/#176 non modificate.
- Cinque ordini ereditati sul candidato 60c859a: {"order-collection": {"counts": {"errors": 0, "failures": 0, "skipped": 0, "tests": 390}, "duration_seconds": 2463.5, "ok": true}, "order-reverse": {"counts": {"errors": 0, "failures": 0, "skipped": 0, "tests": 390}, "duration_seconds": 2541.3, "ok": true}, "order-seed-190001": {"counts": {"errors": 0, "failures": 0, "skipped": 0, "tests": 390}, "duration_seconds": 2412.9, "ok": true}, "order-seed-190002": {"counts": {"errors": 0, "failures": 0, "skipped": 0, "tests": 390}, "duration_seconds": 2429.1, "ok": true}, "order-seed-190003": {"counts": {"errors": 0, "failures": 0, "skipped": 0, "tests": 390}, "duration_seconds": 2386.6, "ok": true}}. Isolati al rilevamento 14/119 PASS, zero skip/residui. driver4.sh attivo: nessun reset o secondo stack. Tentativi FAIL restano storici.
- Preflight: digest 8/8, harness 14 PASS; drift 69 task/180 input zero; 8 binari della toolchain verificati per versione/digest, Node 20.20.2/Python 3.12.11 inclusi. Typed health PASS su stack corrente; prima invocazione con --env-file non supportato NOT_EXECUTED exit 2, corretta una sola volta.
- Gli script ereditati trattavano la suite completa come non richiesta: incompatibile con il mandato §5. Preparato e avviato un solo worker fuori dal repository, in attesa degli isolati: deadline 3h; reset/bootstrap ricetta CI pinned (heap Fuseki 1 GiB/limite 2 GiB), SVID, health, collect, run completo con DSN e toolchain corretta; limite 75 min, arresto restart/OOM, confronto collection/JUnit, teardown fail-closed e ripristino tag governato. La suite completa è tuttora NOT_EXECUTED, non PASS. Guardie impediscono creazione di candidati/richiesta senza questo risultato; provata la rejection prima del run. Gli script finali dell evidenza vanno ancora completati per archiviare raw/run e correggere le note ereditate.
- Precheck piano su origin/main riprodotto FAIL per 13 path ereditati di 0049. Anche base df444af FAIL, con 21 path comprendenti G5 già integrato e il modulo test. PASS con base HEAD non è PASS di integrazione. Nessuna modifica al validator/allowlist; nessuna nuova richiesta di verifica. Il builder della richiesta richiede ora anche gate sullo HEAD/base reale di integrazione. Strategia da concretizzare: separare test sul task 0049 e record/allowlist su governed, mantenendo l ordine REM-0019 -> REM-0017 -> integrazione 0049.
- Implementatori REM-0019: Claude Code (test isolation/VF-001 e campagna ereditata), Codex (oracolo backup e orchestrazione odierna); verifier Grok 4.7 via Cursor CLI, processo/contesto/fornitore separati. Nessun verifier lanciato o verdetto scritto.
- E1=0, E2=0, Verified=0 e claim NO-GO invariati; inputs, produzione e record sigillati invariati. File esterni di ripresa/controllo content-addressed in source_reference; stato, handoff e log sono le sole scritture versionate.
- Prossima azione esatta: OCOR-DEV-REM-0019:qualification — riprendere /home/luca/.ocor-codex/rem-0019-r1m/HANDOFF.md e lo stato versionato. Non avviare reset o suite concorrenti: driver4.sh completa i 119 isolati, full_after_isolated.py attende DONE e 119 PASS (timeout 3h), poi reset/bootstrap ricetta pinned CI, SVID/health, collect e suite completa 75 min con DSN/Node/Python pinnati, union JUnit, teardown fail-closed e ripristino tag Fuseki. Leggere full-worker-result.json: FAIL richiede diagnosi e conservazione dei log; >60 min richiede decision request senza alzare il tetto. Con PASS, completare build_evidence.py/check_evidence.py/make_readme.py/state_sync_candidate.py includendo il run completo e relativi raw/hash e rimuovendo le note ereditate che lo dichiarano non richiesto; require_full.py impone il prerequisito. Risolvere base/branch di integrazione: il piano su origin/main e sul vecchio base df444af fallisce; non allargare allowlist produzione, non usare HEAD come gate di integrazione. Preparare separazione tra diff test del task 0049 e diff governato dei record/allowlist; gate verdi sulla base reale della PR. build_request.py richiede anche integration-base-gate.json PASS sull esatto HEAD e comando non HEAD. Solo dopo tutti i gate, nuova REMEDIATION repair_cycle 1 verifier cursor/Grok, mai avviare verifier. Poi REM-0017, integrazione 0049 e 0056 WIP preservato; nessuna chiusura normativa o claim promosso.

- Gate dello state sync: 9/9 exit 0, JSON canonici, ruff e mypy strict verdi, piano sulla base reale main PASS (37 PASS/2 NOT_EXECUTED opzionali); outputs planning/verify ripristinati. Sono gate del solo stato, non qualifica del candidato o della suite ancora pendente.

## 2026-10-11T12:47:04.904486+00:00 — REM-0019: separazione dei diff e preparazione della qualifica (Codex)

- Baseline main pulita/allineata 9d149062164e47b8966b30654241d1d38ccff54e; PR #211 verificata: 13 required SUCCESS, merge 9d149062164e47b8966b30654241d1d38ccff54e. Ready set ['OCOR-DEV-0049', 'OCOR-DEV-0056', 'OCOR-DEV-0057']; priorità REM-0019, ciclo 1 invariato. 0056 WIP e PR #169/#176 preservati.
- Preflight attuale: digest 8/8; harness 14 PASS; drift 69 task/180 input, zero; 8 toolchain digest/version match; nuovo typed health PASS, 11 servizi attivi senza OOM/restart. Campagna ereditata: cinque ordini 390/390 PASS; isolati 61/119 PASS, zero skip/residui al rilevamento. Worker full esistente WAITING_ISOLATED; suite completa NOT_EXECUTED, nessun secondo stack o reset.
- Preparati e pushati WIP due branch senza PR: task/OCOR-DEV-0049-rem0019-test-isolation@a5c7e681937f2746639a5d980f077072ec9bba02 (worktree rem0019-task-stage) e governed/ocor-dev-rem-0019-evidence-stage@c55c6b532d7e7c5ac6dcf2237488d9dcbb377f9e (rem0019-governed-stage). Scope/RCCAD del task contro main PASS; scope/RCCAD/piano governed contro esatta base task PASS; 10 gate locali staging exit 0. Il primo piano FAIL per self-hash validator, conservato diagnostico; self-hash riallineato, secondo run 37 PASS/2 NOT_EXECUTED opzionali. Nessuna nuova allowlist produzione/test. Tutti gli alberi deploy/src/tests/tools/SDK/inputs/infra identici alla campagna 60c859a; parent ours conservano la storia della campagna dopo verifica di equivalenza, senza riscrittura.
- Questi sono precheck dei componenti, NON CI o integrazione su main: il vecchio piano contro main resta FAIL storico. Ordine di integrazione da rispettare dopo GO/REM-0017: prima codice task verso main, poi governance riallineata/rivalidata alla main reale. Governance nel task prima dello scope CI introdurrebbe path fuori ambito, quindi non va fusa lì.
- Builder esterni aggiornati: regressione completa/ambiente ricreato/raw/JUnit/collection/teardown archiviati prima dei digest; credenziali precedenti incluse nella redazione; checker ricostruisce full union e verifica execution trees; gate usa la base esatta del componente, mai HEAD. Compilazione PASS; builder finali NON ancora esercitati sui dati completi. Richiesta protetta da require_full e qualification_complete: nessun record finale o verify_request creato. Artifacts content-addressed nel source_reference.
- Implementatori REM-0019: Claude Code (isolamento/VF-001 e campagna ereditata), Codex (oracolo backup e orchestrazione/separazione); verifier Grok 4.7 tramite Cursor CLI, processo/contesto/fornitore separati. Nessuna verifica autonoma lanciata. Nessuna modifica a inputs, produzione 0049 o record sigillati; E1=0/E2=0/Verified=0 e claim NO-GO invariati. Nessuna risorsa Docker creata da questa unità; worker ereditati proseguono con teardown fail-closed già accodato.
- Prossima azione esatta: OCOR-DEV-REM-0019:qualification — leggere ~/.ocor-codex/rem-0019-r1m/HANDOFF.md aggiornato e source_reference. Non cambiare HEAD 60c859a o reset/duplicare lo stack: driver4 completa 119 isolati, full_after_isolated attende DONE, poi reset/bootstrap pinned, SVID/11 READY, suite completa <=75 min con DSN/Node/Python pinned, union JUnit, teardown e ripristino tag Fuseki. Leggere full-worker-result.json: FAIL conserva log/diagnosi; >60 min apre decision request, nessun aumento del tetto. Con PASS, completare qualifica e nuovi record sul governed stage c55c6b5 (base task-stage a5c7e68), usando builder aggiornati, assertion_identity, check_evidence, validation_commands 0049, reports/tests, 0050/drift e gate finali. I 5 precheck dei due componenti non sono main integration o CI; rieseguirli sull HEAD finale, acquisire completezza concreta prima di qualification_complete/verify_request. Produzione/test/pin identici alla campagna; source code 2d6d237 e campagna 60c859a conservati come antenati. Solo dopo qualifica completa: RCCAD, push, REMEDIATION repair_cycle 1 verifier cursor/Grok, nessun verifier lanciato. Dopo GO e REM-0017, integrare codice 0049 prima di governance: mai fondere path governed nel task prima del suo scope check verso main; riallineare governance alla main reale e passare piano/scope/CI sull esatto HEAD. 0056 WIP preservato, poi ordine G5 invariato.

- Gate dello state sync: 9/9 exit 0 (digest, ruff, mypy strict, language, RCCAD, scope, piano su main reale, drift, evidenza storica 0055). Piano 37 PASS/2 NOT_EXECUTED opzionali. Output planning ripristinati. Questi gate validano soltanto lo stato; nessun task completato e nessuna qualifica della suite pendente.

## 2026-10-11T14:17:28.633461+00:00 — OCOR-DEV-REM-0019: campagna completata, qualifica bloccata dal teardown Kafka

- Una sola unita: completamento della qualifica del ciclo di riparazione 1 di REM-0019 sul commit 60c859a8c61c; produzione 0049 invariata. Cinque ordini del modulo: 390/390 PASS ciascuno; isolati 119/119 PASS; zero skip. Regressione reports: 48/48 PASS e cinque script documentali PASS (primo tentativo privo del build SDK preservato come diagnostico).
- Suite completa: stato pytest PASS, conteggi {'errors': 0, 'failures': 0, 'skipped': 0, 'tests': 2174}, durata 2891.2086069819925 s; raccolta/JUnit e teardown del bootstrap nei raw log. Il PASS pytest, se presente, non qualifica il run: audit finale FAIL con 4 volumi anonimi residui, tutti attribuiti ai container ocor-spike-0019-* e al mount /etc/kafka/secrets attraverso osservazione prima/dopo e provenance. Nessuna verifica indipendente richiesta e nessuna evidenza candidata assemblata.
- Causa puntuale: KafkaCli.destroy, spikes/kafka_delivery/oracle.py:168, usa docker rm --force senza --volumes. L'immagine Kafka fissata dichiara /etc/kafka/secrets. Nessun difetto analogo attribuito a Qdrant: immagine fissata senza VOLUME. Registrata OCOR-DEV-REM-0022 dopo verifica in sola lettura dell ID libero in tutti i riferimenti locali/remoti/tag; scope e criteri eseguibili versionati in EXECUTION_STATE. Correzione in unita separata, non nel change set di test 0049.
- Cleanup di fine sessione eseguito soltanto sui 4 volumi provati nuovi, dangling e appartenenti al run; audit FAIL originale preservato. La pulizia successiva non corregge il teardown dei test. Quattordici ulteriori volumi nuovi senza prova di ownership conservati: la correlazione temporale non autorizza la cancellazione. Lo stesso difetto e presente nel lifecycle C5, backbone.py:235, incluso nello scope della remediation senza modificare la semantica degli eventi; riqualifica 0019/0040 e regressione 0041 richieste. Nessuna risorsa non OCOR toccata.
- Ruoli: implementazione isolamento/VF-001 Claude Code; oracolo backup e presente orchestrazione/evidenza Codex; verifier di REM-0019 Grok 4.7 via Cursor, NOT_REQUESTED. Verifier previsto di REM-0022 Claude Code per implementazione Codex. Budget REM-0019 invariato (repair_cycle 1). Staging task a5c7e681937f e governed c55c6b532d7e preservati senza qualifica o merge.
- Claims invariati: E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO; 69 task completati invariati, sealed evidence e inputs immutati. PR #169 e #176 lasciate aperte e invariate; WIP 0056 5edd6cd preservato.
- Prossima azione esatta: OCOR-DEV-REM-0022:implementation: new governed/ branch from origin/main in an isolated worktree; read versioned scope, demonstrate real pinned Kafka anonymous-volume leak RED in both lifecycle helpers with mount provenance, correct owned-resource lifecycle and qualify/requalify OCOR-DEV-0019 and OCOR-DEV-0040 with new superseding evidence, then request Claude Code verification. After verified closure resume REM-0019 repair_cycle 1 with fresh full regression and exact-head evidence, verifier Cursor/Grok; then REM-0017, integration 0049 and preserved 0056 WIP. No independent request on the hygiene-failed run.

## 2026-10-11T16:55:01.113429+00:00 — REM-0022: review supplementare e correzione del ruolo di verifica

- Unita unica: riallineamento dello stato e richiesta del verifier obbligatorio per il candidato REM-0022 a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8. Main pulita/allineata 63184cb250c5b385b06c98c69a227937b8ae8fb4; PR #213 merged, 13 required SUCCESS; PR #169/#176 e WIP 0056 preservati. Ready set ['OCOR-DEV-0049', 'OCOR-DEV-0056', 'OCOR-DEV-0057']; priorita REM-0022 come prerequisito del teardown REM-0019. Nessun nuovo task o ciclo di riparazione avviato.
- Il candidato versione a54ebb56955b e presente sul remoto e byte-invariato. Gate meccanici del candidato: 13/13 exit 0 (ruff, mypy strict, language, RCCAD, scope, piano sulla base reale 63184cb, drift, digest, controllo raw/JUnit/supersession, quattro validator evidence). Output planning generati ripristinati. Il checker riacquisisce hash e conferma integrita di raw, riqualifiche e storia sigillata. Non sono nuovi test runtime.
- Verdetto ricevuto OCOR-DEV-REM-0022-a54ebb56955b-0: GO_FOR_EVIDENCE_SEAL, zero finding, nessun NOT_EXECUTED; identita effettiva Grok 4.7 via Cursor CLI. Risultati del verifier: 45 mirati, 196 security e 1806 completa PASS senza skip, teardown finale/inventari coincidenti. La richiesta originale prevedeva Claude Code per REM-0022/0019/0040; il verdetto ricevuto e registrato come SUPPLEMENTAL_ONLY_ROLE_MISMATCH e resta immutabile. Non si attribuisce una verifica a Claude e non si inferisce autorizzazione dal routing del runner. Il verdetto esclude esplicitamente il riesame finale della riqualifica 0050.
- Richiesta preparata OCOR-DEV-REM-0022-a54ebb56955b-0-claude-role-review: stesso task/head/base, repair_cycle 0, Claude Code obbligatorio, contesto/processo/fornitore separati dall implementatore Codex. Il suffisso discrimina la nuova review di ruolo ed evita qualsiasi sovrascrittura del verdetto esistente; nessuna modifica materiale o ciclo consumato. Dopo GO Claude serve il distinto GO Cursor/Grok su 0050 (task toccato dalla riserva Claude Code). Entrambi i GO sul medesimo candidato sono prerequisiti di sigillo/PR; nessun verifier avviato qui.
- Preflight corrente: digest 8/8; harness 14 PASS; drift 69 task/180 input zero; 9 toolchain match incluso Java dell immagine fissata (JAVA_VERSION jdk-21.0.8+9). Primo comparatore esterno del preflight rifiutava il prefisso jdk-, diagnostico preservato; confronto della versione corretto senza cambiare lock o validator. Stack ricreato in worktree con credenziali esistenti e CA disposable locale, 11 servizi running/READY, SVID reale, nessun OOM/restart. Teardown completo, inventari Docker prima/dopo identici; risorse non OCOR e volumi storici preservati.
- Stato/handoff riferiscono per SHA256 i candidati rimasti sul branch sorgente; nessun record copiato, sigillato o riscritto. Completed_evidence_tasks restano 69. Inputs e produzione invariati; E1=0/E2=0/Verified=0, runtime NOT_ESTABLISHED e PoC/Production NO-GO. Prossima azione esatta: OCOR-DEV-REM-0022:verification — external loop executes OCOR-DEV-REM-0022-a54ebb56955b-0-claude-role-review with Claude Code on unchanged candidate a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8. Previous Cursor/Grok GO remains supplemental, immutable, not the required primary role. No seal or implementation PR. After Claude GO, request separate Cursor/Grok final review of OCOR-DEV-0050.requalified-rem0022 on the same HEAD; both exact-head GO verdicts required before sealing, exact-green CI merge and immediate state sync. With NO_GO apply ordinary REM-0022 budget. After verified closure resume REM-0019 repair_cycle 1 with fresh full regression, then REM-0017, 0049 integration and preserved 0056 WIP. No claim promotion.

- Gate del solo state sync: 9/9 exit 0, incluso piano sulla base reale main; JSON canonici. Non qualificano la chiusura REM-0022. Output verify/planning ripristinati prima del commit.

## 2026-10-11T17:53:46.724087+00:00 — REM-0022: GO primario Claude e richiesta distinta di riqualifica 0050

- Una sola unita di integrazione: registrazione del verdetto obbligatorio Claude e preparazione della review finale 0050, candidato remoto a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8 invariato e clean. Baseline main d369036d20847e61b77480457a20956a2783e5fd, PR #215 merged e 13 required SUCCESS acquisiti; #169/#176 e WIP 0056 preservati. Ready set ricalcolato ['OCOR-DEV-0049', 'OCOR-DEV-0056', 'OCOR-DEV-0057']; priorita REM-0022 per sbloccare REM-0019.
- Verdetto primario OCOR-DEV-REM-0022-a54ebb56955b-0-claude-role-review, hash f640f8a48bd5ac2e668841c5f27c6fff530ea9486082680383115484408fc22a: GO_FOR_EVIDENCE_SEAL, Claude Code claude-opus-5-5 (Anthropic), contesto/processo/fornitore separati dall implementatore Codex. Scope REM-0022/0019/0040. Mirati 45 PASS, completa 1806 PASS zero skip, inventari Docker identici. Il tentativo del verifier con Node host: 1798 PASS/8 FAIL, diagnostico conservato; run qualificante successivo con Node pinned. Non sono nuovi run dell implementatore.
- VF-001 medium, nonblocking, resta aperto: dopo perdita del container un retry di destroy puo dimenticare il volume anonimo. Nessun caller corrente ritenta; suite reale senza residui. Nessuna correzione o chiusura inferita dal GO; finding e prova conservati nello stato/handoff e nell hash del verdetto. Il precedente GO Cursor resta supplementare, immutabile.
- Richiesta OCOR-DEV-0050-a54ebb56955b-0-rem0022-requalification preparata per Cursor/Grok 4.7: riqualifica finale 0050 su stesso HEAD/base, repair_cycle 0, esplicita supersession, raw/hash e criteri completi da verificare. 0050 originale implementato dalla riserva Claude Code; riparazioni 1-2 e riqualifica corrente Codex. Claude ha espressamente escluso la disposizione finale 0050. Nessun verifier avviato, candidato non sigillato e nessuna PR implementativa prima del secondo GO.
- Preflight odierno: digest 8/8, harness 14 PASS, drift 69 task/180 input zero; 9 entry toolchain versione/digest coincidenti. Stack ricreato con segreti locali e CA disposable, SVID reale, 11 servizi READY, zero OOM/restart; teardown e inventari prima/dopo identici. Gate meccanici del candidato 13/13 exit 0 (raw/JUnit/supersession, input, quattro evidence validator, RCCAD/scope/piano su base originale esatta). Output planning ripristinati, nessun record riscritto. Suite completa dell implementatore in questa unita NOT_EXECUTED: nessuna modifica runtime, non necessaria alla sola sincronizzazione di stato.
- Completed invariati 69; inputs, produzione e sealed evidence invariati; E1=0/E2=0/Verified=0, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Prossima azione: OCOR-DEV-0050:rem0022-requalification-verification — external loop executes OCOR-DEV-0050-a54ebb56955b-0-rem0022-requalification with Cursor/Grok 4.7 on unchanged candidate a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8. Do not launch verifier in implementer context. Primary Claude GO for REM-0022/0019/0040 is acquired; VF-001 medium teardown retry finding remains OPEN_NONBLOCKING (no current retry caller). Only after exact-head Cursor GO: record both verifier identities/verdicts in new candidate evidence, retain open finding, seal and run required CI/merge with exact HEAD, then immediate state sync. With NO_GO repair within the ordinary REM-0022 budget; never rewrite historical sealed records. Resume REM-0019 repair_cycle 1 with fresh full regression after verified REM-0022 closure, then REM-0017, 0049 integration and preserved 0056 WIP. Claims unchanged.

- Gate del solo state sync: 9/9 exit 0; JSON canonici, ruff/mypy strict verdi, piano sulla base reale d369036 PASS 37/2 NOT_EXECUTED opzionali. Output planning/verify ripristinati; questi gate non sigillano ne chiudono REM-0022.

## 2026-10-11T18:35:20.699130+00:00 — REM-0022: GO 0050 supplementare, routing Cursor vincolato alla richiesta

- Unita unica: state sync della review 0050 ricevuta e correzione locale del routing, candidato remoto a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8 invariato/clean. Main e7db09b67416ac57cdb3883601895089dcece914; PR #216 merged, 13 check obbligatori SUCCESS. PR #169/#176 e WIP 0056 preservati; ready set ricalcolato ['OCOR-DEV-0049', 'OCOR-DEV-0056', 'OCOR-DEV-0057']. Nessun nuovo task, sigillo o ciclo di riparazione.
- Verdetto OCOR-DEV-0050-a54ebb56955b-0-rem0022-requalification, SHA256 8f92d1275456ed4b074638cf83f15c81aa57837b3d0188d5224361794ba13a74: GO_FOR_EVIDENCE_SEAL tecnico, verifier effettivo Claude Code/claude-opus-5-5. Verifier della riqualifica 0050 obbligatorio Cursor/Grok per il mandato corrente (implementazione originale riserva Claude). Il verdetto dichiara esplicitamente di non essere Cursor; VF-001 low nonblocking documenta il disallineamento. Disposition SUPPLEMENTAL_ONLY_ROLE_MISMATCH: nessuna autorizzazione inferita e verdetto preservato byte per byte. Risultati dichiarati dal verifier: 198 mirati, completa 1806 PASS, zero skip, teardown identico; non sono run nuovi dell implementatore. GO primario Claude per REM-0022/0019/0040 confermato; VF-001 medium retry di teardown resta OPEN_NONBLOCKING.
- Causa riprodotta in sola lettura: ocor-loop2.sh rr. 76–82 sceglie claude per default e ignora verifier della richiesta; il flag temporaneo .claude_impl_active non conserva la storia dell implementatore. Usato soltanto il meccanismo verifier_override gia presente: aggiunta la riga esatta `OCOR-DEV-0050-a54ebb56955b-0-rem0022-cursor-role-review cursor`, backup locale prima della modifica, hash prima 10feb62e4271201d177867c64a717463b01d01b516ab10c25cb6d4e794cdbf5d, dopo 97be0fbed1c594de9b28d35b53b2defa940aeaa192d670066c08d0a0427e5760. Dry selection usa il medesimo blocco del runner e restituisce cursor; route 0049/REM-0019 conservate cursor, REM-0022 conservata claude. Runner e prompt invariati. Non e una verifica indipendente e nessun verifier e stato lanciato.
- Richiesta distinta OCOR-DEV-0050-a54ebb56955b-0-rem0022-cursor-role-review, stesso HEAD/base e repair_cycle 0: suffisso evita sovrascrittura del verdetto; ruoli, supersession, raw/hash e criteri completi conservati. Verifier richiesto Grok 4.7 via Cursor in contesto/processo/fornitore separati, non Claude. Richiesta pubblicata al loop solo dopo l integrazione esatta dello state sync.
- Preflight riacquisito: digest 8/8, harness 14 PASS, drift 69 task/180 input zero; 9 strumenti versione/digest coincidenti. Stack disposable: 11 servizi READY, SVID reale, zero restart/OOM, teardown e inventari identici. Gate candidati 13/13 exit 0, incluse integrita raw/JUnit/supersession e immutabilita della storia; output planning ripristinati. Suite completa dell implementatore in questa unita NOT_EXECUTED (solo stato/routing, nessuna modifica runtime).
- Completed 69 e claim invariati: E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Inputs, produzione, candidati e record sigillati immutati. Prossima azione esatta: OCOR-DEV-0050:rem0022-requalification-verification — external loop executes OCOR-DEV-0050-a54ebb56955b-0-rem0022-cursor-role-review with Cursor/Grok 4.7 on unchanged candidate a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8; exact-id local verifier_override selects cursor (selection tested, no verifier launched). Previous 0050 Claude GO is SUPPLEMENTAL_ONLY_ROLE_MISMATCH and immutable; it cannot satisfy the PO role requirement. Primary Claude GO for REM-0022/0019/0040 remains acquired. Only after exact-head Cursor GO: record actual identities/verdicts in new candidate evidence, preserve REM-0022 VF-001 medium OPEN_NONBLOCKING, seal, open implementation PR, required exact-green CI merge and immediate state sync. With NO_GO apply ordinary REM-0022 budget. No repair cycle consumed by this role review. After verified REM-0022 closure resume REM-0019 repair_cycle 1 with fresh full regression, then REM-0017, 0049 integration and preserved 0056 WIP. Claims unchanged.

- Gate dello state sync: 9/9 exit 0, JSON canonici, ruff/mypy strict verdi, scope/RCCAD/piano sulla base main esatta; piano 37 PASS e 2 NOT_EXECUTED opzionali invariati. Nessuna qualifica runtime dedotta da questi gate.

## 2026-10-11T19:40:16.020778+00:00 — REM-0022: NO_GO Cursor 0050 e registrazione REM-0023

- Unita unica di integrazione/disposition: ricevuto OCOR-DEV-0050-a54ebb56955b-0-rem0022-cursor-role-review all HEAD a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8, SHA256 a17f06afc721d5a7c09ef6d40c54dabfe19ed8cc1796425d21bbd461e419d744; verifier effettivo Grok 4.7 via Cursor, NO_GO, VF-001/VF-002 HIGH blocking, nessun NOT_EXECUTED. GO Claude su REM-0022/0019/0040 e GO supplementari rimangono storici, con ambito originale; non autorizzano il sigillo del candidato bocciato. Nessun verifier avviato e nessun nuovo request preparato.
- VF-001 confermato in sola lettura: cinque copie dei raw log candidati (assurance REM-0022, evidence REM-0022/0019/0040/0050) contengono una credenziale disposable. Osservazione safe con conteggi/hash in /home/luca/.ocor-codex/rem0022-nogo/credential-exposure-safe-observation.json, SHA256 3fe56653ae24d7da4da77041ee21e73c3d51bcf3ab2c6db9ea66ad981c628fa2; nessun valore sensibile stampato o copiato nello stato. Raw non qualificanti; riacquisizione richiesta correggendo prima il generatore, senza catturare sorgente worker interpolato. Credenziale non ruotata in questa unita di solo stato; la riparazione deve verificarne l utilizzabilita e ruotare soltanto credenziali locali possedute, se necessario.
- VF-002 confermato normativamente: ADD v1.3 Part II 2.6 assegna denial evidence all audit authority; LLD 2.8.2 prescrive audit nell admission. model.py:1209–1346 ha rifiuti prima dell audit solo di successo e del ledger append. Scope estraneo alla remediation Kafka: registrata OCOR-DEV-REM-0023, prossimo ID libero verificato su 280 ref locali/remoti/tag e metadati correnti, senza ricostruire prior; proof SHA256 a7724920a316783e68fcde80e0744acc9cf22cacbeba635a74f4bce64b817570. Scope, positivi/negativi/fault, riqualifica 0050, rollback, gate e ruoli versionati in execution state e handoff. GO/seal 0050 storici preservati; non e un ciclo 3 di 0050. G5 closure/G6/G7 dipendono dalla nuova remediation.
- REM-0022 resta NON sigillata/mergiata. Nessuna riparazione materiale eseguita: repair_cycle 0 registrato, prossima correzione igiene = ciclo 1/2. VF-001 medium del retry di teardown Claude resta OPEN_NONBLOCKING; nessuna chiusura implicita. Branch Kafka e futura admission remediation distinti; un eventuale staging combinato deve dichiarare scope e ricevere review esatta per entrambi, senza bypassare dipendenze non verificate.
- Preflight riacquisito: main ba98ff633fa5d9e6fe5c16be9a534583dca29bb0 pulita/allineata, PR #217 merged con 13 required SUCCESS; digest 8/8, harness 14 PASS, drift 69 task/180 input zero; toolchain 9 entry versione/digest match. Stack pinned ricreato, SVID reale, 11 READY, zero restart/OOM; teardown PASS, inventari prima/dopo identici. PR #169/#176 e WIP 0056 preservati. Ready set dal backlog ['OCOR-DEV-0049', 'OCOR-DEV-0056', 'OCOR-DEV-0057']; priorita sulle remediation. Suite runtime completa in questa unita NOT_EXECUTED: nessuna modifica runtime; questi preflight non chiudono finding.
- Ruoli: Codex per questo state sync e futura REM-0023; Claude per scope REM-0022 solo Codex; Cursor/Grok obbligatorio per riqualifica 0050, originale riserva Claude. Nessuna modifica a inputs, produzione, backlog o record sigillati. Completed invariati 69, E1=0/E2=0/Verified=0, runtime NOT_ESTABLISHED, PoC/Production NO-GO.
- Prossima azione esatta: OCOR-DEV-REM-0022:repair1-evidence-hygiene — resume isolated worktree .ocor/worktrees/rem-0022 on governed/ocor-dev-rem-0022-kafka-resource-lifecycle from unchanged remote a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8. Read versioned NO_GO disposition and ~/.ocor-codex/rem0022-nogo/credential-exposure-safe-observation.json; fix the raw-capture generator outside Git before rerunning qualifying commands. Never capture an interpolated worker source or a DSN/password. Verify whether the exposed disposable credential remains usable and rotate only owned local test credentials if necessary; do not print secrets. Reacquire all five affected raw-log copies (REM-0022 assurance/evidence, 0019, 0040, 0050), recompute candidate record/manifest hashes, rerun exact-head gates, preserve failure history and sealed records. No new verification request or seal while VF-002 is open. Next distinct unit is OCOR-DEV-REM-0023 implementation on a governed branch from origin/main: admission denial audit, RED before code, fresh superseding 0050 qualification and Cursor/Grok verification. Keep REM-0022 Kafka code and REM-0023 admission code in separate source branches; any combined qualification staging must be explicit and reviewed on its exact HEAD for both scopes, never merged as an unverified dependency or claimed green after hygiene failure. After fixes request primary Claude review for REM-0022/0019/0040 and required Cursor/Grok for 0050 on the final candidate; old-head GO cannot authorize the changed HEAD. Then resume REM-0019 repair_cycle 1 with fresh full regression, REM-0017, 0049 integration and preserved 0056 WIP. No task or claim promotion.

- Gate del solo state sync: 9/9 exit 0 (digest, ruff, mypy strict, RCCAD, scope, piano sulla base main esatta, language, drift, evidenza storica 0055). Piano 37 PASS/2 NOT_EXECUTED opzionali. Output planning/verify ripristinati; nessuna chiusura runtime dedotta.

## 2026-10-11T20:05:12.156981+00:00 — REM-0022: disposition PO, rettifica VF-001 e review di sola regressione 0050

- Unita unica: applicazione della decisione esplicita REM-0022-0050-ROLE-REVIEW-DISPOSITION (2026-10-11). Candidato a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8 invariato, worktree/remoto clean e coincidenti; nessun nuovo sigillo, codice o ciclo di riparazione. Verdetto NO_GO OCOR-DEV-0050-a54ebb56955b-0-rem0022-cursor-role-review e tutti i finding preservati byte per byte, SHA256 a17f06afc721d5a7c09ef6d40c54dabfe19ed8cc1796425d21bbd461e419d744.
- ERRATUM della voce precedente: VF-001 respinto dal PO come falso positivo. I 42 caratteri sono `'+values['OCOR_LOCAL_POSTGRES_PASSWORD']+'`, espressione nel sorgente del worker, non una password. Cinque copie raw, cinque worker per copia parsati AST in sola lettura; proof /home/luca/.ocor-codex/rem0022-po-disposition/vf001-correction-proof.json SHA256 edd07bf887364ee374965f576061be6e1295d1e87ad23b65976902cb6fc08c1e. La precedente osservazione che classificava il sorgente come credenziale era errata e resta storica. Nessuna password letterale nei log o nella storia pubblicata secondo la revisione del PO; nessuna rigenerazione/rotazione necessaria.
- VF-002 fondato, preesistente e fuori ambito REM-0022: riutilizzato OCOR-DEV-REM-0023 gia registrato con allocation proof, nessun nuovo ID. Ambito: audit authority su ogni diniego admitMemory, ledger invariato, audit failure fail-closed; RED/GREEN backend reali per famiglia/fault, OpenAPI invariato, nuova supersession 0050 senza riscrivere sigilli. Dipendenza obbligatoria G5; esecuzione DOPO REM-0019 e REM-0017, PR 0049, PRIMA della ripresa 0056. Rimosso soltanto il blocco di REM-0022 derivato dall ambito errato: nessuna dichiarazione di difetto risolto.
- Richiesta distinta OCOR-DEV-0050-a54ebb56955b-0-rem0022-regression-po-disposition, medesimo HEAD/base, repair_cycle 0, review_type REMEDIATION: SOLA REGRESSIONE dei 198 test esistenti 0050 invariati dopo estensione puntuale allowlist, integrita hash/raw/supersession; nessuna rivalutazione conformance 0050. NO_GO precedente e review non consumano budget per decisione PO. Implementazione originale 0050 Claude Code (riserva), riparazioni 1–2 Codex, riqualifica REM-0022 Codex; verifier richiesto Grok 4.7 via Cursor, fornitore/processo/contesto separati. GO primario Claude REM-0022/0019/0040 conserva ambito e finding medium retry OPEN_NONBLOCKING.
- Routing: riga exact-id aggiunta al meccanismo verifier_override gia esistente, backup precedente preservato. Dry selection usa il blocco reale del loop: Cursor per nuova richiesta/0049/REM-0019, Claude per REM-0022; nessun verifier avviato, prompt/runner invariati. Richiesta pubblicata solo dopo merge exact-green dello state sync; nessuna sovrascrittura di verdetti o richiesta pendente.
- Preflight: main 853f9a5fbcebf9ee0ed01aa4bb3f6ca83982570e pulita/allineata, PR #218 merged con 13 required SUCCESS. Digest normativi 8/8, harness 14 PASS, drift 69 task/180 input zero; 9 entry toolchain versione/digest match. Stack pinned disposable ricreato: 11 READY, SVID reale, zero restart/OOM; teardown PASS e inventari identici. Integrita meccanica candidato 4 record, 1806 casi full/243 task storici, supersession/JUnit/hash/history invariati PASS (non nuova esecuzione delle suite). Suite completa implementatore in questa unita NOT_EXECUTED, solo stato/richiesta. PR #169/#176, WIP 0056 e candidati REM-0019 preservati; ready set ['OCOR-DEV-0049', 'OCOR-DEV-0056', 'OCOR-DEV-0057'], priorita remediation PO.
- Stato/handoff aggiornati canonici; completed 69, E1=0/E2=0/Verified=0, runtime NOT_ESTABLISHED, PoC/Production NO-GO invariati. Scritture repository limitate a tre file di stato/log in reports/development; inputs, backlog, validator, workflow, candidati, raw e sigilli immutati.
- Prossima azione esatta: OCOR-DEV-0050:rem0022-regression-verification — external loop executes OCOR-DEV-0050-a54ebb56955b-0-rem0022-regression-po-disposition with Grok 4.7 via Cursor on unchanged a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8. Scope is ONLY regression: 198 existing 0050 tests unchanged after the exact-path planning allowlist extension; evidence integrity/supersession and historical records preserved; no 0050 conformance reassessment. PO REM-0022-0050-ROLE-REVIEW-DISPOSITION rejects VF-001 as literal worker-source expression (false positive) and accepts VF-002 as preexisting, outside REM-0022, tracked OPEN in REM-0023. Prior NO_GO and this review consume no repair cycles. Primary Claude GO for REM-0022/0019/0040 remains valid on unchanged exact candidate; medium retry finding stays OPEN_NONBLOCKING. Only after exact-head Cursor regression GO: seal REM-0022, open implementation PR, required exact-green CI merge with match-head-commit and immediate state sync. Then resume REM-0019 repair_cycle1 with fresh full regression, REM-0017, merge 0049, and implement REM-0023 before resuming preserved 0056 WIP. REM-0023 is mandatory for G5 closure, not for REM-0022 seal. No task/claim promotion in this state sync.

- Gate locali del solo state sync: 9/9 exit 0 (digest, ruff, mypy strict, RCCAD, scope, piano sulla base main esatta, language, drift, evidenza storica 0055); piano 37 PASS/2 NOT_EXECUTED opzionali, output planning ripristinati. Nessuna esecuzione runtime nuova o chiusura dedotta.


## 2026-10-11T21:12:50.423424+00:00 — REM-0022: integrazione con sigillo conservato, CI FAIL, supersession distinta pronta

- Unita unica di integrazione. Acquisito GO Grok Cursor OCOR-DEV-0050-a54ebb56955b-0-rem0022-regression-po-disposition, sola regressione 198 test per decisione PO; GO primario Claude REM-0022/0019/0040 invariato. Sigillati quattro nuovi record sul branch originale, hash/ruoli/scope/finding/PO disposition in evidenza, manifest chirurgici e assurance; commit e8449a91e7f1bb918905d81992db81e447e36e8a, PR #220 aperta. Soli metadati e tre file di stato rispetto al candidato verificato, codice/test invariati.
- PR #220 NON unita: check supply-chain FAIL, run 38174953732, 15 segnalazioni sui nomi dei test parametrizzati nei JSON/manifests di riqualifica 0040/0050; static/dependencies zero finding. Proof sintetico in /home/luca/.ocor-codex/rem0022-integration/synthetic-node-proof.json SHA256 0931c27f2eae3c8e35abe8a72bdc1e3c49dc732d51ede382f4ec8da57e10e4e6: ciascuna stringa e un node ID esatto del JUnit qualificante, solo due famiglie di test gia approvate. Lo scanner resta FAIL; nessun bypass, waiver, retry transitorio o presunta chiusura. I raw e i sigilli su e8449a9 restano byte-identici.
- Riparazione implementabile senza decisione normativa: NUOVO branch da main, soli sorgenti Kafka gia verificati, record/ID/path distinti e supersession commit/path/hash verso il sigillo conservato; nomi base e mapping content-addressed uno-a-uno dei casi al JUnit, nessun payload sintetico inline nei metadati scansionati. Scanner invariato, stessi casi/asserzioni, nuova evidenza/gate e entrambe le verifiche indipendenti sull HEAD nuovo. Nessuna riparazione materiale eseguita qui; prossimo ciclo 1/2. Non riscrivere il sigillo, non rinominare/saltare test e non usare i GO vecchi per il nuovo candidato.
- Preflight PASS digest 8/8, harness 14 PASS, drift zero 69 task/180 input, toolchain 9/9, undici READY/SVID reale, zero restart/OOM e inventari prima/dopo identici. Bootstrap aveva rimosso lint: diagnostico mypy NOT_AVAILABLE, ripristino con uv sync --frozen --extra test --extra lint e 13/13 gate exit 0. Nessuna nuova suite runtime in questa unita di metadati; run qualificanti originari e verifier preservati.
- Finding retry Kafka OPEN_NONBLOCKING, denial audit admission OPEN in REM-0023; falsopositivo VF-001 precedente respinto dal PO senza modificare il verdict. Completed invariati 69; E1=0/E2=0/Verified=0, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Inputs/backlog/scanner/workflow/record storici invariati; PR 169/176 e WIP 0056 preservati.
- Prossima azione esatta: OCOR-DEV-REM-0022:repair1-ci-evidence-supersession — use NEW isolated worktree .ocor/worktrees/rem-0022-ci-evidence on governed/ocor-dev-rem-0022-ci-evidence-supersession from latest origin/main. Preserve published sealed branch governed/ocor-dev-rem-0022-kafka-resource-lifecycle at e8449a91e7f1bb918905d81992db81e447e36e8a and all sealed records/raw/verdict bytes; PR #220 stays open and unmerged. Port only the already-reviewed Kafka lifecycle code/test and exact plan extension from a54ebb5; no production or test semantic changes. Emit DISTINCT candidate record/raw paths with new record IDs and explicit supersedes pointing to sealed originals via commit/path/hash; do not overwrite or remove originals. For parameter cases use base test names plus SHA-256 identities mapped one-to-one to exact raw JUnit node IDs, retaining all cases/counts/assertions/traceability. No inline synthetic payloads in scanned metadata; scanner remains unchanged and must pass, not waived. Register exact new paths in the planning allowlist and requalify 0050 after any validator-input change; preserve original main evidence. Read synthetic-node-proof.json and failed supply-chain artifact. RED on original scanner, GREEN on new tree; meaningful positive/negative identity/count/hash checks; final task/full/reports regression and all gates with locked toolchain, reset/bootstrap/health, zero skip/residue/restart/OOM and collection/JUnit equality. A fresh candidate requires Claude Code primary review for REM-0022/0019/0040 and Cursor/Grok regression-only review for 0050 on exact new HEAD; never reuse old-head GO as authorization for changed metadata. External loop launches verifiers only. repair_cycle 1 for material repair, ordinary budget 2; no repair performed in this state-only unit. After exact-green verified supersession merge: REM-0019 cycle1 fresh full regression; REM-0017; merge 0049; REM-0023 before preserved 0056 WIP. E1/E2/Verified and claims unchanged.

- Gate dello state sync: 9/9 exit 0, piano 37 PASS e 2 NOT_EXECUTED opzionali. Primo AFF-008 diagnostico dovuto a riferimenti handoff di file non presenti su main: corretto distinguendo evidence_paths locali dalle branch_evidence_paths content-addressed; validator invariato. Planning generato archiviato/ripristinato. CI PR220 osservata: 9/13 required verdi, supply-chain FAIL; ulteriori check ancora in corso restano PENDING, mai PASS. Nessun rerun del fallimento deterministico.


## 2026-10-11T22:20:40.672142+00:00 — REM-0022 repair 1: supersession distinta dei metadati CI

- Unica unita implementativa; branch governed/ocor-dev-rem-0022-ci-evidence-supersession da main 355490ecd5fc28db999b1374c9adeddf95c64e23, sorgente qualificato 7c6daa7b3c3ac1dd80924fb39decd2e961db1e32. Kafka oracle/backbone e 22 test identici al candidato gia verificato a54ebb5. Sigillo e8449a9/PR220, raw e verdetti preservati; nessun record sigillato modificato o GO storico riusato. Nuovi ID/path con supersession commit/path/hash verso i quattro sigilli. Scanner/workflow/backlog/inputs invariati.
- RED scanner invariato sul sigillo: 15 finding; GREEN sul nuovo tree: zero. Metadati: nomi base e SHA256 delle identita esatte; ogni caso risolve uno-a-uno al JUnit raw verbatim, compresi parametri sintetici. Dieci test del mapping PASS con negativi mancanti/duplicati/sostituiti/aggiunti/non-qualificanti/hash alterati. Checker riproducibile content-addressed, allowlist estesa solo per path esatti e 0050 riqualificato con nuova regressione, senza riesaminare conformance o riscrivere sigilli.
- Preflight digest 8/8, harness 14 PASS, drift zero, toolchain lock 9/9, undici READY/SVID reale. Preparazione iniziale FAIL per doppia registrazione SPIRE, nessuna suite avviata. Errore operativo successivo: controllo fase arrivato dopo avvio task e shell proseguita al reset; run 2 casi/exit2 interrotto dal watchdog, diagnostico FAIL conservato. Worker successivo fermato prima delle suite; assertion nuova del mapping corregge controllo del carattere della cornice JSON anziche dei valori. Teardown e ripartenza pulita; nessun fallimento rietichettato o usato come prova. Mypy iniziale NOT_AVAILABLE dopo bootstrap senza lint; dopo sync --extra test --extra lint i gate strict passano, diagnostico non qualificante. Ultima integrazione PR221 osservata 13/13 required SUCCESS, ruleset23412233 active e zero bypass. Prima campagna pulita sorgente 0f2b681: 243/1806 PASS preservati in qualified-before-checker-relocation; successivo language gate FAIL per collocazione checker, risolto spostandolo in reports/tests (codice identico, policy/validator invariati). Campagna intera riacquisita sul nuovo commit. Planning iniziale FAIL sul self-hash del validator esteso; auto-acquisizione governata e secondo passaggio 37 PASS/2 NOT_EXECUTED opzionali, diagnostico preservato.
- Campagna finale sul sorgente pulito: task 243 PASS (REM22 22, 0019 8, 0040 7, 0041 8, 0050 198), full 1806 PASS zero skip/failure/error, unione collection/JUnit esatta; reports 48 PASS e cinque script collegati exit0. Durata task 216.477 s, full 673.472 s; watchdog zero restart/OOM/exit, inventari task/full/sessione identici, teardown PASS. Ruff/mypy strict e gate locali PASS; eventuali NOT_EXECUTED opzionali del planning restano dichiarati. Nessun incremento probatorio o di claim.
- Ruoli: implementatore Codex; primary verifier richiesto Claude Code per REM-0022/0019/0040; verifier Grok 4.7 via Cursor per SOLA REGRESSIONE dei 198 test invariati di 0050, originale Claude riserva/riparazioni Codex. Due GO sull HEAD nuovo obbligatori prima del sigillo. Nessun verifier avviato. Finding medium retry OPEN_NONBLOCKING, audit diniego admission OPEN in REM-0023 (G5), VF-001 rigettato dal PO resta storico. Completed invariati 69; E1=0/E2=0/Verified=0, runtime NOT_ESTABLISHED, PoC/Production NO-GO. PR169/176/220 e WIP0056 preservati.
- Prossima azione: OCOR-DEV-REM-0022:repair1-independent-verification — external loop launches Claude Code primary review of REM-0022/0019/0040 on the exact new candidate HEAD recorded in ~/.ocor-codex/verify_request.json. Then publish ~/.ocor-codex/rem0022-ci-evidence/secondary-request-staged.json as verify_request.json for Grok 4.7 via Cursor on the SAME HEAD for ONLY regression of all 198 unchanged OCOR-DEV-0050 tests and integrity/supersession after exact-path allowlist extension; no reassessment of 0050 conformance. Do not seal until BOTH exact-head GO verdicts; previous GO at a54ebb5 is historical, not authorization for this candidate. Preserve sealed e8449a9 branch/PR220 and all verdict/raw/record bytes. Upon both GO, seal distinct records, exact-green required CI merge and immediate state sync. Then REM-0019 cycle1 fresh full regression, REM-0017, 0049 integration, REM-0023 before preserved 0056 WIP. Retry finding OPEN_NONBLOCKING; admission denial audit OPEN in REM-0023. E1/E2/Verified/claims unchanged.


## 2026-10-11T22:51:52.714484+00:00 — REM-0022: GO primario esatto e richiesta Cursor di sola regressione 0050

- Unita unica di acquisizione verdetto/richiesta: candidato a9d2ffe6f14799a678f935bd2eb939438bd0fae5 clean e coincidente col remoto. GO Claude Code OCOR-DEV-REM-0022-a9d2ffe6f147-1, SHA256 14e961ec14b8d22e0dc213993a06e9c64203bb35c03976f2cb1dfb84d0859d53; nessun finding bloccante o NOT_EXECUTED del verifier. Riesecuzione indipendente 1806 runtime PASS/zero skip, reports 58 PASS, gate verdi. Questo e il risultato del verifier, non una suite nuova di questa unita.
- VF-001 medium retry Kafka OPEN_NONBLOCKING preservato. VF-002 low reperibilita sigillo OPEN_NONBLOCKING: e8449a9 e ancora raggiungibile dal branch remoto governed/ocor-dev-rem-0022-kafka-resource-lifecycle; PR220 resta aperta e il branch non va eliminato. Comando riproducibile: git fetch origin refs/heads/governed/ocor-dev-rem-0022-kafka-resource-lifecycle. Conservazione permanente da completare prima della chiusura PR220; nessuna dichiarazione di finding chiuso.
- Richiesta distinta OCOR-DEV-0050-a9d2ffe6f147-0-rem0022-ci-regression, stesso HEAD/base, repair_cycle0 e review_type REMEDIATION, SOLA REGRESSIONE dei 198 test 0050 invariati e integrita/supersession dopo allowlist. Codex implementatore REM-0022/riqualifica; 0050 originale Claude Code riserva, riparazioni1-2 Codex. Verifier richiesto Grok4.7 via Cursor (terzo fornitore/processo/contesto). Routing exact-id gia presente, nessun runner/prompt cambiato e nessun verifier avviato. Pubblicazione dopo merge exact-green dello state sync. Nessun ciclo consumato.
- Preflight riacquisito: digest8/8, harness14 PASS, drift69 task/180 input zero, toolchain9/9; stack pinned disposable undici READY, SVID reale, zero restart/OOM, teardown PASS e inventari identici. Suite completa implementatore NOT_EXECUTED: soli tre file stato/log modificati. PR220 supply-chain FAIL, altre12 required SUCCESS; niente rerun del fallimento deterministico o merge. PR221 main13/13 required SUCCESS. PR169/176 e WIP0056 preservati.
- Completed invariati69, ready set ['OCOR-DEV-0049', 'OCOR-DEV-0056', 'OCOR-DEV-0057']; priorita remediation PO. Inputs, backlog, codice/test, candidati, raw e tutti i sigilli/verdetti immutati. E1=0/E2=0/Verified=0, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Due GO esatti obbligatori prima del sigillo. Admission denial audit resta OPEN REM-0023.
- Prossima azione esatta: OCOR-DEV-0050:rem0022-ci-regression-verification — external loop executes OCOR-DEV-0050-a9d2ffe6f147-0-rem0022-ci-regression with Grok 4.7 via Cursor on unchanged exact candidate a9d2ffe6f14799a678f935bd2eb939438bd0fae5. Scope ONLY regression of 198 unchanged 0050 tests after exact-path allowlist additions, plus evidence integrity/supersession; no 0050 conformance reassessment. Primary Claude Code GO for REM-0022/0019/0040 acquired on this SAME HEAD. Both GO barriers required before sealing distinct records and opening supersession PR. Preserve sealed e8449a9, remote branch governed/ocor-dev-rem-0022-kafka-resource-lifecycle and open PR220 until permanent reachability is established. Medium Kafka teardown retry finding OPEN_NONBLOCKING, low historical-ref finding OPEN_NONBLOCKING with fetch ref documented. Admission denial audit OPEN in REM-0023, outside regression scope. After exact-head Cursor GO: seal distinct records with actual verifier identities and findings; open supersession PR; all 13 required checks SUCCESS on exact HEAD; merge --match-head-commit and immediate state sync. Then REM-0019 repair1 fresh full regression, REM-0017, merge 0049, REM-0023 before preserved 0056 WIP. No new repair cycle consumed by this state/review-request unit. E1/E2/Verified/claims unchanged.

- Gate locali dello state sync: 9/9 exit0, ruff/mypy strict, RCCAD/scope/piano sulla base main esatta, language, drift, digest ed evidenza storica0055; piano37 PASS/2 NOT_EXECUTED opzionali preesistenti. JSON canonici. Nessuna nuova qualifica runtime dedotta.


## 2026-10-11T23:46:56.116528+00:00 — REM-0022: integrazione supersession con due GO esatti

- Unita unica di integrazione; candidato a9d2ffe6f14799a678f935bd2eb939438bd0fae5 verificato da Claude Code (claude-opus-5-5) per REM-0022/0019/0040 e Grok 4.7 Cursor per SOLA REGRESSIONE 0050. Implementatore Codex; 0050 originale Claude riserva, riparazioni1-2 Codex. Verdetti verbatim e diagnostici invariati, hash riferiti nei quattro nuovi sigilli. Nessun verifier avviato, nessun ciclo consumato.
- Raw, casi/asserzioni, sorgenti, checker, scanner, validator e workflow invariati. Solo sigillo/manifest/assurance e tre file stato, main 8a5081f6030c297eb58188f681c4c125b06918db dal candidato cambia esclusivamente stato. Checker pre-sigillo PASS sul candidato; non modificato per accettare sigilli. Sigilli storici preservati; ref e8449a9/PR220 conservata con comando fetch documentato. Kafka retry OPEN_NONBLOCKING, admission denial audit OPEN REM-0023.
- Preflight digest8/8, harness14 PASS, drift zero, toolchain9/9, undici servizi READY, zero restart/OOM; teardown PASS inventari identici. Suite runtime completa implementatore in questa unita NOT_EXECUTED: i run qualificanti candidato e verifier restano storici, nessun comportamento modificato.
- Prossima azione: OCOR-DEV-REM-0022:integration — await all 13 required checks SUCCESS on exact sealed HEAD; one rerun only for transient infrastructure, never deterministic FAIL. Merge --merge --match-head-commit, verify record/raw/source/hash invariance; immediate governed state sync. Then REM-0019 repair_cycle1 fresh full regression, REM-0017, 0049 integration, REM-0023 before preserved 0056 WIP. Preserve sealed e8449a9 and remote historical ref/PR220. No claim promotion.
- Completed69 ed E1=0/E2=0/Verified=0, runtime NOT_ESTABLISHED, PoC/Production NO-GO invariati. PR169/176/220 e WIP0056 preservati.

- Gate post-sigillo13/13 exit0 (scanner invariato, ruff/mypy strict, RCCAD/scope/piano, language, drift, digest e quattro runtime evidence). Piano37 PASS/2 NOT_EXECUTED opzionali preesistenti. Invarianti: record cambiano solo sigillo/ruoli/finding/ref storica; commit/input/comandi/raw e codice/test byte-identici. Nessun NOT_EXECUTED etichettato PASS.


## 2026-10-12T00:06:07.880473+00:00 — REM-0022: supersession sigillata integrata exact-green, ripresa REM-0019 pronta

- Unita unica di integrazione conclusa: PR223 merge 808ad78359cdc7a7975d583b5285c94db55c4e78 da sigillo 9b766c0366e4278f51dffaf5ef97b1acc1e928d4, tutti13 required SUCCESS sull HEAD esatto, ruleset23412233 attivo/zero bypass, nessun rerun. Run CI 38185627718, 38185627720, 38185627721, 38185627728, 38185627747, 38185627853. Merge --merge --match-head-commit; origin/main coincide e sigilli/raw/input/source immutati verificati. Due GO sul candidato a9d2ffe6f147: Claude Code (claude-opus-5-5) REM22/0019/0040; Grok4.7 Cursor SOLA REGRESSIONE198 casi0050, non conformita. Implementatore Codex, originale0050 Claude riserva. Nessun verifier avviato.
- Remediation22 RESOLVED_VERIFIED_MERGED, storici PR220/e8449a9 e verdetti/raw/sigilli preservati. Retry teardown e ref storica OPEN_NONBLOCKING; admission denial audit OPEN REM23. Rischi non dichiarati chiusi.
- REM19 ciclo1 resta OPEN: rimossa soltanto la precondizione igiene, riparazione test/fixture preservata. Va rieseguita intera campagna finale collection/reverse/tre seed/isolati e nuova full regression; nessun run diagnostico o stantio riusato. PR169/176 e WIP0056 preservati.
- Preflight reale11 READY, toolchain9/9, digest8/8, harness14 PASS, zero drift/restart/OOM/residui, teardown inventari identici. Gate integrazione13/13 exit0. Suite runtime implementatore in questa unita NOT_EXECUTED per soli metadati/stato; run qualificanti candidato/verifier preservati e non rivendicati come nuovi.
- Stato/handoff canonici aggiornati; completed69 e ready ['OCOR-DEV-0049', 'OCOR-DEV-0056', 'OCOR-DEV-0057'] invariati, priorita PO applicata. E1=0/E2=0/Verified=0, runtime NOT_ESTABLISHED, PoC/Production NO-GO. Scritture state-sync solo reports/development, nessun input/backlog/codice/test/sigillo modificato.
- Prossima azione esatta: OCOR-DEV-REM-0019:repair1-qualification-resume — use preserved .ocor/worktrees/rem-0019 on governed/ocor-dev-rem-0019-0049-test-isolation. Read main state and previous_rem0019_reference, ~/.ocor-codex/rem-0019-r1m/HANDOFF.md and historical NO_GO/marker diagnostic. Merge latest origin/main into preserved WIP without force-push, retaining complete test/fixture and structural ciphertext repair; production0049 unchanged. Preserve existing task stage .ocor/worktrees/rem0019-task-stage and governed evidence stage .ocor/worktrees/rem0019-governed-stage, with exact tree equivalence and scope gates; do not merge governance into task before scope CI. REM-0022 verified and merged now supplies owned Kafka cleanup; never delete unknown historical volumes. Before qualifying run: reset --execute -> pinned bootstrap -> init/fixtures -> real control-plane SVID -> sync --extra test --extra lint -> 11 READY. Rerun ENTIRE independence campaign on final source commit: collection order, reverse, seeds190001/190002/190003 and all119 dependency-derived isolated tests, preserving all390 original0049 cases/assertions except PO-approved stronger ciphertext assertion plus deterministic negatives/mutant. New full runtime/reports regression required, zero skip/fail/error/residue/restart/OOM, full75/task45min and collection/JUnit exact union. Update distinct superseding evidence/allowlist/input hashes and exact-head candidate requests; verifier Cursor/Grok for0049 and tasks touched by reserve Claude, Claude Code for Codex-only scopes. Do not reuse diagnostic or old-source runs as qualifying evidence. No verifier launched by implementer; external loop only. Then verified REM-0019 closure -> REM-0017 CI repartition/reruns -> 0049 integration -> REM-0023 admission denial audit -> preserved0056, then0057–0059. E1/E2/Verified/claims unchanged.

- Gate locali state sync9/9 exit0; ruff/mypy strict, RCCAD/scope/piano sulla base main808ad78, language, drift, digest e runtime evidence0055. Piano37 PASS/2 NOT_EXECUTED opzionali preesistenti; planning generato archiviato e ripristinato. Nessun codice/test/sigillo modificato, nessuna nuova suite runtime rivendicata.


## 2026-10-12T00:56:22.380396+00:00 — REM-0019: checkpoint nuova qualifica ciclo1

- Ripresa sola unita REM19; merge main3c9b64e nel WIP e due stage, alberi di esecuzione identici; produzione0049 immutata. Riparazioni storiche Claude/Codex preservate, verifier pianificato Cursor/Grok terzo fornitore. Nessuna verifica avviata.
- Preflight8/8 digest, harness14 PASS, toolchain9/9, undici READY e SVID reale. Deriva0050 sulla allowlist FAIL, non derogata: nuova riqualifica di sola regressione198 casi richiesta prima del sigillo. Main/root pulita, PR169/176/220 e WIP0056 preservati.
- Primo run full2196 interrotto preventivamente con exit130 a JVM4G dentro cgroup2GiB (1.628GiB osservati, nessun OOM); teardown exit0, diagnostico conservato. Un errore import nel preparatore locale successivo resta FAIL. Corretto il preparatore fuori repo e adottato esattamente il profilo CI ci_resources (-Xms128m -Xmx1G), verificato sul processo reale, nessuna modifica a immagini, Compose, lock o validator.
- Nuovo worker seriale sul source8842ab2 in corso; full2196, cinque ordini390 e isolati119 devono concludere prima della candidata. Limiti75/45min, zero skip/residui/riavvio/OOM, unione esatta collection/JUnit. Nessun esito parziale rivendicato. Stato/handoff canonici; completed69 ed E1=0/E2=0/Verified=0 e NO-GO invariati.
- Prossima azione: OCOR-DEV-REM-0019:repair1-qualification-monitor — follow existing serial worker /home/luca/.ocor-codex/rem0019-resume-20261012-bounded-fixed/driver.py (session 13199) and driver.progress; do not start a second stack or pytest. Source 8842ab2658b9eee201fa1bd26d267a9f23c22df5, source worktree .ocor/worktrees/rem-0019; exact executable trees equal task and governed stages. Fresh full2196 + five390 orders + isolated119 required, zero skip/error/fail/residue/restart/OOM; actual heap128m/1G in2GiB cgroup, image identity unchanged. On PASS assemble distinct unsealed REM19/0049 records and new regression-only0050 candidate with explicit supersession, run final gates/checker, publish exact-head external Cursor/Grok request. On FAIL preserve diagnostic, teardown, diagnose; no counts transferred. REM19 repair_cycle1 unchanged. Then verified REM19 -> REM17 -> 0049 integration -> REM23 before preserved0056 WIP; no claim promotion.

- Gate checkpoint9/9 exit0 dopo correzione del solo cwd di mypy; il primo errore di invocazione resta diagnostico. Piano37 PASS/2 NOT_EXECUTED opzionali preesistenti. Report planning generati archiviati e ripristinati, codice/test/sigilli invariati.

## 2026-10-12T03:01:33.749944+00:00 — REM-0019: diagnosi containerd e nuova campagna attempt3 (implementatore di riserva Claude Code)

- Implementatore di riserva Claude Code (claude-opus-5-5) per quota Codex esaurita; verifier pianificato Grok 4.7 via Cursor, nessuna verifica avviata. Unita unica: proseguimento qualifica REM19 ciclo1 sul source 8842ab2 invariato; produzione0049, test, sigilli, inputs e backlog immutati.
- Tentativo precedente (bounded-fixed): full exit130 a 1379/2196 PASS per SIGSEGV di containerd nel nodo kind (01:29:57Z, creazione sandbox del backup manuale); FAIL diagnostico conservato, nessun conteggio trasferito. Il supervisore diagnose.py di Codex e terminato con lo stop per quota: i gruppi di processi orfani (Helm isolato + gdb) sono stati adottati da un supervisore sostitutivo con stessa scadenza, stessi criteri e stesso teardown (exit0, inventario prima==dopo).
- Diagnosi non qualificante: SIGSEGV catturato alle 02:00:03Z (tick */15, sandbox del CronJob) con backtrace e core privato. Simbolizzazione via pclntab del binario pinned containerd v2.1.1: runtime.mallocgcSmallNoscan+0xd8, dereferenza nil nel runtime Go senza traccia fatal; codice OCOR non coinvolto; kernel host 7.0.0-38. Nessuna mitigazione tentata (immagine/versione vietate, variazioni d ambiente riservate). Si tratta come FAIL_INFRASTRUCTURE con riesecuzione integrale.
- Attempt3 (/home/luca/.ocor-codex/rem0019-resume-20261012-attempt3): preflight PASS (digest8/8, harness14, toolchain9/9, undici READY, SVID reale, Fuseki -Xms128m -Xmx1G in cgroup2GiB). Full2196 PASS, zero skip/fail/error, 3338 s (<60 min), unione collection/JUnit esatta, zero residui/riavvii/OOM: risultato di componente, non qualificante finche non concludono cinque ordini390 e 119 isolati nella stessa campagna seriale, ora in corso.
- Completed69, E1=0/E2=0/Verified=0, runtime NOT_ESTABLISHED, PoC/Production NO-GO invariati. Deriva 0050 OPEN_NOT_WAIVED fino alla riqualifica di sola regressione. PR169/176/220 e WIP0056 preservati.
- Prossima azione: OCOR-DEV-REM-0019:repair1-qualification-monitor — follow existing serial campaign /home/luca/.ocor-codex/rem0019-resume-20261012-attempt3/run.sh (setsid; driver.py, run.progress, driver.progress, modules.progress, isolated.progress); do not start a second stack or pytest. Source 8842ab2658b9eee201fa1bd26d267a9f23c22df5 on .ocor/worktrees/rem-0019; full2196 already PASS in this campaign (3338 s, zero skip, exact union, no residue); remaining five 390 module orders with tick alignment then 119 isolated tests, zero skip/error/fail/residue/restart/OOM, 45-min per module run. On kind containerd SIGSEGV (diagnosed: Go runtime malloc fault in pinned containerd v2.1.1, not OCOR code, ~/.ocor-codex/rem0019-kind-diagnosis-20261012-fixed/diagnosis-summary.json) record FAIL_INFRASTRUCTURE, preserve diagnostics, teardown and restart the ENTIRE campaign (full included) in a new attempt directory; never transfer counts or relabel. On PASS assemble distinct unsealed REM19/0049 records and new regression-only0050 candidate with explicit supersession, run final gates/checker, publish exact-head external Cursor/Grok request. REM19 repair_cycle1 unchanged. Then verified REM19 -> REM17 -> 0049 integration -> REM23 before preserved0056 WIP; no claim promotion.

- Gate locali state sync 9/9 exit0 (digest, ruff, mypy strict dalla root, RCCAD/scope/piano su base main esatta, language, drift, runtime evidence0055); piano 37 PASS/2 NOT_EXECUTED opzionali preesistenti; primo mypy con cwd errato conservato come diagnostico. Planning generato archiviato e ripristinato.


## 2026-10-12T04:10:14.780514+00:00 — REM-0019: race del monitor al teardown, self-repair locale e campagna fresca attempt4

- Unita unica: ripresa Codex e diagnosi dell osservazione del nodo kind. Attempt3 resta FAIL: full2196 componente PASS, 390 corpi test PASS in 2398 s ma pytest exit130; il watchdog intercetta docker exec fallito sulla UUID2f738e... dopo kill/die/destroy al teardown. Campioni disponibili senza SIGSEGV osservato; rischio containerd reale precedente ancora aperto. Reset finale exit0, nessun nuovo residuo; nessun conteggio trasferito o rietichettato.
- Self-repair DEC-211 del solo adattatore locale fuori Git: RED riproduce CalledProcessError sul nodo rimosso; GREEN sette funzioni, inclusi positivi e negativi (nodo esistente, rimozione non provata, evento non owned, daemon assente, restart/failure/PID e secondo errore). Mocks soltanto failure handling locale, nessuna evidenza di backend. Un solo retry dell osservazione dopo prova di UUID assente e destroy owned; check originali e limiti invariati. Validator/workflow/script CI del repository non modificati; stessa correzione da portare nello scope REM17 prima della CI.
- Primo preparatore attempt4 fermato prima del launch per un confronto errato dell inventario prima/dopo reset (il reset rimuove undici container bootstrap, rete e quattro volumi): FAIL locale preservato e diagnosi acquisita. Poi nuova campagna intera avviata: reset/bootstrap/init/fixture/SVID, digest8/8, harness14 PASS, toolchain9/9 e11 READY. Source8842ab2 immutato, nuovo worker PID/PGID3451544; full2196 RUNNING, cinque390 ordini e119 isolati ancora NOT_EXECUTED. Tetti75/45min, zero skip/fail/error/residuo/restart/OOM e unione JUnit obbligatori.
- Main/root pulita e allineata; staged task/governed uniti a main senza riscrittura, alberi eseguibili identici. Reports48 PASS/zero skip e cinque harness exit0; AST72 funzioni PASS senza modifiche non autorizzate. Precheck candidato10 PASS/1 FAIL: deriva0050 OPEN_NOT_WAIVED, nuova supersession REGRESSION_ONLY198 casi richiesta. Assemblatori locali DRAFT_NOT_EXECUTED, nessuna candidata emessa, sigillo o verifica indipendente.
- Implementatori storici Claude Code/Codex; ripresa/self-repair/riavvio Codex; verifier futuro Cursor/Grok4.7, terzo fornitore, solo loop esterno. Completed69, inputs, produzione0049, backlog, sigilli, E1=0/E2=0/Verified=0 e NO-GO invariati. PR169/176/220 e WIP0056 preservati.
- Prossima azione: OCOR-DEV-REM-0019:repair1-qualification-monitor — adopt fresh serial campaign /home/luca/.ocor-codex/rem0019-resume-20261012-attempt4/run.sh (launch bash PID/PGID3451544; confirm live command identity before signals). Read run.progress, driver.progress, full.log, then modules.progress/isolated.progress and driver-result.json when present (driver result first appears after full); no second stack/pytest or competing reset. Source8842ab2658b9eee201fa1bd26d267a9f23c22df5 in .ocor/worktrees/rem-0019 unchanged. Fresh reset/bootstrap/SVID/11READY/toolchain9 preflight PASS; full2196 RUNNING, all five390 orders and119 isolated still NOT_EXECUTED on attempt4. Require entire campaign, exact collection/JUnit union, zero skip/fail/error/residue/restart/OOM, full75/task45min. Original service/PID/restart/OOM/deadline checks unchanged; local watchdog_safe.py allows one fresh observation ONLY after exact UUID is absent and Docker records owned destroy, otherwise fails closed. Adapter SHA and RED/7-test local GREEN in checkpoint; mocked local failure handling is not runtime evidence. Attempt3 remains FAIL (390 JUnit PASS but watchdog SIGINT at owned-kind removal, exit130); all prior diagnostics preserved; no counts transferred. Real containerd SIGSEGV risk remains open. On failure preserve diagnostics/teardown/diagnose, no relabelling. On whole-campaign PASS validate draft ~/.ocor-codex/rem0019-codex-20261012/assemble.py and check.py (NOT_EXECUTED), append distinct unsealed REM19/0049 and REGRESSION_ONLY0050 supersession (198 unchanged cases), recheck historical TDD, assertions and final HEAD/input/tree/branch/raw hashes, all final gates incl drift and exact integration-base plan/scope, RCCAD before push; then exact-head external Cursor/Grok requests. No verifier launched by implementer. REM19 repair_cycle1 unchanged. VerifiedREM19 -> REM17 (port same proven node-removal race handling inside its own scope before CI) ->0049 integration->REM23 before preserved0056 WIP; evidence fence and claims unchanged.

- Gate locali state sync9/9 exit0 (digest, ruff, mypy strict, RCCAD, scope/piano su base main esatta, language, drift, runtime evidence0055); output planning generati archiviati e ripristinati. Ready set matematico OCOR-DEV-0049, OCOR-DEV-0056, OCOR-DEV-0057; priorita REM19 e ordine del PO invariati. Nessun nuovo test runtime finale rivendicato.

- Handoff: il precedente artifact fresh_full_runtime e conservato sotto attempt3_full_diagnostic, esplicitamente non qualificante dopo il FAIL della campagna; attempt4 RUNNING senza conteggi trasferiti. Nessun record probatorio modificato.


## 2026-10-12T05:04:24.760816+00:00 — REM-0019: stop-before-destroy del nodo kind, prova del remover e campagna fresca attempt5

- Unita unica Codex: adozione di attempt4, diagnosi del FAIL, self-repair locale DEC-211 e riavvio integrale attempt5 sul source8842ab2 invariato. Nessuna modifica a produzione0049, test, validator, workflow, backlog, inputs o record sigillati. Verifier previsto Cursor/Grok4.7, terzo fornitore; nessuna verifica avviata.
- Attempt4 FAIL: pytest exit130 a2830s, JUnit1383 PASS/zero skip/fail/error, inclusi tutti390 corpi0049, interrotto al teardown del modulo. Die nodo bc1f9c... alle04:53:57.551509Z e destroy alle04:53:58.901672Z: il probe cade nella finestra1,35s in cui il nodo esiste ma e fermo. Ultimo campione97 running/noOOM/noRestart; rischio containerd SIGSEGV storico resta aperto. Teardown exit0, zero nuove risorse rispetto all inventario postbootstrap. Nessuna qualifica/conteggio trasferito.
- RED misurato exit1 riproduce CalledProcessError. GREEN locale11 funzioni (le7 precedenti piu4 con sottocasi) exit0: soltanto failure handling con mock, mai evidenza backend. Prima di una sola attesa2s sullo stesso UUID fermo richiede il processo reale pinned kind delete cluster --name ocor-poc nel PGIDpytest esatto; poi UUID assente e destroy owned comprovato. OOM/restart, nodo ancora esistente o distruzione non provata restano fatali; un solo nuovo snapshot originale e nessun controllo PID/servizio/deadline modificato. Da riportare nello scope REM17 prima della CI.
- Preflight sola lettura: main186input/69task drift PASS; candidato0050 drift FAIL, OPEN_NOT_WAIVED. Toolchain9/9, harness14 PASS in worktree, digest8/8; AST72 funzioni con sole deroghe autorizzate, cinque390 ordini/seed e119 nodi distinti confermati. Alberi eseguibili degli stage uguali al source; main conserva0049 non integrata. PR227 mergiata con13 SUCCESS; PR169/176/220 e WIP0056 preservati. Errori di invocazione locali registrati come diagnostici, mai gate runtime PASS.
- Attempt5 nuovo: reset/bootstrap/init/fixture/SVID e11READY, toolchain9 e digest8/8 PASS; full2196 RUNNING, cinque390 e119 isolati NOT_EXECUTED. Primo launcher fermato prima del lancio per falso self-match dell exclusivity check, diagnostico preservato e confronto di identita corretto. PID/PGID4190954; un solo stack. Tetti75/45min e arresti invariati. Draft assemble/check restano NOT_EXECUTED per candidato, da retargettare ad attempt5 dopo PASS integrale.
- Completed69, E1=0/E2=0/Verified=0, runtime NOT_ESTABLISHED, PoC/Production NO-GO invariati. REM19 ciclo1 invariato; nessun ciclo riparativo normativo aggiuntivo consumato dal tooling.
- Prossima azione: OCOR-DEV-REM-0019:repair1-qualification-monitor — adopt existing fresh entire serial campaign /home/luca/.ocor-codex/rem0019-resume-20261012-attempt5/run.sh (launch PID/PGID4190954; verify current process identity before signals). Read run.progress, driver.progress, full.log; then module/isolated progress and driver-result.json. No second stack, pytest, competing reset or count transfer. Source8842ab2658b9eee201fa1bd26d267a9f23c22df5 on .ocor/worktrees/rem-0019 is unchanged. Attempt4 FAIL exit130 at owned-kind fixture stop/destroy after1383 passing bodies (all390 of0049); not a full or module qualification. New monitor requires real pinned kind delete cluster --name ocor-poc in exact pytest process group for a stopped-node wait; one2s same-UUID reobservation, absent+owned destroy proof, reject OOM/restart, then one original fresh snapshot. Original service/PID/deadline checks unchanged. Eleven mocked local monitor tests are failure-handling only. Fresh preflight PASS:8digests/14harness/9toolchain/11READY/SVID; full2196 RUNNING; five390 orders and119 isolated still NOT_EXECUTED. Entire same-source campaign must PASS with exact collection/JUnit unions, zero skip/error/failure/residue/restart/OOM, full75/task45min; >60min full queues a duration decision. On failure diagnose and preserve artifacts/teardown; never automatically repeat unchanged failures. On whole-campaign PASS align staging to current main preserving execution-tree identity; retarget and validate local draft assemblers ~/.ocor-codex/rem0019-codex-20261012/assemble.py and check.py from attempt4 to attempt5 including correct new RED/11-test GREEN/proc-observer filenames (NOT_EXECUTED candidate tooling). Append separate unsealed REM19/0049 and REGRESSION_ONLY0050 supersessions198 unchanged cases; recheck final HEAD/branch/tree/raw/input hashes and historic TDD/assertions, final scope/plan/drift/other gates; RCCAD before push; exact pushed HEAD external Cursor/Grok requests. Do not run verifier. repair_cycle1 unchanged. VerifiedREM19 -> REM17 (port lifecycle observation fix in its own scope before CI) ->0049 integration->REM23 before preserved0056 WIP; claims unchanged.

- Gate locali checkpoint9/9 exit0: digest, ruff, mypy strict, RCCAD/scope/piano contro base main esatta, language, drift e runtime evidence0055. Output planning generati archiviati e ripristinati; qualifica REM19 non conclusa e deriva0050 candidata non derogata.


## 2026-10-12T05:32:13.808218+00:00 — REM-0019: adozione QUALIFICATION-CAMPAIGN-INFRA-RERUN, attempt5 invariato

- Unita unica Codex: adozione del supervisore seriale esistente e della decisione PO del 2026-10-12. Attempt5 continua sul source8842ab2 pulito, senza interrompere run, cambiare harness o avviare un secondo stack. Tentativo4 resta FAIL diagnostico; copie locali dei raw e diagnosis.json con hash in attempts/historic-attempt4-full, zero conteggi trasferiti.
- Acquisiti digest di script, import CI, elenchi di nodi e alberi input/codice/test. Rerun del solo run fallito ammesso soltanto con identita invariata e causa infrastrutturale provata, zero asserzioni fallite, diagnostico preservato, reset/zero residui: massimo due ripetizioni. Stessa causa su piu run o terzo fallimento richiedono decision request. Modifica observation/teardown richiede prova; modifica esecuzione impone campagna nuova. Nessun rerun effettuato da questa adozione.
- Preflight: main0e51154 pulita e allineata; digest8/8, harness14 PASS in worktree, toolchain9/9 digest/versione ricontrollati, drift186input/69task PASS. PR228:13 check obbligatori SUCCESS; PR169/176/220 e WIP0056 preservati. Bootstrap non ripetuto durante il run owned. Stato completo della campagna nel checkpoint, componenti conclusi: nessuno. Campagna non ancora qualificata; cinque390 ordini e119 isolati richiesti.
- Ruoli: implementatore adozione Codex; implementatori storici Claude Code/Codex; verifier futuro Cursor/Grok4.7 terzo fornitore. Nessuna richiesta di verifica o sigillo emesso. Deriva candidata0050 non derogata: supersession REGRESSION_ONLY198 casi necessaria prima della richiesta. Completed69, inputs, produzione, test, backlog, record sigillati ed E1=0/E2=0/Verified=0 e NO-GO invariati.
- Prossima azione: OCOR-DEV-REM-0019:repair1-qualification-monitor — adopt unchanged serial attempt5 /home/luca/.ocor-codex/rem0019-resume-20261012-attempt5/run.sh (launch PID/PGID4190954; confirm /proc identity before any signal). Read driver.progress/full.log, then modules.progress/isolated.progress/driver-result.json; no second stack or competing reset. Source 8842ab2658b9eee201fa1bd26d267a9f23c22df5 in .ocor/worktrees/rem-0019 unchanged;  recorded only as components. Apply PO QUALIFICATION-CAMPAIGN-INFRA-RERUN 2026-10-12: a proven infrastructure-only failing run may be rerun alone at most twice with identical source/input/execution-harness hashes in /home/luca/.ocor-codex/rem0019-adoption-20261012/campaign-identity.json; preserve attempts/<run>/<attempt>/diagnosis.json and raw hashes, exclude failed counts, reset and verify no owned residue before retry. Assertion/code failures never infrastructure; same cause on multiple runs or third infrastructure failure requires decision request. Observation/teardown-only harness repair needs recorded proof; execution-affecting repair requires full campaign restart. Do not interrupt current run or relabel attempt4. Require exact JUnit collection/order union for full2196, five390 orders and119 isolated, zero fail/error/skip/residue/restart/OOM; full75/task45min, >60min full requires duration request. After complete PASS, align staging to current main preserving execution-tree identity; retarget/validate draft assemble.py and check.py in ~/.ocor-codex/rem0019-codex-20261012 to attempt5, archive valid and diagnostic attempts; append new unsealed REM19/0049 and REGRESSION_ONLY0050 supersessions (198 unchanged tests), verify final HEAD/branch/input/tree/raw hashes, run final gates incl drift and actual integration-base scope/plan, RCCAD before push; submit exact-head Cursor/Grok requests without launching verifier. REM19 repair_cycle1 unchanged. VerifiedREM19 -> REM17 ->0049 integration->REM23 before preserved0056 WIP. No claim/fence promotion.

- Gate locali state sync: 9/9 exit 0 (digest, ruff, mypy strict, RCCAD, scope, piano su base main esatta, language, drift, runtime evidence 0055); output planning generati archiviati e ripristinati. CI della nuova PR ancora da eseguire; nessun PASS runtime dedotto.


## 2026-10-12T05:52:38.893485+00:00 — REM-0019: REM-0019: SIGSEGV containerd archiviato, rerun infrastrutturale 1

- Unita unica Codex: adozione del supervisore seriale esistente e della decisione PO del 2026-10-12. Il full del tentativo5 si e fermato fail-closed al SIGSEGV containerd alle05:44:57Z: exit130, header JUnit1379 ma1380 testcase per il caso Helm interrotto, zero failure/error/skip. Nessuna unione completa o conteggio qualificante. Diagnosi e raw in attempts/full/attempt-1; teardown exit0, inventory set/count identico dopo normalizzazione injective degli ID Docker brevi/completi. Primo rerun full avviato con PID/PGID630308 alle05:51:36Z, script e codice invariati; gli altri run richiesti erano NOT_EXECUTED. Tentativo4 resta FAIL diagnostico; copie locali dei raw e diagnosis.json con hash in attempts/historic-attempt4-full, zero conteggi trasferiti.
- Acquisiti digest di script, import CI, elenchi di nodi e alberi input/codice/test. Rerun del solo run fallito ammesso soltanto con identita invariata e causa infrastrutturale provata, zero asserzioni fallite, diagnostico preservato, reset/zero residui: massimo due ripetizioni. Stessa causa su piu run o terzo fallimento richiedono decision request. Modifica observation/teardown richiede prova; modifica esecuzione impone campagna nuova. Un solo rerun infrastrutturale avviato:1 dei2 consentiti per il full logico, nessun altro run richiesto colpito. Il SIGSEGV storico resta nel rischio aperto; il budget non e un autorizzazione a cambiare immagine/versione.
- Preflight: main0e51154 pulita e allineata; digest8/8, harness14 PASS in worktree, toolchain9/9 digest/versione ricontrollati, drift186input/69task PASS. PR228:13 check obbligatori SUCCESS; PR169/176/220 e WIP0056 preservati. Reset e bootstrap rieseguiti dal worker seriale prima del rerun; esito in preflight-result.json, nessun secondo stack. Stato completo della campagna nel checkpoint, componenti conclusi: nessuno. Campagna non ancora qualificata; cinque390 ordini e119 isolati richiesti.
- Ruoli: implementatore adozione Codex; implementatori storici Claude Code/Codex; verifier futuro Cursor/Grok4.7 terzo fornitore. Nessuna richiesta di verifica o sigillo emesso. Deriva candidata0050 non derogata: supersession REGRESSION_ONLY198 casi necessaria prima della richiesta. Completed69, inputs, produzione, test, backlog, record sigillati ed E1=0/E2=0/Verified=0 e NO-GO invariati.
- Prossima azione: OCOR-DEV-REM-0019:repair1-qualification-monitor — adopt unchanged serial attempt5 /home/luca/.ocor-codex/rem0019-resume-20261012-attempt5/run.sh (launch PID/PGID630308; confirm /proc identity before any signal). Read driver.progress/full.log, then modules.progress/isolated.progress/driver-result.json; no second stack or competing reset. Source 8842ab2658b9eee201fa1bd26d267a9f23c22df5 in .ocor/worktrees/rem-0019 unchanged;  recorded only as components. Apply PO QUALIFICATION-CAMPAIGN-INFRA-RERUN 2026-10-12: a proven infrastructure-only failing run may be rerun alone at most twice with identical source/input/execution-harness hashes in /home/luca/.ocor-codex/rem0019-adoption-20261012/campaign-identity.json; preserve attempts/<run>/<attempt>/diagnosis.json and raw hashes, exclude failed counts, reset and verify no owned residue before retry. Assertion/code failures never infrastructure; same cause on another REQUIRED RUN or third infrastructure failure of the FULL requires decision request; previous full crashes and diagnostic histories remain open, never erased. Observation/teardown-only harness repair needs recorded proof; execution-affecting repair requires full campaign restart. Do not interrupt current run or relabel attempt4. Require exact JUnit collection/order union for full2196, five390 orders and119 isolated, zero fail/error/skip/residue/restart/OOM; full75/task45min, >60min full requires duration request. After complete PASS, align staging to current main preserving execution-tree identity; retarget/validate draft assemble.py and check.py in ~/.ocor-codex/rem0019-codex-20261012 to attempt5, archive valid and diagnostic attempts; append new unsealed REM19/0049 and REGRESSION_ONLY0050 supersessions (198 unchanged tests), verify final HEAD/branch/input/tree/raw hashes, run final gates incl drift and actual integration-base scope/plan, RCCAD before push; submit exact-head Cursor/Grok requests without launching verifier. REM19 repair_cycle1 unchanged. VerifiedREM19 -> REM17 ->0049 integration->REM23 before preserved0056 WIP. No claim/fence promotion.

- Nuovo preflight del rerun: 8 digest, harness 14 PASS, toolchain 9/9 e 11 READY; source e harness invariati. Gate del checkpoint finale 9/9 exit 0; output planning archiviati e ripristinati. HEAD intermedio96c60c5 ha13/13 CI SUCCESS, storico non sostitutivo della CI richiesta sul nuovo HEAD. Errore locale KeyError nel merge dei metadati handoff corretto prima del commit; nessun gate runtime dedotto.


## 2026-10-12T16:13:39.352361+00:00 — REM-0019: aggiornamento host interrompe il rerun, ultimo tentativo infrastrutturale

- Unita unica Codex: diagnosi e recupero del primo rerun infrastrutturale del full di REM-0019 repair1, senza modifiche a produzione, test o harness. Journal/dpkg provano aggiornamento host di containerd.io2.4.1-2 e Docker29.9.0 alle06:29:38–06:29:54Z: daemon indisponibile, watchdog SIGINT, exit130 dopo2246.78s. JUnit incompleto: header1379,1380 testcase incluso Helm interrotto, zero failure/error/skip. Nessun PASS di suite, unione o conteggio qualificante. Il SIGSEGV kind precedente resta archiviato. Raw e diagnosis.json preservati in attempts/full/attempt-2, hashe4d6a5273cbed40606e8e64688e8f36859ab12517bcbd8c327cf00f56ab5d67b; tutti i conteggi diagnostici esclusi.
- Teardown originario FAIL per residui anche se reset exit0:13 container,1 volume kind e2 reti OCOR. Prova di appartenenza tramite delta degli ID, label Compose/kind, mount e worktree; rimossi soltanto quegli oggetti. Ora zero residui posseduti,23 container storici e364 volumi preservati; rete host bridge ricreata dal daemon preservata. Prima assert di scope sul nuovo ID bridge fallita senza mutazioni; corretta soltanto nel recupero locale e ripetuta una volta, nessuna modifica agli script della campagna.
- Identita source8842ab2, alberi input/codice/test e digest harness95f1f3c12a18f945d3d4c9c18aabd8ba5c239198dac0616fd42661190b171f7d ricontrollati invariati. Toolchain isolata8 binari + Java container invariata; client Docker29.7.2, nessun aggiornamento lock/validator. Cambio daemon host registrato come ambiente, nessun run verde precedente riusato. Avviato secondo e ULTIMO rerun full autorizzato da QUALIFICATION-CAMPAIGN-INFRA-RERUN con PID/PGID11336 alle2026-10-12T16:11:53.144283+00:00; reset/bootstrap/11 READY gestiti dal solo worker, esitoPASS. Al terzo fallimento infrastrutturale dello stesso full o causa comune su altro run richiesto: decision request, nessun ulteriore retry.
- Preflight principale: maina5b54e874da9 pulita/allineata; digest8/8, harness14 PASS in worktree, drift186input/69task PASS. PR22913/13 check verdi storici; PR169/176/220 e WIP0056 preservati. Nuova campagna ancora non qualificata; full2196,5 ordini da390 e119 isolati restano obbligatori, zero skip/residui e limiti75/45min.
- Ruoli: implementatore corrente Codex; isolamento/VF-001 storici Claude Code di riserva, oracle Codex; verifier futuro Grok4.7 via Cursor in contesto separato. Nessuna verifica o sigillo emesso. Riqualifica0050 REGRESSION_ONLY198 casi obbligatoria prima di preseal. Completed69, inputs, record sigillati, E1=0/E2=0/Verified=0 e claim NO-GO invariati.
- Prossima azione: OCOR-DEV-REM-0019:repair1-last-infrastructure-rerun-monitor — adopt unchanged serial attempt5 /home/luca/.ocor-codex/rem0019-resume-20261012-attempt5/run.sh, launch PID/PGID11336; validate /proc start identity before signal; only this supervisor owns stack. Source8842ab2658b9eee201fa1bd26d267a9f23c22df5 in .ocor/worktrees/rem-0019 unchanged. Read preflight-result.json, driver.progress/full.json/full.log, modules.progress, isolated.progress and driver-result.json. Original full and first rerun preserved under attempts/full/attempt-1 and attempt-2 with diagnoses and raw hashes; both diagnostic, no counts transferred. Second and LAST full infrastructure retry under QUALIFICATION-CAMPAIGN-INFRA-RERUN; third infrastructure failure of this full or same cause on another required run -> decision request, no third retry; assertion/code failures never infrastructure. No second stack/reset. Host package upgrade Docker daemon29.9.0/containerd.io2.4.1-2 recorded; pinned client29.7.2 and toolchain9 unchanged; no successful prior campaign component reused. Require full2196 exact JUnit union, five390 module orders,119 isolated, zero fail/error/skip/residue/restart/OOM;75min full45min task; full>60min -> duration request. Original teardown exit0 had13 containers/1 volume/2 OCOR networks remaining: FAIL residue preserved; exact ownership cleanup now PASS zero owned residue, historical23 containers364 volumes and host bridge preserved. After complete PASS align staging to origin/main preserving execution-tree identity, retarget assemble.py/check.py in ~/.ocor-codex/rem0019-codex-20261012, archive valid and diagnostic attempts, append unsealed REM19/0049 and REGRESSION_ONLY0050 supersessions198 unchanged tests, verify final commit/branch/input/tree/raw hashes, final gates incl drift and integration-base scope/plan, RCCAD before push; request exact-head Cursor/Grok review without launching it. REM19 repair_cycle1; historic implementers Claude Code reserve/Codex, verifier Grok4.7(Cursor) third provider. VerifiedREM19 -> REM17 ->0049 integration->REM23 before preserved0056 WIP. No claim/fence promotion.

- Gate locali dello state sync:9/9 exit0 (digest,ruff,mypy strict,RCCAD,scope,piano su base origin/main esatta,language,drift,runtime evidence0055); output planning archiviati/ripristinati. Full seriale avviato dopo preflight11READY e ancora RUNNING, nessun risultato finale. Errore locale di parsing del referto verify testuale corretto leggendo il riepilogo14PASS, file generato ripristinato. CI della nuova PR ancora PENDING; nessun PASS runtime dedotto.


## 2026-10-12T17:00:26.486424+00:00 — REM-0019: full ultimo rerun PASS, campagna di indipendenza in corso

- Unità unica Codex: adozione in sola lettura del supervisor11336 (start_ticks111304), senza alterare source, test, harness o stack. Confermati22 confronti di identità, source8842ab2658b9eee201fa1bd26d267a9f23c22df5 e digest degli script identici. Preflight digest8/8, harness14PASS, deriva186input/69task PASS; toolchain e11READY già acquisiti dal medesimo worker, nessun secondo bootstrap.
- Il secondo e ultimo rerun infrastrutturale del full è PASS come singola componente:2196 test,0failure,0error,0skip; unione esatta fra collezione e JUnit, nessun mancante/duplicato/inatteso; durata2817.51s. Watchdog senza errori; inventari container/reti/volumi identici prima/dopo, zero risorse residue del run. Raw/JUnit/metadati e prova archiviati in /home/luca/.ocor-codex/rem0019-resume-20261012-attempt5/attempts/full/attempt-3; valid-component.json SHA256071d64592ac79c15778b84c02992443baeb3ba48d47e8c52b57c7f3c8a6e640b.
- Tentativi full1 e2 restano diagnostici con le diagnosi e hash precedenti, zero conteggi trasferiti; nessun rerun della componente verde. QUALIFICATION-CAMPAIGN-INFRA-RERUN applicata al solo run fallito, codice/test/input/harness invariati. Host daemon Docker29.9.0/containerd.io2.4.1-2 già registrato; client pinnato29.7.2 e lock invariati.
- Campagna REM-0019 non conclusa: ancora obbligatori5 ordini da390 e119 isolati, esiti/unione/ordine/zero residui e teardown finale. Il solo supervisor seriale resta proprietario delle risorse per proseguire; questa sessione non crea risorse Docker. Limiti45min task75min full, arresto su restart/OOM e divieto di indebolire criteri invariati. Nessuna verifica indipendente, sigillo o GO emesso.
- Ruoli: isolamento/VF-001 storici Claude Code di riserva; oracolo e qualifica Codex; verifier futuro Grok4.7(Cursor), terzo fornitore in contesto separato. Riqualifica0050 REGRESSION_ONLY198 test invariati ancora richiesta prima del preseal; difetto admission denial audit resta aperto REM23. WIP0056 e PR169/176/220 preservati. Completed69, inputs, record sigillati, E1=0/E2=0/Verified=0 e claimNO-GO invariati.
- CI storica PR23013/13SUCCESS su6ea880127f7f48e994b2105e7dda8aaf01993c92, mergea6ab09dcea1ee021b8c2dc5c994698cfbe0fceac; nuova PR/check dello state sync da acquisire, non dedotti dal full locale. Prossima azione: OCOR-DEV-REM-0019:repair1-independence-campaign-monitor — adopt existing serial supervisor PID/PGID11336 (start_ticks111304; verify /proc identity before any signal) at /home/luca/.ocor-codex/rem0019-resume-20261012-attempt5/run.sh. Full attempt3 is PASS component only:2196 exact collected/JUnit union, zero fail/error/skip, unchanged resource inventory; attempts/full/attempt-1 and attempt-2 remain diagnostic and contribute zero counts. Source8842ab2658b9eee201fa1bd26d267a9f23c22df5 and execution-harness digests unchanged. Do not rerun the successful full, start another stack or reset resources owned by the live supervisor. Read driver.progress, modules.progress, order-*.json, isolated.progress and driver-result.json; require all five orders of390 cases and119 isolated, exact JUnit identity/order checks, zero skip/fail/error/residue/restart/OOM and final owned teardown. Task cap45min, full75min. QUALIFICATION-CAMPAIGN-INFRA-RERUN: maximum2 same-harness retries for an eligible failed run, diagnostics preserved; same cause affecting multiple runs or third infrastructure failure requires decision request; assertion/code failures never infrastructure. After entire campaign PASS align staging to current origin/main preserving execution-tree identities, retarget ~/.ocor-codex/rem0019-codex-20261012/assemble.py and check.py, archive selected/diagnostic attempts; append unsealed REM19/0049 and REGRESSION_ONLY0050 supersessions198 unchanged tests. Reacquire final commit/branch/input/tree/raw hashes, final gates including drift and actual integration-base scope/plan, RCCAD before push. Request exact-head Cursor/Grok4.7 review through verify_request.json, never launch the verifier. REM19 repair_cycle1; historic Claude Code reserve isolation/VF-001 and Codex oracle/qualification, independent verifier Grok4.7(Cursor). VerifiedREM19 -> REM17 ->0049 integration ->REM23 before preserved0056 WIP. E1/E2/Verified and NO-GO unchanged.

- Gate locali del checkpoint:9/9 comandi exit0 (digest, ruff, mypy strict, RCCAD, scope e piano su base origin/main esatta, language, drift, runtime evidence0055). Output planning/verify generati archiviati e ripristinati. Nessuna risorsa Docker creata da questa sessione; teardown finale affidato al solo supervisor live. CI del nuovo HEAD ancora da acquisire, nessuna deduzione dal PASS locale.


## 2026-10-12T18:01:46.143622+00:00 — REM-0019: errore watchdog nel teardown, diagnosi e decision request

- Unità Codex: adottato in sola lettura il supervisor11336, identità start_ticks111304 verificata; 22 confronti di identità PASS. Source8842ab2658b9eee201fa1bd26d267a9f23c22df5, codice, test, input e harness invariati. Nessuna nuova suite/ripetizione avviata. Preflight digest8/8, harness14PASS, drift186 input/69task PASS e toolchain9/9.
- order-collection attempt1 FAIL non qualificante: 390 corpi/JUnit PASS,0failure/error/skip e ordine/unione esatti, ma exit130 dopo2419,44s per SIGINT del watchdog durante teardown. Fallito docker exec systemctl show containerd sul nodo owned5c4a3536. Eventi die(exit137)17:54:04,475715312Z e destroy17:54:05,936134330Z, distanti1,460419s;95 snapshot precedenti running/OOMfalse/RestartCount0; nessun oom/restart negli eventi acquisiti. Compatibile con race osservazione/rimozione già diagnosticata nel full storico; identità precisa del processo di rimozione nel ramo di errore NOT_EXECUTED, nessuna attribuzione più forte.
- Archivio diagnostico completo /home/luca/.ocor-codex/rem0019-resume-20261012-attempt5/attempts/order-collection/attempt-1, diagnosis.json SHA2564cee2086930f8fca1ab751399d1f87a09a708dea2810bd96a15a7ff5d0c10547; conteggi esclusi dalla qualifica. Full attempt3 PASS2196 conservato, tentativi full1/2 e storico4 preservati senza riclassificazione. Quattro ordini e119isolati NOT_EXECUTED. Supervisor concluso; teardown exit0, zero nuove risorse rispetto al baseline immediato; rimossi11container/1rete/4volumi di sessione, preservati23container/5reti/364volumi storici.
- QUALIFICATION-CAMPAIGN-INFRA-RERUN: causa della stessa classe su più run -> stop e richiestaREM-0019-KIND-TEARDOWN-OBSERVATION; nessun retry o modifica dell'harness. DraftPR232, branchgoverned/decision-request-rem0019-teardown-observation, commit8be2b87a936bbc52909ae0e489d65a68dbc1fbac, SHA256 documento27c162d0fc5a7dca25e5e8c2a18553090e859eaac7ca7f33f8eed08a834f8d17. Raccomandazione: correzione esclusivamente osservativa con prove bounded di intento owned/destroy e negativi per nodo esistente/crash/OOM/restart; riuso full solo con prova observation-only, altrimenti nuova campagna completa. Nuovo percorso del documento fuori allowlist esatta: gate piano FAIL36PASS/1FAIL/2opzionali NOT_EXECUTED, RCCAD PASS. Draft non integrabile, allowlist invariata; testo completo e riferimenti versionati nei metadati di questo checkpoint.
- CI precedente PR23113/13SUCCESS, merge60e0e1213996fc750567866c0348a496cff817ec. Nuovo checkpoint modifica solo state/handoff/log, check ancora da acquisire. Ready set matematico0049/0056/0057, ma ordine e blocker preservati. Resta eseguibile la diagnosi REM-0017 già autorizzata opzione1; nessuna campagna qualificante avviabile prima della disposizione. PR169/176/220 e WIP0056 preservati.
- Ruoli: Codex corrente; Claude Code riserva storico per isolamento/VF-001 e Codex per oracle/qualifica; verifier futuro Grok4.7(Cursor), contesto separato. Riqualifica0050 REGRESSION_ONLY198 test ancora necessaria prima del preseal; denial audit aperto REM23. Completed69 e record sigillati invariati. Nessuna modifica inputs, E1=0/E2=0/Verified=0 e NO-GO invariati.
- Prossima azione: OCOR-DEV-REM-0017:authorized-infrastructure-diagnosis — resume option1 of REM-0017-KIND-CONTAINERD-CRASH in .ocor/worktrees/ocor-dev-rem-0017-ci-provision-spire using existing diagnostic logs, same pinned image/version; do not start CI/qualification or change REM-0019 harness while REM-0019-KIND-TEARDOWN-OBSERVATION is OPEN_PO_DECISION_REQUIRED. REM-0019 repair_cycle1 source8842ab2658b9eee201fa1bd26d267a9f23c22df5 unchanged; supervisor11336 exited. Retain full attempt3 PASS2196 and all diagnostic attempts. order-collection attempt1 is FAIL exit130, despite390 test bodies/JUnit PASS; no counts transferred, no retry started; remaining4 orders/119isolated NOT_EXECUTED. Read decision request draftPR232 at 8be2b87a936bbc52909ae0e489d65a68dbc1fbac and versioned diagnosis before any resumption. Same teardown-observation class recurs in historic full: PO infra-rerun rule requires decision, no blind retries. After resolved infrastructure authority, prove observation-only scope to retain full or rerun entire campaign; then all required orders/isolated, exact JUnit identity/order, zero skip/fail/error/restart/OOM/residue, final teardown. Request verifier only after complete fresh final-head evidence and REGRESSION_ONLY0050 supersession198 unchanged tests; historic Claude Code reserve isolation/VF-001 and Codex oracle/qualification; verifier Grok4.7(Cursor). VerifiedREM19 ->REM17 ->0049 integration ->REM23 before preserved0056 WIP. E1/E2/Verified and NO-GO unchanged.

- Gate locali del checkpoint: 9/9 exit0 (digest, ruff, mypy strict, RCCAD, scope e piano su origin/main esatto, language, drift, runtime evidence0055). Output planning generati archiviati e ripristinati. Nessuna nuova suite o ripetizione avviata da questa unità; campagna interrotta e qualifica bloccata dalla decision request. Il PASS dei gate di metadati non qualifica il run exit130. CI del nuovo checkpoint ancora da acquisire.
