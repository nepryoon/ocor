# FUSEKI-LOCAL-IDENTITY-AFTER-CI-EXERCISE

Status: RESOLVED — decisione PO2026-10-08 eseguita; candidato in verifica indipendente, integrazione pending.
Data: 2026-10-07. Change set REM-0017 WIP; implementatore Codex.

## Contesto osservato

La prova locale della nuova ricetta CI ha costruito dal Dockerfile invariato
un'immagine Fuseki `sha256:3629b2fe3e41cc1845cbee23e69c7f655944dd8c19f7a590bd85d70b508cb834`.
Il lock richiede invece `sha256:a1eb484a7d056a897c7bc832fb735b06136fc876aa90da3055d9882bc1b8d9e3`.
Il primo ID è acquisito da `docker image inspect` e dal log della build CI;
il secondo da infra/services.lock.json. Il digest precedente non è presente
nel daemon (inspect: No such image). Non è stata catturata l'identità prima
della build CI, quindi non si attribuisce con certezza a questa prova l'origine
della deriva o della perdita dell'immagine precedente.

Dockerfile, base digest, SHA-512 dichiarato nel Dockerfile e lock sono invariati.
La ricetta CI usa il Dockerfile approvato e il suo RUN verifica SHA-512;
non si deduce da ciò che l'ID di output coincida con quello della macchina.
Il validator tipizzato accetta la ricetta CI; il controllo di identità nel
bootstrap locale esigerebbe il valore del lock. Non è stato modificato né
aggirato quel controllo. Il PASS della suite sulla ricetta CI non risolve
questa divergenza del bootstrap locale.

## Opzioni e raccomandazione

1. Ripristinare un archivio locale affidabile dell'immagine con l'ID già governato,
   se disponibile. Una ricerca bounded degli archivi nel perimetro OCOR non lo
   ha individuato: recupero dell'artefatto NOT_EXECUTED.
2. Autorizzare una riacquisizione governata separata dell'identità locale dopo
   verifica completa di base effettiva e archivio sorgente, conservando il
   valore precedente, host e data. Non confonderla con la build CI né cambiare
   il validator. La decisione del 2026-10-01 riguarda il cambio macchina;
   qui non si asserisce un nuovo cambio macchina per giustificare l'update.

Raccomandazione: preservare il lock e preferire il recupero dell'artefatto;
se impossibile, usare soltanto una nuova autorizzazione puntuale e un change set
dedicato. Nessun aggiornamento del lock in REM-0017.

## Impatto

Il bootstrap locale che richiede esattamente l'ID del lock resta irrisolto.
Non blocca diagnosi/implementazione della pipeline CI in worktree isolati.
Nessun test escluso, nessun record sigillato modificato, nessuna sostituzione
tecnologica. REM-0017 resta WIP anche per TEST-INFRA-006 assente su main;
0049 conserva NO_GO ciclo 6 e nessun ciclo 7 è autorizzato. Proseguire il
lavoro eseguibile e non promuovere E1/E2/Verified o alcun claim.


## Disposition2026-10-08 — autorizzazione ed esecuzione

La decisione del Product Owner FUSEKI-LOCAL-IDENTITY-AFTER-CI-EXERCISE adotta
l’opzione2 dopo la modifica ADD→COPY già pubblicata in REM17bc811af. Questa
unità separata aggiorna solo l’ID locale del services lock; host, data, vecchio
valore, nuovo ID, base effettiva, SHA512 e hash della ricetta sono nel companion
`infra/fuseki/local_identity.lock.json`. Lo schema chiuso e il checker restano
invariati. La ricetta esatta è archiviata come dati in
`reports/assurance/FUSEKI-LOCAL-IDENTITY-20261008/build_recipe.txt`; il Dockerfile
di main resta quello precedente fino all’accettazione separata di REM17.

Qualifica e otto riqualifiche sono candidate PASS; implementatore Codex/OpenAI,
verifier Claude Code/Anthropic ancora da eseguire in processo e contesto separati.
Il record macchina e i raw log conservano anche i tentativi non qualificanti.
Il contesto storico sopra è preservato, senza attribuire alle sue date gli esiti
successivi. Nessun cambiamento0049 o promozioneREM17; E1/E2/Verified0 e NO-GO
invariati. Review, sigillo e CI esatta precedono il merge di questa unità.


## Integrazione 2026-10-08T16:32:32.334323+00:00

GO_FOR_EVIDENCE_SEAL indipendente Claude Code (claude-opus-5-5) su `1e808f3824a3fae42bf279ea3e05a8f3d71dfe13`; request `FUSEKI-LOCAL-IDENTITY-AFTER-CI-EXERCISE-1e808f3824a3-0`, verdetto SHA256 `f45427b97fe40cf4d58155324bc925bca0b26176520b3f063f4ef8444e27a970`. Candidato e otto riqualifiche sigillati; CI e merge pending. Tre finding low non bloccanti registrati nel candidato. Companion lock come snapshot storico di acquisizione, ricettaCOPY da REM17 non ancora integrata. Nessuna promozione di claim o completamentoREM17/0049.
