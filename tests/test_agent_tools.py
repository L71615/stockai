"""Agent 工具调用 — v4.0 A2 单元测试

覆盖:
  - TOOL_REGISTRY / list_tool_names / get_tool_schema
  - to_anthropic_tools() 协议转换
  - execute_tool_call() 调度 + 参数解析 + 错误兜底
  - ai_chat_with_tools() 调用循环(monkeypatch LLM)
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from services.agent_tools import (
    TOOL_REGISTRY,
    TOOL_GET_QUOTE,
    TOOL_GET_FACTOR,
    TOOL_RUN_BACKTEST,
    execute_tool_call,
    get_tool_schema,
    list_tool_names,
    to_anthropic_tools,
)


# ═══════════════════════════════════════════════════════════════
#  工具注册表
# ═══════════════════════════════════════════════════════════════


class TestToolRegistry:
    def test_registry_has_four_core_tools(self):
        """phase 1 起步 4 个核心工具(get_quote / get_factor / run_backtest / calc_t1_cost)"""
        names = list_tool_names()
        assert set(names) == {"get_quote", "get_factor", "run_backtest", "calc_t1_cost"}
        assert len(names) == 4

    def test_registry_schemas_are_openai_format(self):
        """所有 schema 都是 OpenAI 协议"""
        for name in list_tool_names():
            schema = get_tool_schema(name)
            assert schema["type"] == "function"
            assert "function" in schema
            fn = schema["function"]
            assert fn["name"] == name
            assert "description" in fn
            assert "parameters" in fn
            assert fn["parameters"]["type"] == "object"

    def test_get_tool_schema_returns_none_for_unknown(self):
        assert get_tool_schema("non_existent") is None

    def test_get_quote_requires_code(self):
        schema = TOOL_GET_QUOTE["function"]["parameters"]
        assert "code" in schema["required"]

    def test_get_factor_requires_code_and_factor_name(self):
        schema = TOOL_GET_FACTOR["function"]["parameters"]
        assert set(schema["required"]) == {"code", "factor_name"}

    def test_run_backtest_default_strategy(self):
        """run_backtest 默认 turtle_s1"""
        params = TOOL_RUN_BACKTEST["function"]["parameters"]
        assert params["properties"]["strategy_id"]["default"] == "turtle_s1"


# ═══════════════════════════════════════════════════════════════
#  协议转换 — OpenAI → Anthropic
# ═══════════════════════════════════════════════════════════════


class TestToAnthropicTools:
    def test_convert_openai_to_anthropic(self):
        openai_tools = [
            {"type": "function", "function": {
                "name": "get_quote",
                "description": "查询报价",
                "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
            }},
            {"type": "function", "function": {
                "name": "get_factor",
                "description": "查询因子",
                "parameters": {"type": "object", "properties": {"code": {"type": "string"}, "factor_name": {"type": "string"}}, "required": ["code", "factor_name"]},
            }},
        ]
        anthropic = to_anthropic_tools(openai_tools)
        assert len(anthropic) == 2
        for a in anthropic:
            # Anthropic 格式: name / description / input_schema
            assert "name" in a
            assert "description" in a
            assert "input_schema" in a
            assert "function" not in a
            assert "type" not in a

    def test_anthropic_input_schema_is_parameters(self):
        openai = [{"type": "function", "function": {
            "name": "x", "description": "X", "parameters": {"type": "object", "properties": {}},
        }}]
        result = to_anthropic_tools(openai)
        assert result[0]["input_schema"] == {"type": "object", "properties": {}}

    def test_empty_tools_returns_empty(self):
        assert to_anthropic_tools([]) == []
        assert to_anthropic_tools(None) == []

    def test_already_anthropic_passthrough(self):
        """非 function 类型的 input 原样保留(防御性)"""
        anthropic_native = [{"name": "x", "description": "X", "input_schema": {"type": "object"}}]
        result = to_anthropic_tools(anthropic_native)
        assert result == anthropic_native


# ═══════════════════════════════════════════════════════════════
#  工具执行调度
# ═══════════════════════════════════════════════════════════════


class TestExecuteToolCall:
    def test_unknown_tool_returns_error(self):
        result = execute_tool_call("non_existent", {"code": "600519"})
        assert "error" in result
        assert "non_existent" in result["error"]
        assert "available" in result

    def test_string_arguments_parsed_as_json(self):
        """arguments 可以是 JSON 字符串"""
        mock_fn = lambda **kw: {"code": kw["code"], "price": 100.0}
        with patch.dict("services.agent_tools.TOOL_EXECUTORS", {"get_quote": mock_fn}):
            result = execute_tool_call("get_quote", '{"code": "600519"}')
            assert result == {"code": "600519", "price": 100.0}

    def test_invalid_json_arguments_returns_error(self):
        result = execute_tool_call("get_quote", "{not valid json")
        assert "error" in result
        assert "JSON" in result["error"]

    def test_non_dict_non_string_arguments_returns_error(self):
        result = execute_tool_call("get_quote", [1, 2, 3])
        assert "error" in result
        assert "dict" in result["error"]

    def test_tool_type_error_returns_param_error(self):
        """参数错误(签名不匹配)返回友好错误"""
        with patch("services.agent_tools.TOOL_EXECUTORS", {"get_quote": lambda: {"ok": True}}):
            # lambda 不接受 kwargs → TypeError
            result = execute_tool_call("get_quote", {"code": "600519"})
            assert "error" in result
            assert "参数错误" in result["error"]

    def test_tool_exception_returns_error(self):
        with patch("services.agent_tools.TOOL_EXECUTORS", {"get_quote": lambda **kw: (_ for _ in ()).throw(ValueError("boom"))}):
            result = execute_tool_call("get_quote", {"code": "600519"})
            assert "error" in result
            assert "boom" in result["error"]


# ═══════════════════════════════════════════════════════════════
#  ai_chat_with_tools 调用循环
# ═══════════════════════════════════════════════════════════════


class TestAiChatWithToolsLoop:
    """用 monkeypatch 模拟 LLM 返回,验证调用循环 + 工具执行 + 终止条件"""

    @pytest.mark.asyncio
    async def test_empty_tools_falls_back_to_ai_chat(self):
        """tools 为空时退化为 ai_chat"""
        with patch("services.ai_service.ai_chat", AsyncMock(return_value="hello")) as mock:
            from services.ai_service import ai_chat_with_tools
            result = await ai_chat_with_tools("hi", tools=[])
            assert result["text"] == "hello"
            assert result["tool_calls"] == []
            assert result["finished"] is True
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_one_tool_call_then_text_response(self):
        """第 1 轮 LLM 返回 tool_call, 执行工具, 第 2 轮返回文本"""
        from services.ai_service import ai_chat_with_tools

        # 模拟 LLM 返回: 第 1 轮有 tool_call, 第 2 轮纯文本
        openai_response_with_call = {
            "text": "",
            "tool_calls": [{
                "id": "call_1",
                "name": "get_quote",
                "arguments": {"code": "600519"},
            }],
            "raw_message": {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "get_quote", "arguments": '{"code": "600519"}'},
            }]},
        }
        openai_response_text = {
            "text": "最新价 100.0 元",
            "tool_calls": [],
            "raw_message": {"role": "assistant", "content": "最新价 100.0 元"},
        }

        with patch("services.ai_service._chat_openai_provider_with_tools",
                   AsyncMock(side_effect=[openai_response_with_call, openai_response_text])), \
             patch("services.agent_tools.execute_tool_call",
                   return_value={"code": "600519", "price": 100.0}):
            result = await ai_chat_with_tools("查询 600519", tools=[TOOL_GET_QUOTE], provider="deepseek")
            assert result["text"] == "最新价 100.0 元"
            assert len(result["tool_calls"]) == 1
            assert result["tool_calls"][0]["name"] == "get_quote"
            assert result["tool_calls"][0]["result"] == {"code": "600519", "price": 100.0}
            assert result["iterations"] == 2
            assert result["finished"] is True

    @pytest.mark.asyncio
    async def test_max_iterations_terminates_loop(self):
        """达到 max_iterations 时返回 finished=False"""
        from services.ai_service import ai_chat_with_tools

        # 永远返回 tool_call → 触发循环
        infinite_response = {
            "text": "",
            "tool_calls": [{"id": "call_x", "name": "get_quote", "arguments": {"code": "000001"}}],
            "raw_message": {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call_x", "type": "function",
                "function": {"name": "get_quote", "arguments": '{"code": "000001"}'},
            }]},
        }

        with patch("services.ai_service._chat_openai_provider_with_tools",
                   AsyncMock(return_value=infinite_response)), \
             patch("services.agent_tools.execute_tool_call",
                   return_value={"code": "000001", "price": 50.0}):
            result = await ai_chat_with_tools(
                "test", tools=[TOOL_GET_QUOTE], provider="deepseek", max_iterations=3,
            )
            assert result["finished"] is False
            assert result["iterations"] == 3
            assert len(result["tool_calls"]) == 3  # 每次循环都执行一次

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_single_response(self):
        """单次 LLM 返回多个 tool_call,全部执行"""
        from services.ai_service import ai_chat_with_tools

        multi_response = {
            "text": "",
            "tool_calls": [
                {"id": "c1", "name": "get_quote", "arguments": {"code": "600519"}},
                {"id": "c2", "name": "get_factor", "arguments": {"code": "600519", "factor_name": "MA5"}},
            ],
            "raw_message": {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "get_quote", "arguments": '{"code": "600519"}'}},
                {"id": "c2", "type": "function", "function": {"name": "get_factor", "arguments": '{"code": "600519", "factor_name": "MA5"}'}},
            ]},
        }
        final_response = {
            "text": "OK", "tool_calls": [],
            "raw_message": {"role": "assistant", "content": "OK"},
        }

        with patch("services.ai_service._chat_openai_provider_with_tools",
                   AsyncMock(side_effect=[multi_response, final_response])), \
             patch("services.agent_tools.execute_tool_call",
                   side_effect=[{"price": 100.0}, {"value": 99.5}]) as mock_exec:
            result = await ai_chat_with_tools("test", tools=[TOOL_GET_QUOTE, TOOL_GET_FACTOR], provider="deepseek")
            assert result["text"] == "OK"
            assert len(result["tool_calls"]) == 2
            assert mock_exec.call_count == 2


# ═══════════════════════════════════════════════════════════════
#  协议转换的端到端(只验 schema,不调真实 LLM)
# ═══════════════════════════════════════════════════════════════


class TestSchemaRoundtrip:
    def test_registry_tools_are_valid_anthropic(self):
        """整个 TOOL_REGISTRY 转 Anthropic 格式后,每个工具都符合 Anthropic 协议"""
        openai_tools = list(TOOL_REGISTRY.values())
        anthropic = to_anthropic_tools(openai_tools)
        assert len(anthropic) == len(openai_tools)
        for a in anthropic:
            assert a["name"] in TOOL_REGISTRY
            assert "input_schema" in a
            assert a["input_schema"]["type"] == "object"
            # input_schema 必须有 properties 字段(Anthropic 要求)
            assert "properties" in a["input_schema"]
