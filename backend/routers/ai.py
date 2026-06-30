"""AI 对话路由"""

import json as _json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import query_all, query_one, execute
from services.ai_service import ai_chat, ai_chat_stream
from services.ai_exceptions import AIServiceError
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

    # 拼接系统提示词
    full_system = req.systemPrompt

    # 调用 AI
    try:
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
    except AIServiceError as e:
        return {"error": str(e), "conversationId": conv_id}

    # 存 AI 回复
    execute(
        "INSERT INTO ai_messages (conversation_id, role, content, model) VALUES (?, ?, ?, ?)",
        (conv_id, "assistant", reply, req.model or None),
    )

    return {"conversationId": conv_id, "reply": reply}


@router.post("/chat/stream")
@limiter_ai.limit("20/minute")
async def chat_stream(req: ChatRequest, request: Request):
    """AI 对话（SSE 流式）— 逐 token 推送到前端"""
    conv_id = req.conversationId
    if not conv_id:
        result = execute(
            "INSERT INTO ai_conversations (user_id, title) VALUES (?, ?)",
            (get_current_user_id(), req.message[:50]),
        )
        conv_id = result["lastrowid"]

    # 加载历史 + 插入用户消息
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

    full_system = req.systemPrompt

    async def generate():
        full_reply = ""
        had_error = False
        try:
            async for chunk in ai_chat_stream(
                req.message,
                history,
                function="chat",
                provider=req.provider,
                api_key=req.apiKey,
                model=req.model,
                base_url=req.baseUrl,
                system_prompt=full_system,
            ):
                full_reply += chunk
                yield f"data: {_json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
        except AIServiceError as e:
            had_error = True
            yield f"data: {_json.dumps({'error': str(e), 'provider': e.provider_name}, ensure_ascii=False)}\n\n"
        except Exception as e:
            had_error = True
            yield f"data: {_json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            # 仅在无错误时保存完整回复
            if full_reply and not had_error:
                execute(
                    "INSERT INTO ai_messages (conversation_id, role, content, model) VALUES (?, ?, ?, ?)",
                    (conv_id, "assistant", full_reply, req.model or None),
                )
        yield f"data: {_json.dumps({'done': True, 'conversationId': conv_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )


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
