"""油料管理存量口径测试：同一条口径在列表、详情、清单、台账之间必须收口。"""
from __future__ import annotations

import unittest

from app.services import fuel as fuel_module
from app.services.fuel import FuelService


class FuelStockTest(unittest.TestCase):
    def setUp(self) -> None:
        # 每个用例一份干净的内存表，避免种子数据干扰
        fuel_module.store._tables[fuel_module.MODULE] = [
            {
                "id": 1,
                "status": "储备充足",
                "pending": True,
                "abnormal": False,
                "记录编号": "FUEL-T1",
                "所属站点": "测试站",
                "油料类型": "0号柴油",
                "调入量": 100,
                "发电消耗": 0,
                "油料日期": "2026-10-01",
                "油料状态": "储备充足",
            }
        ]
        self.service = FuelService()

    def test_consume_deducts_current_stock_and_list_matches_detail(self) -> None:
        """记录消耗后存量立刻扣减，且列表页与详情页同一份数。"""
        entry, message, duplicate = self.service.run_action(
            1, "记录消耗", {"amount": 30, "date": "2026-10-02", "token": "c1"}
        )
        self.assertIsNotNone(entry)
        self.assertFalse(duplicate)
        self.assertEqual(entry["当前存量"], 70)
        self.assertIn("已扣减", message)

        items, total = self.service.list_entries()
        self.assertEqual(total, 1)
        detail = self.service.get_entry(1)
        self.assertEqual(items[0]["当前存量"], detail["当前存量"])
        self.assertEqual(detail["当前存量"], 70)
        self.assertEqual(detail["发电消耗"], 30)

    def test_duplicate_consume_submission_deducts_only_once(self) -> None:
        """同一笔消耗（同 token）连提两次，只扣一次，第二次给出重复提示。"""
        first, _, first_dup = self.service.run_action(
            1, "记录消耗", {"amount": 30, "token": "same"}
        )
        second, message, second_dup = self.service.run_action(
            1, "记录消耗", {"amount": 30, "token": "same"}
        )
        self.assertFalse(first_dup)
        self.assertTrue(second_dup)
        self.assertEqual(first["当前存量"], 70)
        self.assertEqual(second["当前存量"], 70)
        self.assertIn("已提交过", message)
        # 不同 token 是两笔真实消耗，应继续扣
        third, _, third_dup = self.service.run_action(
            1, "记录消耗", {"amount": 10, "token": "other"}
        )
        self.assertFalse(third_dup)
        self.assertEqual(third["当前存量"], 60)

    def test_consume_over_current_stock_is_rejected(self) -> None:
        """消耗量超过存量时拦下，不动存量。"""
        entry, message, _ = self.service.run_action(
            1, "记录消耗", {"amount": 120, "token": "x"}
        )
        self.assertIsNone(entry)
        self.assertIn("超过当前存量", message)
        self.assertEqual(self.service.get_entry(1)["当前存量"], 100)

    def test_completed_resupply_leaves_pending_list_and_adds_stock(self) -> None:
        """完成补油后调运量入账、退出需补油清单；清单与记录取同一份存量。"""
        self.service.run_action(1, "申请补油", {})
        pending, pending_total = self.service.list_entries(status="需补油")
        self.assertEqual(pending_total, 1)
        self.assertTrue(self.service.stats()["需补油"] == 1)

        entry, _, _ = self.service.run_action(
            1, "完成补油", {"amount": 50, "date": "2026-10-03", "token": "r1"}
        )
        self.assertEqual(entry["当前存量"], 150)
        self.assertEqual(entry["油料状态"], "已补充")

        pending, pending_total = self.service.list_entries(status="需补油")
        self.assertEqual(pending_total, 0)
        self.assertEqual(self.service.stats()["需补油"], 0)

        # 清单为空时，记录本身的存量仍与补油后一致
        detail = self.service.get_entry(1)
        self.assertEqual(detail["当前存量"], 150)
        self.assertEqual(detail["累计调运"], 50)

    def test_resupply_recalc_keeps_history_snapshots(self) -> None:
        """补油口径变更后当前存量按新口径重算，历史台账快照保留当时的数。"""
        self.service.run_action(1, "记录消耗", {"amount": 20, "date": "2026-10-02", "token": "c1"})
        self.service.run_action(1, "完成补油", {"amount": 40, "date": "2026-10-03", "token": "r1"})
        detail = self.service.get_entry(1)
        self.assertEqual(detail["当前存量"], 120)
        resupply_event = next(event for event in detail["台账"] if event["类型"] == "补油调运")
        self.assertEqual(resupply_event["事件后余额"], 120)

        # 补油口径 40 -> 60：当前存量重算为 140，历史快照仍是当时的 120
        updated, message = self.service.adjust_resupply(1, resupply_event["序号"], 60)
        self.assertIsNotNone(updated)
        self.assertEqual(updated["当前存量"], 140)
        self.assertIn("重算", message)
        kept = next(event for event in updated["台账"] if event["序号"] == resupply_event["序号"])
        self.assertEqual(kept["事件后余额"], 120)
        self.assertEqual(kept["数量"], 60)

        # 列表与详情继续同口径
        items, _ = self.service.list_entries()
        self.assertEqual(items[0]["当前存量"], 140)

    def test_seed_numeric_fields_normalize_into_one_balance(self) -> None:
        """数值型调入量/消耗的历史记录归一化后，存量按唯一口径派生。"""
        fuel_module.store._tables[fuel_module.MODULE] = [
            {
                "id": 9,
                "status": "油量偏低",
                "记录编号": "FUEL-T9",
                "所属站点": "老站",
                "油料类型": "0号柴油",
                "调入量": 300,
                "发电消耗": 260,
                "油料日期": "2026-09-02",
                "油料状态": "油量偏低",
            }
        ]
        detail = FuelService().get_entry(9)
        self.assertEqual(detail["调入量"], 300)
        self.assertEqual(detail["发电消耗"], 260)
        self.assertEqual(detail["当前存量"], 40)


if __name__ == "__main__":
    unittest.main()
