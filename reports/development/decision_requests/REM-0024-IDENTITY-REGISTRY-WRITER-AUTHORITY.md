# REM-0024-IDENTITY-REGISTRY-WRITER-AUTHORITY

Status: `OPEN_PO_DECISION_REQUIRED` — rischio residuo sull'autorità di scrittura del registry,
non riapertura di `REM-0024-BREAK-GLASS-PRINCIPAL-AUTHORITY`.

## Autorità e ambito

La decisione PO del 2026-10-13 ha risolto Q1/Q2/Q3 con opzione 1 e impone che natura, stato e
ruoli siano letti soltanto da `IdentityRegistry`; nessun percorso di richiesta deve scriverli.
La sua condizione aggiuntiva richiede di registrare il rischio di un registry senza autorità di
scrittura con una campagna che lo copra davvero, oppure una decision request. Questa richiesta
adempie quella condizione. Convenzione `principal_kind`/`status`/`roles`, dominio esplicito,
clock attendibile, adattamento dei nove test e dipendenza REM-0028 dopo REM-0024 restano risolti.
Non si richiede un nuovo `DEC-*` e non si estende ora lo scope di REM-0024 a `c2_identity.py`.

## Fatti e limiti della riproduzione

Baseline: `19ef2a2d76c794c1e665ed4ced681ad8c94b2e9a`.

- `ocor-runtime/src/ocor_runtime/c2_identity.py:72-90`: `register(record)` non riceve principal
  autenticato, authority, policy o capability del writer. Il primo writer può inserire un nuovo
  record con `principal_kind=HUMAN`, `status=ACTIVE` e ruoli privilegiati auto-dichiarati.
- Lo stesso metodo **rifiuta** la modifica di un record già esistente con
  `IdentityConflictError`: l'immutabilità non è assente. Una seconda identità nuova con gli
  stessi attributi privilegiati viene invece accettata. Non è dimostrato che chiunque possa
  aggiornare qualsiasi record esistente.
- `c6/safety.py:233-282` non scrive nel registry. Il solo consumer corrente di
  `BreakGlassController` è il modulo di test 0044; il futuro boundary deve continuare a leggere
  soltanto i record e non accettare ruoli dalla richiesta. `GateSignature.role` riguarda REM-0028.
- `c8_agent.py:434` espone l'oggetto `identity_registry` sull'istanza interna di `AgentKernel`;
  `c2/gateway.py:69-74` usa il registry per risolvere identità. Non è stata trovata né provata
  una rotta remota di registrazione attribuibile al richiedente o all'approvatore.
- La prova usa il concreto `IdentityRegistry` in memoria e chiama il suo metodo pubblico in
  processo: **non prova un attacco remoto**, un bypass di autenticazione esterna o conformance
  runtime. Il rischio è l'assenza di una separazione eseguibile fra provisioning autoritativo e
  codice con accesso al registry quando queste chiavi assumono valore autorizzativo.
- I mapping generici di sicurezza in `OCOR_TRACEABILITY_PLAN.csv` non identificano un test
  esistente dell'autorità del writer di queste tre chiavi. Non attribuiamo la copertura a FGM-16,
  REM-0027, REM-0028 o ad una campagna non ancora eseguita.

SHA-256 sorgente `c2_identity.py`: `bbd7794ccc5a43d7e29f0941407edf8ad144acc42faaeec2f24690cfdfff987b`.
SHA-256 probe: `cd6d6016083a17fe9d2c2ecc06d46de0ff809f997a39d474ce39b15f27cf432e`.
SHA-256 output: `9983d4b30fc6f7da1da2eb3b34a3fe3356fd738258bf3023771e1fb1f01bd2ad`.
Output osservato:

```json
{
  "additional_self_declared_privileged_identity_accepted": true,
  "boundary_grant_registers_identity": false,
  "different_existing_record_update_rejected": true,
  "evidence_status": "CHARACTERISATION_NOT_RUNTIME_CONFORMANCE",
  "new_self_declared_privileged_identity_accepted": true,
  "reference_only_break_glass_consumer": "test_ocor_dev_0044.py",
  "register_accepts_authenticated_writer_argument": false,
  "registration_signature": "(self, record: 'IdentityRecord') -> 'IdentityRecord'",
  "scope": "In-process concrete IdentityRegistry. No assertion of remote reachability or of an authenticated external attack."
}
```

Riproduzione dal medesimo HEAD, in ambiente Python 3.12.11 con `PYTHONPATH=ocor-runtime/src`:

```python
"""Read-only production-code characterisation, no external authority simulated."""
import inspect
import json
from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry
from ocor_runtime.errors import IdentityConflictError

attrs = {"principal_kind": "HUMAN", "status": "ACTIVE", "roles": "DOMAIN_OWNER:ops SECURITY_DUTY_OFFICER"}
r = IdentityRegistry()
requester = "urn:ocor:probe:requester"
r.register(IdentityRecord(canonical_id=requester, attributes=attrs))
assert dict(r.get(requester).attributes) == attrs
blocked_update = False
try:
    r.register(IdentityRecord(canonical_id=requester, attributes={"principal_kind": "WORKLOAD", "status": "REVOKED", "roles": ""}))
except IdentityConflictError:
    blocked_update = True
assert blocked_update
second = "urn:ocor:probe:new-approver"
r.register(IdentityRecord(canonical_id=second, attributes=attrs))
assert dict(r.get(second).attributes) == attrs
print(json.dumps({
    "scope": "In-process concrete IdentityRegistry. No assertion of remote reachability or of an authenticated external attack.",
    "new_self_declared_privileged_identity_accepted": True,
    "different_existing_record_update_rejected": blocked_update,
    "additional_self_declared_privileged_identity_accepted": True,
    "registration_signature": str(inspect.signature(IdentityRegistry.register)),
    "register_accepts_authenticated_writer_argument": False,
    "boundary_grant_registers_identity": False,
    "reference_only_break_glass_consumer": "test_ocor_dev_0044.py",
    "evidence_status": "CHARACTERISATION_NOT_RUNTIME_CONFORMANCE"
}, indent=2, sort_keys=True))
```

Il successo di questa caratterizzazione dimostra il comportamento osservato; non è il GREEN
richiesto per correggerlo. Nessun test qualificante, mock o skip viene promosso ad evidenza.

## Opzioni e raccomandazione

1. **Raccomandata: remediation separata dell'autorità di provisioning.** Autorizzare lo scope
   necessario per un boundary di scrittura autenticato/authorised del registry, preservando schema
   e convenzione Q1; distinguere provisioning da grant/authorize/signature e negare la scrittura
   da requester/approver. Prima di modificare: inventario dei consumer, RED/GREEN con creazione
   autorizzata, auto-attribuzione negata, primo writer ostile negato, aggiornamento negato e
   indisponibilità dell'autorità; riqualifiche di tutti gli input sigillati toccati. Il primo
   nuovo REM libero verrà verificato **solo dopo** la disposition, non inventato in questa unità.
2. **Authority boundary di provisioning isolato come interpretazione PoC.** Se il PO conferma
   che il registry è inizializzato esclusivamente da una trusted composition root senza alcun
   accesso di scrittura da requester/approver, documentare ed esercitare quel confine concreto,
   incluso un negativo che prova l'assenza di accesso dal percorso reale. Non basta attribuire
   la fiducia al nome `IdentityRegistry` o a un booleano dichiarato.

Raccomandiamo 1: l'API in-process non esprime l'autorità e l'invariante non è ancora dimostrato.
Nessuna alternativa viene implementata o dichiarata approvata in questa iterazione.

## Impatto e task bloccati

- REM-0024 può implementare i controlli già autorizzati leggendo soltanto il registry, mantenendo
  questo rischio aperto; REM-0028 mantiene la dipendenza da REM-0024. Non si blocca il lavoro
  implementativo per domande Q1/Q2/Q3 già risolte e non si consuma un ciclo di riparazione.
- La disposition/prova dell'autorità del writer è necessaria prima della chiusura dei gate G6;
  `OCOR-DEV-0060`–`0069` restano bloccati, già dipendenti da REM-0024/REM-0028.
- Nessun blocco aggiuntivo a 0049, G5, REM-0029 o all'ultimo ciclo REM-0027; ordine delle priorità
  del PO invariato. REM-0017 resta separatamente bloccata da `REM-0017-CI-KIND-INSPECT-TIMEOUT`.
- Nessuna modifica a produzione, test, schema, backlog, validator, immagini o record sigillati.
  Riqualifiche 0044/0047 e suite qualificante di REM-0024: `NOT_EXECUTED` in questa unità di audit.
- Implementatore dell'audit: Codex. Contributo storico all'audit di REM-0024: Claude Code di
  riserva; verifier previsto per il task: Grok 4.7 tramite Cursor, per la regola sui task toccati
  dalla riserva. Nessun verifier avviato né richiesta qualificante emessa per questo audit.
- `inputs/` intatto; `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC/Production
  `NO-GO` invariati.
