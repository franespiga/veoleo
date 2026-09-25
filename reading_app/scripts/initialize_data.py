"""Create starter Excel files and the default SQLite profile."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database_manager import DatabaseManager  # noqa: E402
from src.word_loader import ensure_vocabulary_files  # noqa: E402


def main() -> None:
    data_dir = ROOT / "data"
    ensure_vocabulary_files(data_dir)
    manager = DatabaseManager(data_dir)
    manager.ensure_ready()
    print(f"Vocabulario en {data_dir}")
    print(f"Base activa: {manager.active_path()}")


if __name__ == "__main__":
    main()
