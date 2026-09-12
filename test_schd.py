import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest
from app import schd


class SCHDTests(unittest.TestCase):
    def test_completed_year_growth_and_no_double_split(self):
        dates = pd.date_range('2019-03-31','2026-06-30',freq='QE')
        dividends = pd.Series([.25*(1.1**(d.year-2019)) for d in dates],index=dates)
        stats = schd.dividend_stats(dividends,'2026-09-12',25,'2019-01-01')
        self.assertEqual(stats['growth_end'],2025)
        self.assertAlmostEqual(stats['growth']['5'],10)
        self.assertAlmostEqual(stats['annual'][0]['amount'],1)
        self.assertFalse(stats['annual'][-1]['complete'])

    def test_price_and_fx_return_and_drawdown(self):
        idx = pd.date_range('2024-01-01','2026-01-01')
        frame = pd.DataFrame({'close':100.,'adjusted':100.,'fx':1000.},index=idx)
        frame.iloc[-2,frame.columns.get_loc('adjusted')] = 80
        frame.iloc[-1] = [100,110,900]
        result = schd.performance(frame,1)
        self.assertAlmostEqual(result['return']['USD'],10)
        self.assertAlmostEqual(result['return']['KRW'],-1)
        self.assertAlmostEqual(result['mdd']['USD'],-20)
        self.assertIsNone(schd.performance(frame,5))

    def test_income_and_cash_in_scenario(self):
        result = schd.income(105000,10,1000,1,15)
        self.assertEqual(result['shares'],10)
        self.assertAlmostEqual(result['cash_usd'],5)
        self.assertAlmostEqual(result['net'],8.5)
        self.assertAlmostEqual(schd.scenario(105000,10,1000,1,15,0,-10),102150)
        self.assertEqual(schd.income(0,10,1000,1,15)['net'],0)
        with self.assertRaises(ValueError):
            schd.income(100,0,1000,1,15)

    def test_fetch_failure_preserves_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'snapshot.json'
            path.write_text('previous')
            with patch.object(schd,'FILE',path), patch('requests.Session.get',side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError):
                    schd.run_batch()
            self.assertEqual(path.read_text(),'previous')

    def test_live_ui_and_zero_budget(self):
        app = AppTest.from_file('dashboard_pages/schd.py').run(timeout=60)
        self.assertFalse(app.exception,str(app.exception))
        self.assertEqual(len(app.tabs),3)
        self.assertEqual(len(app.get('plotly_chart')),4)
        app.selectbox(key='schd-years').set_value(1).run()
        self.assertFalse(app.exception,str(app.exception))
        app.number_input(key='schd-budget').set_value(0).run()
        self.assertFalse(app.exception,str(app.exception))
        self.assertEqual(len(app.get('plotly_chart')),3)


if __name__ == '__main__':
    unittest.main()
