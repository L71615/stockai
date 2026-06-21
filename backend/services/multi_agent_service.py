"""多 Agent 交叉验证选股服务

5 个 AI 投资人格从不同维度独立分析候选股池，投票聚合后给出综合评分。
每个 Agent 的角色定义见 AGENT_ROLES。

工作流:
  1. 接收候选股列表（多因子扫描 Top 50）
  2. 并行调用 5 个 Agent（asyncio.gather）
  3. 聚合结果：投票 + 加权评分 + 风险否决
  4. 返回综合排名 + 各 Agent 独立意见
"""

import json
import re
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 5 个 Agent 角色定义
# ═══════════════════════════════════════════════════════════

AGENT_ROLES = {
    "value": {
        "name": "价值分析师",
        "icon": "💰",
        "color": "emerald",
        "focus": "基本面 + 估值",
        "system_prompt": """你是资深价值投资者，信奉格雷厄姆和巴菲特的价值投资理念。
你的分析框架：
1. PE/PB 估值是否合理（低 PE、低 PB 得分高）
2. ROE 是否持续高于行业平均
3. 股息率是否有吸引力
4. 安全边际是否充足
5. 现金流和资产负债表健康度

你倾向于选择被低估的、有安全边际的股票，回避高估值热门股。
以严格但有建设性的态度给出评估。""",
        "criteria": ["估值合理", "ROE优秀", "安全边际", "现金流健康"],
    },
    "technical": {
        "name": "技术分析师",
        "icon": "📈",
        "color": "blue",
        "focus": "技术面 + 量价",
        "system_prompt": """你是资深技术分析师，专注于价格行为和成交量分析。
你的分析框架：
1. K 线形态（趋势、支撑阻力、形态突破）
2. RSI/MACD 等技术指标信号
3. 量价配合关系（放量突破、缩量回调）
4. 均线排列（多头/空头排列）
5. 相对强度（近期涨幅排名）

你倾向于选择技术面强势、趋势明确的股票，关注短期动量。
以图表分析师的视角给出评估。""",
        "criteria": ["趋势向上", "量价配合", "指标共振", "相对强势"],
    },
    "risk": {
        "name": "风险控制官",
        "icon": "🛡️",
        "color": "red",
        "focus": "风险 + 回撤",
        "system_prompt": """你是风险控制专家，职责是识别和评估投资风险。你拥有否决权。
你的分析框架：
1. 历史波动率和下行风险
2. 最大回撤幅度和恢复时间
3. 贝塔系数和系统性风险
4. 流动性风险（日均成交额）
5. 行业集中度风险
6. 杠杆率（融资余额占比）

你对每只股票给出风险等级（低/中/高），对于高风险股票给出明确的"不建议"标记。
你是保守主义者，宁愿错过机会也不承担不可控的风险。""",
        "criteria": ["低波动", "回撤可控", "流动性好", "风险分散"],
    },
    "sentiment": {
        "name": "情绪捕手",
        "icon": "🔥",
        "color": "orange",
        "focus": "社交 + 资金面",
        "system_prompt": """你是市场情绪分析师，擅长捕捉市场共识和资金流向。
你的分析框架：
1. 雪球社区关注度和讨论热度
2. 微博情绪倾向（看多/看空）
3. 北向资金流向（外资偏好）
4. 融资融券数据（杠杆情绪）
5. 机构持仓变化
6. 市场热点和题材联动

你倾向于选择获得市场共识、资金持续流入的股票。
但你也能识别"过热"信号，提醒回避过度炒作的标的。""",
        "criteria": ["社区关注", "资金流入", "情绪正面", "机构增持"],
    },
    "macro": {
        "name": "宏观策略师",
        "icon": "🌐",
        "color": "purple",
        "focus": "行业 + 宏观",
        "system_prompt": """你是宏观策略分析师，从自上而下的视角评估投资机会。
你的分析框架：
1. 行业景气度和政策面
2. 行业在宏观经济周期中的位置
3. 产业链地位和竞争格局
4. 政策扶持方向（国产替代、新能源等）
5. 行业轮动和风格切换
6. 全球宏观环境对行业的影响

你倾向于选择处于景气上升期、有政策支持的行业龙头。
你的分析更多关注行业配置而非个股选择。""",
        "criteria": ["行业景气", "政策支持", "龙头地位", "周期有利"],
    },
}


def _build_candidate_text(candidates: list[dict], max_candidates: int = 30) -> str:
    """构建候选股文本摘要（给 AI 阅读）

    对输入做基础清洗：截断过长字段、过滤特殊字符（防 prompt 注入）。
    """
    # 限制 candidates_json 最大输入（防超大 payload）
    if len(candidates) > 100:
        candidates = candidates[:100]

    text_parts = []
    for i, c in enumerate(candidates[:max_candidates]):
        code = str(c.get("code", ""))[:12].strip()
        name = str(c.get("name", ""))[:20].strip()
        # 过滤可能干扰 prompt 结构的字符
        name = name.translate(str.maketrans("", "", "{}[]\"'`"))
        industry = str(c.get("industry", "N/A"))[:20].strip()
        score = c.get("score", 0)
        price = c.get("price") or "N/A"
        hit_count = c.get("hit_count", 0)

        # 因子贡献 TOP 3
        top_factors = c.get("top_factors", [])
        factor_desc = ""
        if top_factors:
            top3 = top_factors[:3]
            try:
                factor_desc = " | ".join(
                    f"{t['factor']}({t['contribution']:+.4f})" for t in top3
                )
            except (KeyError, TypeError, ValueError):
                factor_desc = "(因子数据缺失)"

        text_parts.append(
            f"{i + 1}. {code} {name} | 行业:{industry} | 现价:{price} | "
            f"评分:{score:.4f} | 因子数:{hit_count}\n"
            f"   因子贡献: {factor_desc}"
        )

    return "\n".join(text_parts)


def _build_agent_prompt(agent_key: str, candidates: list[dict]) -> str:
    """为指定 Agent 构建分析 prompt"""
    role = AGENT_ROLES[agent_key]
    candidate_text = _build_candidate_text(candidates)

    criteria_text = "\n".join(f"  {i + 1}. {c}" for i, c in enumerate(role["criteria"]))

    prompt = f"""你是「{role['name']}」，{role['focus']}专家。

以下是多因子量化模型筛选出的 A 股候选股票池（前 {min(len(candidates), 30)} 只）：

{candidate_text}

请从你的专业视角（{role['focus']}）进行分析，选出你认为最有投资价值的 3-5 只股票，并对每只给出评分和理由。

评估标准（按重要性排序）：
{criteria_text}

请严格按 JSON 格式输出（不要 markdown 代码块标记）：
{{
  "picks": [
    {{
      "code": "股票代码",
      "name": "名称",
      "score": 0.0-10.0的评分,
      "confidence": "high/medium/low",
      "reason": "推荐理由(50字内)",
      "risk_flag": "如有风险标注，否则null"
    }}
  ],
  "summary": "你的整体分析摘要(80字内)",
  "top_themes": ["当前最看好的1-3个主题/行业"]
}}"""

    return prompt


async def _run_single_agent(
    agent_key: str,
    candidates: list[dict],
    provider: str = "",
) -> dict | None:
    """执行单个 Agent 的分析（30s 超时 + refusal 检测）"""
    role = AGENT_ROLES[agent_key]

    try:
        from services.ai_service import ai_chat

        prompt = _build_agent_prompt(agent_key, candidates)

        # 30 秒超时
        raw = await asyncio.wait_for(
            ai_chat(
                prompt,
                provider=provider,
                system_prompt=role["system_prompt"],
            ),
            timeout=30.0,
        )

        # 解析 JSON 输出
        text = raw.strip()

        # Refusal 检测：LLM 拒绝提供投资建议
        refusal_patterns = [
            "cannot recommend", "unable to", "i apologize",
            "i'm unable", "i am unable", "无法提供", "不能提供",
            "as an ai", "not financial advice",
        ]
        text_lower = text.lower()
        if any(p in text_lower for p in refusal_patterns):
            return {
                "agent_key": agent_key,
                "agent_name": role["name"],
                "icon": role["icon"],
                "color": role["color"],
                "focus": role["focus"],
                "error": "model_refusal",
                "raw": raw[:200],
                "picks": [],
                "summary": "",
                "top_themes": [],
            }

        # 去掉可能的 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:]) if len(lines) > 1 else text
            if text.rstrip().endswith("```"):
                text = text[: text.rfind("```")].strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # 尝试从文本中提取 JSON
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                result = json.loads(m.group(0))
            else:
                return {
                    "agent_key": agent_key,
                    "agent_name": role["name"],
                    "error": "AI 输出无法解析为 JSON",
                    "raw": raw[:200],
                    "picks": [],
                }

        return {
            "agent_key": agent_key,
            "agent_name": role["name"],
            "icon": role["icon"],
            "color": role["color"],
            "focus": role["focus"],
            "picks": result.get("picks", []),
            "summary": result.get("summary", ""),
            "top_themes": result.get("top_themes", []),
        }

    except asyncio.TimeoutError:
        logger.warning(f"Agent {agent_key} 超时 (30s)")
        return {
            "agent_key": agent_key,
            "agent_name": role["name"],
            "icon": role["icon"],
            "color": role["color"],
            "focus": role["focus"],
            "error": "timeout: Agent 分析超时 (30s)",
            "picks": [],
            "summary": "",
            "top_themes": [],
        }
    except Exception as e:
        logger.warning(f"Agent {agent_key} 执行失败: {e}")
        return {
            "agent_key": agent_key,
            "agent_name": role["name"],
            "error": str(e),
            "picks": [],
        }


def _aggregate_results(
    agent_results: list[dict],
    candidates: list[dict],
) -> dict:
    """聚合 5 个 Agent 的分析结果

    聚合逻辑：
    1. 投票计数：统计每只股票被多少个 Agent 推荐
    2. 加权评分：各 Agent 对该股的评分取均值
    3. 风险否决：风险控制官标记高危 → 自动降级或剔除
    4. 共识度：根据投票离散度给出 全票/多数/分歧/少数 标签
    """
    if not agent_results:
        return {"aggregated": [], "agent_count": 0, "consensus_summary": "无 Agent 结果"}

    # 按股票代码聚合
    code_picks: dict[str, dict] = {}  # code → {votes, scores, reasons, agents}

    for ar in agent_results:
        if "error" in ar:
            continue
        agent_name = ar["agent_name"]
        agent_color = ar.get("color", "neutral")
        is_risk = ar["agent_key"] == "risk"

        for pick in ar.get("picks", []):
            code = pick.get("code", "")
            if not code:
                continue

            if code not in code_picks:
                code_picks[code] = {
                    "code": code,
                    "votes": 0,
                    "total_score": 0.0,
                    "score_count": 0,
                    "reasons": [],
                    "agents": [],
                    "risk_flags": [],
                    "risk_veto": False,
                }

            entry = code_picks[code]
            entry["votes"] += 1
            score = pick.get("score", 5)
            if score is not None:
                try:
                    entry["total_score"] += float(score)
                    entry["score_count"] += 1
                except (ValueError, TypeError):
                    pass
            entry["reasons"].append({
                "agent": agent_name,
                "color": agent_color,
                "reason": pick.get("reason", ""),
                "confidence": pick.get("confidence", "medium"),
            })
            entry["agents"].append(agent_name)

            # 风险标注
            risk_flag = pick.get("risk_flag")
            if risk_flag:
                entry["risk_flags"].append({
                    "agent": agent_name,
                    "flag": risk_flag,
                })

            # 风险否决
            if is_risk and pick.get("confidence") == "low" and (score is None or float(score) < 3):
                entry["risk_veto"] = True

    # 计算平均分和共识度
    aggregated = []
    for code, entry in code_picks.items():
        # 平均分（归一化到 0-10）
        avg_score = round(entry["total_score"] / entry["score_count"], 1) if entry["score_count"] > 0 else 0

        # 共识度
        vote_count = entry["votes"]
        if vote_count >= 4:
            consensus = "全票通过"
            consensus_class = "all"
        elif vote_count >= 3:
            consensus = "多数通过"
            consensus_class = "majority"
        elif vote_count >= 2:
            consensus = "分歧较大"
            consensus_class = "divided"
        else:
            consensus = "少数推荐"
            consensus_class = "minority"

        # 风险否决
        if entry["risk_veto"]:
            consensus = "⚠️ 风险否决"
            consensus_class = "vetoed"
            avg_score = max(avg_score - 2, 0)

        # 找到原始候选股信息
        stock_info = {}
        for c in candidates:
            if c.get("code") == code:
                stock_info = {
                    "name": c.get("name", ""),
                    "industry": c.get("industry", ""),
                    "price": c.get("price"),
                    "quant_score": c.get("score"),
                }
                break

        aggregated.append({
            "code": code,
            "name": stock_info.get("name", ""),
            "industry": stock_info.get("industry", ""),
            "price": stock_info.get("price"),
            "quant_score": stock_info.get("quant_score"),
            "agent_score": avg_score,
            "votes": vote_count,
            "total_agents": len([a for a in agent_results if "error" not in a]),
            "consensus": consensus,
            "consensus_class": consensus_class,
            "reasons": entry["reasons"],
            "agents": entry["agents"],
            "risk_flags": entry["risk_flags"] if entry["risk_flags"] else None,
            "risk_veto": entry["risk_veto"],
        })

    # 排序：按得票数 desc → Agent 评分 desc
    aggregated.sort(key=lambda x: (x["risk_veto"] is False, x["votes"], x["agent_score"]), reverse=True)

    # 生成共识摘要
    active_agents = [a for a in agent_results if "error" not in a]
    themes = []
    for ar in active_agents:
        themes.extend(ar.get("top_themes", []))
    # 去重并取前 5
    theme_counts = {}
    for t in themes:
        theme_counts[t] = theme_counts.get(t, 0) + 1
    top_themes = sorted(theme_counts, key=theme_counts.get, reverse=True)[:5]

    consensus_summary = f"{len(active_agents)} 位 AI 分析师参与交叉验证，" \
                        f"共推荐 {len(aggregated)} 只股票。" \
                        f"共识主题: {', '.join(top_themes[:3]) if top_themes else '无明确共识'}"

    return {
        "aggregated": aggregated,
        "agent_count": len(active_agents),
        "error_agents": [a for a in agent_results if "error" in a],
        "consensus_summary": consensus_summary,
        "top_themes": top_themes,
    }


async def run_multi_agent_screen(
    candidates: list[dict],
    provider: str = "",
    agent_keys: list[str] = None,
) -> dict:
    """主入口：运行多 Agent 交叉验证

    Args:
        candidates: 候选股列表（来自多因子扫描结果）
        provider: AI 供应商（为空则用默认）
        agent_keys: 要运行的 Agent 列表，默认全部 5 个

    Returns:
        {
            "agent_results": [...],   # 每个 Agent 的完整分析
            "aggregation": {...},     # 聚合结果
            "provider": str,
            "elapsed_ms": int,
        }
    """
    import time as _time

    if not candidates:
        return {"error": "候选股列表为空", "agent_results": [], "aggregation": None}

    keys = agent_keys or list(AGENT_ROLES.keys())
    logger.info(
        "multi_agent_screen start: candidates=%d agents=%d provider=%s",
        len(candidates), len(keys), provider or "default",
    )

    # 过滤未知的 agent_key
    keys = [k for k in keys if k in AGENT_ROLES]

    if not keys:
        return {"error": "无有效 Agent", "agent_results": [], "aggregation": None}

    t0 = _time.time()

    # 并行执行所有 Agent
    tasks = [_run_single_agent(k, candidates, provider) for k in keys]
    agent_results = await asyncio.gather(*tasks)

    # 聚合
    aggregation = _aggregate_results(agent_results, candidates)

    elapsed = int((_time.time() - t0) * 1000)

    # 结构化完成日志
    success_count = len([a for a in agent_results if "error" not in a])
    error_count = len(agent_results) - success_count
    top_consensus = aggregation.get("consensus_summary", "")[:80] if aggregation else "N/A"
    logger.info(
        "multi_agent_screen done: elapsed=%dms success=%d/%d consensus=%s",
        elapsed, success_count, len(agent_results), top_consensus,
    )

    return {
        "agent_results": agent_results,
        "aggregation": aggregation,
        "provider": provider or "default",
        "elapsed_ms": elapsed,
    }
