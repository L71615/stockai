"""StockAI — AI 模型服务

支持的供应商：MiniMax / Claude / OpenAI / OpenAI 兼容
"""

import json as _json
import logging
from typing import AsyncGenerator

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from .ai_exceptions import AIServiceError, AIKeyError, AIProviderError, AIRateLimitError, AIResponseError, AIConfigError

logger = logging.getLogger("stockai")

from config import (
    AI_PROVIDER, CLAUDE_API_KEY, CLAUDE_MODEL,
    OPENAI_API_KEY, MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_BASE_URL,
    DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL,
    XIAOMI_API_KEY, XIAOMI_MODEL, XIAOMI_BASE_URL,
)

_openai_clients: dict[str, AsyncOpenAI] = {}
_anthropic_client: AsyncAnthropic | None = None


def _get_openai_client(api_key: str, base_url: str) -> AsyncOpenAI:
    cache_key = f"{api_key}@{base_url}"
    if cache_key not in _openai_clients:
        _openai_clients[cache_key] = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return _openai_clients[cache_key]


_last_anthropic_key: str = ""

def _get_anthropic_client(api_key: str) -> AsyncAnthropic:
    global _anthropic_client, _last_anthropic_key
    if _anthropic_client is None or api_key != _last_anthropic_key:
        _anthropic_client = AsyncAnthropic(api_key=api_key)
        _last_anthropic_key = api_key
    return _anthropic_client



async def _chat_openai_compatible(
    messages: list[dict], *, api_key: str, base_url: str, model: str,
    system_prompt: str = "",
) -> str:
    client = _get_openai_client(api_key, base_url)
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)
    response = await client.chat.completions.create(model=model, messages=full_messages)
    return response.choices[0].message.content


async def _chat_openai_compatible_stream(
    messages: list[dict], *, api_key: str, base_url: str, model: str,
    system_prompt: str = "",
) -> AsyncGenerator[str, None]:
    """OpenAI 兼容流式输出 — 逐 token yield 文本"""
    client = _get_openai_client(api_key, base_url)
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)
    stream = await client.chat.completions.create(model=model, messages=full_messages, stream=True)
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


PROVIDER_DEFAULTS = {
    "minimax":  (MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_BASE_URL, "MiniMax"),
    "deepseek": (DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL, "DeepSeek"),
    "xiaomi":   (XIAOMI_API_KEY, XIAOMI_MODEL, XIAOMI_BASE_URL, "小米"),
    "openai":   (OPENAI_API_KEY, "gpt-4o", "https://api.openai.com/v1", "OpenAI"),
}


async def _chat_openai_provider(
    messages: list[dict], provider_key: str,
    *, api_key: str = "", model: str = "", system_prompt: str = "",
) -> str:
    """通用 OpenAI 兼容供应商调用"""
    env_key, default_model, base_url, name = PROVIDER_DEFAULTS[provider_key]
    key = api_key or env_key
    if not key:
        raise AIKeyError(f"未配置 {name} API Key，请在设置页配置", provider_name=name)
    m = model or default_model
    try:
        return await _chat_openai_compatible(messages, api_key=key, base_url=base_url, model=m, system_prompt=system_prompt)
    except AIServiceError:
        raise
    except Exception as e:
        err_msg = str(e)
        # 避免编码错误导致无法显示
        try:
            err_msg = err_msg.encode("ascii", errors="replace").decode("ascii")
        except Exception:
            err_msg = "未知错误"
        raise AIProviderError(f"{name} API 调用失败: {err_msg}", provider_name=name, original_exception=e) from e


async def _chat_openai_provider_stream(
    messages: list[dict], provider_key: str,
    *, api_key: str = "", model: str = "", system_prompt: str = "",
) -> AsyncGenerator[str, None]:
    """通用 OpenAI 兼容供应商 — 流式"""
    env_key, default_model, base_url, name = PROVIDER_DEFAULTS[provider_key]
    key = api_key or env_key
    if not key:
        raise AIKeyError(f"未配置 {name} API Key，请在设置页配置", provider_name=name)
    m = model or default_model
    try:
        async for chunk in _chat_openai_compatible_stream(messages, api_key=key, base_url=base_url, model=m, system_prompt=system_prompt):
            yield chunk
    except AIServiceError:
        raise
    except Exception as e:
        raise AIProviderError(f"{name} API 流式调用失败: {e}", provider_name=name, original_exception=e) from e


async def chat_with_claude(messages: list[dict], *, system_prompt: str = "", api_key: str = "", model: str = "") -> str:
    key = api_key or CLAUDE_API_KEY
    if not key:
        raise AIKeyError("未配置 Claude API Key，请在设置页配置", provider_name="Claude")
    m = model or CLAUDE_MODEL
    try:
        client = _get_anthropic_client(key)
        response = await client.messages.create(
            model=m, max_tokens=4096,
            system=system_prompt, messages=messages,
        )
        if response.content and len(response.content) > 0:
            return response.content[0].text
        raise AIResponseError("Claude 返回空响应", provider_name="Claude")
    except AIServiceError:
        raise
    except ImportError:
        raise AIConfigError("请先安装 anthropic SDK: pip install anthropic", provider_name="Claude")
    except Exception as e:
        raise AIProviderError(f"Claude API 调用失败: {e}", provider_name="Claude", original_exception=e) from e


async def chat_with_claude_stream(
    messages: list[dict], *, system_prompt: str = "", api_key: str = "", model: str = ""
) -> AsyncGenerator[str, None]:
    """Claude 流式输出 — 逐 token yield 文本"""
    key = api_key or CLAUDE_API_KEY
    if not key:
        raise AIKeyError("未配置 Claude API Key，请在设置页配置", provider_name="Claude")
    m = model or CLAUDE_MODEL
    try:
        client = _get_anthropic_client(key)
        async with client.messages.stream(
            model=m, max_tokens=4096,
            system=system_prompt, messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except AIServiceError:
        raise
    except ImportError:
        raise AIConfigError("请先安装 anthropic SDK: pip install anthropic", provider_name="Claude")
    except Exception as e:
        raise AIProviderError(f"Claude API 流式调用失败: {e}", provider_name="Claude", original_exception=e) from e


def get_default_provider() -> str:
    """获取用户保存的默认 AI 供应商

    优先级：settings 表 ai_config.default_provider → 环境变量 AI_PROVIDER → "deepseek"
    当 function_providers 未配置时，所有功能回退到此默认值。
    """
    try:
        from database import query_one
        import json as _json
        row = query_one("SELECT value FROM settings WHERE key = 'ai_config'")
        if row and row.get("value"):
            cfg = _json.loads(row["value"])
            if isinstance(cfg, dict) and cfg.get("default_provider"):
                return cfg["default_provider"]
    except Exception:
        logger.debug("get_default_provider: settings read failed, using env fallback")
    return AI_PROVIDER or "deepseek"


def get_provider_for_function(function_key: str) -> str:
    """按功能解析供应商 — 读取 settings 表 function_providers 映射

    优先级：function_providers[function_key] → default_provider → 环境变量 → "deepseek"
    用户在设置页可以为每个 AI 功能独立指定供应商。
    """
    try:
        from database import query_one
        import json as _json
        row = query_one("SELECT value FROM settings WHERE key = 'ai_config'")
        if row and row.get("value"):
            cfg = _json.loads(row["value"])
            if isinstance(cfg, dict):
                fp = cfg.get("function_providers", {})
                if isinstance(fp, dict) and function_key in fp and fp[function_key]:
                    return fp[function_key]
    except Exception:
        logger.debug("get_provider_for_function: settings read failed")
    return get_default_provider()


async def ai_chat(
    message: str,
    conversation_history: list[dict] = None,
    *,
    provider: str = "",
    function: str = "",
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    system_prompt: str = "",
) -> str:
    """统一的 AI 对话入口（多供应商调度）

    provider 为空时自动用 get_default_provider()（用户设置 > 环境变量）。
    如果提供了 function 参数，优先从 function_providers 映射查找供应商。
    api_key/model 为空时，自动从 settings 表读取该供应商的保存配置。
    """
    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": message})

    # 参数为空时，从设置页读取用户保存的配置
    if not provider and function:
        provider = get_provider_for_function(function)
    p = provider or get_default_provider()
    if not api_key or not model:
        stored = _load_stored_ai_config(p)
        api_key = api_key or stored.get("api_key", "")
        model = model or stored.get("model", "")
        base_url = base_url or stored.get("base_url", "")

    if p in PROVIDER_DEFAULTS:
        return await _chat_openai_provider(messages, p, api_key=api_key, model=model, system_prompt=system_prompt)
    elif p == "claude":
        return await chat_with_claude(messages, api_key=api_key, model=model, system_prompt=system_prompt)
    elif p == "custom":
        if not base_url:
            raise AIConfigError("使用自定义供应商请填写 Base URL", provider_name="custom")
        m = model or "gpt-4o"
        try:
            return await _chat_openai_compatible(messages, api_key=api_key, base_url=base_url, model=m, system_prompt=system_prompt)
        except AIServiceError:
            raise
        except Exception as e:
            raise AIProviderError(f"自定义 API 调用失败: {e}", provider_name="custom", original_exception=e) from e
    else:
        raise AIConfigError(f"不支持的 AI 供应商: {p}", provider_name=p)


async def ai_chat_stream(
    message: str,
    conversation_history: list[dict] = None,
    *,
    provider: str = "",
    function: str = "",
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    system_prompt: str = "",
) -> AsyncGenerator[str, None]:
    """统一的 AI 流式对话入口（多供应商调度）

    参数同 ai_chat()，但返回 AsyncGenerator，逐 token yield 文本。
    """
    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": message})

    # 参数为空时，从设置页读取用户保存的配置
    if not provider and function:
        provider = get_provider_for_function(function)
    p = provider or get_default_provider()
    if not api_key or not model:
        stored = _load_stored_ai_config(p)
        api_key = api_key or stored.get("api_key", "")
        model = model or stored.get("model", "")
        base_url = base_url or stored.get("base_url", "")

    if p in PROVIDER_DEFAULTS:
        async for chunk in _chat_openai_provider_stream(messages, p, api_key=api_key, model=model, system_prompt=system_prompt):
            yield chunk
    elif p == "claude":
        async for chunk in chat_with_claude_stream(messages, api_key=api_key, model=model, system_prompt=system_prompt):
            yield chunk
    elif p == "custom":
        if not base_url:
            raise AIConfigError("使用自定义供应商请填写 Base URL", provider_name="custom")
        m = model or "gpt-4o"
        try:
            async for chunk in _chat_openai_compatible_stream(messages, api_key=api_key, base_url=base_url, model=m, system_prompt=system_prompt):
                yield chunk
        except AIServiceError:
            raise
        except Exception as e:
            raise AIProviderError(f"自定义 API 流式调用失败: {e}", provider_name="custom", original_exception=e) from e
    else:
        raise AIConfigError(f"不支持的 AI 供应商: {p}", provider_name=p)


def _decrypt_dict(cfg: dict) -> dict:
    """递归解密 dict 中所有 api_key 字段"""
    from services.crypto_service import decrypt
    result = {}
    for k, v in cfg.items():
        if k == "api_key" and isinstance(v, str) and v:
            try:
                result[k] = decrypt(v.encode("latin-1"))
            except Exception:
                result[k] = v  # 无法解密则保留原值（兼容旧数据）
        elif isinstance(v, dict):
            result[k] = _decrypt_dict(v)
        else:
            result[k] = v
    return result


def _encrypt_dict(cfg: dict) -> dict:
    """递归加密 dict 中所有 api_key 字段"""
    from services.crypto_service import encrypt
    result = {}
    for k, v in cfg.items():
        if k == "api_key" and isinstance(v, str) and v:
            result[k] = encrypt(v).decode("latin-1")  # 存为字符串
        elif isinstance(v, dict):
            result[k] = _encrypt_dict(v)
        else:
            result[k] = v
    return result


def _load_stored_ai_config(provider: str = "") -> dict:
    """从 settings 表读取已保存的 AI 配置（自动解密 api_key）

    - 多供应商模式: {"minimax": {"api_key":"...","model":"..."}, "deepseek": {...}}
    - 旧版单配置:   {"provider":"minimax","api_key":"...","model":"..."}
    - 指定 provider 时，只返回该供应商的配置
    """
    try:
        from database import query_one
        row = query_one("SELECT value FROM settings WHERE key = 'ai_config'")
        if row and row.get("value"):
            import json as _json
            cfg = _json.loads(row["value"])
            if isinstance(cfg, dict):
                cfg = _decrypt_dict(cfg)
                # 多供应商模式
                if provider and provider in cfg and isinstance(cfg[provider], dict):
                    return cfg[provider]
                if provider and "api_key" in cfg:
                    # 旧版单配置，直接返回
                    return cfg if cfg.get("provider") == provider else {}
                # 不指定 provider，返回原始数据
                return cfg
    except Exception:
        logger.debug("load_stored_ai_config: settings read failed")
    return {}


def save_stored_ai_config(config: dict) -> None:
    """保存 AI 配置到 settings 表（自动加密 api_key）"""
    from database import execute
    import json as _json
    encrypted = _encrypt_dict(config)
    execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('ai_config', ?)",
        (_json.dumps(encrypted, ensure_ascii=False),),
    )


# ═══════════════════════════════════════════════════════════════
#  v4.0 A2 — Agent 工具调用 (OpenAI / Anthropic tool_use 协议)
#  工具通过 backend/services/agent_tools.py 注册,本模块只负责
#  (1) 把 OpenAI 工具 schema 投递给 LLM
#  (2) 解析 LLM 返回的 tool_calls
#  (3) 拼接消息历史执行调用循环(最多 5 轮)
#
#  设计原则:
#  - 不破坏现有 ai_chat / chat_with_claude 的纯文本 API
#  - 工具调用循环统一由 ai_chat_with_tools() 编排
#  - schema 以 OpenAI 格式为标准,Anthropic 通过 to_anthropic_tools() 转换
# ═══════════════════════════════════════════════════════════════

import json as _json_tool


async def _chat_openai_compatible_with_tools(
    messages: list[dict],
    tools: list[dict],
    *,
    api_key: str, base_url: str, model: str,
    system_prompt: str = "",
) -> dict:
    """OpenAI 兼容协议 + tools 参数

    Returns:
        {
            "text": str,            # 文本回复(可能为空)
            "tool_calls": [         # 工具调用列表(可能为空)
                {"id": "...", "name": "...", "arguments": {...}}
            ],
            "raw_message": dict,    # 完整 assistant message,用于拼接历史
        }
    """
    client = _get_openai_client(api_key, base_url)
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    response = await client.chat.completions.create(
        model=model,
        messages=full_messages,
        tools=tools,
    )
    msg = response.choices[0].message
    text = msg.content or ""
    tool_calls: list[dict] = []
    raw_calls = msg.tool_calls or []
    for tc in raw_calls:
        try:
            args = _json_tool.loads(tc.function.arguments) if tc.function.arguments else {}
        except _json_tool.JSONDecodeError:
            args = {"_raw": tc.function.arguments}
        tool_calls.append({
            "id": tc.id,
            "name": tc.function.name,
            "arguments": args,
        })

    # 构造完整 assistant raw_message(用于下次请求拼接)
    raw_message: dict = {"role": "assistant", "content": text}
    if raw_calls:
        raw_message["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            }
            for tc in raw_calls
        ]

    return {"text": text, "tool_calls": tool_calls, "raw_message": raw_message}


async def _chat_openai_provider_with_tools(
    messages: list[dict],
    tools: list[dict],
    provider_key: str,
    *,
    api_key: str = "", model: str = "", system_prompt: str = "",
) -> dict:
    """通用 OpenAI 兼容供应商 + tools"""
    env_key, default_model, base_url, name = PROVIDER_DEFAULTS[provider_key]
    key = api_key or env_key
    if not key:
        raise AIKeyError(f"未配置 {name} API Key,请在设置页配置", provider_name=name)
    m = model or default_model
    try:
        return await _chat_openai_compatible_with_tools(
            messages, tools,
            api_key=key, base_url=base_url, model=m, system_prompt=system_prompt,
        )
    except AIServiceError:
        raise
    except Exception as e:
        raise AIProviderError(f"{name} API 调用失败: {e}", provider_name=name, original_exception=e) from e


async def chat_with_claude_with_tools(
    messages: list[dict],
    tools: list[dict],
    *,
    system_prompt: str = "", api_key: str = "", model: str = "",
    anthropic_tools: list[dict] | None = None,
) -> dict:
    """Claude + Anthropic tool_use 协议

    Args:
        anthropic_tools: 已转换为 Anthropic 格式的工具 schema(可选);
                       若为空,自动从 OpenAI 格式转换(需先 import agent_tools)
    """
    if anthropic_tools is None:
        try:
            from services.agent_tools import to_anthropic_tools
            anthropic_tools = to_anthropic_tools(tools)
        except ImportError:
            anthropic_tools = []

    key = api_key or CLAUDE_API_KEY
    if not key:
        raise AIKeyError("未配置 Claude API Key,请在设置页配置", provider_name="Claude")
    m = model or CLAUDE_MODEL

    try:
        client = _get_anthropic_client(key)
        kwargs = {
            "model": m,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": messages,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        response = await client.messages.create(**kwargs)

        text = ""
        tool_calls: list[dict] = []
        content_blocks: list[dict] = []
        for block in response.content or []:
            btype = getattr(block, "type", None)
            if btype == "text":
                text += block.text
                content_blocks.append({"type": "text", "text": block.text})
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input or {},
                })
                content_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input or {},
                })

        raw_message = {"role": "assistant", "content": content_blocks}
        return {"text": text, "tool_calls": tool_calls, "raw_message": raw_message}
    except AIServiceError:
        raise
    except ImportError:
        raise AIConfigError("请先安装 anthropic SDK: pip install anthropic", provider_name="Claude")
    except Exception as e:
        raise AIProviderError(f"Claude API 调用失败: {e}", provider_name="Claude", original_exception=e) from e


async def ai_chat_with_tools(
    message: str,
    tools: list[dict],
    *,
    provider: str = "",
    function: str = "",
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    system_prompt: str = "",
    max_iterations: int = 5,
) -> dict:
    """统一 AI 工具调用入口(多供应商 + 工具调用循环)

    Args:
        message: 用户消息
        tools: OpenAI 格式工具 schema 列表
        max_iterations: 最大工具调用轮数(防止死循环),默认 5

    Returns:
        {
            "text": 最终文本回复,
            "tool_calls": [{"name", "arguments", "result"}],  # 实际执行的工具
            "iterations": 实际迭代次数,
            "finished": bool,  # True=正常结束, False=达到 max_iterations
        }
    """
    if not tools:
        # 没有工具时直接退化为普通对话
        text = await ai_chat(
            message,
            provider=provider, function=function,
            api_key=api_key, model=model, base_url=base_url,
            system_prompt=system_prompt,
        )
        return {"text": text, "tool_calls": [], "iterations": 1, "finished": True}

    # 解析供应商
    if not provider and function:
        provider = get_provider_for_function(function)
    p = provider or get_default_provider()
    if not api_key or not model:
        stored = _load_stored_ai_config(p)
        api_key = api_key or stored.get("api_key", "")
        model = model or stored.get("model", "")
        base_url = base_url or stored.get("base_url", "")

    # 导入工具执行器
    from services.agent_tools import execute_tool_call

    messages: list[dict] = [{"role": "user", "content": message}]
    executed_tool_calls: list[dict] = []
    iterations = 0
    finished = False

    for i in range(max_iterations):
        iterations = i + 1

        # ── 调用 LLM ──
        if p in PROVIDER_DEFAULTS:
            response = await _chat_openai_provider_with_tools(
                messages, tools, p,
                api_key=api_key, model=model, system_prompt=system_prompt,
            )
        elif p == "claude":
            response = await chat_with_claude_with_tools(
                messages, tools,
                system_prompt=system_prompt,
                api_key=api_key, model=model,
            )
        elif p == "custom":
            if not base_url:
                raise AIConfigError("使用自定义供应商请填写 Base URL", provider_name="custom")
            m = model or "gpt-4o"
            try:
                response = await _chat_openai_compatible_with_tools(
                    messages, tools,
                    api_key=api_key, base_url=base_url, model=m, system_prompt=system_prompt,
                )
            except AIServiceError:
                raise
            except Exception as e:
                raise AIProviderError(f"自定义 API 调用失败: {e}", provider_name="custom", original_exception=e) from e
        else:
            raise AIConfigError(f"不支持的 AI 供应商: {p}", provider_name=p)

        # ── 拼接助手消息 ──
        messages.append(response["raw_message"])

        # ── 无工具调用,正常结束 ──
        if not response["tool_calls"]:
            return {
                "text": response["text"],
                "tool_calls": executed_tool_calls,
                "iterations": iterations,
                "finished": True,
            }

        # ── 执行每个工具调用 ──
        if p == "claude":
            # Anthropic: tool_results 合并在一个 user 消息里
            tool_results_blocks: list[dict] = []
            for tc in response["tool_calls"]:
                result = execute_tool_call(tc["name"], tc["arguments"])
                executed_tool_calls.append({
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                    "result": result,
                })
                tool_results_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": _json_tool.dumps(result, ensure_ascii=False),
                })
            messages.append({"role": "user", "content": tool_results_blocks})
        else:
            # OpenAI: 每个 tool_call 独立一条 tool 消息
            for tc in response["tool_calls"]:
                result = execute_tool_call(tc["name"], tc["arguments"])
                executed_tool_calls.append({
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                    "result": result,
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": _json_tool.dumps(result, ensure_ascii=False),
                })

    # 达到 max_iterations 仍未完成 → 返回最后一次文本 + 已执行的工具
    finished = False
    last_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content")
            if isinstance(content, str):
                last_text = content
            elif isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        last_text += blk.get("text", "")
            break

    return {
        "text": last_text,
        "tool_calls": executed_tool_calls,
        "iterations": iterations,
        "finished": finished,
    }
