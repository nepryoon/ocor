# REM-0017-CI-ARCHIVE-ACQUISITION

Status: OPEN_PO_DECISION_REQUIRED. Data: 2026-10-08T09:40:15.212131+00:00.
Implementatore Codex; verifier previsto Claude Code, non richiesto.

La PR169 draft sul source HEAD `40c9c0925970f7e2b9d5217d1af3e8d2a950be68` fallisce prima dell'avvio dello stack:
[run RCCAD37749800723](https://github.com/nepryoon/ocor-detailed-design/actions/runs/37749800723) e
[run closure37749801174](https://github.com/nepryoon/ocor-detailed-design/actions/runs/37749801174),
ciascuno al primo tentativo e all'unico rerun autorizzato. Il buildlog localizza
il timeout600s nel Docker ADD dell'archivio ufficiale
`https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-6.2.0.tar.gz`.
Base digest-pinned acquisita; download dell'archivio non concluso nel budget.
Non è prova di OOM, indisponibilità DNS o alterazione dell'archivio. Il controllo
SHA512 non raggiunto nei run falliti resta NOT_EXECUTED. Nessun nuovo retry.

11/13 required verdi: rccad-methodology e validation-closure FAIL;
conditional-infrastructure-0049 FAIL; candidate/main closure FULL NOT_EXECUTED.
[Delivery37749800685](https://github.com/nepryoon/ocor-detailed-design/actions/runs/37749800685)
completa invece la stessa ricetta e la FULL1101/zero skip in509.84s con teardown
PASS. Non trasferisce il PASS ai run falliti o ai successivi HEAD.
Locale storico: main1101 e candidato0049 df444af1491, zero skip, supervisore
362.80s e2845.55s; ultima portfolio73 PASS. FULL e CI dell'ultimo codice restano
NOT_EXECUTED: correzioni locali successive non riqualificano i run precedenti.

Budget suite completa4500s e task2700s, arresto restart/OOM, ricetta,
Dockerfile, lock, SHA512 e checker invariati. Il precedente budget300s
era stato portato al massimo già ammesso600s; non viene ulteriormente esteso.
Opzioni: mantenere600s e rendere riproducibile l'acquisizione ufficiale con
una cache content-addressed in un change set governato, conservando il
controllo SHA512 e i digest; oppure autorizzare esplicitamente un budget
di provisioning superiore sulla base di nuove misure, lasciando75/45 minuti
e tutti i gate invariati. Raccomandazione: acquisizione verificata/cache
senza modificare semantica o tecnologie. La cache verificata repository-scoped
resta una scelta tecnica autonoma entro DEC-211; la richiesta al PO riguarda
soltanto eventuali estensioni del budget o risorse oltre il perimetro.
Nessuna risorsa a pagamento o condivisa.

Impatto: chiusura REM17, CI integrazione0049 e G6/G7 restano bloccati;
0050/G5 e gli audit governati indipendenti restano eseguibili. PR169 draft e
PR176 aperta, nessun merge0049. Si applica REM-0017-PRIORITY: proseguire0050.
Non è esaurito il budget di riparazioni: repair1, nuova verifica non effettuata.

Il teardown locale ha zero delta di container/volumi/reti rispetto alla
baseline; il wrapper finale FAIL nel ripristino dell'immagine locale precedente
non più presente. Nessun retry/lock update; resta la richiesta separata
FUSEKI-LOCAL-IDENTITY-AFTER-CI-EXERCISE. Fonte WIP `8ff46dbd7cf3b1f44030094c6078772063e34e86`,
branch governed/ocor-dev-rem-0017-ci-provision-spire; record nuovo non sigillato
`reports/assurance/OCOR-DEV-REM-0017-RCCAD/repair-1-resume.json`,
raw SHA256 `992cb8ef66d9c508afcd27f12e516d53e4e35c45d07d344e3d9356d13962a12c`; record storici preservati.
Inputs immutati; E1=0/E2=0/Verified0, runtime NOT_ESTABLISHED, NO-GO invariati.

Il WIP completo è pubblicato su `23801b08a50d4212acb65bac8b46313b5c62ae95`; questo state sync promuove soltanto
stato/log/richiesta, nessuno script di provisioning, workflow o record REM.


## 2026-10-08T09:56:03.754217+00:00 — CI dell'ultimo WIP23801b0 conclusa

HEAD23801b08a50d4212acb65bac8b46313b5c62ae95:10/13 required PASS,
RCCAD37758409850/delivery37758409836/closure37758409757 FAIL;
conditional-infrastructure-0049 FAIL. Tutti i provisioning al timeout600s,
RCCAD buildlog conferma ADD dello stesso archivio, base acquisita3.1s;
nessuna FULL qualificante. Nessun retry aggiuntivo di questo HEAD dopo
il retry bounded già consumato su40c9, senza cambiamento pertinente.
Raw RCCAD SHA256d6083bf4369e02ac6d20e3ef1444b320fb3bab2421a3d64dbe85f167cf9f9a1f;
closure cade569b43e1802439ee5ade9d0fba011391994c0bbbfb941d298b33d059b681;
delivery87c9c49652ec80f1bd4c7bb70389eb97ef030b1b20e292da36e42dfedba442c0.
Il PASS delivery40c9 è storico, non trasferito al finale.
