import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest
from dashboard_pages.overview_data import align,strength,convert,forecast,load,window


class OverviewTests(unittest.TestCase):
    def test_common_dates_no_fill(self):
        a = pd.Series([100,101],index=pd.to_datetime(["2026-01-01","2026-01-03"]))
        b = pd.Series([2,3],index=pd.to_datetime(["2026-01-02","2026-01-03"]))
        result = align({"KRW":a,"GEL":b},["KRW","GEL"])
        self.assertEqual(len(result),1)
        self.assertEqual(result.index[0],pd.Timestamp("2026-01-03"))

    def test_strength_direction_and_conversion(self):
        p = pd.DataFrame({"KRW":[1000.,1200.],"GEL":[2.,2.]})
        usd = strength(p,"USD")
        won = strength(p,"KRW")
        self.assertLess(usd["KRW"].iloc[-1],usd["KRW"].iloc[0])
        self.assertEqual(won["KRW"].tolist(),[1.,1.])
        self.assertGreater(won["GEL"].iloc[-1],won["GEL"].iloc[0])
        self.assertEqual(convert(p,1200)["GEL"].iloc[-1],2.)

    def test_forecast_excludes_partial_month(self):
        dates = pd.date_range("2023-01-31",periods=44,freq="ME")
        frame = pd.DataFrame({"KRW":1000+np.arange(44)*2,"GEL":2+np.arange(44)*.01},index=dates)
        before = forecast(frame,"2026-08-15","USD")
        frame.iloc[-1] *= 10
        self.assertEqual(before,forecast(frame,"2026-08-15","USD"))
        won = forecast(frame,"2026-08-15","KRW")
        self.assertTrue(np.allclose(won["KRW"]["median"],100))
        self.assertEqual(len(won["GEL"]["median"]),12)

    def test_missing_files_and_short_window(self):
        with tempfile.TemporaryDirectory() as folder:
            daily,monthly,sources,errors = load(Path(folder))
            self.assertFalse(daily)
            self.assertEqual(len(errors),3)
        data = pd.DataFrame({"KRW":[1,2]},index=pd.to_datetime(["2026-09-01","2026-09-02"]))
        self.assertIsNone(window(data,30))

    def test_real_ui_controls(self):
        app = AppTest.from_file("dashboard_pages/overview.py").run(timeout=60)
        self.assertFalse(app.exception,str(app.exception))
        self.assertIn("TRY", app.multiselect[0].value)
        self.assertEqual(len(app.get("plotly_chart")),18)
        app.radio[0].set_value("KRW").run()
        self.assertFalse(app.exception,str(app.exception))
        app.number_input[0].set_value(2000000.).run()
        self.assertFalse(app.exception,str(app.exception))
        app.selectbox[0].set_value("1주").run()
        self.assertFalse(app.exception,str(app.exception))
        app.multiselect[0].set_value(["KRW"]).run()
        self.assertFalse(app.exception,str(app.exception))
        app.multiselect[0].set_value([]).run()
        self.assertFalse(app.exception,str(app.exception))


if __name__ == "__main__":
    unittest.main()

