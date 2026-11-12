# Escalation record — OCOR-DEV-REM-0061 (repair budget exhausted)

- **Status**: `BLOCKED_REPAIR_BUDGET_EXHAUSTED`
- **Unità**: `OCOR-DEV-REM-0061`
- **Branch**: `governed/ocor-dev-rem-0061-lane-image-cache`
- **HEAD del ciclo 2**: `42b5840f35ab94c3b5d53c346f2f508b7dcbbb94`
- **Verdetto**: `OCOR-DEV-REM-0061-42b5840f35ab-2`, `NO_GO`
- **Sha256 del verdetto**: `6585d51d9f02d17d2acdedc309ada4f6f935138de9a375ef74bf2769817cae7f`
- **Repair cycle**: 2, ultimo del budget ordinario. Il ciclo 3 non è avviato.
- **Decision request**: `reports/development/decision_requests/REM-0061-REPAIR-BUDGET.md`
- **PR candidata**: #595, bozza, non integrata

## Implementatori e verifier

- Implementatore dei cicli, compreso il ciclo 2: Grok Build, modello grok-4.7, fornitore xAI.
- Codex (OpenAI) è contato fra gli implementatori del task.
- Revisore preventivo del ciclo 2: Cursor, modello cursor-grok-4.6-xhigh, fornitore xAI,
  richiesta `OCOR-DEV-REM-0061-55c3272cf1ef-pre`. Esito letto: un finding bloccante, corretto
  prima della campagna. La revisione non è stata ripetuta.
- Verifier dei cicli 0, 1 e 2: Codex, fornitore OpenAI, processo separato, non avviato
  dall'implementatore. Esiti: `NO_GO`, `NO_GO`, `NO_GO`.

## Storia dei verdetti

- Ciclo 0, `OCOR-DEV-REM-0061-69bbc51fb031-0`: `NO_GO`. La verifica si è fermata per quota
  della directory temporanea prima di pytest.
- Ciclo 1, `OCOR-DEV-REM-0061-1c8a94b9e71e-1`, HEAD `1c8a94b9e71e9c60e8d4b3c4365b43e402715e2f`:
  `NO_GO`. Due finding high e uno medium.
- Ciclo 2, `OCOR-DEV-REM-0061-42b5840f35ab-2`: `NO_GO`. Quattro finding high, tutti bloccanti.
  La campagna del verifier è PASS (5826 test, zero skip, unione esatta, residuo vuoto) e non
  chiude i finding.

## Diagnosi

I quattro finding descrivono lacune fail-closed nel perimetro già richiesto:

1. VF-001. Lo spazio libero del filesystem non blocca l'ammissione delle corsie quando la
   quota è assente, illimitata, o finita ma non è il vincolo più stretto.
2. VF-002. La cache di lavoro resta sul disco quando il percorso di pulizia considera solo
   il consumo di quota.
3. VF-003. Un errore di redazione del log salta il teardown e la rimozione dei work tree.
4. VF-004. Un record canonico illeggibile è escluso in silenzio e il gate può accettare il
   predecessore.

La suite ordinaria verde non copre questi casi. I conteggi della campagna del ciclo 2 non
si trasferiscono a un eventuale ciclo successivo.

## Azione minima di sblocco

Serve una decisione del Product Owner. L'azione minima, se autorizzata, è un solo ciclo 3
limitato ai quattro finding, con prove RED e GREEN dei casi avversariali, campagna nuova e
verifica di un fornitore diverso da xAI e da OpenAI. Senza quella decisione il codice non
si modifica e la PR #595 non si integra.

## Effetto sulla coda

`OCOR-DEV-REM-0060` resta in coda fino al merge di `OCOR-DEV-REM-0061`. I task G6 restano
sospesi. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`,
PoC e Production `NO-GO`.
