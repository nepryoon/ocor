# REM-0061-REPAIR-BUDGET

Status: `DECIDED_BY_PO`. Livello: operativo. Nessun nuovo `DEC-*`.

## Contesto

Il verdetto `OCOR-DEV-REM-0061-42b5840f35ab-2` è `NO_GO` sull'HEAD
`42b5840f35ab94c3b5d53c346f2f508b7dcbbb94`. Lo sha256 del file di verdetto è
`6585d51d9f02d17d2acdedc309ada4f6f935138de9a375ef74bf2769817cae7f`.
Il verifier è Codex (OpenAI), in un processo separato, non avviato dall'implementatore.
L'implementatore del ciclo è Grok Build, modello grok-4.7 (xAI). Il revisore preventivo
del ciclo è Cursor, modello cursor-grok-4.6-xhigh (xAI). Codex resta contato fra gli
implementatori. Quattro finding sono `high` e bloccanti. Zero `critical`, zero `medium`,
zero `low`.

La campagna indipendente del verifier sullo stesso HEAD è PASS: 5826 test, zero skip,
unione esatta, quattro corsie, teardown PASS, residuo vuoto. I finding non sono fallimenti
di quella suite. Sono controlli avversariali sul perimetro già deciso da
`TMP-RESIDUI-CAMPAGNA (2026-11-11)` e dal controllo meccanico dei digest di esecuzione.

- VF-001, `scripts/run_local_lane_campaign.py`: con quota illimitata, assente, o finita ma
  con filesystem insufficiente, quattro corsie sono ammesse. Il filesystem va confrontato
  sempre con il budget; la quota, solo se presente e finita.
- VF-002, stesso file: la cache di lavoro non è rimossa quando `consumes_tmp_quota` è falso.
  La rimozione deve essere incondizionata. Log e risultati restano fuori dalle directory rimosse.
- VF-003, stesso file: un errore di redazione del log impedisce teardown e rimozione.
  Il teardown va tentato anche se la redazione fallisce, con esito FAIL e senza credenziali.
- VF-004, `scripts/validate_evidence_input_drift.py`: un record canonico illeggibile è
  scartato e un predecessore può risultare PASS. L'errore di decodifica deve fallire il gate.

Il ciclo 0 e il ciclo 1 erano già `NO_GO`. Il ciclo 2 è il secondo ciclo di riparazione ed
è l'ultimo del budget ordinario (RCCAD, due cicli). Nessun ciclo 3 è stato avviato.
La PR #595 resta bozza e non si integra. `OCOR-DEV-REM-0060` (NCP-U12) resta in coda fino
al merge di `OCOR-DEV-REM-0061`. I task G6 restano sospesi. La diagnosi e l'azione minima
sono nel record `reports/development/OCOR_DEV_REM_0061_ESCALATION.md` di questo stesso commit.

## Opzioni

1. Autorizzare un solo ciclo di riparazione 3 di `OCOR-DEV-REM-0061`, sul branch
   `governed/ocor-dev-rem-0061-lane-image-cache`, a partire dall'HEAD
   `42b5840f35ab94c3b5d53c346f2f508b7dcbbb94`, senza rebase, reset o force-push. Il perimetro
   è soltanto VF-001, VF-002, VF-003 e VF-004 del verdetto `OCOR-DEV-REM-0061-42b5840f35ab-2`:
   confronto sempre attivo fra spazio libero del filesystem e budget, quota applicata solo
   se presente e finita, rimozione incondizionata della cache di lavoro, teardown tentato
   anche se la redazione fallisce, e propagazione degli errori di decodifica dei record
   canonici nel gate dei digest. RED prima del codice, GREEN dopo, sui casi avversariali
   descritti dal verdetto. Nessun test, gate, timer, tetto, partizione o criterio viene
   indebolito. La campagna qualificante del ciclo 2 non si trasferisce. Seguono il gate
   locale, la revisione preventiva se richiesta dalla procedura, la suite completa e una
   nuova verifica indipendente sull'HEAD esatto. Il verifier è di un fornitore diverso da
   xAI e da OpenAI. Se il verdetto è ancora `NO_GO`, non c'è un ciclo 4: nuova escalation
   e il task resta bloccato.
2. Non autorizzare un altro ciclo. `OCOR-DEV-REM-0061` resta
   `BLOCKED_REPAIR_BUDGET_EXHAUSTED`. La PR #595 non si integra. `OCOR-DEV-REM-0060`,
   NCP-U12 e i task che dipendono dal merge di REM-0061 restano in coda. Nessuna modifica
   al codice di campagna o al validatore dei digest.

## Raccomandazione

Option 1.

## Impatto e task bloccati

Senza una decisione, restano bloccati `OCOR-DEV-REM-0061` e, per la coda già decisa,
`OCOR-DEV-REM-0060`. I task G6 restano sospesi come già deciso. Claim invariati:
`E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
Nessuna modifica a `inputs/`.

## Disposition del Product Owner — 2026-11-12

Decisione del Product Owner `REM-0061-REPAIR-BUDGET (2026-11-12)`, **opzione 1**, come raccomandata in questo file. Il file aperto resta il commit `f5f7656e17c656e9505b3b65d983abb5a3aba857`, sha256 `362d0695bb8418c3437bdf99750d1e992a3d84032d4244936445ff83a80169d1`. Le opzioni sopra non sono state modificate. Stato: `DECIDED_BY_PO`.

La decisione autorizza un solo ciclo 3 di `OCOR-DEV-REM-0061`, dal commit `42b5840f35ab94c3b5d53c346f2f508b7dcbbb94`, senza rebase, reset o force-push. Il perimetro è soltanto VF-001, VF-002, VF-003 e VF-004 del verdetto `OCOR-DEV-REM-0061-42b5840f35ab-2`, con RED prima del codice e GREEN dopo. La campagna del ciclo 2 non si trasferisce. Seguono il gate locale, il controllo meccanico dei digest di esecuzione, la revisione preventiva se richiesta, la suite completa e una nuova verifica indipendente sull'HEAD esatto. Il verifier è di fornitore diverso da xAI e da OpenAI. Se il verdetto è ancora `NO_GO` non c'è un ciclo 4: nuova escalation e il task resta bloccato. Claim invariati. Nessun nuovo `DEC-*`.
