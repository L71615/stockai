"""Skills 管理路由"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_all, execute

router = APIRouter()

# Skills 列表 — 当前为空，后续从 skills/ 目录动态扫描加载
AVAILABLE_SKILLS: list[dict] = []


@router.get("")
def list_skills():
    """获取所有 Skills（含安装状态）"""
    installed = query_all("SELECT skill_id, enabled FROM installed_skills WHERE user_id = 1")
    installed_map = {s["skill_id"]: s["enabled"] for s in installed}

    return [
        {**s, "installed": s["id"] in installed_map, "enabled": installed_map.get(s["id"], 0) == 1}
        for s in AVAILABLE_SKILLS
    ]


@router.get("/installed")
def installed_skills():
    return query_all("SELECT * FROM installed_skills WHERE user_id = 1 AND enabled = 1")


class SkillInstallBody(BaseModel):
    skillId: str


@router.post("/install")
def install_skill(body: SkillInstallBody):
    skill = next((s for s in AVAILABLE_SKILLS if s["id"] == body.skillId), None)
    if not skill:
        raise HTTPException(404, "Skill 不存在")

    execute(
        "INSERT OR REPLACE INTO installed_skills (user_id, skill_id, skill_name, version, enabled) VALUES (1, ?, ?, ?, 1)",
        (skill["id"], skill["name"], skill["version"]),
    )
    return {"message": f"{skill['name']} 安装成功"}


@router.post("/uninstall")
def uninstall_skill(body: SkillInstallBody):
    execute("DELETE FROM installed_skills WHERE user_id = 1 AND skill_id = ?", (body.skillId,))
    return {"message": "已卸载"}


class SkillToggleBody(BaseModel):
    skillId: str
    enabled: bool


@router.post("/toggle")
def toggle_skill(body: SkillToggleBody):
    execute(
        "UPDATE installed_skills SET enabled = ? WHERE user_id = 1 AND skill_id = ?",
        (1 if body.enabled else 0, body.skillId),
    )
    return {"message": "已启用" if body.enabled else "已禁用"}
