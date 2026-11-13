"""资源计量接口：计量明细维护 + 跨引擎计量视图，视图与导出共用同一份结算结果。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.resource import ResourceService

router = APIRouter(prefix="/api/resource", tags=["资源计量"])

service = ResourceService()

LIST_FIELDS = ["记录编号", "计算引擎", "作业名称", "CPU核秒", "内存GB秒", "存储占用GB", "扫描数据量", "计费周期"]
STATUSES = ["草稿", "待汇总", "已结算", "已归档"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="草稿、待汇总、已结算、已归档"),
    engine: str | None = Query(default=None, description="按计算引擎过滤，如 Spark、Flink"),
    period: str | None = Query(default=None, description="按计费周期过滤，格式 YYYY-MM"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号、状态、引擎与计费周期过滤计量明细；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, engine=engine, period=period, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/metering")
def metering_view(
    engine: str | None = Query(default=None, description="按计算引擎过滤"),
    job: str | None = Query(default=None, description="按作业名称检索"),
    period_start: str | None = Query(default=None, description="计费周期起，格式 YYYY-MM"),
    period_end: str | None = Query(default=None, description="计费周期止，格式 YYYY-MM"),
) -> dict[str, Any]:
    """跨引擎计量视图：按引擎、作业与时间区间汇总核心指标，非法计费周期直接拒绝。"""
    view, error = service.build_metering_view(
        engine=engine, job=job, period_start=period_start, period_end=period_end
    )
    if error:
        raise HTTPException(status_code=400, detail=error)
    return view


@router.get("/metering/export")
def metering_export(
    engine: str | None = Query(default=None, description="按计算引擎过滤"),
    job: str | None = Query(default=None, description="按作业名称检索"),
    period_start: str | None = Query(default=None, description="计费周期起，格式 YYYY-MM"),
    period_end: str | None = Query(default=None, description="计费周期止，格式 YYYY-MM"),
) -> dict[str, Any]:
    """导出当前计量视图：与视图读取同一份结算结果，分组、周期与筛选口径完全一致。"""
    view, error = service.build_metering_view(
        engine=engine, job=job, period_start=period_start, period_end=period_end
    )
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"module": "resource", "view": "跨引擎计量视图", **view}


@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    engine: str | None = Query(default=None),
    period: str | None = Query(default=None),
) -> dict[str, Any]:
    """导出资源计量明细清单：与列表保持同一过滤口径。"""
    items, total = service.list_entries(keyword=keyword, status=status, engine=engine, period=period, page=1, size=10000)
    return {"module": "resource", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条计量记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"计量记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记计量记录：缺字段说明原因，非法计费周期拒绝，同一记录编号重复提交只计一次。"""
    entry, message, ok = service.create_entry(payload.values)
    return ActionResult(ok=ok, message=message, entry=entry)


@router.post("/batch", response_model=ActionResult)
def run_batch(payload: EntryPayload) -> ActionResult:
    """批量动作：提交汇总、结算确认、归档记录、归入计费周期；返回实际影响行数。"""
    action = str(payload.values.get("action") or "").strip()
    ids = payload.values.get("ids") or []
    if not isinstance(ids, list):
        return ActionResult(ok=False, message="ids 应为记录 id 列表")
    period = payload.values.get("计费周期")
    message, affected, ok = service.run_batch(action, ids, str(period) if period else None)
    return ActionResult(ok=ok, message=message, entry={"影响行数": affected})


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条计量记录执行提交汇总、结算确认、归档记录；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message, ok = service.run_action(entry_id, action)
    return ActionResult(ok=ok, message=message, entry=entry)
