# REM-0023-DENIAL-AUDIT-CONSUMER-FIXTURES

Status: OPEN_PO_DECISION_REQUIRED — estensione puntuale delle aree di file.
Nessuna variazione normativa richiesta. Autorità corrente: decisione PO
REM-0022-0050-ROLE-REVIEW-DISPOSITION (2026-10-11), DEC-210/211.

## Contesto e prova

REM-0023 aggiunge MemoryAdmissionAuditSink v1 al boundary reale. Il RED iniziale
prova un rifiuto senza audit durevole su PostgreSQL e senza append al journal.
Il cablaggio esplicito passa 302 casi (198 di 0050 e 104 della REM), zero skip.
La regressione estesa passa 481 casi e fallisce quattro asserzioni: i fixture
0054/0055 non forniscono il nuovo port. Il boundary rifiuta esplicitamente con
CONTROL_PLANE_UNAVAILABLE/AUDIT_UNAVAILABLE, come richiesto quando audit manca.
Non è infrastruttura e non è un PASS. Nessuna suite completa avviata.

Il record [checkpoint.json](../../assurance/OCOR-DEV-REM-0023-RCCAD/checkpoint.json)
lega conteggi e hash ai raw in checkpoint.log. I quattro casi sono:

- 0054: test_a_deadline_elapsing_during_the_job_writes_nothing;
- 0054: test_derived_memory_and_dissent_cannot_be_admitted_or_rewritten_around_the_service;
- 0054: test_a_directly_admitted_dissent_cannot_be_rewritten_by_a_new_version;
- 0055: test_the_admission_guard_refuses_a_new_version_on_an_excluded_head.

I costruttori in CWorld (0054) e World (0055) e i rispettivi fixture vanno cablati
all'audit authority. Questi due file non sono nelle expected_file_areas del record
versionato REM_0023_MEMORY_ADMISSION_DENIAL_AUDIT. AGENTS.md impone:
«le scritture sono limitate al change set autorizzato e alle aree dichiarate nel backlog».
Il loop conserva quindi il checkpoint e richiede l'estensione senza cambiare test
fuori area o nascondere la causa con una diversa semantica dell'errore.

## Opzioni

1. **Raccomandata.** Autorizzare nel change set governed/ di REM-0023 i soli
   costruttori MemoryAdmissionService e relativi fixture nei file
   ocor-runtime/tests/tasks/test_ocor_dev_0054.py e test_ocor_dev_0055.py,
   per passare esplicitamente il port di audit. Stessi casi, identità, asserzioni
   e reason code; nessun caso rimosso, unito, escluso o saltato. Riqualificare
   0054 e 0055 con nuovi record e supersession esplicita, oltre a 0050 già
   richiesto; registri e sigilli storici intatti. Aggiungere alla sola allowlist
   del piano i percorsi esatti e le nuove evidenze; aggiornare i report derivati.
2. Tenere REM-0023 bloccata e stabilire un diverso change set governato di
   cablaggio dei consumer prima della sua qualifica. Non cambiare reason code,
   silenziare AUDIT_UNAVAILABLE o usare un fallback volatile per passare i test.

## Impatto e prossima azione

Blocca la qualifica/integrazione di REM-0023 e la ripresa ordinata di 0056;
la chiusura G5 e i gate G6 restano dipendenti. Non blocca la coda indipendente:
REM-0029, ultimo ciclo autorizzato REM-0027 e REM-0031 dopo REM-0028 integrata,
secondo le priorità del PO. Nessun ciclo di riparazione consumato: non è stato
richiesto alcun verdetto. Dopo la disposizione: riprendere il branch WIP,
non riscrivere la storia, cablare i fixture autorizzati, rieseguire tutti i gate
richiesti e la suite completa; poi nuovi record e verifica esterna sull'HEAD esatto.

Inputs intatti; E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED,
PoC/Production NO-GO. Nessun nuovo DEC e nessuna promozione probatoria.
