"""报表产物登记接口：查询每次排期生成的不可变产物。

产物登记由报表任务「确认排期」在事务内自动完成，本模块只提供只读查询，
不提供修改/删除入口，保证旧产物不可变。空态与异常态都带可读说明。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import PageResult
from app.services.reportartifact import ReportArtifactService

router = APIRouter(prefix="/api/report-artifacts", tags=["报表产物登记"])

service = ReportArtifactService()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按产物编号或任务编号检索"),
    status: str | None = Query(default=None, description="已登记、生成失败、已中断"),
    task_code: str | None = Query(default=None, description="按报表任务编号过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """列出报表产物；任务尚未排期时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, task_code=task_code, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出全部报表产物，含异常产物，便于审计核对。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "reportartifact", "total": total, "items": items}


@router.get("/by-task/{task_id}")
def list_by_task(task_id: int) -> dict[str, Any]:
    """按报表任务 id 查询该任务的全部排期产物（含失败/中断记录）。"""
    rows = service.artifacts_of_task(task_id)
    return {
        "报表任务id": task_id,
        "total": len(rows),
        "items": rows,
        "message": "该报表任务暂无排期产物，可在报表调度页执行确认排期" if not rows else "",
    }


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict[str, Any]:
    """读取单条产物明细；不存在时给出可读说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"报表产物 {entry_id} 不存在或已归档")
    return entry
