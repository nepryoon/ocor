# REM-0063-CYCLE13-EVALUATION-CONTEXTS

Stato `DECIDED_BY_PO`. Unità `OCOR-DEV-REM-0063`, ciclo 13. La richiesta riguarda il §2 di `REM-0063-RITORNO-AL-PROGETTO (2026-11-20)`, in applicazione di `NORMATIVE-QUESTIONS-EARLY-DR (2026-11-09)` e della sua integrazione sui vincoli del PO.

## Osservazioni e perimetro

Candidato `010f1f6faba36f37f985406e9c0c915d7990eeae`, branch `governed/ocor-dev-rem-0063-cycle10-campaign`. Nel contratto `reports/assurance/OCOR-DEV-REM-0063-RCCAD/README.md` alle righe 436–468 la discesa statica entra nella sottorisorsa. Alle righe 189–191 il contratto precedente lascia fuori dall'oracolo di istanza la ricorsione senza avanzamento. Entrambe le scelte incidono su quali strumenti si possono consegnare.

Misura locale su Python 3.12.11, `jsonschema` 4.26.0 e `referencing` 0.37.0. Per ciascuno dei due campi autonomi, lo schema originale è la radice di un `Registry` senza retrieval con la base B1 del campo. Dopo `Draft202012Validator.check_schema`, la misura consuma `iter_errors({"child": {}})` con il resolver del registro. Una normale violazione dei dati è distinta da un'eccezione nella valutazione dello schema. In parallelo si consegna lo stesso campo con `validate_mcp_descriptor` e la fixture fissata.

| Schema | Librerie | Consegna per entrambi i campi |
| --- | --- | --- |
| `{"type":"object","not":{"$id":"https://example.invalid/child","$ref":"#/$defs/x","$defs":{"x":{"type":"string"}}}}` | Lo schema è valido per il metaschema. La valutazione solleva `PointerToNowhere` sulla radice. | Accettato |
| Come sopra, con `"$defs":{"x":{"type":"string"}}` anche sulla radice | Valutazione completata, zero violazioni | Accettato |
| `{"type":"object","$ref":"#"}` | Il riferimento si risolve. La valutazione solleva `RecursionError`. | Accettato |
| `{"type":"object","properties":{"child":{"$ref":"#"}}}` | Valutazione completata, zero violazioni | Accettato |

SHA-256 dell'uscita degli otto casi `b6bc06d328c84ff3d3738f45986dbb3623da502934190f8a7e0ae52edb519eb3`. Il primo caso ha un contesto di valutazione aggiuntivo; il terzo ha tutti i riferimenti risolvibili. La frase «falliscono su un'istanza» e l'unica causa ammessa per la maggiore severità statica richiedono perciò due scelte distinte.

File interessati dalle opzioni: `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py` (contesti alle righe 450, 885, 922 e 954), `ocor-runtime/src/ocor_runtime/c1/codegen.py` (chiusura e controllo finale alle righe 748–859), `ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py` (matrice differenziale dal ciclo 10) e il contratto sopra indicato. L'impatto è limitato alla rendicontazione del ciclo e ai due percorsi pubblici del profilo MCP.

## Quesito A

Quali contesti fanno parte del controllo statico quando la valutazione delle librerie usa la base del genitore anche se lo schema figlio dichiara una nuova risorsa? Questo include i percorsi condizionali ed i rami che nessuna istanza del contratto può attivare.

### Opzioni del quesito A

A1. **Includere tutti i contesti del valutatore fissato.** Il calcolo condiviso aggiunge il contesto del genitore nei punti in cui il valutatore usa quel resolver senza entrare nel figlio. Le posizioni comprendono `not`, `if`, `contains`, i membri successivi di `oneOf`, `unevaluatedItems` e i passaggi di raccolta delle annotazioni in presenza di `unevaluatedProperties` o `unevaluatedItems` (combinatori, condizioni e `dependentSchemas`). L'inventario si ricava dalle funzioni del validatore e dei due raccoglitori di annotazioni nella versione fissata, distinguendo le forme effettivamente applicabili a proprietà e indici. Ogni percorso conserva la base che la libreria restituisce durante i lookup successivi. Una risoluzione fallita in uno di questi contesti assume lo stesso errore tipizzato di un riferimento irrisolto, anche quando nessuna istanza attiva quel ramo. Restano i confini per le definizioni non raggiunte del §2. Una condizione ordinaria sui dati non è un errore di risoluzione. Contratto, matrice sul prodotto di posizione, campo, origine, riferimento, base e presenza del bersaglio, quindi RED/GREEN e riqualifica. Per ogni posizione un'istanza entra nel ramo quando possibile; il controllo complementare usa l'enumeratore di test indipendente. Il consumatore rifiuta il primo esempio e accetta il secondo. Il produttore esegue lo stesso controllo sui campi finiti prima di restituire byte. Costo stimato: due iterazioni di implementazione e prove, oltre alla qualifica prevista.

A2. **Limitare il contratto alla discesa strutturale e ai percorsi di riferimento.** Restano i contesti espliciti del progetto pubblicato; il contratto circoscrive la garanzia di accordo ai lookup eseguiti in tali contesti, con una deroga esplicita al §2 per le modalità di valutazione del genitore. Il primo e il secondo esempio rimangono consegnabili e si registra un caso di compatibilità che dimostra la differenza sul primo. Il generatore può quindi emettere anche uno strumento che la libreria non riesce a valutare. Costo stimato: una iterazione per contratto, matrice e delimitazione della garanzia.

## Quesito B

Qual è la disposizione per la ricorsione sulla stessa istanza, distinta da un riferimento irrisolto e dalla ricorsione che scende a un elemento dei dati?

### Opzioni del quesito B

B1. **Rifiutare staticamente i cicli di valutazione senza avanzamento.** Una volta fissati i contesti con il quesito A, il controllo condiviso costruisce gli archi potenzialmente valutati dalla radice o da un riferimento raggiunto. Distingue gli archi sulla stessa istanza (tra cui riferimenti, combinatori, condizioni e `dependentSchemas`) da quelli che consumano un valore figlio o valutano il nome scalare di una proprietà. Per i nomi di proprietà si distingue il passaggio oggetto→stringa, che impedisce un ulteriore passaggio sullo stesso nome. Un ciclo di soli archi sulla stessa istanza rifiuta il campo con il nuovo messaggio tipizzato `MCP schema contains a non-progressing evaluation cycle` (`McpProfileError` in consegna, `C1Error/TYPE_ERROR` in generazione). Il contratto autorizza la maggiore severità anche per un ciclo potenziale in un ramo insoddisfacibile. Un ciclo che richiede una discesa nei dati e una definizione inutilizzata restano ammessi se altrimenti conformi. Il controllo termina sul grafo finito, senza eseguire istanze arbitrarie in produzione. L'oracolo prova un ciclo diretto, uno tra più riferimenti, un ramo opzionale con e senza attivazione, il controllo sotto definizione inutilizzata e una ricorsione che consuma dati. Per le celle preesistenti che accettano un ciclo ora vietato, il contratto autorizza soltanto il passaggio al rifiuto tipizzato, documentato riga per riga secondo il §5. Costo stimato: due iterazioni di implementazione e prove, integrate nella stessa qualifica di A.

B2. **Limitare la garanzia ai riferimenti e alla validità dello schema.** La frase «falliscono su un'istanza» del §2 copre un errore di risoluzione o schema durante la valutazione. La mancata terminazione dopo lookup riusciti resta fuori dalla garanzia statica. Entrambi gli esempi ricorsivi rimangono consegnabili; i test documentano distintamente il completamento del quarto caso e il limite osservato sul terzo. Il produttore rimane in grado di emettere un contratto ricorsivo che il consumatore non può valutare su certi dati. Costo stimato: una iterazione per delimitare il contratto e documentare i casi.

## Accettazione e raccomandazione

| Percorso dal produttore al consumatore | A1 / B1 | A2 / B2 |
| --- | --- | --- |
| Campo con bersaglio solo nel figlio, nella posizione `not` sopra | Errore tipizzato prima dell'emissione e in consegna diretta (A1) | Emissione e consegna, eccezione riproducibile del validatore su un dato (A2) |
| Stesso contratto con bersaglio in entrambe le risorse | Generazione e consegna riuscite (A1) | Generazione e consegna riuscite (A2) |
| Release con campo che si riferisce a sé sulla stessa istanza | Rendering e consegna rifiutati con l'errore del ciclo (B1) | Rendering e consegna ammessi, limite documentato (B2) |
| Schema ricorsivo di un oggetto con un oggetto figlio finito | Risoluzione e consegna riuscite (B1) | Risoluzione e consegna riuscite (B2) |

Raccomandazione A1 e B1. Entrambe eliminano una classe di contratti inutilizzabili sul validatore fissato e dichiarano la differenza ammessa per i rami statici. L'ordine proposto è contratto, prove differenziali, implementazione unica, revisione prima della campagna e verifica del candidato finale secondo il §7. Il quesito blocca i percorsi dipendenti e la qualifica del solo `OCOR-DEV-REM-0063`. Le correzioni indipendenti ai punti d'ingresso del §3 restano eseguibili.

## Disposition del 20 novembre 2026

La decisione `REM-0063-CYCLE13-EVALUATION-CONTEXTS (2026-11-20)` adotta A1 per il quesito A e B1 per il quesito B. Disposizione decisa per conto del PO, modello claude-fable-5-2, effort max, ai sensi di `DECISIONI-A-FABLE (2026-11-17)`. La richiesta decisa è al commit `8a38ac5efab5d95cb9800bbcf246d341c6315ede` con SHA-256 `a5903e9cc23f06b5cdb660f2b7a8bf574b034b696bf5f3d92a4915efd2166f40`.

A1 estende il controllo condiviso ai contesti di valutazione e di raccolta delle annotazioni del validatore fissato. B1 richiede il rifiuto dei cicli potenziali sulla stessa istanza. Perimetro, diagnostici, casi positivi e negativi e ordine dei lavori sono quelli delle due opzioni sopra. L'attuazione prosegue nel ciclo 13 di `OCOR-DEV-REM-0063`.
