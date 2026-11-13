# FABLE52-PLAN-STATE-DOC-REFRESH

Status: `OPEN_PO_DECISION_REQUIRED`. Livello: operativo per i quesiti A e B (documenti derivati e file d'istruzioni),
normativo per il quesito C (erratum del Requirement Register). Origine: audit
`reports/review/OCOR_FABLE52_AUDIT_2026-11-11.md`, finding F-12, F-13, F-14, F-15, F-20, F-23, su `main`
`113f935cf6e04df460406a0b5dfea6949df6723a`. Redatto da Claude Fable 5.2 (Anthropic) in sola lettura.

## Contesto

- **Piano.** `docs/development_plan/OCOR_AI_FIRST_DEVELOPMENT_PLAN.md` dichiara 69 task (riga 42), 13 task di G2
  (riga 50) e 28 onde (riga 61); il backlog ne ha 84, 28 e 29. Il testo è fissato per hash in
  `reports/planning/OCOR_PLAN_RUN_STATE.json` e il suo generatore è escluso dai controlli perché disallineato
  (`pyproject.toml:14-21`).
- **Stato satellite.** `reports/development/METHOD_COMPLIANCE.json` riporta `BLOCKED` e una deviazione aperta che lo
  stato registra come chiusa; `INFRASTRUCTURE_STATE.json` elenca 11 servizi contro i 14 di
  `infra/services.lock.json`; `TOOLING_STATE.json` e `OCOR_MODEL_OPERATING_PROFILE.md:3-14` descrivono un host e un
  agente non più in uso; `OCOR_DELIVERY_RUNNER_CONFIG.json:11-19` e
  `reports/planning/OCOR_COMPENSATING_PROTECTION_MODE.md:5-7` descrivono una protezione assente, mentre lo stato
  registra il ruleset con 13 check. 76 voci del registro di conformità sono `IN_REMEDIATION` con l'unità già
  integrata (chiusura del registro ancora da fare).
- **File d'istruzioni per gli agenti.** `AGENTS.md:3` descrive il repository come contesto di sola revisione e
  `:19` vieta identificativi oggi approvati; `ocor-runtime/AGENTS.md:3-4` indica un obiettivo e uno stato superati.
  Entrambi sono letti a ogni iterazione.
- **Register.** Nove righe hanno una priorità che non è un solo livello (righe 122, 125-128, 144, 414, 415 e 422
  del Register v1.1; per esempio `P0/P1`, `P2/Deferred`, `P1 MVP; P0 Production`) e le tabelle hanno sei
  intestazioni diverse; gli strumenti devono trattarle caso per caso.

## Opzioni

Quesito A: documenti derivati e stato satellite. Quesito B: file d'istruzioni per gli agenti. Quesito C: priorità
composte del Register.

### Opzioni del quesito A

A1. **Una unità di riallineamento (raccomandata).** Correzione del generatore del piano fino alla parità con il
   backlog a 84 task e rigenerazione del testo con il solo percorso ammesso (riesecuzione dello script, hash
   aggiornati); `METHOD_COMPLIANCE.json`, `INFRASTRUCTURE_STATE.json` e `TOOLING_STATE.json` rigenerati dai dati
   correnti oppure sostituiti da un rinvio allo stato di esecuzione; `OCOR_DELIVERY_RUNNER_CONFIG.json` e la nota
   sulla protezione allineati al ruleset registrato; stati del registro di conformità portati avanti alla chiusura
   (punto 4.g). I controlli S01, S03, S04 e S10 passano senza voci registrate e diventano `BLOCKING`. Stima: 3
   iterazioni.
A2. **Sola nota di superamento.** Ogni file riceve in testa una riga «storico, non aggiornato»; i controlli restano
   consultivi con le voci registrate.
A3. **Nessuna modifica.**

### Opzioni del quesito B

B1. **Aggiornamento dei due file con testo fisso approvato dal PO (raccomandata).** `AGENTS.md`: l'intestazione
   descrive il repository com'è (norma, runtime, evidenza), la regola 4 rinvia al Decision Register vigente, la
   struttura elenca `ocor-runtime/`, `docs/`, `scripts/`, `deploy/`; le regole assolute su `inputs/`, claim e
   segreti restano parola per parola. `ocor-runtime/AGENTS.md`: rinvio al file di radice e al backlog. Il testo
   nuovo è allegato alla decisione; nessun agente lo redige.
B2. **Solo `ocor-runtime/AGENTS.md`**, che è il più distante dallo stato reale.
B3. **Nessuna modifica.**

### Opzioni del quesito C

C1. **Erratum nella stessa unità dell'erratum della matrice (raccomandata).** `NCP-U14` aggiunge all'erratum una
   tabella «priorità per release» per le nove righe, senza cambiare il testo del Register; gli strumenti
   leggono la tabella.
C2. **Nuova versione del Register con priorità atomiche**, con promozione governata e nuovo sigillo.
C3. **Nessuna modifica.**

## Impatto a cascata

A1: `scripts/build_ocor_development_plan.py`, testo del piano, `OCOR_PLAN_RUN_STATE.json` (hash), i quattro file di
stato, `reports/development/ALIGNMENT_BASELINE.json` (voci tolte, modalità cambiate). B1: due file d'istruzioni;
nessun validatore li ha fra gli input sigillati. C1: file dell'erratum di `NCP-U14` e `validate_runtime_evidence.py`
(lettura della tabella). Nessun requisito cambia testo, priorità o release.

## Criteri di accettazione verificabili

- `python3 -I scripts/validate_alignment_invariants.py --root .` senza voci S01, S03, S04, S10.
- `reports/tests/test_backlog_generator_reality_parity.py` verde con il generatore rientrato nel controllo dei tipi.
- `grep -n "non è un progetto software\|EV-001 to EV-035" AGENTS.md ocor-runtime/AGENTS.md` senza risultati; le sette
  regole assolute di `AGENTS.md` identiche byte per byte al testo precedente.
- Per ciascuna delle nove righe, la tabella dell'erratum dà una priorità in `P0`-`P3` per ogni release nominata.

Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
