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

## Osservazione REM-0028 — 2026-10-20T08:52:17.648364+00:00

La suite completa locale sul commit sorgente `d7369f7c5ef0c0c85c4a9ad4ca4b4170055fb8b2` termina PASS in 3831.461 secondi (63.86 minuti), {'errors': 0, 'failures': 0, 'skipped': 0, 'tests': 2377}. È una nuova osservazione della soglia di notifica di 60 minuti, aggiunta alla richiesta già aperta, senza riaprire domande risolte né bloccare la qualifica corrente. Il limite resta 75 minuti; nessun timeout, criterio, caso, immagine o gate è cambiato.

Il caso Helm usa il tick reale del CronJob ogni15min, come già fissato nel test. Una misura separata e completa del contributo causale dei singoli tratti è NOT_EXECUTED: non si attribuisce tutta la durata a una causa inferita. Il candidato resta soggetto a verifica indipendente e CI.

Raccomandazione invariata: mantenere il tetto vigente e valutare soltanto interventi autorizzati che preservino tutti i casi e i criteri. Nessun aumento del limite è eseguito o inferito. Questa notifica non richiede di interrompere il lavoro indipendente pronto.

Digest dei raw conservati (identificativi parametrizzati e credenziali non riprodotti):

- `full-exit.json`: `351b236a0de9b2aa28018bc24f71b9d2a4adc69fdfb478694f18905d640396f6`
- `full/campaign_result.json`: `e181de9ee535521ddecd7e179c05b120a0c2b13fc84954aee542d44b1c6b5399`
- `full/post_remediation_runtime.log`: `ec6ec19f92225d99c6cfc26eccef3fa172c9c0df69fd7d06f4cd49808c0c941e`
- `full/runtime_junit_post_approval.xml`: `18343de981ab668ed7ce17a01098c3399da366fefd9bc45516b51423fffbe55e`
- `full/kind-teardown-observations.json`: `8641aa03ec12bf7e9603e9588fbb691445e2602f8e88c5978a067ba89de394ee`

Implementatore della ripresa e della notifica: Codex/OpenAI. Linea storica delle riqualifiche: Claude Code/Anthropic. Verifier previsto: Cursor/Grok4.7 xAI, soltanto loop esterno, non avviato. Inputs intatti; E1=0,E2=0,Verified=0 e claim NO-GO invariati.

## Osservazione allineamento REM-0028 — 2026-10-21T15:20:45.450822+00:00

Nuova campagna completa dopo il merge non distruttivo di main e del fix osservatore REM-0019. Sorgente `0af64b5c492f7f4572d2fc11df06fe2793e964a1`, PASS in 3846.922 secondi (64.12 minuti), conteggi `{'errors': 0, 'failures': 0, 'skipped': 0, 'tests': 2377}`. La soglia di notifica di60min e superata; il tetto resta75min. Nessun test, timeout, cadenza, gate, immagine o criterio cambiato. Nessun conteggio trasferito dalla qualifica precedente; il GO storico rimane valido esclusivamente per il vecchioHEAD.

Notifica aggiunta alla richiesta gia aperta; raccomandazione invariata: mantenere i limiti e valutare soltanto interventi autorizzati che preservino tutti i casi. Non si attribuisce una causa senza misure; decomposizione causale completa NOT_EXECUTED. Nessuna chiusura o approvazione implicita, nessun blocco nuovo del lavoro indipendente.

Digest dei raw locali conservati (fixture e credenziali non riprodotte):

- `full-exit.json`: `69cc726e3953250af8c6b2eaf8813559643960d371c9d74a50c4bbef56ad2358`
- `full/campaign_result.json`: `6f7315981fe94730dcdf31fa76a96f081b71074c7be268706140ee9b75cfe7c0`
- `full/post_remediation_runtime.log`: `2ea35047921f26ef26332b75eacf521a81b67da95845869998ab4c1bc00912f1`
- `full/runtime_junit_post_approval.xml`: `a771ed5107c20df0e5aa87ceb9e10468bc7865f7e8524967f421e5a1882dbb38`
- `full/kind-teardown-observations.json`: `1202629037ff08d41273f05a6c390bec43f3f05a6e98055846b8ff2c5cfe3e87`

Implementatori dichiarati: Codex/OpenAI e Claude Code/Anthropic per la linea ereditata REM-0019. Verifier richiesto Cursor/Grok4.7/xAI, solo loop esterno, non avviato. Inputs,E1/E2/Verified eclaim invariati.

## Osservazione REM-0035, CI della revisione corrente — 2026-10-21T20:50:48.595097+00:00

Nuova campagna completa sul change set CI che dismette il checkout storico di 0049. Harness, codice runtime e 390 casi di 0049 invariati. Sorgente `cb411402de9bb7f0c64b5482025ccf221c1d2b9c`, PASS in 3717.123 secondi (61.95 minuti), conteggi `{'errors': 0, 'failures': 0, 'skipped': 0, 'tests': 2377}`. La soglia di notifica di60min e superata; il tetto resta75min. Nessun test, timeout, cadenza, gate, immagine o criterio cambiato. Nessun conteggio parziale o trasferito da altre esecuzioni; verifica indipendente ancora da richiedere sull’HEAD candidato esatto.

Notifica aggiunta alla richiesta gia aperta; raccomandazione invariata: mantenere i limiti e valutare soltanto interventi autorizzati che preservino tutti i casi. Non si attribuisce una causa senza misure; decomposizione causale completa NOT_EXECUTED. Nessuna chiusura o approvazione implicita, nessun blocco nuovo del lavoro indipendente.

Digest dei raw locali conservati (fixture e credenziali non riprodotte):

- `full-exit.json`: `eff2cc452fc8c415fdf1f87823942767c52bce4c68034f7cd43a7aa2d9759863`
- `full/campaign_result.json`: `f388f3d8e6d0fc70bcab4e52f066f75a40631fff46911faf5bb7cd6a8e6ad62e`
- `full/post_remediation_runtime.log`: `e6b88eb4f0e3b31ed82b9f512e06be874dc168944f3f9b91e8c8c6e3d5d40db5`
- `full/runtime_junit_post_approval.xml`: `b4506068ddb866b54413286797cbe0a19a1bfd230104523f25e53c79515396e4`
- `full/kind-teardown-observations.json`: `9d25ba62a7dfdde03ba9a9840d4f42e4914a821f29e60ae5765f7022cf340d1e`

Implementatori dichiarati: Codex/OpenAI e Claude Code/Anthropic per la linea ereditata REM-0019. Verifier richiesto Cursor/Grok4.7/xAI, solo loop esterno, non avviato. Inputs,E1/E2/Verified eclaim invariati.


## 2026-10-22T15:44:52.898138+00:00 — occorrenza REM-0023, full del verifier

- Richiesta `OCOR-DEV-REM-0023-73fa908d2a35-0`, HEAD `73fa908d2a3531463617fc786615cb1edb5918fc`. Verifier Cursor CLI/Grok4.7/xAI, implementatori Codex/OpenAI e linea storicaClaudeCode/Anthropic, contesti e processo separati. Verdetto GO senza finding; hash SHA256 `e2b124316ee2fa0a1348b932e25bf82a9f7ad1968f0b5b4b273845ddf66f16c0`.
- Misura: 3916.19s, 2482 PASS, zero fail/error/skip; unione JUnit esatta,0048=196,0049=390. Soglia consultiva3600s superata; tetto4500s rispettato e invariato. La full locale del candidato era3389.90s.
- Nessun aumento del tetto, nessuna selezione/esclusione, nessuna modifica a test/gate/harness. Notifica non bloccante accodata al PO; nessun replay richiesto per sola variabilità prestazionale. Qualunque futura variazione di limite resta riservata al PO.
- Opzioni: (1) presa d'atto mantenendo i limiti e la sorveglianza (raccomandata); (2) diagnosi prestazionale separata, senza variare casi, tecnologie o soglie. Nessuna approvazione implicita.
- Fonte riproducibile: verdetto esterno e relativi raw/campaign_result nel verify-env della richiesta; digest del verdetto sopra. Il branch di notifica conserva questo aggiornamento; nessun file di codice o record sigillato cambia. E1=0,E2=0,Verified=0 e claim invariati.


## Occorrenza OCOR-DEV-0058, repair_cycle 1 — 2026-10-23T12:54:47.919816+00:00

La campagna locale completa sul commit `657e5b450e3505d15070017530bd6e41143eab90` termina con **2786 PASS, zero failure/error/skip**. Durata **3648.624688 s**, oltre la soglia informativa di 3600 s e sotto il tetto invariato di 4500 s. `po_decision_required=true` conservato; nessun caso, comando, timer, gate o limite modificato e nessun rerun per ridurre la durata. Bootstrap: `scripts/bootstrap_ci_environment.py --execute --timeout 600`, profilo versionato e SVID control-plane. Unione JUnit esatta; Helm PASS; rimozione kind v2 osservata, un evento di rimozione e zero rifiuti. Teardown finale PASS e zero risorse possedute residue.

Il verifier del candidato ciclo 0, `OCOR-DEV-0058-e5f3729a5219-0`, aveva riprodotto la full in 3645.60 s, 2772 PASS; il suo NO_GO resta storico per VF-001/VF-002, non per durata. Nessun conteggio di quel run e trasferito nella qualifica nuova.

Raw SHA256 della nuova occorrenza:

- `full/campaign_result.json`: `cffe0528cbca577545e9099ad4a2d032d42c5be70bc4bce1398f918b19c1696d`.
- `full/runtime_junit_post_approval.xml`: `27f01e6bf4d867bc8d9fa65431384b563983309bfe9d370aac26a679788bad4e`.
- `full/post_remediation_runtime.log`: `0fd12f2c8a9693656586c4dadda55c192180bda7943ebba1c3fc1f89ff3bbe80`.
- `full/kind-teardown-observations.json`: `1442b25a2bf2a3c913848ae43ac47a3ada6665c802089f40148035aff61aa57c`.
- `exact-junit-union.json`: `5a420eaa8e16e46bfdb16e821b451a7c643a7a2b2b8d35cf05a224e605e68ec1`.

Verdetto esterno storico SHA256: `5fd887db6e0d10d2d072ab6d2e410a75aab5588fe8fcf1cc42a3e8fce0198b9c`.

Raccomandazione invariata: mantenere il tetto75min e la notifica oltre60min; caratterizzare le durate senza modifiche esecutive. La notifica non blocca la verifica indipendente di0058. Il candidato resta senza sigillo e senza PR fino al GO esterno. Nessuna allowlist estesa; nessun merge di questa sola richiesta e necessario prima della disposition. Inputs intatti; E1=0, E2=0, Verified=0 e claim NO-GO invariati.


## 2026-10-23T20:45:27.222913+00:00 — OCOR-DEV-0058 ciclo 2: full locale e verifica indipendente

- `repair2-full-local`: HEAD `bca0773ef989f65036cb593d446f139fb59c76dd`, durata 4108.628862 s, 2820 PASS e zero failure/error/skip; SHA256 campaign_result `9085d4bc0062384cd55cff5a28ab577aeb8a9271421d4649bb4835572037b70f`.
- `verifier-repair2-full`: HEAD `b0fbb184f51f15ef777c5ead16aba3f362d28db8`, durata 4403.665523 s, 2820 PASS e zero failure/error/skip; SHA256 campaign_result `fffa6d350d5272d5b6261f0b1f51bd78b86b45eb4a770bd2f016d305e6f1639f`.
- Verdetto `OCOR-DEV-0058-b0fbb184f51f-2`: GO_FOR_EVIDENCE_SEAL, nessun finding o NOT_EXECUTED; SHA256 `6f503b6ab183d32c3a203c6117b059687e8b5f6e7c4e4ff722d2b971611f44a6`. Implementatori Codex/OpenAI e Claude Code/Anthropic; verifier Cursor CLI/grok-4.7-high/xAI, processo e contesto separati. Il precedente verifier ciclo 1 aveva misurato 3899.85 s (verdetto storico NO_GO per audit binding, non per durata).
- Bootstrap standard `scripts/bootstrap_ci_environment.py --execute --timeout 600`, profilo di risorse e SVID versionati; unione JUnit esatta, rimozione kind v2 provata, zero OOM/restart, teardown senza residui secondo i record originali. Soglia informativa 3600 s superata, tetto 4500 s rispettato e invariato. Nessuna campagna ripetuta per ridurre la durata. Nessun conteggio trasferito fra run.
- Raccomandazione e opzioni invariate: presa d’atto mantenendo i limiti, oppure diagnosi prestazionale separata. La causa prestazionale non e stabilita da questi soli tempi. Notifica non bloccante; nessuna estensione dell’allowlist, nessun merge della richiesta senza disposition, nessun cambio a codice, test, gate o record sigillati. E1=0, E2=0, Verified=0 e claim NO-GO invariati.


## Occorrenza OCOR-DEV-0059 — full del verifier ciclo 0 (2026-10-24)

Il verifier Cursor/Grok xAI ha osservato 3002 casi, zero failure/error/skip,
con durata 4238.05 s: superiore alla soglia di notifica di 3600 s, inferiore
al tetto invariato di 4500 s. La full e PASS; il task ha verdetto NO_GO per
VF-001/VF-002 (stop epoch nel restore e inventario), indipendenti dalla durata.
Nessun conteggio di quel run si trasferisce alla riparazione 1.

- Sorgente: `~/.ocor-codex/verdicts/OCOR-DEV-0059-e226fc7d127c-0.json`.
- Head verificato: `e226fc7d127c3b660e2ea7c82864525577ecaf2d`.
- SHA256 del verdetto: `4831d3e4ce2eeff5fe5b188f6f391863492664804ef5decb3d91c8cad2e301ba`.
- Bootstrap: `scripts/bootstrap_ci_environment.py --execute --timeout 600`,
  profilo versionato, controllo SVID; stack pinned.
- Arresto al primo OOM/restart e tetto 75 minuti invariati; nessuno skip.

Richiesta non bloccante: presa d atto delle misure sotto la richiesta esistente
REM-0033-LOCAL-FULL-DURATION. Nessuna estensione del limite o deroga proposta;
nessun task bloccato. Rimangono E1=0, E2=0, zero requisiti Verified e claim NO-GO.


## Riparazione 1 — soglia osservata durante il run

2026-10-24T03:46:34.849931+00:00: la full sul commit `5abf97104498d54844a70035056f47a017dd82f7` ha superato 3600 s ed e ancora IN_PROGRESS. Nessun esito qualificante anticipato. Il tetto resta 4500 s; nessuna modifica a timer, test o gate. Il risultato finale e i digest saranno aggiunti alla conclusione del run.


## Riparazione 1 — risultato finale

Full PASS sul commit `5abf97104498d54844a70035056f47a017dd82f7`: 3043 casi, zero failure, error o skip; durata esatta 4076.349030048994 s. Unione JUnit esatta PASS (3043 raccolti/eseguiti, nessun mancante/duplicato/extra).

SHA256 `campaign_result.json`: `dca512129824c5befbd3d415983a5905f502b232e2c33c40e661d6c37e47fdda`. Sorgente locale: `~/.ocor-codex/ocor-dev-0059/repair1/full/campaign_result.json`; raw pubblicato con l evidenza candidata di OCOR-DEV-0059. Teardown standard PASS, zero residui posseduti; nessun OOM o restart. Il superamento dei 60 minuti resta una notifica non bloccante; tetto di 75 minuti invariato. Nessuna nuova soglia proposta, nessun conteggio trasferito da altri run.
