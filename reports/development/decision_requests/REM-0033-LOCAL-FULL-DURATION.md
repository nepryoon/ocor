# REM-0033-LOCAL-FULL-DURATION — rimisurazione REM-0018 sul nuovo host

Status: `OPEN_PO_DECISION_REQUIRED` — notifica non bloccante, nessuna deroga applicata.
Data UTC: 2026-10-25T05:22:47.530596+00:00.

## Contesto e autorita

La decisione PO REM-0017-CI-CAMPAIGN-BUDGET (2026-10-07) mantiene il limite
locale di 75 minuti e richiede notifica oltre 60 minuti. HOST-MIGRATION
(2026-10-24) richiede una misura nuova: le durate del vecchio host non sono
confrontabili. Questa occorrenza aggiorna la richiesta esistente soltanto
con dati della campagna REM-0018, senza modificare documenti storici.

## Misura riproducibile

- Host: Intel Core Ultra 9 275HX, 24 thread, RAM 32504823808 byte;
  kernel 7.0.0-38-generic (nuovo host del mandato HOST-MIGRATION).
- Codice/test: `7fc59409aebf3f632e2dff8925b98f78a2facc11`; branch
  `governed/ocor-dev-rem-0018-anonymous-volume-teardown`.
- Campagna versionata: `scripts/run_qualifying_campaign.py --execute`,
  shell pulita, bootstrap `scripts/bootstrap_ci_environment.py --execute --timeout 600`,
  reset preventivo e stack fissato dai lock; nessun source di bootstrap.env.
- Durata misurata: **3965.363 s**
  (66.089 minuti), sopra 3600 s e sotto 4500 s.
- Conteggi qualificanti: `{"errors": 0, "failures": 0, "skipped": 0, "tests": 3066}`.
  La campagna e' conclusa: `PASS`. Nessun conteggio trasferito da altri run.
- Nessun test, caso, timer, soglia, partizione o gate e' stato cambiato.
  La nuova occorrenza non giustifica un incremento del tetto.
- Evidenza completa e raw nel candidato REM-0018:
  `reports/evidence/G2/OCOR-DEV-REM-0018.json` e `.log`;
  hash dei raw originali della campagna:

```json
{
  "full/campaign_result.json": "2c467b427eca08fe6a83b9954836f0dc4cff0eb0d98c56b7a448283271831695",
  "full/kind-teardown-observations.json": "5929704a134b70d65ceebaeec9ca18094fb86a9d9ec7002739ff831e285d1876",
  "full/post_remediation_runtime.log": "dd08cd931aeb56b842dcdeaedd2515b17690de83deb13934f262fd7622c30637",
  "full/runtime_junit_post_approval.xml": "e805d86ff526d5a9eb9159d8d8d5fe0c8f0431c0130f218da3c92f0637491b3d"
}
```

## Opzioni e raccomandazione

1. Raccomandata: prendere atto della misura e mantenere il tetto locale di
   75 minuti, il monitoraggio e la notifica a 60 minuti invariati. Profilare
   in sola lettura eventuali future ricorrenze prima di proporre interventi.
2. Autorizzare in seguito un change set specifico per ridurre il tempo di
   preparazione o migliorare l'osservazione, con prova di equivalenza e senza
   rimuovere casi o cambiare limiti. Nessuna implementazione di questa opzione
   e' avviata da questa richiesta.

## Impatto e disposizione attesa

Task bloccati: **nessuno**. La campagna e' entro il tetto vigente;
REM-0018 prosegue alla verifica indipendente e ai gate ordinari. Questa
notifica resta su branch governato dedicato in attesa della disposition PO;
non modifica l'allowlist del piano e non viene integrata implicitamente.
La decisione riguarda soltanto questa notifica, non i claim del sistema.

Inputs immutabili; E1=0, E2=0, Verified=0; runtime NOT_ESTABLISHED,
PoC/Production NO-GO. Nessun nuovo DEC o chiusura normativa.
