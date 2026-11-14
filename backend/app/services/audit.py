"""发布审计服务：记录排期产物登记与数据服务发布/回滚的每一次动作。

审计日志只追加、不修改，用于回答「哪个服务版本在什么时候绑定了哪一份
报表产物」以及「哪次联动失败、两侧是否一起退回」。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "auditlog"

# 结果口径：成功/失败成对出现，失败记录保证发布与登记的回退可追溯。
RESULT_OK = "成功"
RESULT_ROLLED_BACK = "已回滚"


class AuditService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        result: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)), reverse=True)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("关联编号", ""))
                or keyword in str(row.get("动作类型", ""))
                or keyword in str(row.get("操作对象", ""))
            ]
        if result:
            rows = [row for row in rows if row.get("结果") == result]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def records_of(self, ref_code: str) -> list[dict[str, Any]]:
        return [
            row
            for row in sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)))
            if row.get("关联编号") == ref_code
        ]

    def record(
        self,
        *,
        action: str,
        target: str,
        ref_code: str,
        result: str,
        detail: str,
        service_version: str = "",
        artifact_code: str = "",
    ) -> dict[str, Any]:
        entry = {
            "id": store.next_id(MODULE),
            "动作类型": action,
            "操作对象": target,
            "关联编号": ref_code,
            "服务版本号": service_version,
            "产物编号": artifact_code,
            "结果": result,
            "说明": detail,
            "记录时间": datetime.now().isoformat(timespec="seconds"),
        }
        store.rows(MODULE).append(entry)
        return entry
