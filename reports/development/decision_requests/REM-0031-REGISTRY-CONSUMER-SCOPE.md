# REM-0031-REGISTRY-CONSUMER-SCOPE

Status: `OPEN_PO_DECISION_REQUIRED` — perimetro dei consumer di test per
`OCOR-DEV-REM-0031`. Nessuna variazione normativa richiesta. Autorità corrente:
decisione PO `REM-0024-IDENTITY-REGISTRY-WRITER-AUTHORITY (2026-10-14)`, opzione 1;
DEC-210/211.

## Contesto

La decisione del 2026-10-14 apre REM-0031 con ambito chiuso: boundary di
provisioning autenticato e autorizzato (principal, authority, policy), scrittura
negata a richiedente e approvatori, **inventario dei consumer prima di modificare**,
RED/GREEN sui backend reali (creazione autorizzata, auto-attribuzione negata, primo
writer ostile negato, aggiornamento negato, autorità indisponibile fail-closed),
schema `identity-record` e convenzione Q1 invariati, riqualifica con supersession.
Lo stato registra che lo scope esatto dei file si stabilisce dall'inventario.

L'inventario, eseguito in sola lettura su `origin/main`
`d1207eec98257b50bb18ac936e54dacc90caf427`, mostra che ogni chiusura reale del primo
writer ostile cambia il comportamento di `IdentityRegistry.register()` per i record
con le chiavi riservate Q1 (`principal_kind`, `status`, `roles`). Sei moduli di test
di altri task scrivono oggi quei record direttamente con `register()`. Sono fuori dalle
aree autorizzate per nome. Per il precedente `REM-0023-DENIAL-AUDIT-CONSUMER-FIXTURES`
(2026-10-22), anche un adattamento dei soli fixture richiede un'estensione esplicita
del perimetro. Qui l'adattamento tocca anche istruzioni nei corpi di test.

## Fatti dell'inventario

Artefatti fuori da Git, in `~/.ocor-codex/rem0031-inventory-20261025/`:
`inventory.py` sha256 `cb2456da7a4cfb3dc76cd484859c33f9a49a7ffbfd4c057abcf735ceab3e4678`,
`inventory.json` sha256 `57463432605f9b0ffc37447be5648967868f9ba848840b473ca9e62821deeda3`.
Metodo: `git grep` dell'API del registry e di `.register(` su `src/` e `tests/`, poi
incrocio con gli `inputs` del record più recente di ognuno dei 74 task completati
(`select_most_recent` di `validate_evidence_input_drift.py`) e con ogni JSON sigillato
in `reports/evidence` e `reports/assurance`.

- `c2_identity.py` sha256 `bbd7794ccc5a43d7e29f0941407edf8ad144acc42faaeec2f24690cfdfff987b`,
  invariato dalla caratterizzazione della decision request del 2026-10-14: il primo
  writer di un'identità nuova con chiavi Q1 privilegiate è ancora accettato.
- **Consumer in `src/`** (sola lettura, nessuno scrive): `c2/gateway.py`,
  `c6/human_gate.py`, `c6/safety.py`, `c8_agent.py`, `__init__.py`. Non serve
  modificarli in nessuna opzione.
- **Scrittori con chiavi riservate Q1**, tutti nei test:
  - fixture o helper: `test_ocor_dev_0043.py` (`identities`), `test_ocor_dev_0044.py`
    (`identities`, `break_glass_identities`), `test_ocor_dev_rem_0024.py` (`registry`),
    `test_ocor_dev_rem_0027.py` (`__init__` del mondo di test), `test_ocor_dev_rem_0028.py`
    (`directory`);
  - corpi di test: `test_ocor_dev_0058.py` (helper `workflow`, 1 sito);
    `test_ocor_dev_rem_0028.py` (3 siti in
    `test_real_dual_role_holder_still_cannot_fill_two_role_slots`,
    `test_valid_distinct_role_assignment_is_independent_of_signature_order`,
    `test_distinct_role_matching_agrees_with_exhaustive_assignment_oracle`);
  - asserzione dipendente dalla semantica di `register()`:
    `test_ocor_dev_rem_0024.py::test_a_requester_cannot_update_its_record_into_an_approver`
    attende `IdentityConflictError` sull'aggiornamento di un record esistente.
- **Scrittori senza chiavi riservate** (non toccati in nessuna opzione):
  `acceptance_ev/test_ev_001_010_semantics_identity.py`,
  `acceptance_ev/test_ev_029_035_fence_agent_e2e.py`,
  `mission_thread/test_first_governed_slice.py`, `tasks/test_ocor_dev_0034.py`.
- **Riqualifiche, vista del validator di deriva** (record più recente):
  - opzione 1: `OCOR-DEV-0043`, `OCOR-DEV-0044`, `OCOR-DEV-0058` (3 task);
  - opzioni 2 e 3: nessuna (`c2_identity.py` non è input del record più recente di
    alcun task completato).
- **Vista ampia** (qualunque JSON sigillato): i file di test compaiono anche nei
  record di REM-0024, REM-0027, REM-0028, REM-0034 e in
  `OCOR-DEV-0050.requalified-rem0028.json`, già superato da
  `OCOR-DEV-0050.requalified-rem0027.json`, che non li include. Per questi si propone
  la sola regressione documentata, senza nuovi record, come nelle remediation
  precedenti.

## Opzioni

1. **Raccomandata: registry chiuso per default sulle chiavi Q1, boundary
   autenticato, consumer di test adattati con prova AST.**
   - `register()` mantiene per primo il controllo di immutabilità
     (`IdentityConflictError` invariato). Poi rifiuta ogni record nuovo con chiavi Q1
     con un reason code dedicato. I record senza chiavi Q1 restano invariati.
   - I record Q1 entrano soltanto in due modi:
     - **seeding alla costruzione** (composition root che crea il registry prima di
       condividerlo);
     - a runtime, tramite un nuovo `IdentityProvisioningBoundary`. Il writer si
       autentica con Keycloak reale e viene autorizzato da OPA reale con bundle
       firmato. Sono negati l'auto-attribuzione, i writer registrati come principal
       (richiedente, approvatori) e l'aggiornamento; con autorità indisponibile il
       boundary è fail-closed.
   - Il PO autorizza nel change set governed/ di REM-0031 l'adattamento, al solo
     seeding, delle scritture elencate sopra nei sei moduli.
   - **Invarianti** come REM-0023:
     - stesso elenco di funzioni di test;
     - nodi `assert` e `pytest.raises` identici;
     - decorator di parametrizzazione identici;
     - cambiano solo le chiamate di scrittura del registry e la costruzione;
     - un test fallisce se il diff tocca altro.
   - **Riqualifiche:** 0043, 0044 e 0058 con supersession; regressione di REM-0024,
     REM-0027 e REM-0028. Sigilli storici intatti.
   - Nell'allowlist del piano entrano soltanto i nuovi percorsi esatti.
2. **Finestra di composizione chiusa alla prima lettura autorevole.**
   - `register()` accetta chiavi Q1 finché il registry non viene letto, poi solo dal
     boundary.
   - Si tocca solo `c2_identity.py` e nessun test di altri task, con zero riqualifiche.
   - Non raccomandata: un writer ostile che scrive prima della prima lettura è ancora
     accettato. Il criterio «primo writer ostile negato» non è quindi soddisfatto senza
     condizioni, e la fiducia dipende dall'ordine di composizione, non da un'autorità.
3. **Registry governato su adesione.**
   - Il registry è chiuso solo se costruito con un'autorità; il default resta aperto.
   - Nessun test cambia e non ci sono riqualifiche.
   - Non raccomandata: `AgentKernel` e ogni costruzione di default restano esposti, e il
     rischio residuo resterebbe aperto.

## Raccomandazione

Opzione 1. È l'unica che nega il primo writer ostile senza condizioni, lega la scrittura
a un principal autenticato e a una policy firmata e non lascia aperto il default.
Il costo è limitato: 3 riqualifiche di task (meno di 0049/0050) e modifiche ai test
limitate alle istruzioni di scrittura, con una prova AST che lo garantisce.

## Impatto e task bloccati

- Blocca solo l'adattamento dei consumer di test, e quindi la qualifica, la verifica e
  l'integrazione di REM-0031. G6 (`OCOR-DEV-0060`–`0069`) resta subordinato a REM-0031,
  come già registrato.
- **Non blocca** l'implementazione del boundary di provisioning, comune a tutte le
  opzioni: nuovo modulo C2, policy firmata di provisioning, nuovo modulo di test
  `test_ocor_dev_rem_0031.py`, RED/GREEN sui backend reali Keycloak/OPA per creazione
  autorizzata, auto-attribuzione negata, writer registrato negato, aggiornamento negato
  e autorità indisponibile. Il loop la prosegue sul branch
  `governed/ocor-dev-rem-0031-identity-registry-writer-authority`, senza toccare i sei
  moduli finché la disposition non arriva.
- Non è stato consumato nessun ciclo di riparazione e non è stato chiesto alcun verdetto.
- Limite dichiarato: in Python un codice in processo può aggirare i membri privati.
  La prova resta in processo, come la caratterizzazione del 2026-10-14, e non
  dimostra conformance runtime né l'assenza di attacchi remoti.

Implementatore: Claude Code (Anthropic, claude-opus-5-5, CLI 2.1.310). Codex (OpenAI) è
contato fra gli implementatori dal loop; il verifier dell'unità implementativa dovrà
essere di un fornitore diverso (Cursor/Grok, xAI, o Antigravity/Gemini, Google).
`inputs/` intatto; E1=0, E2=0, Verified=0, runtime `NOT_ESTABLISHED`, PoC/Production
`NO-GO`. Nessun nuovo `DEC-*`, nessuna chiusura di `OI-*`/`ASM-*`/`RSK-*`.
