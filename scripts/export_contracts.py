"""Regenerate documentation from the actual backend; does not queue any jobs."""
import json
from pathlib import Path
import sys

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / "backend"))
from app.main import app  # noqa: E402
from app.db import SCHEMA  # noqa: E402

(project / "docs" / "openapi.json").write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
(project / "docs" / "schema.sql").write_text(SCHEMA.strip() + "\n", encoding="utf-8", newline="\n")
print("docs/openapi.json e docs/schema.sql atualizados a partir do código real.")
