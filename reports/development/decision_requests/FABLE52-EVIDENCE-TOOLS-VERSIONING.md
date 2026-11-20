# FABLE52-EVIDENCE-TOOLS-VERSIONING

Status: `OPEN_PO_DECISION_REQUIRED`. Livello: operativo (regole di produzione dell'evidenza; nessun record sigillato
cambia). Origine: audit `reports/review/OCOR_FABLE52_AUDIT_2026-11-11.md`, finding F-10 e F-11, su `main`
`113f935cf6e04df460406a0b5dfea6949df6723a`. Redatto da Claude Fable 5.2 (Anthropic) in sola lettura.

## Contesto

- 351 record JSON di `reports/evidence/`, `reports/assurance/` e `reports/development/` citano script di controllo o
  di confronto che stanno nella cartella del loop sulla workstation, fuori dal repository (per esempio
  `reports/assurance/OCOR-DEV-REM-0059-RCCAD/OCOR-DEV-REM-0059.json:1128`, confronto degli alberi sintattici). La
  riproduzione in ambiente pulito prevista da `OCOR-DEV-0068` non li può rieseguire.
- 741 file contengono un percorso assoluto della home dell'utente e 7 un indirizzo e-mail personale (per esempio
  `reports/planning/OCOR_PLAN_RUN_STATE.json:48`). Il repository è pubblico. I record hanno già il campo
  `raw_output_redactions`.

## Opzioni

1. **Strumenti nel repository e redazione alla fonte, da ora in poi (raccomandata).** Gli script di controllo e di
   confronto usati per l'evidenza entrano in `scripts/evidence_tools/` (Python, tipizzati, con test), e i record
   nuovi li citano con percorso del repository e sha256. I log grezzi e i record nuovi sostituiscono il percorso
   della home con `~` e non contengono indirizzi e-mail; la sostituzione è registrata in `raw_output_redactions`. I
   controlli D04 e D05 passano a `BLOCKING` secondo `FABLE52-ALIGNMENT-GUARD-ENFORCEMENT`. I record già sigillati
   restano come sono.
2. **Solo redazione.** Come l'opzione 1 senza il trasferimento degli strumenti: resta il limite di riproducibilità.
3. **Nessuna modifica**, con il limite dichiarato nel pacchetto di `OCOR-DEV-0069`.

## Impatto a cascata

Opzione 1: nuova cartella `scripts/evidence_tools/` (rientra nella politica dei linguaggi, area 3), regola nelle
istruzioni degli implementatori, `OCOR_TEST_STRATEGY.md` invariato. Una unità di stima 3 iterazioni per portare gli
strumenti ricorrenti (`check_evidence.py`, `ast_compare.py`, `supply_chain.py`, `register_control_plane.py`). Per i
record sigillati che citano strumenti esterni, il pacchetto di `OCOR-DEV-0069` elenca il limite per record.

## Criteri di accettazione verificabili

- `git grep -lE "(~|/home/[^/]+)/\.ocor-codex/[^\"]+\.(py|sh)"` sui record creati dopo l'unità non restituisce nulla.
- Ogni strumento citato da un record nuovo esiste al commit del record con lo sha256 dichiarato.
- Il referto di `ocor-alignment-guard` di una unità successiva non ha voci D04 né D05.

Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
