# REM-0063-CYCLE10-INTERNAL-RESOURCE-URI

Stato: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`.
Livello: `NORMATIVE`. Unità: `OCOR-DEV-REM-0063`, ciclo 10, fase A.
Base di produzione: `f485dc964e47bde83842ecd5ba2627d8342612f9`.
Prima revisione del contratto: `OCOR-DEV-REM-0063-5dae37f94a80-pre`, P6.

## Contesto e quesito unico

La prima revisione del contratto ha distinto un quesito dalla scelta già
compiuta in `REM-0063-CYCLE10-ORACLE-CONFLICT (2026-11-16)`, A1+B1:
che cosa significa «riferimento interno» quando il riferimento non inizia
con `#`, ma nomina una risorsa contenuta nello stesso schema autonomo.
Le prove eseguibili stabiliscono che la libreria lo risolve; non stabiliscono
quale dei due profili sia stato voluto dal testo delle decisioni.

`MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)` punto 1 include la risorsa autonoma
e le risorse che contiene, secondo JSON Schema 2020-12. Il punto 2 vieta
ricadute sul descriptor, sugli altri strumenti e il recupero esterno.
`REM-0063-CYCLE7-NO-GO (2026-11-15)` punto 2 applica la restrizione
«riferimento interno allo stesso documento» al bersaglio risolto.
Il modulo `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`, righe 5–7,
262 e 1077–1078 alla base, impone invece che lo spelling inizi con `#`.
`docs/development_plan/OCOR_MCP_2026-07-28_PROFILE.md`, riga 60 circa,
descrive la medesima restrizione dei frammenti.

`REM-0063-CICLO-10-CONTRATTO (2026-11-16)` punto 2 richiede «URI di una
risorsa annidata» come dimensione; il contratto pubblicato prima della
revisione citava il rifiuto esistente come se fosse imposto dalla decisione.
Quella citazione è stata rimossa: ora la questione è aperta, senza cambiare
il codice né i test esistenti. La richiesta precedente trattava soltanto
lo spelling percent-encoded e la collisione della base fissa. La revisione
ha individuato questa diversa incertezza fra il confine della risorsa e
la restrizione lessicale; le opzioni già decise non ne autorizzano la scelta.
Questa richiesta raccoglie anche i conseguenti casi relativi, con frammento
e senza, e la regola di accordo fra produttore e consumatore.

## Prova e esempio completo

Python 3.12.11, `referencing` 0.37.0, `jsonschema` 4.26.0, dal lock vigente.
Lo schema di `inputSchema` o `outputSchema` consegnato è:

```json
{
  "$id": "https://cycle10.invalid/root.json",
  "type": "object",
  "$defs": {
    "holder": {
      "$id": "https://cycle10.invalid/child.json",
      "type": "object",
      "$defs": {"leaf": {"type": "object"}}
    }
  },
  "properties": {
    "entry": {"$ref": "https://cycle10.invalid/child.json#/$defs/leaf"}
  }
}
```

Con `Registry().with_resource(schema["$id"], DRAFT202012.create_resource(schema))`,
`resolver(schema["$id"]).lookup(schema["properties"]["entry"]["$ref"])`
restituisce `{"type":"object"}`. `Draft202012Validator(schema)` valida
`{"entry":{}}` senza errori e senza rete. Inserito nello strumento `cycle10`
di un descriptor con revisione `2026-07-28`, il percorso pubblico
`validate_mcp_descriptor` solleva `McpProfileError` con testo
`MCP $ref must be a same-document fragment`.
La sonda completa conserva schema, target e risultato; SHA256: `bbbbe14e46a46ae0434aeae62fd97490106d45c7cd2635af12f07ce979d806ae`.

Gli esempi gemelli da includere nel contratto sono lo stesso riferimento
scritto come `child.json#/$defs/leaf`, l'URI della risorsa senza frammento,
e un URI che nessuna risorsa dello schema contiene. Il consumatore usa
sempre i byte originali e le librerie fissate; nessun caso abilita rete.

## Opzioni

1. **Conservare il profilo limitato ai frammenti.** Chiarire che «interno» per questo profilo significa anche spelling che inizia con `#`: ogni URI con parte prima del frammento è rifiutato con `McpProfileError`, anche se `referencing` può risolverlo senza rete in una risorsa contenuta. La regola più severa del modulo resta e il contratto la attribuisce a questa disposition. La matrice registra separatamente risoluzione della libreria e rifiuto del profilo, con negativi su URI assoluti, relativi, con e senza frammento. Il generatore emette solo i riferimenti `#/$defs/<Nome>` già prescritti e rifiuta prima della restituzione se lo schema finale richiede uno spelling vietato. Nessun test esistente cambia; i casi della nuova matrice mantengono il rifiuto. Costo aggiuntivo: incluso nell'iterazione di completamento del contratto, più il flusso del ciclo 10 già previsto.

2. **Ammettere gli URI delle sole risorse contenute.** Chiarire che la restrizione riguarda il bersaglio contenuto nello schema autonomo, non lo spelling iniziale: un URI assoluto o relativo, con o senza frammento, è accettato solo se `referencing` 0.37.0 lo risolve dentro quella risorsa o una sua risorsa contenuta, senza alcun recupero. Supersedere espressamente la regola «same-document fragments only» del modulo e del documento derivato del profilo; autorizzare nel ciclo 10 la sola correzione di quella riga del documento e dei relativi test nuovi della matrice. Un URI che richiede recupero, una risorsa del descriptor, di un altro campo o strumento resta rifiutato. Il generatore conserva i `#/$defs/<Nome>` prescritti; ogni artefatto emesso deve passare il profilo ampliato e le due librerie sullo schema da solo. I negativi esistenti per documenti esterni restano identici. Se emerge un altro test esistente contrario, si applica la regola vigente per le decision request. Costo aggiuntivo stimato: un'iterazione entro il ciclo 10 per matrice, profilo e prova di accordo, oltre al flusso già previsto.

| Criterio | Opzione 1 | Opzione 2 |
| --- | --- | --- |
| Esempio completo sopra | Rifiuto tipizzato del profilo, libreria risolvibile | Accettazione, target e istanza coincidono con le librerie |
| `child.json#/$defs/leaf` quando risolvibile localmente | Rifiuto tipizzato | Accettazione |
| URI della risorsa contenuta senza frammento | Rifiuto tipizzato | Accettazione della radice della risorsa |
| URI assente, recupero esterno, altro tool/campo | Rifiuto tipizzato | Rifiuto tipizzato |
| Emissione del generatore | Solo schema accettabile dal profilo e dalle librerie | Stessa proprietà con il profilo chiarito |
| Dipendenze, immagini, limiti, byte della fixture | Invariati | Invariati |

## Raccomandazione

Opzione 1. Conserva il sottoinsieme già dichiarato nel modulo e nel documento
derivato, senza introdurre una nuova forma accettata. Le librerie restano
l'oracolo della risoluzione, mentre il rifiuto aggiuntivo diventa esplicito
nel contratto. La raccomandazione non decide il quesito.

## Impatto, ambito e ripresa

Blocca soltanto il codice del ciclo 10 che dipende da questa interpretazione
e la campagna completa di `OCOR-DEV-REM-0063`. Contratto, nuovi test, seconda
revisione del contratto e registrazione delle decisioni ricevute procedono.
Nessun'altra unità dipende dal risultato tecnico di questa richiesta.
Non si chiede un ciclo 11 e non si cambia il budget del ciclo 10.

File tecnici in ambito: `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`,
la funzione `_mcp` e i suoi helper in
`ocor-runtime/src/ocor_runtime/c1/codegen.py`,
`ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`,
`reports/assurance/OCOR-DEV-REM-0063-RCCAD/README.md` e il record
`reports/assurance/OCOR-DEV-REM-0063-RCCAD/OCOR-DEV-REM-0063.json`.
Solo l'opzione 2 autorizza la riga indicata del documento derivato.
Nessun record sigillato, manifest esistente, gate, timer, tetto, partizione,
immagine, digest, contratto del dossier o `inputs/` cambia.
Claim invariati: E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED,
PoC e Production NO-GO.
