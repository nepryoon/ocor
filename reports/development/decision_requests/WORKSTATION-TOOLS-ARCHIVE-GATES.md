# WORKSTATION-TOOLS-ARCHIVE-GATES

Status: `OPEN_PO_DECISION_REQUIRED`. Riguarda l'unità di manutenzione
`WORKSTATION-TOOLS-ARCHIVE (2026-10-28)`. La copia invariata dell'archivio in
`tools/workstation/` è conforme al manifest e lo scanner dei segreti non trova nulla,
ma tre gate obbligatori esistenti la rifiutano e la protezione richiesta dal punto 3 non
si può introdurre nella stessa PR che crea la cartella. Nessuna variazione di test,
limiti, timeout, soglie, gate, contratti o schemi. Autorità corrente:
`WORKSTATION-TOOLS-ARCHIVE (2026-10-28)` punti 1, 3, 4 e 5; `CC-OCOR-DELIVERY-COMPLETION`
§7 e §10 («nessun indebolimento di test, validator, workflow CI»); `DEC-212`.

## Contesto

Il 2026-10-29, su `origin/main` `4b3b8fc8faaa1190cae5aee21eb0ead7d1f80f32`, in un
worktree locale isolato (`.ocor/worktrees/workstation-tools-archive`, branch
`governed/workstation-tools-archive-20261029`, **non pubblicato**), è stata copiata senza
modifiche la cartella `~/ocor-workstation-export/tools/workstation/`. Non è stato fatto
alcun commit dei file dell'archivio e nulla dell'archivio è stato pubblicato.

## Fatti

Integrità (punto 1):

- `MANIFEST.json` sha256 `bebea25099393b9c558fecb0200f6663fd7dc2f2639df23f0a038dad321c5bef`,
  uguale al valore della decisione; 52 file elencati, tutti presenti, sha256 e dimensione
  uguali al manifest; nessun file non elencato; il manifest non elenca sé stesso.

Riservatezza (punto 5):

- Scanner dei segreti di `.github/workflows/ocor-supply-chain.yml` (versione 1.1.0,
  estratto dal workflow ed eseguito sul worktree): `secrets` PASS, zero finding nella
  cartella. Poiché lo scanner esamina solo le estensioni testuali dichiarate (non `.sh` né
  i file senza estensione), gli stessi tre pattern (`AWS_ACCESS_KEY`, `GITHUB_TOKEN`,
  `PRIVATE_KEY`) sono stati applicati anche a tutti i 53 file: zero occorrenze. Nessun
  indirizzo e-mail e nessun percorso `/home/luca` nei file.

Gate che rifiutano la copia invariata:

1. **Language policy (`DEC-212`).** `scripts/validate_language_policy.py` (sha256
   `d32dbd6149f080e7a6e0e6ccb23d91cd79aea15e129b65e6bb852af0024f735e`) con i file
   nell'indice: `FAIL: 46 language-policy violation(s)`, 42 `.sh` e 4 `.py`, «extension has no
   authorized area for this path in OCOR_LANGUAGE_POLICY.md» (sha256
   `cd0e131f2127195144fa168642fd39965a76b8053fd37f41541cf2298ff59fce`). La riga 3 della
   policy esclude esplicitamente lo shell come sostituto dei validatori; nessuna riga
   copre un archivio non eseguito. La policy è normativa (`DEC-212`).
2. **Scanner statico di supply chain.** Stesso workflow (sha256
   `aab635eafb71a3ad705329b8a44d3eba8c06da5688206bd83bb75d2bef34d30d`), regola
   `DYNAMIC_CODE_EXECUTION` (HIGH, bloccante): `tools/workstation/sorveglianza/delega.py`
   riga 96 (sha256 del file
   `c91d1954253c86313cf11e51c04b1a4273eb3d02deca9f49c9f45f31016c3afa`), `exec` sui byte di
   `sentinella.py` dopo la verifica del loro hash. Il job `supply-chain` è fra i 13 check
   obbligatori. Lo scanner non ha un registro di sospensione per i finding statici (il
   registro di `REM-0019-SEALED-SYNTHETIC-SECRET-SCANNER (2026-10-15)` vale solo per i
   segreti sintetici).
3. **Ruff.** `ruff check .` (0.13.1): 16 × `E741` in
   `tools/workstation/sorveglianza/sentinella.py` (sha256
   `5e17a828f06ae43e987bb031c5f3b970d57ec6c852298914fa23a508d396b828`). `pyproject.toml`
   ha già un precedente di esclusione per file content-addressed che non si possono
   modificare (`extend-exclude`, OCOR-DEV-0004/0015 e i corpus di review v1.1/v1.2).

Protezione (punto 3):

4. I «percorsi protetti già controllati dal repository» sono la tupla `IMMUTABLE` di
   `scripts/validate_ocor_change_scope.py` (sha256
   `5eceb1101f98558cca42b5987d82fda6f74b0ec71c940d8eb3360683a9f489f0`), eseguita nel job
   `delivery-activation` sul diff `base...head` della PR. Aggiungere `tools/workstation/`
   alla tupla nella stessa PR che crea la cartella fa fallire quella PR, perché ogni file
   aggiunto è un «immutable path change». Serve un ordine o una forma diversa.

Non richiedono decisione (eseguibili nel perimetro, registrati per completezza): la voce
`CODEOWNERS`; l'allowlist del validator di piano (`authorized planning-only diff` FAIL
sui 53 percorsi nuovi, da aggiornare solo per i nuovi file come da prassi); il controllo
di integrità del punto 4; il drift dell'evidenza (una modifica di prova a
`validate_ocor_change_scope.py` e `CODEOWNERS` dà `drifted_tasks: []` su 75 task); mypy
strict non copre `tools/`.

## Opzioni

Gate 1, language policy:

- **1a (raccomandata).** Una riga nuova di `OCOR_LANGUAGE_POLICY.md` e l'area
  corrispondente in `validate_language_policy.py`: `tools/workstation/**`, «copia
  d'archivio non eseguita, Shell e Python ammessi esclusivamente come contenuto
  archiviato vincolato a `MANIFEST.json`», con divieto esplicito di riferimenti da
  runtime, CI o loop. Pro: dichiarativo, tracciabile, fail-closed per ogni altra area.
- **1b.** Esclusione del solo percorso dal validator senza riga nella policy. Contro: una
  deroga silenziosa a una policy normativa.

Gate 2, scanner statico:

- **2a (raccomandata).** Registro di sospensione dei finding statici, sul modello di
  `REM-0019`: una sola voce vincolata a percorso, sha256 del file, riga e regola
  (`delega.py`, `c91d1954…`, 96, `DYNAMIC_CODE_EXECUTION`); qualunque altro finding, o la
  stessa voce con hash diverso, resta bloccante. Pro: la deroga più stretta possibile.
- **2b.** Escludere `tools/workstation/` dalle sole regole AST statiche, mantenendo
  sintassi e segreti; vincolo al manifest dato dal controllo di integrità. Contro: deroga
  per cartella, più ampia di 2a.
- **2c.** Il PO sostituisce in origine `exec` con un caricamento equivalente
  (`importlib`) e consegna un nuovo manifest. Contro: cambia lo strumento installato.

Gate 3, ruff:

- **3a (raccomandata).** `extend-exclude` di `tools/workstation/` in `pyproject.toml`
  con commento che rimanda a questa decisione, come per i file content-addressed già
  esclusi.

Protezione:

- **4a (raccomandata).** Una sola PR, con regola vincolata: in
  `validate_ocor_change_scope.py` ogni modifica sotto `tools/workstation/` è ammessa solo
  se, all'head, `MANIFEST.json` ha la sha256 fissata nel validator
  (`bebea250…`) e `README.md` la sha256 fissata nel validator; altrimenti FAIL. Una
  modifica futura richiede un nuovo pin, cioè una nuova decisione del PO con nuovo
  manifest; il validator è già sotto `CODEOWNERS`. Il controllo di integrità del punto 4
  impedisce file diversi dal manifest. Nessuna finestra non protetta.
- **4b.** Due PR: prima l'archivio con `CODEOWNERS` e controllo di integrità, poi
  `tools/workstation/` nella tupla `IMMUTABLE`. Contro: doppia campagna CI e una breve
  finestra in cui la cartella è protetta solo da `CODEOWNERS` e dall'integrità.

## Raccomandazione

**1a + 2a + 3a + 4a**, in un'unica PR governata di manutenzione, con test RED/GREEN dei
nuovi controlli (language policy, registro statico, regola vincolata di scope, integrità)
e PRE-CAMPAIGN-GATE prima del push. Nessun file dell'archivio modificato.

## Impatto

- Blocca soltanto l'unità `WORKSTATION-TOOLS-ARCHIVE`. Non blocca `OCOR-DEV-REM-0041`
  (unità overlay), `OCOR-DEV-0060` né `0062`–`0064`, coerentemente con il punto 7 della
  decisione.
- Il worktree locale e il branch non pubblicato restano conservati per la ripresa.
- Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e
  Production `NO-GO`. Nessun nuovo `DEC-*`.
