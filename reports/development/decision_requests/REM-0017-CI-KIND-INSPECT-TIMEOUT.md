# REM-0017-CI-KIND-INSPECT-TIMEOUT

Stato: `RESOLVED` dalla decisione PO `REM-0017-CI-KIND-INSPECT-TIMEOUT` del 2026-10-14. Apertura storica: 2026-10-14T06:45:19.063941+00:00.

## Contesto e fatti

Decisione `REM-0017-CI-0049-RELAY-HEALTH` del 2026-10-14, opzione 1 implementata da Codex. Candidato immutato `7cd5f7a30e04d1671fe122eff58dfb5f54fb58b0`, PR #169 DRAFT; run `38520281413`.

- Parti 2/3/4 PASS: rispettivamente 731/621/871 casi, zero skip, zero failure/error.
- Parte 1 (Helm), job `115708165570`: il singolo caso è PASS nel JUnit (707,233 s); il processo pytest è interrotto durante il teardown e il supervisore registra FAIL: `docker inspect 049d262cb848f0185e6e421061707967154ac1d9836e93fd3df79c7ec9726092` timeout dopo 10 s. Non esiste un’unione qualificante; nessun conteggio si trasferisce a un altro tentativo.
- Nodo precedentemente osservato: containerd/kubelet attivi, PID 112/737, zero restart; diagnostica successiva Kubernetes vuota. `kind-teardown-observations.json`: removals=[], rejections=[], finestra 30 s. Non prova intenzione, processo kind, UUID e destroy correlati richiesti dalla disposizione del 2026-10-12.
- La firma del timeout compare già nel precedente HEAD `313ae7933545d5b09e5fa6375aa4180431b5e7d2`, registrato in stato come causa NOT_ESTABLISHED. Non la considero una nuova causa dimostrata né un motivo per tentare fino al verde.
- L’osservatore nuovo funziona: manifest e digest verificati sulle quattro parti, nessun errore dell’osservatore. Cinque eventi unhealthy di container `ocor-ops` per HTTP503 durante la readiness non ancora validata; **zero eventi unhealthy dei relay**. Nessuna asserzione fallita per quegli eventi. Il rischio/interpretazione del health contract resta aperto verso l’opzione 2 della decisione relay-health; non chiude né spiega il timeout kind.
- Nel campionamento finale della parte 1 il load è circa 3,2–3,5 su 4 CPU e MemAvailable circa 11–12 GiB su 16 GiB. Questi dati non dimostrano che il timeout sia causato da contesa. La rimozione potrebbe correre con inspect, ma senza la prova prescritta resta ipotesi.

Riferimento preciso: `scripts/run_qualifying_campaign.py:586` (`inspect_kubernetes_runtimes_raw`, timeout=10 nella chiamata inspect) e adapter di osservazione v2. I timer e i gate restano invariati e falliscono chiusi. Nessuna modifica al deploy/test di 0049 o ai sigilli.

Evidenza riproducibile: `reports/assurance/OCOR-DEV-REM-0017-RCCAD/ci-7cd5f7a-diagnosis.json` SHA256 `9f2b8a369f7f0e7780a454ba3a78a95c53521a0919b7173d03cf1b8f35cd638b`, raw `.log` SHA256 `786046b58e3815d8ae8e6532b87f0faff7461eff8f23f6749c80501219d513de`. Artifact CI originari: gli ID e i digest zip/raw sono nel JSON; gli artifact contengono i campioni originali e i log.

## Opzioni e raccomandazione

1. **Raccolta di prova supplementare sul teardown/daemon (raccomandata).** Autorizzare sul change set REM-0017 un’estensione esclusivamente diagnostica per registrare l’intento/processo kind, UUID/destroy e stato del daemon durante il timeout, con buffer bounded e prove positive/negative. Pytest, selezione, timer e gate immutati. Serve un nuovo budget CI esplicito prima di ripubblicare una nuova sorgente. La raccolta deve stabilire la causa prima di una correzione governata; non autorizza a sopprimere timeout o ad accettare nodo mancante senza prova.
2. Riproduzione/diagnosi dedicata del blocco di Docker inspect con stesso pin e budget, prima di concedere nuovi run CI. Una modifica del comportamento di osservazione o dei test 0049 richiede un ambito espressamente autorizzato e, se tocca input sigillati, nuova riqualifica con supersession.

Esclusi: aumento dei timer, catch del timeout che produce PASS, skip/deselezioni, cambio immagine/versione senza autorità, rerun senza causa provata.

## Impatto e stato

Bloccati su questa richiesta: chiusura REM-0017, merge 0049, integrazione REM-0019, REM-0023 e ripresa 0056 sul percorso deciso. Non bloccati: REM-0024 → REM-0028, REM-0029 e ultimo ciclo REM-0027, con coordinamento su c6/safety.py. Nessuna nuova verifica indipendente o rerun avviati. Verifier previsto REM-0017: Grok4.7 via Cursor (riserva Claude Code storica); implementatore di questa unità Codex.

Questa PR è DRAFT diagnostica: nessuna estensione dell’allowlist o riscrittura di 0050 in questo branch; il gate del piano può quindi rifiutare i nuovi path. La richiesta viene riportata integralmente nello stato governato su main. Nessun nuovo DEC, inputs intatti, E1=0/E2=0/Verified=0 e NO-GO invariati.


## Disposizione del Product Owner — 2026-10-14

Il PO autorizza una correzione governata dell’osservazione v2, in luogo dell’opzione 1: TimeoutExpired del singolo inspect/exec su UUID posseduto entra nella stessa prova di rimozione (assenza entro 30 s, destroy dello stesso UUID e kind delete nel gruppo pytest). Nessun timeout/cadenza/finestra/tetto/gate cambia; timeout nella disposizione del 2026-10-12 indica la finestra scaduta. Nodo presente, evento o remover mancanti, OOM/restart/PID cambiato e daemon indisponibile a finestra scaduta restano FAIL. Esportati remover, latenza di ogni probe e orari dei rifiuti.

Prove RED/GREEN e confronto AST, full locale e regressione 0050 sono registrati nel nuovo candidato REM-0017. Una sola coppia CI (tentativo più eventuale rerun) condivisa con relay-health. Verde con OWNED_KIND_TEARDOWN_OBSERVED nella parte Helm qualificante; verde senza rimozione registrata non qualificante; rifiuto v2 in Helm vieta rerun e richiede riproduzione/decision request. Altra firma: solo causa infrastrutturale provata permette l’unico rerun della parte fallita; ricorrenza successiva richiede nuova decisione. Verifica indipendente Cursor/Grok solo dopo CI qualificante sull’HEAD esatto.

La diagnosi e i raw citati sopra restano storici nel commit f77aad920a9ebaa27cdf8cbb288291aecac6aa8d, PR #260; nessuna rietichettatura né conteggi trasferiti. La chiusura della richiesta non chiude REM-0017, né promuove claim o evidenze. Implementatore Codex; contributi storici Claude Code conservati; verifier Cursor/Grok.
