# REM-0017-CI-CAMPAIGN-BUDGET

Status: RESOLVED_BY_PO_DECISION — IMPLEMENTATION_PENDING. Data: 2026-10-07T20:07:47.087641+00:00.
Decisione applicabile: REM-0017-PRIORITY, STACK-HYGIENE. Implementatore Codex;
verifier previsto Claude Code, non avviato perché il gate qualificante è FAIL.

La CI della PR #169 sull'HEAD esatto `11fd3e49b606ead40dfb270e3496851e86b55e84`,
[run 37672467983](https://github.com/nepryoon/ocor-detailed-design/actions/runs/37672467983),
ha superato il provisioning completo pinned e ha fallito la campagna completa del
candidato immutabile 0049 `9d86abebc7626a36115540a2711772c1d2d19e23`:
`45-minute campaign limit reached`. Avvio step 19:16:18 UTC, errore registrato
20:02:21.835 UTC dopo arresto e diagnostici. JUnit parziale: 1314 casi, zero
failure/error/skip registrati, tempo 2701.689s; il test Helm era interrotto e il
conteggio non è un PASS della suite da 1426 casi. Il teardown ha fallito con
`owned resources remain after teardown`; non sono esportate le identità delle
risorse residue, quindi causa e tipologia precise sono NOT_EXECUTED.
`validation-closure` ha rifiutato la dipendenza: suite main NOT_EXECUTED; il
suo teardown senza env ha invece verificato inventari vuoti (PASS). Gli artifact
main contengono anche file storici tracciati: non sono prova di esecuzione nuova.

12/13 check richiesti SUCCESS, `validation-closure` FAILURE; job aggiuntivo
`conditional-infrastructure-0049` FAILURE. Nessun rerun opportunistico.
Il run sorgente 16afae4, [37663505832](https://github.com/nepryoon/ocor-detailed-design/actions/runs/37663505832),
era verde: candidato 1426/0 skip in 2650.596s (margine49.404s), main1101/0 skip
in392.547s. Locale: candidato1426/0 skip in2552.413s, main1101/0 skip in383.354s,
report63/0 skip. Le variazioni tra run non giustificano una qualifica stabile.
Il rischio VF-002 del primo verifier si è materializzato; VF-001 non è chiuso.

Docker stats al timeout: runner15.61GiB, Fuseki1.361GiB/2GiB,
Keycloak586.6MiB/2GiB. L'errore del supervisore è timeout, non un allarme OOM;
questo campionamento non dimostra assenza di ogni pressione di risorse.
Diagnostici/raw sul branch governato REM-0017 in `repair-1.log`, SHA256
`76a63b4dbf4636db04534b4b18d8c7727fd05c7a60576013137b2c136db7aaf3`; job log originale SHA256 `c01a189ffff9493622d8df17af3e7d2a5497a3e6a4ca6e186339cb5b8553479f`;
proof JSON esterno SHA256 `ca42c84dcab16eb03da86711d592c41af783445e9292bef06e0d7ec83a3ad07c`.
I dettagli dell'ambiente e gli artifact ID/digest sono nel record non sigillato.

Opzioni: mantenere il blocco e rendere riproducibile la campagna entro2700s con
interventi governati che preservino ogni caso e criterio; oppure disporre
esplicitamente un diverso ambiente non-production autorizzato. Nessuna risorsa
condivisa/a pagamento, modifica semantica o ulteriore riparazione0049 è autorizzata
implicitamente. L'eventuale riapertura di0049 resta nella richiesta REPAIR-BUDGET;
qui non si richiede automaticamente un ciclo8 o l'aumento del limite45 minuti.

Raccomandazione: conservare FAIL e priorità di riqualifica REM-0017, raccogliere
in una ripresa governata pod/job Helm e inventari residui esatti, dimostrare tempi
stabili entro il limite prima della verifica Claude. Questa registrazione segue
la disposizione PO di accodare le misure quando il runner non completa lo stack
nei tempi, quindi proseguire subito con0050/G5 indipendente. Non anticipa alcuna
approvazione. Bloccati: chiusura REM-0017 e tutti i task G6/G7 che la richiedono;
0050–0058 restano raggiungibili. PR169 resta draft, nessun sigillo/merge REM.
E1=0, E2=0, zero Verified, NO-GO invariati; inputs, lock e gate immutati.


Il WIP e i raw sono versionati nel commit `433613772806b3034e1229d7cd58a5d92841e8c2` della PR169;
lo state sync di questa richiesta non integra script, workflow o candidati REM.
La CI del solo state sync mantiene la deviazione temporanea già autorizzata
della PR164: non è evidenza qualificante REM-0017 o0049.


## 2026-10-08T07:18:03.967776+00:00 — Risoluzione Product Owner (2026-10-07)

La decisione `REM-0017-CI-CAMPAIGN-BUDGET` risolve questa richiesta: limite della suite completa locale/CI **75 minuti (4500s)**; suite del task **45 minuti (2700s)**. Se una full supera60 minuti si apre nuova richiesta con le durate, senza alzare il limite. Arresto immediato al primo servizio riavviato/OOM con statistiche/log invariato; nessun caso o criterio escluso. REM-0017 deve esportare le identità delle risorse residue nel teardown e correggerne la causa, fail-closed.

Decisione recepita; richiesta chiusa, implementazione/qualifica REM pendenti sulla PR169, non realizzate da questo state sync.0049 ciclo8 ha chiusura verificata GO ma PR176 CI rossa: si applica REM-0017-PRIORITY, PR aperta→REM→riallineamento/merge0049. Diagnosi CI PR176: anche rccad-methodology/delivery-activation mancano dell’env del vero stack e di mypy (extras lint); 1 failed/1164 passed/189 skipped/137 errors per ciascuno, non qualificanti. La remediation deve coprire tutti i job full-suite; nessuna nuova deroga o esclusione. Nessun completamento o sigillo REM, nessuna verifica simulata. G6 resta bloccato fino alla chiusura verificata del REM.
