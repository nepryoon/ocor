# REM-0063-PINNED-FIXTURE-DIFF-CHECK

Status: `OPEN_PO_DECISION_REQUIRED`. Livello: operativo. Nessun nuovo `DEC-*`.

## Contesto

`git diff --check 4b277f76b743466f6f96245b5666d536d14a6a94..HEAD` esce 2 sul branch `governed/ocor-dev-rem-0063-mcp-profile`. L'unica riga è `ocor-runtime/tests/fixtures/mcp/2026-07-28/schema.json:3963: new blank line at EOF.` La fixture è lo schema ufficiale fissato byte per byte (`DEPENDENCY.md`). Togliere la riga vuota cambia il digest pinnato. Il comando non è un passo dei workflow in `.github/`: è il controllo di presentazione registrato nel gate locale dei cicli precedenti. Sugli altri 51 passi locali del gate, rieseguiti sull'HEAD di codice `3c2a95f4f00553b181e4ba2d54f69a7d7bd76d4c`, l'esito è PASS; sei passi solo CI restano `NOT_EXECUTED`. `git diff --check` resta `NOT_GREEN`. La fixture non è stata modificata. L'allowlist del piano non è stata allargata: questo file sta solo su questo branch.

VF-002 del verdetto `OCOR-DEV-REM-0063-875169cae96f-8` è low e non bloccante. Il `required_fix` chiede una disposition governata del conflitto fra la fixture pinnata e il controllo di presentazione. La revisione preventiva `OCOR-DEV-REM-0063-3c1fa6fa53a6-pre` (P11, advisory) chiede di pubblicare la richiesta su un branch dedicato, come le richieste precedenti di `OCOR-DEV-REM-0063`. Questa richiesta non blocca la verifica del ciclo 9. Non rende verde `git diff --check`.

Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Opzioni

1. **Eccezione registrata, fixture invariata.** Il PO registra che la riga vuota finale della fixture ufficiale resta, e che `git diff --check` su quel solo file esce 2. Il comando non si dichiara PASS. Gli altri file del diff restano sotto lo stesso controllo. Non cambiano la fixture, il digest, i test, i gate, i timer, le partizioni, le immagini. Dopo l'adozione, il verifier non tratta quell'unica riga come finding bloccante. Fino all'adozione lo stato nel record resta `NOT_GREEN` e `OPEN_PO_DECISION_REQUIRED`.
2. **Aggiornare la fixture.** Il PO autorizza la rimozione della riga vuota, il nuovo digest, e la riqualifica di ogni record che pinna la fixture. Solo dopo quel change set `git diff --check` può essere verde. È un cambio di un artefatto pinnato.
3. **Lasciare il conflitto senza eccezione.** Nessun cambio di fixture e nessuna eccezione. Il comando resta `NOT_GREEN`. Il ciclo 9 prosegue. Un verifier può ripetere VF-002 come non bloccante.

## Raccomandazione

Opzione 1. La fixture è lo schema ufficiale byte per byte. Togliere la riga vuota per soddisfare un controllo di presentazione cambia un digest pinnato. Escludere il file dal comando, o dichiarare il comando verde, indebolirebbe il controllo. L'opzione 1 non trasforma l'uscita 2 in PASS: registra l'eccezione. L'opzione 3 lascia la stessa contraddizione al verifier successivo.

## Impatto e task bloccati

Nessun task è bloccato. La verifica del ciclo 9 di `OCOR-DEV-REM-0063` prosegue. Non si integra questo branch. Non si modifica `inputs/`. Non si allarga l'allowlist. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
