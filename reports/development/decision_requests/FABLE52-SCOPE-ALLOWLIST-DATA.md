# FABLE52-SCOPE-ALLOWLIST-DATA

Status: `OPEN_PO_DECISION_REQUIRED`. Livello: operativo (processo e validatori; nessun requisito, ADD, LLD o contratto
cambia). Origine: audit indipendente `reports/review/OCOR_FABLE52_AUDIT_2026-11-11.md`, finding F-01, su `main`
`113f935cf6e04df460406a0b5dfea6949df6723a`. Redatto da Claude Fable 5.2 (Anthropic) in sola lettura.

## Contesto

- `scripts/validate_ocor_development_plan.py` contiene l'elenco dei percorsi ammessi (`extension_paths`, da riga 274;
  regola alle righe 1776-1788, controllo «authorized planning-only diff»). Ogni unità aggiunge i propri percorsi
  all'elenco nello stesso change set che l'elenco deve autorizzare: il controllo prova che i percorsi sono stati
  dichiarati, non che erano autorizzati.
- Lo stesso file è input sigillato di 134 record di evidenza. Ogni aggiunta all'elenco ne cambia lo sha256 e obbliga
  alle riqualifiche di sola regressione dei record che lo citano (`0005`, `0050` e `0082` a ogni unità).
- Il costo ricade su ogni unità, comprese quelle che non toccano codice.

## Opzioni

1. **Elenco come dato legato alle decisioni (raccomandata).** I percorsi passano in
   `docs/development_plan/OCOR_AUTHORIZED_PATHS.json`: una voce per unità con `decision` (identificativo di una
   decisione registrata in `po_normative_decisions_registered` o di un task del backlog), `unit` e `paths`. Il
   validatore del piano legge il file e non cambia più a ogni unità. Il controllo base-anchored
   (`ocor-alignment-guard`) legge il file dalla revisione di base e accetta nel change set solo le voci nuove la cui
   `decision` esiste nello stato della base. Un'ultima riqualifica di `0005`, `0050` e `0082` per la modifica del
   validatore; poi nessuna riqualifica dovuta all'elenco.
2. **Elenco come dato, senza legame con le decisioni.** Come l'opzione 1 ma senza il campo `decision` e senza il
   controllo dalla base: elimina le riqualifiche, lascia l'auto-autorizzazione.
3. **Nessuna modifica.** L'elenco resta nel validatore; le riqualifiche continuano.

## Impatto a cascata

Opzione 1: `scripts/validate_ocor_development_plan.py` (lettura del file, elenco storico migrato senza perdita di
voci), nuovo `docs/development_plan/OCOR_AUTHORIZED_PATHS.json`, `scripts/validate_alignment_invariants.py` (nuovo
controllo D08 sulle voci aggiunte), `reports/tests/` (RED prima del codice), `reports/planning/OCOR_PLAN_RUN_STATE.json`
(solo hash), riqualifiche di sola regressione dei record con input toccati, una unità di remediation di stima 3
iterazioni. Nessun workflow esistente cambia.

## Criteri di accettazione verificabili

- Dopo l'unità, `git diff --stat` di una unità successiva che aggiunge file non contiene
  `scripts/validate_ocor_development_plan.py`.
- Un change set che aggiunge un percorso con `decision` assente dallo stato della base fa fallire D08 (caso negativo
  nei test); con `decision` presente passa (caso positivo).
- Il numero di voci migrate è uguale al numero di percorsi di `extension_paths` al commit precedente (test di parità).
- `validate_evidence_input_drift.py` PASS dopo le riqualifiche; nessun record sigillato modificato.

Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
