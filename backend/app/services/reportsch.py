"""报表调度业务规则：状态流转、字段校验与筛选口径都收在这里。

「确认排期」会在同一事务内联动登记报表产物：排期状态与产物登记要么一起
成功，要么一起退回；排期失败/中断时登记可解释的异常产物，任务保持
「调度评审中」且标记异常，不会被误展示成已发布服务。
"""
from __future__ import annotations

from typing import Any

from app.services.audit import AuditService, RESULT_OK, RESULT_ROLLED_BACK
from app.services.reportartifact import (
    ABNORMAL_STATUSES,
    ReportArtifactService,
    RESULT_FAILED,
    RESULT_INTERRUPTED,
    RESULT_SUCCESS,
)
from app.store import store

MODULE = "reportsch"
REQUIRED_FIELDS = ["任务编号", "报表名称", "包含指标"]
STATUS_ORDER = ["草稿", "调度评审中", "已排期", "已暂停"]
ACTION_RULES = {"提交调度评审": "调度评审中", "确认排期": "已排期", "暂停调度": "已暂停"}
NEGATIVE_ACTIONS = []

# 确认排期允许声明本次执行结果，默认成功；失败/中断走可解释的异常产物链路。
SCHEDULE_ACTION = "确认排期"
SCHEDULE_RESULTS = {RESULT_SUCCESS, RESULT_FAILED, RESULT_INTERRUPTED}

_audit = AuditService()
_artifacts = ReportArtifactService()


class ReportschService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        with store.transaction():
            rows = store.rows(MODULE)
            entry = {"id": store.next_id(MODULE)}
            entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
            # 排期相关配置允许在登记时一并带上，后续确认排期会用于产物登记。
            for field in ("输出格式", "调度cron", "收件人列表", "数据日期偏移", "重试次数上限"):
                if values.get(field) is not None:
                    entry[field] = values.get(field)
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        extra: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"报表任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于报表调度可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        if action != SCHEDULE_ACTION:
            with store.transaction():
                entry["status"] = target
                entry["pending"] = target != STATUS_ORDER[-1]
                entry["abnormal"] = action in NEGATIVE_ACTIONS
            return entry, f"报表任务已{action}"

        extra = extra or {}
        result = str(extra.get("result") or RESULT_SUCCESS).strip() or RESULT_SUCCESS
        if result not in SCHEDULE_RESULTS:
            return None, f"排期结果「{result}」不被支持，仅支持：{'、'.join(sorted(SCHEDULE_RESULTS))}"
        reason = str(extra.get("reason") or "").strip()
        schedule_date = extra.get("schedule_date")
        task_code = str(entry.get("任务编号", entry_id))

        # 排期与产物登记同事务：任一侧抛错都整体回滚，不会留下半条登记。
        try:
            with store.transaction():
                artifact, artifact_message, created = _artifacts.register_from_schedule(
                    entry,
                    schedule_date_raw=schedule_date,
                    result=result,
                    reason=reason,
                )
                if result == RESULT_SUCCESS:
                    entry["status"] = target
                    entry["pending"] = target != STATUS_ORDER[-1]
                    entry["abnormal"] = False
                    entry["最新产物编号"] = artifact["产物编号"]
                    _audit.record(
                        action="确认排期",
                        target="报表任务",
                        ref_code=task_code,
                        result=RESULT_OK,
                        detail=artifact_message,
                        artifact_code=str(artifact["产物编号"]),
                    )
                    message = artifact_message
                else:
                    # 失败/中断：任务不进入已排期，保留可解释的异常态等待重试。
                    entry["status"] = "调度评审中"
                    entry["pending"] = True
                    entry["abnormal"] = True
                    entry["最新产物编号"] = artifact["产物编号"]
                    _audit.record(
                        action="确认排期",
                        target="报表任务",
                        ref_code=task_code,
                        result=artifact["状态"],
                        detail=artifact_message,
                        artifact_code=str(artifact["产物编号"]),
                    )
                    message = (
                        f"报表任务排期{result}，未进入已排期；{artifact_message}。"
                        "请修复后重试，重试仅补充缺失版本，不会重复登记相同结果。"
                    )
        except Exception as exc:  # 事务已在 store 层完成回滚，这里补一条失败审计
            try:
                with store.transaction():
                    _audit.record(
                        action="确认排期",
                        target="报表任务",
                        ref_code=task_code,
                        result=RESULT_ROLLED_BACK,
                        detail=f"排期与产物登记联动失败，两侧已同时退回：{exc}",
                    )
            except Exception:
                pass
            return None, f"排期处理失败，产物登记已一并退回：{exc}"

        return entry, message
