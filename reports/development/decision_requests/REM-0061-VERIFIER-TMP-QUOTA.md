# REM-0061-VERIFIER-TMP-QUOTA

Status: `DECIDED_BY_PO`. Livello: operativo. Nessun nuovo `DEC-*`.
Riguarda la verifica indipendente di `OCOR-DEV-REM-0061`, ciclo di riparazione 1, non il codice del
trasferimento delle immagini. La questione riguarda l'ambiente di verifica indipendente, che sta fuori
da questo repository: la richiesta resta al Product Owner.

## Contesto

Il verdetto `OCOR-DEV-REM-0061-69bbc51fb031-0` sull'HEAD `69bbc51fb031e06f11b1bd442985b88b4b639d51` è
`NO_GO`. La suite completa dell'orchestratore locale è `NOT_EXECUTED`. Il comando ha ammesso quattro
corsie, ha raccolto 5826 casi e si è fermato dopo 47,855 s, prima di pytest: il checkout della seconda
corsia è uscito con codice 128.

```
fatal: sha1 file '/tmp/ocor-verify-OCOR-DEV-REM-0061-69bbc51fb031-0/full/lane-2/repo/.git/index.lock' write error: Disk quota exceeded
```

`lanes_run` è 0. I quattro teardown sono PASS e il controllo dei residui è vuoto. Log
`/tmp/ocor-verify-OCOR-DEV-REM-0061-69bbc51fb031-0/full.log`, sha256
`c1266b2baeacbca4dda247ebaf56d8952607decb0a81fdc8ba667bff4e3b898f` (13124 byte; è anche il risultato
`full/campaign_result.json`). Verdetto sha256
`57f78a52d22fc11a938faaaf7ec88b9ffff83ab199d292455a63b500242f644b`.

`/tmp` è un tmpfs con opzione `usrquota` (`findmnt`: `rw,nosuid,nodev,size=32099836k,nr_inodes=1048576,inode64,usrquota`).
`df` mostra spazio libero sul filesystem e non misura la quota dell'utente. `quota` non è installato.
`sudo -n` chiede una password, quindi questa unità non può leggere né alzare la quota.

Misure di scrittura dell'utente `luca` (uid 1000), file rimosso subito dopo ogni prova:

- una scrittura di byte non nulli si è fermata con `Errno 122` a 5272 MiB;
- più tardi, con `/tmp` che occupava circa 104 MiB, la stessa scrittura ha completato 6442450944 byte
  (6144 MiB) e poi 12884901888 byte (12 GiB) senza errore.

La quota libera non è stabile nello stesso giorno. La somma delle parti misurate di una campagna a
quattro corsie supera la misura più bassa: cache delle immagini 1,7 GiB
(`/home/luca/.ocor-codex/rem-0061/campaign-6c0a233-run3/image-cache`), un virtualenv di `ocor-runtime`
1,1 GiB, quattro alberi di checkout (la directory `reports` pesa 979 MiB) e la copia degli strumenti
(181 MiB). La campagna locale già eseguita sta sul filesystem radice, sotto la home, e non ha
incontrato questa quota. Una verifica richiesta adesso può esaurire l'ultimo ciclo di riparazione su
un fallimento di ambiente già osservato.

Il mount in sola lettura della cache, in questo ciclo di riparazione, non cambia la quota né la
directory di lavoro della verifica. Ridurre corsie, servizi, timeout, guardia di memoria o il controllo
di unione non è ammesso.

## Opzioni

1. **Quota sufficiente sulla directory temporanea (raccomandata).** Alzare o togliere la quota utente
   di `/tmp` in modo che una verifica possa tenere nello stesso momento la cache delle immagini, quattro
   clone del repository e quattro ambienti isolati, con margine rispetto all'altra occupazione della
   directory temporanea. Poi rieseguire lo stesso comando di verifica, con le corsie ammesse, i servizi
   pinned, i timeout, la guardia di memoria e il controllo di unione invariati. Nessuna modifica al
   codice, al lock delle immagini o all'orchestratore.
2. **Stesso comando, directory di lavoro sul filesystem radice.** Lasciare la quota di `/tmp` invariata
   e far scrivere la verifica sul filesystem radice, che al 2026-11-11 ha centinaia di GiB liberi e non
   applica questa quota utente. Stessi corsie, servizi, timeout, guardia e controllo di unione. Cambia
   solo il punto in cui la verifica scrive.

## Raccomandazione

Opzione 1. La correzione richiesta dal verdetto è una quota sufficiente e lo stesso comando. L'opzione 2
sposta la directory di lavoro: è un cambiamento dell'ambiente di verifica, che questa unità non può
fare da sola.

## Impatto e task bloccati

Bloccata la richiesta di verifica indipendente di `OCOR-DEV-REM-0061` finché l'ambiente non può tenere
la campagna. Non è bloccato il repair del mount in sola lettura, né la campagna locale a quattro corsie
sul filesystem radice. `OCOR-DEV-REM-0060` (NCP-U12) resta in coda fino al sigillo di `OCOR-DEV-REM-0061`.
Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
Nessuna modifica a `inputs/`.

## Disposition

Decisione operativa del PO `TMP-RESIDUI-CAMPAGNA (2026-11-11)`, letta in questo turno prima della richiesta di verifica. Non è l'opzione 1 e non è l'opzione 2. La richiesta decisa è il file al commit `83d9b74648c14a2afb14904a2a83183274ece7c9`, sha256 `89b7412b40ff2188c1c02e93bc5445fcf012f0447e97bd63c05160fa07b44bed` (verificata prima dell'attuazione). Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`; claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

Il PO ha rimosso a mano i residui sotto `/tmp` (16 directory, 19,2 GB) che avevano causato `Disk quota exceeded` nel checkout della seconda corsia. La decisione chiede, in questa riparazione:

1. ogni script che crea directory di lavoro in `/tmp` per campagne, gate o preparazione delle corsie le rimuove a fine run, anche su errore o interruzione (`try/finally` e segnali); in alternativa le crea sotto `~/.ocor-codex/<unità>/` con la stessa rimozione; le evidenze restano fuori da quelle directory;
2. prima di lanciare le corsie, lo script misura lo spazio libero di `/tmp`, quota utente compresa, e se non basta per le corsie previste si ferma con una diagnosi esplicita;
3. test RED/GREEN e i controlli della pipeline.

La pulizia periodica dei residui non usati da più di sei ore resta al PO. Questa unità non alza la quota di `/tmp` e non sposta la directory di lavoro della verifica.
