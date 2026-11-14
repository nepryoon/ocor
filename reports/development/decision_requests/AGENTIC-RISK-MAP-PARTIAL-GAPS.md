# AGENTIC-RISK-MAP-PARTIAL-GAPS

Status: `OPEN_PO_DECISION_REQUIRED`

Livello: operativo. Unità `OCOR-DEV-REM-0065`, punto 2 di
`FABLE52-POST-POC-PROGRAMME (2026-11-11)`. Il documento generato non è
evidenza e non è un claim di conformità (`NFR-050`). Non cambia i
criteri di `OCOR-DEV-0062`, `OCOR-DEV-0064`, `OCOR-DEV-0068` e
`OCOR-DEV-0069`. Non modifica codice di runtime, test esistenti, `inputs/`
né il backlog approvato. Nessun nuovo `DEC-*`. Claim invariati: `E1=0`,
`E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC `NO-GO`, Production
`NO-GO`.

## Contesto

La mappa è generata da `scripts/generate_agentic_risk_inventory.py`.
Ogni riga `PARTIAL` o `GAP` entra in questa sola richiesta. Le righe
sono:

- `ASI01` `PARTIAL`: Controls resolve, and OCOR-DEV-0062 is not a completed evidence task. NFR-048 is therefore not sealed. This map is not that campaign.
- `ASI02` `PARTIAL`: Controls resolve, and OCOR-DEV-0062 is not a completed evidence task. NFR-048 is therefore not sealed. This map is not that campaign.
- `ASI03` `PARTIAL`: Controls resolve, and OCOR-DEV-0062 is not a completed evidence task. NFR-048 is therefore not sealed. This map is not that campaign.
- `ASI04` `PARTIAL`: Controls resolve, and OCOR-DEV-0062 is not a completed evidence task. NFR-048 is therefore not sealed. This map is not that campaign.
- `ASI05` `PARTIAL`: Controls resolve, and OCOR-DEV-0062 is not a completed evidence task. NFR-048 is therefore not sealed. This map is not that campaign.
- `ASI06` `PARTIAL`: Controls resolve, and OCOR-DEV-0062 is not a completed evidence task. NFR-048 is therefore not sealed. This map is not that campaign.
- `ASI07` `PARTIAL`: Controls resolve, and OCOR-DEV-0062 is not a completed evidence task. NFR-048 is therefore not sealed. This map is not that campaign.
- `ASI08` `PARTIAL`: Controls resolve, and OCOR-DEV-0062 is not a completed evidence task. NFR-048 is therefore not sealed. This map is not that campaign.
- `ASI09` `PARTIAL`: Controls resolve, and OCOR-DEV-0062 is not a completed evidence task. NFR-048 is therefore not sealed. This map is not that campaign.
- `ASI10` `PARTIAL`: Controls resolve, and OCOR-DEV-0062 is not a completed evidence task. NFR-048 is therefore not sealed. This map is not that campaign.

Il registro dei tool ammessi, letto dai contratti del repository, è
`NO_ADMITTED_INSTANCE`. Nessun ruolo di `AgentRole` ha
una allow-list di capability nel modulo che lo dichiara.

## Opzioni

1. **Registro informativo.** Le righe restano un allegato informativo. Nessun criterio cambia. La richiesta non blocca alcun task.

2. **Unità dopo la decisione su G7.** Dopo quella decisione, un'unità
nuova può trattare le sole righe `GAP`, senza toccare il percorso del PoC
e senza cambiare i criteri dei task già fissati.

3. **Allargare OCOR-DEV-0062.** Le righe entrano nei criteri di quel task.
La decisione del 2026-11-11 vieta questo cambiamento: l'opzione è
elencata e non è raccomandata.

## Impatto e task bloccati

Nessun task è bloccato. Questa richiesta non blocca alcun task. Non apre
un nuovo `DEC-*`.

## Raccomandazione

Opzione 1. La decisione che autorizza la mappa dice che il documento non
è evidenza, non è un claim (`NFR-050`) e non cambia i criteri di
`OCOR-DEV-0062`, `OCOR-DEV-0064`, `OCOR-DEV-0068` e `OCOR-DEV-0069`.
