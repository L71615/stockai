"""v5.0-alpha M4 — /live 页面 smoke 测试

纯前端页面, 验证:
  - page.tsx 文件存在且 export default LivePage
  - sidebar 加了 /live 入口
  - 5 个 section 关键字都在文件中 (PnL / 行情 / 信号 / 持仓 / 因子)
  - 接受/拒绝按钮存在
  - DESIGN 规范: Tabler Icons / rounded-none / tabular-nums
"""
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_PAGE = REPO_ROOT / "frontend/src/app/live/page.tsx"
SIDEBAR = REPO_ROOT / "frontend/src/components/app-sidebar.tsx"


def test_live_page_file_exists():
    assert LIVE_PAGE.exists(), f"缺少文件: {LIVE_PAGE}"


def test_live_page_exports_default():
    content = LIVE_PAGE.read_text(encoding="utf-8")
    assert "export default function LivePage" in content, "缺少 default export LivePage"


def test_live_page_has_five_sections():
    content = LIVE_PAGE.read_text(encoding="utf-8")
    # 5 个 section 标识(注释或变量名)
    expected = ["PnL", "watchlist", "信号", "持仓", "因子"]
    found = [s for s in expected if s in content]
    assert len(found) >= 4, f"5 个 section 应至少有 4 个标识; 找到: {found}"


def test_live_page_has_accept_reject_buttons():
    content = LIVE_PAGE.read_text(encoding="utf-8")
    assert "acceptSignal" in content, "缺少 acceptSignal"
    assert "rejectSignal" in content, "缺少 rejectSignal"
    assert "/api/realtime/signal/" in content, "缺少 accept API 调用"


def test_live_page_uses_tabler_icons():
    content = LIVE_PAGE.read_text(encoding="utf-8")
    # 应有 IconCheck + IconX
    assert "IconCheck" in content
    assert "IconX" in content
    # 应 import from @tabler/icons-react
    assert '@tabler/icons-react' in content


def test_live_page_follows_design_rounded_none():
    content = LIVE_PAGE.read_text(encoding="utf-8")
    # DESIGN.md: rounded-none
    assert "rounded-none" in content, "应使用 rounded-none"


def test_live_page_uses_tabular_nums():
    content = LIVE_PAGE.read_text(encoding="utf-8")
    # DESIGN.md: 数字列必须 tabular-nums
    assert "tabular-nums" in content, "数字列应使用 tabular-nums"


def test_live_page_uses_china_color_convention():
    """A 股惯例: 涨红跌绿(与中国市场一致, 西方市场相反)"""
    content = LIVE_PAGE.read_text(encoding="utf-8")
    # 红色 = 涨/正盈亏, 绿色 = 跌/负盈亏
    assert "text-red-400" in content or "text-red-500" in content, "盈利/上涨应用红色"
    assert "text-emerald-400" in content or "text-emerald-500" in content, "亏损/下跌应用绿色"


def test_live_page_no_emoji_as_icons():
    """DESIGN.md 禁止 emoji 作为功能图标"""
    content = LIVE_PAGE.read_text(encoding="utf-8")
    # 查找可能的 emoji (简单启发式: 4 字节 UTF-8 字符)
    emoji_pattern = re.compile(r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF]")
    matches = emoji_pattern.findall(content)
    assert len(matches) == 0, f"不应有 emoji 作为功能图标: {matches[:5]}"


def test_sidebar_has_live_entry():
    content = SIDEBAR.read_text(encoding="utf-8")
    assert '"/live"' in content, "sidebar 应有 /live 入口"
    # 中文 label
    assert "盘中量化" in content, "sidebar /live 应有中文 label '盘中量化'"


def test_sidebar_uses_tabler_icon_for_live():
    content = SIDEBAR.read_text(encoding="utf-8")
    # /live 行的 icon 应为 IconWaveSine 或类似 IconXxx
    live_section = content[content.find('"/live"'):content.find('"/live"') + 200]
    assert "Icon" in live_section, "/live 应使用 Tabler Icon"