"""v4.1 Phase 2A: 同步服务抽象基类 — 模板方法模式

子类:
    - services/index_sync_service.IndexSyncService
    - services/etf_sync_service.ETFSyncService

子类必填类属性:
    _RUN_TABLE          -- 'index_sync_runs' | 'etf_sync_runs'
    _ITEM_TABLE         -- 'index_sync_run_items' | 'etf_sync_run_items'
    _TARGET_CODE_COL    -- 'symbol' | 'code'  (run_items.target 字段)
    _ALERT_FOOTER       -- 'index' | 'etf'     (通知标题前缀)

子类必填方法:
    load_targets()      -- list[dict{'code', 'name'}]
    _fetch_one(code, days) -> int  -- 实际拉取+upsert 返回行数
"""
from __future__ import annotations

import abc
import logging
import time
from datetime import datetime
from typing import Optional

from database import execute

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ms_diff(started_iso: str, finished_iso: str) -> int:
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        return int(
            (datetime.strptime(finished_iso, fmt) - datetime.strptime(started_iso, fmt)).total_seconds() * 1000
        )
    except Exception:
        return 0


class BaseVendorSyncService(abc.ABC):
    """抽象基类 — sync 编排 / 审计 / 告警 / 限频 全在基类.

    子类只需提供:
      - 类属性 _RUN_TABLE/_ITEM_TABLE/_TARGET_CODE_COL/_ALERT_FOOTER
      - load_targets()
      - _fetch_one(code, days) -> int
    """

    _RUN_TABLE: str = ""
    _ITEM_TABLE: str = ""
    _TARGET_CODE_COL: str = ""
    _ALERT_FOOTER: str = ""

    # ── 抽象方法 ──────────────────────────────────────
    @abc.abstractmethod
    def load_targets(self) -> list[dict]:
        """返回 [{'code': 'sh000300', 'name': '沪深300'}, ...]"""

    @abc.abstractmethod
    def _fetch_one(self, code: str, days: int) -> int:
        """拉取单只 + upsert 入库, 返回写入行数.

        实现里失败抛 RuntimeError, 基类负责 catch + 写 audit.
        """

    # ── 模板方法 ──────────────────────────────────────
    def run_sync(
        self,
        *,
        run_type: str = "nightly",
        days_back: int = 1250,
        sleep_seconds: float = 0.2,
    ) -> dict:
        """执行一次同步, 写 runs/items audit, 返回汇总 dict.

        状态聚合:
          - 0 failed -> 'success'
          - 全部 failed -> 'failed'
          - 部分 failed -> 'partial_success'
        告警(>=50% 失败 或 全部失败) 触发 send_notification.
        """
        targets = self.load_targets()
        run_id = self._record_run(run_type, len(targets))
        run_started = _now_iso()

        if len(targets) == 0:
            self._finalize_run(
                run_id=run_id,
                success=0,
                failed=0,
                status="skipped",
                err_summary="no targets",
                started_iso=run_started,
            )
            return {
                "run_id": run_id,
                "status": "skipped",
                "target_count": 0,
                "success_count": 0,
                "failed_count": 0,
                "alert_sent": False,
            }

        success = 0
        failed = 0
        errors: list[str] = []

        for target in targets:
            item_started = _now_iso()
            try:
                rows = self._fetch_one(target["code"], days_back)
                self._record_item(
                    run_id=run_id,
                    target=target,
                    status="success",
                    rows=rows,
                    err="",
                    started_iso=item_started,
                )
                success += 1
            except Exception as e:
                err = str(e)[:200]
                self._record_item(
                    run_id=run_id,
                    target=target,
                    status="failed",
                    rows=0,
                    err=err,
                    started_iso=item_started,
                )
                failed += 1
                errors.append(f"{target['code']}:{err[:80]}")
                logger.warning(
                    "sync %s run_id=%d failed for %s: %s",
                    self._RUN_TABLE, run_id, target["code"], err,
                )
            time.sleep(sleep_seconds)

        # 状态聚合
        if failed == 0 and success > 0:
            status = "success"
        elif success == 0:
            status = "failed"
        else:
            status = "partial_success"

        err_summary = "; ".join(errors[:5])
        self._finalize_run(
            run_id=run_id,
            success=success,
            failed=failed,
            status=status,
            err_summary=err_summary,
            started_iso=run_started,
        )

        alerted = self._maybe_alert(
            status=status,
            target_count=len(targets),
            failed=failed,
            err_summary=err_summary,
            run_id=run_id,
        )

        return {
            "run_id": run_id,
            "status": status,
            "target_count": len(targets),
            "success_count": success,
            "failed_count": failed,
            "alert_sent": alerted,
        }

    # ── 私有 helper ──────────────────────────────────────
    def _record_run(self, run_type: str, target_count: int) -> int:
        r = execute(
            f"INSERT INTO {self._RUN_TABLE} "
            "(run_type, target_count, status, started_at) "
            "VALUES (?, ?, 'running', ?)",
            (run_type, target_count, _now_iso()),
        )
        return int(r["lastrowid"])

    def _record_item(
        self,
        *,
        run_id: int,
        target: dict,
        status: str,
        rows: int,
        err: str,
        started_iso: str,
    ) -> None:
        finished_iso = _now_iso()
        execute(
            f"INSERT INTO {self._ITEM_TABLE} "
            f"(run_id, {self._TARGET_CODE_COL}, sync_type, status, "
            f" rows_upserted, error_message, started_at, finished_at, duration_ms) "
            "VALUES (?, ?, 'daily_kline', ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                target["code"],
                status,
                rows,
                err,
                started_iso,
                finished_iso,
                _ms_diff(started_iso, finished_iso),
            ),
        )

    def _finalize_run(
        self,
        *,
        run_id: int,
        success: int,
        failed: int,
        status: str,
        err_summary: str,
        started_iso: str,
    ) -> None:
        finished_iso = _now_iso()
        execute(
            f"UPDATE {self._RUN_TABLE} "
            "SET success_count=?, failed_count=?, status=?, error_summary=?, "
            " finished_at=?, duration_ms=? WHERE id=?",
            (
                success,
                failed,
                status,
                err_summary,
                finished_iso,
                _ms_diff(started_iso, finished_iso),
                run_id,
            ),
        )

    def _maybe_alert(
        self,
        *,
        status: str,
        target_count: int,
        failed: int,
        err_summary: str,
        run_id: int,
    ) -> bool:
        should_alert = False
        if status == "failed":
            should_alert = True
        elif status == "partial_success" and target_count > 0 and failed / target_count >= 0.5:
            should_alert = True

        if not should_alert:
            return False

        try:
            from services.notify_service import send_notification
            send_notification(
                markdown=(
                    f"⚠️ {self._ALERT_FOOTER} sync {status}\n"
                    f"run_id={run_id}, failed={failed}/{target_count}\n"
                    f"err={err_summary[:300]}"
                ),
                title=f"[sync 告警] {self._ALERT_FOOTER}",
                run_id=f"{self._RUN_TABLE}:{run_id}",
            )
            return True
        except Exception:
            return False
