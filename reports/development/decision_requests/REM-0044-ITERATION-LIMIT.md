# REM-0044-ITERATION-LIMIT

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Riguarda il limite di iterazioni dell'unità del registro
`OCOR-DEV-REM-0044`: otto iterazioni secondo `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)` punto 4, come elevato
dal punto 3 di `NORMATIVE-CONFORMANCE-PROGRAMME-SUPPLEMENT (2026-10-29)`. Il punto 4 prescrive: «Se dopo sei
[otto] iterazioni non hai finito, fermati e apri una decision request di livello normativo con lo stato del
lavoro». È una decisione riservata al PO perché riguarda un limite fissato da una decisione normativa.

## Stato del lavoro

- Iterazioni 1–5: ricognizione di C1–C8, memoria governata, slice legacy e osservazioni; iterazione 6: piano di
  remediation (4.e) e proposte G6/G7 (4.f); iterazione 7: allowlist del piano e `PRE-CAMPAIGN-GATE`; iterazione 8
  (questa): `PRE-CAMPAIGN-GATE` sull'head finale, campagna completa, riqualifiche, record dell'unità, richiesta di
  verifica indipendente.
- Branch `governed/ocor-dev-rem-0044-normative-conformance-register`; commit qualificato `c90b99907f4f67d7a9134dd7c1ce0429592f20a9`; candidato
  `f8270ae90ca904a44da5f7d9de3333be1f68ade8`, pubblicato, senza PR.
- Registro: 83 voci; gravità `HIGH` 59, `LOW` 3, `MEDIUM` 21; stato `DECISION_REQUIRED` 8, `OPEN` 73, `REFUTED` 2; copertura dell'elenco
  iniziale 59/59 e dell'elenco integrativo 11/11; 13 unità `NCP-Uxx` proposte.
- Campagna sul commit qualificato: suite completa a due corsie 3334/3334 PASS, zero skip, 2445 s; test d'integrità 3 run verdi;
  15 controlli negativi rifiutati dal test mirato; riqualifiche di sola regressione di
  `OCOR-DEV-0005`, `0050` e `0082`; `PRE-CAMPAIGN-GATE` 42/42 PASS all'head del candidato (41/42 al commit qualificato, con il solo drift atteso).
- Revisione preventiva `OCOR-DEV-REM-0044-775bc07408b1-pre`: `SKIPPED` dal loop (nessun revisore ammesso).
- Verifica indipendente richiesta al loop: `OCOR-DEV-REM-0044-f8270ae90ca9-0` (`REMEDIATION`, fornitore né Anthropic né OpenAI).

Per finire mancano soltanto passi che il punto 4.g prevede dopo il verdetto: sigillo, PR, check obbligatori, merge,
state sync, e poi la decision request `NORMATIVE-CONFORMANCE-PLAN`. Richiedono almeno un'altra iterazione, perché
la verifica la esegue il loop in un processo separato. Con un `NO_GO` servirebbe anche un ciclo di riparazione.

## Opzioni

1. **Completare la chiusura oltre il limite (raccomandata).** Il PO autorizza fino a tre iterazioni aggiuntive
   per `OCOR-DEV-REM-0044`, solo per la chiusura 4.g: integrazione dopo il `GO_FOR_EVIDENCE_SEAL`, oppure al massimo
   due cicli di riparazione secondo il §8 del prompt del loop, poi lo state sync e la decision request
   `NORMATIVE-CONFORMANCE-PLAN`. Le riparazioni possono toccare soltanto registro, test d'integrità ed evidenza
   dell'unità. Nessun'altra modifica al perimetro, ai test o ai gate.
2. **Chiudere l'unità senza merge.** L'unità si ferma qui e il registro resta sul branch, senza sigillo e senza
   merge. Il PO apre la decisione sul piano dal branch o con un'altra istruzione. In questo caso le campagne G6
   restano sospese finché il registro non è su `main`, perché le condizioni del punto 5 si verificano sul registro
   integrato.
3. **Riprendere da capo con un'unità integrativa.** Si apre un nuovo `OCOR-DEV-REM-*` per la sola chiusura
   (stesso ciclo, limite di tre iterazioni, come l'unità integrativa del punto 3 dell'aggiunta). Questa opzione
   duplica le registrazioni e non porta vantaggi rispetto all'opzione 1.

**Raccomandazione**: opzione 1. Il lavoro sostanziale è terminato entro l'ottava iterazione. Il limite serve a
fermare una ricognizione che non converge, e questa è già conclusa: restano verifica, sigillo e merge, che seguono il
ciclo ordinario delle remediation.

## Impatto e task bloccati

- La verifica indipendente `OCOR-DEV-REM-0044-f8270ae90ca9-0` può proseguire, perché la esegue il loop. L'integrazione di `OCOR-DEV-REM-0044`
  (sigillo, PR, merge, state sync) e la decision request `NORMATIVE-CONFORMANCE-PLAN` attendono questa decisione.
- Restano invariati: le sospensioni di `OCOR-DEV-0060`, `0062`–`0066` e `OCOR-DEV-REM-0043`, i blocchi di
  `0067`–`0069` e il divieto di remediation di codice prima della decisione sul piano. Senza questa decisione non
  resta lavoro ammesso, quindi il loop chiude con `TERMINAL_BLOCKED` alla prossima iterazione senza verdetto
  utilizzabile.
- Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessun nuovo
  `DEC-*`. `main` al momento della richiesta: `64b5ac4487aec24222b4abebf213587b55de4b6f`.

Interpretazione registrata: `CC-OCOR-DELIVERY-COMPLETION` §7 chiede di applicare la lettura fail-closed più
restrittiva. Per questo «finito» comprende il merge del punto 4.g, e il limite risulta esaurito prima del merge.
