# NCP-U01-RETAINED-C1-BUILDERS

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Riguarda l'unità `OCOR-DEV-REM-0047` (NCP-U01 di
`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, branch `governed/ocor-dev-rem-0047-ncp-u01-c1-conformance`, RED
`fb27e601c35d`, fingerprint `65ebdb63dbe8`). Aperta secondo il punto 6 («Stop») di
`NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)` e il punto 1 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`:
la remediation, come scritta nel piano, richiede una riqualifica che il piano non prevede e il riallineamento
di asserzioni per cui la norma non è univoca. Implementatore: Claude Code (Anthropic).

## Contesto

- C1 ha oggi due builder «retained» della release, `RetainedCanonicalIrBuilder`
  (`ocor-runtime/src/ocor_runtime/c1/compiler.py:96-156`) e `FrontendCanonicalIrBuilder`
  (`c1/frontend.py:255-317`), con le classi di `c1/releases.py`. Leggono un DSL pre-normativo di risorse
  (`id`, `fields`, `field_types`, `references`, `execution_owner`) e producono il core piatto con
  `signature_envelope_ref` `urn:ocor:unsigned:<digest>`. Le voci `NCR-C1-002`, `003`, `004`, `006` e `008`
  citano questi file come `code_refs`.
- La norma prescrive invece un sorgente OaC validato da meta-schema con i costrutti di ADD v1.3 righe 417-431
  (package, namespace, module, type, link, constraint, derived, contract, marking scheme, capability
  disposition), il `CanonicalIRCore` di ADD v1.3 righe 441-462 (namespace, module, symbol table, security
  profile, capability matrix e artifact plan obbligatori, `lock_digest`) e la busta DSSE firmata (righe
  466-523). Dal DSL di risorse non si ricavano namespace, module, security profile e capability disposition
  senza fabbricarli.
- Consumer dei builder retained (`consumers_to_inventory` del piano, riverificato su `8725a08`):
  - `ocor-runtime/tests/mission_thread/test_first_governed_slice.py:110-127` (`compile_mission_fixture`):
    costruisce `RetainedCanonicalIrBuilder()` senza firmatario, con una sorgente `id`/`fields`; il file è fra
    gli `inputs` dell'ultimo record di `OCOR-DEV-0031` (`reports/evidence/G3/OCOR-DEV-0031.json`).
    `OCOR-DEV-0031` non è fra le riqualifiche di NCP-U01 (`requalifications.with_supersession_candidates`:
    `0011`, `0028`, `0032`, `0033`); è previsto soltanto da NCP-U12.
  - `test_ocor_dev_0028.py:76-81`, `test_ocor_dev_0032.py:83-87, 192, 228`, `test_ocor_dev_rem_0011.py:66`:
    asseriscono chiavi del core piatto (`core["resources"]`), un solo artefatto `migration-metadata` e il
    riferimento non firmato. Il piano autorizza solo `test_ocor_dev_0028.py:81`; le altre rientrerebbero nel
    caso 1 del punto 5.
  - `test_ocor_dev_0033.py:96, 108, 123, 138`: `IDENTICAL` per release uguali e `BREAKING` per la rimozione
    di una risorsa o di una dichiarazione di tipo. FR-045 (Register v1.1 riga 141) fissa le cinque classi
    `compatible`, `conditional`, `breaking`, `destructive`, `causal-breaking`, ma non associa i cambiamenti
    concreti alle classi: che la rimozione sia `destructive` e che `IDENTICAL` non sia una classe non è
    univoco (punto 7 del programma, ultimo capoverso).
- Rendere conformi i builder retained cambia quindi il mission thread (riqualifica di `0031` non prevista) e
  asserzioni di `0033` su cui la norma non è univoca. Il nuovo pipeline conforme di C1 (meta-schema, compiler
  del `CanonicalIRCore`, firma DSSE e admission, generatori con drift check, classificazione FR-045 con dual
  control e nuovo major, publisher immutabile, conformance suite e le cinque operazioni di ADD v1.3 riga 282)
  non dipende dalla scelta: i test RED di `ocor-runtime/tests/tasks/test_ocor_dev_rem_0047.py` lo
  specificano come modulo nuovo in `ocor_runtime/c1/`.

## Opzioni

1. **Builder retained resi conformi in NCP-U01.** `RetainedCanonicalIrBuilder` e `FrontendCanonicalIrBuilder`
   delegano al compiler conforme: sorgenti OaC, core `ocor.cir/1.0`, firmatario obbligatorio. Servono:
   l'adattamento della costruzione in `compile_mission_fixture` (sorgente OaC e firmatario, senza RED, con
   confronto dell'albero sintattico) e la riqualifica con supersession di `OCOR-DEV-0031`, oltre a `0011`,
   `0028`, `0032`, `0033`; il riallineamento con RED delle asserzioni sul core piatto elencate sopra; una
   mappatura approvata dal PO fra cambiamenti e classi FR-045 (proposta: aggiunta opzionale `compatible`,
   aggiunta obbligatoria senza default `conditional`, cambio di tipo, cardinalità o chiavi `breaking`,
   rimozione di un tipo o di una proprietà `destructive`, cambio di un tipo `CAUSAL` o di un manifest causale
   `causal-breaking`), con il riallineamento di `test_ocor_dev_0033.py:108, 123` a `destructive`.
2. **Pipeline conforme nuovo; builder retained confinati come candidati non rilasciabili (raccomandata).**
   Il percorso normativo della release è il pipeline nuovo; solo da lì nasce una release firmata, ammessa e
   pubblicata. I builder retained restano invariati nel comportamento, salvo le correzioni che non toccano il
   loro contratto (`NCR-C1-008`: `references` ordinato e senza duplicati in `frontend.py`; `NCR-C1-009`:
   SemVer in `CompilerRequest`, `ports.py`), e la docstring li dichiara candidati pre-normativi: l'admission
   e il publisher rifiutano ogni loro output (non firmato, core non `ocor.cir/1.0`). Il riallineamento di
   `test_ocor_dev_0028.py:81` previsto dal piano non si applica: il riferimento `urn:ocor:unsigned:` resta
   corretto per un candidato e la firma è verificata sul pipeline. NCP-U12 porta il mission thread sul
   pipeline conforme (come già per il kernel C8 in `NCR-C8-006`, opzione A); i builder retained e
   `releases.py` entrano nella decision request `NORMATIVE-CONFORMANCE-LEGACY-RETIREMENT` (punto 6 della
   decisione sul piano). Riqualifiche di NCP-U01: `0011` e `0032` (per `ports.py` e `frontend.py`), più
   `0005`, `0050`, `0082`; nessun cambio di `0028`, `0031`, `0033`.
3. **Mission thread anticipato.** Come l'opzione 1, ma l'adattamento del mission thread e la riqualifica di
   `0031` passano da NCP-U12 a NCP-U01; la mappatura FR-045 resta una scelta del PO come nell'opzione 1.

**Raccomandazione**: opzione 2. Realizza tutti gli elementi normativi citati dai criteri di NCP-U01 sul
percorso che produce release, senza fabbricare namespace, module, security profile o capability disposition
dal DSL di risorse; non richiede riqualifiche fuori dal piano né la scelta, oggi non univoca, della classe
FR-045 di una rimozione; è coerente con le disposizioni del PO su `NCR-C8-006` e `NCR-LEGACY-001`
(componente corrente conforme, vecchio percorso invariato fino al ritiro). Con l'opzione 2 il registro
riporta come prova della risoluzione delle voci il pipeline nuovo e il rifiuto, da parte di admission e
publisher, di ogni output dei builder retained.

## Impatto

- Bloccati in attesa della decisione: il GREEN dei builder retained, il riallineamento di
  `test_ocor_dev_0028.py:81`, la campagna, il sigillo e il merge di `OCOR-DEV-REM-0047`.
- Non bloccati: il GREEN del pipeline conforme (comune alle tre opzioni), le correzioni di `NCR-C1-008` in
  `frontend.py` e di `NCR-C1-009` in `ports.py` (comuni alle tre opzioni).
- Nessun nuovo `DEC-*`; ADD, LLD, contratti, schemi, registri normativi, test, soglie, timeout, gate e claim
  invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Disposition del Product Owner — 2026-11-01

Decisione normativa del PO `NCP-U01-RETAINED-C1-BUILDERS (2026-11-01)`: opzione 2 (pipeline conforme nuovo; builder retained confinati come candidati non rilasciabili), con la mappatura delle classi di FR-045 del punto 3. Il testo integrale della decisione, riportato qui sotto senza modifiche salvo il livello del titolo, è la disposition di questa richiesta. La richiesta decisa è il file al commit `51abcaa`, sha256 `5813165b79d483dc7ca61282bc7674e0883cb4de9f1be47b16b28743201008be`. Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`; claim invariati.

### NCP-U01-RETAINED-C1-BUILDERS (2026-11-01) — decisione normativa del PO

Decisione **di livello normativo**, presa dal PO con istruzione esplicita, sulla decision request `NCP-U01-RETAINED-C1-BUILDERS` (`reports/development/decision_requests/NCP-U01-RETAINED-C1-BUILDERS.md`, PR #438, commit `51abcaa`, sha256 `5813165b79d483dc7ca61282bc7674e0883cb4de9f1be47b16b28743201008be`). Il PO sceglie l'opzione 2 e fissa la mappatura delle classi di FR-045 del punto 3. Integra `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` per NCP-U01 e NCP-U12. Nessun nuovo `DEC-*`. Restano invariati ADD, LLD, contratti, schemi, registri normativi e claim.

1. **Percorso normativo della release.** Una release di C1 firmata, ammessa e pubblicata nasce solo dal pipeline conforme di NCP-U01: sorgente OaC validato dal meta-schema, `CanonicalIRCore` `ocor.cir/1.0`, busta DSSE firmata, admission e publisher immutabile. Admission e publisher rifiutano ogni output dei builder retained (`RetainedCanonicalIrBuilder` in `c1/compiler.py`, `FrontendCanonicalIrBuilder` in `c1/frontend.py` e le classi di `c1/releases.py`), perché non è firmato o ha un core diverso da `ocor.cir/1.0`. Un test lo dimostra per l'admission e uno per il publisher.
2. **Builder retained.**
   - Comportamento e contratto restano invariati, salvo le correzioni di `NCR-C1-008` (`frontend.py`) e `NCR-C1-009` (`ports.py`). La docstring li dichiara candidati pre-normativi, non rilasciabili.
   - Il riallineamento di `test_ocor_dev_0028.py` riga 81 previsto dal piano non si applica. Non cambiano le asserzioni sul core piatto di `test_ocor_dev_0028.py`, `test_ocor_dev_0032.py` e `test_ocor_dev_rem_0011.py`, né i test di `test_ocor_dev_0033.py`.
   - I builder retained e `c1/releases.py` entrano fra i file da ritirare della decision request `NORMATIVE-CONFORMANCE-LEGACY-RETIREMENT` (punto 6 della decisione sul piano). Fino ad allora non cambiano oltre a quanto detto qui.
   - Nel registro, la prova di risoluzione delle voci di NCP-U01 che li citano fra i `code_refs` è il pipeline conforme insieme al rifiuto del punto 1, ciascuno con il proprio test.
3. **Classi di FR-045 nel pipeline conforme** (Register v1.1 riga 141; LLD v1.1 riga 107). Valgono solo per il pipeline conforme.

   | Cambiamento | Classe e obblighi |
   |---|---|
   | aggiunta di un elemento opzionale: proprietà nullable o con default, nuovo tipo | `compatible` |
   | aggiunta di un elemento obbligatorio senza default | `conditional`: piano di backfill |
   | cambio di tipo, cardinalità o chiavi | `breaking`: piano di migrazione, dual control, nuovo major |
   | rimozione di un tipo o di una proprietà, anche in un tipo `CAUSAL` | `destructive`: in più, piano di backup e replay; senza, la release è rifiutata |
   | cambio di un tipo `CAUSAL` o di un manifest causale | `causal-breaking`: gli obblighi di `breaking` |

   - Due release identiche sono `compatible`, senza cambiamenti.
   - Una rimozione in un tipo `CAUSAL` porta entrambe le classi, `destructive` e `causal-breaking`, con gli obblighi di tutte e due.
   - La classe della release è la più restrittiva fra quelle dei suoi cambiamenti, nell'ordine `compatible` < `conditional` < `breaking` < `causal-breaking` < `destructive`. Il gate applica gli obblighi di ogni classe presente, non solo di quella dominante.
   - I cambiamenti che la tabella non nomina seguono lo stesso criterio: nessun effetto su dati e consumer, `compatible`; effetto risolto da un backfill, `conditional`; incompatibilità per i consumer, `breaking`; perdita di dati, `destructive`; effetto sui modelli causali, `causal-breaking`. Il record dell'unità riporta la mappatura implementata completa, riga per riga, con la motivazione.
4. **Mission thread (NCP-U12).** Il mission thread usa il pipeline conforme di C1, non i builder retained. In `ocor-runtime/tests/mission_thread/test_first_governed_slice.py`, `compile_mission_fixture` usa una sorgente OaC e un firmatario. È un adattamento della costruzione (caso 3 del punto 5 della decisione sul piano), con il confronto dell'albero sintattico, e con la riqualifica con supersession di `OCOR-DEV-0031` già prevista per NCP-U12. Il resto del mission thread segue l'ambito di NCP-U12 del piano.
5. **Riqualifiche di NCP-U01.**
   - Con supersession: `OCOR-DEV-0011` e `0032`, come nel piano. `0028` e `0033` non hanno riqualifica con supersession, perché i loro test non cambiano.
   - Di sola regressione, nella classe non qualificante di `REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30)`: `0005`, `0050`, `0082` e ogni task il cui ultimo record ha fra gli input un file che NCP-U01 modifica, compresi `0028`, `0031` e `0033`.
   - Nessun test di `0028`, `0031` o `0033` cambia in NCP-U01.
6. **Registrazione.** Al primo state sync registra questa decisione come disposition nel file della decision request, secondo `AGENTS.md`, e nell'`ITERATION_LOG.md`. Se il validatore del piano non ammette il file in un change set di solo stato, il file entra in `main` con il change set di NCP-U01, come per le decisioni precedenti. Poi riprendi `OCOR-DEV-REM-0047`. Le iterazioni già usate contano per la stima di NCP-U01.
