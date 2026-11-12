# REM-0061-CYCLE3-MERIT-NO-GO

Status: `DECIDED_BY_PO`. Livello: operativo. Nessun nuovo `DEC-*`.
Opzione adottata: **1**, con le precisazioni dei punti 2 e 3 della decisione
`REM-0061-CYCLE3-MERIT-NO-GO (2026-11-12)`. Il testo della richiesta, sopra la
disposition, resta quello aperto al commit `6c2bb7995b29228abd700a52e986651436c4a2f6`.

## Contesto

Il verdetto di merito `OCOR-DEV-REM-0061-a65649022b29-3-reassign` è `NO_GO` sull'HEAD
`a65649022b29a59edece529fd40b4ef872dcba15`. Lo sha256 del file di verdetto è
`4e70cd80a7cd9991c4d407ce357c3402321060b81db4a9ba26b52e2f3b46a6a6`.
Il verifier è Claude Code, modello `claude-opus-5-5`, fornitore Anthropic, effort high,
in un processo separato, non avviato dall'implementatore. Il fornitore del verifier è
diverso da quelli degli implementatori e del revisore preventivo.

L'implementatore del ciclo 3 è Grok Build, modello grok-4.7 (xAI). Codex (OpenAI) è
contato fra gli implementatori dalla decisione `REM-0061-REPAIR-BUDGET (2026-11-12)` e
non ha commit sul branch. Il revisore preventivo del ciclo 3 è Cursor, modello
`cursor-grok-4.6-xhigh` (xAI), richiesta `OCOR-DEV-REM-0061-cf3739600e1f-pre`, esito
`BLOCKING_FINDINGS` sull'head `cf3739600e1ffa59f6b332fcf915f45f6543b5d4`: il finding
bloccante è stato corretto prima della campagna e la revisione non è stata ripetuta.
È un revisore di riserva, dello stesso fornitore dell'implementatore.

Due finding sono `high` e bloccanti. Zero `critical`. Due `medium` e quattro `low` non
sono bloccanti. La campagna indipendente del verifier sullo stesso HEAD è PASS: 5826
test, zero skip, unione esatta, quattro corsie, teardown PASS, residuo vuoto, 1766,038 s.
I finding non sono fallimenti di quella suite.

- VF-001, high, bloccante, `scripts/validate_evidence_input_drift.py`. Un successore
  elencato nel manifest per un task esce dall'insieme se il `task_id` del record
  differisce da quello del manifest (identificativo diverso, spazio finale, differenza
  di maiuscole). Il gate verifica solo il predecessore e può dare PASS. La stessa classe
  include un successore elencato senza `supersedes`, input senza digest per file quando
  il task ha più record, e voci di manifest non canoniche. I casi del verdetto precedente
  sul record illeggibile sono chiusi; la classe no.
- VF-002, high, bloccante. I record non sigillati
  `reports/evidence/G2/OCOR-DEV-REM-0037.requalified-rem0061.json` e
  `reports/evidence/G2/OCOR-DEV-REM-0056.requalified-rem0061.json` citano il commit
  `b22debf2e08e805db56643030b17efafdd5e4da5`, cioè il codice del ciclo 2, non l'HEAD.
  Il record dell'unità dichiara che non restano riqualifiche. Il validatore di drift non
  seleziona questi due task, quindi la deriva non è rilevata dal gate ordinario.
- VF-003, medium, non bloccante. La lettura del log di corsia sta fuori dal `try`: una
  directory di output non attraversabile salta teardown e rimozione della cache.
- VF-004, medium, non bloccante. Il record non dichiara il limite di indipendenza del
  revisore preventivo di riserva (stesso fornitore dell'implementatore, modello diverso).
- VF-005, low. Alcuni test di campagna dipendono dallo spazio libero reale di `/tmp`.
- VF-006, low. La campagna dell'implementatore ha montato `uv` 0.13.5, mentre il lock
  fissa `uv` 0.12.5. La campagna del verifier, con lo strumento del lock, è PASS.
- VF-007, low. `roles.implementers` non elenca Codex (OpenAI).
- ENV-001, low. Osservazione di ambiente della verifica, non difetto del repository: la
  prima campagna del verifier non è contata. Non entra nel perimetro di codice.

Il verdetto `OCOR-DEV-REM-0061-a65649022b29-3` (sha256
`7e8b3c9a8d8132160aa5c6eb77fc27cb9021471e39256c45c88e4b7b6e6e8713`) è un `NO_GO` di sola
assegnazione: verifier Codex (OpenAI), escluso, controlli tecnici `NOT_EXECUTED`. Non
giudica il codice e non consuma il ciclo 3.

La decisione `REM-0061-REPAIR-BUDGET (2026-11-12)`, opzione 1, ha autorizzato quel solo
ciclo 3 e stabilisce che, se il verdetto è ancora `NO_GO`, non c'è un ciclo 4: nuova
escalation e il task resta bloccato. Questa richiesta è quella escalation. Il ciclo 4
non è autorizzato da quella decisione. La diagnosi e l'azione minima sono nel record
`reports/development/OCOR_DEV_REM_0061_ESCALATION.md` di questo stesso commit.

La PR #595 resta bozza e non si integra. `OCOR-DEV-REM-0060` (NCP-U12) resta in coda
fino al merge di `OCOR-DEV-REM-0061`. I task G6 restano sospesi come già deciso.
L'adozione della PR #599 resta dopo un GO di `OCOR-DEV-REM-0061`, secondo
`ADOZIONE-PR599-FABLE52 (2026-11-11)`, e non parte da questa richiesta.

## Opzioni

1. **Un solo ciclo 4 sul verdetto di merito (raccomandata).** Autorizzare un solo ciclo
   di riparazione 4 di `OCOR-DEV-REM-0061`, sul branch
   `governed/ocor-dev-rem-0061-lane-image-cache`, a partire dall'HEAD
   `a65649022b29a59edece529fd40b4ef872dcba15`, senza rebase, reset o force-push. Il
   perimetro è soltanto i finding VF-001, VF-002, VF-003, VF-004, VF-005, VF-006 e
   VF-007 del verdetto `OCOR-DEV-REM-0061-a65649022b29-3-reassign`. ENV-001 resta fuori.
   VF-001: il gate rifiuta, per il task del manifest e senza traceback, un `task_id` del
   record diverso da quello del manifest e non lascia che il predecessore sostituisca un
   successore elencato escluso; gli input senza digest per file sono vuoti quando il
   task ha più record. VF-002: rieseguire la regressione di REM-0037 e REM-0056 sul
   commit di codice finale e rigenerare i due record non sigillati, con supersession
   invariata verso i predecessori sigillati, manifest G2 e controllo dei digest. VF-003
   a VF-007: teardown anche se la directory di output non è leggibile; limite di
   indipendenza del revisore di riserva nel record; test che non misurano `/tmp` reale
   indipendenti dallo spazio dell'host; strumenti montati nelle corsie con il digest del
   lock e dichiarati nel record; `roles.implementers` allineato agli implementatori già
   dichiarati. RED prima del codice e GREEN dopo, sui casi del verdetto. Nessun test,
   gate, timer, tetto, partizione o criterio viene indebolito. La campagna del ciclo 3
   non si trasferisce. Seguono il gate locale, il controllo meccanico dei digest di
   esecuzione, la revisione preventiva se richiesta dalla procedura, la suite completa e
   una nuova verifica indipendente sull'HEAD esatto. Il verifier è di un fornitore
   diverso da xAI e da OpenAI. Se il verdetto è ancora `NO_GO`, non c'è un ciclo 5:
   nuova escalation e il task resta bloccato. Questa opzione è una autorizzazione nuova:
   `REM-0061-REPAIR-BUDGET (2026-11-12)` non la contiene.
2. **Solo i due finding bloccanti.** Stessi vincoli, stesso branch e stesso HEAD
   dell'opzione 1, ma il perimetro è soltanto VF-001 e VF-002. VF-003, VF-004, VF-005,
   VF-006 e VF-007 restano registrati e non sono, da soli, motivo per cambiare test,
   gate o criteri. Se il verdetto successivo ne tratta uno come bloccante, non c'è un
   ciclo 5 sotto questa opzione: nuova escalation e il task resta bloccato.
3. **Nessun altro ciclo; la coda resta ferma.** Non autorizzare un ciclo 4.
   `OCOR-DEV-REM-0061` resta `BLOCKED_CYCLE3_MERIT_NO_GO_NO_CYCLE_4`. La PR #595 non si
   integra. `OCOR-DEV-REM-0060`, NCP-U12 e i task che dipendono dal merge di REM-0061
   restano in coda. I task G6 restano sospesi. L'adozione della PR #599 non parte.
   Nessuna modifica al codice di campagna o al validatore dei digest. Una ripresa
   richiede una decisione successiva.

## Raccomandazione

Opzione 1. VF-001 è una classe fail-open del gate dei digest, non un caso singolo già
chiuso. VF-002 lascia i record di regressione sul codice permissivo del ciclo 2. I
finding non bloccanti stanno negli stessi file e negli stessi record: chiuderli nello
stesso ciclo evita una verifica che supera i due finding high e si riapre sugli altri.
L'opzione 2 è più stretta e lascia difetti già riprodotti. L'opzione 3 è conforme al
divieto attuale di ciclo 4 e ferma la coda, perché `OCOR-DEV-REM-0060` attende il merge
e i task G6 restano sospesi.

## Impatto e task bloccati

Senza una decisione restano bloccati `OCOR-DEV-REM-0061` e, per la coda già decisa,
`OCOR-DEV-REM-0060`. I task G6 restano sospesi come già deciso. La PR #595 non si
integra. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`,
PoC e Production `NO-GO`. Nessuna modifica a `inputs/`.

## Disposition

`DECIDED_BY_PO` il 2026-11-12, istruzione esplicita del Product Owner, opzione 1,
come raccomandata in questo file al commit `6c2bb7995b29228abd700a52e986651436c4a2f6`
(sha256 `731d084e8c0e0692756c5beb89c501b0bbdcae110e1355e3032e54b292b44835`), con le
precisazioni dei punti 2 e 3 della decisione `REM-0061-CYCLE3-MERIT-NO-GO (2026-11-12)`.
Dove il riassunto e questo file differiscono, vale questo file. Le precisazioni restano
dentro i finding del verdetto e non cambiano test, gate, timer, tetti, partizioni o criteri.

Il ciclo 4 è stato eseguito sul branch `governed/ocor-dev-rem-0061-lane-image-cache`,
dall'HEAD `a65649022b29a59edece529fd40b4ef872dcba15`, senza rebase, reset o force-push.
HEAD del ciclo: `d45161f3b86feb588b0f66d1f1b6b2729a375e6f`.

Verdetto `OCOR-DEV-REM-0061-d45161f3b86f-4`: `NO_GO`. Sha256 del file
`d36d8ac2f89ea6f2e88c22075c06d4f2f4cf0047ebdeb8b59e6a049dd82be589`. Due finding high
bloccanti, entrambi la classe di VF-001 del verdetto di merito del ciclo 3 ancora aperta:
VF-001, un path di manifest che non è una stringa non produce finding e il predecessore
resta PASS; VF-002, un record elencato il cui `task_id` non coincide con quello del
manifest e non è un task completato esce dall'indice e il predecessore resta PASS.
VF-002, VF-003, VF-004, VF-005, VF-006 e VF-007 del verdetto
`OCOR-DEV-REM-0061-a65649022b29-3-reassign` risultano chiusi sui controlli rieseguiti.
ENV-001 resta fuori perimetro. La campagna FOUR_LANE del verifier sull'HEAD è PASS:
5826 test, zero skip, zero fallimenti, unione esatta, 1770,243 s, tetto 5400 s.

Verifier di riserva: Cursor, modello grok-4.7-xhigh, fornitore xAI, stesso fornitore
dell'implementatore Grok Build (xAI). `independent_verification: SAME_VENDOR_FALLBACK`,
riferimento `VERIFIER-CLAUDE-OPUS (2026-11-12)` punto 2 e `VERIFIER-RISERVA (2026-11-11)`.
Il verdetto è di merito e vale. Implementatori dichiarati: Grok Build (xAI), con tutti i
commit del branch compreso il ciclo 4, e Codex (OpenAI), senza commit sul branch.

Come dice l'opzione 1: il verdetto è ancora `NO_GO`, non c'è un ciclo 5, nuova
escalation, il task resta bloccato. La PR #595 non si integra. `OCOR-DEV-REM-0060` resta
in coda fino al merge di `OCOR-DEV-REM-0061`. Nessun nuovo `DEC-*`. Claim invariati.
