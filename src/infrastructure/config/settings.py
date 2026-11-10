"""臺灣蝦皮分析使用的 OpenAI 相容服務設定。"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    """僅保存 AI 用戶端使用的設定，不建立其他服務或檔案。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
        populate_by_name=True,
    )

    api_key: str | None = Field(None, validation_alias="OPENAI_API_KEY", repr=False)
    base_url: str = Field("", validation_alias="OPENAI_BASE_URL")
    model_name: str = Field("", validation_alias="OPENAI_MODEL_NAME")
    proxy_url: str | None = Field(None, validation_alias="PROXY_URL", repr=False)
    enable_response_format: bool = Field(True, validation_alias="ENABLE_RESPONSE_FORMAT")

    def is_configured(self) -> bool:
        """判斷必要的連線設定是否已填寫，不代表已成功連線。"""
        return all(isinstance(value, str) and bool(value.strip())
                   for value in (self.api_key, self.base_url, self.model_name))
