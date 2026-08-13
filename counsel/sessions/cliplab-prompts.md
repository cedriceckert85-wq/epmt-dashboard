# Counsel: Entwerft die LLM-Prompts, die 'LoL Clip Lab Local' (Spezifikation im Kontext) zur Laufzeit per stdin an die claude-CLI schickt: (1) Session-Pass (liest Timeline-Chunks, findet running_gags/callbacks/arcs/notes, merged ueber Chunk-Grenzen), (2) Moment-Pass (bewertet Kandidaten mit Log-Kontext, entdeckt eigene Momente, liefert t0/t1/Kategorie/Score/punchline_t/Titel/Begruendung/style/channels/callback_refs/lore_refs/captions/zooms/sfx), (3) Gedaechtnis-Konsolidierung (bekannte Gags nach Bedeutung hochzaehlen statt duplizieren), (4) Stil-Destillation (aus Referenz-Fingerprints CUT-Stil-Profile destillieren). Diskutiert je Prompt: Aufbau und Reihenfolge der Abschnitte, exaktes JSON-Ausgabeschema, wie Robustheit gegen geschwaetzige/kaputte Antworten schon im Prompt unterstuetzt wird, Sprach-/Host-Anweisungen, und was NICHT hinein soll. Zitiert in euren Beitraegen konkrete Prompt-Formulierungen und Schema-Snippets — dafuer duerft ihr das Wortlimit ueberschreiten.

- Datum: 2026-08-13T21:30:17.736Z
- Mitglieder: claude·prompt, claude·editorial
- Runden: 3 | Moderator: claude
- Kontext: /root/.claude/uploads/c3882bc8-0222-5c69-86dd-314a5ca6a78b/ce61ff45-AGENT_PROMPT_CLIPLAB_REBUILD.md

# Ergebnis

# Finale LLM-Prompts — LoL Clip Lab Local

Alle vier Prompts folgen dem im Counsel abgestimmten Grundgerüst: **Rolle → Hosts/Sprache → Gedächtnis → (Kategorie-Definitionen, nur Moment-Pass) → Daten → Schema mit Format-Kommentaren → Kürze-Priorität → „Nur JSON"-Schlusssatz.** Platzhalter in `{geschweiften_klammern}` werden zur Laufzeit ersetzt.

---

## 1) Session-Pass

```
Du bist Editorial-Analyst für einen deutschsprachigen League-of-Legends-Stream.
Du liest ein Timeline-Transkript und findest wiederkehrende Gags, Callbacks
(Setup + späterer Payoff), Handlungsbögen (Arcs) und sonstige Notizen für
spätere Clip-Auswahl. Du triffst hier KEINE Clip-Entscheidungen — nur
Struktur-Erkennung im Gesamtverlauf.

HOSTS: {host_namen}
Ordne Gags/Callbacks dem richtigen Host zu, wenn erkennbar (z. B. im
"description"-Feld erwähnen wer den Gag trägt). Rate nicht bei Unsicherheit.

SPRACHE: Titel, Namen und Beschreibungen in der Sprache der Streamer im
Transkript. {sprache_erzwungen_hinweis}

BEKANNTES GEDÄCHTNIS (aus früheren Sessions, kompakt):
{memory_block}
Wiedererkannte Gags aus dem Gedächtnis: verwende deren "id" weiter, lege
KEINE neue an. Ein Gag, der hier auftaucht, aber im Gedächtnis fehlt, ist neu.

Du erhältst Chunk {chunk_index}/{chunk_total} eines langen Transkripts.
Die Liste "bisherige_funde" enthält Gags/Callbacks/Arcs aus früheren Chunks
DIESER Session:
{bisherige_funde}

REGELN FÜR DIE AKTUALISIERUNG (verbindlich):
- Gib die VOLLSTÄNDIGE, aktualisierte Liste zurück — keine Deltas. Bereits
  bekannte Einträge fortschreiben (z. B. payoff_t ergänzen), neue anhängen.
- Wenn ein Eintrag aus "bisherige_funde" zum selben Gag/Callback/Arc gehört,
  den du gerade aktualisierst, VERWENDE DESSEN id UNVERÄNDERT weiter. Vergib
  eine neue id nur für tatsächlich neue Gags/Callbacks/Arcs.
- Einträge aus "bisherige_funde", die im aktuellen Chunk NICHT erwähnt
  werden, bleiben UNVERÄNDERT in der Ausgabe — nicht löschen, nicht
  vermuten dass sie beendet sind. Ein Gag, der einen Chunk pausiert, ist
  kein beendeter Gag.
- Max. {max_running_gags} running_gags — wichtigste zuerst, wenn mehr
  gefunden werden fasse ähnliche zusammen statt zu kappen.
- Ein Callback braucht ZWEI unterschiedliche Zeitpunkte: setup_t (wo der
  Gag zuerst etabliert wird) und payoff_t (wo er wieder aufgegriffen wird).
  Wenn du einen Payoff erkennst, suche im BISHERIGEN Transkript (auch aus
  früheren Chunks, über "bisherige_funde" oder deine eigene Erinnerung an
  vorige Chunks) nach dem Setup zurück. Rate NICHT — wenn du kein
  belastbares Setup findest, gehört der Fund in "notes", nicht in
  "callbacks".

TRANSKRIPT-CHUNK:
{timeline_chunk}

AUFGABE: Extrahiere/aktualisiere running_gags, callbacks, arcs, notes für
diesen gesamten Kontext (bisherige Funde + aktueller Chunk).

AUSGABESCHEMA (exakt, sonst nichts):
{
  "running_gags": [
    {
      "id": "string, stabiler slug, z.B. \"stolper_gag\"",
      "name": "kurzer Spitzname (2-4 Wörter), wie die Streamer den Gag selbst nennen würden oder nennen sollten — KEINE Beschreibung des Ereignisses",
      "first_t": 0.0,
      "description": "1 Satz, Details des Gags"
    }
  ],
  "callbacks": [
    {
      "setup_t": 0.0,
      "payoff_t": 0.0,
      "description": "1 Satz, was Setup und Payoff verbindet"
    }
  ],
  "arcs": [
    {
      "name": "kurzer Name",
      "start_t": 0.0,
      "end_t": 0.0,
      "description": "1 Satz"
    }
  ],
  "notes": ["freie Stichpunkte zu Beobachtungen ohne festen Platz oben, z.B. vermutete aber unbestätigte Callbacks"]
}

// alle Zeit-Felder (first_t, setup_t, payoff_t, start_t, end_t): Sekunden
// als Zahl (float), relativ zum VOD-Start, NIE "MM:SS"-Strings.
// Leere Kategorien als [] zurückgeben, NIE null.

Antworte NUR mit dem JSON-Objekt. Kein Markdown-Codeblock, kein Vorspann,
kein Nachwort.
```

**Einsatz-Hinweise:**
- Wird einmal pro Chunk aufgerufen (~150k Zeichen, konfigurierbar, zeilen-aligniert), bei Chunk 1 ist `bisherige_funde` eine leere Struktur (`{"running_gags":[],"callbacks":[],"arcs":[],"notes":[]}`), NIEMALS `null` oder weggelassen.
- `memory_block` kommt aus F6 (Kanal-Gedächtnis) und bleibt über alle Chunks derselben Session identisch — nicht pro Chunk neu befüllen.
- Sanitizer muss: `id` als pfadsicheren Slug erzwingen (auch wenn das Modell Leerzeichen/Sonderzeichen liefert), Dedup nach `id` bei identischen Objekten aus konsekutiven Chunk-Antworten, Zeit-Felder auf endliche Zahlen klemmen, `notes` auf String-Liste beschränkt (keine Objekte).

---

## 2) Moment-Pass

```
Du bist Editorial-Analyst für einen deutschsprachigen League-of-Legends-Stream
mit drei Kanälen. Du bewertest Kandidaten-Momente für Kurz-Clips UND darfst
eigene Momente entdecken, die keinen Game-Event-Kandidaten haben.

HOSTS: {host_namen}
Ordne Gags/Pointen dem richtigen Host zu, wo erkennbar.

SPRACHE: title, reasoning und Caption-Texte in der Sprache der Streamer.
{sprache_erzwungen_hinweis}

BEKANNTES GEDÄCHTNIS (Running Gags/Catchphrases/Lore aus früheren Sessions):
{memory_block}
Erkennst du einen Moment als Fortsetzung eines bekannten Gags, trage dessen
id in "lore_refs" ein. Wenn du unsicher bist, ob eine ID passt, LASS DEN
VERWEIS WEG statt zu raten. Ein fehlender Lore-Verweis kostet uns eine Zeile
im Sheet. Ein erfundener Verweis kostet uns das Vertrauen der Editoren in
ALLE Lore-Verweise.

KATEGORIEN (wähle die naheliegendste, nicht die extremste):
- "punchline": pointierter Wortwitz mit klarem Vorher/Nachher
- "chaos": eskalierende Situation ohne einzelne Pointe
- "outplay": Skill-Moment, Reaktion ist Bewunderung nicht Lachen
- "callback": Gag-Wiederaufnahme — erfordert MINDESTENS einen Eintrag in
  callback_refs. Ohne callback_refs wähle eine andere Kategorie.

STYLE-TAGS — "style" MUSS einer dieser Werte sein, sonst leerer String "":
{stil_liste}

KANÄLE — "channels" MUSS eine Teilmenge dieser Namen sein:
{kanal_liste}

KANDIDATEN mit vollem Log-Kontext (±90s um den jeweiligen Zeitpunkt):
{kandidaten}

STICHPROBE des restlichen Transkripts (für eigene Funde ohne Game-Event):
{stichprobe}
Eigene Funde in der Stichprobe unterliegen denselben Kategorie- und
Score-Maßstäben wie die Kandidaten. Auffälliges Transkript (Großschreibung,
Ausrufezeichen, Länge) ist KEIN Signal für Clip-Würdigkeit — bewerte den
Inhalt, nicht die Textoberfläche.

SCHNITTFENSTER (t0/t1):
t0 = frühester Punkt, an dem ein Zuschauer OHNE Vorwissen die Pointe
versteht — nicht der früheste Punkt, an dem das Thema beginnt. Wenn Setup
und Pointe mehr als ~20s auseinanderliegen, prüfe ob ein kürzeres t0
möglich ist, das trotzdem verständlich bleibt.
punchline_t MUSS im Intervall [t0, t1] liegen. Wenn die eigentliche Pointe
außerhalb deines gewählten Fensters liegt, korrigiere t0/t1 statt
punchline_t zu verschieben.

CAPTIONS/ZOOMS/SFX: sparsam setzen, primär auf punchline_t, max. 1-2
zusätzliche auf klare Sekundärmomente. Kein Overlay-Teppich über den
ganzen Clip.

AUSGABESCHEMA (exakt, sonst nichts):
{
  "moments": [
    {
      "t0": 0.0,
      "t1": 0.0,
      "category": "punchline | chaos | outplay | callback",
      "score": 0,
      "punchline_t": 0.0,
      "title": "max. 8 Wörter, ein Satz, keine Zeilenumbrüche/Anführungszeichen",
      "reasoning": "max. 30 Wörter, Struktur: \"<Warum clip-würdig>. <Bezug falls callback/lore>.\" Kein Fließtext-Fazit.",
      "style": "einer aus stil_liste oder \"\"",
      "channels": ["teilmenge von kanal_liste"],
      "callback_refs": ["gag_id, nur bekannte IDs"],
      "lore_refs": ["gag_id, nur bekannte IDs"],
      "captions": [{"t": 0.0, "text": "kurz, ein Satz"}],
      "zooms": [{"t": 0.0, "duration": 0.0}],
      "sfx": [{"t": 0.0, "kind": "kurzes Schlagwort, z.B. \"airhorn\""}]
    }
  ]
}

// alle Zeit-Felder (t0, t1, punchline_t, captions[].t, zooms[].t, sfx[].t):
// Sekunden als Zahl (float), relativ zum VOD-Start, NIE "MM:SS"-Strings.
// score: ganze Zahl 0-10.
// Leere Arrays (callback_refs, lore_refs, captions, zooms, sfx) als [],
// NIE null.

PRIORITÄT BEI KNAPPEM PLATZ: Gib ALLEN Kandidaten ein vollständiges,
valides JSON-Objekt zurück. Ein vollständiges JSON mit knappen Feldern hat
IMMER Priorität vor ausführlichen Feldern. Wenn du bei vielen Kandidaten
Platz sparen musst, kürze zuerst Freitext-Felder (title, reasoning,
Caption-Texte) — NIE Timecodes, NIE Pflichtfelder, NIE die Anzahl der
zurückgegebenen Kandidaten.

Antworte NUR mit dem JSON-Objekt. Kein Markdown-Codeblock, kein Vorspann,
kein Nachwort.
```

**Einsatz-Hinweise:**
- `kandidaten` enthält für jeden Signal-Kandidaten den vollen Transkript-Kontext ±90s; `stichprobe` ist die gleichmäßige Restsample-Auswahl innerhalb des Token-Budgets — kein Kandidat darf seinen ±90s-Kontext verlieren, auch nicht späte/sparse bei knappem Budget (das ist Aufrufer-Logik, nicht Prompt-Logik, aber die Reihenfolge im Prompt sollte Kandidaten vor Stichprobe halten, damit Truncation zuerst die Stichprobe kappt).
- Sanitizer MUSS trotz Prompt-Bitte hart durchsetzen: `punchline_t = clamp(punchline_t, t0, t1)`, `style`/`channels` gegen die bekannten Mengen filtern (nicht nur warnen), `callback_refs`/`lore_refs` gegen bekannte IDs filtern, `category=="callback"` ohne `callback_refs` auf nächstpassende Kategorie umbiegen oder Score-Penalty statt Crash.
- Bei Zweitmeinung (F9) wird dieser Prompt identisch an die zweite CLI geschickt — `memory_block`/`stil_liste`/`kanal_liste` müssen exakt dieselben Werte wie beim Primär-Aufruf sein, sonst sind die Bewertungen nicht vergleichbar.

---

## 3) Gedächtnis-Konsolidierung

```
Du pflegst das Langzeit-Gedächtnis eines League-of-Legends-Streamer-Duos.
Du entscheidest NICHT über neue Inhalte — du ordnest nur zu, welche in
dieser Session erkannten Gags bereits bekannte Gags aus dem Gedächtnis
sind (dann hochzählen) und welche mehrfach benannten Einträge derselben
Session eigentlich derselbe Gag sind (dann zusammenführen).

BEKANNTE GAGS AUS DEM GEDÄCHTNIS (id, name, description, times_seen):
{known_gags}

IN DIESER SESSION ALS LORE ERKANNTE VERWEISE (aus dem Moment-Pass,
lore_refs, sowie Session-Pass running_gags dieser Session):
{new_lore_hits}

AUFGABE:
- "bumped": Liste der ids aus known_gags, die in dieser Session
  nachweislich wieder aufgetreten sind (via lore_refs oder erneut
  erkanntem running_gag). Jede id MAX. EINMAL in der Liste, auch wenn sie
  mehrfach in der Session auftrat — ein Bump pro Gag pro Session.
- "merged": Fälle, in denen zwei oder mehr ids (aus known_gags oder neu in
  dieser Session vergebene ids) denselben Gag beschreiben. "into" = die id,
  die bestehen bleibt (bevorzugt die ältere/bekanntere aus known_gags),
  "from" = die id(s), die darin aufgehen.

Erfinde KEINE neuen Gags und ändere KEINE Namen/Beschreibungen — das ist
nicht deine Aufgabe hier. Wenn du unsicher bist, ob zwei Gags identisch
sind, NICHT mergen — lieber getrennt lassen als fälschlich zusammenlegen.

AUSGABESCHEMA (exakt, sonst nichts):
{
  "bumped": ["gag_id", "..."],
  "merged": [
    {"into": "gag_id", "from": ["gag_id2", "gag_id3"]}
  ]
}

// Nur IDs, keine vollständigen Gag-Objekte. Leere Arrays als [], NIE null.

Antworte NUR mit dem JSON-Objekt. Kein Markdown-Codeblock, kein Vorspann,
kein Nachwort.
```

**Einsatz-Hinweise:**
- Wird EINMAL nach Abschluss beider LLM-Pässe pro Session aufgerufen, ausschließlich mit dem Primär-Gehirn (F9: Zweit-CLI bleibt hier außen vor).
- Deterministischer mechanischer Fallback (bei fehlender LLM-CLI oder Müll-Antwort) muss exakt dasselbe Ausgabeformat erzeugen: reines ID-Matching zwischen `lore_refs`/erkannten `running_gags`-ids und `known_gags`-ids für `bumped`, kein `merged` (Merge-Erkennung ohne LLM ist zu unsicher, leer lassen).
- Re-Analyse derselben VOD darf laut Spezifikation KEINE Zähler erhöhen — das muss VOR diesem Prompt-Aufruf geprüft werden (VOD-Name gegen bereits verarbeitete Sessions im Gedächtnis), nicht im Prompt selbst, da das Modell diese Prüfung nicht zuverlässig leisten kann.

---

## 4) Stil-Destillation

```
Du analysierst Referenz-Clips, um daraus einen wiederverwendbaren
Schnitt-Stil für kurze Highlight-Clips (CUT-Stil) zu destillieren. Du
bekommst pro Stil mehrere Fingerprints (technische Messwerte + kurze
Transkript-Proben) echter Beispiel-Clips desselben Stils.

Destilliere NUR die CUT-Stile, die dir unten mit Fingerprint-Daten
übergeben werden — erfinde keine Werte für Formate ohne Daten und
erfinde keine zusätzlichen Stile, die nicht in der Eingabe vorkommen.

FINGERPRINTS (pro Stil: Liste von {duration_s, cuts_per_min,
transcript_sample}):
{fingerprints}

Für jeden Stil destilliere:
- ideal_clip_s: typische/mediane Ziellänge in Sekunden für diesen Stil,
  basierend auf den gemessenen duration_s-Werten — kein erfundener Wert,
  wenn die Messungen stark streuen nimm den Median und sag das implizit
  über eine engere/weitere Einschätzung in pace nicht in der Zahl.
- pace: kurze Einschätzung des Schnitt-Tempos (z.B. "schnell, viele kurze
  Cuts" oder "wenige lange Einstellungen") basierend auf cuts_per_min.
  0 cuts/min ist eine valide Messung ("lange ungeschnittene Takes") —
  behandle sie nicht als fehlende Daten.
- humor_notes: 3-5 kurze, semikolon-getrennte Stichpunkte zu konkreten
  wiederkehrenden Mustern (Wortspiel-Dichte, Ton-Wechsel, Break-Charakter),
  KEINE Stilkritik, KEIN Fließtext-Absatz.
- caption_style: kurze Einschätzung, wie/ob Text auf dem Bild eingesetzt
  wird, basierend auf den Transkript-Proben (falls erkennbar), sonst "".

AUSGABESCHEMA (exakt, sonst nichts):
{
  "styles": {
    "<style_name>": {
      "ideal_clip_s": 0.0,
      "pace": "kurzer Satz",
      "humor_notes": "3-5 Stichpunkte, semikolon-getrennt",
      "caption_style": "kurzer Satz oder leer"
    }
  }
}

// style_name-Schlüssel MÜSSEN exakt den Stilnamen aus den Fingerprints
// übernehmen (z.B. "insta_funny"), keine Umbenennung/Übersetzung.
// ideal_clip_s als Zahl (float), Obergrenze ~90s beachten falls die
// Messwerte darüber liegen — nenne den gemessenen Median trotzdem ehrlich,
// die Deckelung passiert außerhalb dieses Prompts.

Antworte NUR mit dem JSON-Objekt. Kein Markdown-Codeblock, kein Vorspann,
kein Nachwort.
```

**Einsatz-Hinweise:**
- Wird pro `learn`-Lauf einmal aufgerufen, NUR für Ordner-Ebenen, die nach F7-Klassifikation als CUT-Stil erkannt wurden (Median-Dauer ≤ ~2 min) — FORMAT-Profile (ganze Videos) werden NIE in diesen Prompt gegeben, da sie sonst fälschlich eine `ideal_clip_s` erhalten würden.
- Mechanischer Fallback (ohne LLM oder `--no-llm`) muss dieselben Schlüssel liefern: `ideal_clip_s` = Median der `duration_s`, `pace` = grobe Kategorisierung aus `cuts_per_min`-Schwellwerten, `humor_notes`/`caption_style` leer.
- Sanitizer klemmt `ideal_clip_s` hart auf die im Code definierte Obergrenze (~90s), unabhängig davon was das Modell zurückgibt — der Prompt-Hinweis reduziert nur die Häufigkeit unrealistischer Werte, garantiert die Grenze aber nicht.

# Diskussionsverlauf

## claude·prompt — Runde 1

Als claude·prompt gehe ich die vier Prompts durch – mit Fokus auf maschinell sichere Extraktion.

**1) Session-Pass**

Aufbau: `[SYSTEM/ROLLE]` → `[HOSTS]` (Namensliste aus Config, damit Gag-Zuordnung im Duo stimmt) → `[GEDÄCHTNIS-KONTEXT]` (bekannte Gags kompakt, damit Wiedererkennung schon hier greift) → `[BISHERIGE FUNDE]` (vom letzten Chunk, leer beim ersten) → `[TRANSKRIPT-CHUNK]` → `[AUFGABE]` → `[SCHEMA]`.

Kritisch: Chunking über Chunk-Grenzen. Ich würde explizit instruieren:

```
Du erhältst Chunk {chunk_index}/{chunk_total}. Die Liste "bisherige_funde" enthält
Gags/Callbacks/Arcs aus früheren Chunks. Gib die VOLLSTÄNDIGE, aktualisierte Liste
zurück (nicht nur Deltas) — bestehende Einträge fortschreiben (z.B. payoff_t
ergänzen), neue anhängen, NICHTS aus "bisherige_funde" ohne Grund löschen.
```

Grund: Deltas erzwingen fehleranfälliges Merge-Code auf unserer Seite; volle Liste zurück + Dedup bei uns ist robuster, kostet nur Tokens. Trade-off: bei sehr vielen Gags wird der Prompt lang — dafür `max_running_gags` im Prompt deckeln ("wichtigste zuerst, max N").

Schema strikt:
```json
{"running_gags":[{"id":"slug","name":"...","first_t":0.0,"description":"..."}],
 "callbacks":[{"setup_t":0.0,"payoff_t":0.0,"description":"..."}],
 "arcs":[{"name":"...","start_t":0.0,"end_t":0.0,"description":"..."}],
 "notes":["..."]}
```
`id` als stabiler Slug ist Pflicht – ohne stabile ID kann der Moment-Pass später nicht per `lore_refs` referenzieren, und die Konsolidierung kann nicht mergen.

**2) Moment-Pass** – der heikelste, weil hier UI-Text (Titel/Captions) entsteht, der ungefiltert in Dateinamen/CSV landet.

Reihenfolge: `[ROLLE]` → `[HOSTS]` → `[SPRACHE: Antworte in der Sprache der Streamer — falls erzwungen, exakt {lang}]` → `[GEDÄCHTNIS]` → `[STYLE-TAGS: nur diese verwenden: {cut_styles}]` → `[KANÄLE: nur diese: {channel_names}]` → `[KANDIDATEN mit Volltext-Kontext ±90s]` → `[STICHPROBE des Rests]` → `[SCHEMA]`.

Enum-Disziplin im Prompt selbst, nicht nur im Sanitizer:
```
"style" MUSS einer dieser Werte sein: {cut_style_list}. Wenn keiner passt, "".
"channels" MUSS eine Teilmenge von {channel_list} sein.
```
Doppelte Absicherung (Prompt + Code-Sanitizer) ist bewusst redundant — LLMs ignorieren Constraints gelegentlich, und wir dürfen dem Modell hier nicht vertrauen.

Schema:
```json
{"moments":[{
  "t0":0.0,"t1":0.0,"category":"slug","score":0,"punchline_t":0.0,
  "title":"...","reasoning":"...","style":"",
  "channels":["insta","yt"],"callback_refs":["gag_id"],"lore_refs":["gag_id"],
  "captions":[{"t":0.0,"text":"..."}],
  "zooms":[{"t":0.0,"duration":0.0}],
  "sfx":[{"t":0.0,"kind":"..."}]
}]}
```
Wichtig: `reasoning` und `title` explizit als **Klartext, eine Zeile, keine Markdown-Formatierung** anweisen — Newlines in Titeln zerschießen sonst CSV/Dateinamen selbst vor Sanitizing schon semantisch (abgeschnittene Sätze). Formulierung: `"title": Ein Satz, keine Zeilenumbrüche, keine Anführungszeichen.`

Anti-Geschwätzigkeit: Schlusssatz nicht vergessen:
```
Antworte NUR mit dem JSON-Objekt. Kein Markdown-Codeblock, kein Vorspann, kein Nachwort.
```
Trotzdem muss unser Extractor robust gegen Codeblock-Fences und Vorspann bleiben — die Anweisung senkt die Häufigkeit, ersetzt aber nicht den Balanced-Brace-Parser.

**3) Gedächtnis-Konsolidierung** – klein halten, deterministisch: Input = bekannte Gags + neue lore_refs-Treffer der Session, Output = `{"bumped":["gag_id",...],"merged":[{"into":"id","from":["id2"]}]}`. Bewusst NICHT die vollen Gag-Objekte zurückgeben lassen — nur IDs, damit der mechanische Fallback (reines ID-Matching) exakt das gleiche Format erzeugt und beide Pfade austauschbar sind.

**4) Stil-Destillation** – Input Fingerprints (Dauer/Cuts pro Minute/Transkript-Proben), Output `{"styles":{"insta_funny":{"ideal_clip_s":0,"pace":"...","humor_notes":"...","caption_style":"..."}}}`. Klare Anweisung: `Nur CUT-Stile destillieren, die dir explizit als solche übergeben werden — erfinde keine Werte für Formate ohne Daten.`

**Was NICHT rein soll** in allen vier: keine Ausgabe-Beispiele mit Fantasie-Timecodes (Modelle kopieren Beispielwerte), keine Meta-Diskussion/Begründung außerhalb `reasoning`-Feld, kein Freitext-Präfix wie "Hier ist die Analyse:".

Vorläufige Empfehlung: einheitliches Prompt-Grundgerüst (Rolle→Konstanten→Daten→Schema→Stop-Anweisung) über alle vier Pässe, mit striktem "nur JSON"-Postskriptum und enum-Wiederholung im Schema-Block selbst. An claude·editorial: interessiert mich, ob die Reihenfolge Hosts/Sprache VOR den Daten aus eurer Sicht auch für Ton/Stimme der Captions passt, oder ob ihr das anders gewichten würdet.

## claude·editorial — Runde 1

Als claude·editorial reagiere ich auf prompt aus der Cutter-Perspektive – wo sitzt der Witz, wo landet Text auf dem Bildschirm, wo täuscht die Struktur eine gute Entscheidung nur vor.

**Zustimmung zu prompt bei Session-Pass, aber eine Ergänzung.** Volle Liste statt Delta ist richtig. Was fehlt: `arcs` und `callbacks` brauchen eine explizite Anweisung, **Setup und Payoff getrennt zu timestampen, auch wenn sie Minuten auseinanderliegen** — sonst neigt das LLM dazu, `setup_t` und `payoff_t` gleichzusetzen, wenn es den Bogen erst beim Payoff "erkennt". Ich würde ergänzen:

```
Ein Callback braucht ZWEI unterschiedliche Zeitpunkte: setup_t (wo der Gag zuerst
etabliert wird) und payoff_t (wo er wieder aufgegriffen wird). Wenn du den Payoff
erkennst, suche im BISHERIGEN Transkript (auch aus früheren Chunks) nach dem Setup
zurück — rate nicht, wenn du es nicht findest: dann gehört es in "notes", nicht
in "callbacks".
```
Das ist editorisch der Kernwert des ganzen Tools: ein Callback-Clip ohne belastbaren setup_t ist für den Editor wertlos, weil er das Setup-Material gar nicht findet.

**Beim Moment-Pass widerspreche ich der Reihenfolge leicht.** prompt setzt `[HOSTS]`→`[SPRACHE]` direkt nach der Rolle, vor die Kandidaten. Aus Ton-Sicht ist das richtig für Sprache, aber ich würde **`[KATEGORIE-DEFINITIONEN]` als eigenen Block VOR die Kandidaten** schieben, den prompt komplett ausgelassen hat. Ohne klare Kategorie-Semantik im Prompt selbst (nicht nur als Enum-Liste) bewertet das LLM "witzig" und "cringe" und "hype" inkonsistent zwischen Chunks/Läufen. Konkret:

```
Kategorien-Bedeutung (wähle die naheliegendste, nicht die extremste):
- "punchline": pointierter Wortwitz mit klarem Vorher/Nachher
- "chaos": eskalierende Situation ohne einzelne Pointe
- "outplay": Skill-Moment, Reaktion ist Bewunderung nicht Lachen
- "callback": Gag-Wiederaufnahme, MUSS in callback_refs verweisen
```
Grund: `score` und `category` hängen zusammen — ein "outplay" mit Score 9 braucht andere Caption-/Zoom-Vorschläge (Zoom auf Skill-Moment, keine Lach-SFX) als "chaos" mit Score 9. Wenn die Kategorie schwammig bleibt, sind auch die abgeleiteten `zooms`/`sfx` falsch kalibriert.

**Zweiter Widerspruch, wichtiger:** prompt fordert `t0/t1` als "Schnittfenster inkl. Setup", aber im Schema-Snippet steht keine explizite Anweisung, **wie viel Setup**. Aus Cutter-Sicht ist zu viel Setup genauso ein Fehler wie zu wenig — ein Clip, der 15s Anlauf für eine 2-Sekunden-Pointe hat, verliert auf insta sofort die Retention. Ich würde ergänzen:

```
t0 = frühester Punkt, an dem ein Zuschauer OHNE Vorwissen die Pointe versteht —
nicht der früheste Punkt, an dem das Thema beginnt. Wenn Setup und Pointe mehr
als ~20s auseinanderliegen, prüfe ob ein kürzeres t0 möglich ist, das trotzdem
verständlich bleibt.
```

**Was ich bei captions/zooms/sfx vermisse:** keiner von uns hat bisher angewiesen, dass **zooms/sfx sich am `punchline_t` orientieren müssen, nicht verstreut sein dürfen**. Sonst bekommen wir zehn SFX-Cues über einen 40s-Clip verteilt, die jeden Schnitt entwerten. Kurzer Zusatz im Schema-Kommentar: `Setze zooms/sfx sparsam — primär auf punchline_t, max. 1-2 zusätzliche auf klare Sekundärmomente.`

**Konsolidierung und Stil-Destillation:** stimme prompt voll zu, IDs-only bei Konsolidierung ist sauber. Bei Stil-Destillation würde ich noch `humor_notes` präzisieren, sonst kommt generischer Text raus, der beim Taggen im Moment-Pass nicht hilft: `humor_notes` soll konkrete wiederkehrende Muster benennen (Wortspiel-Dichte, Ton-Wechsel, Break-Charakter), keine Stilkritik.

**Empfehlung (gemeinsam):** prompts Grundgerüst übernehmen, plus vier Ergänzungen: (1) Setup/Payoff-Trennungspflicht im Session-Pass, (2) Kategorie-Definitionsblock vor den Kandidaten im Moment-Pass, (3) explizite t0-Knappheitsregel, (4) Zoom/SFX-Konzentration auf punchline_t. Bei der Reihenfolgefrage von prompt: Hosts/Sprache vor den Daten ist für mich okay, aber Kategorie-Definitionen gehören dazwischen, direkt vor die Kandidatenliste — je näher am Bewertungsauftrag, desto konsistenter die Zuordnung.

## claude·prompt — Runde 2

**Zustimmung zu editorial, mit einer Präzisierung beim Session-Pass.** Die Setup/Payoff-Trennung ist wichtig — ich ergänze sie um eine ID-Stabilitätsregel, die sonst editorials eigene Anforderung unterläuft: Wenn das Modell in jedem Chunk die *volle* Liste neu ausgibt (mein Vorschlag aus Runde 1), muss dieselbe Gag-Instanz über Chunks hinweg dieselbe `id` behalten, sonst dedupliziert unser Merge-Code falsch und `callback_refs`/`lore_refs` aus dem Moment-Pass zeigen später ins Leere. Ergänzung:

```
Wenn ein Eintrag in "bisherige_funde" zum selben Gag/Callback/Arc gehört, den du gerade
aktualisierst, VERWENDE DESSEN id UNVERÄNDERT weiter. Vergib eine neue id nur für
tatsächlich neue Gags/Callbacks/Arcs, die in "bisherige_funde" noch nicht vorkommen.
```

**Kategorie-Definitionsblock vor den Kandidaten — übernommen, aber mit Kosten-Hinweis.** Der Block muss bei jedem Moment-Pass-Aufruf (auch bei Chunking innerhalb des Passes) mitgeschickt werden, das kostet Tokens pro Aufruf. Trade-off ist es wert, weil sonst Score/Kategorie zwischen Chunks driften — genau editorials Punkt.

**Wichtige Ergänzung aus meiner Rolle, die bisher fehlt: Truncation-Schutz durch Kürze-Vorgaben, nicht nur durch Nachbearbeitung.** Der Balanced-Brace-Extractor rettet uns nur, wenn das JSON tatsächlich *vollständig* generiert wurde. Läuft das Modell bei vielen Kandidaten (voller Kontext ±90s + Stichprobe) ins Token-Limit, bricht die Antwort mitten in einem Objekt ab — das ist kein "geschwätziger", sondern ein *unbalancierter* Fall, den kein Parser rettet. Deshalb muss der Prompt selbst Kürze erzwingen, nicht nur Stil verlangen:

```
"title": max. 8 Wörter, ein Satz, keine Zeilenumbrüche/Anführungszeichen.
"reasoning": max. 25 Wörter, Stichpunkt-Charakter — kein Essay.
Gib ALLEN Kandidaten ein vollständiges, valides JSON-Objekt zurück. Ein vollständiges
JSON mit knappen Feldern hat IMMER Priorität vor ausführlichen Feldern. Wenn du bei
vielen Kandidaten Platz sparen musst, kürze zuerst Freitext-Felder — NIE Timecodes,
NIE Pflichtfelder, NIE die Anzahl der Kandidaten.
```

Das ist wichtiger als es klingt: Es ist der einzige Hebel, der abgeschnittene/unparsbare Antworten *vor* der Generierung verhindert statt danach zu reparieren.

**Formatpräzision, die im bisherigen Entwurf implizit blieb:** `t0`/`t1`/`punchline_t`/`setup_t`/`payoff_t` müssen explizit als **Sekunden, float, relativ zum VOD-Start** spezifiziert werden — sonst rutscht ein Modell gelegentlich in `"t0": "12:34"` ab, was der Sanitizer zwar defensiv abfangen muss, aber besser gar nicht erst passiert. Ich schreibe das direkt ins Schema als Kommentar:

```
// alle Zeit-Felder: Sekunden als Zahl (float), relativ zum VOD-Start, NIE "MM:SS"-Strings
```

**Leere-Listen-Disziplin ergänzen:** `"callbacks": [] statt null, wenn keine gefunden wurden"` — reduziert die Häufigkeit der ohnehin pflichtigen Sanitizer-Fälle, ersetzt sie aber nicht.

**Bei editorials t0-Knappheitsregel** stimme ich zu, würde sie aber mit einem Anker versehen, damit sie nicht bei jedem Lauf anders ausfällt: `"~20s" als weiche Faustregel im Prompt` ist qualitativ gut genug, härtere Zahlen würden das Modell nur dazu bringen, künstlich exakt 20,0s zu produzieren.

**Bei Stil-Destillation** übernehme ich editorials Präzisierung, ergänze eine Formatvorgabe, damit `humor_notes` maschinell weiterverarbeitbar bleibt statt Prosa zu werden: `"humor_notes": 3-5 kurze, semikolon-getrennte Stichpunkte, keine Fließtext-Absätze.`

**Empfehlung (aktualisiert):** editorials vier Ergänzungen + meine ID-Stabilitätsregel, Truncation-Schutz durch Feldlängen-Deckel, explizite Zeitformat-Spezifikation und Leere-Listen-Vorgabe. Reihenfolge: Rolle → Hosts/Sprache → Gedächtnis → Kategorie-Definitionen → Kandidaten/Kontext → Schema (mit Format-Kommentaren) → Kürze-Anweisung → "Nur JSON"-Schlusssatz.

## claude·editorial — Runde 2

Als claude·editorial, Runde 3: Ich schließe mich dem Grundgerüst an, will aber vier Punkte präzisieren, die aus Editorial-Sicht noch Lücken lassen, plus einen echten Widerspruch.

**Zustimmung zu prompts ID-Stabilitätsregel** — unverzichtbar, sonst brechen genau die `callback_refs`/`lore_refs`, die ich in Runde 1 gefordert habe. Kein Widerspruch, nur eine Ergänzung: die Regel muss auch für den Fall gelten, dass ein Gag in `bisherige_funde` steht, aber im aktuellen Chunk gar nicht vorkommt — dann NICHT weglassen, sondern unverändert durchreichen. Sonst „verschwinden" Gags aus der Liste, sobald sie mal einen Chunk pausieren, und der Editor verliert die Zuordnung im späteren Sheet.

**Truncation-Schutz durch Feldlängen-Deckel: großer Zustimmung, aber eine Korrektur der Prioritätsreihenfolge.** prompt schreibt „kürze zuerst Freitext-Felder — NIE Timecodes, NIE Pflichtfelder". Aus Cutter-Sicht ist `reasoning` auf 25 Wörter zu knapp, wenn es gleichzeitig `callback_refs`/`lore_refs` belegen soll — ich brauche im Sheet später eine nachvollziehbare Zeile, warum ein Moment als Callback markiert wurde, sonst kann ich das im Schnitt nicht verifizieren und schneide blind. Vorschlag: `reasoning` auf ~30 Wörter, aber mit fester Struktur statt freier Prosa, damit die Kürze nicht auf Kosten der Nachvollziehbarkeit geht:

```
"reasoning": max. 30 Wörter. Struktur: "<Warum clip-würdig>. <Bezug falls callback/lore>."
Kein Fließtext-Fazit, kein "Dieser Moment ist witzig, weil..." — direkt der Grund.
```

**Widerspruch bei der Zeitformat-Regel: nicht hart genug für `punchline_t`.** prompt verlangt „Sekunden als Zahl, relativ zum VOD-Start" — richtig, aber für `punchline_t` speziell muss der Prompt auch verlangen, dass es **innerhalb von `[t0,t1]` liegt**, sonst produziert das Modell gelegentlich einen Pointe-Zeitpunkt außerhalb des eigenen Schnittfensters (z.B. wenn die Pointe technisch vor dem gewählten t0 lag). Für die Schnittplanung (F11: „Ende kurz nach punchline_t") ist das kein Rand-, sondern ein Kernfall:

```
punchline_t MUSS im Intervall [t0, t1] liegen. Wenn die eigentliche Pointe außerhalb
deines gewählten Fensters liegt, korrigiere t0/t1 statt punchline_t zu verschieben.
```

**Übersehener Aspekt: Running-Gag-Benennung im Session-Pass.** Bisher steht nirgends, dass `name` in `running_gags` ein **wiedererkennbarer, kurzer Spitzname** sein muss (für 🧠-Lore-Zeilen im Sheet und für Konsolidierungs-Matching über Sessions hinweg), nicht eine Beschreibung. „Der Moment, wo X über Y stolpert" ist als `name` unbrauchbar für spätere Fuzzy-Zuordnung; „Stolper-Gag" ist es. Ergänzung im Session-Pass-Schema-Kommentar:

```
"name": kurzer Spitzname (2-4 Wörter), wie die Streamer den Gag selbst nennen würden
oder nennen sollten — KEINE Beschreibung des Ereignisses. "description" ist für Details.
```

**Zustimmung zu prompts Leere-Listen-Disziplin und zur Formatvorgabe für `humor_notes`** — beides unterstützt direkt die Weiterverarbeitung im Moment-Pass-Tagging.

**Empfehlung (final, aus meiner Sicht):** Grundgerüst + alle bisherigen Ergänzungen beider Runden, plus: (1) explizite „Gag bleibt in der Liste auch bei Chunk-Pause"-Regel, (2) `reasoning` auf ~30 Wörter mit fester Zwei-Satz-Struktur statt freier 25-Wort-Prosa, (3) `punchline_t ∈ [t0,t1]`-Zwang mit Korrekturregel Richtung t0/t1, (4) `name` explizit als Spitzname statt Beschreibung. Reihenfolge bleibt wie von prompt zuletzt vorgeschlagen (Rolle→Hosts/Sprache→Gedächtnis→Kategorien→Kandidaten→Schema mit Format-Kommentaren→Kürze-Anweisung→Nur-JSON-Schlusssatz) — die passt aus Ton- wie aus Robustheitssicht.

## claude·prompt — Runde 3

Als claude·prompt, letzte Runde: Ich sehe keine Punkte, die ich ablehnen muss — aber zwei brauchen aus meiner Rolle eine Präzisierung, sonst kollidieren sie mit der Robustheits-Mechanik, die wir uns aufgebaut haben.

**Zustimmung zu editorials "Gag bleibt in der Liste auch bei Chunk-Pause".** Das schreibe ich direkt in meine ID-Stabilitätsregel als Fortsetzung:

```
Einträge aus "bisherige_funde", die im aktuellen Chunk NICHT erwähnt werden, bleiben
UNVERÄNDERT in der Ausgabe — nicht löschen, nicht "vermuten" dass sie beendet sind.
```

**Präzisierung, kein Widerspruch, bei `reasoning` auf 30 Wörter mit Zwei-Satz-Struktur.** Editorial hat recht, dass Nachvollziehbarkeit für den Cutter zählt — aber eine feste Struktur mit Punkt-getrennten Sätzen ist für unseren Extraktor sogar *robuster* als freie Prosa, weil sie das Risiko eingebetteter Anführungszeichen/Doppelpunkte senkt, die JSON-Strings gelegentlich brechen. Kein Zielkonflikt, ich übernehme das 1:1 und ergänze nur das Feldlängen-Budget entsprechend (25→30 Wörter ändert die Truncation-Rechnung bei vielen Kandidaten kaum).

**Wichtiger Punkt, den ich noch einbringen muss: `punchline_t ∈ [t0,t1]`-Zwang braucht eine Reihenfolge-Klarstellung für den Sanitizer.** Editorials Regel "korrigiere t0/t1 statt punchline_t zu verschieben" ist editorisch richtig, aber als *Prompt-Anweisung* an ein LLM ist sie nicht erzwingbar — wir können nur bitten. Deshalb muss der Code-Sanitizer eine deterministische Fallback-Regel haben, falls das Modell es trotzdem verletzt (z.B. `punchline_t` auf `clamp(punchline_t, t0, t1)`), und das gehört *nicht* in den Prompt, sondern in die Spezifikation der Sanitisierung — nur damit hier kein Missverständnis entsteht, dass die Prompt-Anweisung allein die Invariante garantiert.

**Einen Aspekt ergänze ich neu, aus JSON-Robustheit:** Bei `callback_refs`/`lore_refs`/style/channels als Arrays sollte der Prompt explizit sagen, dass **unbekannte IDs/Tags wegzulassen statt zu erfinden sind**:

```
Wenn du unsicher bist, ob eine ID aus dem Gedächtnis passt, LASS DEN VERWEIS WEG statt
zu raten. Erfundene IDs sind schlimmer als fehlende Verweise.
```

Das schließt eine Lücke, die sonst der Sanitizer stillschweigend auffängt (unbekannte ID → drop), aber ohne Prompt-seitige Anweisung produziert das Modell unnötig viele Drops, die editorial im Sheet als fehlende Lore-Zeilen bemerken würde.

**Konsens-Formulierung (final):**

Alle vier Prompts folgen dem Grundgerüst Rolle → Hosts/Sprache → Gedächtnis → Kategorie-Definitionen (nur Moment-Pass) → Daten (mit voller-Liste-Regel + ID-Stabilität + Chunk-Pause-Persistenz im Session-Pass) → Schema mit Format-Kommentaren (Sekunden-float, `punchline_t ∈ [t0,t1]`-Bitte, `name`=Spitzname, Feldlängen-Deckel, Leere-Listen-Pflicht, "keine erfundenen Refs") → Kürze-Priorität bei knappem Platz → "Nur JSON, kein Vorspann"-Schlusssatz. Konsolidierung bleibt ID-only, Stil-Destillation bekommt strukturierte `humor_notes` und destilliert nur belegte CUT-Stile.

**Verbleibender Dissens: keiner in der Substanz.** Die einzige offene Feinabstimmung ist `reasoning` 25 vs. 30 Wörter — ich akzeptiere editorials 30, da der Robustheitsverlust minimal ist und der Nachvollziehbarkeitsgewinn real. Damit trage ich den gemeinsamen Vorschlag vollständig mit.

## claude·editorial — Runde 3

Als claude·editorial, letzte Runde: Der Konsens von prompt trägt aus meiner Sicht vollständig — ich formuliere Zustimmung, eine Präzisierung und eine echte Ergänzung, dann den finalen gemeinsamen Vorschlag.

**Zustimmung ohne Einschränkung** zu prompts drei Punkten: Chunk-Pause-Persistenz-Formulierung, reasoning-Struktur bleibt robust, und `clamp(punchline_t, t0, t1)` als Sanitizer-Fallback statt Prompt-Zwang ist der richtige Schnitt — die Trennung "Prompt bittet, Code garantiert" ist genau die Disziplin, die dieses ganze Tool braucht.

**Zustimmung zur "keine erfundenen IDs"-Regel, mit einer editorischen Begründung ergänzt.** prompt begründet das aus JSON-Robustheit (weniger Drops). Aus Cutter-Sicht ist der Schaden größer als nur ein leerer Sanitizer-Log: eine erfundene `lore_refs`-ID erzeugt im Sheet eine 🧠-Zeile, die auf einen Gag verweist, der so nie existierte — das untergräbt genau das Vertrauen in die Lore-Markierungen, das den Wiedererkennungswert des Tools ausmacht. Ich würde den Zusatz im Prompt noch um einen Satz schärfen:

```
Ein fehlender Lore-Verweis kostet uns eine Zeile im Sheet. Ein erfundener Verweis
kostet uns das Vertrauen der Editoren in ALLE Lore-Verweise.
```
Das ist keine neue Regel, nur eine Verstärkung, die das Modell motivational anders gewichtet als ein trockenes "lass es weg".

**Eine Ergänzung, die in drei Runden übersehen wurde: die Stichprobe des Rests im Moment-Pass braucht eine explizite Anti-Bias-Anweisung.** F5 verlangt "gleichmäßige Stichprobe des Rests" fürs eigene Entdecken von Momenten ohne Game-Event. Bisher steht im Prompt nirgends, dass das Modell bei der *Selbstentdeckung* dieselbe Kategorie-Disziplin anwenden soll wie bei den Kandidaten — sonst neigen LLMs dazu, in der Stichprobe bevorzugt „auffällige" Textstellen (viel Text, Ausrufezeichen, Caps) zu ziehen statt tatsächlich witzige, was Editorial-Qualität systematisch gegen offensichtliche statt gute Momente verzerrt. Ergänzung im Moment-Pass:

```
Eigene Funde in der Stichprobe unterliegen denselben Kategorie- und Score-Maßstäben
wie die Kandidaten. Auffälliges Transkript (Großschreibung, Ausrufezeichen, Länge)
ist KEIN Signal für Clip-Würdigkeit — bewerte den Inhalt, nicht die Textoberfläche.
```
Das ist kein Widerspruch zu etwas Bestehendem, sondern schließt eine Lücke, die erst durch die Kombination aus "eigene Momente entdecken" + "Stichprobe" entsteht.

**Letzter Punkt, kurz:** Bei der Kategorie-Definitionsliste sollte "callback" explizit gegenseitig mit `callback_refs` verzahnt werden — `"category":"callback"` OHNE Eintrag in `callback_refs` ist ein Widerspruch, den der Sanitizer zwar technisch durchlassen könnte, der aber editorisch sinnlos ist. Ein Satz reicht: `Kategorie "callback" erfordert mindestens einen Eintrag in callback_refs — sonst wähle eine andere Kategorie.`

**Gemeinsame finale Empfehlung:**

Alle vier Prompts folgen dem Grundgerüst Rolle → Hosts/Sprache → Gedächtnis → Kategorie-Definitionen (nur Moment-Pass, inkl. callback↔callback_refs-Kopplung) → Daten (volle-Liste-Regel, ID-Stabilität inkl. Chunk-Pause-Persistenz, Setup/Payoff-Trennungspflicht, Anti-Bias-Hinweis für Selbstentdeckung) → Schema mit Format-Kommentaren (Sekunden-float, `punchline_t`-Bitte innerhalb `[t0,t1]` + Sanitizer-Clamp als Garantie, `name`=Spitzname, Feldlängen-Deckel mit reasoning ~30 Wörter/Zwei-Satz-Struktur, Leere-Listen-Pflicht, verstärkte „keine erfundenen Refs"-Regel) → Kürze-Priorität bei knappem Platz → „Nur JSON, kein Vorspann"-Schlusssatz. Konsolidierung bleibt ID-only mit mechanischem Fallback; Stil-Destillation liefert strukturierte `humor_notes` und destilliert nur belegte CUT-Stile.

**Verbleibender Dissens:** keiner in der Substanz. Meine Ergänzung zur Stichproben-Verzerrung und die verstärkte Formulierung zu erfundenen Refs sind Zusätze, keine Korrekturen an prompts Vorschlägen — ich trage den gemeinsamen Vorschlag vollständig mit.
