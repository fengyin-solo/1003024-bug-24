"""油料管理业务规则：存量口径、台账、状态流转与幂等都收在这里。

口径约定（全模块只此一份，列表页、详情页、需补油清单共用）：
    当前存量 = 初始调入 + Σ补油调运 − Σ发电消耗
「当前存量」不单独落库，始终由台账即时派生；台账每笔事件冻结事件发生后的余额
快照（balance_after），历史台账永远保留当时的数，后续补油口径调整只重算当前存量。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "fuel"
REQUIRED_FIELDS = ["记录编号", "所属站点", "油料类型"]
STATUS_ORDER = ["储备充足", "油量偏低", "需补油", "已补充"]
ACTION_RULES = {"记录消耗": "油量偏低", "申请补油": "需补油", "完成补油": "已补充"}

LEDGER_CONSUME = "发电消耗"
LEDGER_RESUPPLY = "补油调运"


def _to_number(value: Any) -> float | None:
    """把入参解析成非负数值；空值与无法解析的值返回 None，由调用方报错。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _fmt(number: float) -> float:
    """展示用：整数量去掉小数点，避免列表页冒出 100.0 这种数。"""
    return int(number) if float(number).is_integer() else round(number, 2)


class FuelService:
    # ---- 存量口径：全模块唯一的计算入口 ------------------------------------------------

    def _balance(self, entry: dict[str, Any], upto: int | None = None) -> float:
        """按台账计算存量；upto 指定只算前几笔（用于校验/快照），None 表示算到最新。"""
        balance = float(entry.get("_initial", 0) or 0)
        for event in entry.get("_ledger", [])[:upto]:
            amount = float(event["amount"])
            balance += -amount if event["type"] == LEDGER_CONSUME else amount
        return balance

    def _total(self, entry: dict[str, Any], event_type: str) -> float:
        return sum(
            float(event["amount"])
            for event in entry.get("_ledger", [])
            if event["type"] == event_type
        )

    def _normalize(self, entry: dict[str, Any]) -> dict[str, Any]:
        """兼容历史/种子数据：把散落的数量字段收成台账，存量以后一律从台账派生。"""
        if "_normalized" in entry:
            return entry
        initial = _to_number(entry.get("调入量"))
        entry["_initial"] = initial if initial is not None else 0.0
        events: list[dict[str, Any]] = []
        consumed = _to_number(entry.get("发电消耗"))
        if consumed and consumed > 0:
            events.append({
                "seq": 1,
                "type": LEDGER_CONSUME,
                "amount": consumed,
                "date": str(entry.get("油料日期") or ""),
                "balance_after": entry["_initial"] - consumed,
                "token": None,
            })
        entry["_ledger"] = events
        entry["_tokens"] = set()
        entry["_normalized"] = True
        return entry

    # ---- 出参：列表与详情取同一份口径 --------------------------------------------------

    def _serialize(self, entry: dict[str, Any], *, with_ledger: bool = False) -> dict[str, Any]:
        status = entry.get("status") or STATUS_ORDER[0]
        data: dict[str, Any] = {
            "id": entry["id"],
            "记录编号": entry.get("记录编号"),
            "所属站点": entry.get("所属站点"),
            "油料类型": entry.get("油料类型"),
            "调入量": _fmt(float(entry.get("_initial", 0) or 0)),
            "当前存量": _fmt(self._balance(entry)),
            "发电消耗": _fmt(self._total(entry, LEDGER_CONSUME)),
            "累计调运": _fmt(self._total(entry, LEDGER_RESUPPLY)),
            "油料日期": entry.get("油料日期"),
            "油料状态": status,
            "status": status,
        }
        if with_ledger:
            data["台账"] = [
                {
                    "序号": event["seq"],
                    "类型": event["type"],
                    "数量": _fmt(float(event["amount"])),
                    "日期": event.get("date") or "",
                    "事件后余额": _fmt(float(event["balance_after"])),
                    "可调整": event["type"] == LEDGER_RESUPPLY,
                }
                for event in entry.get("_ledger", [])
            ]
        return data

    # ---- 查询 --------------------------------------------------------------------------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._normalize(dict(row)) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._serialize(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._serialize(self._normalize(entry), with_ledger=True)

    def stats(self) -> dict[str, int]:
        """看板统计与需补油清单同样基于收口后的状态字段，不再各算各的。"""
        rows = [self._normalize(row) for row in store.rows(MODULE)]
        return {
            "储备充足": sum(1 for row in rows if row.get("status") == "储备充足"),
            "油量偏低": sum(1 for row in rows if row.get("status") == "油量偏低"),
            "需补油": sum(1 for row in rows if row.get("status") == "需补油"),
        }

    # ---- 写入 --------------------------------------------------------------------------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        initial = _to_number(values.get("调入量"))
        entry["_initial"] = initial if initial is not None else 0.0
        entry["_ledger"] = []
        entry["_tokens"] = set()
        entry["_normalized"] = True
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["油料日期"] = str(values.get("油料日期") or date.today().isoformat())
        rows.append(entry)
        return self._serialize(entry), []

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """执行动作，返回（明细, 提示, 是否命中重复提交）。"""
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"油料记录 {entry_id} 不存在或已归档", False
        entry = self._normalize(entry)
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于油料管理可执行范围", False

        if action == "申请补油":
            if entry["status"] == "已补充":
                return self._serialize(entry), "该笔补油已完成，无需再次申请", False
            entry["status"] = "需补油"
            entry["pending"] = True
            return self._serialize(entry), "已加入需补油清单", False

        amount = _to_number(values.get("amount"))
        if amount is None or amount <= 0:
            label = "发电消耗量" if action == "记录消耗" else "补油调运量"
            return None, f"{label}必须是大于 0 的数字", False
        on_date = str(values.get("date") or date.today().isoformat())
        token = str(values.get("token") or "").strip()

        if action == "记录消耗":
            # 同一笔消耗只允许扣一次：请求凭证已见过就原样返回，不再动存量。
            if token and token in entry["_tokens"]:
                return self._serialize(entry), "该笔发电消耗已提交过，未重复扣减", True
            if amount > self._balance(entry):
                return None, f"发电消耗 {_fmt(amount)} 超过当前存量 {_fmt(self._balance(entry))}，已拦下", False
            self._append_event(entry, LEDGER_CONSUME, amount, on_date, token)
            entry["status"] = "油量偏低" if entry["status"] == "储备充足" else entry["status"]
            entry["pending"] = entry["status"] != "已补充"
            return self._serialize(entry), f"发电消耗 {_fmt(amount)} 已入账，当前存量已扣减", False

        # 完成补油：调运量入账并立即从需补油清单退出。
        if token and token in entry["_tokens"]:
            return self._serialize(entry), "该笔补油已提交过，未重复增加存量", True
        self._append_event(entry, LEDGER_RESUPPLY, amount, on_date, token)
        entry["status"] = "已补充"
        entry["pending"] = False
        return self._serialize(entry), f"补油 {_fmt(amount)} 已完成，已退出需补油清单", False

    def _append_event(
        self, entry: dict[str, Any], event_type: str, amount: float, on_date: str, token: str
    ) -> dict[str, Any]:
        event = {
            "seq": len(entry["_ledger"]) + 1,
            "type": event_type,
            "amount": amount,
            "date": on_date,
            "balance_after": 0.0,
            "token": token or None,
        }
        entry["_ledger"].append(event)
        event["balance_after"] = self._balance(entry)
        if token:
            entry["_tokens"].add(token)
        return event

    def adjust_resupply(
        self, entry_id: int, seq: int, amount: Any
    ) -> tuple[dict[str, Any] | None, str]:
        """补油口径变更：只改补油事件数量并重算当前存量；历史台账快照保留当时的数。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"油料记录 {entry_id} 不存在或已归档"
        entry = self._normalize(entry)
        event = next((item for item in entry["_ledger"] if int(item["seq"]) == seq), None)
        if event is None:
            return None, f"台账第 {seq} 笔不存在"
        if event["type"] != LEDGER_RESUPPLY:
            return None, "仅支持调整补油调运量，发电消耗请以红冲方式另记"
        new_amount = _to_number(amount)
        if new_amount is None or new_amount <= 0:
            return None, "补油调运量必须是大于 0 的数字"
        event["amount"] = new_amount
        # 快照是「当时的数」：不回写历史事件，只有当前存量按新口径重算。
        return self._serialize(entry, with_ledger=True), "补油口径已更新，当前存量已按新口径重算（历史台账保留当时余额）"
