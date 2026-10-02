"""油料管理接口：维护油料记录，覆盖记录消耗、申请补油、完成补油等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.fuel import FuelService

router = APIRouter(prefix="/api/fuel", tags=["油料管理"])

service = FuelService()

LIST_FIELDS = ["记录编号", "所属站点", "油料类型", "调入量", "当前存量", "发电消耗", "累计调运", "油料日期", "油料状态"]
STATUSES = ["储备充足", "油量偏低", "需补油", "已补充"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="储备充足、油量偏低、需补油、已补充；需补油清单传「需补油」"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤油料管理列表；没有数据时返回空页，不报错。

    列表与详情共用 service 层同一份存量口径，保证两页数字对得上。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def fuel_stats() -> dict[str, int]:
    """看板卡片统计：与需补油清单取同一状态口径。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出油料管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "fuel", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条油料记录明细（含历史台账）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"油料记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条油料记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="油料记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条油料记录执行记录消耗、申请补油、完成补油。

    同一笔消耗/补油可携带幂等凭证 token：重复提交命中凭证时只返回提示，不再扣减或增加存量。
    """
    action = str(payload.values.get("action") or "").strip()
    entry, message, _duplicate = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.put("/{entry_id}/ledger/{seq}", response_model=ActionResult)
def adjust_ledger(entry_id: int, seq: int, payload: EntryPayload) -> ActionResult:
    """调整某笔补油调运量：当前存量按新口径重算，历史台账快照保留当时的数。"""
    entry, message = service.adjust_resupply(entry_id, seq, payload.values.get("amount"))
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
