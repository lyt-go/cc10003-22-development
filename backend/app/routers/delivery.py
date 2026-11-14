"""数据服务接口：维护服务版本，覆盖提交服务评审、发布服务、下线服务等动作。

发布服务时在 values 中携带 artifact_code 绑定报表产物；另提供交付链路
追溯接口，从服务版本反查报表任务、数据日期、产物摘要与审计记录。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.delivery import DeliveryService

router = APIRouter(prefix="/api/delivery", tags=["数据服务"])

service = DeliveryService()

LIST_FIELDS = ["服务编号", "数据集名称", "查询参数定义", "返回字段", "速率限制", "分页最大条数", "版本号", "消费方应用"]
STATUSES = ["草稿", "服务评审中", "已发布", "已下线"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按服务编号检索"),
    status: str | None = Query(default=None, description="草稿、服务评审中、已发布、已下线"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按服务编号与状态过滤数据服务列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出数据服务清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "delivery", "total": total, "items": items}


@router.get("/{entry_id}/trace", response_model=dict)
def trace_entry(entry_id: int) -> dict[str, Any]:
    """交付链路追溯：返回字段 → 报表任务 → 数据日期 → 产物摘要 → 审计记录。

    未绑定产物的服务返回可解释的空链路，而不是报错或伪造绑定关系。
    """
    trace = service.trace_artifact(entry_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"服务版本 {entry_id} 不存在或已归档")
    return trace


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条服务版本明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"服务版本 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条服务版本，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="服务版本已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条服务版本执行提交服务评审、发布服务、下线服务。

    发布服务需在 values 中携带 artifact_code（报表产物编号）；发布与产物
    绑定在同一事务内完成，失败时两侧同时退回。不允许的动作会被拦下。
    """
    action = str(payload.values.get("action") or "").strip()
    extra = {key: value for key, value in payload.values.items() if key != "action"}
    entry, message = service.run_action(entry_id, action, extra)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
