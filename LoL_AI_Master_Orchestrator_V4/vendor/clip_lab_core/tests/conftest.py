import sys
from pathlib import Path

# Make `import clip_lab` work no matter where pytest is invoked from.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
