import csv
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from report import (
    Contract, DataValidationError, Payment, Work, allocate_contract, load_data,
)


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.contract = Contract("D-1", "Подрядчик", Decimal("200.00"), date(2026, 1, 1))
        self.works = [
            Work("W-1", "D-1", "Первая", Decimal("100.00"), "done", date(2026, 1, 10), None),
            Work("W-2", "D-1", "Вторая", Decimal("100.00"), "planned", None, None),
        ]

    def payment(self, payment_id, amount, *, work_id=None, paid_at=date(2026, 1, 5), refunded_at=None):
        return Payment(
            payment_id, "D-1", work_id, "Тест", Decimal(amount),
            "refunded" if refunded_at else "paid", date(2026, 1, 4), paid_at, refunded_at,
        )

    def test_direct_payment_is_applied_before_common_advance(self):
        payments = [self.payment("P-1", "150.00"), self.payment("P-2", "25.00", work_id="W-1")]
        results, total, unallocated = allocate_contract(
            self.contract, self.works, payments, date(2026, 1, 20)
        )
        self.assertEqual(results[0].paid, Decimal("100.00"))
        self.assertEqual(results[1].paid, Decimal("75.00"))
        self.assertEqual(total, Decimal("175.00"))
        self.assertEqual(unallocated, Decimal("0.00"))

    def test_payment_and_refund_boundaries_are_inclusive(self):
        payment = self.payment("P-1", "50.00", refunded_at=date(2026, 1, 10))
        _, total_before, _ = allocate_contract(self.contract, self.works, [payment], date(2026, 1, 9))
        _, total_on_refund, _ = allocate_contract(self.contract, self.works, [payment], date(2026, 1, 10))
        self.assertEqual(total_before, Decimal("50.00"))
        self.assertEqual(total_on_refund, Decimal("0.00"))

    def test_future_payment_is_excluded(self):
        payment = self.payment("P-1", "50.00", paid_at=date(2026, 1, 21))
        _, total, _ = allocate_contract(self.contract, self.works, [payment], date(2026, 1, 20))
        self.assertEqual(total, Decimal("0.00"))

    def test_cancelled_work_has_zero_obligation_and_is_skipped(self):
        cancelled = Work(
            "W-1", "D-1", "Первая", Decimal("100.00"), "cancelled", None, date(2026, 1, 10)
        )
        results, _, unallocated = allocate_contract(
            self.contract, [cancelled, self.works[1]], [self.payment("P-1", "150.00")],
            date(2026, 1, 20),
        )
        self.assertEqual(results[0].payable_price, Decimal("0.00"))
        self.assertEqual(results[1].paid, Decimal("100.00"))
        self.assertEqual(unallocated, Decimal("50.00"))

    def test_future_completion_is_planned_on_report_date(self):
        future_done = Work(
            "W-3", "D-1", "Будущая", Decimal("50.00"), "done", date(2026, 2, 1), None
        )
        self.assertEqual(future_done.status_on(date(2026, 1, 31)), "planned")
        self.assertEqual(future_done.status_on(date(2026, 2, 1)), "done")


class ValidationTests(unittest.TestCase):
    def write_csv(self, directory, filename, fieldnames, rows):
        with (directory / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def valid_files(self, directory):
        self.write_csv(directory, "contracts.csv", ["contract_id", "contractor", "amount", "signed_at"], [{
            "contract_id": "D-1", "contractor": "A", "amount": "100.00", "signed_at": "2026-01-01"
        }])
        self.write_csv(directory, "works.csv", [
            "work_id", "contract_id", "title", "price", "status", "completed_at", "cancelled_at"
        ], [{
            "work_id": "W-1", "contract_id": "D-1", "title": "X", "price": "100.00",
            "status": "planned", "completed_at": "", "cancelled_at": ""
        }])
        self.write_csv(directory, "payments.csv", [
            "payment_id", "contract_id", "work_id", "purpose", "amount", "status",
            "created_at", "paid_at", "refunded_at"
        ], [{
            "payment_id": "P-1", "contract_id": "D-1", "work_id": "", "purpose": "X",
            "amount": "50.00", "status": "paid", "created_at": "2026-01-01",
            "paid_at": "2026-01-02", "refunded_at": ""
        }])

    def test_unknown_work_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.valid_files(directory)
            path = directory / "payments.csv"
            text = path.read_text(encoding="utf-8").replace("P-1,D-1,,", "P-1,D-1,W-404,")
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(DataValidationError, "неизвестный work_id"):
                load_data(directory)

    def test_fraction_of_kopeck_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.valid_files(directory)
            path = directory / "contracts.csv"
            path.write_text(path.read_text(encoding="utf-8").replace("100.00", "100.001"), encoding="utf-8")
            with self.assertRaisesRegex(DataValidationError, "точностью до копейки"):
                load_data(directory)


if __name__ == "__main__":
    unittest.main()
