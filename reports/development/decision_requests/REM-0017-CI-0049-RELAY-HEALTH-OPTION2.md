# REM-0017-CI-0049-RELAY-HEALTH-OPTION2

Stato: `OPEN_PO_DECISION_REQUIRED` — 2026-10-14T11:41:04.969160+00:00.

## Contesto e prove

La coppia autorizzata congiuntamente da `REM-0017-CI-KIND-INSPECT-TIMEOUT` e `REM-0017-CI-0049-RELAY-HEALTH` (2026-10-14) è esaurita sullo stesso HEAD `fad37b47fb25c6a6125df9fd31451f3e3f359036`, PR #169. Run `38548656297`, tentativi 1 e 2 (unico `gh run rerun --failed`, nessun cambio di codice, test, input o harness).

La correzione kind è corretta nella prova eseguita: Helm PASS, `OWNED_KIND_TEARDOWN_OBSERVED`, stesso UUID/destroy/remover nel gruppo pytest, 679 osservazioni di probe, zero rifiuti. La nuova classificazione ops `EXPECTED_READINESS_GATE` è presente; non si propone alcuna riparazione del gate RESTORE_UNTESTED. Le parti 1, 2 e 4 di0049 sono PASS (1/731/871 casi).

La parte3 è FAIL due volte: 620PASS diagnostici e un ERROR di setup su621casi, zero failure/skip, stesso `test_readiness_turns_ready_only_with_a_signed_passed_restore_receipt` (`test_ocor_dev_0049.py:1652`, `_seal_and_restore`, prima del corpo del test). Nel tentativo1 Compose segnala `ocor-relay-typedb` unhealthy; nel tentativo2 `ocor-relay-spire-server`. Nessuna unione qualificante e nessun conteggio trasferito. Nei60s precedenti entrambi gli eventi: CPU100% su tutti gli undici delta5s, load fino a21 su4CPU e memoria disponibile almeno10.67GiB. Primo tentativo: un relay typedb dello stesso gruppo ancora presente mostra `Health check exceeded timeout (3s)` in Health.Log, running/zeroOOM/zero restart. **Health.Log dei due container esatti che bloccano il setup: NOT_EXECUTED**, rimossi prima della cattura della coda (ritardi41s/21s); il dettaglio causale mancante resta esplicito, non ricostruito. Osservatore: zero errori interni, ma questa limitazione di cattura è reale.

L’ipotesi di una causa comune per tutti i precedenti difetti CI non è adottata. È la specifica firma dei probe relay prevista dalla disposizione PO. Il runner più grande, self-hosted e risorse a pagamento restano esclusi; qui è esaurita una sola coppia post-correzione kind, non si avvia la configurazione di altre risorse. Nel secondo tentativo la somma dei tempi JUnit1893.29s supera30min: il riequilibrio N è già autorizzato dalla decisione duration, senza alzare45min; non autorizza nuovi tentativi della coppia qui esaurita.

## Remediation attivata e vincolo d’ordine

`OCOR-DEV-REM-0032` è registrata con ID verificato libero dopo la registrazione versionata diREM0031: ambito `deploy/helm/ocor-poc/compose.profiles.yaml:63` (relay-probe, intervallo2s/timeout3s/15tentativi, nessuno start_period), RED sotto CPU limitata, start_period e budget coerenti con PoC, GREEN positivi/negativi reali, riqualifica0049 con nuova supersession e sigilli storici intatti. Non è implementata. La decisione PO la colloca **dopo** il merge0049 e primaG6; oggi il percorso REM0017→merge0049 è bloccato proprio da questa firma: l’anticipazione richiede una disposizione esplicita, non è inferita dal mandato.

## Opzioni e raccomandazione

1. **Anticipare la sola REM0032 sulla linea candidata0049 (raccomandata).** Autorizzare il raffinamento dei probe/startup, con ambito chiuso e prove reali CPU-limited, riqualifica0049, budget CI nuovo esplicito; nessun caso, gate, immagine o contratto viene indebolito. Coordinare il successivo riequilibrio N già autorizzato in REM0017, con campagna nuova sul nuovo harness. Distinta unità governata: implementatore/verifier secondo i ruoli effettivi e nessuna modifica ai sigilli storici.
2. Mantenere l’ordine dopo0049 e autorizzare prima soltanto una diagnosi/riproduzione dedicata e bounded della firma relay, senza altri run CI finché non cambia una condizione rilevante. La catena d’integrazione resta bloccata; proseguono le remediation indipendenti.

Nessun altro rerun, nessun bypass, esclusione o skip. Non si aumenta alcun tetto. Si richiede la disposizione dell’opzione2 della precedente decisione relay-health, non un nuovo DEC né una promozione di evidenze.

## Evidenza e impatto

Record `reports/assurance/OCOR-DEV-REM-0017-RCCAD/ci-fad37b4-relay-recurrence.json`; raw `.log` SHA256 `a726e44769a68695314e181268cc006692a6ef538aeaeb0ab58a45a67b87133f`; due zip e manifest health indipendentemente verificati, primo tentativo conservato in attempts. Registro dei consumer/ruoli: implementazione nuova Codex, contributi riservaClaude preservati, verifier previstoCursor/Grok non avviato. Nessuna richiesta di verifica/sigillo/merge del candidato.

Bloccati: REM0017, integrazione0049/REM0019, REM0023,0056/0057 e relativo percorsoG6. Pronto: REM0024 GO su22b9347 (integrazione propria), poiREM0028,REM0029, ultimo cicloREM0027 eREM0031 secondoQUEUE-TO-G6-ORDER. REM0032 attende la collocazione autorizzata. Il loop continua; non è TERMINAL_BLOCKED. Inputs intatti;E1=0,E2=0,Verified=0 e tutti iNO-GO invariati.
