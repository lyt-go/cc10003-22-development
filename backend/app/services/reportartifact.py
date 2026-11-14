"""报表产物登记业务规则。

登记边界（依据现有报表调度 → 数据服务交付链路确定）：
- 报表任务执行「确认排期」后，由本服务登记一条不可变的报表产物，记录
  数据日期偏移、实际数据日期、包含指标、返回字段与产物摘要；
- 数据服务「发布服务」时按产物编号绑定产物，绑定关系同样不可变；
- 失败/中断的排期只登记可解释的异常产物，不会产生已发布服务；
- 同一任务下按（数据日期, 指标集合）生成结果指纹：指纹不变的重复排期
  复用原产物、不生成新版本；指纹变化才分配下一排期版本号；
- 失败重试只补充缺失的版本槽，不为同一结果重复建产物/服务。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.store import store

MODULE = "reportartifact"
TASK_MODULE = "reportsch"

STATUS_REGISTERED = "已登记"
STATUS_FAILED = "生成失败"
STATUS_INTERRUPTED = "已中断"
ABNORMAL_STATUSES = (STATUS_FAILED, STATUS_INTERRUPTED)
RESULT_SUCCESS = "成功"
RESULT_FAILED = "失败"
RESULT_INTERRUPTED = "中断"

# 产物一旦登记即不可变，任何接口都不提供修改入口。
IMMUTABLE_HINT = "报表产物登记后不可变"


def split_metrics(raw: Any) -> list[str]:
    """把「包含指标」的多种写法统一成去重、去空的有序列表。"""
    if isinstance(raw, (list, tuple)):
        items = [str(item).strip() for item in raw]
    else:
        text = str(raw or "")
        items = [part.strip() for part in text.replace("，", ";").replace(",", ";").split(";")]
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def resolve_data_date(offset: Any, schedule_date: date) -> tuple[str, str]:
    """按数据日期偏移推导实际数据日期。

    偏移是整数（含 0、负数）时相对排期日期按天偏移；偏移本身是日期串时
    直接作为数据日期；无法解析时回退到排期日期并给出可读说明。
    """
    raw = str(offset or "").strip()
    if not raw:
        return schedule_date.isoformat(), "未配置数据日期偏移，默认取排期日期"
    try:
        return (schedule_date - timedelta(days=int(raw))).isoformat(), ""
    except ValueError:
        pass
    try:
        return date.fromisoformat(raw).isoformat(), "数据日期偏移配置为绝对日期，直接采用"
    except ValueError:
        return schedule_date.isoformat(), f"数据日期偏移「{raw}」无法解析，回退为排期日期"


def build_fingerprint(data_date: str, metrics: list[str]) -> str:
    return f"{data_date}|{';'.join(metrics)}"


def build_return_fields(task_code: str, data_date: str, metrics: list[str]) -> list[str]:
    """返回字段是交付契约的一部分：固定携带任务编号、数据日期，再展开指标。"""
    return ["任务编号", "数据日期", *metrics]


def build_summary(task_code: str, version: int, data_date: str, metrics: list[str]) -> str:
    return (
        f"{task_code} 排期v{version}｜数据日期 {data_date}｜"
        f"指标 {len(metrics)} 项：{'、'.join(metrics)}"
    )


def _parse_schedule_date(raw: Any) -> date:
    if isinstance(raw, date):
        return raw
    text = str(raw or "").strip()
    if text:
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
    return date.today()


class ReportArtifactService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        task_code: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(MODULE))
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("产物编号", "")) or keyword in str(row.get("任务编号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("状态") == status]
        if task_code:
            rows = [row for row in rows if row.get("任务编号") == task_code]
        rows.sort(key=lambda row: int(row.get("id", 0)))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def find_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if row.get("产物编号") == code:
                return row
        return None

    def artifacts_of_task(self, task_id: int) -> list[dict[str, Any]]:
        return [
            row
            for row in store.rows(MODULE)
            if int(row.get("报表任务id", 0)) == task_id
        ]

    def _next_code(self) -> str:
        return f"ARTI-{store.next_id(MODULE):04d}"

    def _next_success_version(self, task_id: int) -> int:
        used = [
            int(row.get("排期版本号", 0))
            for row in self.artifacts_of_task(task_id)
            if row.get("状态") == STATUS_REGISTERED
        ]
        return max(used, default=0) + 1

    def register_from_schedule(
        self,
        task_entry: dict[str, Any],
        *,
        schedule_date_raw: Any,
        result: str = RESULT_SUCCESS,
        reason: str | None = None,
    ) -> tuple[dict[str, Any], str, bool]:
        """排期完成后登记产物。在事务内调用，随排期状态一起提交或回滚。

        返回 (产物, 说明, 是否新建)。命中幂等规则时返回既有产物且 created=False。
        """
        task_id = int(task_entry["id"])
        task_code = str(task_entry.get("任务编号", ""))
        schedule_date = _parse_schedule_date(schedule_date_raw)
        offset = task_entry.get("数据日期偏移")
        data_date, date_note = resolve_data_date(offset, schedule_date)
        metrics = split_metrics(task_entry.get("包含指标"))
        fingerprint = build_fingerprint(data_date, metrics)
        normalized_result = str(result or RESULT_SUCCESS).strip() or RESULT_SUCCESS
        failed = normalized_result in (RESULT_FAILED, "生成失败")
        interrupted = normalized_result in (RESULT_INTERRUPTED, "已中断")
        target_status = (
            STATUS_FAILED if failed else STATUS_INTERRUPTED if interrupted else STATUS_REGISTERED
        )

        # 幂等：同指纹、同结果的登记直接复用，失败重试不重复建产物。
        for row in self.artifacts_of_task(task_id):
            if row.get("结果指纹") != fingerprint or row.get("状态") != target_status:
                continue
            if target_status == STATUS_REGISTERED or row.get("失败原因") == (reason or ""):
                return row, f"产物 {row['产物编号']} 已存在，按幂等规则复用，不重复登记", False

        version = self._next_success_version(task_id)
        artifact: dict[str, Any] = {
            "id": store.next_id(MODULE),
            "产物编号": self._next_code(),
            "报表任务id": task_id,
            "任务编号": task_code,
            "排期版本号": version,
            "排期日期": schedule_date.isoformat(),
            "数据日期偏移": str(offset or ""),
            "数据日期": data_date,
            "包含指标": metrics,
            "返回字段": build_return_fields(task_code, data_date, metrics),
            "产物摘要": build_summary(task_code, version, data_date, metrics),
            "状态": target_status,
            "失败原因": (reason or "").strip(),
            "结果指纹": fingerprint,
            "不可变": True,
            "登记时间": date.today().isoformat(),
            "备注": date_note,
            "pending": target_status in ABNORMAL_STATUSES,
            "abnormal": target_status in ABNORMAL_STATUSES,
        }
        store.rows(MODULE).append(artifact)
        if target_status == STATUS_REGISTERED:
            message = f"排期完成，已登记产物 {artifact['产物编号']}（{artifact['产物摘要']}）"
        else:
            message = (
                f"排期{normalized_result}，已登记{target_status}产物 {artifact['产物编号']}"
                f"：{artifact['失败原因'] or '未提供原因'}；该产物不可用于服务发布"
            )
        return artifact, message, True
