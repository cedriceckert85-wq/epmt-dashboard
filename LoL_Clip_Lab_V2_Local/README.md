# LoL Clip Lab — Local Edit Studio (V2, Test Edition)

A **completely local** tool that watches a **downloaded** League of Legends VOD
and hands you an **edit sheet**: the funny / hype / clutch / callback moments,
with **punchline-aware cut points** and caption / zoom / SFX suggestions you can
act on in your editor. No streaming, no upload, no OBS, no network required for
the analysis itself.

This is the *test / offline* sibling of the big one-shot orchestrator. Its only
job is the part you said matters most — **the humor / meme / edit core**: pulling
context out of a match and finding what's actually worth clipping.

Built for your box: **Ryzen 7 5800X3D + Radeon RX 9070 XT + 64 GB RAM**.
Because the 9070 XT is **AMD**, everything avoids CUDA/NVENC: Whisper runs on the
**CPU** (int8), and clip encoding uses **AMD AMF** (or CPU x264) — never NVENC.

---

## Kurzanleitung (Deutsch)

1. ZIP entpacken.
2. **Windows:** `START.bat` doppelklicken. (Oder eine VOD-Datei auf `START.bat`
   ziehen — dann wird sie direkt analysiert.)
   **Linux/Mac:** `./start.sh /pfad/zur/vod.mp4`
3. Beim ersten Start richtet sich alles selbst ein (venv + Abhängigkeiten) und
   ein **Selbsttest** läuft — er erzeugt ein Beispiel-Edit-Sheet, damit du sofort
   siehst, was rauskommt.
4. Eigene VOD analysieren:
   `.venv\Scripts\python -m clip_lab analyze "C:\pfad\vod.mp4"`
5. Ergebnis: Ordner `vod_clips\` mit **`edit_sheet.md`** (zum Lesen),
   `edit_plan.json` (für Tools) und `clips.csv`.

Es geht hier **nur** ums Editen / Inspiration / Kontext ziehen — kein Streaming,
kein Upload.

**Neu — das Gedächtnis 🧠:** Das Tool merkt sich Running Gags, Catchphrases und
Kanal-Lore **über alle Sessions hinweg** (`channel_memory.json`). Taucht ein Gag
aus Stream #2 in Stream #7 wieder auf, erkennt das LLM ihn und markiert den Clip
im Edit-Sheet mit `🧠 running gag`. `python -m clip_lab memory` zeigt, was das
Tool über deinen Kanal weiß; `--clear` löscht es.

**Neu — Beispiel-Videos 🎬:** Wirf viele Clips, deren **Stil** dir gefällt, in den
Ordner `references/` und lass `python -m clip_lab learn` laufen — das Tool lernt
daraus deinen Ziel-Stil (Clip-Länge, Schnitt-Tempo, Humor-Art, Caption-Stil) und
zielt ab dann bei jeder Analyse darauf. Und: einen **ganzen Ordner voller VODs**
auf `START.bat` ziehen analysiert alle nacheinander (Batch), wobei das Gedächtnis
über alle mitwächst.

---

## What it produces

For each suggested clip, `edit_sheet.md` gives you:

- **Cut points** — punchline-aware: a funny beat gets its *setup* lead-in and
  ends shortly *after* the punchline, not on a fixed stopwatch.
- **Category** — funny 😂 / hype 🔥 / clutch 🎯 / fail 💀 / callback 🔁 / wholesome 🥹.
- **Why it works** — one line, so you can skim and keep only what lands.
- **What was said** — the transcript excerpt across the clip.
- **Overlay plan** — caption / zoom / SFX suggestions at exact timecodes.
- **Callback inserts** — "insert the earlier moment here" when a joke pays off a
  setup from earlier in the game (the running-gag mechanic).

You also get `edit_plan.json` (machine-readable, feed it to your own tooling) and
`clips.csv` (import into a spreadsheet or NLE).

---

## The three moving parts

1. **Signal** — `ffmpeg` pulls the audio, and pure-numpy reaction detection finds
   where you laughed / shouted / got loud. That's the most honest "something
   happened here" signal. Optional game events (kills, objectives) come from a
   small JSON/CSV *you* supply (a downloaded VOD has no live Riot API).
2. **Transcript** — `faster-whisper` (CPU, int8) turns speech into timestamped
   text. Or supply your own transcript and skip Whisper entirely.
3. **Editorial brain** — the creative core. It reads the **whole stream script**
   (speech + reactions + events) and asks an LLM to do what statistics can't:
   find the *funny* moments (including pure-talk moments with **no** game event),
   locate the **punchline**, spot **callbacks / running gags**, and suggest the
   captions / zooms / SFX. Long VODs are not truncated: the session pass goes
   through the entire script in chunks, carrying its findings forward, so a gag
   set up in minute 3 and paid off in hour 3 still gets connected. By default it
   calls `claude -p`; any CLI that reads a prompt on stdin and prints JSON works
   (set it in `config.toml`).

Everything **degrades gracefully**: no LLM → deterministic signal-only ranking;
no Whisper → supply a transcript; no game events → reactions + editorial still
work. The only hard requirement for a real VOD is **ffmpeg** (it reads the audio).

---

## The channel memory (the 🧠 across sessions)

The editorial brain understands running gags *within* one VOD. The **channel
memory** makes them persist *across* VODs: a small JSON file
(`channel_memory.json`, next to the tool) accumulates with every `analyze` run:

- **running gags** with counters — `"I'll hit a Q eventually" (5x, last: vod_12)`;
  the more often a gag returns, the more established it is,
- **catchphrases**, **channel lore / nicknames**,
- one-line **summaries of recent sessions**.

Before each analysis the memory is injected into the editorial prompts, so the
LLM recognizes a gag from a previous stream the moment it reappears — and tags
the clip in the edit sheet: `🧠 running gag (channel lore): …`. Those clips are
gold for community retention (regulars love recognizing inside jokes).

After each analysis an LLM consolidation pass merges today's findings in:
known gags get their counter bumped (matched by meaning, not exact wording),
new ones are added, stale one-offs eventually fall out (caps keep the file
compact). Without an LLM a deterministic mechanical merge does the same on
exact matches.

Controls:

```
python -m clip_lab memory           # show what the brain knows
python -m clip_lab memory --clear   # forget everything
python -m clip_lab analyze vod.mkv --no-memory   # one run without the brain
```

`[memory]` in `config.toml` sets the file location and the caps. The self-test
demonstrates the whole loop offline: it analyzes the bundled sample twice
against a scratch brain — the second pass recognizes the gags learned in the
first (see the 🧠 lines in `selftest_out/edit_sheet.md`).

---

## Learning your style from reference videos (🎬 `references/`)

Drop **many example clips you like** into `references/` — your best uploads or
well-edited clips from other creators — then:

```
python -m clip_lab learn
```

Each clip gets fingerprinted: duration, **editing pace** (cuts per minute via
ffmpeg scene detection on a sample window), and a **transcript sample** (CPU
whisper, skipped if not installed). The LLM distills all fingerprints into ONE
style guide — ideal clip length, pace/energy, humor traits, caption style —
saved as `style_profile.json`. From then on every `analyze` injects it into the
editorial pass, so titles, cut lengths and caption suggestions aim at **your**
target style instead of a generic one. Honest scope: this steers the LLM's
editorial judgement — it is not model training.

Change the clips → run `learn` again. Delete `style_profile.json` (or use
`analyze --no-style`) to go back to neutral. `[style]` in `config.toml` tunes
the folder, sampling window and scene sensitivity.

## Batch: a whole folder of VODs

```
python -m clip_lab batch "C:\vods"        # or drag the folder onto START.bat
```

Analyzes every video in the folder one after the other (each gets its own
`<name>_clips/` folder next to it). The 🧠 channel memory grows across the whole
batch — analyzing your backlog in one go is exactly how you feed the brain.
Single-file failures don't stop the rest.

---

## Install / first run

You need **Python 3.11+** and **ffmpeg** on your PATH.

- **ffmpeg (Windows):** download a build from gyan.dev or the ffmpeg site, unzip,
  and add its `bin\` folder to your PATH (or drop `ffmpeg.exe` next to the VOD).
- The rest installs itself: `START.bat` / `start.sh` calls `bootstrap.py`, which
  creates `.venv`, installs `numpy` + `faster-whisper`, runs `doctor`, and runs
  the offline self-test.

Check what's available any time:

```
.venv\Scripts\python -m clip_lab doctor
```

---

## Usage

```
# analyze a downloaded VOD -> edit sheet
python -m clip_lab analyze "C:\vods\game1.mkv"

# skip Whisper by supplying your own transcript
python -m clip_lab analyze game1.mkv --transcript game1_transcript.json

# add optional game events (kills/objectives you logged)
python -m clip_lab analyze game1.mkv --events game1_events.json

# your VOD has a separate mic track? point at it (e.g. second audio stream)
python -m clip_lab analyze game1.mkv --audio-stream a:1

# a WHOLE FOLDER of VODs in one go (the channel memory grows across all)
python -m clip_lab batch "C:\vods"

# learn your target style from example clips in references/
python -m clip_lab learn

# signal-only, no LLM (fast, deterministic, no creative layer)
python -m clip_lab analyze game1.mkv --no-llm

# also cut the clips with ffmpeg (AMF on the 9070 XT, else CPU x264)
python -m clip_lab analyze game1.mkv --cut

# cut later from an edit plan you already generated
python -m clip_lab cut game1.mkv game1_clips/edit_plan.json

# prove the creative core works, offline, right now:
python -m clip_lab selftest
```

### The self-test (see it work before you touch a real VOD)

```
python -m clip_lab selftest
```

Runs the **whole** editorial → rank → EDL → edit-sheet path on a bundled sample
game (a Yasuo match with a running gag — "I'll hit a Q eventually" — that pays
off on a pentakill), using a **canned** editorial brain so it's deterministic and
needs no network, no Whisper, no ffmpeg. Open `selftest_out/edit_sheet.md` and
you'll see punchline-aware cuts, categories, captions, SFX, and the callback
insert on the pentakill. Add `--signal-only` to see the no-LLM fallback.

---

## Optional game events

A downloaded VOD has no live API, so events are optional and come from a file:

**JSON**
```json
{"events": [
  {"t": 150.0, "kind": "first_blood", "weight": 3},
  {"t": 1332.0, "kind": "penta", "weight": 10}
]}
```

**CSV** (`t,kind[,weight]`, header optional)
```
t,kind,weight
150,first_blood,3
1332,penta,10
```

`t` is seconds from the start of the VOD. Known kinds (penta, ace, baron,
dragon, first_blood, triple, double, kill, death, …) get sensible default
weights; `weight` overrides them. See `samples/fixture_events.json`.

---

## Configuration

Edit `config.toml` (read on Python 3.11+). Highlights:

- `[whisper] whisper_model` — `tiny|base|small|medium`. `small` is a good
  speed/quality balance on the 5800X3D; go `medium` for accuracy, `base` for
  speed on very long VODs.
- `[ranking] w_signal` / `w_semantic` — how much the raw signal vs. the editorial
  brain's judgement counts (default 0.45 / 0.55 — the creative layer leads).
- `[cuts]` — `funny_setup_preroll_s`, `punchline_decay_s`, `clip_min_s`,
  `clip_max_s`: the punchline-aware cutting rules.
- `[editorial] llm_cmd` — the CLI used as the creative brain (default
  `["claude", "-p"]`). `use_llm = false` disables it globally.
- `[render] encoder` — `auto` picks **AMF** on the Radeon, else CPU **x264**.
  Never NVENC.

---

## AMD notes (Ryzen 7 5800X3D + RX 9070 XT)

- **Whisper on CPU.** `whisper_device = "cpu"`, `compute_type = "int8"`. The
  5800X3D handles `small` comfortably; VAD skips silence so long VODs go faster.
  (There is no stable ROCm/CUDA path for Whisper on a consumer Radeon, and this
  test tool deliberately doesn't need one.)
- **Encoding on AMF.** If your ffmpeg build has `h264_amf`, `--cut` uses the
  9070 XT's hardware encoder; otherwise it falls back to CPU `libx264`. Check
  with `ffmpeg -encoders | findstr amf`.
- **RAM.** 64 GB is plenty; nothing here is memory-hungry.

---

## Tests

```
python -m pytest tests/unit -q
```

142 unit + integration tests cover the pure logic (reaction detection, ranking,
punchline-aware cutting, the editorial contract, JSON extraction, event loading,
config) and an end-to-end run on the bundled fixtures.

---

## Layout

```
clip_lab/            the package
  reactions.py       numpy reaction detection
  transcribe.py      faster-whisper (CPU) + transcript load/save
  timeline.py        signal candidates + session doc
  editorial.py       the creative brain (LLM humor/callbacks/punchlines)
  rank.py            signal + semantic ranking
  edl.py             punchline-aware cut points + overlay plan
  editsheet.py       edit_sheet.md / edit_plan.json / clips.csv
  render.py          optional ffmpeg cutting (AMF / x264)
  ingest.py          ffmpeg audio extract + wav read
  doctor.py          preflight checks
  pipeline.py        wires the stages together
  cli.py             analyze / cut / doctor / selftest
  memory.py          the channel brain: running gags remembered across sessions
  style.py           style learning from your reference clips (references/)
  _demo.py           canned editorial brain for the offline self-test
samples/             fixture transcript + events for the self-test
tests/unit/          the test suite
config.toml          tunables
bootstrap.py         one-shot local setup
START.bat / start.sh entrypoints
```

Scope on purpose: **editing / inspiration / context only.** No streaming, no
upload, no network beyond installing dependencies and (optionally) the LLM CLI.
