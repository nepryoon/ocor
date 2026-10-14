# MAIN-CI-30MIN-JOB-CAP

Stato: `OPEN_PO_DECISION_REQUIRED` — 2026-10-14T13:45:00Z.

Redatta da Claude Code (Anthropic), implementatore di riserva del loop, dopo l'esaurimento della
quota di Codex durante l'integrazione di `OCOR-DEV-REM-0024`. Nessun verifier avviato; nessun
nuovo `DEC-*`.

## Contesto e prove

`OCOR-DEV-REM-0024` ha GO indipendente `OCOR-DEV-REM-0024-22b93473024c-0` (Grok 4.7 via Cursor) sul
candidato `22b93473024cfabb3d013f3516a57eff289c8c0a` ed è sigillata da Codex sull'HEAD
`220543954bda25cc690237292b23f23a4df8ed96` (PR #267, solo metadati, README e hash dei manifest).
Sull'HEAD esatto 10 dei 13 check obbligatori sono verdi al primo tentativo; `rccad-methodology`,
`delivery-activation` e `validation-closure` sono `cancelled` al limite `timeout-minutes: 30` dei
job su `main` (`.github/workflows/ocor-rccad.yml:15`, `ocor-delivery-activation.yml:15`,
`ocor-validation-closure.yml:18`).

| Tentativo | Job | Build e avvio Fuseki | Suite completa | Esito |
|---|---|---|---|---|
| 1 (run 38564429366/041/776) | rccad-methodology | 12m09s | cancellata dopo 16m43s | `cancelled` |
| 1 | delivery-activation | 15m52s | cancellata dopo 13m15s | `cancelled` |
| 1 | validation-closure | 15m39s | cancellata dopo 13m10s | `cancelled` |
| 2 (unico `gh run rerun --failed`) | rccad-methodology | 13m18s | completata in 14m39s | `success` in 29m23s |
| 2 | delivery-activation | 17m07s | cancellata dopo 11m44s | `cancelled` |
| 2 | validation-closure | 15m19s | cancellata dopo 13m42s | `cancelled` |

Nessun test è fallito: le suite sono state interrotte dal limite del job. È la stessa firma delle PR #263
(due tentativi), #264, #265 e #266. Storico di `validation-closure` sulle PR verso `main` dal
2026-10-13 (26 job con durata Fuseki misurata):

- 13 `success`: build Fuseki da 26 s a 556 s, mediana 153 s;
- 13 `cancelled`: build Fuseki da 308 s a 1161 s, mediana 545 s.

La build Fuseki su `main` scarica ogni volta l'archivio Apache senza cache content-addressed. La
cache (decisione `REM-0017-CI-ARCHIVE-ACQUISITION`), il tetto di 75 minuti
(`REM-0017-CI-CAMPAIGN-BUDGET`) e la suite in parti parallele (`REM-0017-CI-CAMPAIGN-DURATION`)
esistono solo nel candidato REM-0017 (PR #169), oggi in attesa di `OCOR-DEV-REM-0032`. Sul solo
`main` la riuscita dipende dalla velocità di download del momento: le esecuzioni notturne
(22:00–07:30 UTC) sono passate, quelle diurne sono state quasi tutte cancellate.

## Impatto

- Nessun merge su `main` è oggi ottenibile in modo affidabile: il sigillo di REM-0024 (PR #267) e
  ogni state sync (PR #263, #264, #266 non integrate; checkpoint `252b216` solo su branch).
- `OCOR-DEV-REM-0028` dipende da REM-0024 integrata ed è quindi bloccata.
- Non bloccati: `OCOR-DEV-REM-0032` (branch `governed/` dal task stage
  `a0ee43d4e502f3589cd857cfec4238eab13fe8e7`, non integra su `main`), REM-0029 e l'ultimo ciclo di
  REM-0027 fino alla loro integrazione.
- Il candidato REM-0017 esegue i propri workflow, con parti e tetti già decisi, e non è toccato da
  questo limite.

## Opzioni

1. **Finestra di integrazione fuori picco (raccomandata come sblocco immediato).** Autorizzare, per
   le PR verso `main` cancellate soltanto per il limite di 30 minuti con un rerun già consumato, un
   nuovo tentativo dei soli job cancellati per HEAD, avviato fra le 22:00 e le 06:00 UTC, dove lo
   storico mostra build Fuseki sotto i 200 s. Nessuna modifica a workflow, test, gate o tetti;
   l'esito di ogni tentativo resta registrato.
2. **Change set CI governato su `main`.** Portare ora su `main` la sola cache content-addressed
   dell'archivio Fuseki e il tetto di 75 minuti già decisi, prima di REM-0017. Sblocco strutturale,
   ma tocca workflow inclusi nei record sigillati di più task (riqualifica con supersession) e
   introduce un conflitto con il candidato REM-0017, che richiederebbe di nuovo l'allineamento.
3. **Attendere l'integrazione di REM-0017.** Nessun merge su `main` finché la PR #169 non porta i
   nuovi workflow; REM-0024, gli state sync e REM-0028 restano fermi per tutta la durata di
   REM-0032 e della nuova coppia CI di REM-0017.

Raccomandazione: opzione 1 subito; l'opzione 3 resta lo sblocco strutturale già pianificato.
L'opzione 2 solo se REM-0017 dovesse restare bloccata a lungo.

## Cosa non è stato fatto

Nessun secondo rerun, nessun merge con `--admin` o bypass, nessuna modifica a workflow, timeout,
test o ruleset, nessuna chiusura o riapertura della PR per ottenere un nuovo run. Inputs intatti;
`E1=0`, `E2=0`, `Verified=0` e tutti i claim `NO-GO` invariati.
