REFERENCES / BEISPIEL-CLIPS
===========================

DE: Wirf hier viele Beispiel-Videos rein, deren STIL dir gefaellt — deine
besten Uploads oder gute Edits von anderen Creators (mp4/mkv/webm/mov/...).
Dann:

    .venv\Scripts\python -m clip_lab learn        (Windows)
    .venv/bin/python -m clip_lab learn            (Linux/Mac)

Das Tool analysiert jeden Clip (Laenge, Schnitt-Tempo, was gesprochen wird)
und destilliert daraus einen Style Guide (style_profile.json). Ab dann zielt
jede Analyse auf genau diesen Stil. Clips austauschen + nochmal `learn`
laufen lassen = Stil neu lernen. style_profile.json loeschen = vergessen.

EN: Drop example clips you LIKE in here, then run `clip_lab learn`. The tool
fingerprints each one and distills a style guide that every later `analyze`
aims at. Re-run `learn` after changing the clips; delete style_profile.json
to forget.
