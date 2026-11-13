# REM-0061-STRICT-SELECTION-REPO-HEADS

Status: `OPEN_PO_DECISION_REQUIRED`. Livello: operativo. Nessun nuovo `DEC-*`.

## Contesto

`REM-0061-CYCLE5-REDESIGN (2026-11-13)` adotta l'opzione 1 della richiesta
`REM-0061-CYCLE5-REDESIGN` (branch
`governed/decision-request-rem0061-cycle5-redesign`, commit
`df02d810a16888d3d65bec916a576177c0b7ea9f`, file
`reports/development/decision_requests/REM-0061-CYCLE5-REDESIGN.md`, sha256
`136f795399092c354562a28c4a0d232d9a9140cb8b8b6cf171bcc96138eac9c7`, PR #612).
Il punto 2 di quella decisione dice: sull'HEAD del repository il gate resta
PASS senza modificare record sigillati né manifest esistenti; se non resta
PASS, il controllo non si allenta, il ciclo si ferma e si apre una sola
richiesta con l'elenco dei casi. Questa è quella richiesta. Il codice non è
stato modificato. Nessun record sigillato e nessun manifest è stato modificato.

HEAD misurato: branch `governed/ocor-dev-rem-0061-lane-image-cache`, commit
`b9aec3e1a183f3337ddc31ffa2bac8bf530c2e48`, worktree
`.ocor/worktrees/rem-0061`, albero pulito e allineato al remoto. È l'HEAD da
cui la decisione fa partire il ciclo. Il gate eseguito su quell'albero,
`ocor-runtime/.venv/bin/python scripts/validate_evidence_input_drift.py --root .`,
esce 0 con `status` PASS, `checked_inputs` 241, `checked_tasks` 75,
`drifted_inputs` 0, `findings` vuoto. `completed_evidence_tasks` di
`reports/development/EXECUTION_STATE.json` su quell'HEAD contiene 75 task.
`discover_records` indicizza 84 task con almeno un record.

La selezione attuale è `select_most_recent` in
`scripts/validate_evidence_input_drift.py`, righe 332-364 di quell'HEAD.
L'identità di un record è `record_id`, altrimenti `commit`, altrimenti il
percorso assoluto (`str(path)`), riga 353. L'insieme dei superseduti è ogni
stringa `supersedes` dei record di quello stesso task, righe 355-359. Un
record esce se la sua identità compare in quell'insieme, riga 360. Se ne
resta più di uno, il gate ordina per `created_at` e valida solo l'ultimo,
righe 363-364. Non emette finding per le altre teste. È questo ordinamento
che tiene il gate in PASS.

La proprietà dell'opzione 1, applicata agli stessi record senza modificarli,
non resta PASS. Un record deve uscire dall'insieme corrente solo se un record
distinto, elencato, dello stesso task lo nomina in `supersedes`. Due teste
correnti sono un finding. Due record elencati che nominano lo stesso
predecessore sono un finding. Sono stati misurati, con la stessa identità e
lo stesso insieme `supersedes` del codice, solo i task in
`completed_evidence_tasks`.

- Record che nominano se stessi in `supersedes`: 0.
- Gruppi in cui almeno due record elencati dello stesso task hanno la stessa
  stringa `supersedes`: 5.
- Task il cui insieme corrente, dopo la regola attuale, ha dimensione diversa
  da 1: 22. In tutti e 22 la dimensione è maggiore di 1. Il gate ne valida
  solo il `created_at` massimo e tace sugli altri.

La causa, per i task il cui record originale resta corrente accanto a una
riqualifica, è che `supersedes` contiene un percorso relativo del repository,
mentre l'identità del record originale è il suo `commit`. Le due stringhe non
coincidono, quindi l'originale non esce. Per gli altri task le teste correnti
nominano antenati diversi: nessuna nomina l'identità dell'altra. Applicare
«due teste correnti sono un finding» farebbe fallire questi 22 task. Applicare
«due record elencati nominano lo stesso predecessore» farebbe fallire i 5
gruppi. Non esiste, su questi record, un modo di tenere il gate in PASS senza
allentare la proprietà oppure aggiungere record nuovi. Questa richiesta non
aggiunge record e non allenta il controllo.

Un solo finding di decodifica non entra nei 22. `discover_records` segnala
`OCOR-COMPENSATING-PROTECTION.json`, motivo `record task_id is not a non-empty
string`, `task_id` `OCOR-COMPENSATING-PROTECTION`. Quel task non è in
`completed_evidence_tasks`. `main` di
`scripts/validate_evidence_input_drift.py` (righe 541-543 e 595-597) non
conserva quel finding, quindi il PASS del gate non lo mostra. Non è un caso
di testa doppia.

### Gruppi con lo stesso predecessore

Due o più record elencati hanno la stessa stringa `supersedes`. Il numero è
quello dei record che la nominano.

- `OCOR-DEV-0049`, `supersedes` `e67e50d7b5efa1f551497a8018618a4e7450ab65`, 2 record: `reports/evidence/G4/OCOR-DEV-0049.requalified-rem0019-r1-marker.json`, `reports/evidence/G4/OCOR-DEV-0049.requalified-rem0032.json`.
- `OCOR-DEV-0050`, `supersedes` `OCOR-DEV-0050-requalified-repair2-b6b9f141ff0f`, 2 record: `reports/evidence/G5/OCOR-DEV-0050.rem0017-requalified.json`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0020.json`.
- `OCOR-DEV-0050`, `supersedes` `OCOR-DEV-0050-requalified-rem0026-5e1935e93126`, 4 record: `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0017-20261014.json`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0019-marker.json`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0024.json`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0032.json`.
- `OCOR-DEV-0050`, `supersedes` `OCOR-DEV-0050-regression-rem0032-integration-cdf8819019de`, 2 record: `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0019-integration-20261015.json`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0033-20261015.json`.
- `OCOR-DEV-0075`, `supersedes` `OCOR-DEV-0075-requalified-b920411a8aa5`, 2 record: `reports/evidence/G2/OCOR-DEV-0075.archive-requalified.json`, `reports/evidence/G2/OCOR-DEV-0075.fuseki-identity-requalified.json`.

Il secondo record di `OCOR-DEV-0075` non è fra le teste correnti di quel task:
un record successivo lo nomina. Il gruppo resta un finding della proprietà,
perché due record elencati nominano lo stesso predecessore.

### Teste correnti, 22 task

Per ogni task: quanti record indicizza il gate, quante teste restano, poi
ciascuna testa con `created_at`, file, `supersedes` e identità. Il gate oggi
valida solo l'ultima di ciascun elenco.

- `OCOR-DEV-0005`: 38 record, 2 teste. `2026-10-21T20:51:40.873249+00:00`, `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0035.json`, `supersedes` `OCOR-DEV-0005-requalified-rem0034-a72587020298`, identità `OCOR-DEV-0005-requalified-rem0035-cb411402de9b`. `2026-11-11T07:50:44Z`, `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0061.json`, `supersedes` `OCOR-DEV-0005-requalified-rem0059-636975eaacd7`, identità `OCOR-DEV-0005-requalified-rem0061-83d9b74648c1`.
- `OCOR-DEV-0017`: 2 record, 2 teste. `2026-09-13T04:20:00Z`, `reports/evidence/G2/OCOR-DEV-0017.json`, `supersedes` assente, identità `a2ea8f467cc47891add109fbcd1b2e8567c49399`. `2026-11-02T19:01:17Z`, `reports/evidence/G2/OCOR-DEV-0017.requalified-rem0049.json`, `supersedes` `reports/evidence/G2/OCOR-DEV-0017.json`, identità `OCOR-DEV-0017-requalified-rem0049-511091f41409`.
- `OCOR-DEV-0019`: 5 record, 2 teste. `2026-10-01T20:17:40.152278Z`, `reports/evidence/G2/OCOR-DEV-0019.requalified.json`, `supersedes` `651f52ace00b07f11cd2f6231a16f2b676fcecfa`, identità `OCOR-DEV-0019-requalified-b920411a8aa5`. `2026-11-04T03:54:55Z`, `reports/evidence/G2/OCOR-DEV-0019.requalified-rem0051.json`, `supersedes` `OCOR-DEV-0019-requalified-rem0039-95e89f7a16e5`, identità `OCOR-DEV-0019-requalified-rem0051-f2f40d030a3a`.
- `OCOR-DEV-0028`: 2 record, 2 teste. `2026-09-13T08:10:00Z`, `reports/evidence/G3/OCOR-DEV-0028.json`, `supersedes` assente, identità `c13a634b94bd1b6f6aed52e54d252746242e050d`. `2026-11-02T04:01:36Z`, `reports/evidence/G3/OCOR-DEV-0028.requalified-rem0047.json`, `supersedes` `reports/evidence/G3/OCOR-DEV-0028.json`, identità `OCOR-DEV-0028-requalified-rem0047-1ab725f3ce4c`.
- `OCOR-DEV-0029`: 2 record, 2 teste. `2026-09-13T09:10:00Z`, `reports/evidence/G3/OCOR-DEV-0029.json`, `supersedes` assente, identità `b8170f3c5ca9500d38faf95d2b2d01c7ded41850`. `2026-11-03T14:29:06Z`, `reports/evidence/G3/OCOR-DEV-0029.requalified-rem0050.json`, `supersedes` `reports/evidence/G3/OCOR-DEV-0029.json`, identità `OCOR-DEV-0029-requalified-rem0050-4b0e1db958bd`.
- `OCOR-DEV-0030`: 4 record, 2 teste. `2026-09-13T12:40:00Z`, `reports/evidence/G3/OCOR-DEV-0030.json`, `supersedes` assente, identità `c783d7c2b8b3e6824176764cbda0a683dd44c105`. `2026-11-06T22:15:56Z`, `reports/evidence/G3/OCOR-DEV-0030.requalified-rem0054.json`, `supersedes` `OCOR-DEV-0030-requalified-rem0053-90028ba369a5`, identità `OCOR-DEV-0030-requalified-rem0054-ff0508c04e5c`.
- `OCOR-DEV-0031`: 5 record, 2 teste. `2026-09-13T14:45:00Z`, `reports/evidence/G3/OCOR-DEV-0031.json`, `supersedes` assente, identità `c452a38680058b66d47588ea1dccee433d183487`. `2026-11-05T23:59:35Z`, `reports/evidence/G3/OCOR-DEV-0031.requalified-rem0053.json`, `supersedes` `OCOR-DEV-0031-requalified-rem0050-4b0e1db958bd`, identità `OCOR-DEV-0031-requalified-rem0053-90028ba369a5`.
- `OCOR-DEV-0033`: 2 record, 2 teste. `2026-09-13T16:45:00Z`, `reports/evidence/G4/OCOR-DEV-0033.json`, `supersedes` assente, identità `9a22f7392fa6190af0373e54de2d84aa5bc623d3`. `2026-11-02T04:01:36Z`, `reports/evidence/G4/OCOR-DEV-0033.requalified-rem0047.json`, `supersedes` `reports/evidence/G4/OCOR-DEV-0033.json`, identità `OCOR-DEV-0033-requalified-rem0047-1ab725f3ce4c`.
- `OCOR-DEV-0034`: 4 record, 2 teste. `2026-09-13T18:20:00Z`, `reports/evidence/G4/OCOR-DEV-0034.json`, `supersedes` assente, identità `c5fcdbde94f5eb54a81e9468f0875a79bcdf23d3`. `2026-11-06T22:15:56Z`, `reports/evidence/G4/OCOR-DEV-0034.requalified-rem0054.json`, `supersedes` `OCOR-DEV-0034-requalified-rem0052-4ecec3344165`, identità `OCOR-DEV-0034-requalified-rem0054-ff0508c04e5c`.
- `OCOR-DEV-0035`: 3 record, 2 teste. `2026-09-13T19:45:00Z`, `reports/evidence/G4/OCOR-DEV-0035.json`, `supersedes` assente, identità `ea7ecc51a8830af14b59abe51e248ed44ce06abc`. `2026-11-06T22:15:56Z`, `reports/evidence/G4/OCOR-DEV-0035.requalified-rem0054.json`, `supersedes` `OCOR-DEV-0035-requalified-rem0049-511091f41409`, identità `OCOR-DEV-0035-requalified-rem0054-ff0508c04e5c`.
- `OCOR-DEV-0036`: 2 record, 2 teste. `2026-09-13T20:05:00Z`, `reports/evidence/G4/OCOR-DEV-0036.json`, `supersedes` assente, identità `4a71e0a0f44fc75cbf19d18393e7a2affa70c9bd`. `2026-11-03T14:29:06Z`, `reports/evidence/G4/OCOR-DEV-0036.requalified-rem0050.json`, `supersedes` `reports/evidence/G4/OCOR-DEV-0036.json`, identità `OCOR-DEV-0036-requalified-rem0050-4b0e1db958bd`.
- `OCOR-DEV-0039`: 4 record, 2 teste. `2026-09-13T20:57:00Z`, `reports/evidence/G4/OCOR-DEV-0039.json`, `supersedes` assente, identità `ea9d96309cf55a54a1c7a5f89489a37381eb12b8`. `2026-11-05T09:07:11Z`, `reports/evidence/G4/OCOR-DEV-0039.requalified-rem0052.json`, `supersedes` `OCOR-DEV-0039-requalified-rem0050-4b0e1db958bd`, identità `OCOR-DEV-0039-requalified-rem0052-4ecec3344165`.
- `OCOR-DEV-0040`: 5 record, 2 teste. `2026-09-13T21:25:00Z`, `reports/evidence/G4/OCOR-DEV-0040.json`, `supersedes` assente, identità `f76f04fbe760849c393f990a7462ffb8e7b03922`. `2026-11-04T03:54:55Z`, `reports/evidence/G4/OCOR-DEV-0040.requalified-rem0051.json`, `supersedes` `OCOR-DEV-0040-requalified-rem0026-5e1935e93126`, identità `OCOR-DEV-0040-requalified-rem0051-f2f40d030a3a`.
- `OCOR-DEV-0042`: 2 record, 2 teste. `2026-09-14T00:00:00Z`, `reports/evidence/G4/OCOR-DEV-0042.json`, `supersedes` assente, identità `574a42c955a0bc9c80cb80a7c9984b6902f5cfa9`. `2026-11-05T23:59:35Z`, `reports/evidence/G4/OCOR-DEV-0042.requalified-rem0053.json`, `supersedes` `reports/evidence/G4/OCOR-DEV-0042.json`, identità `OCOR-DEV-0042-requalified-rem0053-90028ba369a5`.
- `OCOR-DEV-0045`: 2 record, 2 teste. `2026-09-14T00:00:00Z`, `reports/evidence/G4/OCOR-DEV-0045.json`, `supersedes` assente, identità `f5ce89e847676025df6fccebf3b9365a4890db30`. `2026-11-08T08:19:53Z`, `reports/evidence/G4/OCOR-DEV-0045.requalified-rem0057.json`, `supersedes` `reports/evidence/G4/OCOR-DEV-0045.json`, identità `OCOR-DEV-0045-requalified-rem0057-10e9473a9426`.
- `OCOR-DEV-0046`: 3 record, 2 teste. `2026-09-14T00:00:00Z`, `reports/evidence/G4/OCOR-DEV-0046.json`, `supersedes` assente, identità `5de9d0c9dee3d192bf2dfbac8175cd6bb72d130b`. `2026-11-08T22:24:06Z`, `reports/evidence/G4/OCOR-DEV-0046.requalified-rem0058.json`, `supersedes` `OCOR-DEV-0046-requalified-rem0050-4b0e1db958bd`, identità `OCOR-DEV-0046-requalified-rem0058-666433e5ae43`.
- `OCOR-DEV-0048`: 2 record, 2 teste. `2026-10-05T07:24:20.026029Z`, `reports/evidence/G4/OCOR-DEV-0048.json`, `supersedes` assente, identità `b2017eca792d2a7531b7cde61b5259c3644bfa11`. `2026-11-06T22:15:56Z`, `reports/evidence/G4/OCOR-DEV-0048.requalified-rem0054.json`, `supersedes` `reports/evidence/G4/OCOR-DEV-0048.json`, identità `OCOR-DEV-0048-requalified-rem0054-ff0508c04e5c`.
- `OCOR-DEV-0049`: 4 record, 3 teste. `2026-10-10T18:28:39.797507+00:00`, `reports/evidence/G4/OCOR-DEV-0049.requalified-rem0019.json`, `supersedes` `reports/evidence/G4/OCOR-DEV-0049.json@sha256:c2355d6d25714fb21b03f473c330d997e3ba4749bfc123ae490c4938c6c2683f (sigillato in df444af855e884d7783612b302e008b90105fe13, GO OCOR-DEV-0049-b14e4bf; nessun record_id)`, identità `OCOR-DEV-0049-requalified-rem0019-4c21be312beb`. `2026-10-13T22:30:15.482518+00:00`, `reports/evidence/G4/OCOR-DEV-0049.requalified-rem0019-r1-marker.json`, `supersedes` `e67e50d7b5efa1f551497a8018618a4e7450ab65`, identità `OCOR-DEV-0049-requalified-rem0019-r1-marker-6e1c4b050ac6`. `2026-10-14T18:02:41.246840+00:00`, `reports/evidence/G4/OCOR-DEV-0049.requalified-rem0032.json`, `supersedes` `e67e50d7b5efa1f551497a8018618a4e7450ab65`, identità `OCOR-DEV-0049-requalified-rem0032-04b9dcb8cc77`.
- `OCOR-DEV-0050`: 57 record, 8 teste. `2026-10-09T15:21:21.996002+00:00`, `reports/evidence/G5/OCOR-DEV-0050.rem0017-parallel-requalified.json`, `supersedes` `OCOR-DEV-0050-rem0017-requalified-98974928d914`, identità `OCOR-DEV-0050-rem0017-parallel-requalified-7fabb328e041`. `2026-10-10T08:26:39Z`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0021.json`, `supersedes` `OCOR-DEV-0050-requalified-rem0020-408eb1cb5c0e`, identità `OCOR-DEV-0050-requalified-rem0021-0e76db2ac62d`. `2026-10-13T22:30:15.482518+00:00`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0019-marker.json`, `supersedes` `OCOR-DEV-0050-requalified-rem0026-5e1935e93126`, identità `OCOR-DEV-0050-requalified-rem0019-marker-6e1c4b050ac6`. `2026-10-14T08:19:57Z`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0024.json`, `supersedes` `OCOR-DEV-0050-requalified-rem0026-5e1935e93126`, identità `OCOR-DEV-0050-requalified-rem0024-9faac98a8653`. `2026-10-14T18:02:41.246840+00:00`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0032.json`, `supersedes` `OCOR-DEV-0050-requalified-rem0026-5e1935e93126`, identità `OCOR-DEV-0050-requalified-rem0032-04b9dcb8cc77`. `2026-10-15T06:30:15.491888+00:00`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0019-integration-20261015.json`, `supersedes` `OCOR-DEV-0050-regression-rem0032-integration-cdf8819019de`, identità `OCOR-DEV-0050-regression-rem0019-integration-a72042ab7787`. `2026-10-21T20:51:40.873249+00:00`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0035.json`, `supersedes` `OCOR-DEV-0050-rem0028-integrated-0af64b5c492f`, identità `OCOR-DEV-0050-requalified-rem0035-cb411402de9b`. `2026-11-11T07:50:44Z`, `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0061.json`, `supersedes` `OCOR-DEV-0050-requalified-rem0059-636975eaacd7`, identità `OCOR-DEV-0050-requalified-rem0061-83d9b74648c1`.
- `OCOR-DEV-0061`: 2 record, 2 teste. `2026-10-26T09:15:09Z`, `reports/evidence/G6/OCOR-DEV-0061.json`, `supersedes` assente, identità `4ab9cafc0935fc62e8a8862f582330522793a885`. `2026-11-09T19:26:08Z`, `reports/evidence/G6/OCOR-DEV-0061.requalified-rem0059.json`, `supersedes` `reports/evidence/G6/OCOR-DEV-0061.json`, identità `OCOR-DEV-0061-requalified-rem0059-636975eaacd7`.
- `OCOR-DEV-0075`: 8 record, 2 teste. `2026-10-08T14:24:15.348500+00:00`, `reports/evidence/G2/OCOR-DEV-0075.archive-requalified.json`, `supersedes` `OCOR-DEV-0075-requalified-b920411a8aa5`, identità `OCOR-DEV-0075-archive-requalified-c3357b439cd1`. `2026-11-07T04:54:44Z`, `reports/evidence/G2/OCOR-DEV-0075.requalified-rem0055.json`, `supersedes` `OCOR-DEV-0075-requalified-rem0052-4ecec3344165`, identità `OCOR-DEV-0075-requalified-rem0055-351bb27eeeb0`.
- `OCOR-DEV-0082`: 35 record, 2 teste. `2026-09-13T00:40:00Z`, `reports/evidence/G2/OCOR-DEV-0082.json`, `supersedes` assente, identità `48b6d01a254d0ceb78fb9ad4ec96088e1835c5fb`. `2026-11-11T07:50:44Z`, `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0061.json`, `supersedes` `OCOR-DEV-0082-requalified-rem0059-636975eaacd7`, identità `OCOR-DEV-0082-requalified-rem0061-83d9b74648c1`.

Il punto 6 di `REM-0061-CYCLE5-REDESIGN (2026-11-13)` pone la riparazione di
`OCOR-DEV-REM-0063` dopo il verdetto di questo ciclo. Il ciclo si ferma prima
della verifica e non emette quel verdetto. Il verdetto già emesso di
`OCOR-DEV-REM-0063` resta `NO_GO`: richiesta
`OCOR-DEV-REM-0063-b7d2af2658bf-0`, HEAD
`b7d2af2658bf4b61b81816bbe7ca88543d93770c`, sha256
`e84aadada45b6c7c6d9a3b8bbef8b18925e24344880f11843f2460859c4f6ec3`, creato
`2026-11-13T06:02:09.836512Z`, verifier Codex, fornitore OpenAI, modello non
esposto dal runtime. Finding: VF-001 high bloccante
`ocor-runtime/src/ocor_runtime/c1/mcp_profile.py:240`; VF-002 high bloccante
`ocor-runtime/src/ocor_runtime/c1/mcp_profile.py:199`; VF-003 medium non
bloccante `ocor-runtime/src/ocor_runtime/c8/mcp_call.py:111`; VF-004 high
bloccante `reports/assurance/OCOR-DEV-REM-0063-RCCAD/OCOR-DEV-REM-0063.json:49`;
VF-005 high bloccante `scripts/bootstrap_ci_environment.py:344`; VF-006 low
non bloccante
`reports/assurance/OCOR-DEV-REM-0063-RCCAD/OCOR-DEV-REM-0063.json:61`.
Questa richiesta non li ripara.

VF-003 e VF-004 del verdetto `OCOR-DEV-REM-0061-b9aec3e1a183-5` non sono
stati eseguiti: il punto 3 della decisione li mette nello stesso ciclo, dopo
che il gate sull'HEAD resta PASS. Non è rimasto PASS. README, record,
merge di `main` e riqualifiche di `OCOR-DEV-0005`, `OCOR-DEV-0050` e
`OCOR-DEV-0082` non sono stati toccati. La PR #595 resta bozza e non si
integra. Non è stata avviata una campagna né una verifica.

## Opzioni

1. **Fermare la selezione stretta e riprendere il profilo MCP.** Non modificare `scripts/validate_evidence_input_drift.py`. Non modificare record sigillati né file `MANIFEST.json`. La PR #595 resta bozza e non si integra. `OCOR-DEV-REM-0061` resta bloccato, senza un altro ciclo di selezione e senza una nuova verifica di quel task. Il ciclo di riprogettazione non emette un verdetto: la riparazione di `OCOR-DEV-REM-0063` parte dall'HEAD `b7d2af2658bf4b61b81816bbe7ca88543d93770c` del verdetto `NO_GO` `OCOR-DEV-REM-0063-b7d2af2658bf-0`, sul branch `governed/ocor-dev-rem-0063-mcp-profile`, senza rebase, reset o force-push e senza toccare `governed/ocor-dev-rem-0061-lane-image-cache`. I sei finding di quel verdetto si chiudono in quel ciclo, con RED prima del codice, senza indebolire test, gate, timer, tetti, partizioni o criteri. `OCOR-DEV-REM-0060` e la PR #599 non partono. La scrittura del registro di conformità autorizzata da `FABLE52-EXTENSION-NCP-U15-ID-COLLISION (2026-11-13)` non precede quella riparazione. Nessun nuovo `DEC-*`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
2. **Riqualificare le teste storiche e poi applicare la proprietà.** Una unità governata successiva, con il primo identificativo `OCOR-DEV-REM-*` libero verificato in sola lettura, aggiunge solo record nuovi. Per ciascuno dei 22 task elencati il record nuovo nomina in `supersedes` l'identità di ogni testa corrente diversa da quella con `created_at` massimo, così che resti una sola testa, la stessa che il gate valida oggi. I cinque gruppi in cui due o più record elencati nominano lo stesso predecessore si chiudono nello stesso modo, con un solo successore distinto. Non si riscrivono record sigillati. Le voci nuove entrano nei manifest senza modificare le voci esistenti. Poi, e solo se il gate sull'HEAD del repository resta PASS, si applica la proprietà dell'opzione 1 di `REM-0061-CYCLE5-REDESIGN` sul branch `governed/ocor-dev-rem-0061-lane-image-cache` a partire da `b9aec3e1a183f3337ddc31ffa2bac8bf530c2e48`, senza rebase, reset o force-push. Se il gate non resta PASS, ci si ferma senza allentare il controllo e senza modificare i record appena aggiunti. `OCOR-DEV-REM-0063` attende il verdetto di quell'unità. La PR #595 non si integra prima di quel verdetto.
3. **Accettare un elenco storico di teste aggiuntive.** La proprietà stretta vale per ogni record nuovo. Per i soli 22 task elencati il gate accetta, come baseline enumerata e non come regola generale, la testa che oggi sceglie per `created_at`, e non emette finding per le altre teste correnti elencate qui né per i cinque gruppi che nominano lo stesso predecessore. È un allentamento circoscritto a quei record. Il resto della proprietà resta, compresi l'auto-`supersedes`, il file elencato assente e la voce di manifest con `path` o `task_id` che non sia una stringa non vuota. `OCOR-DEV-REM-0061` può allora ritentare la selezione sullo stesso branch, da `b9aec3e1a183f3337ddc31ffa2bac8bf530c2e48`, senza rebase, reset o force-push. `OCOR-DEV-REM-0063` attende il verdetto di quel tentativo.

## Raccomandazione

Opzione 1. L'opzione 3 allenta il controllo sulla storia già presente, e il
punto 2 di `REM-0061-CYCLE5-REDESIGN (2026-11-13)` vieta di allentarlo. L'opzione
2 apre un programma di riqualifica sui 22 task e sui 5 gruppi prima di poter
riprovare la proprietà, e non è necessaria per proseguire la riparazione già
decisa di `OCOR-DEV-REM-0063`. L'opzione 1 lascia il gate com'è, non tocca i
sigilli, tiene bloccato `OCOR-DEV-REM-0061` e rimette in coda quella riparazione,
perché il verdetto che doveva precederla non verrà emesso.

## Impatto e task bloccati

Finché questa richiesta è aperta sono bloccati `OCOR-DEV-REM-0061` e la
riparazione di `OCOR-DEV-REM-0063`. Restano in coda, e non partono,
`OCOR-DEV-REM-0060`, l'adozione della PR #599 e la scrittura del registro di
conformità. I task G6 restano sospesi come già deciso. La PR #595 non si
integra. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime
`NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessuna modifica a `inputs/`.
Nessun test, gate, timer, tetto, partizione o criterio è indebolito da questa
richiesta: non cambia codice.
