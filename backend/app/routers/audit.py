"""发布审计接口：只追加的审计日志查询，覆盖排期登记与服务发布/回滚。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import PageResult
from app.services.audit import AuditService

router = APIRouter(prefix="/api/audit-logs", tags=["发布审计"])

service = AuditService()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按关联编号、动作类型或操作对象检索"),
    result: str | None = Query(default=None, description="成功、已回滚、生成失败、已中断"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按结果与关键词过滤审计日志；无日志时返回空页。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, result=result, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/by-ref/{ref_code}")
def list_by_ref(ref_code: str) -> dict:
    """按关联编号（任务编号或服务编号）查同一对象的完整审计轨迹。"""
    rows = service.records_of(ref_code)
    return {
        "关联编号": ref_code,
        "total": len(rows),
        "items": rows,
        "message": "该编号暂无审计记录" if not rows else "",
    }
