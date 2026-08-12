REFERENCES / BEISPIEL-CLIPS
===========================

DE: EIN UNTERORDNER PRO STIL — der Ordnername ist der Stilname:

    references/funny/     <- Beispiel-Clips fuer deinen Funny-Stil
    references/montage/   <- Beispiel-Clips fuer deinen Montage-Stil
    references/hype/      <- beliebige eigene Kategorien anlegen

Wirf in jeden Unterordner viele Clips, deren STIL dir gefaellt — deine besten
Uploads oder gute Edits von anderen Creators (mp4/mkv/webm/mov/...). 5-15 pro
Stil ist der Sweet Spot. Dann:

    .venv\Scripts\python -m clip_lab learn        (Windows)
    .venv/bin/python -m clip_lab learn            (Linux/Mac)

Das Tool lernt pro Ordner ein Stil-Profil (Laenge, Schnitt-Tempo, Humor-Art,
Captions). Bei jeder Analyse entscheidet dann der INHALT eines Moments, in
welchem Stil er geschnitten werden soll — im Edit-Sheet steht z.B.
"Cut as: montage-style". Clips direkt in references/ (ohne Unterordner)
ergeben ein allgemeines Profil. YouTube-Links laden (yt-dlp noetig):

    python -m clip_lab fetch "https://..." --style funny

Clips austauschen + nochmal `learn` = neu lernen.
style_profile.json loeschen = alles vergessen.

EN: One SUBFOLDER per style (folder name = style name). Drop example clips
you LIKE into each, run `clip_lab learn` — one style guide per folder. Every
analyze then tags each moment with the best-fitting style based on content.
Re-run `learn` after changing clips; delete style_profile.json to forget.
