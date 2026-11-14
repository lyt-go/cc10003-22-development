"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

并发与事务约定：
- 所有写操作都走 ``transaction()``：进入时对全库加锁并做深拷贝快照，
  业务在 with 块里直接改表，抛异常即整体回滚到快照，保证「产物登记 +
  服务发布」要么一起成功、要么两侧同时退回。
- 锁是可重入的，服务层之间互相调用（如排期登记产物）可以嵌套事务。
"""
from __future__ import annotations

import copy
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._lock = threading.RLock()
        self._depth = 0
        self._snapshot: dict[str, list[dict[str, Any]]] | None = None

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def next_id(self, module: str) -> int:
        return max((int(row.get("id", 0)) for row in self.rows(module)), default=0) + 1

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """事务边界：异常时把全部业务表回滚到进入前的快照。

        嵌套事务复用最外层快照，内层异常会冒泡到最外层统一回滚，
        避免内层提前恢复把外层尚未完成的改动冲掉。
        """
        with self._lock:
            if self._depth == 0:
                self._snapshot = copy.deepcopy(self._tables)
            self._depth += 1
            try:
                yield
            except BaseException:
                if self._depth == 1 and self._snapshot is not None:
                    self._tables = self._snapshot
                    self._snapshot = None
                self._depth = max(self._depth - 1, 0)
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self._snapshot = None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
