"""FastAPI 依赖注入 — 用户身份 / 配置等

通过 ContextVar 在线程/coroutine 间传递当前用户 ID。
Auth 中间件负责解析 JWT 并设置 user_id，业务代码直接调用 get_current_user_id() 即可。
"""

from contextvars import ContextVar

_current_user_id: ContextVar[int] = ContextVar("current_user_id", default=1)


def get_current_user_id() -> int:
    """获取当前登录用户 ID（从中间件设置的 ContextVar 读取）。

    中间件从 JWT token 解析 user_id 并存入当前 context，
    业务代码无需传参即可获取真实用户 ID。
    """
    return _current_user_id.get()
