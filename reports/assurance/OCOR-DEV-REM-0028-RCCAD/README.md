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

## Allineamento per integrazione — 2026-10-21T15:20:57.501373+00:00

Il GO esterno su `89745cf4b962` resta storico. Il merge non distruttivo di main porta il fix dell’osservatore kind di REM-0019, i relativi test e le aggiunte di allowlist: non è un merge solo di metadati. Nuova campagna completa e regressioni sul sorgente `0af64b5c492f7f4572d2fc11df06fe2793e964a1`, nuovi hash e nuova verifica esterna sull’HEAD finale sono obbligatori. Nessun ciclo di riparazione del comportamento REM-0028 consumato; nessun criterio, timer o gate cambiato. Implementatori dichiarati: Codex/OpenAI e Claude Code/Anthropic per la linea ereditata di REM-0019; verifier richiesto Grok 4.7/xAI via Cursor esterno. I sigilli storici restano intatti.
