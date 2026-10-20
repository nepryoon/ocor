# REM-0033-LOCAL-FULL-DURATION

Stato: `OPEN_PO_DECISION_REQUIRED`. Data: 2026-10-15. Autore: Codex.

## Contesto e misure

Notifica richiesta da `REM-0017-CI-CAMPAIGN-BUDGET` (2026-10-07): una suite completa locale oltre 60 minuti richiede una decision request; il tetto vigente resta 75 minuti.

La ripetizione integrale autorizzata da `HOST-REBOOT-RESUME-ITER27`, sullo stesso HEAD `3c8f2eba711cac1a180ae36df452dc0707efe205`, ha concluso con **2323 PASS, zero failure/error/skip**, durata del supervisore **3724.311 s (62.072 min)**, inferiore a 4500 s. `po_decision_required=true` è stato conservato. Il caso Helm è PASS; rimozione `OWNED_KIND_TEARDOWN_OBSERVED`, zero rifiuti del supervisore. Nessun test, comando, timer, cap o gate è stato alterato.

Durate JUnit aggregate per i cinque moduli più lunghi (comprendono setup/teardown imputati ai casi; non sono una misura isolata della sola logica):

- `tests.tasks.test_ocor_dev_0049`: 2692.099 s.
- `tests.tasks.test_ocor_dev_rem_0026`: 164.847 s.
- `tests.tasks.test_ocor_dev_0048`: 125.657 s.
- `tests.tasks.test_ocor_dev_rem_0025`: 121.765 s.
- `tests.tasks.test_ocor_dev_rem_0020`: 92.670 s.

Il caso Helm attende il tick del CronJob approvato ogni 15 minuti per sovrapporre backup manuale e schedulato; la durata dipende anche dalla fase del tick all'avvio. Questa osservazione non dimostra da sola la causa dell'intera durata.

Raw SHA256:

- `full/campaign_result.json`: `4997ff3bbfa63b55a2e5bb0e6a385ab8b3b312d2d7815d7ec409d3c3445b9235`.
- `full/runtime_junit_post_approval.xml`: `b7fc8f20a8d237b6ed1ccf8a5b85eb675980d1e0793554cd69ffe6ff551a0c6a`.
- `full/post_remediation_runtime.log`: `8cd0b1c422deb00df7eadc6d18bcf77e9cf7d293f92d9a6a7e29c85932d89beb`.
- `full-exit.json`: `812e42df971aea60966fd9fd1271364b9001fb006c4658acfe8bdf51c203545d`.

Il record candidato di REM-0033 raccoglie gli stessi raw e le misure sotto `reports/assurance/OCOR-DEV-REM-0033-RCCAD/OCOR-DEV-REM-0033.json` e `.log`; il JUnit originale resta nel checkpoint locale della campagna. I tentativi precedenti e l'interruzione per reboot restano distinti e non trasferiscono conteggi.

## Opzioni e raccomandazione

1. Mantenere il tetto locale di 75 minuti e la notifica oltre 60, conservando queste misure come caratterizzazione della suite attuale; nessuna modifica esecutiva. Raccomandata per questa occorrenza, che è verde ed entro il tetto.
2. Richiedere un'analisi separata dei tempi prima di eventuali ottimizzazioni governate, con ambito e prove approvati; nessuna ottimizzazione, partizione locale o variazione di schedulazione è introdotta da questa richiesta.

Nessuna richiesta di aumento del tetto. Nessun tentativo aggiuntivo per ridurre la durata misurata.

## Impatto

La notifica non rende FAIL una suite PASS sotto 75 minuti e non blocca la qualifica di REM-0033: restano necessari 13 check obbligatori verdi sull'HEAD esatto, parte Helm accettata e verifica indipendente Grok 4.7 via Cursor. Non modifica l'ordine della coda. Questo branch contiene soltanto la richiesta; nessun merge è richiesto prima della disposition e nessuna allowlist viene estesa qui.

Inputs intatti; E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC e Production NO-GO invariati. Nessun nuovo DEC, nessuna chiusura di rischio normativo.


## Occorrenza REM-0019, repair_cycle 2 — 2026-10-20T02:51:15.130458+00:00

La nuova campagna locale completa di REM-0019, sul sorgente pulito
`dcd3c233765a5d7a2c96564103828798df37e70a`, conclude con **2323 PASS, zero failure/error/skip**.
Durata del supervisore **3676.085646 s (61.268 min)**;
`po_decision_required=true` conservato, tetto75min invariato. Nessun nuovo tentativo
per ridurre la misura. Runtime/test/harness/workflow/lock non modificati.

Il caso Helm e PASS: backup manuale concorrente e backup schedulato entrambi riusciti;
rimozione `OWNED_KIND_TEARDOWN_OBSERVED`, zero rifiuti del supervisore.
L'unico evento unhealthy osservato e classificato `EXPECTED_READINESS_GATE` per
ocor-ops/RESTORE_UNTESTED: comportamento progettato, nessun relay unhealthy.

Durate JUnit aggregate, comprensive di setup/teardown imputati ai casi:

- `tests.tasks.test_ocor_dev_0049`: 2657.156 s.
- `tests.tasks.test_ocor_dev_rem_0026`: 160.287 s.
- `tests.tasks.test_ocor_dev_0048`: 132.596 s.
- `tests.tasks.test_ocor_dev_rem_0025`: 117.526 s.
- `tests.tasks.test_ocor_dev_rem_0020`: 91.231 s.

Raw SHA256 della nuova occorrenza:

- `full/campaign_result.json`: `bdc052bdc14bb3e6fa9e5bbdc18b366307423b2bdc8985078e63817dfe553c5c`.
- `full/runtime_junit_post_approval.xml`: `35b40970b71d4343bfa2305ea60c05d319eea3b2969d00f36c70aa082af87094`.
- `full/post_remediation_runtime.log`: `7267c096baf6bb98516577d35d31f1f10dd6d7bb714cd6c420b2b02979dc6b4a`.
- `full/kind-teardown-observations.json`: `9b81ad751daff8bb312ac6e0d2f98d29743c2d8bd855e75d9a5d8f5a50217a06`.
- `full-exit.json`: `7a383e762bfdffd58f19630b79da186f16dca244596becee7630914f60cf0f69`.

Nuova evidenza candidata: `reports/assurance/OCOR-DEV-REM-0019-RCCAD/integration-20261020.json`
e relativo `.log`, sul branch `governed/ocor-dev-rem-0019-evidence-stage`.
Gli identificativi parametrizzati con fixture credenziali sono pubblicati solo come digest;
originali privati e trasformazione esplicita content-addressed.

Questa aggiunta aggiorna la medesima domanda gia aperta: opzioni e raccomandazione
restano invariate. Notifica non bloccante della qualifica corrente sotto75min;
nessuna modifica a criteri, timer, cap, gate o coda. Restano necessari GO esterno e
13check obbligatori verdi sull'HEAD esatto. Implementatori dichiarati: Codex/OpenAI
(questa riparazione e qualifica), Claude Code/Anthropic (contributi storici conservati);
verifier previsto Cursor/Grok4.7/xAI, non avviato dall'implementatore.

E1=0,E2=0,Verified=0 e claimNO-GO invariati. Questa richiesta resta
`OPEN_PO_DECISION_REQUIRED`, blocks=[]; nessun merge prima della disposition.
