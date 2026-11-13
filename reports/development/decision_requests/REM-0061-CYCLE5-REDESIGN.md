# REM-0061-CYCLE5-REDESIGN

Status: `DECIDED_BY_PO`. Livello: operativo. Nessun nuovo `DEC-*`.
Opzione adottata: **1**, come raccomandato, dalla decisione
`REM-0061-CYCLE5-REDESIGN (2026-11-13)`. Il testo della richiesta,
sotto questa disposition, resta quello aperto al commit
`df02d810a16888d3d65bec916a576177c0b7ea9f`, sha256
`136f795399092c354562a28c4a0d232d9a9140cb8b8b6cf171bcc96138eac9c7`.

## Disposition

Il PO adotta l'opzione 1 come scritta nel file aperto. L'attuazione si è
fermata al controllo sull'HEAD
`b9aec3e1a183f3337ddc31ffa2bac8bf530c2e48` del branch
`governed/ocor-dev-rem-0061-lane-image-cache`. Il gate
`scripts/validate_evidence_input_drift.py` su quell'albero resta PASS
(`checked_inputs` 241, `checked_tasks` 75, `findings` vuoto). La proprietà
dell'opzione 1, applicata agli stessi record senza modificarli, non resta
PASS: 22 task completati hanno più di una testa corrente e 5 gruppi hanno
due o più record elencati che nominano lo stesso predecessore. Il controllo
non è stato allentato. Non è stato modificato
`scripts/validate_evidence_input_drift.py`. Non sono stati modificati record
sigillati né manifest. Non sono stati allineati README e record. Non è stato
eseguito il merge di `main` né la riqualifica di `OCOR-DEV-0005`,
`OCOR-DEV-0050` e `OCOR-DEV-0082`. Non è stata avviata una campagna né una
verifica. La PR #595 resta bozza e non si integra.

I casi misurati sono nella richiesta
`REM-0061-STRICT-SELECTION-REPO-HEADS`, commit
`74e84ddc99564384eda981ad84e8957a90596dcf`, sha256
`fc7c8d7e73a92322639e869a581731ec347f486108c11ee9642d7561c1a60544`,
PR #614 bozza e non da integrare. Finché quella richiesta non è decisa, non
parte la riparazione di `OCOR-DEV-REM-0063`: il punto 6 di questa decisione
la pone dopo un verdetto che questo ciclo, fermato prima della verifica, non
emette.

Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`,
PoC e Production `NO-GO`. Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`.

## Contesto

Il verdetto `OCOR-DEV-REM-0061-b9aec3e1a183-5` è `NO_GO` sull'HEAD
`b9aec3e1a183f3337ddc31ffa2bac8bf530c2e48` del branch
`governed/ocor-dev-rem-0061-lane-image-cache` (PR #595, bozza). Lo sha256 del
file di verdetto è
`2cbd38bc26e304419c8feeaaeb07435c1e8a22fc888b5e12f0d86f9b63174932`.
Il verifier è Claude Code, modello `claude-opus-5-5`, fornitore Anthropic,
in un processo separato, non avviato dall'implementatore. Il fornitore è
diverso da xAI e da OpenAI, come richiede `REM-0061-CYCLE5-INDEPENDENT
(2026-11-13)` punto 3. Il verdetto è nel registro del loop. Giudica il task
intero all'HEAD, non solo i due finding del ciclo 4.

L'implementatore di ogni commit del branch, cicli 4 e 5 compresi, è Grok Build,
modello grok-4.7, fornitore xAI. Codex (OpenAI) è contato fra gli implementatori
da `REM-0061-REPAIR-BUDGET (2026-11-12)` e non ha commit sul branch. Il revisore
preventivo del ciclo 5 è Cursor, modello `cursor-grok-4.6-xhigh` (xAI, riserva),
richiesta `OCOR-DEV-REM-0061-9edaf76cb3e7-pre`, esito `NO_BLOCKING_FINDINGS`.

`REM-0061-CYCLE5-INDEPENDENT (2026-11-13)` ha autorizzato questo solo ciclo 5,
in sostituzione del «nessun ciclo 5» di `REM-0061-CYCLE3-MERIT-NO-GO (2026-11-12)`.
Il punto 5 della stessa decisione dice che, con `NO_GO` anche per un difetto
nuovo, non c'è un ciclo 6: il task resta bloccato e si apre una decision request
di riprogettazione, con opzioni numerate. Questa è quella richiesta. Il codice
non è stato modificato dopo il verdetto. La PR #595 non si integra.

Il finding bloccante è ancora la stessa classe, non un caso nuovo isolato. La
proprietà chiesta da `REM-0061-CYCLE3-MERIT-NO-GO (2026-11-12)` punto 2 è: quando
il manifest elenca per un task un record successore, il gate o lo seleziona dopo
averlo validato per intero, o riporta un finding per quel task; in nessun
percorso dà PASS sul predecessore. I cicli 3, 4 e 5 hanno chiuso i casi nominati
dai verdetti precedenti. `select_most_recent` in
`scripts/validate_evidence_input_drift.py` costruisce ancora l'insieme dei
superseduti con ogni stringa `supersedes` e toglie dall'insieme corrente ogni
record il cui identificativo vi compare, senza esigere che il successore sia un
record distinto dello stesso task e senza segnalare chi esce.

- VF-001, high, bloccante, `scripts/validate_evidence_input_drift.py` riga 355.
  Un record elencato con `supersedes` uguale al proprio `record_id` entra
  nell'insieme dei superseduti ed esce da quello corrente. Resta il
  predecessore, che è selezionato e passa, anche se il successore ha un digest
  errato. Lo stesso accade con due successori che supersedono entrambi lo stesso
  predecessore: il meno recente, con digest errato, non è validato e non produce
  finding. Il generatore di perturbazioni copre `supersedes` assente, vuoto o
  che non indica un record elencato, e non il caso in cui `supersedes` nomina il
  record stesso. All'HEAD nessun record del repository supersede se stesso: il
  PASS del repository non chiude la classe.
- VF-002, medium, non bloccante, stessa funzione di ammissione del manifest,
  riga 216. Una voce con nome canonico e `task_id` null, vuoto o numerico, e
  file assente, è scartata senza finding e il gate dà PASS. Un `task_id` con
  spazio finale o in minuscolo produce un finding che `main` conserva solo per i
  task completati o per `task_id` vuoto, quindi anche quel caso dà PASS. Non
  lega un task completato. È lo stesso fail-open: una voce elencata sparisce e
  non resta traccia.
- VF-003, low, non bloccante, evidenza. `README.md` del record descrive ancora
  il ciclo 4. Il record non cita i verdetti dei cicli 3 e 4 e
  `roles.verifier` indica ancora il verifier del ciclo 1.
- VF-004, low, non bloccante, integrazione. Su `origin/main` i record
  `*.requalified-rem0062.json` di `OCOR-DEV-0005`, `OCOR-DEV-0050` e
  `OCOR-DEV-0082` supersedono lo stesso antenato superseduto dai record
  `rem0061` di questo branch. `git merge-tree` segnala conflitti sui manifest
  G0, G2 e G5 e su `reports/planning/OCOR_PLAN_RUN_STATE.json`. La PR #595 è
  `DIRTY`. Dopo un merge non distruttivo le tre catene avrebbero due teste, e il
  difetto di VF-001 sceglierebbe in silenzio la più recente.

La campagna FOUR_LANE del verifier sull'HEAD esatto è PASS: 5826 test raccolti
ed eseguiti, zero skip, zero fallimenti, quattro corsie, teardown PASS, residuo
vuoto, 1815,304 s sotto il tetto di 5400 s. Non chiude i finding. I controlli
locali rieseguiti dal verifier sono PASS. G15 non è eseguito: il validatore di
allineamento non è su `origin/main` né all'HEAD.

`OCOR-DEV-REM-0060` resta in coda fino al merge di `OCOR-DEV-REM-0061`.
`OCOR-DEV-REM-0063` non è bloccato da questa richiesta:
`REM-0061-CYCLE5-PRIORITY (2026-11-13)` punto 3 lo fa riprendere subito dopo
l'apertura di questa richiesta, dal commit
`7ecbee1ea267ff64d7ffa5f57fdb0fbdf07a7e01`. I task G6 restano sospesi come già
deciso. L'adozione della PR #599 resta dopo un GO di `OCOR-DEV-REM-0061`.
La diagnosi e l'azione minima sono nel record
`reports/development/OCOR_DEV_REM_0061_ESCALATION.md` di questo stesso commit.

## Opzioni

1. **Un solo ciclo di riprogettazione della selezione.** Autorizzare un solo ciclo, sul branch `governed/ocor-dev-rem-0061-lane-image-cache`, a partire dall'HEAD `b9aec3e1a183f3337ddc31ffa2bac8bf530c2e48`, senza rebase, reset o force-push. Non è un sesto giro sui casi nominati: si sostituisce la selezione del record corrente con una funzione totale. Per ogni record elencato di un task completato il gate o lo valida per intero o emette un finding per quel task. Un record esce dall'insieme corrente solo se un record distinto, elencato, dello stesso task, lo nomina in `supersedes`. Sono finding, e non un PASS sul predecessore: `supersedes` che nomina il record stesso; due record elencati che nominano lo stesso predecessore; due teste correnti; un record elencato che esce senza un successore distinto; una voce di manifest con `path` o `task_id` che non sia una stringa non vuota; un file elencato assente. Il criterio di accettazione è questa proprietà. I casi del verdetto ne sono esempi. Un generatore della sola libreria standard copre la classe, comprese le combinazioni a coppie, e per ogni controllo nuovo una sonda di mutazione mostra che, tolto il controllo, almeno un test fallisce. Sull'HEAD del repository il gate resta PASS senza modificare record sigillati né manifest esistenti. Se non resta PASS, il controllo non si allenta: si ferma questo ciclo e si apre una sola richiesta con l'elenco dei casi. Nello stesso ciclo si allineano README e record ai verdetti dei cicli 3, 4 e 5, e si rigenerano le riqualifiche di `OCOR-DEV-0005`, `OCOR-DEV-0050` e `OCOR-DEV-0082` con `supersedes` verso la testa corrente di `main`, rieseguite sull'HEAD integrato nel branch. Poi gate locale, controllo meccanico dei digest, revisione preventiva se richiesta, campagna completa nuova e verifica indipendente sull'HEAD esatto. Il verifier è solo Claude Code oppure Antigravity. Non si applicano `VERIFIER-RISERVA (2026-11-11)` né il punto 2 di `VERIFIER-CLAUDE-OPUS (2026-11-12)`. Un verdetto xAI o OpenAI non integra e non chiude. Se il verdetto è ancora `NO_GO`, non c'è un altro ciclo: il task resta bloccato e la PR #595 non si integra.
2. **Separare la cache dal gate, senza riscrivere il branch.** Non si fa rebase, reset o force-push di `governed/ocor-dev-rem-0061-lane-image-cache`. La PR #595 resta bozza e non si integra. Si apre una remediation nuova, con il primo identificativo `OCOR-DEV-REM-*` libero verificato in sola lettura, dal `main` corrente, il cui solo perimetro è la proprietà dell'opzione 1. La cache immagini in sola lettura resta sul branch attuale finché una decisione successiva non ne autorizza il trasporto. Se il trasporto è tentato in questa opzione, avviene con un branch nuovo da `main` e solo se il diff della cache si applica pulito; altrimenti ci si ferma, senza riscrivere la storia. `OCOR-DEV-REM-0060` resta in coda finché non esiste un merge che chiude il provisioning delle immagini di corsia. La campagna del branch attuale non si trasferisce.
3. **Fermare l'unità.** Nessun codice nuovo. La PR #595 resta bozza e non si integra. `OCOR-DEV-REM-0061` resta bloccato. `OCOR-DEV-REM-0060` resta in coda, senza un'altra strada per il provisioning delle immagini di corsia. Il difetto non è su `main`: il gate di `main` non cambia. `OCOR-DEV-REM-0063` prosegue come già deciso.

## Raccomandazione

Opzione 1. La proprietà di accettazione è stabile da due verdetti di merito consecutivi, e i cicli 3, 4 e 5 hanno mostrato che aggiungere i casi nominati non chiude la classe. La campagna sull'HEAD è verde e non va rifatta per separare la cache. VF-004, al primo merge, riprodurrebbe due teste sulla stessa catena: va chiuso nello stesso ciclo, insieme al fail-open del manifest. L'opzione 2 lascia `OCOR-DEV-REM-0060` senza il provisioning che questa unità doveva consegnare e apre una seconda campagna sullo stesso comportamento. L'opzione 3 non sblocca nulla che dipenda da `OCOR-DEV-REM-0061`.

## Impatto e task bloccati

Bloccati da questa richiesta: `OCOR-DEV-REM-0061` (nessun ciclo 6, PR #595 non integrata) e, finché `OCOR-DEV-REM-0061` non è unito, `OCOR-DEV-REM-0060`. Non sono bloccati: `OCOR-DEV-REM-0063`, che riprende dal commit `7ecbee1ea267ff64d7ffa5f57fdb0fbdf07a7e01`, e la scrittura del registro autorizzata da `FABLE52-EXTENSION-NCP-U15-ID-COLLISION (2026-11-13)` opzione 1, che resta in coda dopo il profilo MCP. I task G6 restano sospesi come già deciso. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessuna modifica a `inputs/`. Nessun test, gate, timer, tetto, partizione o criterio è indebolito da questa richiesta: non cambia codice.
