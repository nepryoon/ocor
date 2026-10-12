# REM-0022 — CI evidence supersession, repair 1

Status: `SEALED_PENDING_EXACT_GREEN_CI`. Due GO sul candidato esatto `a9d2ffe6f14799a678f935bd2eb939438bd0fae5`: Claude Code per REM-0022/0019/0040 e Grok 4.7 via Cursor per la sola regressione 0050. I sigilli includono identita/configurazione effettive, scope, finding e SHA256 del verdetto verbatim conservato dal loop. Nessuna suite nuova in questa unita di integrazione.

Candidato distinto, sigillato. I sorgenti Kafka e i 22 casi del task sono identici
al candidato verificato `a54ebb56955b81a2174cb8b3dc14d0775dcf8bb8`. I quattro record
sigillati del branch storico `e8449a91e7f1bb918905d81992db81e447e36e8a` restano
immutabili; ogni nuovo record li collega tramite `supersedes` e commit/path/SHA256.
La PR #220 resta aperta e non unita, con il fallimento `supply-chain` conservato.

La riparazione riguarda la serializzazione dei metadati: nomi base più SHA256
dell'identità completa del caso, con collegamento uno-a-uno al JUnit raw. Nessun
parametro, caso, asserzione, scanner o gate è rinominato, escluso o indebolito.
Collection e JUnit devono coincidere esattamente, senza skip/failure/error.

```bash
# Eseguire il checker nel worktree detached sul candidato non sigillato a9d2ffe6f147
python reports/tests/check_rem0022_ci_evidence.py .
python -m pytest -q reports/tests/test_rem0022_case_identity.py
```

Il checker ricostruisce il candidato **prima del sigillo**, inclusi input del commit
sorgente, raw, hash di ogni comando, identità dei casi e storia preservata. I raw
contengono anche i diagnostici falliti, distinti dai comandi qualificanti; non sono
rietichettati come PASS. I metadati contengono solo le identità content-addressed,
mentre il raw JUnit mantiene i nomi completi originali.

Implementatore: Codex (OpenAI). Verifica primaria richiesta: Claude Code (Anthropic),
processo/contesto/fornitore separati, per REM-0022 e riqualifiche 0019/0040. La
riqualifica di 0050 richiede inoltre Grok 4.7 via Cursor, in sola regressione dei
198 test invariati e integrità dell'evidenza, secondo la disposizione PO del
2026-10-11. Nessun GO storico autorizza il nuovo candidato; entrambi i nuovi GO
sull'HEAD esatto sono necessari prima del sigillo. Il loop esterno avvia i verifier.

Rimangono aperti il finding non bloccante sul retry del teardown Kafka e REM-0023
per l'audit dei dinieghi di admission. `E1=0`, `E2=0`, zero requisiti globalmente
`Verified`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO` invariati.
