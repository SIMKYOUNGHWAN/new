import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, Mock

import pandas as pd

from gel_app import live_sources, live_news, live_pipeline, live_tracking


class GelLiveTests(unittest.TestCase):
    def test_nbg_request_units(self):
        response = Mock()
        response.json.return_value = [{"date":"2026-09-09T00:00:00.000Z","currencies":[
            {"code":"USD","quantity":1,"rate":2.6114},
            {"code":"EUR","quantity":1,"rate":3.0318},
            {"code":"JPY","quantity":100,"rate":1.6937}]}]
        with patch.object(live_sources.requests,"get",return_value=response) as get:
            day, values = live_sources.fetch_day("2026-09-09")
        self.assertEqual(get.call_args.kwargs["params"], {"date":"2026-09-09"})
        self.assertAlmostEqual(values["JPY"],.016937)
        self.assertEqual(str(day.date()),"2026-09-09")

    def test_bad_nbg_response_is_rejected(self):
        response = Mock()
        response.json.return_value = []
        with patch.object(live_sources.requests,"get",return_value=response), patch.object(live_sources.time,"sleep"):
            with self.assertRaises(ValueError):
                live_sources.fetch_day("2026-09-09")

    def test_news_filters(self):
        now = datetime(2026,9,9,12,tzinfo=timezone.utc)
        current = datetime(2026,9,9,tzinfo=timezone.utc)
        self.assertTrue(live_news.eligible("NBG refinancing rate","https://civil.ge/archives/1",current,"civil.ge",now))
        self.assertFalse(live_news.eligible("Transnational Bank Fraud","https://civil.ge/archives/1",current,"civil.ge",now))
        self.assertFalse(live_news.eligible("Lari exchange rate","javascript:alert(1)",current,"civil.ge",now))
        self.assertFalse(live_news.eligible("Lari exchange rate","https://civil.ge/archives/1",datetime(2020,1,1,tzinfo=timezone.utc),"civil.ge",now))
        self.assertFalse(live_news.eligible("Lari exchange rate","https://evil.test/1",current,"civil.ge",now))

    def test_live_loader_rejects_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"snapshot.json"
            path.write_text('{"meta":{"mode":"sample"}}',encoding="utf-8")
            with patch.object(live_pipeline,"FILE",path):
                self.assertIsNone(live_pipeline.load_snapshot())

    def test_failed_primary_source_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"snapshot.json"
            path.write_text('{"meta":{"mode":"live"}}',encoding="utf-8")
            old = path.read_bytes()
            with patch.object(live_pipeline,"FILE",path), patch.object(live_sources,"fetch_rates",side_effect=RuntimeError("offline")):
                with self.assertRaises(RuntimeError):
                    live_pipeline.run_batch()
            self.assertEqual(path.read_bytes(),old)

    def test_tracking_keeps_first_same_day_forecast(self):
        snap = {"direction":{"up_probability":60},"forecast20":{"lower":2.4,"median":2.6,"upper":2.8}}
        px = pd.Series([2.5,2.6],index=pd.to_datetime(["2026-09-08","2026-09-09"]))
        with tempfile.TemporaryDirectory() as folder, patch.object(live_tracking,"FILE",Path(folder)/"history.json"):
            first = live_tracking.update(snap,px)
            snap["forecast20"]["median"] = 9.9
            second = live_tracking.update(snap,px)
            self.assertEqual(second["total"],1)
            self.assertEqual(second["recent"][0]["median"],2.6)
            self.assertEqual(first["scored"],0)

    def test_tracking_waits_for_twentieth_observation(self):
        record = {"date":"2020-01-01","as_of":"2020-01-01","spot":2.5,"lower":2.4,"median":2.6,"upper":2.8,"probability":60,"actual":None,"correct":None,"within_band":None}
        snap = {"direction":{},"forecast20":{"lower":2.4,"median":2.6,"upper":2.8}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"history.json"
            path.write_text(json.dumps([record]),encoding="utf-8")
            with patch.object(live_tracking,"FILE",path):
                px = pd.Series(2.7,index=pd.bdate_range("2020-01-02",periods=19))
                self.assertEqual(live_tracking.update(snap,px)["scored"],0)
                px = pd.Series(2.7,index=pd.bdate_range("2020-01-02",periods=20))
                result = live_tracking.update(snap,px)
                self.assertEqual(result["scored"],1)
                self.assertEqual(result["direction_hit_rate"],100)


if __name__ == "__main__":
    unittest.main()

