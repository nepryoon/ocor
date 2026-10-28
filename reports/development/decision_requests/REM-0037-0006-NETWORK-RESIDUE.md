# REM-0037-0006-NETWORK-RESIDUE

Status: `OPEN_PO_DECISION_REQUIRED`. Riguarda il perimetro di `OCOR-DEV-REM-0037`
(suite completa locale in due corsie): un test sigillato di `OCOR-DEV-0006` lascia una
rete Docker residua, che il controllo fail-closed di smontaggio delle corsie rileva.
Nessuna variazione di limiti, timeout, soglie, partizioni, casi o gate. Autorità corrente:
decisione normativa del PO `LOCAL-SUITE-SPLIT-REACTIVATION (2026-10-26)`, punto 4
(«Se serve altro, fermati e apri una decision request»); `CC-OCOR-DELIVERY-COMPLETION`
§7; DEC-210/211.

## Contesto

Il 2026-10-27 il candidato di `OCOR-DEV-REM-0037` (branch
`governed/ocor-dev-rem-0037-local-suite-split`, head di codice
`b4ddd6987daa4e35f76176672a1840d4f05ea045`) ha eseguito le campagne qualificanti dopo la
revisione preventiva `OCOR-DEV-REM-0037-a87c6b483ac9-pre` (`NO_BLOCKING_FINDINGS`) e un
`PRE-CAMPAIGN-GATE` con 41 passi su 42 PASS (drift atteso per 0005, 0050, 0082).

- Suite completa **seriale** sullo stack a 15 container: 3224/3224 PASS, zero skip, unione
  JUnit esatta, 3796,541 s (margine dal tetto di 5400 s: 1603,459 s). Smontaggio con zero
  residui.
- Suite completa **in due corsie** sullo stesso head (`scripts/run_local_lane_campaign.py
  --execute`, ammissione `TWO_LANE`): 3224/3224 PASS, zero skip, unione esatta (corsie da
  1000 e 2224 casi, nessun caso mancante, duplicato o in più), stesso insieme di casi della
  seriale, 2342,822 s complessivi. **Esito della campagna: `FAIL`**, perché lo smontaggio
  della corsia 1 ha trovato, nel demone Docker privato della corsia, una rete residua
  (`residue inside the private daemon: networks ['c2570697d499']`). La corsia 2 è stata
  smontata con esito PASS; il residuo sull'host è zero, perché la sandbox e il suo demone
  sono stati rimossi.

La campagna a due corsie non è qualificante e non è registrata come PASS. Nessuna evidenza
è stata costruita e nulla è stato sigillato.

## Fatti

Causa: `ocor-runtime/tests/tasks/test_ocor_dev_0006.py::test_missing_pinned_image_cannot_fall_back_to_public_pull`
esegue `docker compose -p ocor-missing-image-negative -f <file> up --detach` con
un'immagine inesistente e `pull_policy: never`. Compose crea la rete
`ocor-missing-image-negative_default`, l'avvio fallisce come il test si aspetta, e la rete
resta. Il test non la rimuove.

- Sul demone dell'host la rete esiste dal 2026-10-24 21:34 (id `df15bf84d1be`, etichetta
  `com.docker.compose.project=ocor-missing-image-negative`, nessun container). Le corse
  successive la riusano, quindi la suite seriale non mostra il residuo: il suo controllo è
  limitato al progetto `ocor-bootstrap`. Sui runner effimeri della CI il residuo sparisce
  con il runner.
- Nella corsia il demone parte vuoto e il controllo di `teardown_lane` elenca tutte le reti
  `type=custom`: la rete creata dal test è un residuo, e il controllo fallisce come
  progettato.
- Riproduzione deterministica, non qualificante, sullo stesso head: `--execute --select`
  con due casi. La corsia con il solo caso di 0006 fallisce lo smontaggio per una rete
  residua (`8859d7f1511f`); la corsia con `tests/test_interpreter_pin.py` passa.
- Nella suite completa a due corsie questa è l'unica differenza: nessun container o volume
  residuo, nessun'altra rete. Nessun altro record sigillato, oltre a quello di
  `OCOR-DEV-0006` (`reports/evidence/G0/OCOR-DEV-0006.requalified.json`), ha quel file di
  test fra gli `inputs` del record più recente.
- Il punto 4 di `LOCAL-SUITE-SPLIT-REACTIVATION` ammette nei test soltanto modifiche di
  configurabilità delle risorse condivise. Aggiungere lo smontaggio della rete al test di
  0006, oppure ammettere un residuo nel controllo delle corsie, è fuori da quel perimetro.

Artefatti fuori da Git, in `~/.ocor-codex/rem-0037-q/`:

| Artefatto | sha256 |
|---|---|
| `lanes/campaign_result.json` (campagna a due corsie, `FAIL` per residuo) | `b09fd3c5b23f80e6d787a2671d94417d2394efe38395328926f3d7e844e8e51f` |
| `lanes/runtime_junit_post_approval.xml` (JUnit unito, 3224 casi PASS) | `762f522b73156dab1006fe622e0ca7d162d6e3a5de4189fe0e09bbb2f73115f9` |
| `lanes/lane-1/out/lane_spec.json` (selezione della corsia 1, con il caso di 0006) | `ae5d3b7b40d79e1eae5098680a9f87010c1632894048ac317973b5bcebf058fd` |
| `q/full/campaign_result.json` (suite seriale, `PASS`) | `89b2448d39d9d73b9fcdb65d069de39a49e1d4377b866bfa28b76ad61d24197f` |
| `q/full/runtime_junit_post_approval.xml` (JUnit seriale, 3224 casi PASS) | `84817839b6fddeccb86f4928d60736ad844aa53615a19f9b7bf4ba8d5c39fad3` |
| `repro-0006/campaign_result.json` (riproduzione a due casi) | `03899934c6203394dcca8762cbd63689288769ce86182516bc8780daf5c1541a` |
| `repro-0006/lane-1/out/lane_spec.json` (corsia con il solo caso di 0006) | `74ac2aceb98134432b82cc3704ba32d76092365449e0fd74ee79c7ae4af33113` |

## Opzioni

1. **Estensione del perimetro di `OCOR-DEV-REM-0037` al solo test di 0006.** Nel change set
   di REM-0037 si aggiunge a
   `test_missing_pinned_image_cannot_fall_back_to_public_pull` lo smontaggio del progetto
   Compose che il test stesso crea (`docker compose -p ocor-missing-image-negative -f <file>
   down`, in un blocco `finally`), e nient'altro.
   - Prova AST come per REM-0023: stesso elenco di funzioni di test, nodi `assert` e
     `pytest.raises` identici, decorator di parametrizzazione identici, differenze limitate
     allo smontaggio; un test che fallisca se il diff tocca altro.
   - Riqualifica di `OCOR-DEV-0006` con nuovo record e supersession esplicita, insieme a
     0005, 0050 e 0082 già previste; la soglia delle riqualifiche non si applica (punto 3).
   - La rete residua già presente sul demone dell'host, di proprietà dei test OCOR, viene
     rimossa una volta prima delle nuove campagne e la rimozione è registrata.
   - Poi: nuovo `PRE-CAMPAIGN-GATE`, campagne seriale e a due corsie sul nuovo head, unione
     esatta, verifica esterna ordinaria. Il controllo dei residui delle corsie resta
     invariato.
2. **Remediation separata.** Lo stesso intervento sul test di 0006, con la stessa prova AST
   e la riqualifica di `OCOR-DEV-0006`, in un change set `governed/` proprio con il primo
   `OCOR-DEV-REM-*` libero (oggi risulterebbe `OCOR-DEV-REM-0043`), con suite completa,
   verifica esterna, sigillo e merge prima della ripresa di REM-0037. Separa meglio i
   change set, ma richiede una suite completa e una verifica in più prima di poter
   rieseguire le campagne di REM-0037.
3. **Ammissione del residuo nel controllo delle corsie.** Il controllo di smontaggio delle
   corsie rimuove e registra la sola rete `ocor-missing-image-negative_default` prima del
   controllo dei residui, con un test negativo per ogni altro residuo. Non tocca il test di
   0006, ma introduce un'eccezione enumerata in un controllo fail-closed e lascia il residuo
   del test sugli altri demoni.

## Raccomandazione

Opzione 1. Corregge la causa nel test che crea la rete, senza cambiare asserzioni, casi o
semantica, e lascia invariato il controllo fail-closed dei residui delle corsie. Resta in un
solo change set con una sola verifica esterna, perché il difetto è stato rivelato dalle
corsie di REM-0037 e la sua correzione è necessaria alla loro qualifica.

## Impatto

- Bloccato fino alla decisione: `OCOR-DEV-REM-0037` (campagne qualificanti, evidenza,
  verifica e integrazione). Branch, worktree e artefatti restano preservati.
- Non bloccati: `OCOR-DEV-REM-0039`, `0040`, `0041` (che proseguono nell'ordine vigente
  mentre REM-0037 attende), `OCOR-DEV-0062`, `0063`, `0064`.
- Con l'opzione 1 o 2 la suite seriale resta identica per la CI e per il verifier: lo
  smontaggio aggiunto rimuove soltanto la rete creata dal test.
- Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e
  Production `NO-GO`. Nessun nuovo `DEC-*`.

## Disposition PO (2026-10-28)

Decisione `REM-0037-0006-NETWORK-RESIDUE-DISPOSITION (2026-10-28)`, livello
operativo: scelta l'**opzione 1** di questa richiesta (file sha256
`9a4d5534fb4a975b7738731cb5dc29b5a50a6edcf1c2380c8f180cfb508918f8`, commit
`1f2eeb5`, PR #377). Stato della richiesta: risolta.

- Ambito: `OCOR-DEV-REM-0037` si estende a una sola modifica del test sigillato
  `test_ocor_dev_0006.py::test_missing_pinned_image_cannot_fall_back_to_public_pull`,
  cioè lo smontaggio del progetto Compose `ocor-missing-image-negative` creato
  dal test (rete compresa), in un blocco `finally` o equivalente eseguito anche
  in caso di fallimento. Nessun'altra modifica a quel file né ad altri test
  sigillati.
- Prova: RED con fingerprint su Docker reale (resta la rete
  `ocor-missing-image-negative_default`), poi GREEN (nessuna risorsa del
  progetto residua); confronto AST come in REM-0023, con l'unica differenza
  ammessa nello smontaggio.
- Riqualifica di `OCOR-DEV-0006` autorizzata secondo la procedura in uso.
- Controllo dei residui delle corsie invariato e fail-closed; nessuna deroga,
  allowlist o esclusione; `scripts/run_qualifying_campaign.py` non si tocca.
- Campagne: PRE-CAMPAIGN-GATE e PRE-CAMPAIGN-REVIEW, poi prova d'equivalenza
  sullo stesso nuovo head (suite seriale e a due corsie, stesso insieme di
  casi, unione esatta, zero skip, entrambe PASS, residui puliti). Le campagne a
  `b4ddd69` restano storiche e non qualificano il nuovo head. Tetto 5400 s,
  notifica 3600 s, guard invariato.
- Limite: se serve toccare altro, nuova decision request.
- Ordine: REM-0037 riprende al primo confine coerente del lavoro in corso;
  `REM-0039`, `0040`, `0041` e `0062`–`0064` restano non bloccati.

Registrazione: Claude Code (Anthropic, claude-opus-5-5), implementatore del loop
secondo LOOP-IMPLEMENTER-ORDER-AUTH-FALLBACK, dopo il GO e durante
l'integrazione di `OCOR-DEV-REM-0039` (confine coerente). Il blocker si chiude
nello stato con il riferimento a questa disposition. Nessun test, caso, limite,
timeout, soglia o gate cambiato. Claim invariati: E1=0, E2=0, Verified=0;
runtime NOT_ESTABLISHED, PoC/Production NO-GO.
