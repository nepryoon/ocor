# NCP-U11-ADMISSION-QUOTA-WORLDS

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0059`
(NCP-U11 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, memoria governata; branch
`governed/ocor-dev-rem-0059-ncp-u11-governed-memory`, head `89867abfa7e6afdcd919efcb31a1192d43bc9016`), il ciclo di
riparazione 1 del verdetto `OCOR-DEV-REM-0059-3425a01a39c1-0` (finding `VF-001`) e la voce `NCR-MEMORY-002` di
`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`. Aperta secondo il punto 1 della decisione
`NCP-U11-ADMISSION-QUOTA-COMPOSITION (2026-11-09)` («Ciò che l'opzione non descrive resta da decidere: fermati e apri
una nuova decision request invece di estenderla»). Implementatore: Claude Code (Anthropic), implementatore di riserva.

## Contesto

- La decisione `NCP-U11-ADMISSION-QUOTA-COMPOSITION (2026-11-09)` ha scelto le opzioni A1 e B1 della richiesta omonima
  (branch `governed/decision-request-ncp-u11-admission-quota-composition`, commit
  `f5f18e1581397b37601ee3f8b91cd5f666c56a86`). L'opzione A1 descrive: `admitMemory` rifiuta prima di qualsiasi
  scrittura senza un'autorità di quota valida; `MemoryAdmissionQuota` reale nei mondi di 0051, 0052, 0054 e 0055 «sul
  proprio metadata store PostgreSQL e ledger, con `t59.PostgresSerializedQuota`»; port di quota di test esplicito nei
  mondi di sola ammissione di 0050 e REM-0023; estensione del guard REM-0023 per 0054 e 0055 limitata a testi fissati.
- L'attuazione ha trovato tre fatti che l'opzione A1 non descrive. Li ha misurati con un prototipo locale, non
  committato: il rifiuto fail-closed in `ocor-runtime/src/ocor_runtime/memory/model.py` (passo 11 di `admit`) più la
  composizione di A1 nei nove punti di costruzione.
  1. **0051 non ha un metadata store.** `ocor-runtime/tests/tasks/test_ocor_dev_0051.py` riga 220, classe `Admission`
     («The real admission service over one ledger shared by every compartment»), crea il servizio con il solo ledger.
     I mondi la compongono come campo `default_factory`, prima e indipendentemente dal metadata store: `UnitWorld`
     (riga 489, `MemMetadata` in memoria) e lo stack reale (righe 890-935, `PostgresStores`). In quattro punti viene usata
     da sola, senza alcuno store (righe 533, 541, 586 e 619). `MemoryAdmissionQuota`
     (`ocor-runtime/src/ocor_runtime/memory/operations.py` righe 580-607) richiede il metadata store su cui la partizione
     viene committata, che `Admission` non conosce.
  2. **I mondi di 0052, 0054 e 0055 esistono anche senza PostgreSQL.** Le classi `World` di 0052 (riga 274), `CWorld` di
     0054 (riga 208) e `World` di 0055 (riga 171, sottoclasse di `World` di 0053) sono istanziate sia su `PostgresStores`
     sia su `MemMetadata` in memoria: `unit_world()` di 0052 (riga 450, 12 usi), 0053 (riga 455, 21 usi), 0054 (riga 338)
     e 0055 (riga 287, 10 usi). Su un metadata in memoria non esiste un DSN per `t59.PostgresSerializedQuota`.
  3. **Doppio hold della serializzazione e costo.** Con la quota reale composta nei mondi di 0052 e 0055, i writer che
     tengono già la serializzazione della partizione e ammettono attraverso `w.admission` tentano un secondo hold sullo
     stesso lock advisory PostgreSQL da un'altra connessione. Dopo il `lock_timeout` di 3 s la risposta è
     `CONTROL_PLANE_UNAVAILABLE`/`QUOTA_SERIALIZATION_UNAVAILABLE`. È il caso di `MemoryQuotaWriter` nei test sigillati
     `ocor-runtime/tests/tasks/test_ocor_dev_0059.py`
     (`test_quota_writer_rejects_the_actual_third_item_without_appending_or_indexing[True]`,
     `test_quota_writer_allows_exact_replay_and_correction_at_capacity[True]`,
     `test_real_two_quota_writers_share_the_same_serialization_boundary`,
     `test_real_serialization_lock_timeout_is_fail_closed`) e della campagna
     `ocor-runtime/tests/conformance/fgm/test_fgm_01_10.py` (`test_fgm_02_positive_…` e `test_fgm_02_negative_…`).
     La docstring di `MemoryAdmissionQuota` (`operations.py` righe 594-596) prescrive già che un writer che tiene la
     serializzazione non componga questo port sullo stesso dominio. Inoltre la suite dei consumatori della memoria e
     del modulo dell'unità passa da 366 s (1380 casi, head `bf8f582`) a 2365 s: `test_ocor_dev_rem_0020.py` da 54 s a
     1102 s, il modulo dell'unità da 28 s a 658 s, `test_ocor_dev_0053.py` da 37 s a 279 s. Il tempo va nella scansione
     della partizione a ogni ammissione e nelle attese del lock.
- Con il port di test esplicito in tutti i mondi sigillati (variante misurata con lo stesso prototipo) i casi che usano
  la quota reale restano nel modulo dell'unità
  `ocor-runtime/tests/tasks/test_ocor_dev_rem_0059.py`: ammissione entro e oltre quota con rifiuto auditato,
  indisponibilità della serializzazione, consolidamento contato all'ammissione, versioni ammesse e non ancora committate,
  inventario del ledger, rilascio del hold. A questi si aggiungono, con il fail-closed, i nuovi casi di ammissione e di
  consolidamento senza autorità di quota. I dati della variante sono nel paragrafo «Misure».
- Restano fermi, perché A1 li descrive: il rifiuto fail-closed di `admitMemory`, il port di test esplicito di 0050 e
  REM-0023, l'estensione del guard REM-0023 per 0054 e 0055 a testi fissati con casi negativi, e l'estensione B1 delle
  iterazioni. Iterazione corrente: 6 di stima 3, estensione fino alla tredicesima.

## Misure

Suite dei consumatori della memoria più il modulo dell'unità, sullo stesso PostgreSQL di sviluppo con i contenitori Qdrant
e OpenBao dei test. Il prototipo non è committato; il guard REM-0023 non è ancora esteso in nessuna delle due varianti.

| Variante | Esito | Durata |
|---|---|---|
| Head `bf8f582`, senza fail-closed | 1380 passed, 0 falliti | 366 s |
| Fail-closed e composizione di A1 come descritta (quota reale in 0052, 0054 e 0055 su PostgreSQL; `t59.SerializedQuota` sul metadata in memoria; port in 0050, 0051 e REM-0023) | 1379 passed; 9 falliti: 3 del guard REM-0023 non ancora esteso, 2 di FGM-02 e 4 di 0059 con `QUOTA_SERIALIZATION_UNAVAILABLE` | 2365 s |
| Fail-closed e port di test esplicito in tutti i mondi sigillati | 1385 passed; 3 falliti, solo quelli del guard REM-0023 non ancora esteso | 371 s |

## Opzioni

1. **Port di quota di test esplicito in tutti i mondi sigillati, quota reale nel modulo dell'unità (raccomandata).**
   La classe `Admission` di 0051 e le classi `World` di 0052 (con la sottoclasse di 0053), `CWorld` di 0054 e `World`
   di 0055, in ogni istanza (anche `Backends.fresh` di 0054 e `test_lifecycle_state_is_durable_across_fresh_adapters` di
   0055), compongono lo stesso port di quota di test esplicito di 0050 e REM-0023: ammette e registra ogni
   `admission_hold`, senza nuovi backend. Sostituisce, per questi mondi, la frase di A1 sulla `MemoryAdmissionQuota`
   reale. `MemoryAdmissionQuota` reale con `t59.PostgresSerializedQuota` resta composta nei test del modulo dell'unità
   (elenco del contesto). Il guard REM-0023 ammette per 0054 e 0055 soltanto `quota=` con il testo fissato del port.
   Adattamenti del caso 3 del punto 5 del piano, con il confronto dell'albero sintattico. Effetto: nessun percorso
   ammette senza quota; nessun esito sigillato cambia; tempi dei consumatori invariati; i consumatori sigillati non
   esercitano la quota reale, come oggi.
2. **Quota reale dove il mondo ha un metadata store, con serializzazione secondo il metadata, e port nei casi
   restanti.** I mondi su `PostgresStores` compongono `MemoryAdmissionQuota` con `t59.PostgresSerializedQuota`; gli
   stessi mondi su `MemMetadata` la compongono con la serializzazione di test in-process `t59.SerializedQuota`. La classe
   `Admission` di 0051 compone il port di test esplicito. I mondi dei writer che tengono già la serializzazione (0059 e
   la campagna FGM-02) compongono per l'ammissione del writer il port di test esplicito, come prescrive la docstring di
   `MemoryAdmissionQuota`. Il guard REM-0023 ammette per 0054 e 0055 i testi fissati delle due composizioni. Effetto:
   quota reale nei consumatori 0052-0055. Costo misurato dei consumatori: circa sei volte più lento. Adattamenti anche
   in 0059 e nella campagna FGM, oltre ai nove punti.

## Raccomandazione

Opzione 1. Realizza ciò che A1 chiede al servizio (nessuna ammissione senza un'autorità di quota valida) e lascia la
prova della quota reale ai test dell'unità, che la esercitano su PostgreSQL, Qdrant e OpenBao reali, consolidamento
compreso. Non tocca 0059 né la campagna FGM, non cambia alcun esito sigillato e non sposta i tempi della suite.
L'opzione 2 richiede adattamenti in altri due moduli sigillati e una scelta di serializzazione che la richiesta
precedente non descriveva, e moltiplica per sei il tempo dei consumatori.

## Impatto e lavoro bloccato

- Bloccati in attesa della decisione: il GREEN di `VF-001` e il resto del ciclo di riparazione 1 di
  `OCOR-DEV-REM-0059`.
- Non bloccati: `VF-002`, già corretto sul branch dell'unità.
- Riqualifiche: l'insieme delle undici riqualifiche di sola regressione resta lo stesso con l'opzione 1 (0050, 0051,
  0052, 0054, 0055 e REM-0023 vi sono già). L'opzione 2 aggiunge 0059 e i record di `test_fgm_01_10.py`, se ne sono
  input.
- Nessun nuovo `DEC-*`; ADD, LLD, contratti, schemi, registri normativi, limiti e claim invariati
  (`E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`).
