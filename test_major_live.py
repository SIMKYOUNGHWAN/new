import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from gel_app import major_pipeline as pipeline


class LiveDataTests(unittest.TestCase):
    def csv(self):
        idx = pd.bdate_range(end="2026-09-08", periods=700)
        return pd.DataFrame({"USD": 2.0, "CNY": 14.0, "GBP": 1.0, "JPY": 300.0},
                            index=idx).to_csv(index_label="Date").encode()

    def test_units_and_history(self):
        frame = pipeline.parse_history(self.csv(), now="2026-09-09")
        self.assertEqual(frame.iloc[-1].to_dict(), {"CNY": 7.0, "GBP": 0.5, "JPY": 150.0, "EUR": 0.5})
        self.assertEqual(len(frame), 700)

    def test_bad_or_stale_source_rejected(self):
        with self.assertRaises(ValueError):
            pipeline.parse_history(self.csv(), now="2026-10-01")
        with self.assertRaises(ValueError):
            pipeline.parse_history(self.csv().replace(b",2.0,", b",0.0,"), now="2026-09-09")

    def test_fetch_failure_preserves_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot.json"
            path.write_text('{"meta":{"mode":"live"}}', encoding="utf-8")
            before = path.read_bytes()
            with patch.object(pipeline, "FILE", path), patch.object(pipeline, "fetch_history", side_effect=RuntimeError("offline")):
                with self.assertRaises(RuntimeError):
                    pipeline.run_batch()
            self.assertEqual(path.read_bytes(), before)

    def test_sample_is_never_loaded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot.json"
            path.write_text('{"meta":{"mode":"sample"}}', encoding="utf-8")
            with patch.object(pipeline, "FILE", path):
                self.assertIsNone(pipeline.load_snapshot())


if __name__ == "__main__":
    unittest.main()

