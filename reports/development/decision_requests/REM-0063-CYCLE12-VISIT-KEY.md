# REM-0063-CYCLE12-VISIT-KEY

Stato: `OPEN_PO_DECISION_REQUIRED`.
Livello: operativo. Unità: `OCOR-DEV-REM-0063`.
Decisione in corso: `REM-0063-CYCLE12-JSON-DEPTH (2026-11-19)`, opzione 1, commit della richiesta `ac6b59e999b79be45dcb754d475914614fb6d662`, sha256 `5746866b2088094cc9b7b6eabf6d5e8c26c76164bee7518b6c974157054bda53`. Disposition `8a2c7f6a2e3022090070af1a9afa86f554762541`, sha256 `3df2689c32d5d01a118dfb6da2bef794aa01d8f515acd724a6fe8fc6d05018e3`, sul branch `governed/decision-request-rem0063-cycle12-json-depth`.
RED del confronto diretto: `bc6af772c09eabad698e4ac97fec425556a4466f` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`, parent `480f70240a21019b539ab4b1b847e7dd5d1af833`.
Branch di produzione: `governed/ocor-dev-rem-0063-mcp-profile`, fermo a `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.

## Contesto e perimetro

L'opzione 1 di `REM-0063-CYCLE12-JSON-DEPTH (2026-11-19)` è adottata. Il RED del confronto diretto è pubblicato. Il codice del grafo non è pubblicato. Fermarlo è il punto 2 della decisione: se l'attuazione richiede di andare oltre quanto l'opzione descrive, ci si ferma e si apre una decision request. Questa è quell'unica richiesta. Finché è aperta il sorgente del profilo e del generatore non si pubblica, il candidato non si integra e non si sigilla. Non c'è un ciclo 13.

Il conflitto è interno all'opzione 1. La frase sul secondo contatore chiede due cose insieme: in `_resolve_graph` non resta un conteggio di profondità proprio, e la chiave di visita è `(nodo, base)` senza identità del registro. La stessa opzione dice di non indebolire le celle già committate. Attuare la chiave senza identità del registro fa passare due celle del ciclo 8 che il codice committato rifiuta. Lasciare l'identità del registro attua il conteggio unico misurato alle catene 26–28 e non attua la frase letterale sulla chiave. Nessuna delle due letture si può pubblicare senza scegliere quale frase prevale.

`json_bounds` resta com'è. I tetti 4096 e 32 restano. I test del ciclo 10 non cambiano. Le celle pubbliche alle profondità di riferimento 31 e 32 restano un rifiuto di `json_bounds`. La profondità 33 resta un rifiuto di entrambe le funzioni. La catena 23 resta l'accettazione pubblica più profonda di questa famiglia. VF-008 non si corregge. Le campagne diagnostiche non si rilanciano. `inputs/` non si tocca. I record sigillati non si riscrivono. Le opzioni 2 e 3 di `REM-0063-CYCLE12-JSON-DEPTH` non sono applicate. La patch non committata `ac3a5f9e3032e62895f31ee4e76d6359b2d319a6a1021227f6083b2ccafc773c` non si applica.

Implementatori già dichiarati dell'unità: Grok Build `grok-4.7` (xAI) per il ciclo originale, le riparazioni 1–6, il completamento del ciclo 8, il ciclo 9, il codice e il candidato del ciclo 10, il ciclo 11, il RED del confronto diretto e questo arresto; Codex CLI `deepseek-flash` e `deepseek-v4-pro` (DeepSeek) per i cicli 7 e 8; Codex `gpt-6.1-sol` (OpenAI) per la fase A del ciclo 10. Verifier del ciclo 11: Claude Code `claude-opus-5-5` (Anthropic), effort `max`. Revisore preventivo del ciclo 11: Cursor `cursor-grok-4.6-xhigh` (xAI), riserva. Nessun implementatore Anthropic.

## Prove

Il confronto diretto è il commit `bc6af772c09eabad698e4ac97fec425556a4466f`. Il file cambiato è solo `ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`. Pytest `-k cycle12_vf002` su quel commit, con il sorgente ancora al RED: 6 failed, 22 passed, 42141 deselected, 1,75 s. I 6 fallimenti sono le ancore delle catene 26, 27 e 28 in `test_cycle12_vf002_schema_graph_matches_the_shared_bound`: `assert_reference_path_bound` accetta e `_resolve_graph` rifiuta. I puntatori delle stesse catene passano. Le profondità 31, 32 e 33 restano un rifiuto pubblico `exceeds the revision bounds`. La catena 23, profondità di riferimento 27, resta accettata in pubblico.

Sul tree di lavoro, poi ripristinato con `git checkout --` di `mcp_profile.py` e `codegen.py`, togliere solo i due controlli `depth > MAX_SCHEMA_DEPTH` dentro `_resolve_graph` e lasciare la chiave di visita `(nodo, base, identità del registro)` rende verdi il confronto diretto e `test_cycle8_pointer_and_anchor_paths_are_each_resolved`: 16 passed, 42153 deselected, 1,57 s. La causa misurata del rifiuto dell'ancora alle catene 26–28 è quel conteggio proprio, non l'identità del registro.

Togliere anche l'identità del registro, come la frase dell'opzione 1 chiede, sul file di test dell'unità: 2 failed, 42167 passed, 813,98 s. I due fallimenti sono solo `test_cycle8_pointer_and_anchor_paths_are_each_resolved[defs_first-b_first]` e `test_cycle8_pointer_and_anchor_paths_are_each_resolved[props_first-b_first]`, riga 4063, `Failed: DID NOT RAISE McpProfileError`. Lo stesso nodo è raggiunto dal puntatore `#/$defs/h` e dall'ancora `#hold`, con la stessa base `urn:ocor:embedded-tool:0:inputSchema` e due registri. La chiave `(nodo, base)` fa vincere il primo contesto: con `b` prima di `a` il registro dell'ancora entra per primo e il puntatore non viene più rifiutato. I casi `a_first` rifiutano ancora. Un filtro che non include quel test, `-k "cycle12 or cycle10_final_depth or cycle10_final_node or cycle10_depth_growth"`, sullo stesso tree ha dato 199 passed, 41970 deselected, 3,81 s: non è una prova che la chiave senza registro lasci verdi le celle del ciclo 8. Quel sorgente non è un commit. Il branch di campagna pubblicato è pulito su `bc6af772c09eabad698e4ac97fec425556a4466f`. Il branch di produzione resta `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.

VF-001 e VF-003 non sono pubblicati. VF-008 non è stato toccato. Le campagne diagnostiche `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` non sono state rilanciate.

## Quesito

Come si toglie il secondo contatore quando la chiave di visita `(nodo, base)` senza identità del registro rende verdi due celle del ciclo 8 che il codice committato rifiuta, e l'opzione 1 adottata vieta di indebolire le celle già committate?

## Opzioni

1. **Si toglie solo il conteggio proprio di profondità e la chiave di visita tiene l'identità del registro.** Raccomandata. In `_resolve_graph` non restano i due controlli `depth > MAX_SCHEMA_DEPTH`. La chiave di visita resta `(nodo, base, identità del registro)`. La frase letterale «chiave `(nodo, base)` senza identità del registro» non si applica. Il confronto diretto già committato alle catene 26, 27 e 28, ancora e puntatore, diventa lo stesso esito di `assert_reference_path_bound` senza modificare quel test. `test_cycle8_pointer_and_anchor_paths_are_each_resolved` resta com'è committato e resta un rifiuto in tutti e quattro i casi. Il resto dell'opzione 1 di `REM-0063-CYCLE12-JSON-DEPTH (2026-11-19)` resta: `json_bounds` invariato, tetti 4096 e 32, test del ciclo 10 invariati, profondità di riferimento 31 e 32 rifiutate in pubblico da `json_bounds`, profondità 33 rifiutata da entrambe, catena 23 accettata in pubblico, VF-001 e VF-003 come quella opzione già descrive, sugli stessi file. Nessuna cella già committata si indebolisce.

   File: `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`, la funzione `_mcp` di `codegen.py` e gli helper che le servono, `ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`. Nessun altro file. Nessuna dipendenza nuova. Il RED `bc6af772c09eabad698e4ac97fec425556a4466f` non si riscrive. Il branch di produzione resta fermo. Poi si riprende l'opzione 1 di `REM-0063-CYCLE11-NO-GO` dal passo 6, nell'iterazione già prevista per il record. Non si applica la patch non committata. Non si rilanciano le tre campagne diagnostiche. VF-008 non si corregge.

   Costo: si completa la prima delle tre iterazioni già contate da `REM-0063-CYCLE12-JSON-DEPTH`, poi il passo 6, poi revisione preventiva, gate, campagna, controllo distinto e richiesta di verifica. Un `NO_GO` successivo non apre un ciclo 13.

2. **La chiave di visita diventa `(nodo, base)` e le due celle `b_first` del ciclo 8 si aggiornano all'accettazione.** Si attua la frase letterale dell'opzione 1. I casi `defs_first-b_first` e `props_first-b_first` di `test_cycle8_pointer_and_anchor_paths_are_each_resolved` non chiedono più `McpProfileError`. L'ordine dei membri cambia l'esito: con l'ancora prima del puntatore il documento è accettato. È l'indebolimento di una cella già committata che l'opzione 1 vieta. Il confronto diretto delle catene 26–28 diventa verde. `json_bounds` e i test del ciclo 10 restano. File: gli stessi dell'opzione 1. Costo: le stesse tre iterazioni, con il test del ciclo 8 cambiato dentro il GREEN. Non raccomandata.

3. **La chiave di visita è `(nodo, base)` e ogni registro che raggiunge il nodo viene comunque valutato.** Il nodo non viene rientrato per il conteggio, ma il rifiuto del registro del puntatore resta anche se l'ancora è entrata prima. Le quattro celle del ciclo 8 restano un rifiuto senza modificarne il testo. Il confronto diretto delle catene 26–28 diventa verde. Questo comportamento non è descritto dall'opzione 1 adottata: è un'estensione. File: gli stessi dell'opzione 1, senza cambiare le celle del ciclo 8. Costo: le stesse tre iterazioni, con una semantica di visita che l'opzione adottata non nomina. Non raccomandata.

## Raccomandazione

Opzione 1. La misura dice che il rifiuto dell'ancora alle catene 26–28 è il conteggio proprio di `_resolve_graph`. Toglierlo, e tenere l'identità del registro, allinea il grafo a `assert_reference_path_bound` e lascia verde la cella del ciclo 8. L'opzione 2 attua la frase sulla chiave e per farlo accetta due documenti che la cella committata rifiuta. L'opzione 3 tiene il rifiuto del ciclo 8 con una valutazione per registro che l'opzione adottata non descrive. Nessuna opzione di questa richiesta è applicata da chi la apre.

## Impatto

Task bloccato da questa richiesta: `OCOR-DEV-REM-0063`. Gli altri task non sono bloccati da questa richiesta. `OCOR-DEV-REM-0066` resta bloccato da `REM-0066-CANONICAL-R1-HUMAN-GATE`. `OCOR-DEV-REM-0065` resta all'HEAD `583ea0024f18ebe0f63f4c5eaa8da8bc9a246f6c`. `AGENTIC-RISK-MAP-PARTIAL-GAPS` non blocca alcun task.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist del validatore del piano per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione.
