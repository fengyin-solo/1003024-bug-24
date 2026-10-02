"""油料管理业务规则：状态流转、字段校验与筛选口径都收在这里。

存量口径全模块只认一条公式：当前存量 = 调入量 - 发电消耗。
任何动作改了调入量或发电消耗，都必须经过 _recalc_stock 重算当前存量，
列表、详情、需补油清单、导出读的都是同一条记录，口径自然一致。
台账只追加不回改，历史记录保留动作发生当时的数。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "fuel"
REQUIRED_FIELDS = ["记录编号", "所属站点", "油料类型"]
STATUS_ORDER = ["储备充足", "油量偏低", "需补油", "已补充"]
ACTION_RULES = {"记录消耗": "油量偏低", "申请补油": "需补油", "完成补油": "已补充"}
EXTRA_ACTIONS = {"调整调入量"}
NEGATIVE_ACTIONS: list[str] = []

REFILL_STATUS = "需补油"


def _to_number(value: Any) -> float:
    """台账字段统一按数值处理；空值或非数值按 0 计，不让脏数据打断结算。"""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _fmt_number(value: float) -> int | float:
    """整数存量按整数落库，避免列表页出现 100.0 这种口径噪音。"""
    return int(value) if float(value).is_integer() else round(value, 2)


class FuelService:
    # ---------- 读取：列表、详情、需补油清单都取同一份存量 ----------

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
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def refill_list(self) -> list[dict[str, Any]]:
        """需补油清单：与油料记录读同一份存量，已补充的记录自然退出。"""
        return [row for row in store.rows(MODULE) if row.get("status") == REFILL_STATUS]

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---------- 登记 ----------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        transfer = values.get("调入量")
        if not str(transfer or "").strip() and str(values.get("当前存量") or "").strip():
            # 只给了期初存量时，按一笔调入登记，口径仍然是 调入量 - 发电消耗
            transfer = values.get("当前存量")
        entry["调入量"] = _fmt_number(_to_number(transfer))
        entry["发电消耗"] = _fmt_number(_to_number(values.get("发电消耗")))
        entry["油料日期"] = values.get("油料日期") or ""
        entry["油料状态"] = values.get("油料状态") or ""
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["台账"] = []
        self._recalc_stock(entry)
        rows.append(entry)
        return entry, []

    # ---------- 动作：消耗、补油、口径调整都收口到同一条存量公式 ----------

    def run_action(self, entry_id: int, action: str, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"油料记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES and action not in EXTRA_ACTIONS:
            return None, f"动作「{action}」不属于油料管理可执行范围"
        if action == "记录消耗":
            return self._record_consumption(entry, values)
        if action == "完成补油":
            return self._complete_refill(entry, values)
        if action == "调整调入量":
            return self._adjust_transfer(entry, values)
        return self._apply_status(entry, action)

    def _apply_status(self, entry: dict[str, Any], action: str) -> tuple[dict[str, Any], str]:
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if target == REFILL_STATUS:
            return entry, "已申请补油，记录进入需补油清单"
        return entry, f"油料记录已{action}"

    def _record_consumption(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        ticket = str(values.get("消耗单号") or "").strip()
        if not ticket:
            return None, "记录消耗需要提供消耗单号，重复提交时才能识别为同一笔"
        amount = _to_number(values.get("消耗量"))
        if amount <= 0:
            return None, "消耗量需为大于 0 的数值"
        if self._ticket_used(entry, "发电消耗", ticket):
            return entry, f"消耗单号 {ticket} 已入账，本次未重复扣减当前存量"
        entry["发电消耗"] = _fmt_number(_to_number(entry.get("发电消耗")) + amount)
        self._recalc_stock(entry)
        self._append_ledger(entry, 类型="发电消耗", 单号=ticket, 数量=_fmt_number(amount), 说明="记录消耗")
        # 需补油中的记录不能被一笔消耗冲回低油量，否则会被错误地移出需补油清单
        if entry.get("status") != REFILL_STATUS:
            entry["status"] = "油量偏低"
        entry["pending"] = True
        entry["abnormal"] = False
        return entry, f"已记录发电消耗 {_fmt_number(amount)}，当前存量同步扣减为 {entry['当前存量']}"

    def _complete_refill(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        ticket = str(values.get("补油单号") or "").strip()
        amount = _to_number(values.get("补油量"))
        if amount > 0:
            if not ticket:
                return None, "登记补油量需要提供补油单号，重复提交时才能识别为同一笔"
            if self._ticket_used(entry, "补油", ticket):
                return entry, f"补油单号 {ticket} 已入账，本次未重复累加调入量"
            entry["调入量"] = _fmt_number(_to_number(entry.get("调入量")) + amount)
            self._recalc_stock(entry)
            self._append_ledger(entry, 类型="补油", 单号=ticket, 数量=_fmt_number(amount), 说明="完成补油")
        elif ticket and self._ticket_used(entry, "补油", ticket):
            return entry, f"补油单号 {ticket} 已入账，本次未重复累加调入量"
        entry["status"] = "已补充"
        entry["pending"] = False
        entry["abnormal"] = False
        return entry, f"补油完成，已退出需补油清单，当前存量按最新口径重算为 {entry['当前存量']}"

    def _adjust_transfer(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        raw = values.get("调入量", values.get("新调入量"))
        if not str(raw or "").strip():
            return None, "调整调入量需要给出新的调入量数值"
        old_value = _to_number(entry.get("调入量"))
        new_value = _to_number(raw)
        if new_value == old_value:
            return entry, "调入量未变化，当前存量保持原口径"
        entry["调入量"] = _fmt_number(new_value)
        self._recalc_stock(entry)
        self._append_ledger(
            entry,
            类型="口径调整",
            单号=str(values.get("调整单号") or "").strip(),
            数量=None,
            说明=f"调入量由 {_fmt_number(old_value)} 调整为 {_fmt_number(new_value)}，存量按新口径重算",
        )
        return entry, f"调入量已调整，当前存量按新口径重算为 {entry['当前存量']}，历史台账保留当时的数"

    # ---------- 口径收口：所有入口共用 ----------

    def _recalc_stock(self, entry: dict[str, Any]) -> None:
        """当前存量 = 调入量 - 发电消耗，全模块唯一结算点。"""
        stock = _to_number(entry.get("调入量")) - _to_number(entry.get("发电消耗"))
        entry["当前存量"] = _fmt_number(stock)

    def _append_ledger(self, entry: dict[str, Any], *, 类型: str, 单号: str, 数量: Any, 说明: str) -> None:
        """台账只追加不回改，每条记录保存动作发生当时的口径数值。"""
        ledger = entry.setdefault("台账", [])
        ledger.append({
            "序号": len(ledger) + 1,
            "类型": 类型,
            "单号": 单号,
            "数量": 数量,
            "调入量": entry.get("调入量"),
            "发电消耗": entry.get("发电消耗"),
            "当前存量": entry.get("当前存量"),
            "说明": 说明,
            "时间": datetime.now().isoformat(timespec="seconds"),
        })

    def _ticket_used(self, entry: dict[str, Any], 类型: str, 单号: str) -> bool:
        """同一笔业务单号只入账一次，台账即幂等台账。"""
        return any(rec.get("类型") == 类型 and rec.get("单号") == 单号 for rec in entry.get("台账", []))
