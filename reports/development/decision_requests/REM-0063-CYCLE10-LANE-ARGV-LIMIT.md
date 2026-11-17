# REM-0063-CYCLE10-LANE-ARGV-LIMIT

Stato: `OPEN_PO_DECISION_REQUIRED`.
Livello: operativo. Unità: `OCOR-DEV-REM-0063`, ciclo 10.
Branch di produzione: `governed/ocor-dev-rem-0063-mcp-profile`.
Head del gate e della campagna: `5a1a8aaff6af95470171c1add7f9e85f1ec997a8`.

Questa richiesta non è decidibile in automatico. La decide il PO di persona,
come le richieste di stop di un'unità (`DECISIONI-AL-PO (2026-11-16)`, punto 4).
Finché il preambolo non contiene la sezione con questo identificativo, non si
applica nessuna opzione.

## Contesto e perimetro

`REM-0063-CALCOLO-UNICO (2026-11-17)` punto 6 ferma la riparazione quando deve
uscire dai file ammessi per l'unità e chiede una sola richiesta. Il punto 7
lascia invariati gate, campagna, controllo distinto, soglie e limiti. I file
di produzione ammessi restano `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py`
e gli helper `_mcp` di `codegen.py`. I test ammessi restano il modulo del
task. Questa iterazione non modifica quei file, non modifica
`scripts/run_local_lane_campaign.py`, non modifica
`scripts/run_qualifying_campaign.py` e non rilancia la campagna.

Il gate ufficiale `python3 /home/luca/.ocor-codex/rem-0063/pregate.py` sullo
head `5a1a8aaff6af95470171c1add7f9e85f1ec997a8` è PASS. Avvio
`2026-11-17T09:15:03Z`, fine `2026-11-17T09:30:01Z`, exit 0. 51 passi PASS, 0
fallimenti, 6 `NOT_EXECUTED` (i passi che il gate non esegue in locale).
Durata sommata 897.239 s. Mermaid PASS in 4.412 s. Il passo `rem0063-unit`
PASS in 800.021 s. `gates.json` sha256
`860c48da950bf65a27573b71875dd55b8db8780c9b510804d13c0047ef7fa54e`, conservato
in `/home/luca/.ocor-codex/rem-0063/gate/preserved-5a1a8aaf-pass/gates.json`.
Log sha256 `387481316f16219147bb1e479ed82130450c25721010ae809300be220038bec8`.
Il diagramma e `.github/mermaid-puppeteer.json` non sono stati modificati. I
due fallimenti mermaid sullo head `6c1d5c805fab9fff784db5ddfcd419c92790a597`
restano FAIL e non diventano PASS.

La campagna a quattro corsie è poi partita sullo stesso head ed è FAIL. Non è
un fallimento di asserzione, non è OOM, non è un pull HTTP 429 e non è un
head sporco.

## Prove

Host: `ARG_MAX` misurato con `getconf ARG_MAX` uguale a 2097152. Quel tetto
include l'ambiente del processo. `MemAvailable` all'ammissione 59197840 KiB,
soglia FOUR_LANE 25681.2 MiB, ammissione `FOUR_LANE`. Prima della campagna il
budget di pull Docker Hub era `100;w=3600`. Reset dello stack di progetto
PASS. Contenitori sull'host dopo il teardown: zero.

Campagna `5a1a8aaff6af-1794907944`. Avvio `2026-11-17T09:32:24Z`, fine
`2026-11-17T09:36:12Z`, durata 227.898 s, exit 1, stato `FAIL`. Selezione
`tests/`, ambito `FULL_SUITE`, `qualifying_scope` true. Raccolti 47779, sha256
della raccolta
`be9e0ca21a0e0e9ce0c0944180de94d32c9cad41c56d111c0a76318917bbe2fb`. Casi per
corsia: 41953, 972, 2423, 2431. Sha256 della partizione
`ad0d34b86ba5bbd5225010ad59f5106ce1af83bbfeeddf86c6a3a8c053ddcff0`. Alimentazione
di rete all'inizio e alla fine. Residuo host vuoto (contenitori, reti, volumi,
immagine root assente). Teardown delle quattro sandbox PASS. Log
`/home/luca/.ocor-codex/rem-0063/cycle10/lanes-5a1a8aaf.log`, sha256
`bdd232f8e6226e9afb9c081dbcb07dad1ad680eff37f1f67c18aeb1b22aacdec`.

Errore della corsia 1, prima che pytest esegua un caso:
`[Errno 7] Argument list too long` sul binario Python della corsia. Le corsie
2, 3 e 4 sono state fermate dall'orchestratore perché la corsia 1 è uscita
con codice 1. Il flag `po_decision_required` dell'harness è false: l'harness
non chiede lui la decisione. La chiede il punto 6 di
`REM-0063-CALCOLO-UNICO (2026-11-17)`, perché la correzione esce dai file
dell'unità.

Causa. `partition_units` in `scripts/run_qualifying_campaign.py` tiene intero
ogni modulo che non è un caso indipendente di 0049.
`tests/tasks/test_ocor_dev_rem_0063.py` è quindi una sola unità e finisce
tutta nella corsia 1 (41953 identificativi). `lane_pytest_command` in
`scripts/run_local_lane_campaign.py` mette quegli identificativi sull'argv di
pytest. `run_lane` avvia quel comando con `subprocess.Popen`. Lo spec di
corsia contiene già la selezione (`LANE_SPEC_KEYS` include `selection`) ed è
cancellato al teardown: la lunghezza esatta in byte dell'argv non è stata
rimisurata. L'errore `Errno 7` è la prova. Una riesecuzione identica fallisce
allo stesso modo. Il controllo distinto non è stato avviato.

Il test `test_lane_pytest_command_is_the_sealed_supervisor_command_with_the_explicit_selection`
in `reports/tests/test_local_lane_campaign.py` asserisce che gli
identificativi della selezione stanno sull'argv. Una selezione piccola continua
a entrarci. La selezione della corsia 1 no.

## Effetto

La campagna di qualifica del ciclo 10 e il controllo distinto dipendono da
questa richiesta. Il codice del profilo e del generatore già pubblicato non
ne dipende e non si modifica. Nessuna seconda revisione preventiva. Nessuna
richiesta di verifica. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime
`NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Opzioni

1. **Selezione letta dallo spec di corsia.** Un change set governato distinto, non sul branch di produzione di REM-0063, modifica solo `scripts/run_local_lane_campaign.py` e `reports/tests/test_local_lane_campaign.py`. `run_lane` continua a leggere la selezione dallo spec di corsia già scritto e a controllare che la raccolta coincida con quella lista, nello stesso ordine. Pytest riceve gli stessi identificativi, gli stessi flag di coverage e lo stesso JUnit. Il vettore di argomenti del processo resta sotto `ARG_MAX`: la selezione non viene aggiunta all'argv quando la sua lunghezza, insieme all'ambiente, non ci sta. Per una selezione che ci sta già, il comando resta quello che il test sigillato asserisce oggi, identificativi compresi. Un test nuovo, rosso prima della modifica, dimostra che una selezione più lunga di `ARG_MAX` viene eseguita con gli stessi identificativi e che una selezione corta non cambia comando. Non si modifica `scripts/run_qualifying_campaign.py`, non si modifica `partition_units`, non si cambiano soglie, tetti, timer, workflow, diagramma, config Puppeteer, matrice o codice di prodotto. I record sigillati i cui input includono il file cambiato si riqualificano con la regola già in vigore, senza esenzioni. La campagna `5a1a8aaff6af-1794907944` resta FAIL diagnostica. Dopo il change set si ripetono il gate e la campagna a quattro corsie sull'head nuovo; il controllo distinto segue solo una campagna verde. Raccomandata.

2. **Moduli di test più piccoli.** Si divide `tests/tasks/test_ocor_dev_rem_0063.py` in più moduli, ciascuno abbastanza piccolo perché l'argv dell'unità stia in `ARG_MAX`, senza togliere o indebolire alcuna cella o asserzione. L'insieme degli identificativi raccolti cambia perché cambia il percorso del modulo. Un modulo futuro altrettanto grande supera di nuovo `ARG_MAX`. I test del ciclo 10 cambiano dopo le revisioni del contratto. Non raccomandata.

3. **Meno item di pytest.** Si accorpano le celle della matrice in meno item, che eseguono ancora ogni cella. Il conteggio raccolto scende rispetto ai 41896 e ai 41953 item già registrati come passati e l'isolamento dei fallimenti cambia. È la forma che le decisioni del ciclo rifiutano senza una scelta del PO. Non raccomandata.

## Raccomandazione

L'opzione 1. Conserva identificativi, ordine, unione JUnit, partizione e
comandi delle selezioni che oggi stanno in `ARG_MAX`. Corregge solo il modo
in cui la corsia consegna una selezione che non ci sta. Le opzioni 2 e 3
spostano il problema sui test del ciclo 10.

## Impatto

Task bloccato: `OCOR-DEV-REM-0063`. Gli altri task non sono bloccati: le loro
unità di partizione continuano a stare nell'argv. Nessun nuovo `DEC-*`.
Nessuna modifica a `inputs/`, ai record sigillati, ai gate o ai claim.
L'estensione dell'allowlist del validatore del piano per il percorso di
questa richiesta è un change set a parte e non fa parte di questa pubblicazione.

## Disposition

Decisa dal PO di persona il 2026-11-17. Opzione 1. Le opzioni 2 e 3 non sono applicate.
Il change set governato, distinto dal branch di produzione `governed/ocor-dev-rem-0063-mcp-profile`, è `governed/rem0063-lane-argv-overflow`, commit `364f853cfe41f2dd5413c78a2b2b0ce665b77b34`, PR #664, merge `49ec6ed27e093142cf63d0343a6b40a509b6a5bf` su `main`. I soli file modificati sono `scripts/run_local_lane_campaign.py` e `reports/tests/test_local_lane_campaign.py`.
Per una selezione che sta in `ARG_MAX` il comando resta quello che il test sigillato asserisce, identificativi compresi. Per una selezione che non ci sta, la corsia legge la selezione dallo spec già scritto e pytest riceve gli stessi identificativi, gli stessi flag di coverage e lo stesso JUnit. La raccolta che non sta in `ARG_MAX` usa lo stesso spec e lo stesso ordine, dentro lo stesso file di corsia. `scripts/run_qualifying_campaign.py` e `partition_units` non sono modificati.
La campagna `5a1a8aaff6af-1794907944` resta FAIL diagnostica e non è un PASS. Il gate sullo head `5a1a8aaff6af95470171c1add7f9e85f1ec997a8` non è rieseguito. Il controllo distinto non è eseguito.
L'estensione dell'allowlist del validatore del piano non fa parte di questa pubblicazione. Il testo della richiesta sopra questa sezione resta quello del commit `1ffdbaaf23a82753df87c136989c51e23bffe40b`, sha256 `fa95ed2da8c67ae6d967ace3cc59ad527f554be3e950166e1ad31cf5c96ac4e1`.
