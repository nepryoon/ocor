# REM-0063-CYCLE10-NESTED-RESOURCE-RESOLUTION

Stato: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`.
Livello: `NORMATIVE`. Unità: `OCOR-DEV-REM-0063`, ciclo 10.
Branch di produzione: `governed/ocor-dev-rem-0063-mcp-profile`.
Base di produzione del ciclo: `f485dc964e47bde83842ecd5ba2627d8342612f9`.

## Contesto e perimetro

`REM-0063-CALCOLO-UNICO (2026-11-17)` punto 3 chiede che la risoluzione di una
risorsa, della sua base e del bersaglio di un riferimento venga da
`referencing` 0.37.0 applicata allo schema autonomo così com'è, senza
riscrivere `$id`, riferimenti o altri byte, e senza un secondo risolutore
scritto a mano. Il punto 5 ammette, sui test scritti prima del ciclo 10,
soltanto i riallineamenti elencati nelle disposizioni già decise.
`REM-0063-CICLO-10-CONTRATTO (2026-11-16)` punto 6 ferma la riparazione quando
un test esistente contraddice l'esito delle librerie fissate.

Il profilo, in `enter_subschema` e `_resolver_for_subresource`, registra a
mano la risorsa annidata con `registry.with_resource` quando
`in_subresource` cambia la base. `_lookup_reference` ritenta un
`PointerToNowhere` togliendo quell'URI con `registry.remove`. Con questa
registrazione il profilo accetta schemi che le librerie fissate, applicate
allo schema da solo, non risolvono. Togliere registrazione e ritento rende
rossi 39 casi scritti prima del ciclo 10, che non sono fra i riallineamenti
autorizzati. Questa iterazione non sceglie una lettura e non modifica quei
39 casi.

La campagna di qualifica del ciclo 10 e la rimozione della registrazione a
mano dipendono da questa richiesta. Il resto dell'unità non ne dipende: la
chiusura sul proprietario della libreria, il `TypeError` del crawl e il
limite unico di profondità dei riferimenti sono già sul branch e non
anticipano un'opzione.

Il generatore scrive ora la chiusura su `lookup("#").contents` non pinnato,
oppure sul nodo di confine quando quella lookup non recupera una base
relativa, e legge i riferimenti anche dal nodo di confine. La domanda su chi
sia il proprietario della chiusura, generatore contro profilo, non resta
aperta: con le `$defs` sul proprietario della libreria i due percorsi
concordano sulle sonde di ricongiunzione e sulla regressione generata
descritta sotto.

## Prove

Ambiente: Python 3.12.11, `referencing` 0.37.0, `jsonschema` 4.26.0, dal
lock del progetto. Sonde in memoria, senza scrivere nel repository, sul
codice del branch prima del commit di questa richiesta. Il profilo è
`validate_mcp_descriptor` con la fixture ufficiale `2026-07-28`. La libreria
è `Draft202012Validator` sullo schema da solo.

E1. Schema dello strumento:

```json
{"type":"object","properties":{"holder":{"$id":"https://f.invalid/child.json","type":"object","$defs":{"shared":{"type":"integer"}},"properties":{"probe":{"$ref":"#/$defs/shared"},"inner":{"$id":"","type":"object"}}}}}
```

Il profilo accetta, su `inputSchema`. `Draft202012Validator.check_schema`
accetta lo schema. `iter_errors` sull'istanza `{"holder":{"probe":1}}`
solleva `PointerToNowhere: '/$defs/shared' does not exist within
{'$id': '', 'type': 'object'}`.

E2. Schema dello strumento:

```json
{"$id":"rel/root.json","type":"object","properties":{"holder":{"$id":"child.json","type":"object","properties":{"probe":{"$ref":"#"}}}}}
```

Il profilo accetta. `iter_errors` sull'istanza `{"holder":{"probe":{}}}`
solleva `Unresolvable: #`.

E3. Come E1, con il nodo interno `{"$id":"#","type":"object","$defs":{"shared":{"type":"string"}}}`.
Il profilo accetta e il controllo di schema riceve il bersaglio del holder,
`{"type":"integer"}`. La libreria valida `probe` contro lo `shared` interno
di tipo stringa: l'istanza `{"holder":{"probe":1}}` produce un errore di
tipo, l'istanza `{"holder":{"probe":"text"}}` non ne produce. Accettazione
uguale non basta: l'oggetto controllato è diverso.

I 39 casi che diventerebbero rossi senza la registrazione sono tutti in
`ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`:

- `test_cycle6_noop_id_empty_fragment_lands_on_the_parent_resource`, 3 casi,
  posizione `$defs`, identificatori `#`, `https://verifier.invalid/root.json`
  e `./root.json`.
- `test_cycle6_ref_targets_match_referencing_on_the_effective_resource`,
  36 casi: posizioni `$defs` e `nested`; gli stessi tre identificatori;
  riferimenti `#`, `#/$defs/part` e `#/$defs/p%61rt`; con e senza `sibling`.

Il loro oracolo di ciclo 6 costruisce un registro sulla risorsa che il test
chiama parent. Non è l'applicazione della libreria al solo schema dello
strumento nei casi E1 ed E2.

Regressione sul branch, non una campagna: il filtro sui prodotti generati
`cycle10_generated_two_level`, `cycle10_generated_relative`,
`cycle10_generated_cartesian`, `cycle10_delivered_cartesian`, sui test
percent-encoded del ciclo 4, sulla collisione del ciclo 8 e su
`cycle10_null_applicator` ha dato 11548 passati, 30380 deselezionati,
0 falliti, exit 0, 662.83 s. SHA256 del log grezzo
`84dc47037d3f24df44e1234a044a3a78547e395b5d7cffa3b488885324f4c662`.
La matrice resta di 40180 celle. Questa esecuzione non la riqualifica.

### Quesito A — risoluzione della risorsa annidata

Chi decide il bersaglio di un riferimento dentro una risorsa annidata: la
libreria sullo schema dello strumento da solo, oppure la risorsa annidata
come radice dei propri frammenti, come si aspettano i 39 casi del ciclo 6?

### Opzioni del quesito A

A1. **L'oracolo è la libreria sullo schema da solo.** Il bersaglio è quello che `referencing` 0.37.0 e `Draft202012Validator` ottengono sullo schema dello strumento, senza registrazione a mano e senza ritento dopo `PointerToNowhere`. I 39 casi del ciclo 6 si riallineano solo con l'elenco esplicito di questa opzione: stessi nomi, stessi ingressi, aspettativa nuova uguale alla libreria sullo schema da solo. Si tolgono `registry.with_resource` in `_resolver_for_subresource` e il ritento in `_lookup_past_registered_boundary`. Nessuna cella della matrice si toglie. La dimensione del quesito C, se si sceglie C1, è l'estensione che rende visibile questa lettura.

A2. **La risorsa annidata è la radice dei propri frammenti.** Si conserva l'aspettativa del ciclo 6: un `$id` annidato, anche vuoto, `#` o relativo, è la radice dei frammenti che partono da quel nodo. La registrazione e il ritento restano. Questa opzione supera, per questi schemi, la frase «schema così com'è» di `REM-0063-CALCOLO-UNICO (2026-11-17)` punto 3 e accetta che le librerie fissate non risolvano E1 ed E2. I 39 casi non si riallineano.

### Quesito B — identità del bersaglio quando l'accettazione coincide

In E3 profilo e libreria accettano lo schema, ma il profilo controlla
`{"type":"integer"}` del holder e la libreria valida contro
`{"type":"string"}` del nodo interno. L'accettazione uguale basta, o
l'oggetto controllato deve essere quello che la libreria restituisce?

### Opzioni del quesito B

B1. **L'oggetto controllato è quello della libreria.** Se i due oggetti differiscono, il profilo deve controllare l'oggetto che la libreria restituisce per quello spelling, non un altro oggetto che sarebbe comunque uno schema. L'accettazione uguale non è un accordo.

B2. **Basta che entrambi accettino.** Il profilo può continuare a controllare il bersaglio del holder quando anche la libreria accetta lo schema, e il record dichiara che l'oggetto può differire. E3 resta accettato con il bersaglio intero.

### Quesito C — dimensione «solo discesa statica»

La matrice attuale raggiunge ogni nodo di prova anche con un riferimento.
Non contiene un nodo raggiunto soltanto per discesa statica dentro una
risorsa annidata. Va aggiunta questa dimensione, senza togliere celle?

### Opzioni del quesito C

C1. **Aggiungere la dimensione.** Si estende la matrice con nodi raggiunti soltanto per discesa statica dentro risorse annidate, con e senza un discendente che si ricongiunge allo stesso URI, e con una radice relativa. Le 40180 celle restano. L'oracolo dei casi nuovi sono le librerie fissate sullo schema originale, mai il codice in prova.

C2. **Non aggiungere la dimensione.** La matrice resta di 40180 celle. Nessuna cella si toglie e nessuna si aggiunge per questa classe.

## Raccomandazione

Opzioni A1, B1 e C1. A1 applica la libreria allo schema da solo e riallinea
i 39 casi con un elenco esplicito, invece di lasciare un secondo
risolutore. B1 distingue l'oggetto controllato dall'accettazione, che in E3
non basta. C1 rende visibile la classe senza ridurre la matrice. Nessuna
di queste opzioni è applicata in questa richiesta.

## Ambito bloccato e ripresa

Bloccati da questa richiesta: la campagna di qualifica del ciclo 10 e la
rimozione della registrazione a mano e del ritento. Non è bloccata l'intera
unità. Non si apre un ciclo 11. Non si scelgono qui A2, B2 o C2.

File che una decisione può toccare, soltanto dopo la scelta: 
`ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`, la funzione `_mcp` e i
suoi helper in `ocor-runtime/src/ocor_runtime/c1/codegen.py`,
`ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py` limitatamente
all'elenco dei 39 casi se si sceglie A1, e il README e il record in
`reports/assurance/OCOR-DEV-REM-0063-RCCAD/`.

Nessun test è stato rimosso, saltato, deselezionato o reso meno severo.
Nessuna modifica a fixture fissata, record sigillati, gate, timer, tetto,
partizione, immagine, digest o `inputs/`. I limiti restano 4096 valori JSON
e profondità 32.
Claim invariati: E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED,
PoC e Production NO-GO.

## Controllo del formato

Le sei opzioni sono A1, A2, B1, B2, C1 e C2, ciascuna all'inizio della riga,
sotto la propria sezione `### Opzioni del quesito`. Nessuna opzione sta in
un blocco di codice. La raccomandazione scritta è A1, B1 e C1.

## Disposition

Decisa dal PO di persona il 2026-11-17. Quesito A, opzione A1; quesito B,
opzione B1; quesito C, opzione C1. A2, B2 e C2 non sono applicate.
Il commit di codice `7cc393a55b42e91af34e4cfe0f31beecd35e0fdb` sul branch
`governed/ocor-dev-rem-0063-mcp-profile` toglie la registrazione a mano e
il ritento dopo `PointerToNowhere`, riallinea i 39 casi nominati e aggiunge
le 24 celle di discesa statica. Il record è
`5d6bd2662fc8db619d057169f25962d9c76ce4e1`. L'allineamento delle annotazioni
a mypy 2.3.1, senza cambiare rami di esecuzione, è
`6c1d5c805fab9fff784db5ddfcd419c92790a597`. Il testo della richiesta sopra
questa sezione resta quello del commit
`99172353fc2ac6b2a56aadf54321339d6ea9a4a4`, sha256
`66e7e5b2a5dab5b21064fd118484687aa95c6bfab40bc8ee47db844406ddf729`.
