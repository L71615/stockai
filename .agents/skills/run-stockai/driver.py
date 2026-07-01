"""StockAI 冒烟测试驱动 — 启动服务 → 验证 API → 停止服务"""
import subprocess, sys, time, json, urllib.request, os, signal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
BACKEND = ROOT / "backend"
PORT = 8765  # 用非常规端口避免冲突
BASE = f"http://localhost:{PORT}"

_token = None

def fail(msg):
    print(f"FAIL {msg}"); sys.exit(1)

def ok(msg):
    print(f"OK   {msg}")

def login():
    """登录获取 JWT token"""
    global _token
    data = json.dumps({"email": os.environ.get("ADMIN_EMAIL", "admin@stockai.com"),
                       "password": os.environ.get("ADMIN_PASSWORD", "")}).encode()
    try:
        req = urllib.request.Request(f"{BASE}/api/auth/login", data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            _token = result.get("token", "")
            if not _token:
                fail("登录失败：未获取到 token")
    except Exception as e:
        fail(f"登录失败: {e}")

def api(path):
    """GET JSON from API（带 JWT 认证）"""
    try:
        headers = {}
        if _token:
            headers["Authorization"] = f"Bearer {_token}"
        req = urllib.request.Request(f"{BASE}{path}", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        fail(f"API {path}: {e}")

# ---- 1. 安装依赖 ----
print("=== 安装依赖 ===")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                str(BACKEND / "requirements.txt")], check=True, cwd=str(ROOT))
ok("依赖已安装")

# ---- 2. 启动服务 ----
print("=== 启动 StockAI ===")
env = os.environ.copy()
env["PORT"] = str(PORT)
env["PYTHONPATH"] = str(BACKEND)
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app",
     "--host", "0.0.0.0", "--port", str(PORT)],
    cwd=str(BACKEND), env=env,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)

# 等待服务就绪
for _ in range(30):
    try:
        urllib.request.urlopen(f"{BASE}/api/health", timeout=2)
        break
    except Exception:
        time.sleep(0.5)
else:
    proc.terminate()
    fail("服务启动超时")
ok(f"服务运行在 :{PORT}")

# ---- 3. 冒烟测试 ----
print("=== 核心 API 验证 ===")

# 健康检查
h = api("/api/health")
assert h["status"] == "ok", f"health: {h}"
ok("GET /api/health")

# 登录获取 token
login()
ok("POST /api/auth/login (JWT obtained)")

# 全球指数
indices = api("/api/stocks/indices/global")
assert len(indices) == 15, f"indices count: {len(indices)}"
live = sum(1 for i in indices if i["price"])
assert live >= 7, f"live indices: {live}"
ok(f"GET /api/stocks/indices/global ({live}/15 实时)")

# 个股透视
insight = api("/api/quant/stock-insight/600519?days=5")
assert insight["name"], f"insight name: {insight['name']}"
assert insight["price"] > 0, f"insight price: {insight['price']}"
assert len(insight["kline"]["dates"]) == 5, f"dates: {len(insight['kline']['dates'])}"
ok(f"GET /api/quant/stock-insight ({insight['name']} price={insight['price']})")

# 因子数据
factors = api("/api/quant/factors/600519")
assert factors.get("pe"), f"PE: {factors.get('pe')}"
assert factors.get("roe"), f"ROE: {factors.get('roe')}"
ok(f"GET /api/quant/factors (PE={factors['pe']} ROE={factors['roe']}%)")

# 港股行情
hk = api("/api/stocks/quote/00700")
assert hk.get("price") and hk["price"] > 0, f"HK price: {hk.get('price')}"
ok(f"GET /api/stocks/quote/00700 (Tencent {hk['name']} HKD={hk['price']})")

# 基金净值
fund = api("/api/stocks/fund-nav/000001")
ok(f"GET /api/stocks/fund-nav (fund OK)" if fund else "fund SKIP")

# 风控 (无持仓时返回 error 但结构正确)
risk = api("/api/quant/portfolio-risk")
assert "error" in risk or "holdings_count" in risk, f"risk: {risk}"
ok("GET /api/quant/portfolio-risk (structure OK)")

# 前端静态文件
try:
    with urllib.request.urlopen(f"{BASE}/", timeout=5) as resp:
        html = resp.read().decode()
        assert "StockAI" in html or "持仓" in html, "frontend content"
    ok("GET / (前端首页)")
except Exception as e:
    fail(f"前端首页: {e}")

# ---- 4. 停止 ----
print("\n=== 停止服务 ===")
proc.terminate()
proc.wait(timeout=5)
ok("服务已停止")

print(f"\n{'='*40}")
print("ALL PASSED: StockAI smoke test")
print(f"{'='*40}")
