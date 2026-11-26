"""Synthetic corporate-action ledger tests; no official data claims."""
import unittest
from copy import deepcopy
from decimal import Decimal

from src.v3_corporate_action_ledger import opening_action_step


class CorporateActionLedgerTests(unittest.TestCase):
    def event(self, **overrides):
        row = dict(event_id="e1", stock_id="2301", market="TWSE",
                   currently_listed=True, terms_verified=True,
                   source_sha256="a"*64, effective_session="2024-06-03",
                   public_date="2024-05-30", kind="CASH_DIVIDEND",
                   cash_per_share="2.35", credit_session="2024-07-01")
        row.update(overrides)
        return row

    def step(self, **overrides):
        args = dict(session_date="2024-06-03", previous_session_date="2024-05-31",
                    holdings={"2301":1000}, pending_dividends=[],
                    applied_event_ids=[], actions=[self.event()])
        args.update(overrides)
        return opening_action_step(**args)

    def test_ex_date_receivable_not_cash(self):
        holdings = {"2301":1000}
        r = self.step(holdings=holdings)
        self.assertEqual(Decimal(r["gross_receivable_created"]), Decimal("2350"))
        self.assertEqual(Decimal(r["gross_cash_credited"]),0)
        self.assertEqual(r["holdings"],holdings)
        self.assertEqual(r["applied_event_ids"],["e1"])
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertFalse(r["source_provenance_verified"])

    def test_credit_after_selling_eligible_shares(self):
        r=self.step()
        p=self.step(session_date="2024-07-01",previous_session_date="2024-06-28",
                    holdings={}, pending_dividends=r["pending_dividends"],
                    applied_event_ids=r["applied_event_ids"],actions=[])
        self.assertEqual(Decimal(p["gross_cash_credited"]),Decimal("2350"))
        self.assertEqual(Decimal(p["gross_receivable_balance"]),0)
        self.assertEqual(p["holdings"],{})
        self.assertEqual(len(r["pending_dividends"]),1)

    def test_no_prior_shares_no_dividend(self):
        r=self.step(holdings={})
        self.assertEqual(r["pending_dividends"],[])
        self.assertEqual(Decimal(r["gross_receivable_created"]),0)

    def conversion(self, **overrides):
        e=self.event(kind="IMMEDIATE_SHARE_CONVERSION",old_shares=2,new_shares=3,
                     delivery_session="2024-06-03")
        del e["cash_per_share"], e["credit_session"]
        e.update(overrides)
        return e

    def test_exact_share_conversion_retains_odd_lots(self):
        r=self.step(holdings={"2301":1002},actions=[self.conversion()])
        self.assertEqual(r["holdings"]["2301"],1503)
        with self.assertRaises(ValueError):
            self.step(holdings={"2301":1001},actions=[self.conversion()])
        with self.assertRaises(ValueError):
            self.step(actions=[self.conversion(delivery_session="2024-07-01")])

    def test_duplicate_and_unsupported_events(self):
        for actions in ([self.event(),self.event(event_id="e2")],
                        [self.event(kind="RIGHTS_SUBSCRIPTION")],
                        [self.event(kind="STOCK_DIVIDEND")],
                        [self.event(cash_per_share=2.35)],
                        [self.event(public_date="2024-06-03")],
                        [self.event(terms_verified=False)],
                        [self.event(stock_id="1589")],
                        [self.event(source_sha256="invalid")]):
            with self.assertRaises(ValueError):
                self.step(actions=deepcopy(actions))
        with self.assertRaises(ValueError):
            self.step(applied_event_ids=["e1"])

    def test_inconsistent_receivable_rejected(self):
        r=self.step()
        with self.assertRaises(ValueError):
            self.step(actions=[],pending_dividends=r["pending_dividends"])
        with self.assertRaises(ValueError):
            self.step(actions=[],applied_event_ids=["e1"],
                      pending_dividends=r["pending_dividends"]*2)


if __name__=="__main__":
    unittest.main()
