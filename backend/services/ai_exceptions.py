"""AI 服务异常层次 — 替代原先的 "（...）" 字符串约定"""

from typing import Optional


class AIServiceError(Exception):
    """AI 服务异常的基类"""
    def __init__(self, message: str, *, provider_name: str = "", function_key: str = "",
                 original_exception: Optional[Exception] = None) -> None:
        super().__init__(message)
        self.provider_name = provider_name
        self.function_key = function_key
        self.original_exception = original_exception


class AIKeyError(AIServiceError):
    """API Key 未配置或无效"""
    pass


class AIProviderError(AIServiceError):
    """供应商 API 调用失败（网络、认证、限流等）"""
    pass


class AIRateLimitError(AIServiceError):
    """被供应商限流"""
    pass


class AIResponseError(AIServiceError):
    """AI 响应异常（空响应、格式错误等）"""
    pass


class AIConfigError(AIServiceError):
    """配置错误（不支持的供应商、参数缺失等）"""
    pass
