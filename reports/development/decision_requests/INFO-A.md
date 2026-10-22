# Decision request — INFO-A (idempotenza C5)

- **Status**: `RESOLVED` — decisione del Product Owner `INFO-A` (2026-10-05), opzione 1; verifica di
  conformità eseguita il 2026-10-12; remediation registrata come `OCOR-DEV-REM-0025`.
- **Fonte**: `reports/review/OCOR_FULL_CODE_REVIEW_2026-09-15.md` (osservazione INFO-A)

## Risoluzione (2026-10-05, eseguita il 2026-10-12)

Il Product Owner ha risolto la richiesta con l'opzione 1: nessuna modifica alla semantica di replay
di C5. Per C5 ADD v1.3 richiede soltanto che `idempotency_key` deduplichi l'evento logico; il
rilevamento "stessa chiave / payload diverso" non è requisito normativo e richiederebbe una nuova
`DEC`, fuori dal mandato attuale. La decisione dispone inoltre una verifica di conformità (non una
modifica semantica) della deduplica rispetto alla chiave di isolamento completa.

### Nota per una futura decisione normativa

Limite registrato e accettato: in `CanonicalEventBackbone.publish` un evento che riusa una
`idempotency_key` già pubblicata **nello stesso contesto** con contenuto diverso viene scartato come
replay, senza quarantena, senza `Violation` e senza Audit Record. Rilevarlo come conflitto (come fa C3
con `IDEMPOTENCY_CONFLICT`, LLD v1.1 §1.5) sarebbe un invariante più forte che oggi nessun testo
normativo impone a C5. Resta materia di una eventuale nuova `DEC`; nessun task o remediation lo
introduce, e `OCOR-DEV-REM-0025` non deve introdurlo.

## Verifica di conformità (2026-10-12)

Oggetto: `ocor-runtime/src/ocor_runtime/c5/backbone.py` su `origin/main`
`12c7758332c022d767c0f526158328da0d4271e3`, SHA-256
`d34a3609907905001a6780242f88e257d7707d05a1a20ade791b6880bf75c914`; consumer
`ocor-runtime/src/ocor_runtime/c5/operations.py`, SHA-256
`922a9984d263cf8bd4a316781d88307b9668248962491799fd017f2effbb95b5`.

Testo normativo (ADD v1.3, baseline composita approvata in
`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md`):

- §1.4: ogni evento è associato a una e una sola istanza di `GovernedContext`; la chiave di
  isolamento è la tupla `(tenant_id, organization_id, domain_id, compartments, purpose,
  classification_marking_ref, ontology_release_digest, policy_bundle_digest)`; "cache e indici non
  sono condivisi fra tuple incompatibili; code, topic e storage prefix sono compartment-scoped"
  (`TB-CXT-05`, fail state `POLICY_DENIED`).
- §3.2, regole runtime: "l'envelope admitted realizza integralmente `GovernedContext` §1.4: la chiave
  di isolamento completa è costruibile per ogni evento ammesso"; "`idempotency_key` deduplica
  l'evento logico"; "ordering è garantito soltanto per `ordering_key` nella relativa partizione".
- §3.0.1, riga Ingestion: enforcement point `C5` admission boundary.
- LLD v1.1 §2.5 (envelope chiuso con GCS/digest) e §6 (C4/C5: ordering per aggregate/partition,
  deduplica durable).

Un evento logico appartiene a un solo `GovernedContext`: due eventi di contesti con chiave di
isolamento diversa non sono lo stesso evento logico, anche se il producer ha riusato la stessa
`idempotency_key`. Una deduplica che li confonde non realizza §3.2 e viola la separazione degli indici
di §1.4.

Prova eseguibile in sola lettura sul codice invariato, fuori dal repository e non qualificante, con un
broker Kafka reale auto-provisionato da `CanonicalEventBackbone.provision` e smontato da `destroy`
(nessun container o volume residuo creato dalla prova):
`~/.ocor-codex/infoa-audit-20261012/probe.py` (SHA-256
`c14b939e09193667d2a8ea7c0e724df243c55d526f2042d5113bd5a3f3b3ceab`), esito `probe-result.json`
(SHA-256 `d869fda55b537ea9f0f0ea1395c68a9f9f0157b64fcb68704909be1b83d443db`). I due tentativi
precedenti della prova, falliti per difetti della prova stessa (doppia creazione del topic; lettura di
un numero insufficiente di record), sono conservati nella stessa cartella. È un'osservazione del
comportamento attuale, non evidenza `E1`/`E2`.

| Punto | Codice | Esito | Prova |
|---|---|---|---|
| Deduplica per evento logico nello stesso contesto | `publish`, righe 312–315: replay con chiave già vista è un no-op | **Conforme.** Il replay identico non produce un secondo record | `test_a_replayed_idempotency_key_is_a_safe_no_op_not_a_duplicate_publish` (0040) |
| Deduplica rispetto alla chiave di isolamento | `_seen_idempotency_keys: set[str]` (riga 173), indicizzato dalla sola `idempotency_key` (righe 312 e 342); `governed_context_digest` ignorato | **Non conforme.** Un evento del contesto B con la stessa chiave di un evento già pubblicato dal contesto A è scartato in silenzio: nessun errore, nessuna quarantena, nessun dead letter, nessun record sul topic | `P1` (nessun errore né quarantena); `P2`, attraverso `EventOperationsCoordinator.publish_with_backpressure`: sul topic 2 record invece di 3, `dead_letters` vuoto |
| Replay da DLQ | `EventOperationsCoordinator.replay` delega a `publish` | **Non conforme per derivazione.** Il replay di un dead letter del contesto B è scartato se il contesto A ha già usato la stessa chiave | Stesso ramo di `P2` |
| Stato di ordinamento per aggregate (controllo di classe) | `_last_sequence: dict[str, int]` (riga 172), indicizzato dal solo `aggregate_ref` (righe 317 e 341) | **Non conforme, stessa classe.** Un evento del contesto B è messo in quarantena `OUT_OF_ORDER` per la sequenza di un evento del contesto A con lo stesso `aggregate_ref` | `P3`: contesto A sequenza 5, contesto B sequenza 1 → `OUT_OF_ORDER` |

Il backbone non vincola un'istanza a un solo contesto: lo stesso topic accetta envelope con
`governed_context_digest` diversi, quindi lo scoping per compartimento di topic e code (§1.4) non è
imposto dal codice e non rende irraggiungibili i casi `P1`–`P3`.

Osservazioni fuori ambito, nessuna azione in questa unità:

- La deduplica è in memoria e si perde al riavvio, mentre LLD v1.1 §6 richiede "deduplica durable"
  per C4/C5: è il punto 1 della decisione `INFO-C`, che lo valuta nella propria unità.
- `publish_with_backpressure(tenant=…)` usa un tenant fornito dal chiamante, non derivato
  dall'envelope: riguarda la quota di backpressure (punto 2 di `INFO-C`), non la deduplica.
- L'envelope del PoC (`CanonicalIngestionEnvelope` a 14 campi) porta solo `governed_context_digest` e
  non i campi della chiave di isolamento; la sua chiusura rispetto allo schema completo di §3.2 non è
  oggetto di questa verifica.

Percorso reale del PoC: `CanonicalEventBackbone` ed `EventOperationsCoordinator` non sono usati da
altri moduli di `ocor-runtime/src` (consumer: `test_ocor_dev_0040.py`, `test_ocor_dev_0041.py`,
`test_ocor_dev_rem_0022.py`). Il difetto non è oggi raggiungibile da un percorso di produzione del PoC,
ma la qualifica G6 di ingestion, replay e deduplica (`BA-07`, `FR-069`–`FR-075`) si appoggerebbe a
questo componente: per questo la remediation è dipendenza dei task G6, come chiesto dalla decisione.

## Remediation registrata

`OCOR-DEV-REM-0025`, primo identificativo libero verificato il 2026-10-12 su tutti i ref locali e
remoti, sui file di `~/.ocor-codex` e sulle PR (ultimo usato: `OCOR-DEV-REM-0024`). Ambito, criteri,
file attesi e dipendenze sono in `reports/development/EXECUTION_STATE.json` →
`remediation_status.REM_0025_C5_ISOLATION_SCOPED_DEDUP`. In sintesi: deduplica e stato di sequenza
indicizzati dal contesto di isolamento dell'envelope oltre che da chiave e aggregate, con test positivo
e negativo cross-tenant sul broker reale; replay nello stesso contesto invariato; nessun rilevamento
"stessa chiave / payload diverso". È dipendenza obbligatoria dei task G6 (`OCOR-DEV-0060` e
successivi); non blocca `OCOR-DEV-0049` né G5. Richiede la riqualifica di `OCOR-DEV-0040` (il cui
record più recente ha `c5/backbone.py` tra gli input) e, se cambia `c5/operations.py`, di
`OCOR-DEV-0041`, con record nuovi e supersession esplicita.

`E1=0`, `E2=0`, `Verified=0`, claim `NO-GO` e record sigillati invariati. Nessun `DEC-*`.

## Contesto originale

`c5/backbone.py` usa uno short-circuit «solo chiave» per il replay identico richiesto
da `test_a_replayed_idempotency_key_is_a_safe_no_op_...`. Rilevare il conflitto «stessa
chiave / payload diverso» (come fa C3) sarebbe un invariante più forte, oggi non
richiesto.

## Opzioni originali

1. **Lasciare invariato** — comportamento intenzionale documentato; nessun cambio.
2. **Irrobustire** — rilevare «stessa chiave / payload diverso» come conflitto (invariante
   più forte, da decidere in sede normativa).

## Raccomandazione originale

Raccomando l'opzione 1 (nessun intervento) in assenza di un requisito normativo che
imponga l'invariante più forte. L'opzione 2 è una variazione semantica e va confermata.
Adottata dalla decisione del 2026-10-05.

## Impatto

Originale: nessuno sul flusso previsto. Dopo la verifica: `OCOR-DEV-REM-0025` è dipendenza dei task
G6.

## Task bloccati

Nessuno da questa richiesta. `OCOR-DEV-REM-0025` blocca i task G6 fino alla sua chiusura verificata.
