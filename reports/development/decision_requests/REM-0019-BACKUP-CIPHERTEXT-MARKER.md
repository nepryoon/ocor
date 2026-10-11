# REM-0019-BACKUP-CIPHERTEXT-MARKER

Status: `RESOLVED_PO_DECISION` (opzione 1, decisione PO 2026-10-11). Stato originario: `OPEN_PO_DECISION_REQUIRED`. Data: 2026-10-11T05:59:24.499712+00:00.
Registrazione e diagnosi: Codex (OpenAI), implementatore del loop.
Codice di REM-0019, cicli 0 e 1: Claude Code (implementatore di riserva).
Verifier del task: Grok 4.7 tramite Cursor CLI (`verifier: cursor`), processo,
contesto e fornitore separati. Nessuna nuova verifica indipendente avviata.

## Contesto e osservazione

La decisione PO `REM-0017-CI-0049-REMAINDER-CAP` del 2026-10-10 autorizza solo
il modulo di test di 0049 e i suoi fixture, con «stessi 390 casi e stesse
asserzioni». Il codice di produzione e il record sigillato storico restano invariati.

Sul commit `63a0a939d84402af4ed91acd77de2dac341ee976`, il run live
`order-seed-190003`, tentativo 1, ha concluso con exit 1,
389 PASS, 1 FAIL, 0 skip in 2350.8 s. Fallisce
`test_backup_seals_an_encrypted_signed_immutable_recovery_point` alla riga 1813:

```python
assert b"PGDMP" not in blob and b"tenant-a" not in blob and b"evt-del" not in blob
```

L'asserzione è identica a quella di `df444af855e884d7783612b302e008b90105fe13`.
L'analisi conservata trova `PGDMP` all'offset 6274804 del blob
`5c683b9c4298079c2773951321e3739f752d7c8669e5ff92badf9ddcd28cdcbc.enc`,
lungo 10109372 byte, dentro il testo base64 di un chunk `vault:v1:`.
La cornice JSON dei chunk è quella attesa. Questa osservazione dimostra un
difetto del predicato lessicale, non prova da sola la correttezza crittografica
del backup: l'autenticazione/decrittazione completa di quel blob non è stata
rieseguita da Codex in questa iterazione (`NOT_EXECUTED`).

L'inferenza di falso positivo è coerente con l'alfabeto base64: `PGDMP` è una
sequenza possibile anche per ciphertext corretto. La stima ≈0,94% riportata
nell'analisi deriva da un modello di caratteri uniformi su 10129416
caratteri; non è un tasso misurato di fallimento. Anche cercare marcatori nel
ciphertext binario decodificato lascerebbe una probabilità non nulla di
collisione e non risolverebbe strutturalmente il difetto.

## Vincolo e disposizione attuale

Un test intermittente non è un PASS. L'eventuale rerun verde non chiude il
finding e non rende qualificante la campagna mentre il predicato resta
invariato. Nessun errore è escluso dai conteggi o rietichettato.
La nota locale precedente descriveva la richiesta come non bloccante: questa
registrazione rettifica quella disposizione per la qualifica di REM-0019 e
per le integrazioni che ne dipendono, preservando il tentativo storico.

Codex non modifica l'asserzione: cambiarla eccederebbe il vincolo puntuale del
PO. Il ciclo di riparazione 1 resta in corso; la diagnosi non consuma un nuovo
ciclo e non è un verdetto indipendente. I processi di test già avviati dalla
sessione precedente possono completare la raccolta diagnostica; nessun loro
esito cancella il FAIL registrato. Nessuna nuova richiesta di verifica o
sigillo finché il blocco non è risolto.

## Opzioni e raccomandazione

1. **Autorizzare una variazione puntuale del test**, mantenendo i 390 casi,
   il codice di produzione e tutti gli altri criteri. Raccomandata: sostituire
   la ricerca di sottostringhe nel ciphertext con verifica strutturale stretta
   dell'envelope e decrittazione autenticata sul backend pinned, collegando il
   plaintext recuperato ai digest/source artifact attesi. Prima del codice:
   positivo con ciphertext valido contenente la sequenza lessicale (se
   riproducibile senza alterare il backend) e negativi deterministici per
   plaintext, base64 del plaintext camuffato da chunk, envelope malformato e
   ciphertext alterato. Il progetto concreto e le prove restano da realizzare:
   questa proposta non li dichiara eseguiti o sufficienti senza verifica.
2. **Mantenere l'asserzione invariata**: REM-0019 resta non qualificato sul
   difetto osservato; REM-0017 e l'integrazione di 0049 restano in attesa.
   Ripetere fino al verde non è una soluzione ammissibile alla stabilità.

## Impatto e lavoro eseguibile

Bloccati su questo punto: qualifica e sigillo di `OCOR-DEV-REM-0019`, successiva
ripresa qualificante di `OCOR-DEV-REM-0017` e integrazione di `OCOR-DEV-0049`
(PR #176); i loro prerequisiti di G6 restano aperti. Non blocca le dipendenze
tecniche di G5: ready set dal backlog e da origin/main = 0049, 0056, 0057;
0049 non è integrabile, il prossimo task indipendente è 0056 appena lo stack
è libero. Nessun lavoro di G6 viene avviato.

Il nuovo path non è nell'allowlist di `validate_ocor_development_plan.py` su
main. La richiesta è conservata su un branch `governed/` dedicato e richiamata
con commit e digest nello state sync; la sua integrazione futura richiede
l'estensione chirurgica autorizzata dell'allowlist e la relativa riqualifica
di 0050. Nessun validator è modificato o bypassato in questa iterazione.

## Provenienza content-addressed

Directory locale: `/home/luca/.ocor-codex/rem-0019-r1/attempts/`.
Le impronte sono riacquisite dai byte conservati; non sono nuovi risultati
di test. Nessun raw privato del nodo kind o secret è incluso nella richiesta.

| Artefatto | SHA256 |
|---|---|
| `attempt1-order-seed-190003.json` | `0abbf4999bfdde9ccaf360a1b978923d193f66e29628e240e22f34b747c2254d` |
| `attempt1-order-seed-190003-marker-analysis.json` | `9127903feccea839b3c8d74fd9a08fc11cf564a5dbe90ebeb052fc2cbb838e5b` |
| `attempt1-order-seed-190003.xml` | `e837866bb29b70a155c7314ef9c013e9b838bed315edb5ef9087d9ce66874303` |
| `attempt1-order-seed-190003.log` | `e881e0b10abc944e4cad1552f8e897103c0f2a5dd796de2522e5439094d98b13` |
| `attempt1-order-seed-190003.order` | `e723bb96f56f4e6ade80394eedc3f4922141e79f0bbd8f37a43baa8f79c5cf74` |
| `attempt1-order-seed-190003-residue.json` | `011b70eac3c85c5738f6b3803b77099d6e2070188c86b9f24f412560c309ce9d` |

Riferimenti: ADD v1.3 Part I §6.4–6.5; LLD v1.1 §5.4; strategia RCCAD su
stabilità, zero skip e verifica indipendente; decisione PO citata sopra.
E1=0, E2=0, zero Verified, runtime NOT_ESTABLISHED e PoC/Production NO-GO
restano invariati. Nessun nuovo DEC, nessuna modifica a inputs/ o a evidenze
sigillate.

## Disposition del Product Owner — 2026-10-11

Risolta con opzione 1 (`REM-0019-BACKUP-CIPHERTEXT-MARKER` nella conversazione corrente).
Autorizzato il solo cambio dell’asserzione lessicale del backup: schema chiuso
dell’envelope/chunk, decrittazione autenticata su OpenBao pinned, collegamento
a digest e sorgenti attese, marcatori positivi nel plaintext e assenti dalla
cornice. Negativi deterministici e mutante del writer che salva plaintext.
Produzione 0049 invariata e 390 casi conservati. L’eventuale ciphertext valido
contenente PGDMP viene provato solo se riproducibile senza alterare il backend.

Autorizzati i soli path nominati nell’allowlist del piano per questa richiesta
e per l’evidenza REM-0019/riqualifica 0050. Record sigillati storici invariati.
Il FAIL order-seed-190003 resta diagnostico storico. Tutta la campagna
(collection, reverse, tre seed, 119 isolati) deve essere rieseguita sul commit
finale; un caso mirato verde non qualifica il task. Ciclo di riparazione 1
invariato, nessun nuovo ciclo consumato.

Implementatori REM-0019: Claude Code (riserva, cicli 0/1) e Codex (riparazione
puntuale dell’oracolo nel ciclo 1). Verifier: Grok 4.7 tramite Cursor CLI
(`verifier: cursor`), processo e contesto separati. E1/E2/Verified e claim
NO-GO invariati. La chiusura della richiesta non chiude la remediation.
