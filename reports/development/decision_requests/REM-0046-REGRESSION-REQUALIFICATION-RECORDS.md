# REM-0046-REGRESSION-REQUALIFICATION-RECORDS

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Riguarda l'unità `OCOR-DEV-REM-0046` (NCP-U13 di
`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`) e ogni unità successiva del programma. Due prescrizioni della stessa
decisione non si possono soddisfare insieme senza una scelta riservata al PO: la condizione 1 del punto 3 e le
riqualifiche di sola regressione di `OCOR-DEV-0005`, `0050` e `0082`, che il programma considera sempre previste.

## Contesto

- Punto 3, condizione 1: «un validatore fail-closed rifiuta ogni record nuovo che lega un caso a un requisito non
  dichiarato dal test, o che non ha i campi di `NFR-004` e di LLD v1.1 §7.3». I record sigillati esistenti sono
  riconosciuti per percorso e sha256; ogni altro record è nuovo.
- `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)` punti 4.g, 7 e «Stop», e `plan_units.NCP-U13.requalifications`
  (`always_regression_only`): ogni unità aggiunge i nuovi percorsi all'elenco di
  `scripts/validate_ocor_development_plan.py`; quel file è fra gli `inputs` degli ultimi record di `0005`, `0050` e
  `0082` (`*.requalified-rem0045.json`), quindi ogni unità produce per loro un record di riqualifica nuovo.
- Il validatore di NCP-U13 (`scripts/validate_runtime_evidence.py`, branch
  `governed/ocor-dev-rem-0046-ncp-u13-plan-evidence-governance`, head `7b4b6a5`) realizza la condizione 1:
  ogni record nuovo deve avere `requirement_results`, ogni caso tutti i campi del pacchetto di evidenza
  (requisito, metodo del Register, metrica, soglia, baseline, dataset o scenario, release, risultato, raw log,
  owner, firma) e ogni requisito deve essere dichiarato dai test del caso (nel sorgente del test; i legami
  dell'indice di tracciabilità inversa non valgono come dichiarazione). Il test RED della condizione
  (`reports/tests/test_ocor_dev_rem_0046.py::test_ncr_evidence_002_conforms`) prevede il rifiuto di un record
  nuovo senza casi.
- Le riqualifiche di sola regressione legano oggi i loro casi al requisito del task: `BR-003` per `0005`
  (metodo del Register «test/dimostrazione», quindi servono test che lo dichiarino e l'evidenza della
  dimostrazione), `BR-003` per `0050` e `0082`. Nessuno dei test che rieseguono
  (`ocor-runtime/tests/tasks/test_ocor_dev_0005.py`, `test_ocor_dev_0050.py`, `test_ocor_dev_rem_0023.py`,
  `reports/tests/test_reset_teardown_residue.py`, `test_kind_teardown_observation.py`,
  `test_rem0034_secret_registry.py`) nomina un requisito.

Quindi una riqualifica di sola regressione prodotta da NCP-U13 o da un'unità successiva viene rifiutata dal
validatore, qualunque sia il suo contenuto, a meno di cambiare i test (non previsto dal punto 5) o la regola.

## Opzioni

1. **Classe dichiarata di record non qualificanti (raccomandata).** Un record di riqualifica di sola regressione
   dichiara `requalification_kind: "regression"` e `qualifies_requirements: false`, ha `supersedes` verso il
   record precedente dello stesso task e non ha `requirement_results`. Il validatore:
   - gli applica tutti i controlli che non riguardano i requisiti (comandi eseguiti, raw log content-addressed,
     `PASS`, contatori `failed`/`skipped`/`not_executed`/`xfailed` a zero, campi obbligatori);
   - lo rifiuta se contiene anche un solo caso legato a un requisito, se manca `supersedes` o se il record
     superato non è dello stesso task;
   - non lo conta mai come evidenza di un requisito (`--requirement-evidence` e criteri di `OCOR-DEV-0067`).

   I casi negativi entrano in `reports/tests/test_runtime_evidence_validator.py`. Nessun record che lega un caso
   a un requisito sfugge alla condizione 1: la classe non qualifica nulla.
2. **Dichiarare i requisiti nei test rieseguiti.** Si aggiunge ai sei moduli una docstring con i requisiti dei
   loro task, senza toccare funzioni, asserzioni o parametri. È una modifica di test fuori dal punto 5, cambia
   input di record sigillati (altre riqualifiche) e lega test di tooling a requisiti generici come `BR-003`,
   contro la direzione di `NCR-PLAN-001`/`NCR-EVIDENCE-001`.
3. **Mantenere il formato attuale delle riqualifiche.** I record di sola regressione restano nel formato
   attuale e il validatore li elenca come record nuovi non conformi. La condizione 1 non sarebbe soddisfatta
   nel repository: lo escludiamo, ma lo riportiamo per completezza.

**Raccomandazione**: opzione 1. Le regole di `NFR-003`/`NFR-004` riguardano l'evidenza dei requisiti, e una
riqualifica di sola regressione non qualifica nulla: dimostra che i test di un task chiuso passano ancora sul
nuovo head. L'opzione 1 rende questo fatto esplicito e verificabile: ogni record che lega un requisito resta
soggetto a tutte le regole, e nessun test o soglia si allenta.

## Impatto e task bloccati

- Bloccati in attesa della decisione: le riqualifiche di `0005`, `0050` e `0082` di `OCOR-DEV-REM-0046`, quindi
  la sua campagna, la verifica indipendente, il sigillo e il merge; a cascata le unità successive di
  `plan_order` (NCP-U01 … NCP-U12), che dipendono dall'integrazione di NCP-U13 e producono le stesse
  riqualifiche.
- Proseguono: il resto del GREEN di NCP-U13 (allowlist dei nuovi percorsi, hash degli artefatti del piano,
  record dell'unità, transizioni del registro, `PRE-CAMPAIGN-GATE`).
- Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessun
  nuovo `DEC-*`. `main` al momento della richiesta: `ccf01549c1024aec7dcc7982b7a243a06e347d18`.

Interpretazione registrata: `CC-OCOR-DELIVERY-COMPLETION` §7 chiede la lettura fail-closed più restrittiva.
L'opzione 1 cambia l'ambito della condizione 1 rispetto alla sua lettura letterale («ogni record nuovo»), e
l'opzione 2 cambia test fuori dal punto 5: entrambe sono scelte normative, quindi riservate al PO.

## Disposition del Product Owner — 2026-10-30

Decisione normativa del PO `REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30)`: opzione 1 (classe dichiarata di record non qualificanti), con le precisazioni dei punti 2 e 3 della decisione. Il testo integrale della decisione, riportato qui sotto senza modifiche salvo il livello del titolo, è la disposition di questa richiesta. La richiesta decisa è il file al commit `86559cf`, sha256 `2095cd3ba20db529be33240ab8cfad969d61fd4d297d7bae85df497b5cd2b851`. Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`; claim invariati.

### REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30) — decisione normativa del PO

Decisione **di livello normativo**, presa dal PO con istruzione esplicita, sulla decision request `REM-0046-REGRESSION-REQUALIFICATION-RECORDS` (`reports/development/decision_requests/REM-0046-REGRESSION-REQUALIFICATION-RECORDS.md`, PR #432, commit `86559cf`, sha256 `2095cd3ba20db529be33240ab8cfad969d61fd4d297d7bae85df497b5cd2b851`). Il PO sceglie l'opzione 1, con le precisazioni dei punti 2 e 3. Integra il punto 3 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (condizione 1 e paragrafo su `OCOR-DEV-0061`). Nessun nuovo `DEC-*`. Restano invariati ADD, LLD, contratti, schemi, registri normativi e claim.

1. **Record di riqualifica di sola regressione: classe non qualificante.**
   - Il record dichiara `requalification_kind: "regression"` e `qualifies_requirements: false`, ha `supersedes` verso il record precedente dello stesso task e non ha `requirement_results` né casi legati a requisiti.
   - Il validatore di NCP-U13 (`scripts/validate_runtime_evidence.py`) gli applica tutti i controlli che non riguardano i requisiti: comandi eseguiti, raw log content-addressed, esito `PASS`, contatori `failed`, `skipped`, `not_executed` e `xfailed` a zero, campi obbligatori.
   - Lo rifiuta se contiene anche un solo caso legato a un requisito, se manca `supersedes` o se il record superato non è dello stesso task.
   - Non lo conta mai come evidenza di un requisito, né in `--requirement-evidence` né nei criteri di `OCOR-DEV-0067`.
   - I casi negativi di queste regole entrano in `reports/tests/test_runtime_evidence_validator.py`, nell'ambito di NCP-U13. Un record che lega un caso a un requisito resta soggetto a tutte le regole della condizione 1.
2. **Ambito.** La classe vale per ogni riqualifica di sola regressione autorizzata dal programma o dalle decisioni del PO e prodotta da NCP-U13 in poi: quelle di `OCOR-DEV-0005`, `0050` e `0082` di ogni unità, quelle del punto 7 (dipendenze, NCP-U06), quelle del punto 2 (spostamento degli adapter, NCP-U11) e quelle di `OCOR-DEV-0061` prima della sua riqualifica con supersession. Per `0061` sostituisce la frase del punto 3 di `NORMATIVE-CONFORMANCE-PLAN` secondo cui il record di regressione dichiara «fuori dal profilo PoC» i legami con `FR-135`, `NFR-025` e `NFR-033`: il record di regressione di `0061` non lega alcun requisito. La riqualifica con supersession di `0061` è invece qualificante e segue tutte le regole della condizione 1.
3. **Evidenza dei requisiti per `OCOR-DEV-0067`.** L'evidenza di un requisito resta quella dell'ultimo record qualificante della catena `supersedes` del task. Un record di regressione attesta che quel record regge all'head della riqualifica; non lo sostituisce come evidenza e non ne estende i requisiti. I record sigillati non conformi restano esclusi (condizione 2 del punto 3).
4. **Nessun allentamento.** Nessun test, soglia, limite, timeout o gate cambia. I test rieseguiti dalle riqualifiche non cambiano: l'opzione 2 non è scelta.
5. **Registrazione.** Al primo state sync registra questa decisione come disposition nel file della decision request, secondo `AGENTS.md`, e nell'`ITERATION_LOG.md`. Se il validatore del piano non ammette il file della decision request in un change set di solo stato, il file entra in `main` con il change set di NCP-U13, come per `NORMATIVE-CONFORMANCE-PLAN`. Poi riprendi `OCOR-DEV-REM-0046` dal punto in cui si è fermato.
