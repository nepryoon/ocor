# REM-0063-CYCLE10-REMAINING-CONTRACT-QUESTIONS

Stato: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`.
Livello: `NORMATIVE`. Unità: `OCOR-DEV-REM-0063`, ciclo 10.
Base di produzione: `f485dc964e47bde83842ecd5ba2627d8342612f9`.
Contratto esaminato: `8ac669c8b1474d09363fbed3ef42aba16f8b19a8`,
branch `governed/ocor-dev-rem-0063-mcp-profile`.

## Contesto e perimetro

La seconda e ultima revisione del contratto ha individuato tre questioni
collegate alla promessa di risoluzione dello schema autonomo originale.
Le sonde seguenti le riproducono sulle librerie fissate, senza modificare
codice di produzione, test esistenti, fixture od oracoli.
`REM-0063-CICLO-10-CONTRATTO (2026-11-16)` punti 2 e 6 impone una decisione
quando un test esistente contraddice le librerie o le decisioni non fissano
un comportamento. `NORMATIVE-QUESTIONS-EARLY-DR (2026-11-09)` punto 4 richiede
un'unica richiesta per le questioni già ricavabili dagli stessi dati.

Non si chiede un ciclo ulteriore. Si chiedono i chiarimenti necessari alla
fase B del ciclo 10 già autorizzato. Il contratto e la matrice nuovi si
completano; il codice dipendente e la campagna completa restano sospesi.
Solo `OCOR-DEV-REM-0063` dipende direttamente da questa richiesta.

Restano separate e decise: A1+B1 di
`REM-0063-CYCLE10-ORACLE-CONFLICT (2026-11-16)`;
opzione 1 di `REM-0063-CYCLE10-INTERNAL-RESOURCE-URI (2026-11-16)`
(solo spelling che inizia con `#`); opzione 1 di
`REM-0063-PINNED-FIXTURE-DIFF-CHECK (2026-11-16)`
(byte fissati invariati, controllo `NOT_GREEN` con eccezione registrata).

## Prove e contratto comune

Ambiente misurato: Python 3.12.11, `referencing` 0.37.0,
`jsonschema` 4.26.0, dal lock del progetto. Sonde sull'head del contratto:
SHA256 dell'uscita JSON
`9b65ff2a0492f2f2ac5226f71409e57f80c5870fbf004a83272d1b9e2a2a5a55`.
Nessun esito della revisione è usato al posto delle sonde.

Il percorso dal produttore al consumatore è sempre
`compiler().build(request)` → `IrArtifactGenerator().render(release)` →
byte del descriptor → schema dello strumento da solo con
`referencing` e `Draft202012Validator` → `validate_mcp_descriptor`.
I rifiuti restano `C1Error` al produttore e `McpProfileError` al profilo;
nessun recupero esterno, ricaduta su altro strumento o modifica delle librerie.

### Quesito A: un caso percent-encoded fuori dall'elenco autorizzato

In `ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`, righe 699 e 716–722
all'head esaminato, il caso `encoded-slash` di
`test_percent_encoded_fragments_resolve_before_the_pointer` ha input
`#%2F$defs/a%20b` e attende accettazione. Questa funzione non compare
nell'elenco tassativo di A1 di `REM-0063-CYCLE10-ORACLE-CONFLICT`, che dice
anche «Ogni altro test esistente resta invariato».
La regola generale di A1 richiede però il rifiuto della slash iniziale
percent-encoded. Non è un nuovo difetto della libreria: è lo stesso spelling,
in un altro caso preesistente, individuato dalla seconda revisione.

Esempio completo consegnato al consumatore:

```json
{
  "x-ocor-mcp-protocol-revision": "2026-07-28",
  "tools": [{
    "name": "example",
    "inputSchema": {
      "type": "object",
      "$defs": {"a b": {"type": "string"}},
      "properties": {"name": {"$ref": "#%2F$defs/a%20b"}}
    }
  }]
}
```

Il profilo accetta; il lookup originale solleva `InvalidAnchor`;
`Draft202012Validator` su `{"name":"okay"}` solleva
`_WrappedReferencingError` con la stessa causa. Il positivo
`#/$defs/a%20b` è accettato da entrambe le librerie.
Riproduzione indipendente dal profilo:

```python
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012
schema = {"type": "object", "$defs": {"a b": {"type": "string"}},
          "properties": {"name": {"$ref": "#%2F$defs/a%20b"}}}
resolver = Registry().with_resource("urn:probe", DRAFT202012.create_resource(schema)).resolver("urn:probe")
resolver.lookup(schema["properties"]["name"]["$ref"])
Draft202012Validator(schema, _resolver=resolver).validate({"name": "okay"})
```

### Opzioni del quesito A

A1. **Estendere il riallineamento al solo caso omesso.** Autorizzare nel ciclo 10 la funzione `test_percent_encoded_fragments_resolve_before_the_pointer` e la sua docstring/commento: stessi nome, input, 19 casi e parametrizzazioni; il solo caso `encoded-slash` attende `McpProfileError`, gli altri 18 conservano le asserzioni. La tabella del record elenca aspettativa precedente e nuova. Nessun altro test esistente cambia oltre all'elenco già autorizzato. Costo aggiuntivo: incluso nell'iterazione di fase B già prevista.

A2. **Conservare un'eccezione esplicita per lo spelling omesso.** Conservare questa aspettativa e autorizzare esplicitamente l'accettazione di `#%2F$defs/a%20b` come eccezione alle librerie originali, con normalizzazione dichiarata di quello spelling nel contratto e nei soli test nuovi. L'eccezione si applica allo stesso input consegnato e generato; il consumatore deve conoscere la forma normalizzata. Questa opzione modifica la promessa di usare sempre lo schema originale, che A1 conserva. Costo stimato: due iterazioni di specifica e prova entro il ciclo autorizzato; nessuna modifica automatica della superficie di trasporto.

| Criterio | A1 | A2 |
| --- | --- | --- |
| Esempio sopra | Rifiuto tipizzato | Accettazione con eccezione dichiarata |
| `#/$defs/a%20b` | Positivo invariato | Positivo invariato |
| Test preesistente | Un caso su 19 riallineato | Tutti i 19 invariati |
| Schema dato alle librerie | Originale | Originale ordinariamente, forma normalizzata per l'eccezione |

### Quesito B: base della radice con `$id` vuoto o solo frammento vuoto

`MCP-TOOL-SCHEMA-AUTONOMO` punto 1 dice base uguale a `$id` «se presente»;
`mcp_profile.py::_declared_id` (righe 437–452) e
`codegen.py::_mcp_declared_id` (righe 264–280) trattano invece `""` e `"#"`
come assenza di una base operativa. L'oracolo nuovo
`_cycle10_base` (righe 5121–5125) usa una terza forma: per `""` sceglie
l'URI fisso, per `"#"` una base vuota dopo `urldefrag`.
Queste non sono copie equivalenti dello stesso contesto.

Esempio completo per entrambi i campi:

```json
{
  "$id": "#", "type": "object",
  "$defs": {
    "root": {"$anchor": "root", "type": "object"},
    "holder": {"$id": "#", "type": "object",
               "properties": {"n": {"$ref": "#root"}}}
  },
  "properties": {"entry": {"$ref": "#/$defs/holder"}}
}
```

Con `Registry().with_resource(base, DRAFT202012.create_resource(schema)).resolver(base)`:
base `"#"` → lookup di `#root` e validazione di
`{"entry":{"n":{}}}` non risolvibili;
base `urn:ocor:embedded-tool:0:inputSchema` → entrambi riusciti.
Il profilo attuale accetta. Con `$id:""` le due basi accettano questo esempio,
ma la base registrata resta diversa. Il contratto deve scegliere una regola
unica prima che generatore, profilo e oracolo la implementino.

### Opzioni del quesito B

B1. **Usare la base fissa per identificativi senza base operativa.** Precisare «se presente» come `$id` con parte non vuota prima del frammento: assente, `""` o `"#"` usano l'URI fisso del tool e del campo; ogni altro `$id` usa la propria parte prima del frammento, senza riscrivere lo schema. Profilo, generatore e oracoli nuovi usano esattamente questa regola. È il comportamento di scelta della base già dichiarato nei due moduli di produzione; i test preesistenti restano invariati. I controlli della fase A, che non sono sigillati, vengono allineati soltanto per questa regola esplicita e la differenza è registrata. Costo: incluso nell'iterazione di fase B.

B2. **Usare ogni identificativo presente come base letterale.** Precisare che `""` e `"#"` presenti sono basi letterali date a `Registry` e `resolver`, senza sostituzione con URI fisso né rimozione preventiva del frammento; solo l'assenza usa l'URI fisso. Il produttore rifiuta prima di emettere uno schema che così non si risolve. I test nuovi espongono questa distinzione; se un test preesistente la contraddice, serve un inventario ulteriore prima della sua modifica. Costo stimato: due iterazioni fra inventario e riallineamento, entro il budget vigente; nessuna autorizzazione implicita di altri test.

| Criterio | B1 | B2 |
| --- | --- | --- |
| Esempio con `$id:"#"` | Librerie con base fissa, accettazione | Base letterale, rifiuto tipizzato |
| Schema senza `$id` | Base fissa | Base fissa |
| `$id` assoluto o relativo non vuoto | Base dichiarata senza frammento vuoto | Base letterale dichiarata |
| Byte degli schemi | Originali | Originali |

### Quesito C: ambito della collisione dell'URI fisso

`MCP-TOOL-SCHEMA-AUTONOMO` punto 1 richiede un URI fisso che non coincida con
alcun `$id` «del documento»; `MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE` punto 2
parla invece di un `$id` «presente in quello schema». B1 della decisione
sul conflitto dell'oracolo riprende il secondo ambito.
Le risorse sono autonome: un'identità in un altro campo o strumento non
entra nel registro locale, ma la prima formula può imporre anche un rifiuto
dell'intero descriptor. È un quesito sul confine, non sulla capacità di lookup.

Esempio completo:

```json
{
  "x-ocor-mcp-protocol-revision": "2026-07-28",
  "tools": [{
    "name": "example",
    "inputSchema": {"type": "object"},
    "outputSchema": {"$id": "urn:ocor:embedded-tool:0:inputSchema",
                     "type": "object"}
  }]
}
```

Il profilo attuale accetta, e il registro del solo `inputSchema` risolve
`#` sulla propria radice. Lo stesso avviene spostando l'ID in un secondo
tool. Una collisione dentro lo stesso `inputSchema` è già da rifiutare
per B1; il codice attuale la accetta scegliendo un suffisso, difetto già
rosso nella matrice. Le sonde includono indice 0 e 1, altro campo e altro
tool, con e senza `#` finale: 12 input pubblici, tutti accettati oggi.
Queste osservazioni non approvano alcuno degli esiti futuri.

### Opzioni del quesito C

C1. **Limitare la collisione allo schema autonomo.** Chiarire che per ogni base fissa si controllano i `$id` soltanto dentro quel medesimo schema; un `$id` in altro campo, altro tool o metadato del descriptor non è una collisione di quel registro. Un frammento vuoto finale non distingue due identità URI: collisione locale anche con `#` finale, rifiutata prima del lookup. L'esempio sopra resta accettato, il lookup di un target presente soltanto nell'altro campo resta rifiutato. I test preesistenti restano invariati salvo quelli già autorizzati. Costo: incluso nell'iterazione di fase B.

C2. **Applicare una collisione globale del descriptor.** Chiarire che la base fissa di ogni schema non può coincidere con un `$id` in alcun campo o strumento del descriptor, normalizzato il solo frammento vuoto finale. L'esempio sopra è rifiutato dal profilo e dal produttore. I registri restano separati: il controllo globale non consente lookup incrociati. Prima di applicare modifiche a test esistenti non già autorizzate si presenta l'inventario necessario secondo la regola vigente per le decision request. Costo stimato: due iterazioni fra inventario e prova, entro il budget vigente.

| Criterio | C1 | C2 |
| --- | --- | --- |
| Collisione dentro lo schema | Rifiuto tipizzato | Rifiuto tipizzato |
| ID uguale in altro campo/tool | Nessuna collisione locale | Rifiuto del descriptor |
| Target presente solo nell'altro campo/tool | Sempre rifiutato | Sempre rifiutato |
| Suffisso alternativo per evitare collisioni | Vietato | Vietato |

## Raccomandazione

Opzioni A1, B1 e C1. A1 completa l'elenco senza derogare alle librerie;
B1 rende esplicita la stessa scelta della base operativa già usata dai due
moduli; C1 segue la clausola più recente sullo schema autonomo e conserva
l'isolamento. Nessuna di queste raccomandazioni attua le opzioni.

## Ambito residuo e ripresa

File tecnici: `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`, solo `_mcp`
e i suoi helper in `ocor-runtime/src/ocor_runtime/c1/codegen.py`,
`ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`, README e record in
`reports/assurance/OCOR-DEV-REM-0063-RCCAD/`.
Prima della decisione non si modifica produzione né il test di A.
La copertura nuova delle classi di URI relativi procede senza anticipare B/C.

La regola esistente delle catene anchor → puntatore resta invariata: si conserva
il resolver restituito dalla libreria. Il controllo statico della matrice non
è l'oracolo universale di quelle catene; i test del ciclo 8 le esercitano con
istanze positive e negative. Non si richiede di cambiarne alcuno.

Nessun test rimosso, saltato, deselezionato o meno severo; nessuna modifica a
fixture fissata, record sigillati, voci esistenti dei manifest, contratto del
dossier, schema, gate, timer, tetto, partizione, immagine, digest o `inputs/`.
Il flusso residuo resta quello autorizzato per il ciclo 10.
Claim invariati: E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED,
PoC e Production NO-GO.

## Controllo del formato

Eseguito prima della pubblicazione:

```bash
grep -cE '^[A-Z]?[0-9]{1,2}\. \*\*' reports/development/decision_requests/REM-0063-CYCLE10-REMAINING-CONTRACT-QUESTIONS.md
```

Esito: `6`, corrispondente ad A1/A2, B1/B2 e C1/C2, consecutive sotto
le rispettive sezioni delle opzioni. Nessuna opzione aggiunta o cambiata.
