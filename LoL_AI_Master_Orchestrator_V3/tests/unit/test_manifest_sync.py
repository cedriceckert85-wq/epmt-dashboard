import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
from generate_manifest import listing

def test_manifest_matches_tree():
    expected=set(listing(ROOT))
    manifest={l.strip()[3:-1] for l in (ROOT/"FILE_MANIFEST.md").read_text().splitlines()
              if l.startswith("- `")}
    assert manifest==expected
