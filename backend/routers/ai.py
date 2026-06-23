"""AI 对话路由"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from database import query_all, query_one, execute
from services.ai_service import ai_chat
from routers.memory import load_memory
from services.rate_limit import limiter_ai
from dependencies import get_current_user_id

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    conversationId: int | None = None
    agentId: int | None = None     # 选择的 Agent ID，用于加载记忆
    provider: str = ""       # 留空从 settings 读取
    apiKey: str = ""         # 留空从 settings 读取（推荐：保存后不传）
    model: str = ""          # 留空使用默认模型
    baseUrl: str = ""        # 自定义 base URL（provider=custom 时使用）
    systemPrompt: str = ""   # Agent 系统提示词


@router.post("/chat")
@limiter_ai.limit("20/minute")
async def chat(req: ChatRequest, request: Request):
    """AI 对话（非流式）"""
    conv_id = req.conversationId
    if not conv_id:
        result = execute(
            "INSERT INTO ai_conversations (user_id, title) VALUES (?, ?)",
            (get_current_user_id(), req.message[:50]),
        )
        conv_id = result["lastrowid"]

    # 先加载历史消息（当前会话的最近 20 轮），再插入用户消息
    history_rows = query_all(
        """SELECT role, content FROM ai_messages
           WHERE conversation_id = ?
           ORDER BY created_at ASC
           LIMIT 40""",
        (conv_id,),
    )
    history = [{"role": r["role"], "content": r["content"]} for r in history_rows]

    execute(
        "INSERT INTO ai_messages (conversation_id, role, content) VALUES (?, ?, ?)",
        (conv_id, "user", req.message),
    )

    # 加载 Agent 记忆
    memory_text = ""
    if req.agentId:
        agent_row = query_one("SELECT name FROM agents WHERE id = ?", (req.agentId,))
        if agent_row:
            memory_text = load_memory(req.agentId, agent_row["name"])

    # 拼接系统提示词（Agent 提示词 + 记忆）
    full_system = req.systemPrompt
    if memory_text:
        full_system += f"\n\n## 你的历史记忆\n{memory_text}"

    # 调用 AI
    reply = await ai_chat(
        req.message,
        history,
        function="chat",
        provider=req.provider,
        api_key=req.apiKey,
        model=req.model,
        base_url=req.baseUrl,
        system_prompt=full_system,
    )

    # 存 AI 回复
    execute(
        "INSERT INTO ai_messages (conversation_id, role, content, model) VALUES (?, ?, ?, ?)",
        (conv_id, "assistant", reply, req.model or None),
    )

    return {"conversationId": conv_id, "reply": reply}


@router.get("/conversations")
def list_conversations():
    return query_all(
        "SELECT * FROM ai_conversations WHERE user_id = ? ORDER BY created_at DESC",
        (get_current_user_id(),)
    )


@router.get("/conversations/{conv_id}")
def get_conversation(conv_id: int):
    conv = query_one(
        "SELECT * FROM ai_conversations WHERE id = ? AND user_id = ?", (conv_id, get_current_user_id())
    )
    if not conv:
        raise HTTPException(404, "会话不存在")
    messages = query_all(
        "SELECT * FROM ai_messages WHERE conversation_id = ? ORDER BY created_at ASC",
        (conv_id,),
    )
    return {"conversation": conv, "messages": messages}


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: int):
    execute("DELETE FROM ai_conversations WHERE id = ? AND user_id = ?", (conv_id, get_current_user_id()))
    return {"message": "已删除"}
