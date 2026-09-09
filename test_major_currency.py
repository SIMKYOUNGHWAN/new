import json
import unittest
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest
from gel_app import analytics, sources


class MajorCurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = sources.sample_bundle()
        for key in ("usdgel", "cnygel", "eurgel", "gbpgel", "jpygel"):
            cls.raw[key].index = pd.date_range(end="2026-09-09", periods=len(cls.raw[key]), freq="B")
        cls.crosses = analytics.currency_crosses(cls.raw)
        cls.snapshot = {"crosses": cls.crosses, "meta": {"mode": "live"}, "summary": {}}
        cls.temp = tempfile.TemporaryDirectory()
        cls.fixture = Path(cls.temp.name) / "fixture.json"
        cls.fixture.write_text(json.dumps(cls.snapshot, allow_nan=False), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_independent_currency_models(self):
        for code in ("CNY", "EUR", "GBP", "JPY"):
            series = self.crosses[code]
            expected = self.raw["usdgel"].iloc[-1] / self.raw[code.lower() + "gel"].iloc[-1]
            self.assertAlmostEqual(series["values"][-1], expected, places=series["digits"])
            analysis = series["analysis"]
            self.assertTrue(analysis["available"])
            self.assertGreater(analysis["observations"], 250)
            self.assertEqual(len(analysis["monte_carlo"]["p50"]), 12)
            self.assertLess(analysis["model_as_of"][:7], series["labels"][-1][:7])
            self.assertEqual(analysis["arima"]["labels"][0], series["labels"][-1][:7])
        self.assertNotEqual(self.crosses["CNY"]["analysis"]["arima"]["mean"],
                            self.crosses["JPY"]["analysis"]["arima"]["mean"])

    def test_short_and_invalid_history(self):
        raw = {k: v.tail(10) for k, v in self.raw.items()}
        raw["cnygel"].iloc[-1] = 0
        raw["jpygel"].iloc[-1] = np.inf
        result = analytics.currency_crosses(raw)
        self.assertFalse(result["CNY"]["analysis"]["available"])
        self.assertLess(result["CNY"]["labels"][-1], raw["usdgel"].index[-1].strftime("%Y-%m-%d"))
        json.dumps(result, allow_nan=False)
        del raw["cnygel"]
        self.assertNotIn("CNY", analytics.currency_crosses(raw))

    def test_four_pages_and_calculator(self):
        for code, title in (("CNY", "중국 위안화"), ("EUR", "유럽 유로화"),
                            ("GBP", "영국 파운드화"), ("JPY", "일본 엔화")):
            app = AppTest.from_string(f'''
import json
from unittest.mock import patch
from pathlib import Path
from dashboard_pages.major_currency import render
with patch("gel_app.major_pipeline.load_snapshot", return_value=json.loads(Path({str(self.fixture)!r}).read_text(encoding="utf-8"))):
    render("{code}", "{title}", "USD/{code} 환율")
''').run(timeout=60)
            self.assertEqual(len(app.exception), 0, str(app.exception))
            self.assertEqual(len(app.tabs), 2)
            self.assertTrue(any("ECB" in item.value for item in app.info))
            self.assertGreaterEqual(len(app.get("plotly_chart")), 7)
            app.number_input[0].set_value(2000.0).run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            expected = 2000 * self.crosses[code]["values"][-1]
            self.assertIn(f"{expected:,.{self.crosses[code]['digits']}f}", app.metric[3].value)


if __name__ == "__main__":
    unittest.main()

