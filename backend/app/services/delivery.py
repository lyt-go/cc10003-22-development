"""数据服务业务规则：状态流转、字段校验与筛选口径都收在这里。

发布与产物登记的联动边界：
- 「发布服务」必须显式绑定一份状态为「已登记」的报表产物；异常产物
  （生成失败/已中断）不允许发布，异常排期不会显示成已发布服务。
- 发布在同一事务内完成绑定并写审计：绑定失败则发布状态与产物侧一起
  退回，调用方不会看到没有产物归属的已发布服务。
- 绑定后冻结返回字段、数据日期与产物摘要快照；数据日期偏移或指标集合
  变化只能通过新排期产物 + 新服务版本交付，旧版本可追溯但不自动改写。
- 幂等：已发布且绑定同一产物时重复发布直接复用，不产生重复服务。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.audit import AuditService, RESULT_OK, RESULT_ROLLED_BACK
from app.services.reportartifact import STATUS_REGISTERED, ReportArtifactService
from app.store import store

MODULE = "delivery"
REQUIRED_FIELDS = ["服务编号", "数据集名称", "查询参数定义"]
STATUS_ORDER = ["草稿", "服务评审中", "已发布", "已下线"]
ACTION_RULES = {"提交服务评审": "服务评审中", "发布服务": "已发布", "下线服务": "已下线"}
NEGATIVE_ACTIONS = ["下线服务"]
PUBLISH_ACTION = "发布服务"

BIND_FIELDS = (
    "绑定产物编号",
    "绑定任务编号",
    "绑定排期版本号",
    "绑定数据日期",
    "绑定产物摘要",
    "绑定指标集合",
)

_audit = AuditService()
_artifacts = ReportArtifactService()


class DeliveryService:
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
            rows = [row for row in rows if keyword in str(row.get("服务编号", ""))]
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
            for field in ("返回字段", "速率限制", "分页最大条数", "版本号", "消费方应用"):
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
            return None, f"服务版本 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据服务可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        if action != PUBLISH_ACTION:
            with store.transaction():
                entry["status"] = target
                entry["pending"] = target != STATUS_ORDER[-1]
                entry["abnormal"] = action in NEGATIVE_ACTIONS
            return entry, f"服务版本已{action}"

        return self._publish(entry, extra or {})

    def _publish(self, entry: dict[str, Any], extra: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        service_code = str(entry.get("服务编号", entry["id"]))
        artifact_code = str(extra.get("artifact_code") or entry.get("绑定产物编号") or "").strip()

        if not artifact_code:
            return None, "发布服务必须绑定报表产物编号（artifact_code），无产物归属的服务不允许发布"
        artifact = _artifacts.find_by_code(artifact_code)
        if artifact is None:
            return None, f"报表产物 {artifact_code} 不存在，无法绑定发布"
        if artifact.get("状态") != STATUS_REGISTERED:
            return (
                None,
                f"报表产物 {artifact_code} 状态为「{artifact.get('状态')}」，"
                "异常排期产物不能发布；请先重试排期生成有效产物",
            )

        # 幂等判断与发布落库放在同一把锁、同一个事务里，保证并发发布只有
        # 第一次真正写库，其余请求走幂等返回；事务内任一步失败整体回滚。
        try:
            with store.transaction():
                if entry.get("status") == "已发布":
                    if entry.get("绑定产物编号") == artifact_code:
                        return entry, (
                            f"服务版本 {service_code} 已发布并绑定产物 {artifact_code}，"
                            "按幂等规则复用，不重复发布"
                        )
                    raise RuntimeError(
                        f"服务版本 {service_code} 已绑定产物 {entry.get('绑定产物编号')} 且已发布，"
                        "旧服务版本不可变"
                    )
                entry["status"] = "已发布"
                entry["pending"] = False
                entry["abnormal"] = False
                # 冻结交付快照：此后报表侧重排也不会改写本版本的返回字段。
                entry["绑定产物编号"] = artifact["产物编号"]
                entry["绑定任务编号"] = artifact["任务编号"]
                entry["绑定排期版本号"] = f"v{artifact['排期版本号']}"
                entry["绑定数据日期"] = artifact["数据日期"]
                entry["绑定产物摘要"] = artifact["产物摘要"]
                entry["绑定指标集合"] = list(artifact["包含指标"])
                entry["返回字段"] = list(artifact["返回字段"])
                entry["发布时间"] = date.today().isoformat()
                _audit.record(
                    action="发布服务",
                    target="数据服务",
                    ref_code=service_code,
                    result=RESULT_OK,
                    detail=(
                        f"服务 {service_code} 绑定产物 {artifact_code} 发布成功，"
                        f"数据日期 {artifact['数据日期']}，返回字段与产物快照一致"
                    ),
                    service_version=str(entry.get("版本号") or entry["id"]),
                    artifact_code=artifact_code,
                )
        except RuntimeError as exc:
            if "不可变" in str(exc):
                return None, (
                    f"{exc}；指标或数据日期变化请登记新服务版本绑定新产物"
                )
            self._record_rollback(service_code, artifact_code, exc)
            return None, f"发布失败，产物绑定已一并退回：{exc}"
        except Exception as exc:
            self._record_rollback(service_code, artifact_code, exc)
            return None, f"发布失败，产物绑定已一并退回：{exc}"

        return entry, (
            f"服务版本 {service_code} 已发布并绑定产物 {artifact_code}，"
            f"数据日期 {artifact['数据日期']}，返回字段已按产物快照冻结"
        )

    def _record_rollback(self, service_code: str, artifact_code: str, exc: Exception) -> None:
        """回滚审计尽力而为：审计自身故障时也不能掩盖事务已经回滚的事实。"""
        try:
            with store.transaction():
                _audit.record(
                    action="发布服务",
                    target="数据服务",
                    ref_code=service_code,
                    result=RESULT_ROLLED_BACK,
                    detail=f"发布与产物绑定联动失败，两侧已同时退回：{exc}",
                    artifact_code=artifact_code,
                )
        except Exception:
            pass

    def trace_artifact(self, entry_id: int) -> dict[str, Any] | None:
        """从服务版本追到报表任务、排期产物、数据日期与审计记录。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        artifact_code = entry.get("绑定产物编号")
        artifact = _artifacts.find_by_code(artifact_code) if artifact_code else None
        task = (
            store.find("reportsch", int(artifact["报表任务id"]))
            if artifact is not None
            else None
        )
        audits = _audit.records_of(str(entry.get("服务编号", "")))
        return {
            "服务版本": {
                "id": entry["id"],
                "服务编号": entry.get("服务编号"),
                "状态": entry.get("status"),
                "版本号": entry.get("版本号"),
                "返回字段": entry.get("返回字段", []),
                "发布时间": entry.get("发布时间", ""),
            },
            "绑定产物": artifact,
            "报表任务": task,
            "审计记录": audits,
            "可追溯": artifact is not None and task is not None,
            "说明": (
                "返回字段 → 报表任务 → 数据日期 → 产物摘要链路完整"
                if artifact is not None and task is not None
                else "该服务版本尚未绑定有效报表产物，暂无交付链路可追溯"
            ),
        }
