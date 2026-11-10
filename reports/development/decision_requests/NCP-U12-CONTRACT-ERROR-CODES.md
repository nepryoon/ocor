# NCP-U12-CONTRACT-ERROR-CODES

Status: `DECIDED_BY_PO`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0060` (NCP-U12 di
`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, test; branch `governed/ocor-dev-rem-0060-ncp-u12-tests`, head `4aa955c`) e la
voce `NCR-TESTS-004` di `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`. Implementatore: Claude Code
(Anthropic), implementatore di riserva.

## Contesto

- La decisione `NCP-U12-TEST-REALIGNMENT-SCOPE (2026-11-10)`, opzione D1, chiede all'unità di inventariare i reason
  code chiusi che ADD v1.3, LLD v1.1 e i contratti di LLD v1.1 §0.2 definiscono per C1-C8 e la memoria governata, e di
  verificare che per ciascuno almeno un test negativo asserisca `reason_code` uguale a quel codice sul componente, «con
  RED dove il codice non è prodotto». Le decisioni `NCP-U12-UNPRODUCED-REASON-CODES (2026-11-10)` (A1 e B2),
  `NCP-U12-REASON-CODE-ENTRIES-PLAN (2026-11-10)` (A1 e B1) e `NCP-U12-C6-COMMIT-REFUSAL-TRANSITIONS (2026-11-10)` (A1)
  hanno deciso che cosa fa l'unità per i codici non prodotti allora noti, codice per codice; per C6 conta soltanto il
  campo `reason_code` del record della transizione FSM (B2).
- La revisione preventiva dell'unità (`PRE-CAMPAIGN-REVIEW (2026-10-26)`, richiesta
  `OCOR-DEV-REM-0060-3d6a01d329d1-pre`, head `3d6a01d`) ha rilevato che l'inventario non comprendeva gli insiemi chiusi
  `error_codes` dei tre contratti incorporati in ADD v1.3. Il testo di D1 li comprende («i contratti»); l'unità li ha
  aggiunti al commit `4f062b2` (tabella `CLOSED_REASON_CODES` di `ocor-runtime/tests/tasks/test_ocor_dev_rem_0060.py`),
  senza ripetere i codici già inventariati per lo stesso componente:
  - MCP Governed Tool Contract, C8 (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md` righe
    1765-1777, §3.5; `FR-108`, P0);
  - Action Type Contract, C6 (righe 2332-2351, §3.7; `FR-077` e `FR-083`, P0);
  - Event Subscription Contract, C5 (righe 2666-2673, §3.8; `FR-069` e `FR-074`, P0);
  - con la stessa lettura dei codici già inventariati in prosa (C3 riga 2569, C6 riga 2753) e del fail state di
    `TB-CXT-03` (riga 173): C5 `PRINCIPAL_BINDING_MISMATCH` (riga 844) e il fail state `SCENARIO_ISOLATION_VIOLATION` di
    `TB-CXT-07`, Scenario sandbox (riga 177, C7; `FR-092`, P0). I fail state di `TB-CXT-04`, `TB-CXT-05` e `TB-CXT-06`
    (righe 174-176) attraversano tutti i componenti e i loro codici sono inventariati sui componenti i cui contratti li
    definiscono; quello di `TB-CXT-09` (riga 179, `RELEASE_REJECTED`) è del confine di supply chain, non di un
    componente C1-C8. Il modulo lo registra in `NOT_REASON_CODES`.
- Nello stesso ciclo la scansione statica accredita un codice solo dove la condizione di un assert confronta un
  `reason_code` per uguaglianza (commit `64f53f8` RED, `cfedf38` GREEN; nessun codice dell'inventario precedente diventa
  scoperto), e la tabella `FALSE_CREDITS` toglie sette crediti verificati a mano che non asseriscono il codice sul
  componente (C5 `RELEASE_MISMATCH` e `CONTROL_PLANE_UNAVAILABLE` asseriti su errori di C3 e C4; C6 `AUDIT_UNAVAILABLE`
  detail code della memoria governata; C6 `EXECUTION_UNKNOWN`, `COMPENSATION_UNKNOWN` e `COMPENSATION_INDETERMINATE`
  asseriti su record di audit della reconciliation, non su record di transizione FSM).
- Dei codici nuovi, tre sono prodotti dal componente e hanno ricevuto un test negativo senza questione (commit
  `4aa955c`): C6 `EMERGENCY_STOP_ACTIVE` sulla transizione `ACT-T23a` (`docs/OCOR_LLD_v1.1.md` riga 295); C5
  `SUBSCRIPTION_NOT_FOUND` e `CONTROL_PLANE_UNAVAILABLE` sul backbone reale. I restanti diciannove non sono prodotti dal
  componente mantenuto (esito del controllo di copertura al commit `4aa955c`, fingerprint `2d6a71433f77`):
  - C8, `APPROVAL_EXPIRED`, `COMPENSATION_REQUIRED`, `COMPENSATION_UNKNOWN` (righe 1769, 1776, 1777): compaiono solo nel
    testo dello schema di `ocor-runtime/src/ocor_runtime/c8/tool_contract.py` (righe 361, 368-369); nessun percorso del
    tool runtime li solleva;
  - C6, codici assenti dal pacchetto `ocor-runtime/src/ocor_runtime/c6`: `POLICY_DENIED`, `AUTHORITY_MISSING`,
    `APPROVAL_REQUIRED`, `STALE_CONTEXT`, `PROJECTION_NOT_READY`, `RELEASE_MISMATCH`, `CAPABILITY_LEASE_EXPIRED` (righe
    2332-2339, 2351); il motore rifiuta con il proprio vocabolario (per esempio `AUTHORITY_DENIED`, `APPROVAL_MISSING`,
    `DECISION_MISSING`, cause `STALE_<campo>` e `LEASE_*`, `c6/engine.py` righe 861, 883-895, 1091-1095);
  - C6, codici prodotti ma senza transizione FSM che li registri: `APPROVAL_EXPIRED` (riga 2335) è la causa del rifiuto
    del Human Gate (`c6/human_gate.py` riga 594, `c6/engine.py` righe 888-895), ma il motore non applica `ACT-T09b`
    (LLD v1.1 riga 271): il RED del commit `4f062b2` (`ocor-runtime/tests/tasks/test_ocor_dev_rem_0060.py` righe
    730-747) mostra l'azione ferma in `APPROVAL_PENDING`; `AUDIT_UNAVAILABLE` (riga 2341) è un rifiuto del fence di
    dispatch (`c6/dispatch.py` riga 643) che il motore rilancia senza transizione, perché solo le cause di stop e di
    drift chiudono l'azione (`c6/engine.py` righe 539-542, 1090-1096); `EXECUTION_UNKNOWN`, `EXECUTION_INDETERMINATE`,
    `COMPENSATION_UNKNOWN` e `COMPENSATION_INDETERMINATE` (righe 2342-2345) sono stati dell'`OutcomeReconciler` e
    reason code dei suoi record di audit (`c6/safety.py` righe 1140-1148, 1295, 1389-1408) e `EXECUTION_UNKNOWN` è anche
    il reason code dell'errore del motore (`c6/engine.py` righe 795-816), ma il motore non applica `ACT-T18a`,
    `ACT-T18b`, `ACT-T21c`, `ACT-T24` né `ACT-T25` (LLD v1.1 righe 282-283, 291, 297-298): applica soltanto `ACT-T01`,
    `T04`, `T05`, `T06`, `T08`, `T10a`, `T10b`, `T11`, `T12`, `T13`, `T22`, `T23a`, `T23b`, `T26`, `T27`, `T29` e `T30`;
  - C5, `AUTHORITY_MISSING` e `RELEASE_MISMATCH` (righe 2667, 2669): compaiono solo nel testo dello schema di
    `ocor-runtime/src/ocor_runtime/c5/subscription.py` (righe 116, 118); il backbone rifiuta un subscriber non
    autenticato con `POLICY_DENIED` (`c5/backbone.py` riga 408);
  - C7, `SCENARIO_ISOLATION_VIOLATION` (riga 177): assente dal pacchetto `ocor-runtime/src/ocor_runtime/c7`.
- Le decisioni precedenti dell'unità descrivono i codici che nominano; questi diciannove non sono descritti da alcuna
  opzione decisa, e la regola vigente per le decision request chiede una nuova richiesta. Le questioni collegate allo
  stesso punto sono raccolte qui: che cosa fa l'unità per i codici non prodotti e come si pianificano le voci nuove
  (quesito A), il budget di iterazioni dell'unità che questa estensione consuma (quesito B) e il perimetro
  dell'inventario per i codici in prosa e per i fail state dei trust boundary (quesito C).
- Budget: iterazione 7 di stima 3 (stop a 9, `NCP-THROUGHPUT-RULES (2026-11-05)` punto 2). Restano da eseguire, dopo la
  decisione, l'attuazione, la campagna qualificante, la verifica indipendente (fino a due cicli di riparazione) e
  l'integrazione.

## Opzioni

Quesito A: che cosa fa l'unità per i diciannove codici chiusi che il componente mantenuto non produce, e come si
pianificano. Quesito B: il budget di iterazioni dell'unità. Quesito C: il perimetro dell'inventario.

### Opzioni del quesito A

A1. **Nuove voci del registro pianificate in NCP-U15, unità di soli test (raccomandata).** I codici entrano nel registro
   di conformità come voci nuove `OPEN`, con il primo identificativo libero del componente al momento della
   registrazione, gravità secondo `severity_rule` (`HIGH`: ciascun gruppo viola un requisito P0) e le ancore di questa
   richiesta: una voce C8 (i tre codici del Tool Contract, `FR-108`); una voce C6 per i sette codici assenti dal
   motore (`FR-077`); una voce C6 per i sei codici prodotti senza transizione FSM (`FR-077`, `FR-083`), con `red_tests`
   il test del commit `4f062b2` citato con commit, percorso e righe; una voce C5 (i due codici del Subscription
   Contract, `FR-069`, `FR-074`); una voce C7 (`SCENARIO_ISOLATION_VIOLATION`, `FR-092`). Le cinque voci hanno
   `plan_unit` `NCP-U15`, che le aggiunge a `resolves` con un criterio di accettazione ciascuna, e `blocks` con i task G6
   che esercitano il comportamento: C8 `OCOR-DEV-0064` e `OCOR-DEV-0065`; C6 `OCOR-DEV-0063`; C5 `OCOR-DEV-0064` e
   `OCOR-DEV-0065`; C7 `OCOR-DEV-0060` e `OCOR-DEV-0065`; la stima di `NCP-U15` passa da 3 a 5 iterazioni e
   `plan_summary` si aggiorna di conseguenza. Nel modulo dell'unità il controllo di copertura elenca i diciannove
   codici come divergenze note con l'identificativo della voce, e fallisce per ogni altro codice scoperto; il RED di
   `APPROVAL_EXPIRED` esce dalla suite in un commit successivo e resta nella storia del branch come RED della voce.
   Nessun file di runtime cambia; nessuna riqualifica aggiuntiva.
A2. **Estensione di NCP-U12 ai componenti.** L'unità produce i codici nei componenti con RED e GREEN: `code_paths` si
   estende a `c5/backbone.py`, `c5/subscription.py`, `c6/engine.py`, `c6/dispatch.py`, `c6/safety.py`,
   `c7/runtime.py` e al tool runtime di C8, con le riqualifiche dei task i cui ultimi record hanno quei file fra gli
   input; `NCR-TESTS-004` si risolve con la copertura completa.
A3. **Voce non risolta da NCP-U12.** `NCR-TESTS-004` resta `IN_REMEDIATION` con la copertura dei codici prodotti; i
   diciannove codici restano nel controllo come scoperti e il controllo di copertura non entra nella suite qualificante
   finché non passa.

### Opzioni del quesito B

B1. **Estensione del budget (raccomandata).** Per `OCOR-DEV-REM-0060` sono autorizzate fino a quattro iterazioni oltre
   la nona (dalla decima alla tredicesima), solo per l'attuazione di questa decisione, la campagna qualificante, la
   verifica indipendente con al massimo due cicli di riparazione e l'integrazione. Resta lo stop anticipato per due
   iterazioni consecutive senza avanzamento; se le iterazioni finiscono senza merge, l'unità si ferma e apre una
   decision request di livello normativo con lo stato del lavoro.
B2. **Nessuna estensione.** Resta lo stop a 9; se l'unità non si integra entro la nona iterazione si ferma con una
   decision request.

### Opzioni del quesito C

C1. **Perimetro come al commit `4f062b2` (raccomandata).** L'inventario comprende gli insiemi chiusi `error_codes` dei
   tre contratti di ADD v1.3, i codici che ADD v1.3 e LLD v1.1 nominano in prosa per un componente (come C5
   `PRINCIPAL_BINDING_MISMATCH`) e i fail state dei trust boundary posseduti da un solo componente (`TB-CXT-03` per C8,
   `TB-CXT-07` per C7); i fail state di `TB-CXT-04`, `TB-CXT-05`, `TB-CXT-06` e `TB-CXT-09` restano fuori, con il
   motivo registrato in `NOT_REASON_CODES`.
C2. **Solo gli insiemi chiusi dei contratti e i codici in prosa.** I fail state dei trust boundary escono
   dall'inventario, compreso `TB-CXT-03` (C8 `CAPABILITY_DENIED` resta inventariato attraverso il Tool Contract); la
   voce C7 di A1 non si crea.

## Raccomandazione

Opzioni A1, B1 e C1. A1 tratta i codici nuovi come le decisioni già prese per gli altri codici chiusi (voci `OPEN`
pianificate in `NCP-U15`, unità di soli test, nessun file di runtime), distingue per C6 i codici assenti da quelli
prodotti senza transizione FSM, come B2 di `NCP-U12-UNPRODUCED-REASON-CODES` richiede, e adegua la stima di `NCP-U15` al
lavoro che riceve; A2 porterebbe in un'unità di test modifiche di quattro componenti; A3 lascerebbe la suite con un
controllo permanentemente rosso. B1 evita un arresto prevedibile dovuto al solo completamento dell'inventario, con gli
stessi limiti già usati per `OCOR-DEV-REM-0059`. C1 applica ai codici nuovi la stessa lettura già usata per
l'inventario dell'unità (codici in prosa e `TB-CXT-03`), ed è la lettura più restrittiva.

## Impatto e lavoro bloccato

- Bloccati in attesa della decisione: le voci nuove del registro e quindi la forma finale del controllo di copertura,
  il GREEN di `NCR-TESTS-004`, la suite completa, la campagna qualificante e la verifica dell'unità.
- Non bloccati: il resto dell'unità secondo le decisioni in vigore (autocontrollo, scansioni, gate sui commit già
  fatti).
- Riqualifiche: con A1 o A3 nessuna nuova; con A2 quelle dei task i cui ultimi record hanno fra gli input i file di
  runtime toccati.
- Nessun nuovo `DEC-*`; ADD, LLD, contratti, schemi, limiti e claim invariati (`E1=0`, `E2=0`, `Verified=0`, runtime
  `NOT_ESTABLISHED`, PoC e Production `NO-GO`).

## Disposition del Product Owner — 2026-11-10

`NCP-U12-CONTRACT-ERROR-CODES (2026-11-10)` — decisione del PO,
 decisa su delega completa del PO, modello `grok-4.7`, effort `xhigh`.
Opzioni adottate: **A1, B1, C1**, esattamente come descritte in questa richiesta
al commit `ed75f85493f3c8814c08e0c162c4dd25d26c962e`, sha256
`c6493ed79363e14aa7213e05fbe3b2dc7ee8e160abd231e42ede7bd89ef11223`.

Cinque nuove voci `OPEN` `HIGH`, con i primi identificativi liberi verificati,
pianificate in NCP-U15 (stima 3 → 5), e diciannove codici come divergenze note nel
controllo di copertura. Il RED di `APPROVAL_EXPIRED` resta nella storia ed esce dalla
suite. Perimetro C1 confermato. Per REM-0060 estensione fino alla tredicesima
iterazione, massimo due cicli di riparazione e stop anticipato invariati.
Nessun file di runtime cambia; nessuna riqualifica aggiuntiva.
Claim invariati: E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED,
PoC e Production NO-GO. Nessun nuovo DEC.
