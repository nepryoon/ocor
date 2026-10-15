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
