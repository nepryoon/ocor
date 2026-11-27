# FABLE52-ALIGNMENT-GUARD-ENFORCEMENT

Status: `OPEN_PO_DECISION_REQUIRED`. Livello: operativo (CI e protezione del ramo `main`). Origine: audit
`reports/review/OCOR_FABLE52_AUDIT_2026-11-11.md`, finding F-04, F-08, F-09, F-10, F-11, su `main`
`113f935cf6e04df460406a0b5dfea6949df6723a`. Redatto da Claude Fable 5.2 (Anthropic) in sola lettura.

## Contesto

- I tredici check obbligatori girano sull'evento `pull_request`: workflow e validatori sono quelli del change set
  che devono giudicare (`.github/workflows/ocor-rccad.yml:3-7`, `ocor-poc-ci.yml:3-7`). `CODEOWNERS` ha un solo
  account ed è consultivo (`.github/CODEOWNERS:1-3`).
- Il change set dell'audit aggiunge `.github/workflows/ocor-alignment-guard.yml` (evento `pull_request_target`:
  esegue il validatore della revisione di base e legge l'head come dati, senza checkout né esecuzione) e
  `scripts/validate_alignment_invariants.py`. Bloccanti dal primo giorno: D01 (`inputs/` e baseline approvate),
  D02 (claim), D03 (evidenza sigillata in sola aggiunta). Rieseguiti sulle ultime 69 integrazioni di `main`: nessun
  esito bloccante. Gli altri controlli (S01-S10, D04-D07) sono consultivi secondo
  `reports/development/ALIGNMENT_BASELINE.json`.
- Dal 2 dicembre 2026 GitHub disattiva per default `pull_request_target` nei repository pubblici senza una event
  policy propria (regola in modalità di valutazione dal 17 settembre 2026).

## Opzioni

1. **Guard obbligatorio, controlli consultivi promossi per gradi (raccomandata).** Azioni del PO sul server, da
   eseguire dopo il merge del change set: (a) event policy del repository che ammette `pull_request_target` per
   `ocor-alignment-guard.yml`; (b) aggiunta del contesto `alignment-guard` ai check obbligatori del ruleset
   `23412233`. I controlli S05, S06, S07, D04, D05 e D06 passano a `BLOCKING` nella baseline, ciascuno dopo dieci
   integrazioni consecutive senza nuovi finding e dopo la correzione delle voci registrate che lo riguardano
   (unità delle decision request `FABLE52-RUNTIME-PACKAGING-AND-CLI` e `FABLE52-EVIDENCE-TOOLS-VERSIONING` e
   pinning dei workflow). Il cambio di modalità è una modifica della baseline con riferimento a questa decisione.
2. **Guard obbligatorio, tutti i controlli bloccanti subito.** Come l'opzione 1, senza gradualità: le unità in corso
   che citano strumenti fuori repository o percorsi personali falliscono finché non si adeguano.
3. **Guard solo consultivo.** Il workflow gira e pubblica il referto, senza entrare nel ruleset.

## Impatto a cascata

Opzione 1: nessun file oltre a quelli del change set; due azioni sul server; una unità breve (stima 2 iterazioni) per
il pinning delle nove azioni con tag mobile e dei due runner (`ocor-poc-ci.yml`, `ocor-supply-chain.yml`,
`ocor-lld-add-alignment.yml`, `ocor-tooling-bootstrap.yml`, `ocor-auto-merge.yml`), con le riqualifiche dei record che
hanno quei workflow fra gli input. Il loop usa lo stesso validatore prima della richiesta di verifica
(`PRE-VERIFY-GATE (2026-11-11)`), quindi un esito bloccante si vede prima della CI.

## Criteri di accettazione verificabili

- `gh api repos/nepryoon/ocor/rulesets/23412233` elenca `alignment-guard` fra i contesti obbligatori.
- Una pull request di prova che modifica un file sotto `inputs/` ha il check `alignment-guard` rosso con D01; una
  che aggiunge solo un nuovo record di evidenza lo ha verde.
- Dopo l'unità di pinning, `python3 -I scripts/validate_alignment_invariants.py --root .` non riporta voci S05.

Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
