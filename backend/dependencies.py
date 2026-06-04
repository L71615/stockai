"""FastAPI 依赖注入 — 用户身份 / 配置等

当前为单用户模式（user_id 固定为 1），后续接入 JWT 时只需修改此模块。
"""


def get_current_user_id() -> int:
    """获取当前登录用户 ID

    TODO: 接入 JWT 后，从 Request.headers 解析 token 并返回真实用户 ID。
    当前为单用户模式，固定返回 1。
    """
    return 1
