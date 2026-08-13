# Counsel: Wir bauen 'LoL Clip Lab Local' exakt nach dem beigelegten Spezifikationsdokument. Trefft die zentralen Software- und Design-Entscheidungen VOR dem Bau: Modulschnitt/Paketstruktur, zentrale Datenstrukturen (Timeline, Momente, Gedaechtnis, Stil-Profile), Reihenfolge der Pipeline, LLM-Anbindung (Chunking, JSON-Extraktion, Sanitisierung), Teststrategie fuer 200+ Tests, und die groessten Risiken mit Gegenmassnahmen.

- Datum: 2026-08-13T18:35:05.540Z
- Mitglieder: claude·architekt, claude·backend, claude·llm
- Runden: 2 | Moderator: claude
- Kontext: /root/.claude/uploads/c3882bc8-0222-5c69-86dd-314a5ca6a78b/ce61ff45-AGENT_PROMPT_CLIPLAB_REBUILD.md

# Entscheidungsprotokoll

## Entscheidung
Das Counsel empfiehlt eine Pipeline-orientierte Modulstruktur (12 Module: `ingest`, `transcribe`, `reactions`, `events`, `timeline`, `llm/{client,extract,merge,sanitize,prompts,chunk}`, `memory`, `style`, `rank`, `edl`, `outputs`, `cli`/`pipeline`) mit einem zentralen, abhängigkeitsfreien `model.py` als einziger gemeinsamer Wahrheit für Datenstrukturen und Config. LLM-Anbindung, Persistenz und Sanitisierung werden als strikt getrennte, einzeln testbare Systemgrenzen gebaut, sodass der Großteil der 200+ Tests ganz ohne Subprozesse/Binaries läuft.

## Begründung
- **Testbarkeit zuerst:** Reine Logik an den Pipeline-Rändern von IO (ffmpeg, Subprocess, Dateisystem) zu trennen ist Voraussetzung für „reine Logik ohne echte Binaries testbar" und für die geforderte Fuzz-Testklasse gegen feindliche LLM-Antworten.
- **Klare Import-Regel verhindert Kopplungswildwuchs:** `model.py` ohne Abhängigkeiten; Fachmodule importieren nur von `model.py`, nie voneinander; Orchestrierung ausschließlich über `pipeline.py`/`cli.py`. Das hält 12+ Module über 200 Tests hinweg zyklenfrei und macht Demo-/Real-LLM austauschbar (`LLMClient`-Protocol).
- **Sanitisierung als eigenständige Pflicht-Grenze:** Getrennt von `extract.py` (JSON-Balancierung) und `client.py` (reine Bytes rein/raus), direkt am Extractor-Ausgang angewendet — verhindert, dass z. B. ein `Infinity`-Score das Ranking kontaminiert, bevor er geklemmt wird.
- **Zwei getrennte Dedup-Ebenen bei Gedächtnis/Chunking:** Chunk-Merge (normalisierter Namens-Key für Gags über Session-Pass-Grenzen) und Re-Analyse-Schutz (stabiler VOD-Identitätsschlüssel, „max. 1 Bump pro Gag pro Session") sind unterschiedliche Probleme auf unterschiedlichen Ebenen und müssen getrennte Funktionen bleiben.
- **Atomare Persistenz** (Read-Validate-Merge-Write via Temp-Datei + `os.replace`) mit permissivem Reader macht „korrupte Datei → frisches Gehirn" strukturell statt ad-hoc garantiert.
- **Iterativer Extractor + defensiver Recursion-Guard** erfüllt sowohl die strukturelle Robustheit (kein O(n²), kein RecursionError möglich) als auch die explizite Spec-Invariante (Fehler wird trotzdem abgefangen) — beides, kein Trade-off.

## Verworfene Alternativen
- **Schichten-/Hexagonale Architektur (Domain/Adapter):** verworfen, weil das Spec selbst pipeline-förmig ist und eine zusätzliche Abstraktionsebene die Testisolation je Pipeline-Stufe eher erschwert als erleichtert.
- **Prompts als verstreute f-Strings in `client.py`:** verworfen zugunsten versionierter Prompt-Konstanten in `prompts.py`, da der byte-deterministische Selftest exakt auf den Prompt-Wortlaut angewiesen ist.
- **Ein gemeinsames Zeitfenster-Konzept für Session-Chunking und Moment-Kontext:** verworfen — Zeichen-basiertes Chunking (`llm/chunk.py`) und zeitbasiertes Kandidaten-Kontextfenster (±90s, gehört zu `timeline.py`) haben unterschiedliche Einheiten/Budgets; eine Verschmelzung hätte zu doppelter, inkonsistenter Zeit-zu-Zeichen-Umrechnung geführt.
- **Eine einzige Memory-Dedup-Funktion für Gag-Merge und Re-Analyse-Schutz:** verworfen, da das genau die Pflicht-Invariante „max. 1 Bump pro Gag pro Session" gefährdet hätte.
- **Rekursiver JSON-Balance-Scanner mit reinem Try/Except gegen RecursionError:** verworfen zugunsten eines iterativen Stack-Scanners, ergänzt um zusätzlichen defensiven Guard.

## Risiken & offene Fragen
- **Sanitize als Flaschenhals-Modul:** Wenn Validierungslogik doch über die Codebase versickert statt zentral in `sanitize.py` zu bleiben, werden die geforderten Fuzz-Tests unvollständig bzw. widersprüchlich. Gegenmaßnahme: Sanitize-Aufruf als dokumentierte Pipeline-Invariante direkt am Extractor-Ausgang, mit eigener Testklasse gegen feindliche Inputs.
- **Windows-Executable-Auflösung (`shutil.which`, `.cmd`-Shims):** Diskrepanz zwischen `doctor`-Diagnose und tatsächlichem Lauf ist ein reales Risiko bei PATH-Reihenfolge-Eigenheiten. Gegenmaßnahme: gemeinsamer `resolve_executable()` in `llm/client.py`, von `doctor` und `cli.py` gleichermaßen genutzt — im Diskussionsverlauf vorgeschlagen, aber noch nicht gegen reale Windows-PATH-Fälle getestet.
- **Zweit-Gehirn-Blend-Nebenläufigkeit:** Halb geblendete Ergebnisse bei Timeout der Zweit-CLI sind ein Idempotenz-Risiko. Gegenmaßnahme (Konsens, ungetestet): Schreibsperre bis Blend abgeschlossen/timeout, Fehlschlag der Zweit-CLI nur auf Subprocess-Ebene abgefangen.
- **Offen:** Kein Rollenmitglied hat die exakte Grenze zwischen `timeline.py` (Kontext-Sampling) und `llm/chunk.py` (Zeichen-Chunking) mit konkretem Interface spezifiziert — das bleibt vor Implementierungsbeginn zu klären.
- **Offen:** Die konkrete Teststrategie für 200+ Tests wurde nur als Prinzip (tabellarisch/parametrisiert statt 200 Einzelfunktionen) benannt, nicht in Testfall-Kategorien mit Zielzahlen heruntergebrochen.

## Nächste Schritte
1. `model.py` mit frozen dataclasses (`TimelineDoc`, `Candidate`, `Moment`, `MemoryState`, `StyleProfile`) und validiertem Config-Typ anlegen — als erste, abhängigkeitsfreie Grundlage.
2. `llm/`-Untermodule (`client`, `extract`, `merge`, `chunk`, `sanitize`, `prompts`) mit `LLMClient`-Protocol (Demo/Real austauschbar) implementieren, iterativer Extractor mit defensivem Recursion-Guard zuerst, da er die Fuzz-Tests entsperrt.
3. `memory.py` mit atomarer Read-Validate-Merge-Write-Persistenz und den zwei getrennten Dedup-Funktionen (`merge_gags_by_name`, `should_bump_counter`) bauen.
4. Import-Regel (nur Richtung `model.py`, Orchestrierung über `pipeline.py`) als Lint-/Test-Check (z. B. einfacher Importgraph-Test) von Anfang an durchsetzen, nicht erst am Ende prüfen.
5. `resolve_executable()` in `client.py` implementieren und in `doctor` sowie `cli.py` wiederverwenden.
6. Feindliche-LLM-Antworten-Testklasse (Infinity, null-Listen, Nicht-Strings, Klammer-Fluten, tiefes Nesting, Kommas/Pfadzeichen) als erste große Testfläche gegen `sanitize.py`/`extract.py` schreiben, sobald diese Module stehen.
7. Selftest-Pfad (kanned Demo-LLM, zwei Sessions gegen Scratch-Gedächtnis) früh aufsetzen, um Determinismus fortlaufend gegen echte Implementierung zu verifizieren.

## Dissens
Keiner — alle drei Rollen (architekt, backend, llm) haben in Runde 2 explizit vollständigen Konsens erklärt; die einzige Nicht-Übereinstimmung (rekursiv abgesicherter vs. iterativer Extractor) wurde als „beides, kein Widerspruch" aufgelöst.

# Diskussionsverlauf

## claude·architekt — Runde 1

## Architektur-Perspektive

**Modulschnitt:** Ich würde NICHT nach Schichten (Domain/Adapter/Hexagonal) bauen, sondern nach Pipeline-Stufen – das Spec ist selbst pipeline-förmig, und 200+ Tests brauchen isolierbare Einheiten: `ingest.py`, `transcribe.py`, `reactions.py`, `events.py`, `timeline.py`, `llm/{client,extract,sanitize,prompts}.py`, `memory.py`, `style.py`, `rank.py`, `edl.py`, `outputs.py`, `cli.py`. Jede Stufe: reine Funktion, IO (ffmpeg-Aufruf, Datei-Read) nur an den Rändern, injizierbar. Das ist Voraussetzung für die geforderte „reine Logik ohne echte Binaries testbar".

**Zentrale Datenstrukturen:** Ein gemeinsames `model.py` mit frozen dataclasses (`TimelineDoc`, `Candidate`, `Moment`, `MemoryState`, `StyleProfile`) – als einzige Wahrheit, die alle Stufen durchreichen. Wichtig: `sanitize.py` als EIGENES Modul getrennt von `extract.py` (JSON-Balancierung) und `client.py` (CLI-Spawn) – das Spec verlangt eine ganze Testklasse „feindliche LLM-Antworten", die muss gegen sanitize.py laufen können, ohne CLI/Netz zu berühren.

**Reihenfolge:** Trotz „frei optimierbar" gibt es harte Abhängigkeiten: Gedächtnis muss VOR beiden LLM-Pässen geladen sein (Injection), Stil-Profile müssen vor dem Moment-Pass existieren (CUT-Stile im Prompt). Ranking erst nach Moment-Matching, EDL erst nach Ranking.

**Größtes Risiko aus Architektursicht:** Die Sanitisierung wird zum Flaschenhals-Modul, das von JEDEM LLM-Feld durchlaufen wird – wenn das nicht als eigenständige, gut typisierte Grenze existiert, versickert Validierungslogik über die Codebase und die Fuzz-Tests werden unmöglich sauber zu schreiben.

Vorläufige Empfehlung: Pipeline-Module + zentrales `model.py` + strikt getrenntes `llm/sanitize.py`. Bin gespannt, wie backend das aus Testbarkeits-/Performance-Sicht sieht.

## claude·backend — Runde 1

Zustimmung zu Pipeline-Module + zentrales `model.py` + separates `sanitize.py` – das deckt sich mit meiner Sicht auf Testbarkeit. Ergänzungen aus Backend-Perspektive:

**Persistenz (Gedächtnis/Profile):** Das sind die einzigen zustandsbehafteten Dateien im System – hier drohen die fiesesten Bugs. Ich würde `memory.py` strikt nach *Read-Validate-Merge-Write-atomic* strukturieren: Laden über ein permissives Schema (alles Unbekannte/Falschgetypte wird verworfen, nie geworfen), Schreiben via Temp-Datei + `os.replace` (Windows-tauglich, kein halbgeschriebenes JSON bei Absturz). Die Invariante „keine Doppelzählung bei Re-Analyse" verlangt einen stabilen VOD-Identitätsschlüssel (Dateiname laut Spec) als Dedup-Key im Memory-Objekt selbst – das gehört ins Datenmodell, nicht als Zusatzlogik in der CLI.

**LLM-Anbindung als Systemgrenze:** `client.py` sollte Subprocess-Aufruf, Timeout und Executable-Resolution (shutil.which, Windows .cmd) kapseln und NICHTS über Inhalte wissen – reine Bytes rein/raus. Trennung zu `extract.py` (Klammer-Balancierung) ist richtig, ich würde zusätzlich einen harten Zeichen-/Iterationsdeckel im Extractor einziehen (Spec verlangt kein O(n²) bei Klammerfluten) – das ist eine Performance- UND eine DoS-ähnliche Robustheitsanforderung, gehört als expliziter Test mit synthetisch pathologischem Input.

**Sicherheit:** Pfad-Traversal bei Style-Slugs/Kategorie-Slugs und bei `fetch` (yt-dlp `--`-Trenner) sind klassische Injection-Flächen – dafür jeweils eigene Sanitizer-Unittests, nicht nur Blackbox.

**Teststrategie 200+:** Ich würde Property-based-ähnliche Tabellen für Sanitizer/Extractor fahren (viele kleine parametrisierte Fälle statt 200 Einzelfunktionen), reale Subprozesse nie in Unit-Tests – nur in optionalen ffmpeg-Integrationstests.

**Empfehlung:** Architektur von architekt übernehmen, `memory.py`/`style.py` explizit als „atomare Persistenz mit permissivem Reader" spezifizieren.

## claude·llm — Runde 1

Zustimmung zu Pipeline-Module, `model.py`, striktem `sanitize.py`, atomarer Persistenz. Ein paar Punkte aus LLM-Integrations-Sicht ergänzen und einen leichten Widerspruch:

**Widerspruch zu architekt:** Ranking „erst nach Moment-Matching" stimmt, aber die Reihenfolge Session-Pass → Moment-Pass ist selbst eine harte Abhängigkeit, die ins Pipeline-Diagramm gehört – Session-Pass liefert `running_gags`/`callbacks`, die als Kontext in den Moment-Pass injiziert werden (für `lore_refs`, `callback_refs`). Das ist kein Detail, sondern bestimmt Chunking-Design: der Moment-Pass braucht bereits konsolidierte Gag-Namen, sonst matcht das LLM gegen sich selbst widersprechende Bezeichnungen über Chunk-Grenzen hinweg.

**Chunking konkret:** Zeilen-alignierte ~150k-Zeichen-Chunks mit gemergten Vorfunden verlangen eine explizite Dedup-Strategie im Datenmodell – ich würde `running_gags`/`callbacks` über einen normalisierten Namens-Key (lowercase, whitespace-collapsed) mergen, nicht über exakten String-Match, sonst entstehen Duplikate durch minimale LLM-Formulierungsvarianz zwischen Chunks. Das gehört als eigene, gut getestete Funktion in `llm/merge.py`, nicht verstreut in `client.py`.

**Extraktion:** Balancierter Top-Level-JSON-Scan sollte ein Zeichen-Budget UND einen Klammertiefen-Deckel haben (RecursionError kommt typischerweise aus rekursivem Parsing, nicht aus dem Scan selbst – also: iterativer Stack-Scanner, kein rekursiver Abstieg, dann ist RecursionError strukturell ausgeschlossen statt nur abgefangen).

**Determinismus/Tests:** Der „kanned Demo-LLM" für selftest sollte als austauschbare `LLMClient`-Implementierung hinter derselben Schnittstelle wie die echte CLI leben (Protocol/ABC) – dann testen 150+ der 200 Tests ausschließlich gegen sanitize/extract/merge mit handgeschriebenen feindlichen Fixtures, ganz ohne Subprocess-Mocking.

**Empfehlung:** architekt+backend übernehmen, zusätzlich `llm/merge.py` als eigenes Modul, iterativer (nicht rekursiver) Extractor, `LLMClient`-Protocol für Demo/Real-Austauschbarkeit.

## claude·architekt — Runde 2

Zustimmung zu fast allem: Pipeline-Module, `model.py`, atomare Persistenz, `llm/merge.py`, iterativer Extractor, `LLMClient`-Protocol. Aus Architektursicht drei Ergänzungen und ein Einwand:

**Einwand zu llm:** Der iterative Stack-Scanner für den Extractor ist richtig, aber „RecursionError abgefangen" steht explizit im Spec – ich würde ihn trotzdem defensiv abfangen, auch wenn strukturell ausgeschlossen. Architektur-Prinzip: Invarianten aus dem Spec werden nicht durch Implementierungsdetails ersetzt, sondern zusätzlich abgesichert – ein künftiger Refactor darf die Garantie nicht stillschweigend verlieren. Kein Widerspruch in der Sache, nur: beides, nicht entweder-oder.

**Übersehen – Modul-Abhängigkeitsrichtung:** Bei 12+ Modulen brauchen wir eine explizite Schichtregel, sonst wächst über 200 Tests hinweg ein Zyklus. Ich schlage vor: `model.py` hat keine Abhängigkeiten; `llm/*` und `memory.py`/`style.py` dürfen nur von `model.py` importieren, nie voneinander (Kopplung nur über `pipeline.py`/`cli.py` als Orchestrator). Das erzwingt genau die von backend geforderte Austauschbarkeit und verhindert, dass z.B. `rank.py` heimlich `memory.py`-Interna kennt.

**Übersehen – Konfigurationsobjekt:** Config (Kanäle, Gewichte, Chunk-Größe, Host-Namen) sollte als eigener, validierter dataclass-Typ in `model.py` landen statt als loses dict, das durch alle Module gereicht wird – sonst wird „kaputte Config → Defaults" an zig Stellen einzeln implementiert statt einmal beim Parsen.

**Konsensvorschlag (final):** Pipeline-Module (12, wie oben) + zentrales `model.py` (inkl. Config-Typ) als einzige gemeinsame Abhängigkeit + strikt getrenntes `llm/{client,extract,merge,sanitize,prompts}.py` + `LLMClient`-Protocol für Demo/Real + atomare Read-Validate-Merge-Write-Persistenz in `memory.py`/`style.py` + iterativer Extractor mit zusätzlichem defensivem Recursion-Guard + Import-Regel „nur Richtung `model.py`, Orchestrierung über `pipeline.py`". Kein verbleibender Dissens in der Sache – nur die eine Präzisierung oben (beides statt entweder-oder beim Extractor).

## claude·backend — Runde 2

Zustimmung zum Konsensvorschlag von architekt (Import-Regel, Config-Typ, iterativer Extractor + defensiver Guard). Aus Backend-Sicht drei Ergänzungen, kein Widerspruch in der Sache:

**Persistenz-Präzisierung zu llm's Dedup-Vorschlag:** Der normalisierte Namens-Key für Gag-Merging ist richtig für den Session-Pass, aber F6 verlangt zusätzlich einen *stabilen VOD-Identitätsschlüssel* fürs Re-Analyse-Invariant – das ist ein anderer Key auf einer anderen Ebene (Memory-Datei, nicht Chunk-Merge). Ich würde `memory.py` zwei getrennte Dedup-Funktionen geben: `merge_gags_by_name()` (llm/merge.py-Ausgabe konsolidieren) und `should_bump_counter(vod_id, session_seen)` (Re-Analyse-Schutz). Beide in einer Funktion zu verschmelzen wäre der Bug, der die Pflicht-Invariante "max. 1 Bump pro Gag pro Session" kaputt macht.

**Übersehen – Zweit-Gehirn (F9) als Nebenläufigkeits-/Idempotenz-Frage:** Der Blend-Prozess (Primär+Zweit) ist reine Post-Processing-Logik, sollte aber explizit NICHT in `memory.py` oder `rank.py` schreiben dürfen, bevor der Blend fertig ist – sonst persistiert ein halb geblendetes Ergebnis bei Timeout der Zweit-CLI. Zweit-CLI-Aufruf braucht denselben Timeout-Schutz wie Primär, aber ihr Fehlschlag darf den Gesamtlauf nie blockieren (try/except auf Subprocess-Ebene, nicht auf Pipeline-Ebene).

**Betrieb:** `doctor` und `selftest` sollten denselben Executable-Resolver (`shutil.which`) wie `client.py` nutzen – sonst diagnostiziert doctor "claude gefunden", während der echte Lauf eine andere .cmd-Shim-Auflösung trifft (Windows PATH-Reihenfolge). Ein gemeinsames `resolve_executable()` in `llm/client.py`, von `cli.py` importiert.

**Finale Empfehlung:** Konsens von architekt übernehmen, ergänzt um: zwei getrennte Memory-Dedup-Funktionen (Chunk-Merge vs. Re-Analyse-Schutz), Blend-Schreibschutz bis Zweit-CLI abgeschlossen/timeout, gemeinsamer `resolve_executable()` für doctor/client. Kein verbleibender Dissens – die drei Punkte sind additiv, nicht widersprüchlich zu Runde 2.

## claude·llm — Runde 2

Zustimmung zum Konsens von architekt (Import-Regel, Config-Typ, `LLMClient`-Protocol, iterativer Extractor + defensiver Guard) und zu backends drei Ergänzungen (getrennte Dedup-Funktionen, Blend-Schreibschutz, gemeinsamer `resolve_executable()`). Kein Widerspruch in der Sache – vier Präzisierungen aus LLM-Sicht, die die Teststrategie direkt betreffen:

**Prompt-Versionierung:** `prompts.py` sollte Prompt-Templates als versionierte Konstanten mit eingebettetem Schema-Beispiel führen, nicht als f-Strings verstreut über `client.py`-Aufrufe. Grund: Der Selftest-Determinismus (F15, byte-deterministisch) verlangt, dass der Demo-LLM exakt auf den Prompt-Wortlaut reagieren kann – wenn Prompts sich implizit ändern, bricht das lautlos.

**Chunk-Grenzen und Kandidaten-Kontext sind zwei verschiedene Fenster-Konzepte**, die im Datenmodell nicht verschmelzen dürfen: Session-Pass-Chunking (150k Zeichen, zeilen-aligniert) und Moment-Pass-Kontextfenster (±90s um Kandidaten + Stichprobe) haben unterschiedliche Einheiten (Zeichen vs. Zeit) und unterschiedliche Budgets. Ich würde `llm/chunk.py` (zeichenbasiert, Session-Pass) von der Kontext-Sampling-Logik im Moment-Pass (die eher zu `timeline.py` gehört, weil sie Zeit-Indizes braucht) trennen – sonst landet Zeit-zu-Zeichen-Umrechnung doppelt und inkonsistent in beiden Pfaden.

**Sanitize-Reihenfolge:** Zahlen-Klemmung (Infinity/NaN) muss VOR jeder Vergleichs-/Sortierlogik laufen, nicht erst beim Output – sonst kann ein `Infinity`-Score bereits das Ranking (F10) kontaminieren, bevor `sanitize.py` greift. Das bedeutet: Sanitize direkt am `extract.py`-Ausgang, nicht erst am `outputs.py`-Eingang. Das sollte explizit als Pipeline-Invariante dokumentiert werden, nicht nur als Modul-Existenz.

**Ergänzung zu backends Blend-Punkt (F9):** Die Zweit-CLI nutzt denselben `LLMClient`, daher gilt derselbe Extract/Sanitize-Pfad automatisch – kein separater Sanitizer nötig, nur sicherstellen, dass Blend NACH Sanitize beider Seiten läuft.

**Finale Empfehlung (Konsens):** Ich schließe mich dem vollständigen Konsens aus Runde 2 an, ergänzt um: versionierte Prompt-Konstanten, `chunk.py` (Zeichen) getrennt von zeitbasiertem Kandidaten-Kontext-Sampling, Sanitize direkt am Extractor-Ausgang als dokumentierte Pipeline-Invariante. Kein verbleibender Dissens zwischen den drei Rollen.
