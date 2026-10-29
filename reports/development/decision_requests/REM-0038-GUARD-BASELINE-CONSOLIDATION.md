# REM-0038-GUARD-BASELINE-CONSOLIDATION

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. È la decision request separata prevista
dalla condizione c di `REM-0038-CAMPAIGN-GUARD-ADMISSION (2026-10-26)`, dovuta dopo
l'integrazione di `OCOR-DEV-REM-0041` (PR #403, merge `82b71d0`). Le opzioni 1 e 2
cambiano lo standard del guard d'invarianza, quindi la decisione è normativa. Fino alla
decisione le baseline `9b4d3be` e `7cd5f7a` restano invariate e nessun file è stato
modificato. Nessuna variazione di test, limiti, timeout, finestre, cadenze, timer,
partizioni, selezione dei casi o gate. Non blocca `OCOR-DEV-0060` né `0062`–`0064`.

## Contesto

Il guard d'invarianza di `reports/tests/test_kind_teardown_observation.py` (sha256
`e8b9eb37bdb25bd7e50c23265559bd19e85cbd43595b98c6fc09c7b481caeaa2` su `origin/main`
`e92bdef52e6cc1b0b46f581557adbcba76cde78f`) dimostra che il supervisore di campagna
(`scripts/run_qualifying_campaign.py`), l'osservatore (`scripts/observe_kind_teardown.py`)
e tutti i workflow non sono cambiati, salvo differenze autorizzate, rispetto a due
baseline storiche:

- `bootstrap_probe_proof`: AST dell'intero modulo di campagna e tutti i workflow contro
  `9b4d3be` (ultimo `main` qualificato, `CI-0049-KIND-BOOTSTRAP-EXEC-PROBE`); costanti
  `WINDOW_SECONDS`, `POLL_SECONDS`, `SAMPLE_SECONDS`, `KIND_BINARY`; timeout delle sonde
  `{10}`.
- `observation_only_proof`: AST delle funzioni della baseline (escluso
  `observe_health_event`) e delle assegnazioni di modulo contro `7cd5f7a`, con la
  trasformazione `DiagnosticsOnly`; tutti i workflow.

Prima del confronto il guard applica oggi questa catena di normalizzazioni esatte:

| Strato | Funzione | Origine |
|---|---|---|
| 1 | `move_scope_gate_before_provisioning` (solo contro `7cd5f7a`) | riparazione CI dell'integrazione di 0049 |
| 2 | pin `beab1b4` e N=5 in `assert_governed_workflow` (solo contro `7cd5f7a`) | `REM-0017-CI-0049-RELAY-PROBE-REMEDIATION (2026-10-14)` |
| 3 | `retire_integrated_0049_pin` | `CANDIDATE-INTEGRATION-STATE-FREEZE (2026-10-14)` |
| 4 | `normalize_rem0034_secret_scanner` (blocco con digest) | decisione del PO del 2026-10-15 |
| 5 | `normalize_rem0038_campaign`, `normalize_rem0038_workflow` | `REM-0038-CAMPAIGN-GUARD-ADMISSION`, opzione 1 |
| 6 | `normalize_rem0042_campaign` | `LOCAL-FULL-SUITE-CAP-90-AMENDMENT`, punto 3 |
| 7 | `normalize_rem0037_workflow` | `LOCAL-SUITE-SPLIT-REACTIVATION`, punto 6 |
| — | `DropExport` (`bootstrap_recoveries`), `DiagnosticsOnly` (`run_probe`, tre campi diagnostici) | `CI-0049-KIND-BOOTSTRAP-EXEC-PROBE`, REM-0017 |

`OCOR-DEV-REM-0039`, `0040` e `0041` non hanno aggiunto normalizzazioni: il loro diff
non tocca i percorsi sorvegliati. L'ultima modifica a workflow, supervisore, osservatore o
guard su `origin/main` è il merge di REM-0037 `969d2d2` (PR #385); dopo di esso, fino a
`e92bdef`, la storia first-parent non tocca quei percorsi.

## Fatti

Tutti ottenuti in sola lettura, in un worktree staccato a `e92bdef`, con Python 3.12.11 del
lock. Script di prova fuori dal repository
(`~/.ocor-codex/dr-rem0038-consolidation/equivalence.py`, sha256
`42787c9e020f6bd9624433f47481128bae658cd7dcc48fcb41ce170074a9286c`); esito JSON
(`equivalence.json`, sha256
`ea005446ad600a79091b54d39cf7d80c265b4b93e23aabdad7a208af96f4d153`).

1. **Guard attuale verde.** `pytest reports/tests/test_kind_teardown_observation.py`:
   48 passed, 83 subtests passed.
2. **Baseline candidata `B` = `82b71d0db410bcdb8124e8ec8a8235631ecfa1fa`** (merge
   dell'integrazione di REM-0041, PR #403 con 13/13 check obbligatori verdi sull'HEAD
   esatto `b5db94d`). I 10 file sorvegliati (8 workflow, supervisore, osservatore)
   hanno a `B` e a `e92bdef` contenuto identico: zero differenze.
3. **Catena storica su `B`.** I due proof attuali, eseguiti con il contenuto di `B` al
   posto dell'albero di lavoro, passano: la catena 1–7 porta `B` esattamente a
   `9b4d3be` e a `7cd5f7a`.
4. **Osservatore.** `WINDOW_SECONDS=30.0`, `POLL_SECONDS=0.5`, `SAMPLE_SECONDS=0.2` e
   `KIND_BINARY` hanno lo stesso valore a `9b4d3be`, `7cd5f7a` e `B`. Spostare su `B` il
   riferimento delle costanti è quindi esattamente equivalente; il controllo dei timeout
   `{10}` non dipende dalla baseline.
5. **Casi negativi.** I 34 casi negativi del modulo attuale (8 + 5 di REM-0038, 12 di
   REM-0042, 9 di REM-0037), riprodotti testualmente, sono rifiutati da tutti e tre i
   guard confrontati: `G_old` (attuale) 34/34, `G_bytes` (opzione 1) 34/34, `G_ast`
   (opzione 2) 34/34.
6. **Divergenze dimostrate** (sonde aggiuntive, non presenti nel modulo):

   | Sonda | `G_old` | `G_bytes` | `G_ast` |
   |---|---|---|---|
   | costante `MANDATORY_CONTAINERS` spostata in fondo al modulo | accetta | rifiuta | rifiuta |
   | due segnaposto di REM-0038 spostati dopo il comando di rendering, fuori dal prefisso d'ambiente | accetta | rifiuta | rifiuta |
   | commento della costante di REM-0038 riformulato | rifiuta | rifiuta | accetta |
   | commento aggiunto in coda al modulo di campagna | accetta | rifiuta | accetta |

   Le normalizzazioni a sostituzione unica verificano il conteggio ma non la posizione:
   la stessa riga in un altro punto viene rimossa e il confronto passa. È una lacuna di
   `G_old`, non un difetto di un candidato integrato.
7. **Relazione fra gli insiemi accettati.** `G_old` è funzione del solo contenuto dei
   file e accetta `B` (fatto 3). `G_bytes` accetta esclusivamente il contenuto di `B`,
   quindi `G_bytes ⊆ G_old`, e l'inclusione è stretta (prime due sonde). `G_ast` non è
   confrontabile con `G_old`: è più severo sulle ricollocazioni e più permissivo sui
   commenti (terza sonda).
8. **Costo d'evidenza.** Una modifica di prova a `test_kind_teardown_observation.py`
   (poi annullata) fa fallire `validate_evidence_input_drift.py` su `OCOR-DEV-0005` e
   `OCOR-DEV-0050`. Qualunque opzione che cambi il modulo richiede quindi le riqualifiche
   di sola regressione di 0005 e 0050 (più 0082 se cambia l'allowlist del piano), come
   per REM-0038, REM-0042 e REM-0037.

## Opzioni

- **Opzione 1: baseline unica `B` con identità di byte.** In
  `reports/tests/test_kind_teardown_observation.py`:
  - un solo proof corrente: ogni workflow e il supervisore devono essere byte-identici a
    `B`; un workflow nuovo, assente a `B`, fallisce. Le costanti dell'osservatore si
    confrontano con `B` e i timeout delle sonde restano `{10}`;
  - le normalizzazioni 1–7 e le trasformazioni `DropExport`/`DiagnosticsOnly` non si
    applicano più all'albero di lavoro. Restano nel modulo, congelate, in un test storico
    che le esegue sul contenuto di `git show B:<percorso>` e prova a ogni esecuzione che
    `B` si riduce esattamente a `9b4d3be` e a `7cd5f7a`. La storia resta dimostrabile e
    non cresce più;
  - i 34 casi negativi restano, ridiretti sul proof corrente, insieme alle sonde di
    ricollocazione del fatto 6 come nuovi casi negativi;
  - ogni differenza futura richiede una nuova normalizzazione esatta su `B` autorizzata
    da una decisione del PO (schema della condizione a), oppure un nuovo consolidamento
    deciso dal PO.

  Pro: chiude la lacuna di ricollocazione; inclusione stretta dimostrata
  (`G_bytes ⊆ G_old`); catena corrente vuota, quindi la prossima ammissione non deve
  comporsi con altre sette e non crea conflitti d'ordine fra normalizzazioni (come
  nell'allineamento REM-0038/REM-0042). Contro: anche una modifica ai soli commenti del
  supervisore richiede una decisione; serve un change set governato con verifica esterna
  e le riqualifiche del fatto 8.
- **Opzione 2: baseline unica `B` con AST del supervisore.** Come l'opzione 1, ma il
  supervisore si confronta con l'AST dell'intero modulo a `B` (docstring incluse,
  commenti esclusi); workflow byte-identici. Pro: le modifiche ai soli commenti non
  richiedono decisioni. Contro: non è un sottoinsieme di `G_old`, perché accetta la
  riformulazione dei commenti che oggi le normalizzazioni esatte rifiutano. Allenta
  quindi un controllo esistente, anche se solo su testo non eseguito.
- **Opzione 3: nessun consolidamento ora.** Baseline e catena invariate. Si rivaluta
  alla prossima differenza autorizzata dei percorsi sorvegliati, o dopo
  l'integrazione di `OCOR-DEV-0060`. Pro: zero modifiche, nessuna riqualifica. Contro: la
  lacuna di ricollocazione resta; la catena di sette strati più due trasformazioni cresce
  a ogni ammissione.

## Raccomandazione

**Opzione 1.** È l'unica che riduce la catena senza allentare alcun controllo: accetta
un sottoinsieme stretto di ciò che il guard accetta oggi, conserva la prova storica
contro `9b4d3be` e `7cd5f7a` come test congelato e aggiunge come casi negativi le due
ricollocazioni oggi accettate. Esecuzione proposta: change set governato
`OCOR-DEV-REM-*` (primo identificativo libero), RED (le sonde di ricollocazione falliscono
sul guard attuale) e poi GREEN, `PRE-CAMPAIGN-GATE`, revisione preventiva, riqualifiche
di sola regressione di 0005 e 0050 (e 0082 se serve), verifica esterna ordinaria di un
fornitore diverso da ogni implementatore, sigillo, CI sull'HEAD esatto e merge. Nessun
cambiamento a supervisore, osservatore o workflow. Da eseguire dopo l'unità in corso al
momento della decisione, senza precedenza su `OCOR-DEV-0060`, salvo diversa
indicazione del PO.

## Impatto

- Non blocca alcun task: `OCOR-DEV-0060` e `0062`–`0064` proseguono. Una differenza
  futura dei percorsi sorvegliati non coperta dalla condizione a richiede comunque una
  decision request, qualunque opzione si scelga.
- Con le opzioni 1 e 2 cambiano soltanto `reports/tests/test_kind_teardown_observation.py`
  e le riqualifiche di sola regressione; nessun record sigillato viene modificato.
- Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e
  Production `NO-GO`. Nessun nuovo `DEC-*`: `CC-OCOR-DELIVERY-COMPLETION` non attiva
  l'eccezione di baseline promotion di `AGENTS.md`.
