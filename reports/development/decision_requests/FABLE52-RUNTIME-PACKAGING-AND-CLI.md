# FABLE52-RUNTIME-PACKAGING-AND-CLI

Status: `OPEN_PO_DECISION_REQUIRED`. Livello: normativo per la registrazione delle voci (registro di conformità),
operativo per l'unità. Origine: audit `reports/review/OCOR_FABLE52_AUDIT_2026-11-11.md`, finding F-05, F-06, F-07, su
`main` `113f935cf6e04df460406a0b5dfea6949df6723a`. Redatto da Claude Fable 5.2 (Anthropic) in sola lettura.

## Contesto

- **Dipendenze di runtime non dichiarate.** `ocor-runtime/src` importa `psycopg` (25 import), `temporalio` (9) e
  `rdflib` (4); `ocor-runtime/pyproject.toml` li dichiara solo nell'extra `test` (righe 18-27), mentre le dipendenze
  di runtime sono quattro (righe 10-15). Import diretti di `google.protobuf` e `referencing` senza dichiarazione.
- **File normativi letti fuori dal pacchetto.** `c6/fsm.py:56` legge la tabella delle transizioni da
  `docs/OCOR_LLD_v1.1.md`; `c2/transport.py:39-41` legge il contratto OpenAPI da `ocor-runtime/docs/…`. Un pacchetto
  installato non contiene quei file.
- **Nessuna riga di comando.** `FR-050` (Register v1.1 riga 146) e `FR-164` (riga 409), entrambi P0 PoC, chiedono
  comandi eseguibili in locale e in CI con lo stesso digest. Il pacchetto non ha entry point né moduli eseguibili.
  `NCR-PLAN-003` registra solo l'allocazione di `FR-164` a un task non pertinente.
- **Identità di workload via `docker exec`.** `security/control_plane.py:2054-2062`.
- Nessuna di queste voci è nel registro `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`.

## Opzioni

1. **Tre voci nuove nel registro e una unità dedicata prima di `OCOR-DEV-0065` (raccomandata).** Voci `OPEN`:
   `NCR-C1-011` (`MISSING`, `HIGH`: riga di comando OaC, `FR-050`, `FR-164`), `NCR-PACKAGING-001` (`DIVERGENT`,
   `HIGH`: dipendenze di runtime e risorse normative nel pacchetto, `BR-004`, `NFR-073`), `NCR-SECURITY-001`
   (`DIVERGENT`, `MEDIUM`: adapter della Workload API dietro il port esistente). Unità: dipendenze spostate in
   `[project].dependencies` con versione esatta; tabella delle transizioni e contratti distribuiti come risorse del
   pacchetto generate dai file approvati e verificate per sha256 al caricamento; comando `ocor` con `validate`,
   `compile`, `diff`, `package`, `verify` sui port `ValidatePackage`, `Compile`, `SemanticDiff`, `PackageRelease`,
   `VerifyRelease` (ADD v1.3 §2.2.1); adapter SPIFFE Workload API. Stima: 6 iterazioni.
2. **Sole voci nel registro, unità dopo G7.** Le voci entrano come `DEFERRED_BY_PO`; i casi di `FR-050` e `FR-164` in
   `OCOR-DEV-0065` restano senza oggetto.
3. **Nessuna registrazione.**

## Impatto a cascata

Opzione 1: `ocor-runtime/pyproject.toml` e `uv.lock` (input sigillati: riqualifiche di sola regressione),
`ocor-runtime/src/ocor_runtime/c1/` (comando), `c6/fsm.py`, `c2/transport.py`, `security/control_plane.py`, test con
RED per ogni voce, `plan_units` e `plan_order` del registro, `OCOR_TRACEABILITY_PLAN.csv` (`FR-164` riallocato a un
task C1). Il controllo S07 del validatore di allineamento passa senza voci registrate.

## Criteri di accettazione verificabili

- In un ambiente con `pip install ocor-runtime` senza extra, `python -c "import ocor_runtime.c3.adapters.postgres,
  ocor_runtime.c6.temporal_adapter, ocor_runtime.c4.jena_adapter"` termina con codice 0.
- Lo stesso ambiente, senza il repository, carica le 44 transizioni e il contratto del gateway con gli sha256 dei file
  approvati; una risorsa alterata è rifiutata (caso negativo).
- `ocor compile` in locale e in CI sullo stesso sorgente e lock stampa lo stesso `ir_digest`; un errore riporta file,
  riga e causa (`FR-164`).
- Nessun `docker` in `security/control_plane.py`; il caso di identità usa il socket della Workload API.

Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
