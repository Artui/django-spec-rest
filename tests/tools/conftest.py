from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"

if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
