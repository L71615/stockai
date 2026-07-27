"""v4.0 C1 反事实报告 API 测试

覆盖:
  - GET /api/pipeline/counterfactual 基础返回结构
  - GET /api/pipeline/counterfactual 自定义 days/baseline
  - GET /api/pipeline/retrospectives 列表
  - 过滤参数(decision / experiment_id)传递
  - JWT 鉴权
"""

import pytest
from datetime import datetime, timedelta


class TestCounterfactualApi:
    def test_counterfactual_returns_summary(self, client):
        """GET /api/pipeline/counterfactual 返回汇总结构"""
        resp = client.get("/api/pipeline/counterfactual?days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert "window" in data
        assert "baseline_code" in data
        assert data["baseline_code"] == "csi300"  # 默认
        assert "accepted" in data
        assert "rejected" in data
        assert "edge" in data
        assert "interpretation" in data
        assert "v4_metadata" in data
        assert data["v4_metadata"]["phase"] == "C1"

    def test_counterfactual_custom_days(self, client):
        """自定义 days 参数"""
        resp = client.get("/api/pipeline/counterfactual?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["v4_metadata"]["days"] == 7

    def test_counterfactual_custom_baseline(self, client):
        """自定义 baseline 参数"""
        resp = client.get("/api/pipeline/counterfactual?days=30&baseline=000300")
        assert resp.status_code == 200
        data = resp.json()
        assert data["baseline_code"] == "000300"

    def test_counterfactual_window_includes_since(self, client):
        """window 包含 since 时间"""
        resp = client.get("/api/pipeline/counterfactual?days=60")
        data = resp.json()
        assert "since" in data["window"]
        assert "until" in data["window"]
        # since 应该是约 60 天前
        since = datetime.fromisoformat(data["window"]["since"])
        delta = datetime.now() - since
        assert 55 <= delta.days <= 65


class TestRetrospectivesApi:
    def test_retrospectives_returns_list(self, client):
        """GET /api/pipeline/retrospectives 返回列表"""
        resp = client.get("/api/pipeline/retrospectives?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "retrospectives" in data
        assert "count" in data
        assert "v4_metadata" in data
        assert isinstance(data["retrospectives"], list)

    def test_retrospectives_default_limit(self, client):
        """默认 limit=20"""
        resp = client.get("/api/pipeline/retrospectives")
        assert resp.status_code == 200
        assert resp.json()["v4_metadata"]["filters"]["limit"] == 20

    def test_retrospectives_custom_limit(self, client):
        """自定义 limit"""
        resp = client.get("/api/pipeline/retrospectives?limit=5")
        assert resp.status_code == 200
        assert resp.json()["v4_metadata"]["filters"]["limit"] == 5

    def test_retrospectives_filter_by_decision(self, client):
        """按 decision 过滤"""
        resp = client.get("/api/pipeline/retrospectives?decision=approved")
        assert resp.status_code == 200
        data = resp.json()
        # 过滤参数被记录
        assert data["v4_metadata"]["filters"]["decision"] == "approved"
        # 所有返回的记录都应是 approved
        for r in data["retrospectives"]:
            assert r["decision"] == "approved"

    def test_retrospectives_filter_by_experiment(self, client):
        """按 experiment_id 过滤"""
        resp = client.get("/api/pipeline/retrospectives?experiment_id=exp_001")
        assert resp.status_code == 200
        data = resp.json()
        for r in data["retrospectives"]:
            assert r["experiment_id"] == "exp_001"

    def test_retrospectives_limit_capped(self, client):
        """limit 上限保护"""
        resp = client.get("/api/pipeline/retrospectives?limit=10000")
        assert resp.status_code == 422  # FastAPI 验证失败(> 100)
