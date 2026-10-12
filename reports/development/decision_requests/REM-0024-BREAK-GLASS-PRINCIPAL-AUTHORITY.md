# REM-0024-BREAK-GLASS-PRINCIPAL-AUTHORITY

Stato: `OPEN_PO_DECISION_REQUIRED` — 2026-10-12.

Richiesta aperta dall'implementatore di riserva del loop (Claude Code, quota Codex esaurita) prima di
qualunque modifica a `ocor-runtime/src/ocor_runtime/c6/safety.py`, in applicazione della regola
dell'ambito registrato di `OCOR-DEV-REM-0024`: "If role/human/active representation or audit/alert
integration needs a contract or semantic change, write a decision request instead of inventing it."

## Contesto

La decisione PO `RVW-03` (2026-10-05) dispone l'allineamento di `BreakGlassController` ad ADD v1.3
§5.4–5.5 e LLD v1.1 §4.2. L'audit del 2026-10-12 (`RVW-03.md`) ha registrato `OCOR-DEV-REM-0024` con
questi criteri, tra gli altri:

- punto 2: all'uso, approvatori rivalidati contro `IdentityRegistry` come "esistenti, attivi, umani,
  distinti", richiedente escluso;
- quorum per ruolo di ADD §5.4: "Security Duty Officer + affected Domain Owner";
- punto 3: finestra valutata sull'ora attendibile del boundary, mai su un istante del chiamante;
- "existing 0044 tests unchanged and green".

## Fatti verificati (sola lettura, `origin/main` `d098ed7`)

1. **Il contratto d'identità non rappresenta né la natura umana, né lo stato, né i ruoli.**
   `ocor-runtime/schemas/identity-record.schema.json` (`$id` `…/v1.2/identity-record.schema.json`)
   ammette solo `canonicalId`, `aliases` e `attributes` con valori scalari
   (`string|number|integer|boolean|null`), senza chiavi definite. `c2_identity.IdentityRecord`
   rispecchia lo schema; `IdentityRegistry` offre solo `register`/`get`/`resolve` per esistenza.
   Nessun modulo di `ocor-runtime/src` legge un attributo di tipo principal, stato o ruolo
   (ricerca su `attributes[`/`attributes.get`/`principal_type`/`HUMAN`/`WORKLOAD`: zero risultati
   fuori dalla memoria). Il testo normativo nomina i ruoli (ADD §5.4) ma nessun contratto approvato
   ne fissa la rappresentazione, l'autorità che li attribuisce o il legame "affected" fra Domain Owner
   e scope del grant (il grant ha solo una stringa `scope`).
2. **I criteri registrati sono in conflitto tra loro.** Le nove funzioni break-glass di
   `tests/tasks/test_ocor_dev_0044.py` (righe 145–296, 13 casi con il parametrizzato su cinque
   capability) chiamano `grant(...)` senza richiedente né capability nominate, con identità
   registrate senza attributi, e dimostrano la scadenza passando a `authorize` un istante del
   chiamante (`at=NOW + 6 min`, righe 211–226). Qualunque implementazione conforme ai punti 2, 3 e
   alle capability nominate rende obbligatori nuovi input o ignora l'istante del chiamante: quei
   test, invariati, non possono restare verdi. Mantenerli verdi richiederebbe un percorso legacy
   permissivo, che è esattamente il difetto da rimuovere (`P1`–`P3`, `X1` della prova RVW-03).
   Modificare il file di test di un task sigillato è fuori dalle `expected_file_areas` di REM-0024.
3. **Controllo di classe su `c6/human_gate.py` (assegnato all'implementatore di REM-0024): confermato.**
   `HumanGateCoordinator.validate` (righe 124–160) conta un firmatario se esiste nel registry
   (riga 149), senza verificare natura umana o stato; il ruolo è dichiarato dalla stessa
   `GateSignature.role` (riga 92), non attribuito da un'autorità; `at` e `signed_at` (riga 153) sono
   forniti dal chiamante. Stessa classe anche in `c6/safety.py`
   `EmergencyStopController.request_reset` (righe 152–159): reset a doppio controllo con approvatori
   verificati per sola esistenza e istante del chiamante. Stessa classe del punto 2 e del punto 3,
   sullo stesso vuoto di rappresentazione. Come prescritto, non è
   allargato dentro REM-0024: registrato come `OCOR-DEV-REM-0028` (primo ID libero verificato il
   2026-10-12 su tutti i ref locali e remoti, sui file di `~/.ocor-codex` e sui titoli/branch delle
   PR: zero occorrenze di `REM-0028`…`REM-0099`), bloccato da questa stessa richiesta.
4. **Fase dei requisiti.** `FR-139` (break-glass governato) è registrato con fase `MVP`;
   `NFR-081` (dual control, "break-glass è limitato, scade ed è auditato") con fase `PoC`. La
   decisione `RVW-03` resta comunque vincolante per l'allineamento al testo ADD/LLD approvato.

Punti realizzabili senza decisione (nessun contratto toccato), che l'implementazione eseguirà in
ogni caso: grant emessi solo dal controller e registrati (punto 1), `TrustedClock` iniettato
(punto 3), TTL ≤ 15 minuti senza rinnovo (punto 4, già soddisfatto, solo test di regressione),
revoca e scadenza fail-closed (punto 5), richiedente obbligatorio ed escluso dagli approvatori,
capability nominate legate al grant, audit sincrono e alert tramite port iniettati secondo il
pattern già presente (`*AuditSink` in `memory/`), fail-closed. Non sono stati implementati ora
perché cambiano la firma di `grant`/`authorize` e rompono comunque i test 0044 (fatto 2): una
riqualifica parziale di 0044/0047 andrebbe rifatta dopo la decisione.

## Opzioni

**Q1 — Rappresentazione di natura umana, stato e ruoli degli approvatori**

1. *(raccomandata)* Convenzione su chiavi riservate degli `attributes` scalari già ammessi dallo
   schema v1.2, senza modificare schema né `c2_identity.py`: `principal_kind` (`HUMAN`|`WORKLOAD`),
   `status` (`ACTIVE`; ogni altro valore o assenza = non attivo), `roles` (stringa di token ordinati
   separati da spazio, per esempio `SECURITY_DUTY_OFFICER DOMAIN_OWNER:<domain>`). Il grant porta un
   `domain` esplicito e "affected Domain Owner" significa ruolo `DOMAIN_OWNER:<domain>` dello stesso
   dominio. Attributo assente o malformato: rifiuto fail-closed. La convenzione viene documentata nel
   record di REM-0024 come interpretazione PoC, non come estensione del contratto.
2. Port d'autorità dedicato (`ApproverDirectory`) iniettato nel controller, che restituisce natura,
   stato e ruoli da una fonte autoritativa (per esempio Keycloak già integrato da 0048). Più fedele
   all'architettura, ma introduce un nuovo port e una dipendenza di C6 dal control plane: ambito e
   riqualifiche più ampi.
3. Estensione dello schema `identity-record` con campi tipizzati: variazione di contratto, richiede
   un nuovo `DEC-*` (riservato).

**Q2 — Test break-glass di OCOR-DEV-0044**

1. *(raccomandata)* Autorizzare in REM-0024 la modifica delle sole nove funzioni di test break-glass di
   `test_ocor_dev_0044.py` (e delle loro fixture) per fornire gli input ora obbligatori: orologio
   attendibile avanzato al posto dell'istante del chiamante, richiedente, capability nominate,
   attributi degli approvatori. Stessi casi, stesse asserzioni e stessi reason code; nessun caso
   rimosso, unito o indebolito; corrispondenza uno a uno registrata nell'evidenza; aggiunta del file
   alle `expected_file_areas`; riqualifica di 0044 con record nuovo e supersession, sigilli storici
   intatti.
2. Lasciare invariati i test 0044 e mantenere un percorso compatibile: respinta dall'implementatore
   perché conserva il difetto (grant non verificati e tempo del chiamante).

**Q3 — Ordine di REM-0028 (Human Gate)**

1. *(raccomandata)* Stessa risposta di Q1 e Q2 applicata a `human_gate.py`, a
   `EmergencyStopController.request_reset` e ai relativi casi di test di `OCOR-DEV-0043` e
   `OCOR-DEV-0044`, eseguita come REM separata dopo REM-0024; dipendenza obbligatoria dei task G6.
2. Differire REM-0028 a una decisione normativa successiva, registrandola come rischio aperto.

## Raccomandazione

Q1 opzione 1, Q2 opzione 1, Q3 opzione 1: nessun nuovo `DEC-*`, nessuna modifica di contratto o di
`c2_identity.py`, interpretazione fail-closed più restrittiva, riqualifiche limitate a 0043, 0044 e
0047 (più ogni task il cui record sigillato include i file toccati).

## Impatto e task bloccati

- Bloccati: `OCOR-DEV-REM-0024` e `OCOR-DEV-REM-0028`, quindi i task G6 (`OCOR-DEV-0060`…`0069`),
  che ne dipendono già.
- Non bloccati: `OCOR-DEV-0049`, G5, `OCOR-DEV-REM-0025`, `REM-0026`, `REM-0027` (prossima unità
  eseguibile: REM-0025, mentre REM-0019/REM-0017 attendono la decisione
  `REM-0019-KIND-CONTAINERD-SEGV-RECURRENCE`).
- Nessuna modifica a input, codice, test o record sigillati in questa unità. `E1=0`, `E2=0`,
  `Verified=0`, claim `NO-GO` invariati. Nessuna verifica indipendente richiesta: nessun risultato
  qualificante. Per l'implementazione successiva di REM-0024/REM-0028 da parte di Claude Code di
  riserva, il verifier sarà Cursor/Grok.
