# REM-0019-SEALED-SYNTHETIC-SECRET-SCANNER

Stato: `OPEN_PO_DECISION_REQUIRED`. Apertura: 2026-10-15. Autore: Codex,
implementatore del loop. Unità: integrazione REM-0019, PR #254.

## Contesto e fatti riproducibili

Il candidato `88ba930bd66d06f83f2d4b7d1fbd69bf831e09a2` ha ricevuto il verdetto
`GO_FOR_EVIDENCE_SEAL` `OCOR-DEV-REM-0019-88ba930bd66d-1-integration` da Grok 4.7 via
Cursor, eseguito dal loop esterno in processo, contesto e fornitore separati.
Codex ha applicato il sigillo in `0addbaa99c3f13d39cb64c1e9aee73ca45eed3cd`:
soltanto metadati dei due record nuovi e hash nel manifest G5. Nessun albero
eseguibile, record storico o raw log modificato.

Dopo il retarget della PR #254 da task stage a `main`, la CI obbligatoria ha
rifiutato il candidato nel check `supply-chain`, run `38694928888`, job
`116289165719`. È il primo tentativo qualificante di questo HEAD. Nessun rerun:
la firma è deterministica, non infrastrutturale. I tre workflow lunghi ancora
attivi sullo stesso HEAD sono stati cancellati dopo il fallimento definitivo;
nessuna loro esecuzione incompleta conta come PASS.

L'artifact `11953268316` della run contiene:

- `secrets.json`: tre finding CRITICAL; righe 3298 e 3438 (`PRIVATE_KEY`) e
  riga 3302 (`AWS_ACCESS_KEY`), tutti nel file
  `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0019-marker.json`;
- `static.json` e `dependencies.json`: zero finding;
- il campo coinvolto è `regression_case_identity`, indici 140, 141 e 175:
  identificativi pytest dei casi negativi di rifiuto delle credenziali.
  Le stringhe sono fixture sintetiche presenti nei test storici di 0050
  sul commit `6e1c4b050ac610a22673d6f559e424a01705189c`.
  I due parametri di chiave privata hanno soltanto un'intestazione fittizia
  e il frammento non operativo MIIB; il parametro AWS è un valore fittizio
  della fixture. Questa richiesta non riproduce i marcatori riconosciuti
  dallo scanner.

Il record ha stato `SEALED`; SHA256:
`0e37bcb00cd57560cb74342d00b08a04c8fda7abaac0e762a8bab688dfefdee7`.
Il blob Git `9b14be55228dfe535c83470ac7f41af4de4bee6c` è identico nei commit
`5453075`, `88ba930` e `0addbaa`. I marcatori precedono questa integrazione;
non sono introdotti dal sigillo corrente. Il record e i verdetti restano intatti.

La scansione corrente cerca marcatori lessicali in tutti i JSON sotto 2 MB.
Non distingue i nomi di test storici dalle credenziali reali. L'implementatore
non può correggere il finding riscrivendo il record sigillato, rimuovendolo,
mascherandolo, ingrandendolo oltre la soglia, o escludendolo dal controllo:
sarebbe in conflitto con i divieti del mandato. Il controllo resta FAIL.

Riproduzione senza stampare marcatori: scaricare l'artifact della run con
`gh run download 38694928888`, confrontare i finding per path/riga e
verificare `git rev-parse <ref>:reports/evidence/G5/OCOR-DEV-0050.requalified-rem0019-marker.json`
sui tre ref sopra; confrontare il digest del file e gli indici del campo
`regression_case_identity`. La run esegue lo scanner pinnato nel workflow
`.github/workflows/ocor-supply-chain.yml`, versione 1.0.0, invariato.

## Opzioni e raccomandazione

1. **Disposition governata puntuale per fixture sintetiche in evidenza storica
   immutabile (raccomandata, da autorizzare).** Conservare record e raw intatti;
   introdurre un registro append-only delle sole occorrenze verificate come
   fixture, vincolato a path, digest completo del record, campo/indice e digest
   dell'esatta stringa. L'eventuale scanner deve rifiutare record alterati,
   occorrenze aggiuntive, campi differenti e credenziali fuori da tale insieme;
   nessuna esclusione per file, directory o regola. Prima dell'uso: RED/GREEN
   positivi e negativi, verifica indipendente, riqualifiche degli input sigillati
   coinvolti e CI obbligatoria sull'HEAD esatto. È un'eccezione alla copertura
   lessicale corrente e richiede questa decisione esplicita del PO; non viene
   applicata dal presente change set.
2. **Mantenere il blocco senza eccezioni.** Nessuna modifica a scanner o sigilli;
   PR #254 resta aperta. Eventuali alternative di gestione degli artifact
   storici richiedono una disposizione dedicata che preservi la storia e i
   digest; non si propone una riscrittura come semplice supersessione.

Non è raccomandato sostituire il record storico con una copia sanitizzata:
la supersessione del record corrente è già esplicita, ma non elimina l'obbligo
di conservare i byte storici, che continuerebbero a essere segnalati.

## Impatto e lavoro non bloccato

Bloccati soltanto il merge della PR #254 e i passi della coda che ne richiedono
l'integrazione. Nessun nuovo ciclo di riparazione consumato; REM-0019 resta
al ciclo 1, campagna storica e GO conservati. REM-0023 resta aperta.
Quando questo percorso non ha un'azione eseguibile, proseguono le unità già
autorizzate e pronte secondo la coda del PO (REM-0028, REM-0029, ultimo ciclo
REM-0027, REM-0031), senza cambiare ordine o scope per aggirare il controllo.
Il ritiro del checkout candidato `TEST-INFRA-006` resta un change set CI distinto.
Nessun merge della PR #254 prima dei 13 check obbligatori verdi sull'HEAD esatto.

## Integrità delle prove diagnostiche

- `dependencies.json`: `fe26eda78b0fe2ebce8633f12597bab5f7655bf819ffeec641de7e842e5c823e`.
- `sbom.cdx.json`: `e3107c7bcecb97caf7e1b1e5c2d3eeb2c7ef62e701ddd312c3b6e4dbb5326eb4`.
- `secrets.json`: `9199a58516fe04f0a9e2f509b2e9935a46c00dbbac5940e529aae54eef699b2a`.
- `static.json`: `326e617261aa3955a3bd02fa52ba9a7f22c55e0b4877b0ef6c5cd97ba972b25c`.
- `summary.json`: `d0d8f981f29348e7dbd8abf86d78a55d3260e5ae14e0d7619fe417f20e47707c`.
- Log del job fallito: `51b3930ab6b06debb15d6bbb76bc791d695631c28f6156a4ad07610ea04e8e18`.

Digest SHA256 delle tre stringhe del campo, senza riportarne il contenuto:

- Indice 140: `face5b9e01f3f67cd66a05b7f769d7c9794db20c89608f1738d6f8ed045d277a`.
- Indice 141: `588b75fc376710d8d592238d317df325417a1734200818620e5dde8e8d51c5bb`.
- Indice 175: `fe135a59f6261b411db6f713e7249c545a745bb72619c42a5d3ba1068fffea61`.

Fonte remota: artifact e log della run
<https://github.com/nepryoon/ocor-detailed-design/actions/runs/38694928888>.
Diagnosi locale e copie acquisite conservate nella sessione del loop; nessun
segreto pubblicato. Teardown dello stack locale PASS: zero risorse nuove o
bootstrap residue. `inputs/` intatto, E1=0, E2=0, Verified=0;
runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO` invariati. Nessun nuovo DEC.
