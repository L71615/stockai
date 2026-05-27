"""Agent 记忆系统路由

每个 Agent 独立 .md 记忆文件，存储在 backend/memory/ 目录下。
每次对话时自动注入到系统提示词。
"""

import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_one

router = APIRouter()
MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"

MEMORY_TEMPLATE = """---
agent_id: {agent_id}
agent_name: {agent_name}
updated: {updated}
---

# {agent_name} 记忆

"""


def _memory_path(agent_id: int) -> Path:
    return MEMORY_DIR / f"agent_{agent_id}.md"


def _ensure_memory(agent_id: int, agent_name: str) -> Path:
    """确保记忆文件存在，不存在则创建模板"""
    path = _memory_path(agent_id)
    if not path.exists():
        path.write_text(MEMORY_TEMPLATE.format(
            agent_id=agent_id,
            agent_name=agent_name,
            updated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        ), encoding="utf-8")
    return path


def load_memory(agent_id: int, agent_name: str = "") -> str:
    """读取 Agent 记忆内容（去除 frontmatter）"""
    path = _ensure_memory(agent_id, agent_name)
    text = path.read_text(encoding="utf-8")
    # 去除 frontmatter
    text = re.sub(r'^---\n.*?\n---\n*', '', text, flags=re.DOTALL)
    return text.strip()


def append_memory(agent_id: int, agent_name: str, entry: str):
    """追加一条记忆"""
    path = _ensure_memory(agent_id, agent_name)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    text = path.read_text(encoding="utf-8")
    # 更新 frontmatter 中的 updated 时间戳
    text = re.sub(r'^updated: .*', f'updated: {timestamp}', text, flags=re.MULTILINE)
    # 追加新条目
    text += f"\n## {timestamp}\n{entry}\n"
    path.write_text(text, encoding="utf-8")


@router.get("/agents/{agent_id}/memory")
def get_memory(agent_id: int):
    row = query_one("SELECT name FROM agents WHERE id = ?", (agent_id,))
    if not row:
        raise HTTPException(404, "Agent 不存在")
    name = row["name"]
    path = _ensure_memory(agent_id, name)
    return {"agent_id": agent_id, "agent_name": name, "content": path.read_text(encoding="utf-8")}


class MemoryUpdate(BaseModel):
    entry: str


@router.post("/agents/{agent_id}/memory")
def add_memory(agent_id: int, body: MemoryUpdate):
    row = query_one("SELECT name FROM agents WHERE id = ?", (agent_id,))
    if not row:
        raise HTTPException(404, "Agent 不存在")
    append_memory(agent_id, row["name"], body.entry)
    return {"message": "记忆已保存"}
