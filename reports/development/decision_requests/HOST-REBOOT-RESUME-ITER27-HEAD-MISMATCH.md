# HOST-REBOOT-RESUME-ITER27-HEAD-MISMATCH

Stato: `RESOLVED_PO_DECISION_OPTION_1` (disposition PO 2026-10-15). Rilevazione: 2026-10-15T13:47:08.820958+00:00. Autore: Codex.

## Contesto

`HOST-REBOOT-RESUME-ITER27`, punto 1, prescrive la verifica degli HEAD locali prima di ogni altra azione: «Se gli head non coincidono, fermati e apri una decision request».
La prima verifica di questa iterazione ha rilevato:

| Branch | HEAD richiesto | HEAD osservato | Esito |
|---|---|---|---|
| `governed/ocor-dev-rem-0033-kind-bootstrap-exec-probe` | `3c8f2eba711cac1a180ae36df452dc0707efe205` | `ccb372272631a2e0500f57c87ec56cd7409a4652` | `MISMATCH` |
| `governed/ocor-dev-rem-0028-approver-revalidation` | `1974738` | `19747383d3d570b2ffbb503a1878c49d140b8032` | `MATCH` |

`main` è pulita e allineata dopo fetch a `origin/main` `9b4d3be8ec5bd785b02072a99037dd801b53d9a5`. Il worktree REM-0033 è pulito. Entrambi i branch sono stati conservati, senza reset, rebase, force-push, campagne o modifiche.

## Ricostruzione in sola lettura

`git log` mostra `ccb372272631a2e0500f57c87ec56cd7409a4652` come figlio diretto di `3c8f2eba711cac1a180ae36df452dc0707efe205`. Il commit aggiuntivo è `assurance(rem-0033): record post-reboot qualification and 0050 regression supersession`; il diff riguarda soltanto cinque file di evidenza/manifest:

- `reports/assurance/OCOR-DEV-REM-0033-RCCAD/OCOR-DEV-REM-0033.json`;
- `reports/assurance/OCOR-DEV-REM-0033-RCCAD/OCOR-DEV-REM-0033.log`;
- `reports/evidence/G5/MANIFEST.json`;
- `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0033-20261015.json`;
- `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0033-20261015.log`.

La PR [#281](https://github.com/nepryoon/ocor-detailed-design/pull/281) pubblica già lo stesso HEAD: i 13 check obbligatori per nome risultano `completed`/`success`, compreso `validation-closure`. Run osservati: `38738364384`, `38738364401`, `38738364413`, `38738364432`, `38738364442`, `38738364472`. Sono risultati preesistenti, non esecuzioni di questa iterazione.
Il checkpoint versionato `2c31ae59d05cbcfd26801dd632a600e845baaea5` sul branch `governed/state-sync-rem0033-reboot-resume-20261015` registra la qualifica post-reboot e la richiesta di verifica; non è su main.

È presente il verdetto esterno `OCOR-DEV-REM-0033-ccb372272631-0`, HEAD `ccb372272631a2e0500f57c87ec56cd7409a4652`, `NO_GO`, SHA256 `8c96a137233e5e95fec8177c8cd87d02c8b8328c7d120bb4b55e420fa2c43f48`, verifier Grok 4.7 tramite Cursor. VF-001 (high, bloccante): la scomparsa del nodo dopo il recupero del probe può restituire una mappa vuota senza prova v2 di destroy e remover. Richiesti rifiuto o prova v2 anche in tale percorso e negativo deterministico. Le suite live completa e 0050 non rieseguite dal verifier restano `NOT_EXECUTED` nel verdetto. Nessun verdetto è stato modificato. CI verde non supera il `NO_GO`.

## Opzioni e raccomandazione

1. Riconoscere esplicitamente `ccb372272631a2e0500f57c87ec56cd7409a4652` come nuovo checkpoint di ripresa, conservando storia ed evidenze post-reboot. Dopo la disposition: primo ciclo ordinario di riparazione di REM-0033 su VF-001, prove richieste dal cambio di harness e nuova verifica Grok 4.7 via Cursor. Raccomandata: l'avanzamento è tracciato e non richiede scarti o riscritture.
2. Indicare un diverso checkpoint non distruttivo e la disposition delle evidenze e della PR #281 prima di riprendere. Nessun ritorno automatico al precedente HEAD.

La discrepanza non dimostra un difetto di supply chain né un nuovo fallimento di test. Si applica la condizione esplicita di arresto del PO. Questa registrazione non consuma cicli di riparazione.

## Impatto e prossima azione

REM-0033 resta non sigillata e non integrabile, per il vincolo di ripresa e VF-001. REM-0028 resta ferma a `1974738`. Nessun'altra unità viene avviata in questa iterazione di arresto. L'ordine scanner → REM-0019 → REM-0023 → 0056 e successivi resta invariato; nessuna nuova dipendenza normativa.
Dopo la disposition del PO: verificare nuovamente gli HEAD e riprendere il checkpoint autorizzato. Non ripetere campagne già registrate senza una ragione richiesta dal codice/harness modificato. Ruoli: harness originario Claude Code; qualifica post-reboot Codex; verifier Grok 4.7 (Cursor), processo e contesto separati.

Checksum normativi in questa iterazione: `PASS` 8/8. Stack, suite e qualifica runtime: `NOT_EXECUTED` per arresto prescritto. Nessun container creato, avviato o rimosso. Il reboot del 2026-10-15 13:20 CEST resta interruzione infrastrutturale, senza conteggi PASS/FAIL; i run successivi preesistenti non sono ripetuti qui.
Inputs intatti; E1=0, E2=0, zero requisiti globali Verified, runtime NOT_ESTABLISHED, PoC e Production NO-GO invariati. Nessun nuovo DEC.

## Disposition del Product Owner — 2026-10-15 (opzione 1)

`HOST-REBOOT-RESUME-ITER27-HEAD-MISMATCH` supersede soltanto il punto 1 della decisione
operativa di ripresa: il controllo di uguaglianza era unico, è già stato assolto alle
13:45 CEST e non va più ripetuto. La discrepanza nasce dalla formulazione dell'istruzione,
non da un difetto. Gli altri punti, incluso il carattere infrastrutturale del reboot,
restano validi.

Il checkpoint autorizzato è `ccb372272631a2e0500f57c87ec56cd7409a4652`; si conserva tutta
la storia, senza reset, rebase distruttivi o force-push. REM-0028 resta ferma a `1974738`
fino all'integrazione di REM-0033. Il ciclo 1 corregge VF-001 con RED prima del codice,
rifiuto fail-closed o prova v2 completa dopo il recupero; mappa vuota mai equivalente a
successo in quel percorso. Finestra 30 s, timeout, timer e gate invariati. Le prove del
cambio di harness precedono una nuova verifica esterna Cursor/Grok.

Esecuzione Codex (OpenAI), 2026-10-16 UTC: RED `TeardownObservationError not raised`, poi
riparazione `bb5b20940548662b5f621a2d6fae6a9848cd9066`; 167 test e 42 subtest GREEN.
Checkpoint pubblicato sul branch candidato: `beeaf5e` (discendente di `ccb3722`). Full
locale e regressione 0050 sul nuovo albero: `NOT_EXECUTED`, bootstrap Keycloak bloccato
dalla porta host 8080 occupata dal proxy di agente Antigravity, non modificato. Nessuna
richiesta di verifica o sigillo fino alla qualifica locale completa. Record del checkpoint:
`reports/assurance/OCOR-DEV-REM-0033-RCCAD/OCOR-DEV-REM-0033.json` sul branch candidato.

Questa richiesta è risolta; il precedente arresto TERMINAL_BLOCKED per la discrepanza
non è più attivo. L'impedimento di porta è distinto e non riapre il controllo di HEAD.
Ordine invariato: REM-0033 → scanner → REM-0019 → REM-0023 → 0056 e successivi.
Ruoli secondo `LOOP-AGENT-ROTATION` (2026-10-16): implementatori REM-0033 Claude Code
(Anthropic) e Codex (OpenAI); verifier previsto Grok 4.7 via Cursor (xAI), esterno.
