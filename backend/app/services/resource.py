"""资源计量业务规则：跨引擎汇总视图、结算冻结、审计回写与筛选口径都收在这里。"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.store import store

MODULE = "resource"
REQUIRED_FIELDS = ["记录编号", "计算引擎", "作业名称"]
METRIC_FIELDS = ["CPU核秒", "内存GB秒", "存储占用GB", "扫描数据量"]
STATUS_ORDER = ["草稿", "待汇总", "已结算", "已归档"]
ACTION_RULES = {"提交汇总": "待汇总", "结算确认": "已结算", "归档记录": "已归档"}
BATCH_ACTIONS = [*ACTION_RULES, "归入计费周期"]

# 计量单价（元）：视图估算与结算冻结共用同一套口径，保证各入口结果一致
UNIT_PRICES = {"CPU核秒": 0.0001, "内存GB秒": 0.00005, "扫描数据量": 0.5, "存储占用GB": 1.0}

# 计费周期只接受 YYYY-MM 且月份必须在 01-12 之间，其余一律视为非法周期
PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _valid_period(period: Any) -> bool:
    return isinstance(period, str) and bool(PERIOD_PATTERN.match(period.strip()))


def _to_number(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _estimate_amount(row: dict[str, Any]) -> float:
    """按当前单价估算一条记录的金额，未结算记录在视图中使用该口径。"""
    return round(sum(_to_number(row.get(field)) * price for field, price in UNIT_PRICES.items()), 2)


def _row_amount(row: dict[str, Any]) -> float:
    """已结算记录读取冻结金额，未结算记录按当前单价估算。"""
    if row.get("status") == "已结算" and row.get("结算金额") is not None:
        return round(_to_number(row.get("结算金额")), 2)
    return _estimate_amount(row)


def _next_id(module: str) -> int:
    return max((int(row.get("id", 0)) for row in store.rows(module)), default=0) + 1


def _write_audit(action: str, codes: list[str], affected: int, detail: str) -> dict[str, Any]:
    """动作完成后同步写一条审计日志，影响行数与本次实际生效的记录数一致。"""
    rows = store.rows("audit")
    entry = {
        "id": _next_id("audit"),
        "日志编号": f"AUDI-{len(rows) + 1:04d}",
        "操作类型": f"资源计量-{action}",
        "操作对象": "、".join(codes) if codes else "资源计量",
        "操作详情": detail,
        "操作来源": "资源计量",
        "执行时间": date.today().isoformat(),
        "影响行数": str(affected),
        "回滚能力": "不可回滚" if action == "结算确认" else "可回滚",
        "status": "待审核",
        "pending": True,
        "abnormal": False,
    }
    rows.append(entry)
    return entry


def _write_catalog_todo(period: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    """结算完成后跨模块回写一条目录待办，结算人员可在数据目录继续跟进。"""
    rows = store.rows("catalog")
    engines = sorted({str(row.get("计算引擎", "")) for row in records if row.get("计算引擎")})
    entry = {
        "id": _next_id("catalog"),
        "编目编号": f"CATA-{len(rows) + 1:04d}",
        "数据集名称": f"计量结算单-{period}",
        "存储路径": f"/settlement/{period}",
        "文件格式": "PARQUET",
        "所属分层": "gold",
        "负责人": "结算中心",
        "业务域标签": f"资源计量/{'、'.join(engines)}" if engines else "资源计量",
        "编目版本": "v1",
        "status": "草稿",
        "pending": True,
        "abnormal": False,
    }
    rows.append(entry)
    return entry


class ResourceService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        engine: str | None = None,
        period: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if engine:
            rows = [row for row in rows if row.get("计算引擎") == engine]
        if period:
            rows = [row for row in rows if row.get("计费周期") == period]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        """登记计量记录；同一记录编号重复提交只计一次，非法计费周期直接拒绝。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}", False
        period = str(values.get("计费周期") or "").strip()
        if period and not _valid_period(period):
            return None, f"计费周期「{period}」不合法，应为 YYYY-MM 格式（月份 01-12）", False
        code = str(values.get("记录编号") or "").strip()
        for row in store.rows(MODULE):
            if str(row.get("记录编号", "")) == code:
                return row, f"记录 {code} 已存在，同一记录重复提交只计一次", True
        entry: dict[str, Any] = {"id": _next_id(MODULE)}
        for field in [*REQUIRED_FIELDS, *METRIC_FIELDS]:
            if field in values:
                entry[field] = values.get(field)
        entry["计费周期"] = period
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        store.rows(MODULE).append(entry)
        return entry, "计量记录已登记", True

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str, bool]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"计量记录 {entry_id} 不存在或已归档", False
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于资源计量可执行范围", False
        ok, _, message = self._apply_action(entry, action, sync=True)
        if not ok:
            return None, message, False
        return entry, message, True

    def run_batch(
        self,
        action: str,
        ids: list[Any],
        period: str | None = None,
    ) -> tuple[str, int, bool]:
        """批量执行动作：自动去重记录，返回实际生效行数并同步审计。"""
        if action not in BATCH_ACTIONS:
            return f"动作「{action}」不属于资源计量可执行范围", 0, False
        unique_ids = list(dict.fromkeys(str(item) for item in ids))
        if not unique_ids:
            return "未选择任何计量记录", 0, False
        if action == "归入计费周期":
            if not period or not _valid_period(period):
                return f"计费周期「{period or '空'}」不合法，应为 YYYY-MM 格式（月份 01-12）", 0, False
            return self._batch_assign_period(unique_ids, period.strip())

        entries: list[dict[str, Any]] = []
        missing: list[str] = []
        for raw_id in unique_ids:
            try:
                entry = store.find(MODULE, int(raw_id))
            except (TypeError, ValueError):
                entry = None
            if entry is None:
                missing.append(str(raw_id))
            else:
                entries.append(entry)
        affected = 0
        skipped: list[str] = []
        codes: list[str] = []
        for entry in entries:
            ok, changed, _ = self._apply_action(entry, action, sync=False)
            if ok and changed:
                affected += 1
                codes.append(str(entry.get("记录编号", entry.get("id"))))
            elif not changed:
                skipped.append(str(entry.get("记录编号", entry.get("id"))))
        message = f"{action}完成，影响行数 {affected}"
        if skipped:
            message += f"，跳过 {len(skipped)} 条（状态不允许或金额已冻结：{'、'.join(skipped)}）"
        if missing:
            message += f"，{len(missing)} 条记录不存在"
        if affected:
            detail = f"批量{action}，影响行数 {affected}"
            _write_audit(action, codes, affected, detail)
            if action == "结算确认":
                self._write_catalog_todos(entries)
        return message, affected, affected > 0

    def build_metering_view(
        self,
        *,
        engine: str | None = None,
        job: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """跨引擎计量视图：按引擎、作业与计费周期汇总，视图与导出共用这一份结果。"""
        for label, period in (("计费周期起", period_start), ("计费周期止", period_end)):
            if period and not _valid_period(period):
                return None, f"{label}「{period}」不合法，应为 YYYY-MM 格式（月份 01-12）"
        if period_start and period_end and period_start > period_end:
            return None, f"计费周期起「{period_start}」不能晚于计费周期止「{period_end}」"

        # 同一记录编号只计一次，重复上报的记录在汇总前剔除
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        duplicates = 0
        for row in store.rows(MODULE):
            if row.get("status") == "已归档":
                continue
            code = str(row.get("记录编号", ""))
            if code in seen:
                duplicates += 1
                continue
            seen.add(code)
            rows.append(row)

        if engine:
            rows = [row for row in rows if row.get("计算引擎") == engine]
        if job:
            rows = [row for row in rows if job in str(row.get("作业名称", ""))]
        if period_start:
            rows = [row for row in rows if str(row.get("计费周期", "")) >= period_start]
        if period_end:
            rows = [row for row in rows if str(row.get("计费周期", "")) <= period_end]

        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (str(row.get("计算引擎", "未标注")), str(row.get("计费周期", "未排期")))
            group = groups.setdefault(key, self._new_group(key[0], key[1]))
            job_name = str(row.get("作业名称", "未命名作业"))
            job_row = group["_jobs"].setdefault(job_name, self._new_job(job_name))
            for bucket in (group, job_row):
                self._accumulate(bucket, row)

        group_list = []
        for group in groups.values():
            jobs = sorted(group.pop("_jobs").values(), key=lambda item: item["作业名称"])
            group["jobs"] = jobs
            group_list.append(group)
        group_list.sort(key=lambda item: (item["计费周期"], item["计算引擎"]))

        totals = self._new_group("全部", "全部")
        totals.pop("_jobs")
        totals["重复剔除数"] = duplicates
        for group in group_list:
            for field in METRIC_FIELDS:
                totals[field] = round(totals[field] + group[field], 2)
            for field in ("记录数", "待汇总数", "已结算数", "异常数"):
                totals[field] += group[field]
            totals["金额合计"] = round(totals["金额合计"] + group["金额合计"], 2)

        view = {
            "filters": {
                "计算引擎": engine or "",
                "作业名称": job or "",
                "计费周期起": period_start or "",
                "计费周期止": period_end or "",
            },
            "prices": UNIT_PRICES,
            "groups": group_list,
            "totals": totals,
        }
        return view, None

    def _new_group(self, engine: str, period: str) -> dict[str, Any]:
        return {
            "计算引擎": engine,
            "计费周期": period,
            **{field: 0.0 for field in METRIC_FIELDS},
            "记录数": 0,
            "待汇总数": 0,
            "已结算数": 0,
            "异常数": 0,
            "金额合计": 0.0,
            "_jobs": {},
        }

    def _new_job(self, job_name: str) -> dict[str, Any]:
        return {
            "作业名称": job_name,
            **{field: 0.0 for field in METRIC_FIELDS},
            "记录数": 0,
            "待汇总数": 0,
            "已结算数": 0,
            "异常数": 0,
            "金额合计": 0.0,
        }

    def _accumulate(self, bucket: dict[str, Any], row: dict[str, Any]) -> None:
        for field in METRIC_FIELDS:
            bucket[field] = round(bucket[field] + _to_number(row.get(field)), 2)
        bucket["记录数"] += 1
        if row.get("status") == "待汇总":
            bucket["待汇总数"] += 1
        if row.get("status") == "已结算":
            bucket["已结算数"] += 1
        if row.get("abnormal"):
            bucket["异常数"] += 1
        bucket["金额合计"] = round(bucket["金额合计"] + _row_amount(row), 2)

    def _apply_action(self, entry: dict[str, Any], action: str, *, sync: bool) -> tuple[bool, bool, str]:
        """单条状态流转，返回（是否成功、是否实际变更、说明）；sync=True 时同步写审计与目录待办。"""
        status = str(entry.get("status", ""))
        code = str(entry.get("记录编号", entry.get("id")))
        if status == "已归档":
            return False, False, f"记录 {code} 已归档，不能再执行{action}"
        if action == "提交汇总":
            if status == "已结算":
                return False, False, f"记录 {code} 已结算，金额已冻结，不能再提交汇总"
            if status == "待汇总":
                return True, False, f"记录 {code} 已处于待汇总，重复提交只计一次"
            entry["status"] = "待汇总"
            entry["pending"] = True
            if sync:
                _write_audit("提交汇总", [code], 1, f"记录 {code} 提交汇总")
            return True, True, f"计量记录 {code} 已提交汇总"
        if action == "结算确认":
            if status == "已结算":
                return False, False, f"记录 {code} 已结算，金额 {entry.get('结算金额')} 元已冻结，不能重复结算"
            if status != "待汇总":
                return False, False, f"记录 {code} 仍为草稿，需先提交汇总再结算"
            # 结算即冻结金额：此后视图与导出都读取这份冻结结果，不再随单价变动
            entry["结算金额"] = _estimate_amount(entry)
            entry["结算时间"] = date.today().isoformat()
            entry["金额冻结"] = True
            entry["status"] = "已结算"
            entry["pending"] = False
            if sync:
                _write_audit("结算确认", [code], 1, f"记录 {code} 结算确认，冻结金额 {entry['结算金额']} 元")
                todo = _write_catalog_todo(str(entry.get("计费周期", "未排期")), [entry])
                return True, True, f"计量记录 {code} 已结算，金额 {entry['结算金额']} 元已冻结，目录待办 {todo['编目编号']} 已回写"
            return True, True, f"计量记录 {code} 已结算，金额 {entry['结算金额']} 元已冻结"
        if action == "归档记录":
            entry["status"] = "已归档"
            entry["pending"] = False
            if sync:
                _write_audit("归档记录", [code], 1, f"记录 {code} 归档")
            return True, True, f"计量记录 {code} 已归档"
        return False, False, f"动作「{action}」不属于资源计量可执行范围"

    def _batch_assign_period(self, ids: list[str], period: str) -> tuple[str, int, bool]:
        affected = 0
        skipped: list[str] = []
        codes: list[str] = []
        for raw_id in ids:
            try:
                entry = store.find(MODULE, int(raw_id))
            except (TypeError, ValueError):
                entry = None
            if entry is None:
                skipped.append(str(raw_id))
                continue
            code = str(entry.get("记录编号", entry.get("id")))
            if entry.get("status") in ("已结算", "已归档"):
                skipped.append(code)
                continue
            entry["计费周期"] = period
            affected += 1
            codes.append(code)
        message = f"已归入计费周期 {period}，影响行数 {affected}"
        if skipped:
            message += f"，跳过 {len(skipped)} 条（已结算或已归档：{'、'.join(skipped)}）"
        if affected:
            _write_audit("归入计费周期", codes, affected, f"批量归入计费周期 {period}，影响行数 {affected}")
        return message, affected, affected > 0

    def _write_catalog_todos(self, entries: list[dict[str, Any]]) -> None:
        """按计费周期把本批结算记录回写成目录待办，并同步资源状态为已结算。"""
        by_period: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            if entry.get("status") != "已结算":
                continue
            by_period.setdefault(str(entry.get("计费周期", "未排期")), []).append(entry)
        for period, records in by_period.items():
            _write_catalog_todo(period, records)
