# OCOR-DEV-REM-0022 — Lifecycle e teardown Kafka

Status: `SEALED_PENDING_EXACT_GREEN_CI`. Candidato verificato `a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8`: GO Claude Code per REM-0022/0019/0040; GO Grok 4.7 via Cursor per la sola regressione 0050 autorizzata dal PO. Il finding sul retry del teardown resta `OPEN_NONBLOCKING`; il difetto preesistente di audit admission resta aperto in REM-0023. Nessun nuovo ciclo di riparazione. Il primo FAIL del gate di piano e i verdict precedenti restano storici.

La suite completa di REM-0019 aveva lasciato quattro volumi anonimi attribuiti a
`KafkaCli`, oltre a quattordici volumi senza prova sufficiente di ownership. La
pulizia successiva del run non qualificava il teardown. `KafkaCli` e
`CanonicalEventBackbone` omettevano entrambi `--volumes` nella rimozione del
container; il fallimento di una creazione già avvenuta non rimuoveva il container.

La remediation mantiene immagine e semantica degli eventi. Ogni lifecycle assegna
una label di ownership a broker, inizializzatore e volume dati; rifiuta collisioni
prima dell'uso. La rimozione verifica coppia di nomi e label prima di mutare,
usa gli ID immutabili dei container, rimuove i mount anonimi e il solo volume
nominato del run, poi verifica l'assenza delle risorse. Il `finally` copre anche
provisioning parziale, inizializzatore interrotto e scadenza della readiness.
Errori Docker e residui sono propagati; nessun prune globale. La pulizia di risorse
ormai assenti è idempotente. I volumi storici senza ownership provata restano intatti.

I test RED precedono il codice: due teardown normali lasciano il mount anonimo,
due interruzioni dopo il reale `docker run` lasciano il volume dati in uso. Il
primo errore di importazione (`PYTHONPATH` mancante) è conservato come diagnostico e
non è il RED comportamentale. I 22 nuovi casi eseguono Docker e l'immagine Kafka
fissata; i fault sono nella gestione locale di errore/clock e non simulano risposte
di successo del broker. I casi di residuo volutamente indotto verificano il
rifiuto e ripuliscono soltanto i mount osservati del test. Questo cleanup non
nasconde un fallimento di teardown del percorso positivo.

La nuova allowlist del validator di piano elenca esattamente il modulo di test, i
file di evidenza, il sorgente Kafka già autorizzato e il relativo record di disposition. Non cambia alcun controllo e richiede
la riqualifica di 0050; il self-hash del validator nel planning state è riallineato.
Le riqualifiche di 0019, 0040 e 0050 hanno nuovi raw log, hash riacquisiti e
`supersedes` esplicito. I record sigillati e i relativi log restano byte-identici.
Il caso di regressione storico di 0040 con due fallimenti di interprete non è
trasferito come eccezione: la nuova regressione deve avere zero failure/error/skip.

Per i conteggi, i tempi, la raccolta/JUnit, l'ownership e i comandi realmente
eseguiti fanno fede i record JSON e i raw JSONL allegati. I comandi non eseguiti
non sono PASS. La regressione completa parte da reset/bootstrap, con 11 servizi
READY e SVID reale, e si interrompe al primo riavvio/OOM/uscita del bootstrap o
al limite di 75 minuti. Gli inventari prima/dopo devono coincidere, prima del
teardown di fine sessione. I raw degli eventi Docker conservano identità e
ownership; gli argomenti degli exec e le credenziali locali restano privati.

Implementatore attuale: Codex (OpenAI). Verifier di REM-0022 e delle riqualifiche
Kafka: Claude Code, fornitore/processo/contesto separati, avviato solo dal loop.
La riqualifica di 0050 richiede inoltre Cursor/Grok 4.7 perché 0050 è stato toccato
dall'implementatore di riserva Claude Code. Entrambi i verdetti sullo stesso HEAD
sono obbligatori prima di sigillare o aprire la PR; nessun verifier è lanciato qui.

Rollback: nuova revert del change set; nessuna migrazione dei dati, variazione di
API o decisione normativa. Una revert mantiene bloccata la qualifica dipendente
dall'igiene dello stack. Dopo chiusura verificata: REM-0019 ciclo 1, REM-0017,
integrazione di 0049, REM-0023 e ripresa del WIP 0056. `E1=0`, `E2=0`, zero `Verified`,
conformance `NOT_ESTABLISHED`, PoC/Production `NO-GO`; `inputs/` immutabile.
