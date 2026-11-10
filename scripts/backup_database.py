"""Create an independent SQLite backup, including committed WAL transactions."""
from __future__ import annotations

import argparse
from contextlib import closing
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def backup_database(source: Path, destination: Path) -> Path:
    source, destination = source.resolve(), destination.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"找不到資料庫：{source}")
    if source == destination:
        raise ValueError("備份目的地不得與原始資料庫相同。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting any existing user data.
    with destination.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("備份完整性檢查失敗。")
    except BaseException:
        destination.unlink(missing_ok=True)  # Only the file this call exclusively created.
        raise
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="建立包含已提交 WAL 資料的 SQLite 一致性備份，不覆寫既有檔案。")
    parser.add_argument("--source", type=Path, default=Path("data/app.sqlite3"))
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    destination = args.destination or Path("backups") / f"app-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.sqlite3"
    try:
        target = backup_database(args.source, destination)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"備份失敗：{exc}\n")
    print(f"備份完成：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
