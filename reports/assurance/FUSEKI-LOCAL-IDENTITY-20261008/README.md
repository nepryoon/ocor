# Riacquisizione locale Fuseki — candidato2026-10-08

Scope governato separato da REM17, autorizzato dalla decisione PO
FUSEKI-LOCAL-IDENTITY-AFTER-CI-EXERCISE. Solo output_sha256 nel services lock
cambia. La companion lock registra la provenienza senza alterare lo schema
chiuso o il checker. La ricetta COPY proviene dal commit remoto bc811af ed
è archiviata con gli stessi byte come build_recipe.txt: non promuove il REM
e non rappresenta una nuova ricetta di main.

`candidate.json`/`MANIFEST.json` legano risultati, raw log, commit e input.
Il bundle qualification.log contiene sezioni FILE/BYTES/SHA256, redazione
trasparente delle credenziali e i run falliti o con skip, mai qualificanti.
I dati full_main.py.txt e register_control_plane.py.txt documentano gli script
locali eseguiti: riusano i guard invariati del REM e registrano l’entry SPIRE
necessaria. Le loro path locali sono fingerprint dell’ambiente, non istruzioni
incorporate da eseguire automaticamente. Nessuno di questi dati cambia validator.

Riproduzione: toolchain pinned e uv frozen con extras test/lint; reset del solo
progetto OCOR, bootstrap standard con immagine locale esatta, registrazione
SPIRE spiffe://ocor.test/ocor/control-plane con selector unix:uid:0 sul solo
agent attestato, init e fixture, poi health typed con negativi, FULL tests/
senza esclusioni e faultbounded. Il bootstrap standard non crea quell’entry;
lo SVID va verificato prima della suite. Il verifier riacquisisce da sé valori
e risultati. Nuova build: usare ricetta e archivio SHA512 già verificati; un
ID diverso non aggiorna il lock implicitamente. Nessuna identità di rebuild
clean-main o portabilità tra macchine è asserita.

Acceptance: python -m pytest reports/tests/test_fuseki_local_identity.py -q.
Evidenza: python scripts/validate_runtime_evidence.py
--task FUSEKI-LOCAL-IDENTITY-AFTER-CI-EXERCISE --non-skipped
--manifest reports/assurance/FUSEKI-LOCAL-IDENTITY-20261008/MANIFEST.json.
Originali G2 preservati; riqualifiche con supersedes esplicito e log condiviso.
Implementatore Codex/OpenAI, verifier Claude Code/Anthropic pending.
E1=0,E2=0,Verified=0; tutti i NO-GO invariati.
