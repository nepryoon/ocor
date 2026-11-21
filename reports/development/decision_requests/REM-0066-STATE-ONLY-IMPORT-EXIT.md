# REM-0066-STATE-ONLY-IMPORT-EXIT

Stato: `DECIDED_BY_PO`.
Disposition: opzione 1, decisa per conto del PO, modello claude-fable-5-2, effort max. Il file pubblicato a `34053edb0c4d9167598b649c46cc84a893094d36` resta sha256 `c180b11ef72957a9b66cc066ec2c2da8f9f28d0c0ef7f0a79a6ba2bfcf65791d`. Rosso `5e559b8223cd0a5b8c47170fb0916a9975da4d9f`, verde `6b5a5a2a3c8a5cfdb396c5f9eb4a8f7cb01b19c1`, sul branch `governed/ocor-dev-rem-0066-state-only-ci`. La raccolta con i cinque ignore esce 0. I quattro script v12 escono 0, il referto dello schema è solo quello noto e i cinque JSON tornano ai byte fotografati. `PRE-CAMPAIGN-GATE` su quel verde è FAIL solo a `state-only-ci-path`, exit 1: `gates.json` sha256 `e71c207647a3cee8e629dd29d6fcd5bc3b414c1637f94612bccfaf8c974c5683`. Pytest esegue `ConsumerRegistryScope.test_exact_seeding_only_diff` e fallisce. Quel guard è fuori dall'opzione. La richiesta nuova è `REM-0066-STATE-ONLY-REM0031-GUARD`, commit `08e4149180f96ac08273bd5e4ee0963214b34ed8`, sha256 `5f2a013eccf70f3033d1480b7e1a2b84ea9c4cd2c6464d0603837ee5ef43b23c`, bozza PR #734, non si integra e nessuna sua opzione è applicata. Non si scrive `prereview_request.json`. La suite completa non parte. Claim invariati. Questa PR si chiude come risolta e non si integra.
Livello: operativo. Unità: `OCOR-DEV-REM-0066`.
Head di `origin/main` alla pubblicazione: `51cfe1f0041fb24c9a83eba4a82324099cd06337`.
Branch dell'unità, senza commit nuovi: `governed/ocor-dev-rem-0066-state-only-ci`, HEAD `fe913c06a22d6fd48915dff177d6145de69b0a40`.
Richiesta già decisa, opzione 2 non applicata: `REM-0066-CANONICAL-R1-HUMAN-GATE (2026-11-18)`, commit `32a15467d8cc46626d58c1a3eeed79c998366f95`, sha256 `8c8aa9596430144a15f3470e2ac2e59a6f7b52eeeb0b92614ffdceb63906686b`, bozza PR #684.

## Contesto

`REM-0066-CANONICAL-R1-HUMAN-GATE (2026-11-18)` adotta l'opzione 2. Il testo, al commit citato, dice: non si modifica `inputs/` né l'atteso `REJECT`; non si cambia `sys.exit(1 if summary["failed"] else 0)` alla riga 417 di `reports/tests/test_schema_conformance.py`; in `scripts/run_state_only_ci_path.py` pytest di `reports/tests` non importa quel file; lo stesso passo lo esegue come script; il passo esce 0 solo se il referto è esattamente `TOTAL 98 PASS 97 FAIL 1` e l'unico FAIL è `urn:ocor:schema:action-type-contract:1.0 — negativo semantico: CANONICAL_COMMIT R1 senza Human Gate` con osservato `ACCEPT`. Ogni altro FAIL, un caso mancante o un atteso diverso fanno uscire il passo con un codice diverso da 0.

Quel testo non nomina gli altri moduli di `reports/tests` che chiamano `sys.exit` durante l'import. Far uscire 0 il passo richiede di non importarli in pytest, oppure di riscriverli. Entrambe le cose vanno oltre l'opzione 2. Nessuna delle due è stata pubblicata. Il branch resta a `fe913c06a22d6fd48915dff177d6145de69b0a40`. `PRE-CAMPAIGN-GATE` non è stato rieseguito. La suite completa non è partita. Non si scrive `prereview_request.json`.

Il comando pytest del passo è alle righe 66–68 di `scripts/run_state_only_ci_path.py`: `python -m pytest reports/tests -m "not requires_live_stack" -q`. Il test `FastPathCommandTests.test_commands_use_the_folder_marker_and_not_a_hand_written_list` in `reports/tests/test_classify_pull_request_ci_route.py`, riga 376, fissa quell'argv e, alla riga 429, rifiuta l'espressione `reports/tests/test_[A-Za-z0-9_]+\.py` nell'elenco dei comandi. Pytest, senza una configurazione diversa, raccoglie i file `test_*.py`.

## Prove

Misure sull'HEAD `fe913c06a22d6fd48915dff177d6145de69b0a40`, working tree pulito, interprete `ocor-runtime/.venv/bin/python`.

`sys.exit` a livello di modulo, confermato sull'albero sintattico:

- `reports/tests/test_schema_conformance.py`, riga 417
- `reports/tests/test_v12_approval_readiness.py`, riga 70
- `reports/tests/test_v12_candidate.py`, riga 462
- `reports/tests/test_v12_release_gate.py`, riga 138
- `reports/tests/test_v12_semantics.py`, riga 213
- `reports/tests/build_validation_closure_report.py`, riga 187
- `reports/tests/validate_openapi_governed.py`, riga 124

I primi cinque hanno il nome `test_*.py` e pytest li raccoglie. Gli ultimi due no: non sono la causa dell'uscita 3.

Raccolta con il solo ignore autorizzato dall'opzione 2:

`python -m pytest reports/tests -m "not requires_live_stack" --ignore=reports/tests/test_schema_conformance.py --collect-only -q -p no:cacheprovider`

Esito: codice 3. Stderr: `mainloop: caught unexpected SystemExit!`. Il traceback termina in `reports/tests/test_v12_approval_readiness.py`, riga 70, `sys.exit(1 if failed else 0)`, `SystemExit: 0`. Lo stdout chiude con `950 tests collected in 0.18s`. Il nome `test_schema_conformance` non compare né nello stdout né nello stderr. Il conteggio 950 è parziale: la raccolta si interrompe su quell'eccezione.

La stessa raccolta con cinque ignore, uno per ciascun `test_*.py` della lista sopra, esce 0: `968/971 tests collected (3 deselected) in 0.29s`. Nessuno dei cinque nomi compare nello stdout o nello stderr. I tre deselected sono il marcatore `requires_live_stack`, non uno dei cinque file.

Esecuzione come script, sullo stesso HEAD. Dopo ogni script il working tree è stato ripristinato.

- `reports/tests/test_schema_conformance.py`: codice 1. Unica riga `FAIL`: `FAIL urn:ocor:schema:action-type-contract:1.0 — negativo semantico: CANONICAL_COMMIT R1 senza Human Gate [ACCEPT]`. Riga `TOTAL 98 PASS 97 FAIL 1`. `reports/tests/conformance_results.json` resta ai byte tracciati.
- `reports/tests/test_v12_approval_readiness.py`: codice 0. `TOTAL 18 PASS 18 FAIL 0`. Riscrive `reports/tests/v12_approval_readiness_results.json`. Sha256 prima `b3bada245d4dcd489a493765889f1fb46021e241bc3e1545fbed496e9f37fd39`, dopo `a4ca71a012f64d0c9ff70575bc9dc00c83f30578a27bcf884b377cba9deaa17e`. `git hash-object` prima `8c13b83bcf2eff996a2fd95ffbd5d8146f7324aa`, dopo `aeff7563103ae82275a98b130c06cadfa64ef2f9`.
- `reports/tests/test_v12_candidate.py`: codice 0. `TOTAL 105 PASS 105 FAIL 0`. `reports/tests/v12_conformance_results.json` invariato.
- `reports/tests/test_v12_release_gate.py`: codice 0. `TOTAL 12 PASS 12 FAIL 0 HUNKS 60`. `reports/tests/v12_release_gate_results.json` invariato.
- `reports/tests/test_v12_semantics.py`: codice 0. `TOTAL 29 PASS 29 FAIL 0`. `reports/tests/v12_semantic_results.json` invariato.
- `reports/tests/build_validation_closure_report.py`: codice 0, non raccolto da pytest. Riscrive `reports/tests/validation_closure_results.json`.
- `reports/tests/validate_openapi_governed.py`: codice 0, non raccolto da pytest. Riscrive `reports/tests/openapi_31_validation_results.json`.

`reports/tests/test_schema_conformance.py` e `reports/tests/test_v12_approval_readiness.py` compaiono fra gli input di record sotto `reports/evidence/`. `scripts/run_state_only_ci_path.py` e `reports/tests/test_classify_pull_request_ci_route.py` non compaiono in quei JSON. Questa pubblicazione non modifica nessuno di questi file.

Implementatore di `OCOR-DEV-REM-0066` e di questa richiesta: Grok Build, modello grok-4.7, fornitore xAI. Nessun verifier è stato avviato. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Quesito

Come fa il passo di `scripts/run_state_only_ci_path.py` a uscire 0, conservando il referto noto di `reports/tests/test_schema_conformance.py`, se pytest di `reports/tests` esce 3 anche dopo aver escluso solo quel file, perché `reports/tests/test_v12_approval_readiness.py` e gli altri `test_*.py` con `sys.exit` a livello di modulo sono ancora importati?

## Opzioni

1. **Separare da pytest i cinque script raccolti e accettare solo gli esiti misurati.** Sul branch `governed/ocor-dev-rem-0066-state-only-ci`, un commit nuovo sopra `fe913c06a22d6fd48915dff177d6145de69b0a40`, senza rebase, reset o force-push. Non si modifica `inputs/`. Non si modifica `reports/tests/test_schema_conformance.py`, né la riga 417. Non si modificano i quattro script v12, né `reports/tests/build_validation_closure_report.py`, né `reports/tests/validate_openapi_governed.py`. In `scripts/run_state_only_ci_path.py` il comando pytest resta la cartella `reports/tests` con il marcatore `not requires_live_stack` e `-q`, e aggiunge esattamente questi argomenti, prima di `-q`: `--ignore=reports/tests/test_schema_conformance.py`, `--ignore=reports/tests/test_v12_approval_readiness.py`, `--ignore=reports/tests/test_v12_candidate.py`, `--ignore=reports/tests/test_v12_release_gate.py`, `--ignore=reports/tests/test_v12_semantics.py`. Non si elenca la suite. Lo stesso passo, dopo pytest a codice 0, esegue i cinque file come script, con lo stesso interprete, in quest'ordine. Per `reports/tests/test_schema_conformance.py` il codice del processo non decide: il passo esce 0 solo se lo stdout contiene esattamente una riga `TOTAL 98 PASS 97 FAIL 1`, esattamente 97 righe che iniziano con `PASS `, ed esattamente una riga `FAIL`, uguale a `FAIL urn:ocor:schema:action-type-contract:1.0 — negativo semantico: CANONICAL_COMMIT R1 senza Human Gate [ACCEPT]`. Ogni altro FAIL, un caso mancante o un'osservazione diversa fanno uscire il passo con un codice diverso da 0. Lo schema continua ad accettare l'istanza. Per ciascuno dei quattro script v12 il passo esce 0 solo se il processo esce 0. Un codice diverso da 0 del processo è un codice diverso da 0 del passo. Non si accetta un FAIL noto di quei quattro. Prima degli script si fotografano i byte di `reports/tests/conformance_results.json`, `reports/tests/v12_approval_readiness_results.json`, `reports/tests/v12_conformance_results.json`, `reports/tests/v12_release_gate_results.json` e `reports/tests/v12_semantic_results.json`. Dopo gli script si ripristinano quei byte. Se il ripristino non torna alla fotografia, il passo esce con un codice diverso da 0. I due script non raccolti da pytest non si eseguono e non si ignorano. In `reports/tests/test_classify_pull_request_ci_route.py` il test alla riga 376 accetta i cinque `--ignore` nell'argv di pytest e continua a rifiutare ogni altro percorso `reports/tests/test_[A-Za-z0-9_]+\.py` dopo aver tolto solo quelle cinque stringhe. Resta il divieto di `bootstrap_ci_environment.py` e di `run_qualifying_campaign.py`. Si aggiungono asserzioni sul comando dei cinque script, sul referto noto accettato, su un FAIL in più, su un caso mancante e su un'osservazione diversa. Il rosso precede il verde. Se, con quei cinque ignore, la raccolta esce ancora diverso da 0, ci si ferma e si apre una richiesta nuova: non si aggiungono ignore nello stesso change set. Se `scripts/validate_evidence_input_drift.py` segnala un input sigillato fra i due file modificati, ci si ferma e si apre una richiesta nuova con l'elenco: non si riqualifica dentro questa opzione. Poi si riesegue `PRE-CAMPAIGN-GATE` su quel HEAD. La suite completa non parte nella stessa iterazione del gate. La revisione preventiva si chiede solo dopo un gate PASS. Nessun nuovo `DEC-*`. Claim invariati. Accettazione: la raccolta con i cinque ignore esce 0 e non nomina i cinque file; i quattro script v12 escono 0; il referto dello schema è solo quello noto; i cinque JSON tracciati tornano ai byte fotografati; il test del comando rifiuta ancora un elenco scritto a mano. Costo onesto: un commit su due file già presenti, i test del passo, e un `PRE-CAMPAIGN-GATE` sull'HEAD nuovo. Non si riscrivono gli script e non si toccano record sigillati.

2. **Rendere importabili i quattro script v12.** Si sposta il corpo eseguibile di `reports/tests/test_v12_approval_readiness.py`, `reports/tests/test_v12_candidate.py`, `reports/tests/test_v12_release_gate.py` e `reports/tests/test_v12_semantics.py` sotto `if __name__ == "__main__"`, così pytest li importa senza `SystemExit`. `reports/tests/test_schema_conformance.py` resta escluso da pytest ed eseguito come script, con la stessa regola di referto dell'opzione 2 di `REM-0066-CANONICAL-R1-HUMAN-GATE (2026-11-18)`. I quattro file, in particolare `reports/tests/test_v12_approval_readiness.py`, compaiono fra gli input dei record sotto `reports/evidence/`. L'opzione non dice quali record riqualificare, né come il test alla riga 376 debba trattare l'ignore che resta. Accettazione: pytest di `reports/tests` con il solo ignore dello schema esce 0, e i quattro script, eseguiti come programmi, conservano i totali misurati sopra. Costo onesto: quattro script riscritti, più l'inventario e le riqualifiche degli input sigillati, che questa opzione non elenca. Resta incompiuta la regola del passo finché inventario e riqualifiche non sono decisi. Non raccomandata.

3. **Fermare OCOR-DEV-REM-0066 sull'HEAD attuale.** Non si modifica `scripts/run_state_only_ci_path.py` né `reports/tests/test_classify_pull_request_ci_route.py`. L'HEAD resta `fe913c06a22d6fd48915dff177d6145de69b0a40`. Non si riesegue `PRE-CAMPAIGN-GATE`, non si scrive `prereview_request.json` e non si avvia la suite completa. Il passo continua a uscire 3. Gli altri task non bloccati da una richiesta aperta proseguono. Nessun nuovo `DEC-*`. Claim invariati. Accettazione: il branch non riceve commit e il gate resta FAIL. Costo onesto: nullo sul codice, e il percorso state-only resta fermo. Resta incompiuto il passo che l'opzione 2 già adottata chiedeva di far uscire 0. Non raccomandata.

## Raccomandazione

Opzione 1. È l'unica che fa uscire 0 il passo, esegue ancora i cinque controlli con gli esiti misurati su `fe913c06a22d6fd48915dff177d6145de69b0a40`, e mantiene obbligatorio l'unico FAIL noto dello schema, senza riscrivere file citati dai record di evidenza. L'opzione 2 sposta il lavoro su script che sono input di record sigillati e non chiude da sola la regola del referto. L'opzione 3 lascia il passo a codice 3. Chi apre questa richiesta non ne applica nessuna opzione.

## Impatto e task bloccati

Finché questa richiesta è aperta, `OCOR-DEV-REM-0066` è bloccato. Non si modifica `scripts/run_state_only_ci_path.py`, `reports/tests/test_classify_pull_request_ci_route.py`, i cinque script, `inputs/` né i record sigillati. Non si aggiunge un commit sopra `fe913c06a22d6fd48915dff177d6145de69b0a40`. Non si riesegue `PRE-CAMPAIGN-GATE` e non si avvia la suite completa. `OCOR-DEV-REM-0063` resta bloccato da `REM-0063-CI-ARGV-LAUNCHER`, non da questa richiesta. La PR #722 non riceve commit e non si mergia. Non si apre un `repair_cycle` 14. I job con `[Errno 7] Argument list too long` non si rilanciano. Lo sha256 del record di unità sigillato resta `70b17ee909c81c9da2fd0aa546c91d994e9dab6649fbf259c98a4502b92ea9ef`. Nessun nuovo `DEC-*`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist del validatore del piano per il percorso di questa richiesta non fa parte di questa pubblicazione.
