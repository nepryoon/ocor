# FABLE52-POST-POC-PROGRAMME

Status: `OPEN_PO_DECISION_REQUIRED`. Livello: normativo (estensione del piano approvato oltre G7; nessun requisito
cambia). Origine: audit `reports/review/OCOR_FABLE52_AUDIT_2026-11-11.md`, finding F-22 e gap G-1…G-9, su `main`
`113f935cf6e04df460406a0b5dfea6949df6723a`. Redatto da Claude Fable 5.2 (Anthropic) in sola lettura.

## Contesto

- Il piano approvato termina con il pacchetto di decisione del PoC: «The separate Production campaign is
  deliberately absent from implementation tasks» (`docs/development_plan/OCOR_AI_FIRST_DEVELOPMENT_PLAN.md:57`); i
  gate del backlog sono G0-G7. L'obiettivo dichiarato dal PO il 2026-10-29 è un prodotto pronto per l'integrazione in
  produzione.
- La proposta di backlog G8-G11 del 2026-10-30 (51 task) non è stata adottata e non è nel repository.
- Dal confronto con lo stato dell'arte del 2026 (sezione 3 dell'audit) emergono voci che quella proposta non
  conteneva: profilo MCP alla revisione 2026-07-28 (G-1), confine A2A (G-2), esportazione OSI (G-3), soglia misurata
  di qualità della memoria (G-5), scoperta causale come generazione di ipotesi (G-6), mappa OWASP per gli agenti
  (G-7).

## Opzioni

1. **Programma post-PoC deciso ora, eseguito dopo la decisione su G7 (raccomandata).** Il PO approva l'estensione
   dello schema del backlog ai gate G8-G11 e incarica una unità di sola pianificazione, da eseguire in parallelo in
   sola lettura, che produca il backlog esteso a partire dalla proposta del 2026-10-30 riverificata sull'head
   corrente, con queste aggiunte e classificazioni: G-1 e G-7 in G8 (necessarie); G-5 in G10 con soglia
   preregistrata su un benchmark pubblico di memoria ed esecuzione sugli store reali (necessaria); G-3 in G9
   (generatore C1 di un artefatto derivato, facoltativa ma richiesta dal posizionamento come nucleo di una
   piattaforma di analisi); G-2 e G-6 in G11 o successivi (facoltative; G-6 solo come proposte marcate come ipotesi,
   mai come modifica di un modello causale registrato). Nessun task post-PoC parte prima della decisione su G7.
2. **Programma deciso dopo G7.** Nessuna pianificazione ora; il rischio è che le unità G6 fissino scelte da rifare
   (per esempio il profilo MCP).
3. **Solo G-1 e G-7 subito**, come unità prima di `OCOR-DEV-0064`, e il resto dopo G7.

## Impatto a cascata

Opzione 1: `docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.schema.json` (pattern dei gate e degli identificativi),
backlog, DAG, piano di tracciabilità con `release_profile` per i 68 requisiti fuori dal profilo PoC, validatore del
piano. Stima della sola pianificazione: 3 iterazioni, senza toccare codice o test. La stima del programma resta
quella della proposta (238 iterazioni) più le aggiunte: G-1 3, G-3 3, G-5 6, G-7 2, G-2 6, G-6 6.

## Criteri di accettazione verificabili

- Il backlog esteso passa `scripts/validate_ocor_development_plan.py` con lo schema esteso; ogni requisito con
  release diversa da PoC ha un task di verifica in un gate G8-G11 e nessuno in G6.
- Ogni voce G-1…G-7 adottata ha un task con criteri positivi e negativi e il metodo di verifica del Register.
- Il task di G-5 nomina benchmark, versione, soglia e store prima dell'esecuzione; il task di G-6 ha un criterio
  negativo: una relazione proposta non entra nel modello causale né nello stato canonico senza il percorso governato.

Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
