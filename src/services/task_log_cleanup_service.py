"""
任務執行日誌清理服務。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


def cleanup_task_logs(
    logs_dir: str = "logs",
    *,
    keep_days: int = 7,
    now: datetime | None = None,
) -> list[str]:
    if keep_days < 1:
        print(f"任務日誌清理已跳過：保留天數配置無效 ({keep_days})")
        return []

    root = Path(logs_dir)
    if not root.exists():
        return []

    current_time = now or datetime.now()
    cutoff = current_time - timedelta(days=keep_days)
    removed_files: list[str] = []

    for path in root.glob("*.log"):
        if not path.is_file():
            continue
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError as exc:
            print(f"讀取任務日誌時間失敗，已跳過: {path} ({exc})")
            continue

        if modified_at >= cutoff:
            continue

        try:
            path.unlink()
            removed_files.append(str(path))
        except OSError as exc:
            print(f"刪除歷史任務日誌失敗，已跳過: {path} ({exc})")

    if removed_files:
        print(
            f"任務日誌清理完成：已刪除 {len(removed_files)} 個超過 {keep_days} 天的歷史日誌檔案。"
        )

    return removed_files
