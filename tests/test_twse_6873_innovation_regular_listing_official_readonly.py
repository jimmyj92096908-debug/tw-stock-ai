"""Synthetic offline tests for authentic 6873 innovation -> regular board history."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

from scripts.twse_2022_official_current_listing_date_triage import (
    URL as BASIC_URL, classify_official_current_listing,
)
from scripts.twse_2022_aes_neon_eligible_density_readonly import (
    SCOPE as PRIOR_SCOPE,
)
from scripts.twse_6873_innovation_regular_listing_official_readonly import (
    URL, SCOPE, STOCK, EXPECTED_INITIAL, EXPECTED_REGULAR,
    _TableRows, fetch_twse_historic_listings, reconcile,
)


def owner_reports():
    roster={str(x) for x in range(6000,7092)}
    assert len(roster)==1092 and STOCK in roster
    no2022=set(sorted(roster)[-128:])|{STOCK}
    assert len(no2022)==129
    rows=[]
    first={}
    for sid in sorted(roster):
        listing="20240304"
        first[sid]=date(2024,3,5)
        if sid==STOCK:
            listing="20240926"
            first[sid]=EXPECTED_INITIAL
        rows.append({"公司代號":sid,"上市日期":listing,
                     "出表日期":"1151122"})
    proof={"rows":rows,"response_sha256":"f"*64,"endpoint":BASIC_URL}
    args=dict(eligible_ids=roster,no_2022_ids=no2022,
              first_2023plus=first,current_day=date(2026,11,23),
              prior_window_end=date(2026,11,23))
    public=classify_official_current_listing(proof,**args)
    private=classify_official_current_listing(
        proof,**args,private_listing_conflict_details=True)
    self_entry=private["owner_private_official_listing_first_neon_date_conflicts"][0]
    assert self_entry["stock_id"]=="6873"
    assert self_entry["stored_source_precedes_current_listing_by_calendar_days"]==570
    core=dict(
        schema_version=1,scope=PRIOR_SCOPE,year=2022,
        official_current_listed_eligible_twse_issuers=1092,
        aes_neon_current_listed_stocks_with_all_246_source_dates=825,
        production_neon_writes=0,line_messages_sent=0,
        model_release="BLOCKED",
    )
    return (
        dict(core,owner_129_no2022_current_twse_official_listing_date_triage=public),
        dict(core,owner_129_no2022_current_twse_official_listing_date_triage=private),
    )


def official_rows():
    one=[
        "6873","泓德能源-創","111.10.31","謝源一","850000",
        "111.12.12","111.12.27","111.12.28","",
        "112.03.06","永豐金","110.0","創新板",
    ]
    return [
        tuple([str(n),"Other","111.10.31","Name","1000",
               "111.12.12","111.12.27","111.12.28","",
               "112.05.09","券商","40.0",""])
        for n in range(4000,4070)
    ]+[tuple(one)]


def historic():
    return {"rows":official_rows(),"endpoint":URL,
            "source_sha256":"a"*64}


class TWSE6873HistoricInnovationToRegularBoardTests(unittest.TestCase):
    def test_true_twse_innovation_board_2023_regular_board_2024_not_tpex(self):
        public,private=owner_reports()
        r=reconcile(public,private,historic())
        self.assertEqual(r["scope"],SCOPE)
        self.assertEqual(r["stock_id"],"6873")
        self.assertEqual(r[
            "official_2023_initial_twse_innovation_board_trading_date"],"2023-03-06")
        self.assertEqual(r["official_latest_current_regular_board_listing_date"],"2024-09-26")
        self.assertEqual(r["time_between_innovation_listing_and_regular_board_days"],570)
        self.assertTrue(r[
            "recorded_current_official_listing_date_is_regular_board_switch_not_first_twse_listing"])
        self.assertEqual(r["historic_first_twse_board"],"TWSE_INNOVATION_BOARD")
        self.assertEqual(r["regular_board_switch_event"],"TWSE_INNOVATION_TO_REGULAR_BOARD")
        self.assertTrue(r["not_tpex_to_twse_transfer"])
        self.assertTrue(r[
            "prior_report_source_date_mismatch_reclassified_as_board_transition"])
        self.assertFalse(r["individual_neon_price_ohlcv_economics_verified"])
        self.assertFalse(r["historical_pit_issuer_universe_verified"])
        self.assertFalse(r["historical_halt_or_2022_116_internal_gaps_resolved"])
        self.assertEqual(r["neon_reads"],0)
        self.assertEqual(r["production_neon_writes"],0)
        self.assertEqual(r["line_messages_sent"],0)
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_fail_closed_if_actual_owner_stock_date_or_sha_changes(self):
        public,private=owner_reports()
        bad=dict(private)
        nested=dict(private["owner_129_no2022_current_twse_official_listing_date_triage"])
        nested["owner_private_official_listing_first_neon_date_conflicts"]=[
            dict(nested["owner_private_official_listing_first_neon_date_conflicts"][0],
                 first_valid_neon_source_date="2023-03-07")]
        bad["owner_129_no2022_current_twse_official_listing_date_triage"]=nested
        with self.assertRaises(ValueError):
            reconcile(public,bad,historic())
        changed=dict(public)
        source=dict(public["owner_129_no2022_current_twse_official_listing_date_triage"])
        source["official_current_company_basics_response_sha256"]="b"*64
        changed["owner_129_no2022_current_twse_official_listing_date_triage"]=source
        with self.assertRaises(ValueError):
            reconcile(changed,private,historic())
        bad=dict(private,production_neon_writes=1)
        with self.assertRaises(ValueError):
            reconcile(public,bad,historic())

    def test_historic_first_listing_wrong_date_wrong_board_or_market_fails(self):
        old,new=owner_reports()
        for mode in ("2024_regular_instead_of_innovation","tpex","wrong_date",
                     "wrong_code","missing","duplicate","wrong_column"):
            payload=historic()
            rows=payload["rows"]
            stock=list(rows[-1])
            if mode=="2024_regular_instead_of_innovation":
                stock[9]="113.09.26"
            elif mode=="tpex":
                stock[12]="上櫃"
            elif mode=="wrong_date":
                stock[9]="112.03.07"
            elif mode=="wrong_code":
                stock[0]="6874"
            elif mode=="missing":
                rows.pop()
            elif mode=="wrong_column":
                stock[0],stock[1]=stock[1],stock[0]
            if mode not in ("missing",):
                rows[-1]=tuple(stock)
            if mode=="duplicate":
                rows.append(tuple(stock))
            with self.assertRaises(ValueError):
                reconcile(old,new,payload)

    def test_fetch_public_official_html_extracts_real_table_semantics(self):
        html='<html><table>'+''.join(
            '<tr>'+''.join(f'<td>{cell}</td>' for cell in row)+'</tr>'
            for row in official_rows())+'</table></html>'
        response=Mock()
        response.status_code=200
        response.url=URL
        response.content=html.encode("utf-8")
        get=Mock(return_value=response)
        got=fetch_twse_historic_listings(get=get)
        self.assertEqual(got["source_sha256"],sha256(response.content).hexdigest())
        self.assertEqual(len(got["rows"]),71)
        self.assertEqual(got["rows"][-1][0],"6873")
        public,private=owner_reports()
        self.assertTrue(reconcile(public,private,got)[
            "prior_report_source_date_mismatch_reclassified_as_board_transition"])
        get.assert_called_once()
        args,kwargs=get.call_args
        self.assertEqual(args,(URL,))
        self.assertFalse(kwargs["allow_redirects"])

    def test_redirect_oversize_untrusted_no_data_or_nested_invalid_fails(self):
        response=Mock()
        response.url=URL
        response.status_code=200
        response.content=b"<html><table></table></html>"
        get=Mock(return_value=response)
        with self.assertRaises(ValueError):
            fetch_twse_historic_listings(get=get)
        response.url="https://not-twse.example.net/redirect"
        with self.assertRaises(ValueError):
            fetch_twse_historic_listings(get=get)
        response.url=URL
        response.content=b"x"*6_000_001
        with self.assertRaises(ValueError):
            fetch_twse_historic_listings(get=get)
        p=_TableRows()
        with self.assertRaises(ValueError):
            p.feed("<tr><td>6873<td>fail</td></tr>")

    def test_cli_help_requires_no_neon_credentials_aes_or_line(self):
        env=os.environ.copy()
        for x in ("DATABASE_URL","STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(x,None)
        root=Path(__file__).resolve().parents[1]
        cmd=[sys.executable,"-m",
             "scripts.twse_6873_innovation_regular_listing_official_readonly",
             "--help"]
        p=subprocess.run(cmd,cwd=root,env=env,capture_output=True,
                         text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("--prior-234-official-report",p.stdout)
        self.assertIn("--prior-235-conflict-report",p.stdout)
        self.assertIn("--out",p.stdout)


if __name__=="__main__":
    unittest.main()
