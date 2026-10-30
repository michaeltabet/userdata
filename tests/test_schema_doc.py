"""docs/SCHEMA.md matches the migration DDL."""

import pathlib
import subprocess
import sys

_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def test_schema_doc_is_current() -> None:
    """Regenerating docs/SCHEMA.md would change nothing."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT / "schema_doc.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
