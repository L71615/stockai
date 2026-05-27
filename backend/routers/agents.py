"""Agent 工坊路由"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_all, query_one, execute

router = APIRouter()


class AgentBody(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = ""
    tools: str = "[]"  # JSON array string


@router.get("/agents")
def list_agents():
    return query_all("SELECT * FROM agents ORDER BY id ASC")


@router.post("/agents")
def create_agent(body: AgentBody):
    result = execute(
        "INSERT INTO agents (name, description, system_prompt, tools) VALUES (?, ?, ?, ?)",
        (body.name, body.description, body.system_prompt, body.tools),
    )
    return {"id": result["lastrowid"], "message": "Agent 创建成功"}


@router.put("/agents/{agent_id}")
def update_agent(agent_id: int, body: AgentBody):
    row = query_one("SELECT id FROM agents WHERE id = ?", (agent_id,))
    if not row:
        raise HTTPException(404, "Agent 不存在")
    execute(
        """UPDATE agents SET name=?, description=?, system_prompt=?, tools=?,
           updated_at=datetime('now','localtime') WHERE id=?""",
        (body.name, body.description, body.system_prompt, body.tools, agent_id),
    )
    return {"message": "Agent 已更新"}


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: int):
    execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    return {"message": "Agent 已删除"}
