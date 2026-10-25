# OCOR-DEV-REM-0018-RCCAD — anonymous volume teardown in spike tests

Status: `OPEN`, non implementato, nessuna evidenza qualificante.

Fonte: VF-004 del verdetto indipendente Claude Code
`OCOR-DEV-REM-0017-6e2a08b62524-0` (2026-10-07).
ID verificato libero: ricerca degli identificativi REM nel repository corrente e
nei worktree OCOR esistenti; massimo assegnato 0017, successore libero 0018.
Nessuna rinomina di storia o decisione normativa.

## Difetto e perimetro

`spikes/vector_partition/oracle.py` e `spikes/kafka_delivery/oracle.py`
invocano `docker rm --force` senza eliminare i volumi anonimi delle immagini.
Il verifier ha osservato 18 residui per suite completa (36 in due campagne),
non rilevati dal filtro per label Compose. Lo stack bootstrap non è l'unica
fonte di risorse create dai test.

La futura unità governata deve correggere esclusivamente il teardown degli
spike e qualificare le risorse create da ogni test, anche al fallimento, senza
eliminare volumi estranei. Cambiare input sigillati richiede riqualifica nello
stesso change set dei task coinvolti (0019/0023 da verificare sul manifest).
Questo record apre il task; non corregge gli spike nello scope REM-0017.

## Criteri eseguibili prima della modifica

- Test positivi con immagini reali pinned: alla fine del test container,
  reti e volumi creati dal test sono assenti; baseline Docker estranea invariata.
- Test negativi: errore dell'oracolo o timeout non impediscono il teardown;
  un residuo è un fallimento esplicito. Nessuno skip qualificante.
- RED sul comportamento attuale, GREEN sul teardown corretto;
  suite dei task sigillati coinvolti, nuova riqualifica content-addressed con
  supersession esplicita, drift validator verde e gate normali RCCAD.
- Verifica indipendente Claude Code (Anthropic), implementatore Codex (OpenAI),
  prima di sigillo, check CI sull'HEAD esatto e merge senza bypass.

## Dipendenze e rollback

Dipendenza obbligatoria dei task G6 (0060–0066) per STACK-HYGIENE;
non blocca 0049 né G5. Rollback mediante nuovo revert commit e riqualifica,
nessuna cancellazione di record sigillati e nessun prune Docker globale.

E1=0, E2=0, zero requisiti Verified, runtime NOT_ESTABLISHED,
PoC/Production NO-GO. Inputs immutabili.


## Osservazione aggiuntiva della classe — 2026-10-07

Le full del ciclo 7 e di REM-0017 mostrano anche volumi anonimi da
`ocor-runtime/src/ocor_runtime/c5/backbone.py` (container `ocor-c5-backbone-*`).
Il mandato STACK-HYGIENE richiede la correzione in unità distinta: estendere
l'audit/teardown del REM anche a questo harness, con riqualifica dei suoi input
sigillati. Nella ripresa REM-0017 18 volumi per full sono stati osservati,
attribuiti tramite Docker mounts e rimossi; zero residui finali. Questo record
registra il difetto, non dichiara riparato o qualificato REM-0018.

## Ripresa 2026-10-25 — candidato REM-0018

Stato corrente: `IMPLEMENTED_AWAITING_QUALIFICATION_AND_INDEPENDENT_REVIEW`.
Il testo di apertura sopra e' storico: non costituisce un esito di qualifica.
Implementatore di questa unita: Codex (OpenAI); verifier esterno richiesto
secondo LOOP-AGENT-ROTATION, con fornitore diverso dagli implementatori.

L'inventario in `audit.json` riconcilia i difetti con `main`:

- Kafka spike e C5 sono gia corretti da REM-0022: label di ownership, rimozione
  per ID immutabile con `--volumes`, volume nominato esatto e controllo dei residui.
  Sorgenti e test restano byte-identici; i test live di REM-0022, 0019 e 0040
  vengono rieseguiti, senza dedurre la qualifica dalla sola lettura del codice.
- L'immagine Qdrant pinnata non dichiara `VOLUME`; lo storage del test e' tmpfs.
  Il leak anonimo di serie non e' riprodotto su questa immagine. Restano difetti
  di lifecycle: avvio fuori dal try, controllo del solo prefisso e nessuna
  verifica del teardown. Il RED ne dimostra gli effetti su Docker reale.
- La correzione riguarda solo il lifecycle Qdrant: ownership e immagine verificate,
  identita immutabile, avvio nel try/finally anche per interruzione Python,
  rimozione con `--volumes`, memoria dei mount e verifica fail-closed dei residui.
  Nessun prune; un volume nominato resta intatto e viene segnalato come residuo.
  Gli errori di Docker restano errori, compresi quelli di cleanup.

I test aggiungono un mount anonimo scratch al container reale per esercitare la
classe senza cambiare immagine o backend. Volume nominato, container e rete
sentinella restano invariati, insieme all'intero insieme degli ID preesistenti.
Il caso stock prova separatamente assenza di mount anonimi e storage tmpfs.
Fault locali: timeout dopo creazione, KeyboardInterrupt, readiness timeout,
fallimento della rimozione, CLI che restituisce successo senza rimuovere,
container assente con volume residuo, risorsa estranea. Nessuna risposta di
successo del backend e' simulata come evidenza qualificante.

`red.log` conserva il RED iniziale (8 FAIL, 1 PASS, commit `0e22e52`).
Il fingerprint addizionale dell'interruzione Python e' in `audit.json`;
le esecuzioni diagnostiche restano distinte dai run qualificanti.
I tredici nuovi casi sono inclusi nella suite runtime e quindi nella CI completa.
La riqualifica di 0023 copre l'input cambiato; le riqualifiche degli input
allowlist sono di sola regressione, senza riaprire conformita o sigilli storici.
I 22 consumer sono inventariati prima della modifica in `audit.json`.

Rollback: nuovo revert commit, seguito da riqualifica. Contratti, risultati
funzionali, test preesistenti, harness, timer, workflow e fence restano invariati.
Nessuna chiusura della remediation prima del GO esterno e dell'integrazione.
