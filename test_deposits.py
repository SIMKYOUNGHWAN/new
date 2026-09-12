import unittest
from datetime import date

from streamlit.testing.v1 import AppTest
from dashboard_pages.deposits import load_products, status, won_return


class DepositTests(unittest.TestCase):
    def test_rates_have_sources_and_cover_currencies(self):
        data = load_products()
        self.assertEqual({p['code'] for p in data['products']}, {'KRW','GEL','CNY','EUR','GBP','JPY','TRY'})
        for p in data['products']:
            self.assertTrue(p['url'].startswith('https://'))
            self.assertEqual(p['months'], 12)
        turkey = next(p for p in data['products'] if p['code'] == 'TRY')
        self.assertIsNone(turkey['rate'])
        self.assertEqual(status(turkey, data['checked_on']), '금리 확인 필요')
        self.assertEqual(status(data['products'][0], '2026-09-12', date(2026,9,20)), '자료 재확인 필요')

    def test_fx_loss_can_exceed_interest(self):
        total, pct = won_return(1000000, 10, -10)
        self.assertAlmostEqual(total, 990000)
        self.assertAlmostEqual(pct, -1)
        self.assertAlmostEqual(won_return(1000000, 10, 0)[0], 1100000)
        with self.assertRaises(ValueError):
            won_return(100, 10, -100)

    def test_filter_and_calculator(self):
        app = AppTest.from_string('from dashboard_pages.deposits import render\nrender(["TRY", "GEL"])').run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(set(app.dataframe[0].value['통화']), {'TRY', 'GEL'})
        app.number_input(key='deposit-yield').set_value(10).run()
        app.number_input(key='deposit-fx').set_value(-10).run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(app.metric[0].value, '990,000원')


if __name__ == '__main__':
    unittest.main()
