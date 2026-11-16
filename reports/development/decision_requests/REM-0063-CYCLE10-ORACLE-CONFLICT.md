# REM-0063-CYCLE10-ORACLE-CONFLICT

Stato: `DECIDED_BY_PO`.
Livello: `NORMATIVE`. Unità interessata: `OCOR-DEV-REM-0063`, ciclo 10.
Base esaminata: `f485dc964e47bde83842ecd5ba2627d8342612f9`.
Contratto e test nuovi della fase A: `f92d038780f823ed6b9488326a1f7a1e3591b12b`,
branch `governed/ocor-dev-rem-0063-mcp-profile`.

## Contesto e perimetro

`REM-0063-CICLO-10-CONTRATTO (2026-11-16)` punti 2 e 6 richiede le librerie
fissate sullo schema autonomo originale e impone una richiesta quando un test
esistente le contraddice o quando serve cambiare test esistenti. Le decisioni
`MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)` punti 1–3 e
`MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15)` punti 2–4 restano applicabili.
La verifica della fase A ha trovato due questioni collegate alla stessa regola:
l'identità dello schema e della base realmente consegnati al consumatore.
Nessun file di produzione o test esistente è stato cambiato nella fase A.

Non si chiede un altro ciclo di riparazione. Si chiede quali aspettative
esistenti possano essere riallineate **entro il ciclo 10 già autorizzato**.
La fase B resta sospesa su questa richiesta. Il contratto di fase A può essere
rivisto senza modificare produzione. I due quesiti non decidono la questione
separata `REM-0063-PINNED-FIXTURE-DIFF-CHECK`: i byte fissati e `NOT_GREEN`
restano invariati. Task direttamente bloccato: solo `OCOR-DEV-REM-0063`.

## Prove riproducibili

Ambiente: Python 3.12.11; `referencing` 0.37.0 e `jsonschema` 4.26.0 di
`ocor-runtime/uv.lock`. I percorsi e le righe seguenti sono quelli della base.

### Quesito A: frammenti percent-encoded e oracolo senza riscrittura

In `ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`:

| Funzione o dato | Righe | Aspettativa attuale |
| --- | --- | --- |
| `test_cycle4_a_percent_encoded_plain_name_is_decoded_before_classification` | 1398–1401 | Il profilo accetta `#p%61rt` come `#part` |
| `test_cycle4_a_percent_encoded_slash_stays_a_json_pointer` | 1404–1410 | Il profilo accetta `#%2F$defs/part` come puntatore |
| `test_cycle4_a_percent_encoded_tool_schema_anchor_is_decoded` | 1573–1580 | Stessa accettazione, anche per `$dynamicAnchor` |
| `_CYCLE5_ORACLE_FRAGMENT`, `_cycle5_lookup`, `_cycle5_counterproof` | 1833–1841, 2008–2026, 2043–2068 | L'oracolo sostituisce `#p%61rt` con `#part`; la controprova modifica una copia dello schema |
| `test_cycle5_ref_targets_match_referencing_on_the_current_resource` | 2159–2188 | I casi percent-encoded usano quella sostituzione |
| `_CYCLE6_ORACLE_FRAGMENT`, `_cycle6_lookup` | 2222–2230, 2355–2374 | Stessa sostituzione prima del lookup |
| `test_cycle6_ref_targets_match_referencing_on_the_effective_resource` | 2518–2554 | I casi percent-encoded usano quella sostituzione |

Il profilo esegue la decodifica prima del lookup in
`ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`, `_resolve_reference`, righe
1055–1087 circa. Non è la libreria ad accettare lo spelling originale.

Esempio completo, dal descriptor consegnato al consumatore:

```json
{
  "x-ocor-mcp-protocol-revision": "2026-07-28",
  "tools": [{
    "name": "example",
    "inputSchema": {
      "type": "object",
      "$defs": {"part": {"$anchor": "part", "type": "integer"}},
      "properties": {"x": {"$ref": "#p%61rt"}}
    }
  }]
}
```

`validate_mcp_descriptor(descriptor, official_schema, expected_revision="2026-07-28")`
accetta. Sul medesimo `inputSchema`, senza cambiare un byte:

- `Registry().with_resource("urn:example", DRAFT202012.create_resource(schema)).resolver("urn:example").lookup("#p%61rt")`
  solleva `NoSuchAnchor`;
- `Draft202012Validator(schema).validate({"x": 1})` solleva
  `_WrappedReferencingError` con `NoSuchAnchor`;
- sostituendo **solo nell'input del riproduttore** il riferimento con
  `#%2F$defs/part`, il profilo accetta e le due librerie rifiutano con
  `InvalidAnchor`;
- il controllo positivo con `#part`, e il puntatore `#/$defs/part`, sono
  risolvibili senza sostituzioni. Il puntatore `#/%24defs/part` resta distinto:
  la decodifica dei suoi segmenti è svolta dalla libreria stessa.

La nuova matrice `test_cycle10_delivered_cartesian_standalone_oracle` conserva
questi spelling e usa le librerie originali. Correggere il comportamento per
seguirle rende rossi i test esistenti elencati: il punto 6 della decisione del
ciclo 10 richiede questa disposition prima del codice.

### Opzioni del quesito A

A1. **Usare lo schema originale con le librerie fissate.** Confermare la regola del ciclo 10 e autorizzare il riallineamento delle sole aspettative percent-encoded dei tre test di ciclo 4 e dei due test differenziali di ciclo 5 e 6 elencati sopra, insieme alle due mappe e ai tre helper elencati. I nomi, le parametrizzazioni e il numero dei casi restano invariati: gli anchor percent-encoded e la slash iniziale percent-encoded sono rifiutati con `McpProfileError`; gli anchor letterali e i puntatori che le librerie risolvono restano accettati. Gli oracoli non sostituiscono più i riferimenti, nemmeno nella controprova. Ogni altro test esistente resta invariato. Costo stimato aggiuntivo entro il ciclo 10: un'iterazione di riallineamento e prova, oltre al flusso già previsto.

A2. **Conservare la decodifica preventiva come eccezione esplicita.** Mantenere i test attuali e modificare il contratto del ciclo 10 per richiedere alle librerie una copia normalizzata, anziché lo schema emesso o consegnato senza modifiche. Occorre specificare come il consumatore ottiene quella copia e come è legata ai byte originali, così che il descriptor accettato non prometta una risoluzione autonoma che il consumatore originale non ottiene. Questa opzione cambia espressamente la regola sullo schema originale, non la versione delle librerie. Costo stimato: due iterazioni di specifica e test; la superficie di trasporto resta fuori ambito e non viene implementata automaticamente.

| Criterio del contratto risultante | A1 | A2 |
| --- | --- | --- |
| Schema dato a `referencing` e `Draft202012Validator` | Byte originali dello schema autonomo | Copia normalizzata, con legame esplicito ai byte originali |
| `#p%61rt` dell'esempio | Rifiuto tipizzato | Accettazione dopo conversione dichiarata in `#part` |
| `#%2F$defs/part` | Rifiuto tipizzato | Accettazione dopo conversione dichiarata in `#/$defs/part` |
| `#part`, `#/$defs/part`, `#/%24defs/part` | Positivi preservati | Positivi preservati |
| Scope aggiuntivo sui test | Solo l'elenco sopra, senza riduzione dei casi | Nessun cambiamento a quei test; nuovi test del legame fra forme |

### Quesito B: collisione dell'URI sintetico

La decisione `MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE` punto 2 prescrive rifiuto
se l'URI fisso di uno schema senza `$id` coincide con un `$id` al suo interno.
Invece `test_cycle8_synthetic_uri_avoids_declared_id_collisions`, righe
3989–4028 dello stesso modulo, accetta il modo `resolvable` perché il profilo
sceglie un URI con suffisso. `_synthetic_tool_uri`, righe 646–657 di
`ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`, e `_mcp_synthetic_uri`, righe
762–779 di `ocor-runtime/src/ocor_runtime/c1/codegen.py`, applicano tale scelta.

Esempio completo: lo strumento di indice 0 ha `inputSchema` senza `$id`;
`inputSchema.$defs.h.$id` è `urn:ocor:embedded-tool:0:inputSchema`, e
`properties.a.$ref` è `#/$defs/h`. Il profilo attuale sceglie un'altra base e
accetta se `h` possiede il target `#/$defs/t` richiesto dalla sua proprietà `n`.
Il consumatore della base fissa prescritta vede invece una collisione.
La fixture esistente `_cycle8_uri_collision_document("inputSchema", "resolvable")`
produce esattamente questo descriptor; la variante `outputSchema` è analoga.
Il test nuovo `test_cycle10_fixed_base_collision_is_a_typed_refusal` attende il
rifiuto prescritto e fallisce con `DID NOT RAISE McpProfileError` per entrambi i
campi. Cambiare solo il codice renderebbe rosso il test del ciclo 8.

### Opzioni del quesito B

B1. **Applicare il rifiuto già prescritto.** Autorizzare nel ciclo 10 il riallineamento di `test_cycle8_synthetic_uri_avoids_declared_id_collisions` e della sola sua docstring: stesso nome, stesse parametrizzazioni `field`/`mode`, stessi quattro casi; entrambe le modalità attendono `McpProfileError` per collisione prima del lookup. La fixture resta invariata. I positivi senza collisione restano nei test esistenti e nella matrice del ciclo 10. Profilo e generatore usano la stessa base fissa senza ricerca di un suffisso. Costo aggiuntivo stimato: incluso nell'iterazione di A1, oppure un'iterazione se adottato da solo.

B2. **Autorizzare la scelta deterministica di un'altra base.** Supersedere espressamente la clausola di rifiuto del punto 2 della decisione del generatore: profilo e generatore scelgono la prima base senza collisioni con la medesima regola deterministica, e i test del ciclo 8 restano invariati. Il contratto e i test nuovi del ciclo 10 devono esporre quella regola al consumatore. Nessun lookup sul descriptor o su un altro strumento è ammesso. Costo aggiuntivo stimato: un'iterazione di contratto e prova dell'accordo fra produttore e consumatore.

| Criterio del contratto risultante | B1 | B2 |
| --- | --- | --- |
| URI fisso già dichiarato sotto lo schema | Rifiuto tipizzato prima del lookup | Scelta deterministica di un URI diverso |
| Esempio `inputSchema.$defs.h.$id` sopra | `McpProfileError`, nessun descriptor generato accettabile | Il produttore e il consumatore scelgono lo stesso suffisso |
| Isolamento fra tool e campi | Invariato | Invariato |
| Test del ciclo 8 | Quattro casi riallineati al rifiuto | Quattro casi invariati |

## Raccomandazione

Opzioni A1 e B1. Mantengono il contratto esplicito più recente: verifica sui
byte realmente emessi, rifiuto tipizzato delle combinazioni non risolvibili e
rifiuto della collisione della base. Si chiede soltanto l'autorizzazione dei
riallineamenti necessari; non una modifica di librerie, versioni o limiti.

## Impatto, esclusioni e ripresa

Sono coinvolti solo `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`, `_mcp` e
i suoi helper in `ocor-runtime/src/ocor_runtime/c1/codegen.py`, il modulo
`ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py` e il record dell'unità.
Restano intatti test di REM-0047, fixture MCP fissata, record sigillati, voci
esistenti di manifest, `inputs/`, gate, timer, tetti, partizioni e immagini.
La fase B parte soltanto dopo la decisione e la revisione del contratto.
Il flusso residuo resta GREEN, revisione preventiva, gate locale, campagna,
controllo distinto, verifica indipendente sull'HEAD esatto; nessun esito della
fase A li sostituisce. `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`,
PoC e Production `NO-GO`.

## Disposition — REM-0063-CYCLE10-ORACLE-CONFLICT (2026-11-16)

Decisione del PO di persona: quesito A, opzione A1; quesito B, opzione B1. Le sole aspettative e gli helper enumerati nelle opzioni adottate sono autorizzati al riallineamento nel ciclo 10; nessuna normalizzazione degli input delle librerie e nessuna selezione di suffissi per la base fissa. I testi delle opzioni restano invariati. Disposition adottata dopo verifica del file al commit 0531a438f0d68637d8a7221507080a7c672c0847, SHA256 35259990c43e2e2def484b7d763bdc691feb25e262e661d9a5323fa06fdeec41. La fase A prosegue con soli contratto e test nuovi; il riallineamento autorizzato dei test preesistenti resta alla fase B.

La PR della richiesta si chiude come risolta con il riferimento al commit dello state sync; il branch resta conservato. Nessun merge della richiesta.
