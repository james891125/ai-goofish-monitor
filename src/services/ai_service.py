"""
AI 分析服務
封裝 AI 分析相關的業務邏輯
"""
from typing import Dict, List, Optional
from src.infrastructure.external.ai_client import AIClient


class AIAnalysisService:
    """AI 分析服務"""

    def __init__(self, ai_client: AIClient):
        self.ai_client = ai_client

    async def analyze_product(
        self,
        product_data: Dict,
        image_paths: List[str],
        prompt_text: str
    ) -> Optional[Dict]:
        """
        分析商品

        Args:
            product_data: 商品資料
            image_paths: 圖片路徑列表
            prompt_text: 分析提示詞

        Returns:
            分析結果
        """
        if not self.ai_client.is_available():
            print("AI 客戶端不可用，跳過分析")
            return None

        try:
            result = await self.ai_client.analyze(product_data, image_paths, prompt_text)

            if result and self._validate_result(result):
                return result
            else:
                print("AI 分析結果驗證失敗")
                return None
        except Exception as e:
            print(f"AI 分析服務出錯: {e}")
            return None

    def _validate_result(self, result: Dict) -> bool:
        """驗證 AI 分析結果的格式"""
        required_fields = [
            "prompt_version",
            "is_recommended",
            "reason",
            "risk_tags",
            "criteria_analysis"
        ]

        # 檢查必需欄位
        for field in required_fields:
            if field not in result:
                print(f"AI 響應缺少必需欄位: {field}")
                return False

        # 檢查資料型別
        if not isinstance(result.get("is_recommended"), bool):
            print("is_recommended 欄位不是布林型別")
            return False

        if not isinstance(result.get("risk_tags"), list):
            print("risk_tags 欄位不是列表型別")
            return False

        criteria_analysis = result.get("criteria_analysis", {})
        if not isinstance(criteria_analysis, dict) or not criteria_analysis:
            print("criteria_analysis 必須是非空字典")
            return False

        return True
