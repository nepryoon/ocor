# FABLE52-EXTENSION-NCP-U15-ID-COLLISION

Status: `DECIDED_BY_PO`. Livello: normativo. Nessun nuovo `DEC-*`.
Opzione adottata: **1**, come raccomandato, dalla decisione
`FABLE52-EXTENSION-NCP-U15-ID-COLLISION (2026-11-13)`. Il testo della richiesta,
sotto questa disposition, resta quello aperto al commit
`142514fa302f23a49ee5695a2e25da6bb3f4054a`.

## Disposition

`NCP-U15` resta l'unità dei reason code sul WIP
`governed/ocor-dev-rem-0060-ncp-u12-tests`, commit
`b869cc9c0e92b6d23b386cf5162c07d3ebc12aec`. Il WIP non si rinomina.
Le due voci nuove, ammissione dei claim e risoluzione delle identità, usano il
primo identificativo di plan unit libero dopo quelle già presenti sul WIP,
verificato in sola lettura al momento della scrittura. Hanno gli stessi campi
che `FABLE52-EXTENSION-ASSESSMENT (2026-11-12)` assegnava a `NCP-U15`: stima 8,
dipendenza da `NCP-U12`, le due sole voci, backend reale già usato da C3, C4 e
C6. La voce della vista del mission thread resta `DECISION_REQUIRED`, senza
`plan_unit`. La scrittura sul registro di conformità è un'unità governata
successiva, con revisione preventiva e verifica indipendente. Non tocca il
backlog approvato né `OCOR-DEV-REM-0061`. Non precede `OCOR-DEV-REM-0063`:
`REM-0061-CYCLE5-PRIORITY (2026-11-13)` fa riprendere quel profilo subito dopo
la richiesta di riprogettazione del ciclo 5. Claim invariati: `E1=0`, `E2=0`,
`Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessun nuovo
`DEC-*`. Nessuna modifica a `inputs/`.

## Contesto

`FABLE52-EXTENSION-ASSESSMENT (2026-11-12)` assegna la plan unit `NCP-U15`
alle due voci nuove di ammissione dei claim e di risoluzione delle identità,
con stima 8, `depends_on_units` `NCP-U12`, e stabilisce che l'unità risolve
quelle due voci e nient'altro. La terza voce, la vista del mission thread,
resta `DECISION_REQUIRED` e non ha `plan_unit`.

Su `main` al commit `db8854bf8f8abf43abcf5df943ea0a9bfdcc4c15` `plan_units`
non contiene `NCP-U15`. L'ultimo identificativo presente è `NCP-U14`.

Sul branch non integrato `governed/ocor-dev-rem-0060-ncp-u12-tests`, commit
`b869cc9c0e92b6d23b386cf5162c07d3ebc12aec`, `plan_units.NCP-U15` esiste già.
Stato `PROPOSED`, stima 5, `depends_on_units` `["NCP-U12"]`. Risolve dieci
voci di reason code: `NCR-C2-014`, `NCR-C6-015`, `NCR-C7-008`, `NCR-C6-016`,
`NCR-C6-017`, `NCR-C8-009`, `NCR-C6-018`, `NCR-C6-019`, `NCR-C5-004` e
`NCR-C7-009`. Lo scope registrato è l'insieme chiuso dei reason code dei
componenti retained, da `NCP-U12-REASON-CODE-ENTRIES-PLAN (2026-11-10)`,
opzioni A1 e B1. Quel branch è il WIP di `OCOR-DEV-REM-0060` e non è su `main`.

Le due assegnazioni non possono occupare lo stesso identificativo senza
perdere un perimetro già deciso oppure allargare `NCP-U15` oltre il «nient'altro»
di `FABLE52-EXTENSION-ASSESSMENT (2026-11-12)`. Il registro su `main` non è
stato modificato. I primi identificativi liberi verificati in sola lettura su
`main` sono `NCR-C3-008`, `NCR-C3-009` e `NCR-PLAN-007`. Non sono stati scritti.

## Opzioni

1. **NCP-U15 resta l'unità dei reason code.** Le due voci nuove di ammissione dei claim e di risoluzione delle identità usano il primo identificativo di plan unit libero dopo quelle già presenti sul WIP, con gli stessi campi che `FABLE52-EXTENSION-ASSESSMENT (2026-11-12)` assegna a `NCP-U15` (stima 8, dipendenza da `NCP-U12`, le due sole voci, backend reale già usato da C3, C4 e C6). La voce della vista del mission thread resta `DECISION_REQUIRED`, senza `plan_unit`. Il WIP di `OCOR-DEV-REM-0060` non si rinomina.
2. **NCP-U15 è solo l'unità di questa decisione.** Su `main` si scrive `NCP-U15` come la descrive `FABLE52-EXTENSION-ASSESSMENT (2026-11-12)`. Al riprendere di `OCOR-DEV-REM-0060` le dieci voci di reason code passano al primo identificativo libero successivo, senza cambiare i loro criteri. Fino a quel riallineamento il WIP non si integra.
3. **Una sola unità, due perimetri.** `NCP-U15` risolve sia le dieci voci di reason code sia le due voci nuove. La stima diventa la somma delle due stime. Questa opzione contraddice il «nient'altro» della decisione del 2026-11-12.

## Raccomandazione

Opzione 1. L'unità dei reason code è già specificata da decisioni precedenti e sta sul WIP che deve integrarsi prima che l'unità di ammissione dei claim sia eseguita: `FABLE52-EXTENSION-ASSESSMENT (2026-11-12)` punto 3 la pone dopo l'integrazione di NCP-U12. Rinominare l'unità in corso sposta un perimetro già scritto. I criteri delle voci nuove non dipendono dalla cifra dell'identificativo.

## Impatto e task bloccati

Nessun task del backlog è bloccato da questa richiesta. `OCOR-DEV-REM-0061` resta bloccato dal `NO_GO` del ciclo 4, per la decisione già presa, e `OCOR-DEV-REM-0060` resta in coda fino al suo merge: non per questa richiesta. I task G6 restano sospesi come già deciso. È bloccata solo la scrittura sul registro di conformità delle tre voci e della plan unit descritte dal punto 2 di `FABLE52-EXTENSION-ASSESSMENT (2026-11-12)`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessuna modifica a `inputs/`.
