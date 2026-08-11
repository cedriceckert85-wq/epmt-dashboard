#!/usr/bin/env python3
"""Regenerate FILE_MANIFEST.md from the actual tree. Run before packaging;
tests/unit/test_manifest_sync.py fails when the manifest is stale."""
from pathlib import Path

EXCLUDE=("__pycache__",".pytest_cache",".orchestrator",".git/")

def listing(root: Path):
    out=[]
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        rel=p.relative_to(root).as_posix()
        if any(x in rel for x in EXCLUDE):
            continue
        out.append(rel)
    return sorted(set(out)|{"FILE_MANIFEST.md"})

if __name__=="__main__":
    root=Path(__file__).resolve().parents[1]
    files=listing(root)
    (root/"FILE_MANIFEST.md").write_text("# File Manifest\n\n"+"\n".join(f"- `{f}`" for f in files)+"\n")
    print(f"manifest: {len(files)} files")
