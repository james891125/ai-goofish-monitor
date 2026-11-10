"""
環境變數管理器
負責讀取和更新 .env 檔案，並在讀取時回退到執行時環境變數
"""
import os
import re
from typing import Dict, List, Optional
from pathlib import Path

from dotenv import dotenv_values


_PLAIN_ENV_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_./:-]+$")


class EnvManager:
    """環境變數管理器"""

    def __init__(self, env_file: str = ".env"):
        self.env_file = Path(env_file)
        self._ensure_env_file_exists()

    def _ensure_env_file_exists(self):
        """確保 .env 檔案存在"""
        if not self.env_file.exists():
            self.env_file.touch()

    def read_env(self) -> Dict[str, str]:
        """讀取所有環境變數"""
        if not self.env_file.exists():
            return {}

        loaded = dotenv_values(self.env_file, encoding="utf-8")
        return {
            key: value
            for key, value in loaded.items()
            if key and value is not None
        }

    def get_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """獲取單個環境變數的值，優先讀取 .env，缺失時再回退到執行時環境變數"""
        env_vars = self.read_env()
        if key in env_vars:
            return env_vars[key]

        runtime_value = os.getenv(key)
        if runtime_value is not None:
            return runtime_value

        return default

    def update_values(self, updates: Dict[str, str]) -> bool:
        """批次更新環境變數"""
        return self.apply_changes(updates=updates)

    def apply_changes(
        self,
        updates: Dict[str, str],
        deletions: List[str] | None = None,
    ) -> bool:
        """批次更新並刪除環境變數"""
        try:
            existing_vars = self.read_env()
            existing_vars.update(updates)
            for key in deletions or []:
                existing_vars.pop(key, None)
            return self._write_env(existing_vars)
        except Exception as e:
            print(f"更新環境變數失敗: {e}")
            return False

    def set_value(self, key: str, value: str) -> bool:
        """設定單個環境變數"""
        return self.update_values({key: value})

    def delete_keys(self, keys: List[str]) -> bool:
        """刪除指定的環境變數"""
        try:
            existing_vars = self.read_env()
            for key in keys:
                existing_vars.pop(key, None)
            return self._write_env(existing_vars)
        except Exception as e:
            print(f"刪除環境變數失敗: {e}")
            return False

    def _write_env(self, env_vars: Dict[str, str]) -> bool:
        """寫入環境變數到檔案"""
        try:
            with open(self.env_file, 'w', encoding='utf-8') as f:
                for key, value in env_vars.items():
                    f.write(f"{key}={self._serialize_value(value)}\n")
            return True
        except Exception as e:
            print(f"寫入 .env 檔案失敗: {e}")
            return False

    def _serialize_value(self, value: str) -> str:
        text = str(value)
        if text == "":
            return ""
        if _PLAIN_ENV_VALUE_PATTERN.fullmatch(text):
            return text
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'


# 全域實例
env_manager = EnvManager()
