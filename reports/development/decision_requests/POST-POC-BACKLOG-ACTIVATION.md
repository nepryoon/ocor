# POST-POC-BACKLOG-ACTIVATION

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`

Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0062` e i file nuovi in
`docs/development_plan/post_poc/`. Quei file non sono il backlog approvato.
Ogni task ha stato `PLANNED_NOT_ACTIVE`. Nessun task dei gate G8, G9, G10 e
G11 è eseguibile. ADD v1.3, LLD v1.1, contratti, schemi, Register, backlog
approvato, piano di tracciabilità e `inputs/` non cambiano con questa
richiesta. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime
`NOT_ESTABLISHED`, PoC `NO-GO`, Production `NO-GO`.

## Contesto

`FABLE52-POST-POC-PROGRAMME (2026-11-11)`, punto 3, chiede un piano dopo il
PoC in file nuovi. Il punto 4 vieta di eseguire i task G8-G11 prima della
decisione del Product Owner su G7 e affida a una decisione successiva
l'estensione dello schema del backlog, l'ingresso dei task nel backlog
eseguibile e lo spostamento dei requisiti nel piano di tracciabilità. Questa
richiesta è quella decisione. Non sceglie il momento.

Il piano àncora la baseline `2278be4180de5d91d1fec9d7608027b0f287b545`. I
requisiti la cui release non è esattamente `PoC` hanno un task di realizzazione
e un task di verifica, con il metodo del Register. Le voci adottate hanno
criteri positivi e negativi. Il grafo è aciclico. G-4 è solo osservata. G-7
resta un'unità distinta, prima di `OCOR-DEV-0062`. La voce di audit sulla
supply chain non è il gate G8. La soglia numerica e l'identità del benchmark
di G-5 non sono scelte: restano la decisione esterna
`G5-BENCHMARK-PREREGISTRATION`.

## Opzioni

1. **Attivare insieme alla decisione su G7.** Nello stesso change set si estende lo schema del backlog, si ammettono i task e si spostano i requisiti nel piano di tracciabilità.

2. **Attivare in un change set successivo alla decisione su G7.** I file restano un piano non eseguibile fino a quel change set.

3. **Non attivare.** I file restano un piano non eseguibile e nessun task entra nel backlog eseguibile.

## Impatto e task bloccati

Fino a una decisione, restano bloccati tutti i task `OCOR-POST-*`. Il blocco
non ferma il percorso del PoC. La decisione del Product Owner su G7 resta un
presupposto distinto: anche dopo l'esito di questa richiesta, nessun task
G8-G11 si esegue prima di quella decisione. Non si apre un nuovo `DEC-*`.

## Raccomandazione

Nessuna raccomandazione sul momento. Il Product Owner sceglie il momento
dell'attivazione. Questo testo non designa una preferenza fra le tre voci
elencate sopra.
