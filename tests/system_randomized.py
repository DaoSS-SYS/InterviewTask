"""Изолированный генеративный тест полного контура CSV -> отчёт.

Запуск из корня проекта:
    py -3 tests/system_randomized.py --cases 500 --seed 20261116
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from report import build_report, load_data  # noqa: E402


CONTRACT_FIELDS = ["contract_id", "contractor", "amount", "signed_at"]
WORK_FIELDS = [
    "work_id", "contract_id", "title", "price", "status",
    "completed_at", "cancelled_at",
]
PAYMENT_FIELDS = [
    "payment_id", "contract_id", "work_id", "purpose", "amount", "status",
    "created_at", "paid_at", "refunded_at",
]
BASE_DATE = date(2026, 1, 1)


def day(number: int) -> str:
    return (BASE_DATE + timedelta(days=number)).isoformat()


def amount(rng: random.Random, maximum_cents: int = 2_000_000) -> str:
    return f"{Decimal(rng.randint(0, maximum_cents)) / 100:.2f}"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def generate_case(rng: random.Random, data_dir: Path) -> tuple[str, int, int, int]:
    contract_rows: list[dict[str, str]] = []
    work_rows: list[dict[str, str]] = []
    payment_rows: list[dict[str, str]] = []
    work_number = 0
    payment_number = 0

    for contract_number in range(1, rng.randint(2, 7)):
        contract_id = f"D-{contract_number}"
        contract_rows.append({
            "contract_id": contract_id,
            "contractor": f"Случайный подрядчик {contract_number}",
            "amount": amount(rng, 10_000_000),
            "signed_at": day(rng.randint(0, 20)),
        })
        contract_work_ids: list[str] = []
        for _ in range(rng.randint(1, 8)):
            work_number += 1
            work_id = f"W-{work_number}"
            contract_work_ids.append(work_id)
            status = rng.choice(["planned", "done", "cancelled"])
            event_day = rng.randint(21, 330)
            work_rows.append({
                "work_id": work_id,
                "contract_id": contract_id,
                "title": f"Работа {work_number}",
                "price": amount(rng),
                "status": status,
                "completed_at": day(event_day) if status == "done" else "",
                "cancelled_at": day(event_day) if status == "cancelled" else "",
            })
        for _ in range(rng.randint(1, 12)):
            payment_number += 1
            status = rng.choice(["paid", "paid", "paid", "queued", "refunded"])
            created_day = rng.randint(0, 300)
            paid_day = created_day + rng.randint(0, 15)
            refunded_day = paid_day + rng.randint(0, 15)
            payment_rows.append({
                "payment_id": f"P-{payment_number}",
                "contract_id": contract_id,
                "work_id": rng.choice(contract_work_ids + ["", ""]),
                "purpose": f"Случайный платёж {payment_number}",
                "amount": amount(rng),
                "status": status,
                "created_at": day(created_day),
                "paid_at": "" if status == "queued" else day(paid_day),
                "refunded_at": day(refunded_day) if status == "refunded" else "",
            })

    write_csv(data_dir / "contracts.csv", CONTRACT_FIELDS, contract_rows)
    write_csv(data_dir / "works.csv", WORK_FIELDS, work_rows)
    write_csv(data_dir / "payments.csv", PAYMENT_FIELDS, payment_rows)
    report_date = day(rng.randint(0, 365))
    return report_date, len(contract_rows), len(work_rows), len(payment_rows)


def money(value: str) -> Decimal:
    result = Decimal(value)
    assert result >= 0, f"отрицательная сумма: {value}"
    assert result == result.quantize(Decimal("0.01")), f"не копейки: {value}"
    return result


def check_case(data_dir: Path, output_dir: Path, report_date_text: str) -> None:
    contracts, works, payments = load_data(data_dir)
    report_date = date.fromisoformat(report_date_text)
    work_rows, contract_rows = build_report(
        contracts, works, payments, report_date, output_dir
    )
    assert len(work_rows) == len(works)
    assert len(contract_rows) == len(contracts)
    assert (output_dir / "works.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert (output_dir / "contracts.csv").read_bytes().startswith(b"\xef\xbb\xbf")

    works_by_contract: dict[str, list[dict[str, str]]] = {}
    for row in work_rows:
        works_by_contract.setdefault(row["contract_id"], []).append(row)
        payable = money(row["payable_price"])
        direct = money(row["direct_paid"])
        allocated = money(row["allocated_paid"])
        paid = money(row["paid_total"])
        remaining = money(row["remaining"])
        overpaid = money(row["overpaid"])
        assert paid == direct + allocated
        assert remaining == max(payable - paid, Decimal("0.00"))
        assert overpaid == max(paid - payable, Decimal("0.00"))
        if row["status_on_date"] == "cancelled":
            assert payable == 0

    payment_by_contract: dict[str, Decimal] = {}
    for payment in payments:
        if payment.is_effective_on(report_date):
            payment_by_contract[payment.contract_id] = (
                payment_by_contract.get(payment.contract_id, Decimal("0.00")) + payment.amount
            )

    for row in contract_rows:
        contract_id = row["contract_id"]
        rows = works_by_contract[contract_id]
        paid_total = money(row["paid_total"])
        allocated_total = money(row["allocated_to_works"])
        unallocated = money(row["unallocated_payment"])
        payable_total = money(row["payable_works_total"])
        remaining_total = money(row["remaining_by_works"])
        assert paid_total == payment_by_contract.get(contract_id, Decimal("0.00"))
        assert allocated_total == sum((money(item["paid_total"]) for item in rows), Decimal("0.00"))
        assert paid_total == allocated_total + unallocated
        assert payable_total == sum((money(item["payable_price"]) for item in rows), Decimal("0.00"))
        assert remaining_total == sum((money(item["remaining"]) for item in rows), Decimal("0.00"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20261116)
    args = parser.parse_args()
    if args.cases <= 0:
        parser.error("--cases должен быть положительным")

    rng = random.Random(args.seed)
    total_contracts = total_works = total_payments = 0
    with tempfile.TemporaryDirectory(prefix="candidate-b-random-") as temporary:
        root = Path(temporary)
        for case_number in range(1, args.cases + 1):
            case_dir = root / f"case-{case_number}"
            data_dir = case_dir / "data"
            output_dir = case_dir / "report"
            data_dir.mkdir(parents=True)
            report_date, contracts, works, payments = generate_case(rng, data_dir)
            try:
                check_case(data_dir, output_dir, report_date)
            except Exception:
                print(f"FAIL case={case_number} seed={args.seed} path={case_dir}", file=sys.stderr)
                raise
            total_contracts += contracts
            total_works += works
            total_payments += payments

    print("RANDOMIZED SYSTEM TEST: PASS")
    print(f"seed={args.seed}")
    print(f"cases={args.cases}")
    print(f"contracts={total_contracts}")
    print(f"works={total_works}")
    print(f"payments={total_payments}")
    print("isolation=TemporaryDirectory (removed after successful run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
