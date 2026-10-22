# Decision request — RVW-03 (BreakGlass authorize re-validation)

- **Status**: `RESOLVED` — decisione del Product Owner `RVW-03` (2026-10-05); audit di conformità
  eseguito il 2026-10-12; remediation registrata come `OCOR-DEV-REM-0024`.
- **Fonte**: `reports/review/OCOR_FULL_CODE_REVIEW_2026-09-15.md` (finding RVW-03)

## Risoluzione (2026-10-05, eseguita il 2026-10-12)

Il Product Owner ha risolto la richiesta senza adottare né l'opzione 1 né l'opzione 2 come
formulate: ADD v1.3 §5.5 definisce il break-glass come "Delegation eccezionale firmata", quindi la
rivalidazione all'uso è conformità ad ADD §5.1–5.2 e §5.5 già approvati, non una variazione
semantica, e non richiede una nuova decisione normativa. La decisione dispone una remediation con il
primo `REM-*` libero verificato su `c6/safety.py` `BreakGlassController`, allineata ad ADD v1.3
§5.4–5.5 e LLD v1.1 §4.2, previo confronto di ogni punto con il testo normativo.

La raccomandazione originale (opzione 1, "nessun intervento") è superata dalla decisione e resta
nella storia di questo record.

## Audit di conformità (2026-10-12)

Oggetto: `ocor-runtime/src/ocor_runtime/c6/safety.py` su `origin/main`
`2710c1b9f6c1deddee3a5156b9627dbb92727178`, SHA-256 del file
`d241be276c3e1a9c4c335d9d950439536f5f8065193aa83cce9fff519e0cbe83`. Testo normativo: ADD v1.3
§5.4 (tabella SoD, riga Break-glass) e §5.5; LLD v1.1 §1.1 (tempo e autorità derivata) e §4.2.

Prova eseguibile in sola lettura, fuori dal repository e non qualificante:
`~/.ocor-codex/rvw03-audit-20261012/probe.py` (SHA-256
`350797f5344adf50a23f61c93dc7cace9374a8c66283f9e6797c2571c15593ec`), esito
`probe-result.json` (SHA-256 `ad81c6dbc58354d192526ea7850067150b99b94c476a784216439b34bebb9098`).
È un'osservazione del comportamento attuale, non evidenza `E1`/`E2`.

| Punto della decisione | Testo normativo | Stato nel codice | Prova |
|---|---|---|---|
| 1. `authorize` accetta solo grant emessi e verificabili | ADD §5.5 "Delegation eccezionale firmata" | **Assente.** `BreakGlassGrant` è un dataclass pubblico; `authorize` (righe 270–282) controlla solo revoca, scadenza, denylist, stop e review, non la provenienza del grant | Grant costruito direttamente con approvatori mai registrati: autorizzato (`P1`) |
| 2. Rivalidazione all'uso degli approvatori: esistenti, attivi, umani, distinti, richiedente escluso | ADD §5.4 "Requester non approva"; §5.5 "due approvatori indipendenti"; LLD §4.2 "due principal umani distinti" | **Parziale a `grant()`, assente all'uso.** `grant()` (righe 238–265) verifica distinzione ed esistenza nel registry; nessun controllo di stato attivo o di natura umana; nessun campo richiedente; `authorize` non rivalida nulla | Principal workload accettato come approvatore (`P2`); `grant()` non ha parametro richiedente |
| 3. Finestra sull'ora attendibile del boundary | LLD §1.1 (tempo osservabile, autorità mai da input client) | **Assente.** `grant(at=…)` e `authorize(at=…)` usano l'istante fornito dal chiamante; il controller non ha un clock attendibile | Grant scaduto autorizzato con istante retrodatato; grant emesso con `at` un anno nel futuro (`P3`) |
| 4. TTL massimo 15 minuti, nessun rinnovo automatico | ADD §5.5 | **Soddisfatto.** `BreakGlassGrant.__post_init__` rifiuta `ttl <= 0` e `ttl > MAX_BREAK_GLASS_TTL` anche per grant costruiti fuori da `grant()`; nessuna API di rinnovo | `test_a_ttl_beyond_the_maximum_is_refused_at_construction`; `P4` |
| 5. Revoca e scadenza fail-closed | ADD §5.5; LLD §4.2 "revoca automatica alla scadenza" | **Soddisfatto come logica, dipendente da 1 e 3.** Revoca per `grant_id` e confine `instant >= expires_at` rifiutano; la scadenza è però valutata sull'istante del chiamante e la revoca vale solo per id noti | `test_an_expired_grant_denies_even_though_it_was_valid_when_first_used`, `test_a_revoked_grant_denies_immediately`; `P5` |

Lacune ulteriori rilevate confrontando lo stesso testo normativo, incluse nell'ambito della
remediation perché la decisione dispone l'allineamento ad ADD §5.4–5.5 e LLD §4.2:

- **Capability nominate.** ADD §5.5 richiede "scope minimo, purpose obbligatorio, capability
  nominate". Il grant ha solo una stringa `scope`; `authorize` autorizza ogni capability non presente
  nella denylist, anche fuori dallo scope del grant (`X1`, `X2`).
- **Quorum per ruolo.** ADD §5.4 richiede per il break-glass il quorum "Security Duty Officer +
  affected Domain Owner"; il codice verifica soltanto due principal distinti.
- **Audit e alert.** ADD §5.5 richiede alert immediato e audit immutabile, LLD §4.2 audit sincrono;
  `authorize` restituisce un `BreakGlassUse` in memoria senza scrittura di audit né alert.

Percorso reale del PoC: `BreakGlassController` non è usato da altri moduli di
`ocor-runtime/src` (unico consumer: `tests/tasks/test_ocor_dev_0044.py`). Le lacune non sono oggi
raggiungibili da un percorso di produzione del PoC, ma la qualifica G6 di break-glass (BA e requisiti
collegati) si appoggerebbe a questo componente: per questo la remediation è dipendenza dei task G6.

Osservazione fuori ambito, nessuna azione in questa unità: `c6/human_gate.py:149` verifica gli
approvatori con la sola esistenza nel registry, come `grant()`. Il controllo di classe è assegnato
all'implementatore di `OCOR-DEV-REM-0024`; se il difetto è confermato, va registrato con una
remediation separata e il proprio identificativo libero.

## Remediation registrata

`OCOR-DEV-REM-0024`, primo identificativo libero verificato il 2026-10-12 su tutti i ref locali e
remoti, sui file di `~/.ocor-codex` e sui titoli delle PR (ultimo usato: `OCOR-DEV-REM-0023`).
Ambito, criteri, file attesi e dipendenze sono in `reports/development/EXECUTION_STATE.json` →
`remediation_status.REM_0024_BREAK_GLASS_CONFORMANCE`. È dipendenza obbligatoria dei task G6
(`OCOR-DEV-0060` e successivi), come `OCOR-DEV-REM-0017`; non blocca `OCOR-DEV-0049` né G5.
Richiede la riqualifica di `OCOR-DEV-0044` e `OCOR-DEV-0047`, i cui record sigillati hanno
`c6/safety.py` tra gli input, con record nuovi e supersession esplicita.

`E1=0`, `E2=0`, `Verified=0`, claim `NO-GO` e record sigillati invariati. Nessun `DEC-*`.

## Contesto originale

`c6/safety.py` `BreakGlassController.authorize` (~righe 270–282) non ri-valida gli
`approvers` contro `IdentityRegistry`; il doppio controllo è presente soltanto in
`grant()`. Il `grant` è l'artefatto già autorizzato: ripetere la validazione all'uso
sarebbe difesa-in-profondità, non un requisito dell'architettura approvata.

## Opzioni originali

1. **Lasciare invariato** — `grant()` resta l'unico punto di doppio controllo; nessun
   cambio semantico a C6.
2. **Ri-validare in `authorize()`** — difesa-in-profondità aggiuntiva, richiede conferma
   normativa (variazione semantica della semantica break-glass approvata).

## Raccomandazione originale (superata)

Raccomando l'opzione 1 (nessun intervento) finché non arriva una conferma normativa
esplicita in LLD: la semantica C6 è approvata e `grant` è l'artefatto autorizzato.
L'opzione 2 è legittima ma è una variazione di comportamento approvato, quindi riservata.

## Impatto

Originale: difesa-in-profondità sul break-glass C6; nessun task del backlog dipendeva da questa
decisione. Dopo la risoluzione: `OCOR-DEV-REM-0024` è dipendenza dei task G6.

## Task bloccati

Nessuno da questa richiesta. `OCOR-DEV-REM-0024` blocca i task G6 fino alla sua chiusura verificata.
