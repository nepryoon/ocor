# OCOR-DEV-REM-0028 — autorità degli approvatori e tempo

Mandato DEC-210/211, decisione PO `REM-0024-BREAK-GLASS-PRINCIPAL-AUTHORITY`
del 2026-10-13, Q3 con condizione Q1. La matrice normativa, i consumer,
i rami condizionali, i test e i rischi residui sono in `audit.json`.

Il registro reale in-memory fornisce natura, stato e ruoli. Nessun campo
della richiesta o firma scrive questi attributi. L'orologio di Human Gate
appartiene al boundary; il timestamp del reset viene dall'orologio UTC locale.
Il parametro storico `at` resta compatibile ma non decide tempo o validità.
Il reset non eredita ruoli o TTL specifici del break-glass: ADD §5.4–5.5
richiede due approvatori umani e LLD §4.3 richiede un nuovo epoch.

Casi e asserzioni di 0043/0044 conservati uno a uno (prova AST).
Le riqualifiche sono record nuovi con supersessione; i sigilli storici
restano intatti. Il primo writer del registry resta un rischio aperto
assegnato a REM-0031 dalla decisione PO del 2026-10-14.

Implementatore REM-0028: Codex (OpenAI), checkpoint e ripresa del 2026-10-20.
La linea storica delle riqualifiche include Claude Code (Anthropic).
Verifica richiesta a Grok 4.7 (xAI), via Cursor CLI, in processo e contesto
separati avviati soltanto dal loop esterno, secondo LOOP-AGENT-ROTATION.
Nessun verifier è avviato dall’implementatore.

E1=0, E2=0, nessun requisito globalmente Verified; claim NO-GO invariati.
