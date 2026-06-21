"""FastAPI 依赖注入 — 用户身份 / 配置等

当前为单用户模式（user_id 固定为 CURRENT_USER_ID），后续接入多用户时改为从 JWT 解析。
"""

# ═══════════════════════════════════════════════════════════
# ⚠️ 重要：默认用户 ID 配置
# ═══════════════════════════════════════════════════════════
# 系统默认为 admin 用户（user_id = 2）。
# 如需修改为其他用户，请先在数据库中确认目标用户的 id 值，
# 然后将下方的 CURRENT_USER_ID 改为对应数字。
#
# 查询用户 ID：sqlite2 "D:\stocks\database\stockai.db" "SELECT id, username FROM users;"
# ═══════════════════════════════════════════════════════════

CURRENT_USER_ID = 2


def get_current_user_id() -> int:
    """获取当前登录用户 ID

    单用户模式：直接返回 CURRENT_USER_ID。
    后续接入多用户时，从 Request.headers 解析 JWT token 并返回真实用户 ID。
    """
    return CURRENT_USER_ID
