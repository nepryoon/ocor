# FABLE52-LOOP-INSTRUCTIONS-AND-ARCHIVE

Status: `OPEN_PO_DECISION_REQUIRED`. Livello: operativo, riservato al PO (riguarda le istruzioni e gli strumenti del
loop sulla workstation, non il repository OCOR). Origine: audit `reports/review/OCOR_FABLE52_AUDIT_2026-11-11.md`,
finding F-16, F-17, F-19, sull'archivio degli strumenti al commit `41642908654b9482ead8622402e3396614a6df0d`.
Redatto da Claude Fable 5.2 (Anthropic) in sola lettura.

## Contesto

- Il file delle decisioni passato all'implementatore a ogni iterazione (`openhands_preamble.md`) è di 391.738 byte
  in 152 sezioni; il prompt del verifier (`verifier_prompt.md`) è di 128.203 byte in 97 sezioni. Molte sezioni riguardano unità già integrate. Una stessa
  intestazione compare due volte (righe 145 e 167 del file delle decisioni).
- L'archivio giornaliero degli strumenti non raccoglie le cartelle delle estensioni, che le migliorie automatiche
  possono creare, né il programma eseguito dal blocco personale di Grok (ne archivia solo il file JSON).
- L'insieme degli implementatori di un task si ricostruisce dal registro del loop, che è un file scrivibile.

## Opzioni

1. **Indice e archivio delle sezioni chiuse, archivio completo (raccomandata).** (a) Le sezioni che riguardano unità
   registrate come integrate nello stato passano, senza modifiche, in un file di archivio accanto all'originale; nel
   file attivo resta una riga per sezione con identificativo, data e sha256 del testo archiviato. Restano attive le
   decisioni permanenti, le autorizzazioni e ogni sezione citata da una unità aperta. L'operazione è uno script con
   controllo preliminare, copia di riserva e verifica delle tre autorizzazioni prima e dopo. (b) Lo script di
   archiviazione raccoglie anche le due cartelle delle estensioni e i programmi dei blocchi personali. (c) Il
   registro dei verdetti introdotto da `PRE-VERIFY-GATE (2026-11-11)` registra anche gli implementatori avviati.
2. **Solo archivio completo** (punto b), senza toccare il file delle decisioni.
3. **Nessuna modifica.**

## Impatto a cascata

Opzione 1: un installatore per la workstation, da lanciare a loop fermo; nessun file del repository OCOR. Le
decisioni prese in precedenza restano leggibili nell'archivio con lo stesso testo. Prima dell'esecuzione va
verificato sulle copie che il componente che riconosce le decisioni già prese le ritrovi anche dall'indice.

## Criteri di accettazione verificabili

- Dopo l'operazione il file attivo è sotto 120.000 byte; ogni riga dell'indice ha uno sha256 uguale a quello della
  sezione nell'archivio; nessuna intestazione è ripetuta.
- Le tre verifiche di autorizzazione e di integrità passano sulle copie e sui file reali.
- L'archivio degli strumenti contiene i file delle due cartelle delle estensioni e i programmi dei blocchi.

Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
