# REM-0063-CYCLE12-JSON-DEPTH

Status: `DECIDED_BY_PO`.
Livello: operativo. Unità: `OCOR-DEV-REM-0063`.
Decisione in corso: `REM-0063-CYCLE11-NO-GO (2026-11-18)`, opzione 1, commit `391ff177a5c0e25fbbdbe4840a0d4c14612ae03e`, sha256 `c8ae68e98a1455591761726be8f85575d857faa3a3a20ce6be866e383d89403f`.
RED del ciclo 12: `480f70240a21019b539ab4b1b847e7dd5d1af833` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`, parent `5defee7436120e9a5f51191113b5995467bacaf2`.
Branch di produzione: `governed/ocor-dev-rem-0063-mcp-profile`, fermo a `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.

## Contesto e perimetro

L'opzione 1 di `REM-0063-CYCLE11-NO-GO (2026-11-18)` è adottata. Il passo RED è pubblicato. Il GREEN di VF-001, VF-002 e VF-003 non è pubblicato: fermarlo è il punto dell'opzione che dice di aprire una sola richiesta se l'attuazione richiede un tetto o una cella che l'opzione non nomina. Questa è quell'unica richiesta. Finché è aperta il candidato non si modifica, non si integra e non si sigilla. Non c'è un ciclo 13.

Il conflitto è fra due limiti già esistenti, entrambi di profondità 32. `json_bounds` conta ogni valore JSON del descriptor, radice inclusa, e rifiuta se la profondità supera 32. `assert_reference_path_bound` conta la profondità del percorso di riferimento e accetta 31 e 32. L'opzione 1, al passo 3, chiede che l'esito pubblico sia quello della funzione condivisa e delle librerie a profondità 31, 32 e 33, e che il caso che il profilo rifiuta mentre la funzione condivisa accetta diventi accettato. Le celle già committate costruiscono quel caso con una catena di `not` dentro il bersaglio. Su quelle celle la profondità JSON del documento è 36 o 37, quindi `validate_mcp_descriptor` rifiuta in `json_bounds` prima di `_resolve_graph`. Accettarle significa far passare un documento che il limite JSON rifiuta. Riscriverle verso una profondità che il limite JSON accetta non raggiunge le profondità 31 e 32 che l'opzione nomina.

`REM-0063-CALCOLO-UNICO (2026-11-17)` punto 7 e l'opzione 1 lasciano invariati i limiti di 4096 valori e di profondità 32. I test del ciclo 10 fissano la profondità JSON del descriptor: 32 accettato, 33 rifiutato, anche quando la crescita passa da `properties` e `not`. Nessuna delle due letture si può attuare senza scegliere quale dei due testi prevale.

Implementatori già dichiarati dell'unità: Grok Build `grok-4.7` (xAI) per il ciclo originale, le riparazioni 1–6, il completamento del ciclo 8, il ciclo 9, il codice e il candidato del ciclo 10, il ciclo 11 e questo GREEN non pubblicato; Codex CLI `deepseek-flash` e `deepseek-v4-pro` (DeepSeek) per i cicli 7 e 8; Codex `gpt-6.1-sol` (OpenAI) per la fase A del ciclo 10. Verifier del ciclo 11: Claude Code `claude-opus-5-5` (Anthropic), effort `max`. Revisore preventivo del ciclo 11: Cursor `cursor-grok-4.6-xhigh` (xAI), riserva. Nessun implementatore Anthropic.

## Prove

Misure del 2026-11-18 sul commit `480f70240a21019b539ab4b1b847e7dd5d1af833`, Python del worktree `rem-0063`, librerie fissate. La catena N è `_cycle12_depth_schema`, `deep=4`. La profondità di riferimento attesa dal test è N+4. La profondità JSON è quella di `_cycle10_size`: la radice vale uno, le chiavi non contano.

| Catena | Profondità di riferimento | JSON dello schema | JSON del documento | `assert_reference_path_bound` | `json_bounds` sul documento | Profilo pubblico, codice committato | Profilo con `json_bounds` escluso, codice committato |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 23 | 27 | 29 | 32 | accetta | accetta | ancora e puntatore accettati | ancora e puntatore accettati |
| 24 | 28 | 30 | 33 | accetta | rifiuta | entrambi rifiutati | non misurato in questa riga |
| 26 | 30 | 32 | 35 | accetta | rifiuta | entrambi rifiutati | ancora rifiutata, puntatore accettato |
| 27 | 31 | 33 | 36 | accetta | rifiuta | entrambi rifiutati | ancora rifiutata, puntatore accettato |
| 28 | 32 | 34 | 37 | accetta | rifiuta | entrambi rifiutati | ancora rifiutata, puntatore accettato |
| 29 | 33 | 35 | 38 | rifiuta | rifiuta | entrambi rifiutati | entrambi rifiutati |

Il percorso JSON più profondo della catena 27 è `$.$defs.a.properties.c` seguito da 27 volte `.not` e da `.type`. Il documento aggiunge `tools`, l'elemento e il campo: profondità 36. Lo schema da solo è già a profondità 33, sopra 32. I nodi restano 46–48, sotto 4096.

Sul codice committato la divergenza ancora/puntatore non compare sul percorso pubblico. Compare solo se si esclude `json_bounds`: dalla catena 26 l'ancora è rifiutata da `_resolve_graph` e il puntatore è accettato, mentre la funzione condivisa accetta entrambi. È il secondo contatore, la chiave di visita che include l'identità del registro. Quella divergenza inizia a profondità JSON 35 del documento. `json_bounds` rifiuta già dalla profondità 33. Non c'è una catena di questa famiglia in cui il secondo contatore sia visibile e il documento stia dentro il limite JSON.

Una catena di `$ref` fra definizioni sorelle non alza la profondità di riferimento: la visita per riferimento non rientra in un nodo già entrato, e le sorelle sono semi alla stessa profondità. Trenta salti restano accettati, con profondità JSON dello schema 8 e del documento 11. Non è un modo per portare la profondità di riferimento a 31 dentro il limite JSON.

Sul tree di lavoro, non committato e poi ripristinato, la chiave di visita è `(nodo, base)` senza identità del registro, i due conteggi propri di `_resolve_graph` sono tolti, la regola 4 usa i segmenti di `referencing` 0.37.0 e il generatore entra solo da `contained_subschemas` e `enter_subschema`. Pytest `-k cycle12` su quel tree: 8 failed, 155 passed, 41990 deselected, 2,02 s. Gli 8 fallimenti sono solo `test_cycle12_vf002_reference_path_depth_matches_the_shared_bound` per le profondità 31 e 32, ancora e puntatore, entrambi i campi, tutti a `mcp_profile.py:544`, da `json_bounds`. Log locale sha256 `9b198c8b97e5ea2785057fde1042e659a10f8395803c55ec66350385d9a75305`. Con `json_bounds` escluso, le stesse sei combinazioni di forma e profondità sullo `inputSchema` coincidono con la funzione condivisa, e gli 8 casi pubblici di accettazione passano. Quel diff non è un commit. Il branch è di nuovo pulito su `480f70240a21019b539ab4b1b847e7dd5d1af833`. La patch resta solo in `~/.ocor-codex/salvage/20261118T225234Z/cycle12-green-uncommitted.patch`, sha256 `ac3a5f9e3032e62895f31ee4e76d6359b2d319a6a1021227f6083b2ccafc773c`. Non è un artefatto del repository e non va applicata come patch: il testo di questa richiesta basta.

VF-001 e VF-003, sullo stesso tree non committato, erano fra i 155 passaggi. Non sono stati pubblicati. `json_bounds` non è stato modificato. I test del ciclo 10 non sono stati modificati. I test del ciclo 12 non sono stati indeboliti. Le opzioni 2 e 3 di `REM-0063-CYCLE11-NO-GO` non sono applicate. Le campagne diagnostiche `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` non sono state rilanciate. VF-008 non è stato toccato.

## Quesito

Come si chiude il passo 3 dell'opzione 1 quando la cella che deve diventare accettata ha profondità JSON 36 o 37, sopra il limite 32 che la stessa opzione lascia invariato?

## Opzioni

1. **Si tengono i due limiti e si correggono solo le celle che il limite JSON non può accettare.** Raccomandata. Non si modifica `json_bounds`. Restano 4096 valori e profondità JSON 32 sull'intero documento, compresi `default`, `examples` e la crescita `properties`/`not` dei test del ciclo 10. Quei test non cambiano. Il secondo contatore si toglie comunque: in `_resolve_graph` non resta un conteggio di profondità proprio, e la chiave di visita è `(nodo, base)` senza identità del registro, come il passo 3 già descrive. VF-001 e VF-003 si attuano come l'opzione 1 già descrive, sugli stessi file.

   Le celle committate alle profondità di riferimento 31 e 32 restano un rifiuto pubblico. `validate_mcp_descriptor` alza `McpProfileError` con `exceeds the revision bounds` perché `json_bounds` vede profondità 36 e 37. Il test continua a chiamare `assert_reference_path_bound` e a registrare che quella funzione accetta. Non chiede più che `_validate` accetti il documento. La profondità 33 resta un rifiuto di entrambe le funzioni. Si aggiunge un confronto diretto, sullo schema e non sul documento, fra `assert_reference_path_bound` e il grafo del profilo, per ancora e puntatore alle catene 26, 27 e 28: stesso esito. È il lucchetto del secondo contatore, che sul percorso pubblico è mascherato dal limite JSON. La catena 23, documento a profondità 32, resta l'accettazione pubblica più profonda di questa famiglia: ancora e puntatore accettati, profondità di riferimento 27. Non sostituisce le profondità 31 e 32, che il limite JSON rifiuta.

   File: `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`, la funzione `_mcp` di `codegen.py` e gli helper che le servono, `ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`. Nessun altro file. Nessuna dipendenza nuova. Il branch di produzione resta fermo. Poi si riprende l'opzione 1 dal passo 6, nell'iterazione già prevista per il record. Criteri: RED del confronto diretto prima del codice del grafo; le profondità 31 e 32 rifiutate in pubblico da `json_bounds`; la profondità 33 rifiutata da entrambe; i test del ciclo 10 di profondità e di nodi ancora verdi; VF-001 e VF-003 verdi senza indebolire le celle già committate.

   Resta incompleto, rispetto alla frase letterale del passo 3, il punto che il profilo accetti ciò che le librerie accettano alle profondità di riferimento 31 e 32. Quei documenti restano rifiutati dal limite JSON. Non resta incompleto il secondo contatore: la causa misurata alle catene 26–28 si toglie e si lucchetta sullo schema.

   Costo: tre iterazioni dopo questa decisione. La prima è il GREEN, con la correzione delle celle e il codice di VF-001, VF-002 e VF-003. La seconda è il passo 6, record e riqualifica. La terza è revisione preventiva, gate, campagna, controllo distinto e richiesta di verifica. Poi la verifica indipendente e uno state sync. Un `NO_GO` successivo non apre un ciclo 13.

2. **La profondità di riferimento diventa l'unico limite di profondità dello schema, e le celle 31 e 32 sono accettate.** `json_bounds` continua a contare i nodi, con tetto 4096, e la profondità JSON del descriptor fuori dallo schema e delle parole chiave di istanza `default`, `examples`, `enum` e `const`, con tetto 32. Non conta più l'annidamento degli applicator (`not`, `properties`, `allOf` e le altre parole chiave di schema) verso quel tetto. `assert_reference_path_bound` resta l'unico rifiuto di profondità su quell'annidamento, stesso messaggio, stesso confine 32 accettato e 33 rifiutato. I test `test_cycle10_final_depth_boundary` e `test_cycle10_final_node_boundary` restano. `test_cycle10_depth_growth_from_reachable_types` si riscrive sul percorso di riferimento: il caso 33 è una catena che la funzione condivisa rifiuta, non un documento a profondità JSON 33 costruito con `properties` e `not`. Le celle del ciclo 12 restano come sono committate e, insieme alla chiave di visita del punto precedente, diventano verdi. È la lettura che realizza per intero la tabella del passo 3.

   Questa opzione è più permissiva del limite attuale. La catena 24 ha profondità JSON del documento 33 e la funzione condivisa accetta: oggi il profilo la rifiuta, con questa opzione la accetterebbe. Le profondità 31 e 32 del ciclo 12, documenti a profondità 36 e 37, diventerebbero accettate. I numeri 32 e 4096 restano, ma la passeggiata che applica il 32 agli applicator cambia. L'opzione 1 di `REM-0063-CYCLE11-NO-GO` dice che quei tetti restano. Per questo non è la raccomandazione.

   File: `mcp_profile.py` (`json_bounds` o il punto in cui il profilo e il generatore lo chiamano), `codegen.py` per la stessa funzione condivisa, il test del ciclo 10 nominato sopra. I test del ciclo 12 non si indeboliscono. Costo: le stesse tre iterazioni, con la riscrittura del test del ciclo 10 dentro il GREEN. Rischio: ogni schema la cui profondità JSON supera 32 e la cui profondità di riferimento no cambia da rifiuto ad accettazione.

3. **Nessun codice.** Il branch resta a `480f70240a21019b539ab4b1b847e7dd5d1af833`. VF-001, VF-002 e VF-003 non si pubblicano. Il secondo contatore resta. Le celle 31 e 32 restano rosse. La classe non si chiude. Costo: zero iterazioni di codice. Non raccomandata.

## Raccomandazione

Opzione 1. Chiude la causa misurata, il secondo contatore, senza alzare ciò che `json_bounds` e i test del ciclo 10 rifiutano. L'opzione 2 realizza la tabella letterale del passo 3 e per farlo accetta documenti a profondità JSON 33, 36 e 37: è più permissiva del tetto che `REM-0063-CALCOLO-UNICO (2026-11-17)` e l'opzione adottata lasciano invariato. L'opzione 3 lascia il secondo contatore e la classe aperti. Non esiste una forma di questa famiglia che porti la profondità di riferimento a 31 o 32 e tenga il documento a profondità JSON non superiore a 32: lo schema della catena 27 è già a profondità 33.

## Impatto

Task bloccato da questa richiesta: `OCOR-DEV-REM-0063`. Gli altri task non sono bloccati da questa richiesta. `OCOR-DEV-REM-0066` resta bloccato da `REM-0066-CANONICAL-R1-HUMAN-GATE`. `OCOR-DEV-REM-0065` resta all'HEAD `583ea0024f18ebe0f63f4c5eaa8da8bc9a246f6c`. `AGENTIC-RISK-MAP-PARTIAL-GAPS` non blocca alcun task.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist del validatore del piano per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione.
## Disposition

Decisa per conto del PO, modello `claude-fable-5-2`, effort `max`. Decisione `REM-0063-CYCLE12-JSON-DEPTH (2026-11-19)`. Opzione 1 adottata. Le opzioni 2 e 3 non sono applicate.

Il RED del confronto diretto, prima di ogni modifica sotto `ocor-runtime/src/`, è il commit `bc6af772c09eabad698e4ac97fec425556a4466f` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`, parent `480f70240a21019b539ab4b1b847e7dd5d1af833`, senza rebase, reset o force-push. Il file cambiato è solo `ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`. Pytest `-k cycle12_vf002` su quel commit, con il sorgente ancora al RED: 6 failed, 22 passed, 42141 deselected, 1,75 s. I 6 fallimenti sono le ancore delle catene 26, 27 e 28 in `test_cycle12_vf002_schema_graph_matches_the_shared_bound`: `assert_reference_path_bound` accetta e `_resolve_graph` rifiuta. I puntatori delle stesse catene passano. Le profondità 31, 32 e 33 restano un rifiuto pubblico `exceeds the revision bounds`. La catena 23, profondità di riferimento 27, resta accettata in pubblico.

Il codice del grafo non è pubblicato. Tolti solo i due controlli `depth > MAX_SCHEMA_DEPTH` dentro `_resolve_graph`, e lasciata la chiave di visita `(nodo, base, identità del registro)`, il confronto diretto e `test_cycle8_pointer_and_anchor_paths_are_each_resolved` sono verdi: 16 passed. Tolta anche l'identità del registro, come la frase dell'opzione 1 chiede, i due casi `b_first` di quel test del ciclo 8 non alzano più `McpProfileError`: stesso nodo, stessa base, due registri, e vince il primo. Quel sorgente non è un commit. Il branch di campagna pubblicato resta `bc6af772c09eabad698e4ac97fec425556a4466f`. Il branch di produzione resta `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.

L'attuazione letterale della chiave senza registro rende rossa una cella già committata che l'opzione 1 dice di non indebolire. Non si sceglie al posto del PO. È aperta `REM-0063-CYCLE12-VISIT-KEY`. VF-001 e VF-003 non sono pubblicati. VF-008 non è stato toccato. Le campagne diagnostiche `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` non sono state rilanciate. `inputs/` non è stato modificato. Nessun record sigillato è stato riscritto.

Il testo sopra questa sezione, esclusa la riga di stato, resta quello del commit `ac6b59e999b79be45dcb754d475914614fb6d662`, sha256 `5746866b2088094cc9b7b6eabf6d5e8c26c76164bee7518b6c974157054bda53`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessun nuovo `DEC-*`.
