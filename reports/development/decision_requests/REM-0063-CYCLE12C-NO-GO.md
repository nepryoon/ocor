# REM-0063-CYCLE12C-NO-GO

Stato: `DECIDED_BY_PO`.
Livello: operativo. Unità: `OCOR-DEV-REM-0063`.
Verdetto: `OCOR-DEV-REM-0063-2e4a3e51220a-12`, esito `NO_GO`, sha256 `e70d58bed97c278a882ab70bd3325a987d20a0775936679aa95b316960f501f3`.
Head verificato: `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`.
Commit di comportamento del codice: `da754e862a2c2fba621cf5d4534fcc5396299b6a`.
Impronta del validatore del piano su quell'HEAD: `f06c2ebc0631d0ad4766d9e8109154fa030f9399501c0c8b79ff8bf37ad831a0`.
Impronta di `reports/planning/OCOR_PLAN_RUN_STATE.json` su quell'HEAD: `723af7b47239eace4cb92c51b8e27b3c7101f291893a2a6b51411106e3e06563`.
Branch di produzione: `governed/ocor-dev-rem-0063-mcp-profile`, fermo a `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.

## Contesto e perimetro

`REM-0063-CYCLE12-NO-GO (2026-11-19)` opzione 1 è attuata. Non era un ciclo 13: commit di allowlist `2b8a9c33`, settle `673656f3`, otto record `cycle12c` su `0c48624c`, riallineamento `698b944a`, campagna `698b944a1de4-1795114196`, controllo distinto `698b944a1de4-1795117669`, poi il solo riallineamento di hash `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19` richiesto da `REM-0063-CYCLE12-UNIT-RECORD-INPUTS (2026-11-19)` opzione 1. Il `required_fix` del finding bloccante di questo verdetto dice che `REM-0063-CYCLE12-NO-GO` esclude un ciclo 13 automatico e che serve una decisione sul seguito dell'unità. Questa è quell'unica richiesta. Finché è aperta il candidato non si modifica, non si integra e non si sigilla. Non si apre un `repair_cycle` 13.

La campagna `698b944a1de4-1795114196` e il controllo distinto `698b944a1de4-1795117669` restano storici dell'HEAD `698b944a1de4ef78a39346a034bed1a5e6fe4b10`: non sono il PASS di un HEAD successivo e non trasferiscono conteggi. La campagna `a3bd36d3ab51-1795089861` resta PASS storica. Le campagne diagnostiche `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` restano FAIL e non sono un PASS.

Implementatori già dichiarati dell'unità, da riportare in ogni richiesta successiva: Grok Build `grok-4.7` (xAI) per il ciclo originale, le riparazioni 1–6, il completamento del ciclo 8, il ciclo 9, il codice e il candidato del ciclo 10, il ciclo 11, il ciclo 12 e questa richiesta; Codex CLI `deepseek-flash` e `deepseek-v4-pro` (DeepSeek) per i cicli 7 e 8; Codex `gpt-6.1-sol` (OpenAI) per la fase A del ciclo 10. Verifier di questo verdetto: Claude Code, `claude-opus-5-5`, Anthropic, effort `max`. Revisore preventivo del ciclo 12: Claude Code, `claude-fable-5-2`, Anthropic, effort `max`, stesso fornitore del verifier e modello diverso, limite autorizzato da `VERIFIER-CLAUDE-REM0063 (2026-11-16)`. Nessun implementatore Anthropic.

## Prove

Finding bloccante, sull'HEAD `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19`.

| ID | Gravità | Classe | Fatto |
| --- | --- | --- | --- |
| VF-001 | high | codice, risoluzione dei riferimenti | `validate_mcp_descriptor` accetta uno schema che `Draft202012Validator` rifiuta. In `mcp_profile.py`, `_resolve_graph` scarta l'errore statico di ogni nodo raggiunto da un percorso di riferimento, anche se il nodo è in posizione applicativa. Esempio del verdetto: `inputSchema` con `$id` `https://v.invalid/root.json`, `properties.p` che ha `$anchor` `pa` e `$ref` `#/$defs/x`, `properties.q` che ha `$ref` `#pa`, e `allOf` con lo stesso `$id` e `$defs.x` di tipo stringa. `Draft202012Validator.check_schema` accetta, ma `iter_errors` su `{"p": "a"}` con il registro pinnato solleva `PointerToNowhere` perché `properties.p` è valutato nel registro pinnato, dove la radice non ha `$defs/x`. Il profilo accetta il descriptor. Il gemello senza ancora è rifiutato. Il docstring e il README dicono che un fallimento statico può essere irrilevante. Nessuna decisione del PO autorizza questa esenzione. Il campione del verifier: 64/64 celle divergenti sulla dimensione descritta nel `required_fix`; 51200/51200 celle già consegnate concordano; il generatore non esprime la classe. |

Finding non bloccanti dello stesso verdetto, non corretti da questa pubblicazione.

| ID | Gravità | Fatto |
| --- | --- | --- |
| VF-002 | low | `OCOR-DEV-0005-requalified-rem0063-d215c7d2c1dc`, `OCOR-DEV-0050-requalified-rem0063-d215c7d2c1dc` e `OCOR-DEV-0082-requalified-rem0063-d215c7d2c1dc` falliscono `check_execution_commit_inputs.py` e nessun record li supersede. Il record dell'unità li classifica come `PASS_BY_DISTINCT_SUCCESSOR`. `select_most_recent` sceglie i `cycle12c`. |
| VF-003 | low | Dopo `2e4a3e51`, `commit` è `aaf98a28`, ma `commit_role`, `environment.stack` e `environment.branch_note` nominano ancora `a3bd36d3`. La sezione `Cycle 12 record` del README dice che il codice resta `b1cd0832`, mentre `da754e86` ha cambiato `mcp_profile.py` e `codegen.py`. Il record non nomina `REM-0063-CYCLE12-UNIT-RECORD-INPUTS`. |

## Quesito

Come si chiude VF-001, l'esenzione che rende il profilo più permissivo di `Draft202012Validator` sui nodi in posizione applicativa, insieme ai finding non bloccanti VF-002 e VF-003, quando un ciclo 13 automatico è escluso?

## Opzioni

1. **Un solo ciclo autorizzato: esenzione ristretta alle definizioni, successori `cycle12d`, record allineato.** Raccomandata. È la chiusura completa della divergenza fail-closed e dei due finding di evidenza. Non aggiunge funzioni. Parte dall'HEAD `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19` con commit nuovi, senza rebase, reset o force-push. Il branch di produzione resta fermo. `repair_cycle` della richiesta di verifica è 13. Se il parent del commit di allowlist non ha ancora lo sha256 `f06c2ebc0631d0ad4766d9e8109154fa030f9399501c0c8b79ff8bf37ad831a0` di `scripts/validate_ocor_development_plan.py`, ci si ferma e non si inventa un'altra modifica dell'allowlist.

   Codice, prima dei record. Si toccano solo `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`, `ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py` e, nel commit di record, `reports/assurance/OCOR-DEV-REM-0063-RCCAD/OCOR-DEV-REM-0063.json` e `reports/assurance/OCOR-DEV-REM-0063-RCCAD/README.md`. `codegen.py`, `scripts/check_execution_commit_inputs.py`, `scripts/validate_evidence_input_drift.py` e gli altri file di produzione non cambiano. Se un test del generatore fallisce, ci si ferma e si apre una sola richiesta nuova.

   In `_resolve_graph` un errore statico di `$ref` rifiuta il descriptor per ogni nodo raggiunto dalla discesa statica esistente, salvo i nodi raggiungibili dalla radice soltanto attraverso `$defs` o `definitions`. Un nodo raggiunto anche da `properties`, `patternProperties`, `items`, `prefixItems`, `allOf`, `anyOf`, `oneOf`, `not`, `if`, `then`, `else`, `dependentSchemas` o `contains` non è esente, qualunque percorso di ancora lo raggiunga. Non si aggiungono keyword alla discesa. Il docstring della regola e le frasi del README che dicono che un fallimento statico può essere irrilevante, compresa `A static failure still refuses the descriptor only when no reference path reaches that node`, si riscrivono su questa regola e citano questa decisione. Non introducono altra semantica.

   RED prima del GREEN, nello stesso file di test. La dimensione mancante è quella del `required_fix`: contesto del nodo in posizione applicativa il cui `$ref` fallisce nel registro pinnato ed è raggiunto anche da `$anchor` o `$dynamicAnchor` sul registro crawlato; incrocio con l'URI di base della radice ripetuto, letterale, con `#` finale o con grafia relativa equivalente, in `allOf`, `anyOf`, `not` e `$defs`, entrambi gli ordini, entrambi i campi, ingresso dell'ancora da applicatore e da `$defs` non referenziato. Oracolo: `referencing` 0.37.0 e `Draft202012Validator` sullo schema da solo, con la base B1 già fissata, e un'istanza positiva che raggiunge il nodo. Dove le librerie rifiutano, il profilo rifiuta. Dove accettano, il profilo accetta. Il gemello senza ancora che le librerie rifiutano resta rifiutato. Un caso positivo e uno negativo coprono il nodo raggiungibile solo da `$defs` o `definitions`, che resta esente. Nessuna cella esistente si toglie. Un test esistente si aggiorna solo se asseriva l'esenzione ora rimossa, nello stesso commit RED, con tabella nel record dell'unità: funzione, identificativo, aspettativa precedente, aspettativa nuova, esito delle librerie. Se un test esistente fallisce per un'altra causa, ci si ferma e si apre una sola richiesta. La regola di riallineamento del solo ciclo 10 non si riusa.

   Poi l'allowlist. L'unico cambiamento di quel commit sono esattamente questi ventidue percorsi, e nessun altro:

   - `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0063-cycle12d.json`
   - `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0063-cycle12d.log`
   - `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0063-cycle12d.json`
   - `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0063-cycle12d.log`
   - `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0063-cycle12d.json`
   - `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0063-cycle12d.log`
   - `reports/evidence/G2/OCOR-DEV-REM-0037.requalified-rem0063-cycle12d.json`
   - `reports/evidence/G2/OCOR-DEV-REM-0037.requalified-rem0063-cycle12d.log`
   - `reports/evidence/G2/OCOR-DEV-REM-0047.requalified-rem0063-cycle12d.json`
   - `reports/evidence/G2/OCOR-DEV-REM-0047.requalified-rem0063-cycle12d.log`
   - `reports/evidence/G2/OCOR-DEV-REM-0056.requalified-rem0063-cycle12d.json`
   - `reports/evidence/G2/OCOR-DEV-REM-0056.requalified-rem0063-cycle12d.log`
   - `reports/evidence/G2/OCOR-DEV-REM-0062.requalified-rem0063-cycle12d.json`
   - `reports/evidence/G2/OCOR-DEV-REM-0062.requalified-rem0063-cycle12d.log`
   - `reports/evidence/G2/OCOR-DEV-REM-0064.requalified-rem0063-cycle12d.json`
   - `reports/evidence/G2/OCOR-DEV-REM-0064.requalified-rem0063-cycle12d.log`
   - `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0063-cycle12d-orphan.json`
   - `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0063-cycle12d-orphan.log`
   - `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0063-cycle12d-orphan.json`
   - `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0063-cycle12d-orphan.log`
   - `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0063-cycle12d-orphan.json`
   - `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0063-cycle12d-orphan.log`

   Gli otto `cycle12c` citano il validatore `f06c2ebc` e diventano stantii quando l'allowlist cambia. Vanno superseduti, non riscritti. I tre orfani vanno superseduti perché sono teste di biforcazione non superate. Se il validatore riscrive soltanto l'hash in `reports/planning/OCOR_PLAN_RUN_STATE.json`, quel settle è il commit successivo e non cambia i byte del validatore. Se riscrive altro, ci si ferma. Gli undici record si misurano sull'HEAD congelato dopo allowlist e settle. Il commit di esecuzione è quell'HEAD. Si rimisura ogni hash di input. I manifest ricevono solo voci nuove in append. I record superseduti restano byte-identici. I comandi pytest sono quelli già registrati nel record superseduto di ciascun task, con skip zero e log nuovi. `supersedes` è una sola stringa, come oggi. Ogni `cycle12d` supersede il `record_id` letto dal `cycle12c` dello stesso task. Ogni record orfano supersede, rispettivamente, `OCOR-DEV-0005-requalified-rem0063-d215c7d2c1dc`, `OCOR-DEV-0050-requalified-rem0063-d215c7d2c1dc` e `OCOR-DEV-0082-requalified-rem0063-d215c7d2c1dc`. `created_at` del `cycle12d` è strettamente successivo a quello del record orfano dello stesso task, così `select_most_recent` sceglie il `cycle12d`. Non si modifica `select_most_recent`. Se la scelta non è il `cycle12d`, ci si ferma e si apre una sola richiesta.

   Prima di `verify_request.json` si esegue `scripts/check_execution_commit_inputs.py` su ogni record di evidenza aggiunto dal branch rispetto al merge-base con `origin/main`. Ciascuno passa sull'HEAD finale, oppure il suo `record_id` è superseduto da un record distinto dello stesso `task_id` che passa. Comando, HEAD e sha256 dello stdout stanno nel record dell'unità. `scripts/validate_evidence_input_drift.py` non si modifica.

   Nello stesso ciclo, e solo nel record JSON e nel README dell'unità, si chiude VF-003: `commit_role`, `environment.stack` e `environment.branch_note` allineati al commit di misura `aaf98a282f4c6787f1c4753ea86199f2808f7a72` e alla campagna `698b944a1de4-1795114196` come esecuzione storica, non come PASS dell'HEAD finale; la sezione `Cycle 12 record` allineata all'HEAD di codice `da754e862a2c2fba621cf5d4534fcc5396299b6a`; disposition di `REM-0063-CYCLE12-UNIT-RECORD-INPUTS`; classificazione dei tre orfani come teste di biforcazione supersedute dai record orfani nuovi. Quel commit non cambia il validatore, `OCOR_PLAN_RUN_STATE.json` né `codegen.py`. Il registro di conformità non riceve la voce.

   Poi una sola `prereview_request.json`. L'implementatore non avvia il revisore. Non si avvia la campagna nella stessa iterazione della richiesta di revisione. Con finding bloccanti dentro il perimetro di questa opzione si corregge e si chiede una sola nuova revisione. Con un finding fuori perimetro ci si ferma e si apre una sola richiesta. Dopo la revisione senza bloccanti fuori perimetro: `PRE-CAMPAIGN-GATE`, la campagna a quattro corsie e il controllo distinto sull'HEAD finale, poi `verify_request.json`. Le campagne già citate non si rilanciano. Tetti, partizioni, gate e harness restano quelli vigenti. Il verifier resta quello di `VERIFIER-CLAUDE-REM0063 (2026-11-16)`. Nell'evidenza si dichiarano gli implementatori già elencati e l'implementatore di questo ciclo.

   Accettazione: il diff dell'allowlist rispetto a `f06c2ebc0631d0ad4766d9e8109154fa030f9399501c0c8b79ff8bf37ad831a0` è esattamente le ventidue stringhe; ogni cella della dimensione nuova concorda con le librerie; i nodi solo in `$defs` o `definitions` restano esenti; `select_most_recent` sceglie gli otto `cycle12d`; `check_execution_commit_inputs.py` passa su ogni record aggiunto dal branch o sul suo successore distinto; nessun file di produzione fuori da `mcp_profile.py` cambia; nessun record già pubblicato è riscritto; nessun test, gate, soglia o claim è indebolito.

   Costo: due iterazioni di implementazione dopo la decisione, più la verifica indipendente. La prima è RED, GREEN, allowlist, settle, undici record, riallineamento e `prereview_request.json`. La seconda, dopo la revisione, è il gate, la campagna, il controllo distinto e la richiesta di verifica. Se il verdetto è ancora `NO_GO`, non c'è un ciclo 14 automatico: una sola richiesta nuova.

2. **Solo la divergenza fail-closed e VF-003.** Si applica la parte di codice, test, docstring, README e riallineamento di VF-003 dell'opzione 1. Non si estende l'allowlist e non si scrivono record `cycle12d` né record orfani. I tre `record_id` orfani restano FAIL e sono dichiarati teste di biforcazione non correnti, perché `select_most_recent` sceglie i `cycle12c`. VF-002 resta aperto. Costo: le stesse due iterazioni senza i record. La classe di evidenza per `record_id` resta incompleta: il controllo che il verdetto ha rieseguito può riproporre VF-002. Non raccomandata.

3. **Nessun file cambia.** L'HEAD resta `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19`. L'esenzione permissiva resta. VF-001, VF-002 e VF-003 restano aperti. `OCOR-DEV-REM-0063` resta bloccato su questa richiesta. Non c'è un ciclo 13. Costo: zero. Il `NO_GO` resta senza chiusura. Non raccomandata.

## Raccomandazione

Opzione 1. Chiude la divergenza fra il profilo e le librerie fissate, che è il finding bloccante, e chiude anche VF-002 e VF-003 senza lasciare teste FAIL. L'opzione 2 lascia tre `record_id` in FAIL e la verifica successiva può riproporre VF-002. L'opzione 3 lascia il profilo più permissivo delle librerie su nodi che il validatore applica. Nessuna opzione di questa richiesta è applicata da chi la apre.

## Impatto

Task bloccato da questa richiesta: `OCOR-DEV-REM-0063`. Gli altri task non sono bloccati da questa richiesta. `OCOR-DEV-REM-0066` resta bloccato da `REM-0066-CANONICAL-R1-HUMAN-GATE`. `OCOR-DEV-REM-0065` resta all'HEAD `583ea0024f18ebe0f63f4c5eaa8da8bc9a246f6c`. La PR #640, branch `nepryoon-patch-1`, non si tocca.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist del validatore del piano per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione.

## Disposition del Product Owner — 2026-11-20

`REM-0063-CYCLE12C-NO-GO (2026-11-20)` adotta l'opzione 1. Decisa per conto del PO, modello `claude-fable-5-2`, effort `max`. Preambolo sha256 `4100cbd8afb0a93b72c755bc0235aa03da040e6e07c79aeb0120266b5d6ea02b`.

L'attuazione si è fermata sulla clausola della stessa opzione: un test esistente che fallisce per una causa diversa dall'esenzione rimossa obbliga a fermarsi e ad aprire una sola richiesta. La regola strutturale, provata e poi annullata senza commit sul candidato `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19`, fa fallire 192 test in `test_cycle8_depth_and_order_differential_matches_the_library` (160), `test_cycle8_anchor_ref_follows_the_referencing_crawl` (16) e `test_cycle10_preserves_existing_anchor_lookup_context` (16): le librerie accettano, il profilo rifiuta. Nessun commit di codice. Nessuna allowlist, nessun record, nessuna `prereview_request.json`.

La sola richiesta nuova è `REM-0063-CYCLE13-STATIC-LIBRARY-DIVERGENCE`, commit `7ca292c4adb953bd2772d7852c390f7a66b27e2c`, sha256 `6d954208386ca4253e794ab4b68fae93f3a35530004b4fe0f520970700f0970b`, branch `governed/decision-request-rem0063-cycle13-static-library-divergence`, bozza PR #711, non si integra. Nessuna sua opzione è applicata.
