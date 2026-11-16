import csv
import tempfile
import unittest
from pathlib import Path

from report import DataValidationError, load_data


FIELDS = {
    "contracts.csv": ["contract_id", "contractor", "amount", "signed_at"],
    "works.csv": ["work_id", "contract_id", "title", "price", "status", "completed_at", "cancelled_at"],
    "payments.csv": [
        "payment_id", "contract_id", "work_id", "purpose", "amount", "status",
        "created_at", "paid_at", "refunded_at",
    ],
}


def valid_rows():
    return {
        "contracts.csv": [
            {"contract_id": "D-1", "contractor": "A", "amount": "100.00", "signed_at": "2026-01-01"},
            {"contract_id": "D-2", "contractor": "B", "amount": "200.00", "signed_at": "2026-01-01"},
        ],
        "works.csv": [
            {"work_id": "W-1", "contract_id": "D-1", "title": "X", "price": "100.00", "status": "done", "completed_at": "2026-01-10", "cancelled_at": ""},
            {"work_id": "W-2", "contract_id": "D-2", "title": "Y", "price": "200.00", "status": "planned", "completed_at": "", "cancelled_at": ""},
        ],
        "payments.csv": [{
            "payment_id": "P-1", "contract_id": "D-1", "work_id": "W-1", "purpose": "X",
            "amount": "50.00", "status": "paid", "created_at": "2026-01-01",
            "paid_at": "2026-01-02", "refunded_at": "",
        }],
    }


class ValidationMatrixTests(unittest.TestCase):
    def assert_invalid(self, mutation, message):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            rows = valid_rows()
            mutation(rows)
            for filename, content in rows.items():
                with (directory / filename).open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=FIELDS[filename])
                    writer.writeheader()
                    writer.writerows(content)
            with self.assertRaisesRegex(DataValidationError, message):
                load_data(directory)

    def test_duplicate_contract(self):
        self.assert_invalid(lambda r: r["contracts.csv"].append(r["contracts.csv"][0].copy()), "Повторяется contract_id")

    def test_unknown_contract_on_work(self):
        self.assert_invalid(lambda r: r["works.csv"][0].update(contract_id="D-404"), "неизвестный contract_id")

    def test_cross_contract_work_reference(self):
        self.assert_invalid(lambda r: r["payments.csv"][0].update(contract_id="D-2"), "другому договору")

    def test_unknown_work_status(self):
        self.assert_invalid(lambda r: r["works.csv"][0].update(status="maybe"), "неизвестный status")

    def test_done_requires_completion_date(self):
        self.assert_invalid(lambda r: r["works.csv"][0].update(completed_at=""), "требуется completed_at")

    def test_queued_cannot_have_paid_date(self):
        self.assert_invalid(lambda r: r["payments.csv"][0].update(status="queued"), "не должно быть paid_at")

    def test_refund_cannot_precede_payment(self):
        self.assert_invalid(
            lambda r: r["payments.csv"][0].update(status="refunded", refunded_at="2025-12-31"),
            "возврат не может быть раньше оплаты",
        )

    def test_payment_cannot_precede_creation(self):
        self.assert_invalid(lambda r: r["payments.csv"][0].update(created_at="2026-01-03"), "раньше создания")

    def test_negative_money(self):
        self.assert_invalid(lambda r: r["payments.csv"][0].update(amount="-0.01"), "неотрицательной")

    def test_invalid_date(self):
        self.assert_invalid(lambda r: r["contracts.csv"][0].update(signed_at="01.01.2026"), "неверная дата")


if __name__ == "__main__":
    unittest.main()
