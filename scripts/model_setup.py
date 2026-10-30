"""CLI wrapper for CharacterLock Model Setup."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.model_setup import run_interactive_cli  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run_interactive_cli(app_root=ROOT))
