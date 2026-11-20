# REM-0063-CYCLE13-STATIC-LIBRARY-DIVERGENCE

Status: `DECIDED_BY_PO`.
Livello: operativo. Unità: `OCOR-DEV-REM-0063`.
Decisione che apre questa richiesta: `REM-0063-CYCLE12C-NO-GO (2026-11-20)`, opzione 1, preambolo sha256 `4100cbd8afb0a93b72c755bc0235aa03da040e6e07c79aeb0120266b5d6ea02b`.
File della richiesta decisa: `reports/development/decision_requests/REM-0063-CYCLE12C-NO-GO.md` al commit `08bfe9034db5cd6c0f625dc50c603d7550c22ff6`, sha256 `921a7565a953e49386093e3434af31d60de4851f5875a00ec6a7850b9535998d`.
Verdetto ancora aperto: `OCOR-DEV-REM-0063-2e4a3e51220a-12`, esito `NO_GO`, sha256 `e70d58bed97c278a882ab70bd3325a987d20a0775936679aa95b316960f501f3`.
Head del candidato, non modificato: `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`.
Commit di comportamento del codice: `da754e862a2c2fba621cf5d4534fcc5396299b6a`.
Branch di produzione: `governed/ocor-dev-rem-0063-mcp-profile`, fermo a `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.

## Contesto e perimetro

`REM-0063-CYCLE12C-NO-GO (2026-11-20)` adotta l'opzione 1. Quell'opzione autorizza un solo ciclo, con `repair_cycle` 13, a partire da `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19`, senza rebase, reset o force-push. Il codice, prima dei record, può toccare solo `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py` e `ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`. La regola scritta è: un errore statico di `$ref` rifiuta il descriptor per ogni nodo della discesa statica esistente, salvo i nodi raggiungibili dalla radice soltanto attraverso `$defs` o `definitions`. Un nodo raggiunto anche da `properties`, `patternProperties`, `items`, `prefixItems`, `allOf`, `anyOf`, `oneOf`, `not`, `if`, `then`, `else`, `dependentSchemas` o `contains` non è esente, qualunque percorso di ancora lo raggiunga.

La stessa opzione fissa l'oracolo della dimensione nuova: `referencing` 0.37.0 e `Draft202012Validator` sullo schema da solo, base B1, istanza positiva che raggiunge il nodo. Dove le librerie rifiutano, il profilo rifiuta. Dove accettano, il profilo accetta. Nessuna cella esistente si toglie. Un test esistente si aggiorna solo se asseriva l'esenzione ora rimossa. Se un test esistente fallisce per un'altra causa, ci si ferma e si apre una sola richiesta. La regola di riallineamento del solo ciclo 10 non si riusa. Nessun test, gate, soglia o claim si indebolisce.

Questa è quella sola richiesta. L'attuazione si è fermata prima di qualunque commit sul candidato. Il worktree è stato riportato a `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19`. Non c'è un `repair_cycle` 14. Non si scrive `prereview_request.json` né `verify_request.json`.

Implementatore di questa misura: Grok Build `grok-4.7` (xAI). Implementatori già dichiarati dell'unità, da riportare in ogni richiesta successiva: Grok Build `grok-4.7` (xAI) per il ciclo originale, le riparazioni 1–6, il completamento del ciclo 8, il ciclo 9, il codice e il candidato del ciclo 10, i cicli 11 e 12 e questa richiesta; Codex CLI `deepseek-flash` e `deepseek-v4-pro` (DeepSeek) per i cicli 7 e 8; Codex `gpt-6.1-sol` (OpenAI) per la fase A del ciclo 10. Verifier del verdetto `2e4a3e51220a`: Claude Code, `claude-opus-5-5`, Anthropic, effort `max`. Nessun implementatore Anthropic.

## Prove

Prova non versionata, eseguita e poi annullata nel worktree `.ocor/worktrees/rem-0063` sull'HEAD `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19`. Nessun commit, nessun push del candidato. `git status --porcelain` dopo il ripristino è vuoto.

La regola strutturale, limitata a `_resolve_graph`, più 2506 test nuovi della dimensione descritta dal `required_fix`, dà questo esito con `ocor-runtime/.venv/bin/python -m pytest -p no:cacheprovider -q -rfE --tb=line ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py -k test_cycle13`: 2506 passed, 42187 deselected, 6,56 s. Su quelle celle il profilo coincide con `Draft202012Validator`.

Lo stesso albero, senza i test nuovi (`-k "not test_cycle13"`), dà 192 failed, 41995 passed, 2506 deselected, 821,58 s. I fallimenti sono solo tre funzioni:

| Funzione | Fallimenti | Fatto |
| --- | --- | --- |
| `test_cycle8_depth_and_order_differential_matches_the_library` | 160 | Il test richiede che il profilo segua la libreria. `Draft202012Validator.iter_errors` non solleva; il profilo rifiuta con `MCP $ref does not resolve in the descriptor`. |
| `test_cycle8_anchor_ref_follows_the_referencing_crawl` | 16 | Per `placement` diverso da `root`, `validator.is_valid({"n": 11})` è vero e il test si aspetta che il profilo accetti. Il profilo rifiuta. |
| `test_cycle10_preserves_existing_anchor_lookup_context` | 16 | Il test dice che l'oracolo statico largo non sostituisce queste aspettative. La libreria accetta `{"n": 11}`; il profilo rifiuta. |

Le tre funzioni non asseriscono l'esenzione rimossa come permesso di accettare un nodo che le librerie rifiutano. Asseriscono l'accordo con le librerie su celle che le librerie accettano. Aggiornarle a un rifiuto del profilo indebolirebbe quell'accordo e riuserebbe, di fatto, una riscrittura di aspettative del ciclo 10. L'opzione 1 vieta entrambe le cose e ordina lo stop.

Il nodo tipico di `test_cycle8_anchor_ref_follows_the_referencing_crawl` sta sotto `$defs` e poi sotto `properties`: il corpo ha `$ref: #hold` e `$defs.holder.properties.n` ha `$ref` verso `private`. Il percorso statico non è fatto solo di `$defs` o `definitions`, quindi la regola strutturale non lo esenta. La libreria, sul registro crawlato dall'ancora, accetta l'istanza.

La campagna `698b944a1de4-1795114196` e il controllo distinto `698b944a1de4-1795117669` restano storici. La campagna `a3bd36d3ab51-1795089861` resta PASS storica. Le campagne diagnostiche `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` non si rilanciano.

## Quesito

Come si completa l'opzione 1 di `REM-0063-CYCLE12C-NO-GO (2026-11-20)` quando la regola strutturale rende il profilo più severo di `Draft202012Validator` su 192 celle esistenti che le librerie accettano?

## Opzioni

1. **Oracolo delle librerie, test esistenti invariati.** Raccomandata. Non si pubblica un rifiuto del profilo sulle celle che `Draft202012Validator` accetta. Un errore statico di `$ref` su un nodo applicativo rifiuta il descriptor solo quando `referencing` 0.37.0 e `Draft202012Validator`, sullo schema da solo, con la base B1 e l'istanza positiva che raggiunge il nodo, rifiutano. Dove accettano, il profilo accetta. I tre test della tabella restano come sono. I nodi raggiungibili dalla radice soltanto attraverso `$defs` o `definitions` restano esenti. Nessuna cella esistente si toglie. Il resto dell'opzione 1 già adottata (allowlist dei ventidue percorsi, settle, undici record, allineamento di VF-003, una sola `prereview_request.json`) parte solo dopo che questa regola è verde sull'intera suite del file di test, compresa la dimensione nuova. Se un altro test fallisce per una causa non descritta qui, ci si ferma e si apre una sola richiesta nuova. Non c'è un ciclo 14 automatico se il verdetto resta `NO_GO`.

2. **Rifiuto strutturale e riscrittura dei tre test.** Si applica la regola strutturale anche dove le librerie accettano. I 192 casi passano all'aspettativa «il profilo rifiuta». Nel record dell'unità si scrive la tabella: funzione, identificativo, aspettativa precedente, aspettativa nuova, esito delle librerie. Il profilo diventa più severo delle librerie su quelle celle. Questo contraddice la frase dell'opzione 1 «dove accettano, il profilo accetta» e indebolisce `test_cycle8_depth_and_order_differential_matches_the_library`. Non raccomandata.

3. **Nessun file cambia.** L'HEAD resta `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19`. VF-001, VF-002 e VF-003 restano aperti. L'opzione 1 adottata non si completa. Non c'è un altro ciclo. Costo: zero. Non raccomandata.

## Raccomandazione

Opzione 1. Chiude la divergenza permissiva di VF-001 sulle celle che le librerie rifiutano, senza rendere il profilo più severo sulle 192 celle che le librerie accettano, e senza riscrivere i tre test. L'opzione 2 compra la regola strutturale al prezzo di un profilo più severo delle librerie. L'opzione 3 lascia il `NO_GO` senza chiusura. Nessuna opzione di questa richiesta è applicata da chi la apre.

## Impatto

Task bloccato da questa richiesta: `OCOR-DEV-REM-0063`. Gli altri task non sono bloccati da questa richiesta. `OCOR-DEV-REM-0066` resta bloccato da `REM-0066-CANONICAL-R1-HUMAN-GATE`. `OCOR-DEV-REM-0065` resta all'HEAD `583ea0024f18ebe0f63f4c5eaa8da8bc9a246f6c`. La PR #640, branch `nepryoon-patch-1`, non si tocca.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
## Disposition del Product Owner — 2026-11-20

`REM-0063-CYCLE13-STATIC-LIBRARY-DIVERGENCE (2026-11-20)` adotta l'opzione 1. Decisa per conto del PO, modello `claude-fable-5-2`, effort `max`. Rilettura di `~/.ocor-codex/openhands_preamble.md` immediatamente prima di questo commit: sha256 `c9b4cfca3ad4b60b3a4ed42e7b58830e6c33ae9321b70c68857e469585203ecd`. L'ultima sezione è `## REM-0063-CYCLE13-STATIC-LIBRARY-DIVERGENCE (2026-11-20) — decisione del PO, su delega completa`.

L'opzione 1 è applicata sul candidato `governed/ocor-dev-rem-0063-cycle10-campaign`, head `e5e09b329818bd18aab5aa59f558e1c45969dcaa`. Commit di comportamento del codice `a857b332f5c4816243fa3e9bf09ad46195077ca7`. Allowlist dei ventidue percorsi `2becd7bab0a0dab9b2aa7b7a3260f51c7cadef47`. Settle del solo hash del validatore `816c043f83ca9bc06ffe4c5bf3235ce1a4d27795`. Undici record `acd5e08477b88075f97ad6fd53417a4d5d2d5635`. Allineamento di VF-003 `e5e09b329818bd18aab5aa59f558e1c45969dcaa`. Le opzioni 2 e 3 non sono applicate. La suite del file di test è verde: 44694 passed, zero skip. I tre test esistenti restano invariati. I nodi raggiungibili dalla radice soltanto attraverso `$defs` o `definitions` restano esenti. Non c'è un ciclo 14 automatico.

Il testo sopra ## Disposition, esclusa la riga di stato, resta il commit `7ca292c4adb953bd2772d7852c390f7a66b27e2c`, sha256 `6d954208386ca4253e794ab4b68fae93f3a35530004b4fe0f520970700f0970b`.

L'intestazione del file usa la riga `Status:` con `DECIDED_BY_PO`, perché DR-STATUS-CLOSURE-SYNC (2026-11-09) confronta quella riga con lo stato del registro.
