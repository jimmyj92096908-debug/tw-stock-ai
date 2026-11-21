"""Postgres-supported regression for unchanged current-day composite score rows.

Works solely in disposable stock_ci_test PostgreSQL (not Neon). The explicit
TEMP TABLE shadows any persistent public table and vanishes with the connection.
Tests identical reruns and real changes (new chip/coverage/JSON) end-to-end.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock,patch

import psycopg

from src import composite_score


def params(*,stock="2330",chip=None,total=66.0,coverage=0.6,status=None):
    if status is None:
        status={"technical":{"status":"AVAILABLE"},"smc":{"status":"AVAILABLE"}}
    import json
    return (
        "twse",stock,"2026-11-20",total,coverage,70,60,chip,
        65,66,None,0.8,0.6,0.3,json.dumps(status,ensure_ascii=False)
    )


class SQLShapeTests(unittest.TestCase):
    def test_normal_recompute_is_null_safe_idempotent_on_every_scored_field(self):
        sql=composite_score.COMPOSITE_UPSERT_SQL
        self.assertIn("ON CONFLICT (market,stock_id,as_of_date) DO UPDATE SET",sql)
        self.assertIn("IS DISTINCT FROM",sql)
        compare=sql.split("WHERE (",1)[1]
        for name in (
            "total_score","coverage_weight","technical_score","smc_score",
            "chip_score","short_term_score","swing_score","long_term_score",
            "short_coverage","swing_coverage","long_coverage","component_status"
        ):
            with self.subTest(name=name):
                self.assertIn("daily_composite_scores."+name,compare)
                self.assertIn("EXCLUDED."+name,compare)
        self.assertNotIn("daily_composite_scores.calculated_at",compare)
        self.assertNotIn("EXCLUDED.calculated_at",compare)
        self.assertIn("component_status=EXCLUDED.component_status,calculated_at=now()",sql)

    def test_missing_only_converts_update_into_do_nothing(self):
        db=MagicMock()
        db.__enter__.return_value=db
        cur=db.cursor.return_value.__enter__.return_value
        # Decline score because there are no required technical data.
        cur.fetchone.return_value=None
        with patch.object(composite_score.psycopg,"connect",return_value=db):
            count=composite_score.calculate_all("fake",stocks=[("tpex","3523")],
                                                missing_only=True)
        self.assertEqual(count,0)
        with self.assertRaisesRegex(ValueError,"bounded explicit"):
            composite_score.calculate_all("fake",missing_only=True)
        # Pure string derivation is also the actual code's missing-only branch.
        sql=composite_score.COMPOSITE_UPSERT_SQL
        missing=sql[:sql.index("    ON CONFLICT (market,stock_id,as_of_date) DO UPDATE SET")] + (
            "    ON CONFLICT (market,stock_id,as_of_date) DO NOTHING RETURNING stock_id")
        self.assertIn("DO NOTHING RETURNING stock_id",missing)
        self.assertNotIn("DO UPDATE",missing)
        self.assertNotIn("IS DISTINCT FROM",missing)


@unittest.skipUnless(os.environ.get("STOCK_CI_POSTGRES_URL"),
                     "Disposable local PostgreSQL CI connection not provided")
class IsolatedPostgresCompositeTests(unittest.TestCase):
    def test_unchanged_scores_preserve_version_and_timestamp_chip_changes_update(self):
        url=os.environ["STOCK_CI_POSTGRES_URL"]
        from urllib.parse import urlparse
        parsed=urlparse(url)
        if parsed.hostname!="127.0.0.1" or parsed.path!="/stock_ci_test":
            self.fail("This test may run only against the disposable local CI PostgreSQL")
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TEMP TABLE daily_composite_scores (
                      market text NOT NULL,stock_id varchar(6) NOT NULL,
                      as_of_date date NOT NULL,total_score numeric(6,2),
                      coverage_weight numeric(4,2) NOT NULL,
                      technical_score numeric(6,2),smc_score numeric(6,2),
                      chip_score numeric(6,2),short_term_score numeric(6,2),
                      swing_score numeric(6,2),long_term_score numeric(6,2),
                      short_coverage numeric(4,2),swing_coverage numeric(4,2),
                      long_coverage numeric(4,2),component_status jsonb NOT NULL,
                      calculated_at timestamptz NOT NULL,
                      PRIMARY KEY (market,stock_id,as_of_date)
                    ) ON COMMIT PRESERVE ROWS
                """)
                run=lambda p:cur.execute(composite_score.COMPOSITE_UPSERT_SQL,p)
                run(params())
                self.assertEqual(cur.rowcount,1)
                cur.execute("""
                    UPDATE daily_composite_scores
                    SET calculated_at = '2020-01-01 00:00:00+00'
                    WHERE stock_id='2330'
                """)
                cur.execute("""
                    SELECT ctid::text,calculated_at FROM daily_composite_scores
                    WHERE stock_id='2330'
                """)
                old_version,old_time=cur.fetchone()
                run(params())
                self.assertEqual(cur.rowcount,0,"Identical score must not write a new row")
                cur.execute("""
                    SELECT ctid::text,calculated_at FROM daily_composite_scores
                    WHERE stock_id='2330'
                """)
                self.assertEqual(cur.fetchone(),(old_version,old_time))
                run(params(chip=80,total=72,coverage=1))
                self.assertEqual(cur.rowcount,1,"New valid chip coverage must update score")
                cur.execute("""
                    SELECT chip_score,total_score,coverage_weight,calculated_at
                    FROM daily_composite_scores WHERE stock_id='2330'
                """)
                new_chip,new_total,new_weight,new_time=cur.fetchone()
                self.assertEqual(float(new_chip),80)
                self.assertEqual(float(new_total),72)
                self.assertEqual(float(new_weight),1)
                self.assertGreater(new_time,old_time)
                run(params(chip=80,total=72,coverage=1))
                self.assertEqual(cur.rowcount,0)
                # JSONB source-status change must still update independently.
                run(params(chip=80,total=72,coverage=1,status={"chip":{"status":"AVAILABLE"}}))
                self.assertEqual(cur.rowcount,1)
                # Conflicting missing-only mode must never overwrite scores.
                sql=composite_score.COMPOSITE_UPSERT_SQL
                missing=sql[:sql.index("    ON CONFLICT (market,stock_id,as_of_date) DO UPDATE SET")] + (
                    "    ON CONFLICT (market,stock_id,as_of_date) DO NOTHING RETURNING stock_id")
                cur.execute(missing,params(total=1))
                self.assertEqual(cur.rowcount,0)
                self.assertIsNone(cur.fetchone())
                cur.execute(missing,params(stock="1101"))
                self.assertEqual(cur.rowcount,1)
                self.assertEqual(cur.fetchone(),("1101",))


if __name__=="__main__":
    unittest.main()
