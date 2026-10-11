# REM-0022-KAFKA-ORACLE-PLAN-SCOPE

Status: `OPEN_PO_DECISION_REQUIRED` — 2026-10-11.

## Contesto e controllo riproducibile

REM-0022 è autorizzata nello stato versionato di `origin/main@63184cb` per correggere
il teardown di `spikes/kafka_delivery/oracle.py` e del lifecycle C5. Il codice e i
22 nuovi test sono sul commit `0af7a8d2a0bd51fbfd7630ffb506842e115bc690` del branch
`governed/ocor-dev-rem-0022-kafka-resource-lifecycle`.

RED: quattro fallimenti reali dei due helper. GREEN: 243 casi mirati e 1.806 casi
nella regressione completa, zero failure/error/skip, raccolta/JUnit esatti,
inventari Docker identici prima/dopo e teardown di sessione PASS. Non è un GO di
integrazione o un sigillo. Record nuovi di riqualifica per 0019/0040/0050 e raw
log sono candidati; originali sigillati immutati.

Il comando sul vero base di integrazione
`python scripts/validate_ocor_development_plan.py --authorized-extension --base-ref 63184cb250c5b385b06c98c69a227937b8ae8fb4`
ha restituito 36 PASS, 1 FAIL, 2 NOT_EXECUTED opzionali. L'unico path respinto nel
primo tentativo, prima di questa richiesta, è `spikes/kafka_delivery/oracle.py`
(check `authorized planning-only diff`). La nuova richiesta aggiunge un ulteriore
path da registrare esplicitamente se deve essere integrata con il codice.

Il backlog di 0019 già assegna `spikes/kafka_delivery/` al task; tuttavia lo scope
versionato di REM-0022 autorizza **«Surgical plan-allowlist extension only for the
new remediation test/evidence paths»**. Non considero quella clausola un permesso
ad aggiungere anche il sorgente. Non modifico il controllo `allowed`, non uso HEAD
come base del gate governato e non cambio il ruleset/workflow.

## Opzioni e raccomandazione

1. Autorizzare l'aggiunta puntuale all'allowlist di soli
   `spikes/kafka_delivery/oracle.py` e
   `reports/development/decision_requests/REM-0022-KAFKA-ORACLE-PLAN-SCOPE.md`,
   esclusivamente per questo change set. Nessuna wildcard o modifica del validator;
   riallineamento del self-hash, nuova riqualifica di 0050 sul validator finale e
   gate/verifiche indipendenti nuovamente acquisiti prima della PR. **Raccomandata**:
   il sorgente è già nel perimetro della correzione autorizzata; manca il suo
   riconoscimento meccanico nel gate di piano.
2. Mantenere la restrizione: REM-0022 resta bloccata. Una separazione in branch
   `task/0019` e `task/0040` richiederebbe anche una disposition per le nuove
   riqualifiche: lo scope ordinario del task non ammette i nuovi nomi dei record,
   mentre i record sigillati non possono essere riscritti. Nessun bypass tramite
   base HEAD, cambio di nome o merge di un sorgente con deriva non qualificata.

## Impatto e ripresa

Bloccati solo REM-0022 e le dipendenze REM-0019/REM-0017/integrazione 0049; G6 resta
bloccato dalle remediation già registrate. Il WIP 0056 e 0057 restano raggiungibili.
Non si richiede una nuova DEC o una variazione semantica; l'approvazione richiesta
è una deroga puntuale alla restrizione del change set versionato.

Dopo opzione 1: riprendere dal WIP esatto, applicare le due sole entry, riqualificare
0050 e rifare i gate sulla main reale. Claude Code verifica REM-0022/0019/0040;
Cursor/Grok verifica 0050 perché toccato dall'implementatore di riserva Claude.
Entrambi i GO sullo stesso HEAD precedono sigillo/PR/merge. Nessun verifier avviato.

`inputs/` immutabile; E1=0, E2=0, Verified=0; claim runtime/PoC/Production invariati.
