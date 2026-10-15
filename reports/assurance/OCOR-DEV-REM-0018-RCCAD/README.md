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
