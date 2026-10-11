# Escalation record — OCOR-DEV-0049 (repair budget exhausted)

- **Status corrente**: `BLOCKED_REPAIR_BUDGET_EXHAUSTED` (ciclo 7 concluso, NO_GO; loop CONTINUE)
- **Disposition storica ciclo 2**: `BLOCKED_REPAIR_BUDGET_EXHAUSTED`, superseded dalla decisione PO `OCOR-DEV-0049-REPAIR-CLAUDE-AUTO` (2026-10-05).
- **Task**: `OCOR-DEV-0049` — Implement PoC deployment observability backup and safe degradation
- **Change set**: `governed/state-sync-ocor-dev-0049-escalation`
- **Fonte**: OCOR-RCCAD v1.0 §8 (harness) — al massimo 2 cicli di riparazione materialmente
  diversi per task; oltre, escalation con diagnosi e azione minima di sblocco.
- **Implementatore della riparazione (ciclo 2)**: Claude Code (Anthropic); **verifier**: Codex
  (OpenAI) — modelli di fornitori diversi in processi separati (decisione PO
  `OCOR-DEV-0049-IMPLEMENTER-CLAUDE`, 2026-10-05).

## Contesto

`OCOR-DEV-0049` ha esaurito il budget ordinario di 2 cicli di riparazione. Tre verdetti
indipendenti `NO_GO`:

- ciclo 0 `OCOR-DEV-0049-884f7b1160b1-0` (head `884f7b1160b1802c0b00faede1ae00743459d7f5`):
  3 finding bloccanti `high` (`VF-001`…`VF-003`): profili Compose/Helm non operativi, inventario
  delle dipendenze non validato, manifest di backup/replay non vincolanti;
- ciclo 1 `OCOR-DEV-0049-2c5a574a5f3a-1` (head `2c5a574a5f3a127ffd9857601bfa9e593b69e604`):
  6 finding bloccanti `high` (`VF-001`…`VF-006`): processo reale non avviato, restore non
  consumato dal gate, telemetria non osservata, backup non durevole fuori fault domain,
  default-deny non applicata, job qualificante non fail-closed;
- ciclo 2 `OCOR-DEV-0049-7fd4f7728801-2` (head `7fd4f77288010b98330f74a4da455fa1b6e9e321`):
  3 finding bloccanti `high` (`VF-001`…`VF-003`), sotto descritti.

I cicli sono stati materialmente diversi (da 3 a 6 a 3 finding), ma tre difetti `high` residui
persistono dopo entrambe le riparazioni: ammissione non fail-closed, default-deny di rete non
enforce, e gate di restore che non verifica il binding di isolamento per item.

## Finding bloccanti (ciclo 2)

### VF-001 — ammissione non fail-closed su scanner indisponibile / restore non verificato (`high`)

`deploy/helm/ocor-poc/compose.profiles.yaml:1069`. Con tutte le dipendenze disponibili, `/readyz`
risponde `503 RESTORE_UNTESTED` ma `/admit?class=mutative` risponde `200 ADMIT`. Dopo corruzione
del solo profilo temporaneo montato, `/readyz` risponde `503 SCANNER_ERROR` ma
`/admit?class=dispatch` continua a rispondere `200 ADMIT`. Il controllo positivo Emergency Stop
risponde invece `503 DENY`: il bypass dipende dalla guardia, non dal mancato raggiungimento del
processo. `Handler.do_GET` usa soltanto `denied_operation_classes`; `scanner error` e restore non
verificato non entrano in `State.faults`. Viola il comportamento fail-closed e il recovery gate
prima della riapertura previsti da LLD §5.3–5.4; i test 0049 provano la readiness senza verificare
queste ammissioni.

### VF-002 — default-deny di rete non enforce: alias tutti equivalenti (`high`)

`deploy/helm/ocor-poc/compose.profiles.yaml:1180`. `GET http://postgresql:8181/v1/policies`
restituisce `200` con la risposta del vero OPA, pur essendo `postgresql:8181` assente da
`isolation.allowedFlows`. Tutti i nomi dei servizi sono alias dello stesso relay (riga 60), che
ascolta su `0.0.0.0` per ogni porta ammessa e seleziona l'upstream dalla sola porta. Qualsiasi
alias raggiunge qualsiasi porta dell'allowlist. Il test `test_default_deny_admits_only_allowlisted_intra_site_flows`
controlla porte totalmente escluse, ma non coppie host/porta incrociate. Il default-deny con soli
flussi esplicitamente ammessi di ADD §6.1 e LLD §5.1 non è rispettato.

### VF-003 — gate di restore non verifica tenant/compartment per item (`high`)

`deploy/helm/ocor-poc/compose.profiles.yaml:1500`. I metadati PostgreSQL autorevoli di `m1` hanno
`tenant-a/c1`; prima del backup il payload del vero Qdrant è impostato a `tenant-b/c2` con
`governed_context_digest` non vuoto. Backup cifrato e firmato dal vero OpenBao, restore su
PostgreSQL/Qdrant isolati: `exit 0`, `outcome PASSED`, `recovery_gate.gcs.pass=true`. La lettura
dell'indice ripristinato conferma `tenant-b/c2`, diverso dai metadati. Il gate GCS verifica
soltanto che `tenant_id` e digest siano non vuoti; non verifica il binding per item né il
compartment. Il gate di LLD §5.4 e il blocco del projection drift di ADD Part II §2.13 non
rilevano questa incoerenza di isolamento.

## Azione minima di sblocco

1. **VF-001**: bloccare le ammissioni governate/mutative/dispatch quando il controllo di sicurezza
   è indisponibile o il restore è non verificato/fallito, e applicare la riapertura governata
   prevista dal profilo; conservare le degradazioni esplicitamente autorizzate. Aggiungere casi
   operativi positivi e negativi per `SCANNER_ERROR`, `RESTORE_UNTESTED`, receipt invalid/fallita ed
   egress aperto, verificando le decisioni oltre `/readyz`.
2. **VF-002**: enforzare le coppie destinazione/porta dichiarate, con indirizzi o proxy distinti e
   senza listener comuni che rendano tutti gli alias equivalenti. Verificare operativamente la
   coppia ammessa `opa:8181` e negare `postgresql:8181`, `qdrant:5432` e le altre coppie non
   dichiarate; mantenere i controlli positivi e negativi di egress.
3. **VF-003**: confrontare per ogni item il tenant e il compartimento della proiezione con i
   metadati autorevoli, rivalidando anche marking e binding GCS secondo i contratti. Qualsiasi
   mismatch deve produrre receipt `FAILED` e materialisation `BLOCKED`. Aggiungere test con scope
   coerente e mismatch per singolo item, osservando sia receipt sia stato dei servizi ripristinati.

L'esecuzione di una terza riparazione eccede il budget di 2 cicli del harness (OCOR-RCCAD §8):
richiede l'autorizzazione esplicita del Product Owner o una disposition governata alternativa.

## Impatto

`OCOR-DEV-0049` è marcato `BLOCKED_REPAIR_BUDGET_EXHAUSTED`. Task che dipendono transitivamente da
`OCOR-DEV-0049`: `OCOR-DEV-0059`, `OCOR-DEV-0060`, `OCOR-DEV-0063`, `OCOR-DEV-0064`,
`OCOR-DEV-0066`. Restano eseguibili `OCOR-DEV-0050` (hard_dependencies soddisfatte, non dipende da
`OCOR-DEV-0049`) e il suo downstream, oltre a `OCOR-DEV-REM-0017` (CI-0048-REAL-BACKEND), che è la
prossima azione.

## Task bloccati

`OCOR-DEV-0049` e, transitivamente, `OCOR-DEV-0059`, `OCOR-DEV-0060`, `OCOR-DEV-0063`,
`OCOR-DEV-0064`, `OCOR-DEV-0066`.

## Claim fence

Invarato: `E1=0`, `E2=0`, zero requisiti `Verified`, `runtime_conformance` `NOT_ESTABLISHED`,
`PoC`/`Production` `NO-GO`. `inputs/` invariato. L'evidenza di `OCOR-DEV-0049` resta
`CANDIDATE_PENDING_INDEPENDENT_VERIFICATION` (non sigillata).

## 2026-10-05 — Decisione PO e verdetto ciclo 3

La decisione `OCOR-DEV-0049-REPAIR-CLAUDE-AUTO` supera l’escalation della PR #168 e autorizza fino a tre ulteriori riparazioni (cicli 3, 4, 5), esclusivamente Claude Code (Anthropic), con verifier Codex (OpenAI). Il budget ordinario resta 2 per gli altri task. Il testo precedente descrive la disposition storica del ciclo 2; non è il blocco corrente.

Verdetto `OCOR-DEV-0049-02ac643eb3c7-3`, HEAD `02ac643eb3c770361f2f1b67eb0f4ab2bc049097`, creato `2026-10-05T20:09:14.995625Z`: **NO_GO**. SHA-256 del file esterno: `2c860eb6e1bcbeb809125754058bcbda62c7a53cc5f2cedf16d17e650f781f60`. Il task remoto coincide con l’HEAD verificato. Nessun controllo `not_executed` nel verdetto.

### VF-001 — ciclo 3 (`high`, BLOCKER)

Riferimento: `deploy/helm/ocor-poc/compose.profiles.yaml:938`.

latest_valid_receipt verifica firma e digest del manifest, ma non collega manifest.release/profile_digest al profilo corrente. Riproduzione sul codice dell'HEAD richiesto e su OpenBao reale: python3 /tmp/ocor-verify-OCOR-DEV-0049-02ac643eb3c7-3/run.py receipt-pinned ocor-runtime/.venv/bin/python /tmp/ocor-verify-OCOR-DEV-0049-02ac643eb3c7-3/reproduce_receipt.py (worktree detached e ambiente ripristinati secondo il mandato). Il controllo con release ocor-poc-0.2.0 passa. Cambiando solo la release del profilo in ocor-poc-independent-unrestored-release, mantenendo la receipt firmata e il manifest di ocor-poc-0.2.0, /readyz restituisce 200 READY, POST /reopen 200 e /admit?class=mutative 200 ADMIT. Digest corrente e digest del manifest differiscono (e2985ec8... contro d28a8daa...). Prova: /tmp/ocor-verify-OCOR-DEV-0049-02ac643eb3c7-3/logs/receipt-pinned.log, SHA-256 b023cc2e2db8e87dea42e7da85b262072ade4c2af8c9eb0bf9d1f3b851597615. Viola il criterio negativo del task sul restore non testato e la release fence di ADD §6.3/§6.5 e FR-156; il test di drift attuale copre solo il cambiamento del file dopo startup.

Azione richiesta a Claude Code: Prima di assegnare RESTORE_TESTED, verificare che la recovery point e la receipt siano compatibili e vincolate alla release, al digest del profilo e ai pin correnti; un mismatch deve negare readiness e riapertura e mantenere DENY per le operazioni governate. Aggiungere casi live positivi/negativi di riavvio con receipt della release/profilo precedente in entrambi i carrier e rigenerare l'evidenza candidata sul nuovo HEAD, senza cambiare inputs o claim fence.

### VF-002 — ciclo 3 (`high`, BLOCKER)

Riferimento: `deploy/helm/ocor-poc/compose.profiles.yaml:926`.

Il consumer usa soltanto receipt.outcome == PASSED e non controlla i risultati della recovery_gate. Nello stesso riproduttore indipendente, dopo il controllo positivo, una copia della receipt viene resa internamente incoerente: outcome resta PASSED ma recovery_gate.gcs.pass è false e tenant_mismatch contiene m1. La copia è firmata nuovamente dal vero OpenBao transit con la chiave del PoC autorizzato: il test controlla la semantica del consumer di una receipt firmata, senza mock o bypass della firma. Il manifest firmato e il relativo digest restano corretti. /readyz, POST /reopen e /admit?class=mutative restituiscono ancora 200, e la mutazione è ADMIT. Prova: /tmp/ocor-verify-OCOR-DEV-0049-02ac643eb3c7-3/logs/receipt-pinned.log (SHA-256 b023cc2e2db8e87dea42e7da85b262072ade4c2af8c9eb0bf9d1f3b851597615); comando come VF-001. LLD §5.4 richiede GCS/marking e gli altri controlli del recovery gate prima di riaprire traffico; una firma autentica non rende coerente un record con gate fallito. La suite del task non include questo caso negativo del consumer.

Azione richiesta a Claude Code: Validare struttura, versione e coerenza della receipt firmata prima di usarla: tutti i controlli obbligatori della recovery_gate devono essere presenti e avere pass strettamente true; gate mancanti, falsi o malformati devono produrre un reason code specifico, readiness negata, /reopen rifiutato e admission DENY. Aggiungere controlli live con receipt validamente firmate positive e negative per ciascun gate, preservando il fence G4/G6 già approvato e rigenerando soltanto l'evidenza candidata.

### VF-003 — ciclo 3 (`medium`, BLOCKER)

Riferimento: `ocor-runtime/tests/tasks/test_ocor_dev_0049.py:1446`.

Il test qualificante Helm assume che il catalogo contenga esattamente un recovery point dopo il backup manuale, mentre il CronJob resta attivo con schedule */15 * * * *. Nella suite completa sull'HEAD richiesto il job manuale è completato ma l'asserzione len(...) == 1 fallisce con due recovery point reali, rp-20261005T194504Z-35d8c606 e rp-20261005T194509Z-c8eb6135, al confine delle 19:45 UTC. La configurazione consente un backup pianificato durante il test: il requisito sul catalogo totale dipende dall'orario, non dal successo del job sotto verifica. Prova: /tmp/ocor-verify-OCOR-DEV-0049-02ac643eb3c7-3/logs/full-suite.log, SHA-256 43c00284efb1fc965d7c452d804bcabee2113228b138b12da2882f979c0fbc0d; JUnit /tmp/ocor-verify-OCOR-DEV-0049-02ac643eb3c7-3/full-suite.xml. La run mirata aveva passato lo stesso test fuori da tale intersezione. I quattro fallimenti separati per DEPENDENCY_DOWN:fuseki sono diagnosticati e trattati come OOM dello stack, non come questo finding. Riproduzione: avviare la suite Helm sullo stack reale in modo che il backup manuale si sovrapponga a un tick del CronJob, conservando lo schedule approvato. La seconda suite completa, dopo il ripristino di Fuseki e fuori dalla sovrapposizione osservata, ha 1192 PASS e zero skip (full-suite-retry.log, SHA-256 3d8ee16d82ef2d96f136b6966637434151b5fce07095aab105e44bd217c0e832): ciò non elimina la race riprodotta nella prima run.

Azione richiesta a Claude Code: Correlare il recovery point, il manifest e la receipt al job effettivamente verificato, senza assumere la cardinalità totale del catalogo; mantenere il controllo del vault esterno e delle firme. Aggiungere un caso operativo con backup pianificato e manuale concorrenti e verificare entrambi i manifest, senza skip, ignore o quarantine. La campagna qualificante deve essere riproducibile anche al confine del tick CronJob.

Restano **due** cicli autorizzati: prossimo `repair_cycle=4`, poi al massimo 5. Aggiornare `~/.ocor-codex/audit_0049.md`, correggere tutti i finding del verdetto più recente senza riscrivere ciò che è già accettato, riacquisire ogni campo candidato dall’HEAD finale e richiedere verifica Codex. Esauriti i tre ulteriori cicli con `NO_GO`: escalation e `TERMINAL_BLOCKED`.

Il loop implementato da Codex esegue soltanto questa sincronizzazione; termina con `TERMINAL_BLOCKED` e `next_action` «ciclo di riparazione Claude Code su OCOR-DEV-0049», come imposto dalla decisione, pur restando pronto 0050 e aperta REM-0017. Non è una dichiarazione di indisponibilità dell’intero backlog. PR #169 concorrente non modificata; REM-0017 resta prioritario dopo la fase 0049 e obbligatorio prima di G6. Evidenza 0049 candidata, non sigillata; `inputs/`, E1/E2/Verified e claim fence invariati.

## 2026-10-06 — Verdetto ciclo 4 e ultimo passaggio autorizzato

Verdetto `OCOR-DEV-0049-aefabf91777d-4`, HEAD `aefabf91777d311b95cad0c60de0ffa61357ea19`, creato `2026-10-05T23:48:56.535182Z`: **NO_GO**, quattro finding bloccanti. SHA-256 del file esterno: `46e06aad29587d01f51b626ee94b394bbcb0cc2ffda721d15c108a4be346a626`. L’HEAD remoto è stato confrontato con il verdetto prima della scrittura; `not_executed=[]`. Implementatore riparazione **Claude Code (Anthropic)**; verifier **Codex (OpenAI)** in processo indipendente. Implementatore del loop **Codex (OpenAI)**.

### VF-001 — ciclo 4 (`high`, BLOCKER)

Riferimento: `deploy/helm/ocor-poc/templates/deployment.yaml:27`.

FR-156, NFR-068/DEC-157; ADD v1.3 Part I §6.1 e LLD v1.1 §5.2. Su HEAD aefabf91777d311b95cad0c60de0ffa61357ea19, probe_helm_images.py riproduce helm template con operational.image=python:3.11 e con un digest diverso: exit 0, Deployment/Job/CronJob usano l'override, ma profile.json mantiene il vecchio ocor.images.pins.ops. Anche operational.postgresImage, kafkaImage e qdrantImage ammettono tag latest senza cambiare i pin dichiarati. Prova: /tmp/ocor-verify-OCOR-DEV-0049-aefabf91777d-4/helm-image-probes.log. La riproduzione live probe_helm_live.py installa la chart in un namespace disposable con operational.image=python:3.11 e copia del vault autentico: pod imageID docker.io/library/python@sha256:27e044f7e01fea05c1760324d58fc5360a0767b9ef098e74ddaf8c70b8f46d26, /readyz 200 READY, RESTORE_TESTED, /reopen 200 e /admit?class=mutative 200 ADMIT. La distinzione degli artifact è verificata via crictl inspecti: override Python 3.11.17/config cc5f2f88..., pin Python 3.11.15/config 7ba83304..., quindi non è soltanto una differenza fra digest index e platform. Prove: helm-live-image-retry.log e image-identity.log sotto la stessa directory temporanea. SHA256 raw verifier: helm-live-image-retry.log=b1852bf443c135b1e8e55a60b642e5b8ab7f92ddcd2176a3e8b58b83066c6760, image-identity.log=c7b4cdf75aeaab117f38edb304b29b58ae7c98870c12d361e081109b9d4c84f0.

Azione minima: Derivare le immagini effettive di tutti i workload dai pin governati oppure imporre prima del rendering/admission uguaglianza e digest valido tra operational.*Image e ocor.images.pins. La release binding deve coprire gli artifact realmente eseguiti. Aggiungere casi positivi e negativi per tag-only e digest divergente su Deployment, backup e restore, con startup/readiness e riapertura bloccati quando incompatibili.

### VF-002 — ciclo 4 (`high`, BLOCKER)

Riferimento: `deploy/helm/ocor-poc/compose.profiles.yaml:968`.

LLD v1.1 §5.4 e ADD v1.3 §6.5: il recovery gate GCS deve passare prima della riapertura. La riproduzione indipendente probe_receipts.py usa una copia del vault prodotto dalla run sull'HEAD, un nuovo processo dall'identica sorgente, i relay verso i backend reali e la firma del vero OpenBao. Una receipt con recovery_gate.gcs.pass=true ma detail.tenant_mismatch=[m1] viene accettata: RESTORE_TESTED, /readyz 200 READY, /reopen 200 MUTATIVE_PATH_REOPENED_BY_HUMAN e ADMIT 200 per tutte le sei classi. Il controllo positivo con la receipt autentica passa. Il consumer verifica soltanto entry.pass e ignora la contraddizione nel detail. Prova: /tmp/ocor-verify-OCOR-DEV-0049-aefabf91777d-4/receipt-probes.log, caso gcs_detail_with_pass_true. SHA256 raw verifier: receipt-probes.log=9db3fa53644a21a09120e572e9dc1f8e7855eb29ad9a170202bf8d617022a438.

Azione minima: Validare la coerenza semantica e tipata dei dettagli dei recovery gate con il risultato dichiarato, rifiutando ad esempio qualsiasi tenant/compartment/GCS/marking mismatch insieme a pass=true. Coprire con casi live firmati dal custodian sia dettagli coerenti e legittimamente non vuoti (conteggi/watermark), sia dettagli che segnalano violazioni, mantenendo DENY prima della riconciliazione.

### VF-003 — ciclo 4 (`medium`, BLOCKER)

Riferimento: `deploy/helm/ocor-poc/compose.profiles.yaml:995`.

Controllo fail-closed della receipt e del limite restore.receiptMaxAgeHours. Nella stessa riproduzione live, completed_at_epoch=NaN in una receipt validamente firmata produce RESTORE_TESTED, /readyz 200, /reopen 200 e ADMIT per tutte le sei classi. json.loads accetta NaN; il controllo di tipo accetta float e i confronti completed > now()+skew e now()-completed > max_age risultano entrambi falsi: la verifica temporale viene bypassata. Controllo positivo autentico eseguito. Prova: /tmp/ocor-verify-OCOR-DEV-0049-aefabf91777d-4/receipt-probes.log, caso not_a_number_epoch. SHA256 raw verifier: receipt-probes.log=9db3fa53644a21a09120e572e9dc1f8e7855eb29ad9a170202bf8d617022a438.

Azione minima: Rifiutare costanti JSON non standard e numeri non finiti nel parsing/canonicalizzazione delle receipt; verificare esplicitamente math.isfinite per i tempi e coerenza del timestamp. Aggiungere controlli positivi e negativi live per timestamp valido, scaduto, futuro, NaN e Infinity con motivazione del rigetto, readiness 503 e riapertura/admission negate.

### VF-004 — ciclo 4 (`medium`, BLOCKER)

Riferimento: `deploy/helm/ocor-poc/compose.profiles.yaml:1134`.

ADD v1.3 Part I §6.3 e LLD v1.1 §5.3 richiedono il policy digest nella telemetria. probe_policy_digest.py --execute esegue l’identica funzione dell’HEAD nel container pinned Python contro il vero OPA. Controllo positivo: 2 policy, risposta 1420 byte, digest 29f0ae60... uguale all’oracle indipendente. Un solo modulo rule-free in package temporaneo del verifier porta la risposta a 22749 byte/3 policy: digest reale 423e45b430c1645a687b6eb46e2c1d11874e9ed392be1d5f9bbd606841614b0f, ma l’agente restituisce 4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945, SHA256 di []. Il codice sostituisce una risposta grande con {} e considera il risultato una policy inventory vuota valida. Nessuna policy esistente o decisione di authorization modificata; teardown del solo modulo del verifier verificato e controllo positivo post-teardown riuscito. Prova: /tmp/ocor-verify-OCOR-DEV-0049-aefabf91777d-4/policy-digest-probe-live.log, SHA256=f3ccd8beb0094a7da5458e14e38f71e886ec681980806ca381b3bc29eb441673.

Azione minima: Leggere e validare l’inventario reale entro un limite esplicito oppure ottenere una release/bundle digest autorevole. Troncamento, risposta troppo grande o malformata devono essere segnalati come digest indisponibile/error, senza fabbricare un digest di insieme vuoto. Aggiungere casi live positivi sotto soglia e negativi/positivi di risposta grande, verificando il digest esatto nei log/trace anziché soltanto la presenza di una stringa.

La decisione PO `OCOR-DEV-0049-REPAIR-CLAUDE-AUTO` autorizza i cicli 3, 4 e 5. Consumati 3 e 4: resta **un solo ciclo, il 5**, da Claude Code. Il loop non ripara, non sigilla e non lancia la verifica.

Claude Code esegue il ciclo 5 (ultimo dei tre ulteriori cicli autorizzati) dall’HEAD remoto aefabf91777d311b95cad0c60de0ffa61357ea19: corregge tutti i quattro finding del verdetto OCOR-DEV-0049-aefabf91777d-4, aggiorna ~/.ocor-codex/audit_0049.md per comportamenti, riacquisisce ogni campo dell’evidenza dall’HEAD finale e richiede verifica Codex. Codex implementatore del loop esegue solo state sync. Con ulteriore NO_GO: escalation senza altra riparazione.

PR #170 aggiornata per conservare insieme la sincronizzazione dei cicli 3 e 4; PR #169 concorrente non modificata. Lo stato di `origin/main` resta fonte autoritativa fino al merge esatto con gate verdi. Arresto del loop `TERMINAL_BLOCKED` per passaggio obbligatorio a Claude Code; non dichiara tutto il backlog bloccato. REM-0017 precede 0050 dopo la conclusione della verifica/integrazione 0049; resta dipendenza G6. Claim ed evidenza candidata invariati.

## 2026-10-06 — Fallback di verifica del ciclo 5

La riparazione Claude Code del ciclo 5 è pubblicata sul branch `task/OCOR-DEV-0049-poc-deployment-observability-backup-safe-degradation` all’HEAD esatto `b40aa8a6908b02d95cdf8138200f99f2e8aea8b1`; commit sorgente `49cd235473c2105bc54a37b47708135234246651`. Il ciclo interrotto dal blocco macchina è stato ripreso secondo `STACK-HYGIENE`; il record candidato registra 295 test del task e 1396 della suite completa, zero skip. Questi risultati sono dichiarazioni del candidato, ancora da verificare indipendentemente, e non risultati prodotti da questo state sync. Il controllo meccanico dei digest del candidato è stato rieseguito: **83/83 PASS**. Record e raw log restano byte-identici.

Il tentativo `OCOR-DEV-0049-b40aa8a6908b-5` termina con **VERIFIER_ERROR**: tre interruzioni Codex per filtro di moderazione del fornitore, confermate nei raw log. File esterno `/home/luca/.ocor-codex/verdicts/OCOR-DEV-0049-b40aa8a6908b-5.json`, SHA-256 `882ee290ade051a6827b0f26776afbe3064005fe9885e2fd65b1f5e4f9b9f109`. Non è un `NO_GO` né un’accettazione; i finding vuoti non rappresentano una review completata. Il precedente verdetto conclusivo resta quello del ciclo 4. Nessun verdetto è scritto o modificato dal loop implementatore.

La decisione PO `OCOR-DEV-0049-VERIFIER-FALLBACK` del 2026-10-06 è applicabile perché il blocco persiste. Nuova richiesta `OCOR-DEV-0049-b40aa8a6908b-5-claude-fallback-1` sul medesimo HEAD, `repair_cycle=5`; il suffisso distingue il tentativo fallback senza consumare un ciclo di riparazione e senza sovrascrivere il precedente verdetto. **Implementatore della riparazione: Claude Code (Anthropic). Verifier fallback: Claude Code (Anthropic). Implementatore del loop: Codex (OpenAI).** Limite di indipendenza: Riparazioni OCOR-DEV-0049: Claude Code (Anthropic); verifier fallback: Claude Code (Anthropic), stesso modello in processo e contesto separati. Implementazione originale di un altro modello. Variante esatta non attestata dal runtime; nessuna diversità di modello dichiarata. Implementatore del loop: Codex (OpenAI). Questa sezione è l’addendum di attribuzione all’evidenza candidata; la designazione Codex presente nel candidato descrive il verifier previsto alla sua creazione. L’eventuale sigillatura deve incorporare l’identità effettiva e il nuovo verdetto.

Il loop esterno seleziona Claude Code tramite il marker locale `~/.ocor-codex/.verifier_claude_0049`; il loop implementatore prepara il marker e la richiesta dopo la pubblicazione dello state sync, senza avviare né simulare il verifier. Il processo pytest orfano del terzo tentativo è stato interrotto con SIGINT; teardown verificato con zero container, reti e volumi del suo progetto `ocor-poc-ops-e147ab`. File locale env riallineato alle credenziali dello stack corrente dopo confronto in memoria e backup 0600; inizializzazione e fixture PASS dopo un solo retry ciascuno.

PR #170 già mergiata all’HEAD `1055be76acc43213f665cd2f2b4502d617267e9b`, 13 check richiesti SUCCESS; baseline dello state sync `d33ae207105648799ac11479cca5b9eb9bf619ca`. PR #169 concorrente resta invariata. Il ready set JSON è `0049`, `0050`; le decisioni PO impongono la conclusione della verifica 0049 e la priorità REM-0017 prima di 0050. Con `GO_FOR_EVIDENCE_SEAL`: integrazione, CI e merge esatto. Con `NO_GO`: escalation e `TERMINAL_BLOCKED`, nessun ciclo 6 autorizzato. Nessuna nuova decisione PO richiesta per questo fallback.

Nessuna modifica a `inputs/`, runtime, test, workflow, lock o record sigillati. Suite completa del loop implementatore **NOT_EXECUTED**: unità esclusivamente documentale; il verifier dovrà rieseguire i controlli prescritti con igiene dello stack e limite 45 minuti. `E1=0`, `E2=0`, zero requisiti globalmente `Verified`, runtime conformance `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## 2026-10-06 — Ciclo 5 concluso: NO_GO, budget esaurito

Verdetto `OCOR-DEV-0049-b40aa8a6908b-5`, HEAD `b40aa8a6908b02d95cdf8138200f99f2e8aea8b1`, creato `2026-10-06T16:21:05Z`: **NO_GO**. SHA-256 del file esterno: `e1bc2e0662d7323ccf43bc082f13154df7baddbe22be6a6f630c264047abda1a`. HEAD remoto verificato identico. Implementatore riparazioni Claude Code; verifier effettivo Claude Code (`claude-opus-5-5`) tramite `OCOR-DEV-0049-VERIFIER-FALLBACK`; stesso modello in processo e contesto separati, implementazione originale di un altro modello. Implementatore del loop Codex. Il fallback atteso con suffisso `-claude-fallback-1` è stato concluso dal loop sul request_id originale; l’identità effettiva è quella nel verdetto, non quella storica nel candidato.

### VF-001 — ciclo 5 (`high`, BLOCKER)

Riferimento: `deploy/helm/ocor-poc/compose.profiles.yaml:1646`.

snapshot_index esegue il POST /collections/{c}/snapshots?wait=true fuori da ogni gestione d'errore: solo 404 su GET/DELETE e' tollerato. Quando due seal concorrenti (run manuale sovrapposta al CronJob, scenario dichiarato nella docstring) collidono sullo stesso nome di snapshot al secondo, Qdrant reale risponde 500 ('failed to store snapshot archive ... File IO error: No such file', log ocor-bootstrap-qdrant-1 2026-10-06T15:41:07Z) e l'HTTPError propaga al chiamante: il seal fallisce. Riprodotto 3 volte in modo indipendente: suite task (1 failed/294 passed), suite completa (stesso test FAILED con HTTPError 500), probe dedicato 1/60 chiamate. Il test qualificante test_concurrent_seals_each_download_their_own_index_snapshot (ocor-runtime/tests/tasks/test_ocor_dev_0049.py:1404-1442) fallisce quindi sull'HEAD verificato, mentre l'evidenza dichiara 295 passed: il PASS registrato dipende dalla temporizzazione, non dal comportamento.

Azione minima proposta, **non autorizzata come riparazione**: Rendere snapshot_index robusto alla collisione di creazione: trattare un 5xx del POST di creazione come tentativo ritentabile entro il loop limitato con jitter (o serializzare i seal con un lock/lease, o evitare la collisione di nome), mantenendo fail-closed dopo attempts esauriti (INDEX_SNAPSHOT_UNSTABLE) e la pulizia degli snapshot. Aggiungere un caso deterministico che forzi il 500 sul POST (oltre al test concorrente su Qdrant reale) e rigenerare l'evidenza dopo almeno una run task e una run completa verdi.

### VF-002 — ciclo 5 (`low`, NON_BLOCKING)

Riferimento: `ocor-runtime/tests/tasks/test_ocor_dev_0049.py:170-176`.

test_agent_source_passes_ruff_and_mypy_strict invoca sys.executable -m mypy; il validation_command dichiarato per la suite completa ('uv run --frozen pytest -q -ra tests/' in ocor-runtime) risincronizza il venv senza l'extra lint e il test fallisce con 'No module named mypy'. Il sorgente dell'agente e' invece pulito (ruff e mypy --strict PASS in venv isolato con --extra lint).

Azione minima proposta, **non autorizzata come riparazione**: Dichiarare nel validation_command/evidenza l'ambiente con --extra test --extra lint, oppure far fallire il test con un messaggio di precondizione esplicito; nessuna modifica al codice dell'agente richiesta.

Controlli del verifier `NOT_EXECUTED` (nessun PASS attribuito):

- Probe supplementare del verifier sulla coerenza ricevuta/recovery point (tombstone non riprodotti, deletion epoch sotto il checkpoint): run interrotta prima dei casi del probe (results.jsonl assente); non dichiarato superato. Non e' uno dei controlli obbligatori elencati, ma resta aperto per il prossimo ciclo.
- Run CI su GitHub per l'HEAD verificato: non richiesta per OCOR-DEV-0049 (REM-0017-PRIORITY riguarda OCOR-DEV-REM-0017), non consultata.

Esauriti i cicli aggiuntivi 3/4/5; nessun ciclo 6 autorizzato. Decision request `OCOR-DEV-0049-REPAIR-BUDGET` in `reports/development/decision_requests/OCOR-DEV-0049-REPAIR-BUDGET.md`. Nessuna riparazione, nuova richiesta di verifica, sigillatura o merge del task. Candidato b40aa8a preservato byte-identico.

Il loop termina `TERMINAL_BLOCKED` per la disposizione puntuale del PO sul budget di 0049. Non significa che tutto il backlog sia bloccato: REM-0017 è la prossima unità operativa alla ripresa del loop, poi 0050. PR #169 preservata. Claim fence invariato (E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO).

Chiusura transitiva ricalcolata dal backlog: 0049, 0059 e tutti i task 0060–0069. La lista breve dei record precedenti era incompleta; 0050–0058 restano raggiungibili senza la chiusura di 0049. REM-0017 resta prioritario alla ripresa.

## 2026-10-07 — Ciclo 6 NO_GO; escalation circoscritta e prosecuzione

La decisione PO `OCOR-DEV-0049-REPAIR-6` risolve la richiesta di budget del ciclo 5 e autorizza un solo ciclo 6 da Claude Code. Verdetto `OCOR-DEV-0049-d0ac80a9d1d6-6`, HEAD `d0ac80a9d1d603ca19ddbb2d5291e252b3d6ae2b`, creato `2026-10-07T02:05:22Z`: **NO_GO**. HEAD remoto confrontato prima della scrittura; SHA-256 del verdetto esterno `934e0f032daa67c0f6abee6e379c4569c0394c5e3b0c28dce05d799c005fc18c`. Nessun verdetto scritto o modificato dal loop.

Implementatore riparazioni **Claude Code (Anthropic)**; verifier effettivo **Claude Code (claude-opus-5-5)**, processo e contesto separati secondo `OCOR-DEV-0049-VERIFIER-FALLBACK`; stesso modello delle riparazioni, implementazione originale di altro modello. Implementatore loop **Codex (OpenAI)**.

### VF-001 — ciclo 6 (`medium`, BLOCKER)

Riferimento: `deploy/helm/ocor-poc/compose.profiles.yaml:1125`.

Il seal scrive il journal con `order by deletion_epoch, event_id` in PostgreSQL (compose.profiles.yaml:184; database con collation en_US.utf8, verificato: pg_database.datcollate=en_US.utf8 per ocor e template1, da cui `create database ocor_poc_drill` eredita) e firma `last_event_id = journal[-1]` (riga 1829); il restore riproduce i tombstone ordinati in Python per (int(deletion_epoch), event_id) in ordine di codepoint (riga 2021); il nuovo receipt_checkpoint_inconsistencies confronta replayed[-1] con last_event_id (riga 1125). Le due collation divergono (PostgreSQL reale: 'evt-del-a' < 'evt-del-b' < 'evt-del-B' e 'evtdel-m3' < 'evt-del-m4'; Python: l'opposto) e deletion_epoch non e' unico (colonna bigint not null senza vincolo). Probe riproducibile (/tmp/ocor-verify-OCOR-DEV-0049-d0ac80a9d1d6-6/probe/collation_probe.py: ORDER BY eseguita sul PostgreSQL ocor-bootstrap, funzioni reali dell'agente): con due tombstone alla stessa epoch massima, un restore che li ha riprodotti tutti produce receipt_inconsistencies=[] ma receipt_checkpoint_inconsistencies=['memory:tombstones_not_replayed']; latest_valid_receipt restituisce quindi RESTORE_RECEIPT_INCONSISTENT in modo deterministico per quel recovery point (ogni nuovo drill sugli stessi dati fallisce allo stesso modo) con una diagnosi falsa di tombstone non riprodotti. Fail-closed, ma il criterio positivo (restore testato -> readiness) e' violato da dati legittimi e nessun test copre tombstone multipli alla stessa epoch.

Azione minima proposta, **non autorizzata come ciclo 7**: Rendere identico l'ordinamento di seal e replay (es. `order by deletion_epoch, event_id collate "C"` nella capture, oppure ordinare il journal in Python con la stessa chiave del restore prima di calcolare journalCheckpoints), o rendere il confronto indipendente dall'ordine; aggiungere un caso positivo unitario e live con >=2 tombstone alla stessa deletion_epoch e id con maiuscole/punteggiatura divergenti tra collation, e il relativo negativo; rigenerare l'evidenza.

### VF-002 — ciclo 6 (`low`, NON_BLOCKING)

Riferimento: `ocor-runtime/tests/tasks/test_ocor_dev_0049.py:1815`.

Il ciclo 6 ha rimosso dai positivi live la variante journal_ahead_of_metadata (test_ocor_dev_0049.py:1815) perche' incompatibile con il checkpoint della fixture (journal 7); non esiste piu' un positivo live ne' un positivo unitario di receipt_checkpoint_inconsistencies con journal_max > metadata_max coerente col checkpoint (test_receipt_matching_its_checkpoint_is_coherent:791 copre solo 7/7 e 0/0), e la docstring a :1822 dichiara ancora 'journal ahead of metadata'. Il comportamento e' corretto: probe del verifier con checkpoint journal 9 / metadata 7 e ricevuta 9/7 -> [] .

Azione minima proposta, **non autorizzata come ciclo 7**: Aggiungere un caso positivo (unitario e, se possibile, live con un recovery point sigillato con journal davanti ai metadata) per receipt_checkpoint_inconsistencies con journal_max > metadata_max, e allineare la docstring a :1822.

Risultati dichiarati nel verdetto del verifier, non prodotti dal loop: suite task 321 PASS/0 FAIL/0 skip; suite completa 1422 PASS/0 FAIL/0 skip, in 2565.34 s. Queste run verdi non annullano il finding bloccante del probe di collation. VF-001 del ciclo 5 (collisione POST Qdrant) risolto secondo il verifier: 80/80 download, 2 HTTP 500 assorbiti, zero snapshot residui. La coerenza receipt/checkpoint è stata esercitata, ma la riproduzione end-to-end della nuova collisione di collation resta non eseguita.

Controlli del verifier `NOT_EXECUTED`:

- Riproduzione end-to-end live di VF-001 (seal + restore dell'agente su un journal con tombstone alla stessa epoch e id a collation divergente): non eseguita; il difetto e' provato da probe che usa l'ORDER BY reale su PostgreSQL ocor-bootstrap e le funzioni reali dell'agente.

- Run CI GitHub per l'HEAD verificato: non richiesta per OCOR-DEV-0049 (REM-0017-PRIORITY riguarda OCOR-DEV-REM-0017), non consultata.

Budget ciclo 6 consumato: **nessun ciclo 7 autorizzato**, nessuna riparazione Codex, sigillatura o merge 0049. Candidato `d0ac80a9d1d603ca19ddbb2d5291e252b3d6ae2b` preservato. La disposizione globale precedente `TERMINAL_BLOCKED` è superseduta da `OCOR-DEV-0049-REPAIR-6`: il loop continua con **REM-0017 → 0050**, poi i task raggiungibili senza 0049. Chiusura transitiva bloccata: OCOR-DEV-0049, OCOR-DEV-0059, OCOR-DEV-0060, OCOR-DEV-0061, OCOR-DEV-0062, OCOR-DEV-0063, OCOR-DEV-0064, OCOR-DEV-0065, OCOR-DEV-0066, OCOR-DEV-0067, OCOR-DEV-0068, OCOR-DEV-0069. REM-0017 resta prerequisito G6. PR #169 osservata aperta, HEAD 7562d3c48015f45a0b518fde622ca4304e9468ca, validation-closure FAILURE run 37350619188; preservata in questa unità.

State sync documentale su `governed/state-sync-ocor-dev-0049-cycle6` da `5c57d411a7036d585d431a8030c4816831e7d40c`; suite runtime locale **NOT_EXECUTED**, risultati del verifier distinti dai controlli meccanici del loop. `inputs/`, E1=0/E2=0, zero Verified, runtime NOT_ESTABLISHED, PoC/Production NO-GO invariati.


## 2026-10-07 — Autorizzazione OCOR-DEV-0049-REPAIR-7, riparazione Codex

La decisione esplicita del Product Owner autorizza il solo ciclo 7 da HEAD remoto
`d0ac80a9d1d603ca19ddbb2d5291e252b3d6ae2b`, verificato in sola lettura prima
della modifica. Supersede il divieto di ciclo 7 e l’assegnazione delle riparazioni
al solo Claude Code per questa iterazione. Implementatore ciclo 7: Codex (OpenAI);
verifier: Claude Code (Anthropic) in processo/contesto separati. Riparazioni 2–6 di
Claude Code conservate; nessun ciclo 8 autorizzato. Il NO_GO del ciclo 6 rimane
un evento storico e non viene riscritto come GO.

REM-0017 PR #169 `efce339` è WIP in attesa del candidato stabile; non è stata
interrotta né modificata in questa riparazione. Il ciclo 7 procede durante tale
attesa, come autorizzato. Codice sorgente `129cc2a`: ordinamento comune al sigillo
e al replay, capture `COLLATE "C"`, casi positivi/negativi unitari e live con due
tombstone alla stessa epoch e collation divergenti; positivo journal 9/metadata 7
sigillato e restored. Test Helm attende esplicitamente il diniego RESTORE_UNTESTED,
fallendo su 200/Ready e senza accettare NOT_YET_SCANNED come prova.

Stabilità in corso (3 suite task consecutive e 1 completa, zero skip, 45 minuti,
reset/bootstrap/health e watchdog per ogni run). Primo run: 325 PASS in 1811,50 s,
zero skip e nessun nuovo residuo. Non è ancora un verdetto, un sigillo o una chiusura.
Controllo locale dell’ID Fuseki FAIL, registrato separatamente; ricetta CI con base
/source locked e servizi reali, nessun update o bypass del lock. Decision request
FUSEKI-LOCAL-IDENTITY-AFTER-CI-EXERCISE aperta sul change set REM, non occultata.

Con GO si riprende REM-0017 e l’integrazione secondo REM-0017-PRIORITY; con NO_GO
si escala il solo 0049 e si prosegue G5. E1=0, E2=0, zero Verified e claim NO-GO
invariati. Referto finale e HEAD candidato esatto da acquisire dopo la stabilità.

### Candidato ciclo 7 consegnato — 2026-10-07T14:11:08.613626+00:00

Candidato `9d86abebc7626a36115540a2711772c1d2d19e23`, sorgente `a128a622151261d510b332ca93a688912a119197`: task1: 325 PASS/0 skip (2088.5s), task2: 325 PASS/0 skip (1734.4s), task3: 325 PASS/0 skip (1752.6s), full: 1426 PASS/0 skip (2166.9s), reports: 48 PASS/0 skip (10.2s). Esito locale, non verdetto indipendente; escalation storica dei cicli precedenti preservata. Bootstrap locale Fuseki identity-lock FAIL dichiarato, nessuna uguaglianza col lock asserita.

Verifica indipendente Grok 4.7 (Cursor) del ciclo 7 di OCOR-DEV-0049 sull’HEAD 9d86abebc7626a36115540a2711772c1d2d19e23; poi riprendere REM-0017 repair 1 con questo candidato, riallineare il pin e la CI senza esclusioni, richiedere verifica indipendente. Integrazione 0049 dopo REM-0017 verificato; con NO_GO escalation solo 0049 e proseguire G5, nessun ciclo 8.


## 2026-10-07T16:57:52.731979+00:00 — Verdetto finale ciclo 7, escalation circoscritta

Verdetto `OCOR-DEV-0049-9d86abebc762-7` sull’HEAD remoto esatto `9d86abebc7626a36115540a2711772c1d2d19e23`:
**NO_GO**, SHA-256 `bc8539a202ce6d88e711a7832e71cf78902ea5e6fee2cd3b609ffa8628ed8e7e`. Creato dal verifier `2026-10-07T16:53:13Z`,
letto in sola lettura; nessun verdetto scritto o modificato dal loop.

Riparazioni cicli 2–6: **Claude Code (Anthropic)**; ciclo 7: **Codex (OpenAI)**.
Verifier effettivo: **Grok 4.7 (xAI) tramite Cursor CLI**, processo e contesto separati,
fornitore diverso da entrambi gli implementatori (`OCOR-DEV-0049-VERIFIER-CURSOR`).

### VF-001 — ciclo 7 (`high`, BLOCKER)

Riferimento: `deploy/helm/ocor-poc/compose.profiles.yaml:1124`.

La funzione reale receipt_checkpoint_inconsistencies (compose.profiles.yaml:1124-1126), invocata da latest_valid_receipt prima di RESTORE_TESTED (riga 1179), accetta una ricevuta PASSED il cui replayed_event_ids non e il journal checkpointato. Probe sul modulo estratto dall'HEAD, checkpoint entries=3 max_deletion_epoch=9 last_event_id=evt-del-c (ordine codepoint evt-del-B, evt-del-a, evt-del-c): middle_swap ['evt-del-a','evt-del-B','evt-del-c'] -> []; foreign_nonfinal ['evt-del-FOREIGN','evt-del-a','evt-del-c'] -> []. Stessa falla a due id: checkpoint last_event_id=evt-del-a, replayed ['evt-del-FOREIGN','evt-del-a'] -> []. L'inversione che cambia l'ultimo id e l'omissione sono rifiutate, e i test live 7/7 e 9/7 (collation en_US.utf8, journal_max 9 > metadata_max 7, omissione, ordine locale, epoch sotto checkpoint) sono PASS: non coprono la sostituzione di un id non finale ne una permutazione che conserva last_event_id. Il commento della funzione richiede invece ogni tombstone checkpointato, una volta, con l'event id originale. Lista vuota significa ricevuta coerente e, sul boundary, RESTORE_TESTED.

Azione minima tecnica proposta, **non eseguita e non autorizzata come ciclo 8**:
Vincolare replayed_event_ids all'intera sequenza ordinata degli event id del journal firmato, o al digest di quella sequenza, dentro journalCheckpoints. receipt_checkpoint_inconsistencies deve rifiutare con memory:tombstones_not_replayed ogni omissione, duplicato, sostituzione e permutazione, non solo un last_event_id diverso. Aggiungere il negativo unitario e live in cui un id non finale e sostituito e quello in cui due id non finali sono scambiati lasciando invariato last_event_id; entrambi devono dare RESTORE_RECEIPT_INCONSISTENT sul boundary, con il positivo canonico ancora accettato.

LLD v1.1 §5.4 richiede event ID originali e recovery gate prima della riapertura;
ADD v1.3 Part I §6.5 fissa ordering/digest del replay e Part II §2.13 lega i
tombstone al recovery point. La firma della receipt non risolve il binding incompleto.
Il verifier conferma i positivi unitari/live 7/7 e 9/7 e l’ordinamento comune:
nessuna regressione o finding generico aggiunto sui difetti risolti.

Risultati **del verifier**, non run del loop: task **325 PASS/0 skip** (1915,35 s),
full **1426 PASS/0 skip** (2633,22 s). Il tentativo full senza DSN è esplicitamente
non qualificante (1370 PASS/5 skip/51 error), poi ripetuto con DSN reale.
Il finding bloccante del probe prevale sulle suite verdi. `not_executed` del verdetto: `[]`.

Budget ciclo 7 consumato; **nessun ciclo 8**, nessuna sigillatura, nessuna PR o merge
del task 0049. Candidato `9d86abebc7626a36115540a2711772c1d2d19e23` preservato byte per byte.
Un nuovo mandato PO sarebbe necessario soltanto per riaprire 0049: nessuna autorizzazione
implicita o richiesta di conferma. Blocco transitivo ricalcolato: OCOR-DEV-0049, OCOR-DEV-0059, OCOR-DEV-0060, OCOR-DEV-0061, OCOR-DEV-0062, OCOR-DEV-0063, OCOR-DEV-0064, OCOR-DEV-0065, OCOR-DEV-0066, OCOR-DEV-0067, OCOR-DEV-0068, OCOR-DEV-0069.
Task pronti per dipendenze: OCOR-DEV-0049, OCOR-DEV-0050; eseguibile **OCOR-DEV-0050**.
G5 indipendente raggiungibile: OCOR-DEV-0050, OCOR-DEV-0051, OCOR-DEV-0052, OCOR-DEV-0053, OCOR-DEV-0054, OCOR-DEV-0055, OCOR-DEV-0056, OCOR-DEV-0057, OCOR-DEV-0058.

Loop **CONTINUE**: prossimo lavoro **REM-0017 repair 1** (PR #169 `efce339d9fc7a551216c84135e06d39c0488a222`,
CI run 37580988000 FAILURE), poi **0050/G5**; il REM deve gestire esplicitamente il pin
del candidato NO_GO, senza farlo diventare evidenza accettata di 0049. Se resta in attesa
di una decisione/evento esterno, proseguire G5. Nessun test/gate escluso o indebolito.

Preflight corrente: inputs 8/8, harness 14 PASS, drift 0/167 su 63 task, toolchain 9/9.
Bootstrap locale **FAIL**, ID Fuseki diverso dal lock; salute **NOT_EXECUTED**, nessuno
stack avviato. Suite runtime locale **NOT_EXECUTED** per unità solo documentale.
Raw log/hash in MODEL_HANDOFF, `/home/luca/.ocor-codex/state-sync-0049-cycle7-verdict`. Claim fence invariato.


## 2026-10-08T07:18:03.967776+00:00 — REPAIR-8 e disposition del verdetto indipendente

La decisione PO `OCOR-DEV-0049-REPAIR-8` (2026-10-07) supersede il divieto di ciclo8 del record precedente. Implementatore ciclo8 Claude Code; verifier effettivo Grok4.7 (Cursor), fallback previsto dopo due interruzioni Codex. Il ciclo7 e le relative evidenze NO_GO restano storia immutata.

Verdetto `OCOR-DEV-0049-b14e4bf59695-8` su `b14e4bf596959de35313dd9a6ee538576432ffd2`: **GO_FOR_EVIDENCE_SEAL**, nessun finding/NOT_EXECUTED, SHA256 `130a47fc98ed61fc0865079418ff9df3a2877a8d42b140357f3a8d6a1f912d4b`. Riproduzioni indipendenti:390 PASS x3 e full1491 PASS, zero skip/failure/error. Candidato sigillato da Codex nel solo record/manifest su `df444af855e884d7783612b302e008b90105fe13`; nessuna riparazione codice del loop.

PR [#176](https://github.com/nepryoon/ocor-detailed-design/pull/176) aperta: CI finale **FAIL**, 10/13 check richiesti verdi, `rccad-methodology, delivery-activation, validation-closure` fallisce. Il task è `VERIFIED_SEALED_PENDING_CI_REMEDIATION`, **non** completato/mergiato. Nessun finding funzionale aperto del ciclo8; il precedente VF-001 è superseduto dalla correzione/verifica8. Nessun ciclo9. Prossimo lavoro REM-0017 separato secondo REM-0017-PRIORITY e nuovo budget75m, poi check/merge sull’HEAD esatto di0049. Nessuna riduzione di copertura o soglia, E1/E2 e claim invariati.
