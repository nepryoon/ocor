# OCOR-DEV-REM-0029 — teardown con assenza provata

Mandato `CC-OCOR-DELIVERY-COMPLETION`, DEC-210/211 e decisione PO
`REM-0019-KIND-CONTAINERD-SEGV-RECURRENCE` del 2026-10-13.
La scheda registrata nello stato richiede un rifiuto anche quando Compose esce
con zero e lascia una rete occupata. Scope e invarianti sono in
`scope-and-invariants.json`; nessuna modifica ai target logici di `--reset`.

`test_reset_teardown_residue.py` esercita positivi, residui di container/rete/volume,
inventari indisponibili o malformati, proprietà ambigua, cambio di identità,
risorse estranee, errore Compose e dry-run. L'iniezione serve ai soli failure
handling locali. `qualify_rem0029_teardown.py --execute --output-dir <directory>`
richiede uno stack ocor-bootstrap esclusivo e inizializzato: mantiene la rete
reale occupata con un holder temporaneo digest-pinned, prova UUID e residuo,
verifica il rifiuto dello script con Compose zero, poi ripulisce nel finally e
prova il teardown vuoto. Una seconda prova usa Docker reale e una rimozione
concorrente simulata nello scheduling: il container etichettato viene rimosso
senza `-v` prima del vero Compose down. Il volume anonimo deve restare tracciato
con label Docker e UUID del container, e il boundary deve rifiutare. Nessun
risultato Docker è fabbricato; il cleanup rimuove solo gli oggetti della prova. Non eseguirlo insieme ad altre campagne.

Il controllo legge l'inventario Docker indipendentemente da Compose, verifica
label e identità prima della mutazione e ricontrolla dopo. Solo Compose cancella
risorse. Non vengono ispezionate né rimosse risorse estranee; un nome riservato
con label mancante o diversa produce FAIL prima di Compose. I timeout sono
180 s per Compose, 30 s per ciascun inventario e al massimo 10 s per probe.
La concorrenza con un altro proprietario dello stesso progetto resta vietata.

Riqualifiche nuove con supersession: 0082 per lo script; 0050 e 0005 di sola regressione
per l'allowlist esatta del piano (0005 aggiunta da Claude Code: deriva dello stesso input
`scripts/validate_ocor_development_plan.py` non coperta dalla prima stesura). Record storici e casi/asserzioni esistenti intatti.
Implementatori: Codex/OpenAI (codice, test, prima qualifica) e Claude Code/Anthropic
(implementatore di riserva dopo l'esaurimento della quota Codex del 2026-10-22: riqualifica
da zero, riqualifica 0005, evidenza e state sync; linea storica e harness).
Verifier richiesto Cursor/Grok 4.7/xAI o Antigravity/Gemini/Google, soltanto dal
loop esterno. Verifica e CI finali restano NOT_EXECUTED fino alle rispettive fasi.
E1=0, E2=0, Verified=0; runtime NOT_ESTABLISHED e PoC/Production NO-GO invariati.
Rollback mediante nuovo revert governato, preservando ogni evidenza storica.
