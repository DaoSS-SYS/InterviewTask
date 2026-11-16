from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


MONEY = Decimal("0.01")
CONTRACT_COLUMNS = ("contract_id", "contractor", "amount", "signed_at")
WORK_COLUMNS = (
    "work_id", "contract_id", "title", "price", "status",
    "completed_at", "cancelled_at",
)
PAYMENT_COLUMNS = (
    "payment_id", "contract_id", "work_id", "purpose", "amount", "status",
    "created_at", "paid_at", "refunded_at",
)


class DataValidationError(Exception):
    pass


@dataclass(frozen=True)
class Contract:
    contract_id: str
    contractor: str
    amount: Decimal
    signed_at: date


@dataclass(frozen=True)
class Work:
    work_id: str
    contract_id: str
    title: str
    price: Decimal
    snapshot_status: str
    completed_at: date | None
    cancelled_at: date | None

    def status_on(self, report_date: date) -> str:
        if self.cancelled_at is not None and self.cancelled_at <= report_date:
            return "cancelled"
        if self.completed_at is not None and self.completed_at <= report_date:
            return "done"
        return "planned"


@dataclass(frozen=True)
class Payment:
    payment_id: str
    contract_id: str
    work_id: str | None
    purpose: str
    amount: Decimal
    status: str
    created_at: date
    paid_at: date | None
    refunded_at: date | None

    def is_effective_on(self, report_date: date) -> bool:
        if self.paid_at is None or self.paid_at > report_date:
            return False
        return self.refunded_at is None or self.refunded_at > report_date


@dataclass
class WorkResult:
    work: Work
    status: str
    payable_price: Decimal
    direct_paid: Decimal = Decimal("0.00")
    allocated_paid: Decimal = Decimal("0.00")

    @property
    def paid(self) -> Decimal:
        return self.direct_paid + self.allocated_paid

    @property
    def remaining(self) -> Decimal:
        return max(self.payable_price - self.paid, Decimal("0.00"))

    @property
    def overpaid(self) -> Decimal:
        return max(self.paid - self.payable_price, Decimal("0.00"))


def parse_date(value: str, field: str, row_id: str, *, optional: bool = False) -> date | None:
    if not value:
        if optional:
            return None
        raise DataValidationError(f"{row_id}: поле {field} не заполнено")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DataValidationError(
            f"{row_id}: неверная дата в {field}: {value!r}, ожидается YYYY-MM-DD"
        ) from exc


def parse_money(value: str, field: str, row_id: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise DataValidationError(f"{row_id}: неверная сумма в {field}: {value!r}") from exc
    if not result.is_finite() or result < 0 or result.as_tuple().exponent < -2:
        raise DataValidationError(
            f"{row_id}: {field} должна быть неотрицательной суммой с точностью до копейки"
        )
    return result.quantize(MONEY)


def read_csv(path: Path, required_columns: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file():
        raise DataValidationError(f"Не найден файл {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            actual = tuple(reader.fieldnames or ())
            missing = [column for column in required_columns if column not in actual]
            extra = [column for column in actual if column not in required_columns]
            if missing or extra:
                details = []
                if missing:
                    details.append("нет колонок: " + ", ".join(missing))
                if extra:
                    details.append("неожиданные колонки: " + ", ".join(extra))
                raise DataValidationError(f"{path.name}: " + "; ".join(details))
            rows = list(reader)
    except UnicodeDecodeError as exc:
        raise DataValidationError(f"{path.name}: файл должен быть в UTF-8") from exc
    if not rows:
        raise DataValidationError(f"{path.name}: файл пуст")
    return rows


def require_text(row: dict[str, str], field: str, row_id: str) -> str:
    value = row[field].strip()
    if not value:
        raise DataValidationError(f"{row_id}: поле {field} не заполнено")
    return value


def ensure_unique(values: Iterable[str], entity: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise DataValidationError(f"Повторяется {entity}: {value}")
        seen.add(value)


def load_data(data_dir: Path) -> tuple[list[Contract], list[Work], list[Payment]]:
    contract_rows = read_csv(data_dir / "contracts.csv", CONTRACT_COLUMNS)
    work_rows = read_csv(data_dir / "works.csv", WORK_COLUMNS)
    payment_rows = read_csv(data_dir / "payments.csv", PAYMENT_COLUMNS)

    contracts = [
        Contract(
            require_text(row, "contract_id", f"contracts.csv строка {index}"),
            require_text(row, "contractor", f"contracts.csv строка {index}"),
            parse_money(row["amount"], "amount", f"contracts.csv строка {index}"),
            parse_date(row["signed_at"], "signed_at", f"contracts.csv строка {index}"),
        )
        for index, row in enumerate(contract_rows, 2)
    ]
    ensure_unique((item.contract_id for item in contracts), "contract_id")
    contract_ids = {item.contract_id for item in contracts}

    works: list[Work] = []
    for index, row in enumerate(work_rows, 2):
        row_id = f"works.csv строка {index}"
        work_id = require_text(row, "work_id", row_id)
        contract_id = require_text(row, "contract_id", row_id)
        status = require_text(row, "status", row_id)
        if contract_id not in contract_ids:
            raise DataValidationError(f"{row_id}: неизвестный contract_id {contract_id}")
        if status not in {"planned", "done", "cancelled"}:
            raise DataValidationError(f"{row_id}: неизвестный status {status}")
        completed_at = parse_date(row["completed_at"], "completed_at", row_id, optional=True)
        cancelled_at = parse_date(row["cancelled_at"], "cancelled_at", row_id, optional=True)
        if status == "done" and completed_at is None:
            raise DataValidationError(f"{row_id}: для done требуется completed_at")
        if status == "cancelled" and cancelled_at is None:
            raise DataValidationError(f"{row_id}: для cancelled требуется cancelled_at")
        if status != "done" and completed_at is not None:
            raise DataValidationError(f"{row_id}: completed_at допустима только для done")
        if status != "cancelled" and cancelled_at is not None:
            raise DataValidationError(f"{row_id}: cancelled_at допустима только для cancelled")
        works.append(Work(
            work_id, contract_id, require_text(row, "title", row_id),
            parse_money(row["price"], "price", row_id), status,
            completed_at, cancelled_at,
        ))
    ensure_unique((item.work_id for item in works), "work_id")
    works_by_id = {item.work_id: item for item in works}

    payments: list[Payment] = []
    for index, row in enumerate(payment_rows, 2):
        row_id = f"payments.csv строка {index}"
        payment_id = require_text(row, "payment_id", row_id)
        contract_id = require_text(row, "contract_id", row_id)
        work_id = row["work_id"].strip() or None
        status = require_text(row, "status", row_id)
        if contract_id not in contract_ids:
            raise DataValidationError(f"{row_id}: неизвестный contract_id {contract_id}")
        if work_id is not None:
            if work_id not in works_by_id:
                raise DataValidationError(f"{row_id}: неизвестный work_id {work_id}")
            if works_by_id[work_id].contract_id != contract_id:
                raise DataValidationError(
                    f"{row_id}: работа {work_id} относится к другому договору"
                )
        if status not in {"paid", "queued", "refunded"}:
            raise DataValidationError(f"{row_id}: неизвестный status {status}")
        paid_at = parse_date(row["paid_at"], "paid_at", row_id, optional=True)
        refunded_at = parse_date(row["refunded_at"], "refunded_at", row_id, optional=True)
        if status in {"paid", "refunded"} and paid_at is None:
            raise DataValidationError(f"{row_id}: для {status} требуется paid_at")
        if status == "queued" and paid_at is not None:
            raise DataValidationError(f"{row_id}: у queued не должно быть paid_at")
        if status == "refunded" and refunded_at is None:
            raise DataValidationError(f"{row_id}: для refunded требуется refunded_at")
        if status != "refunded" and refunded_at is not None:
            raise DataValidationError(f"{row_id}: refunded_at допустима только для refunded")
        if paid_at and refunded_at and refunded_at < paid_at:
            raise DataValidationError(f"{row_id}: возврат не может быть раньше оплаты")
        created_at = parse_date(row["created_at"], "created_at", row_id)
        if paid_at and paid_at < created_at:
            raise DataValidationError(f"{row_id}: оплата не может быть раньше создания")
        payments.append(Payment(
            payment_id, contract_id, work_id, require_text(row, "purpose", row_id),
            parse_money(row["amount"], "amount", row_id), status,
            created_at, paid_at, refunded_at,
        ))
    ensure_unique((item.payment_id for item in payments), "payment_id")
    return contracts, works, payments


def allocate_contract(
    contract: Contract,
    works: list[Work],
    payments: list[Payment],
    report_date: date,
) -> tuple[list[WorkResult], Decimal, Decimal]:
    results = [
        WorkResult(work, work.status_on(report_date),
                   Decimal("0.00") if work.status_on(report_date) == "cancelled" else work.price)
        for work in works
    ]
    by_id = {result.work.work_id: result for result in results}
    effective = [payment for payment in payments if payment.is_effective_on(report_date)]

    for payment in effective:
        if payment.work_id is not None:
            by_id[payment.work_id].direct_paid += payment.amount

    common_pool = sum(
        (payment.amount for payment in effective if payment.work_id is None),
        Decimal("0.00"),
    )
    allocation_order = sorted(
        (result for result in results if result.status != "cancelled"),
        key=lambda result: (
            0 if result.status == "done" else 1,
            result.work.completed_at or date.max,
            result.work.work_id,
        ),
    )
    for result in allocation_order:
        capacity = max(result.payable_price - result.direct_paid, Decimal("0.00"))
        allocation = min(common_pool, capacity)
        result.allocated_paid = allocation
        common_pool -= allocation
        if common_pool == 0:
            break

    total_paid = sum((payment.amount for payment in effective), Decimal("0.00"))
    return results, total_paid, common_pool


def money(value: Decimal) -> str:
    return format(value.quantize(MONEY), ".2f")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_report(
    contracts: list[Contract], works: list[Work], payments: list[Payment],
    report_date: date, output_dir: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    work_rows: list[dict[str, str]] = []
    contract_rows: list[dict[str, str]] = []
    for contract in contracts:
        contract_works = [work for work in works if work.contract_id == contract.contract_id]
        contract_payments = [p for p in payments if p.contract_id == contract.contract_id]
        results, total_paid, unallocated = allocate_contract(
            contract, contract_works, contract_payments, report_date
        )
        for result in results:
            work_rows.append({
                "report_date": report_date.isoformat(),
                "contract_id": contract.contract_id,
                "contractor": contract.contractor,
                "work_id": result.work.work_id,
                "title": result.work.title,
                "status_on_date": result.status,
                "original_price": money(result.work.price),
                "payable_price": money(result.payable_price),
                "direct_paid": money(result.direct_paid),
                "allocated_paid": money(result.allocated_paid),
                "paid_total": money(result.paid),
                "remaining": money(result.remaining),
                "overpaid": money(result.overpaid),
            })
        payable_total = sum((result.payable_price for result in results), Decimal("0.00"))
        allocated_total = sum((result.paid for result in results), Decimal("0.00"))
        remaining_works = sum((result.remaining for result in results), Decimal("0.00"))
        work_overpayment = sum((result.overpaid for result in results), Decimal("0.00"))
        contract_rows.append({
            "report_date": report_date.isoformat(),
            "contract_id": contract.contract_id,
            "contractor": contract.contractor,
            "contract_amount": money(contract.amount),
            "payable_works_total": money(payable_total),
            "amount_difference": money(contract.amount - payable_total),
            "paid_total": money(total_paid),
            "allocated_to_works": money(allocated_total),
            "unallocated_payment": money(unallocated),
            "remaining_by_works": money(remaining_works),
            "remaining_by_contract": money(max(contract.amount - total_paid, Decimal("0.00"))),
            "overpaid_on_works": money(work_overpayment),
            "overpaid_on_contract": money(max(total_paid - contract.amount, Decimal("0.00"))),
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "works.csv", list(work_rows[0]), work_rows)
    write_csv(output_dir / "contracts.csv", list(contract_rows[0]), contract_rows)
    return work_rows, contract_rows


def print_summary(contract_rows: list[dict[str, str]], output_dir: Path) -> None:
    print("Отчёт сформирован")
    for row in contract_rows:
        print(
            f"{row['contract_id']} | выплачено {row['paid_total']} | "
            f"осталось по работам {row['remaining_by_works']} | "
            f"нераспределено {row['unallocated_payment']}"
        )
    print(f"Файлы: {output_dir / 'works.csv'}, {output_dir / 'contracts.csv'}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Отчёт об оплате работ по договорам")
    parser.add_argument("--date", required=True, type=date.fromisoformat, dest="report_date")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("report"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        contracts, works, payments = load_data(args.data_dir)
        _, contract_rows = build_report(
            contracts, works, payments, args.report_date, args.output_dir
        )
    except (DataValidationError, OSError) as exc:
        print(f"Ошибка данных: {exc}", file=sys.stderr)
        return 2
    print_summary(contract_rows, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
