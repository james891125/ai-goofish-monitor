class RiskControlError(Exception):
    """蝦皮要求人機驗證或拒絕請求。"""


class LoginRequiredError(Exception):
    """登入狀態失效或不存在，需要重新貼上 Cookie。"""
