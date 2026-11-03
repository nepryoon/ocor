# NCP-U04-MEMORY-PROMOTION-GATE-PACKAGE

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0050`
(NCP-U04 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, C3 commit admission, composizione C6 -> C3 e relay
dell'outbox; branch `governed/ocor-dev-rem-0050-ncp-u04-c3-commit-admission`, head di lavoro `8afc3ad`). Aperta
secondo il punto 1 di `NORMATIVE-CONFORMANCE-PLAN` e il punto 6 («Stop») di
`NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)`: per mantenere verdi tre casi di
`ocor-runtime/tests/tasks/test_ocor_dev_0058.py`, consumer di C3 che il piano assegna all'inventario di NCP-U04,
serve una modifica del codice di produzione di `ocor-runtime/src/ocor_runtime/memory/promotion.py`, che non è fra
i `code_paths` di NCP-U04 (è fra quelli di NCP-U07), e un cambiamento di test oltre l'adattamento della
costruzione. Implementatore: Claude Code (Anthropic), implementatore di riserva del loop.

## Contesto

- NCP-U04 risolve `NCR-C3-001` e `NCR-C3-002`: prima della transazione C3 valida «provenienza C6, Decision,
  Authority, Evidence» (`docs/OCOR_LLD_v1.1.md` riga 97) e accetta un commit «soltanto con `Decision` e
  `Authority ref` validi, non scaduti e coerenti con il `GatePackage` congelato» (ADD v1.3 §2.5 regola 10,
  `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md` riga 342). L'implementazione
  dell'unità, `ocor-runtime/src/ocor_runtime/c3/admission.py` (`CommitAdmission.admit`, righe 296-372 all'head
  `8afc3ad`), risolve il record `GatePackage` firmato da C6 il cui digest canonico è `gate_package_digest` del
  comando (righe 301-306) e verifica che i campi del comando coincidano con il pacchetto congelato (righe
  307-316); poi Decision e Authority firmate e legate allo stesso digest. `PostgresC3Service` e
  `TerminusDBC3Service` non si costruiscono più senza admission.
- `C6MemoryPromotionConsumer` (`ocor-runtime/src/ocor_runtime/memory/promotion.py`, classe alla riga 452,
  codice invariato rispetto a `main`) è il consumer C6 del percorso di promozione «`MemoryItem →
  MemoryPromotionProposal → C6 control/approval/decision → GovernedCanonicalCommitCommand → C3`»
  (`docs/OCOR_LLD_v1.1.md` riga 238, task `OCOR-DEV-0058`, requisiti `BR-003` e `FR-053`). Il gate C6 che il
  consumer legge è un corpo firmato con OpenBao che contiene il comando, l'Authority, la Decision, la policy di
  approvazione e le firme. Il consumer esige che `command.gate_package_digest` sia uguale a
  `promotion_gate_digest(body)` (riga 440: digest dell'intero gate senza le due autoreferenze; controllo alla
  riga 523, esito `GATE_PACKAGE_MISMATCH`), poi chiama `self._c3.commit(command)` (riga 551) e verifica la
  ricevuta contro lo stesso comando (riga 554).
- I due vincoli non sono soddisfacibili insieme: lo stesso campo `gate_package_digest` dovrebbe essere sia il
  digest canonico del GatePackage di C3 (un oggetto con `record_type`, `producer`, `stop_epoch`, `frozen_at`,
  digest del delta e binding) sia il digest del gate di promozione (un oggetto diverso, che contiene il comando
  stesso). Nessun adattamento della sola costruzione del test lo risolve: il test può fornire a C3 un'admission
  e un archivio di record firmati, ma non può far coincidere i due digest.
- Esito all'head `8afc3ad`, sullo stack reale (PostgreSQL, OpenBao, Qdrant, OPA), dopo l'adattamento della
  costruzione di C3 nel workflow del test (riga 634; caso 3 del punto 5 di `NORMATIVE-CONFORMANCE-PLAN`, albero
  sintattico delle funzioni di test invariato): 130 casi passano, 3 falliscono, tutti e soli quelli il cui
  comando di promozione raggiunge C3:
  - `test_live_c6_approval_decision_produces_only_c3_commit_and_verified_receipt` (riga 662): C3 rifiuta il
    comando con `GATE_PACKAGE_MISMATCH` («GatePackage does not resolve»), il consumer riporta
    `COMMIT_OUTCOME_UNKNOWN`;
  - `test_live_c3_refusal_after_dispatch_is_indeterminate_never_success` (riga 873): il commit rivale scritto
    direttamente dal test con il comando del gate (riga 882) è rifiutato con `GATE_PACKAGE_MISMATCH`;
  - `test_live_c3_receipt_not_bound_to_command_is_indeterminate` (riga 903): C3 non committa, quindi lo stato
    atteso a revisione 1 manca.
  Prima dell'adattamento i 68 casi che costruiscono C3 fallivano tutti con
  `TypeError: PostgresC3Service.__init__() missing 1 required keyword-only argument: 'admission'`.
- `NCR-C6-009` (registro `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`, unità NCP-U07, `OPEN`,
  `MEDIUM`) già registra che la promozione chiama `c3.commit` direttamente dopo i propri controlli, senza FSM di
  C6, lease normativa ed EMISSION-FENCE di ACT-T29, e accetta le classi di rischio 0-3. NCP-U07 viene dopo
  NCP-U04 in `plan_order` e dipende dalla commit admission di C3 introdotta da NCP-U04 («C3 first in the
  composition chain C3 -> C5 -> C4 required before the C6 action path»).

## Opzioni

1. **Emissione del comando C3 sul percorso governato di C6, dentro NCP-U04 (raccomandata).** NCP-U04 estende il
   proprio ambito a `ocor-runtime/src/ocor_runtime/memory/promotion.py`, solo per l'emissione del comando verso
   C3. `C6MemoryPromotionConsumer` riceve nel costruttore un nuovo parametro obbligatorio, il port C6 di emissione
   del commit canonico già introdotto dall'unità (`CanonicalCommitPath` di
   `ocor-runtime/src/ocor_runtime/c6/engine.py`, oppure un port equivalente basato su `issue_governed_command`
   di `ocor-runtime/src/ocor_runtime/c3/admission.py`, con la chiave di firma di C6 fornita dalla composizione
   fidata). Tutti i controlli esistenti del consumer restano invariati, compreso il legame del gate a
   `promotion_gate_digest(body)` alla riga 523. Subito prima del dispatch (riga 551) il consumer congela il
   GatePackage di C3 sui campi del comando del gate, tutti invariati salvo `gate_package_digest`; firma la
   Decision `ACCEPT` con `effect_class` `CANONICAL_COMMIT`, scadenza uguale a `valid_until` della Decision del
   gate, e l'Authority con la finestra dell'Authority verificata; pubblica i tre record nell'archivio dei record
   di governo che l'admission di C3 legge; invia il comando emesso e verifica la ricevuta contro di esso. Nel
   test `ocor-runtime/tests/tasks/test_ocor_dev_0058.py`: adattamento della costruzione (caso 3) delle tre
   costruzioni del consumer (righe 369, 641 e 906) e del commit rivale (riga 882), emesso sul percorso
   governato; riallineamento con RED (caso 1, ADD v1.3 riga 342) delle righe 668-669, dove il comando verificato
   diventa il comando del gate con il `gate_package_digest` del GatePackage congelato da C6, con un'asserzione
   in più che quel GatePackage è un record firmato da C6 che lega il comando del gate. Nessun caso tolto o reso
   meno severo. `NCR-C6-009` resta `OPEN` in NCP-U07 per FSM, lease, EMISSION-FENCE e classe di rischio. Effetto:
   una iterazione in più per NCP-U04; `memory/promotion.py` entra fra i file modificati dall'unità e fra gli
   input della riqualifica di `OCOR-DEV-0058`, classificata secondo `NCP-UNBINDABLE-REQUALIFICATIONS
   (2026-11-02)`.
2. **Integrazione congiunta di NCP-U04 e NCP-U07.** NCP-U04 non si integra da sola: il suo branch resta come
   base, NCP-U07 (che comprende `NCR-C6-009` e quindi `memory/promotion.py`) si sviluppa sopra di esso, e le due
   unità si verificano e si integrano con un unico change set, con il primo `OCOR-DEV-REM-*` libero per NCP-U07.
   `plan_order` diventa NCP-U04+U07, poi U06, U05, U08-U12. I tre casi di `test_ocor_dev_0058.py` sono risolti
   dalla promozione sul percorso di C6 di NCP-U07. Effetto: nessuna estensione di ambito di NCP-U04, ma un
   change set molto più grande (C3 e intero percorso d'azione di C6), una sola verifica indipendente per due
   unità e il ritardo dell'integrazione di NCP-U04 fino al completamento di NCP-U07; le stime si sommano (4 + la
   stima di NCP-U07).
3. **Seconda forma di GatePackage nell'admission di C3.** `CommitAdmission` accetta, oltre al GatePackage di C6,
   il gate di promozione firmato con OpenBao, riconosciuto dal digest `promotion_gate_digest(body)` e verificato
   con la chiave del verificatore dei gate di C6. `memory/promotion.py` e i test di `0058` cambiano solo nella
   costruzione. Effetto: due formati di pacchetto congelato e due catene di firma accettati da C3 per la stessa
   mutazione canonica, in tensione con ADD v1.3 §4.1 riga 2789 («no second path») e con il criterio di
   `NCR-C3-001`; la forma aggiuntiva andrebbe ritirata con NCP-U07.

**Raccomandazione**: opzione 1. Mantiene una sola forma di GatePackage e una sola catena di firma in C3, come
prescrivono LLD v1.1 riga 97 e ADD v1.3 riga 342; lascia invariati tutti i controlli esistenti della promozione e
non anticipa nulla di `NCR-C6-009`, che resta a NCP-U07; il cambiamento è circoscritto all'emissione del comando
e al riallineamento di una sola asserzione, più severa di prima. L'opzione 2 accorpa due unità grandi in una
verifica sola; l'opzione 3 introduce un secondo percorso di admission da ritirare.

## Impatto e lavoro bloccato

- Bloccati: i tre casi di `ocor-runtime/tests/tasks/test_ocor_dev_0058.py` elencati sopra e quindi la suite
  completa verde, il record dell'unità, il candidato, la richiesta di verifica `REMEDIATION` e l'integrazione di
  `OCOR-DEV-REM-0050`. Le unità successive di `plan_order` (NCP-U06, U05, U07-U12) partono solo dopo
  l'integrazione di NCP-U04.
- Non bloccati: il riallineamento già eseguito di `ocor-runtime/tests/tasks/test_ocor_dev_0046.py` (RED alla base
  `84fb7e7`, GREEN a `2b9e93b`), l'adattamento del mission thread
  (`ocor-runtime/tests/mission_thread/test_first_governed_slice.py`, `b0f106c`, 5 casi verdi), gli altri consumer
  adattati e l'irrobustimento degli adapter C3 per la revisione preventiva.
- Iterazioni di NCP-U04: 2 su una stima di 4 (stop a 8, punto 1 di `NORMATIVE-CONFORMANCE-PLAN`).

Nessun nuovo `DEC-*`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime conformance `NOT_ESTABLISHED`,
PoC e Production `NO-GO`.
