import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CliEndToEndTests(unittest.TestCase):
    def test_real_data_full_cli_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report"
            process = subprocess.run(
                [
                    sys.executable, str(ROOT / "report.py"), "--date", "2026-11-10",
                    "--data-dir", str(ROOT / "data"), "--output-dir", str(output),
                ],
                capture_output=True, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn(b"D-1", process.stdout)
            with (output / "contracts.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = {row["contract_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual(rows["D-1"]["paid_total"], "315000.00")
            self.assertEqual(rows["D-1"]["remaining_by_works"], "185000.00")
            self.assertEqual(rows["D-2"]["paid_total"], "75000.00")
            self.assertEqual(rows["D-2"]["remaining_by_works"], "15000.00")

    def test_invalid_input_returns_code_2_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            output = root / "report"
            data.mkdir()
            (data / "contracts.csv").write_text("wrong,column\n1,2\n", encoding="utf-8")
            (data / "works.csv").write_text("x\n1\n", encoding="utf-8")
            (data / "payments.csv").write_text("x\n1\n", encoding="utf-8")
            process = subprocess.run(
                [
                    sys.executable, str(ROOT / "report.py"), "--date", "2026-11-10",
                    "--data-dir", str(data), "--output-dir", str(output),
                ],
                capture_output=True, check=False,
            )
            self.assertEqual(process.returncode, 2)
            self.assertTrue(process.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
