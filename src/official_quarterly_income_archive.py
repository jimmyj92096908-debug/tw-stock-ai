"""Latest official quarterly general-industry income statement as-first-seen data.

NOT a historical publication-date feed. These official OpenAPI endpoints may
only return a current reporting quarter. First-observed evidence starts NOW,
not at fiscal period-end or the issuer's actual filing timestamp.
"""
from __future__ import annotations
from calendar import monthrange
from datetime import date,datetime
from decimal import Decimal
from hashlib import sha256
import json
import re

from src.official_revenue_archive import aware,decimal_or_none,roc_day

SOURCES={
 "twse":"https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
 "tpex":"https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci",
}
MAX_ROWS=2500
ALIASES={
 "stock_id":("公司代號","SecuritiesCompanyCode","CompanyCode"),
 "year":("年度","Year"),
 "quarter":("季別","Season","Quarter"),
 "table_day":("出表日期","DateOfPublication","TableDate"),
 "revenue":("營業收入","OperatingRevenue"),
 "operating_income":("營業利益（損失）","OperatingIncome"),
 "net_income":("本期淨利（淨損）","NetIncome"),
 "eps":("基本每股盈餘（元）","基本每股盈餘","BasicEarningsPerShare"),
}


def _get(row,key):
    for name in ALIASES[key]:
        if name in row:
            return row[name]
    return None


def fiscal_quarter(raw_year,raw_q):
    try:
        y=int(str(raw_year).strip())
        q=int(str(raw_q).strip())
    except (TypeError,ValueError) as ex:
        raise ValueError("Official fiscal year and quarter required") from ex
    if not 1<=q<=4 or not 95<=y<=2100:
        raise ValueError("Official fiscal period outside realistic bounds")
    year=y+1911 if y<=250 else y
    month=q*3
    return year,q,date(year,month,monthrange(year,month)[1])


def official_day(value,*,period,observed):
    if value is None or str(value).strip()=="":
        # Do NOT invent a company's actual disclosure timestamp.
        return None
    text=str(value).strip()
    if re.fullmatch(r"\d{7}",text):
        result=roc_day(text)
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}",text):
        result=date.fromisoformat(text)
    else:
        raise ValueError("Official table date format unsupported")
    if not period<=result<=observed:
        raise ValueError("Official table date outside fiscal/capture range")
    return result


def _metric(row,key,*,bound=Decimal("1000000000000000")):
    raw=_get(row,key)
    # Blank accounting cells are unspecified, not numeric zero.
    return decimal_or_none(raw,max_abs=bound)


def parse_snapshot(market,raw_rows,*,observed_at):
    if market not in SOURCES:
        raise ValueError("Unknown TWSE/TPEx general-industry income source")
    at=aware(observed_at)
    if not isinstance(raw_rows,list) or not 1<=len(raw_rows)<=MAX_ROWS:
        raise ValueError("Unbounded or empty official quarterly result")
    seen=set()
    records=[]
    for row in raw_rows:
        if not isinstance(row,dict):
            raise ValueError("Official quarterly row must be an object")
        ticker=_get(row,"stock_id")
        stock_id=str(ticker).strip() if ticker is not None else ""
        if not re.fullmatch(r"[0-9]{4,6}",stock_id):
            continue
        fiscal_year,q,period=fiscal_quarter(_get(row,"year"),_get(row,"quarter"))
        if period>at.date():
            raise ValueError("Official fiscal quarter has not ended")
        marker=(market,stock_id,period.isoformat())
        if marker in seen:
            raise ValueError("Duplicate official issuer-quarter")
        seen.add(marker)
        table_date=official_day(_get(row,"table_day"),period=period,
                                observed=at.date())
        revenue=_metric(row,"revenue")
        operating=_metric(row,"operating_income")
        net=_metric(row,"net_income")
        eps=_metric(row,"eps",bound=Decimal("100000000"))
        eps_outlier=eps is not None and abs(eps)>Decimal("100000")
        if eps_outlier:
            eps=None
        if all(v is None for v in (revenue,operating,net,eps)):
            # Do not turn missing empty financial statements into null factors.
            continue
        material={
            "market":market,"stock_id":stock_id,"fiscal_year":fiscal_year,
            "fiscal_quarter":q,"period_end":period.isoformat(),
            "official_table_date":table_date.isoformat() if table_date else None,
            "revenue_ytd_thousands_ntd":str(revenue) if revenue is not None else None,
            "operating_income_ytd_thousands_ntd":str(operating) if operating is not None else None,
            "net_income_ytd_thousands_ntd":str(net) if net is not None else None,
            "basic_eps_ytd_ntd":str(eps) if eps is not None else None,
            "eps_outlier_suppressed":eps_outlier,
        }
        digest=sha256(json.dumps(material,sort_keys=True,ensure_ascii=False,
                                 separators=(",",":")).encode()).hexdigest()
        records.append({
            **material,
            "first_observed_at":at.isoformat(),
            "source_url":SOURCES[market],
            "payload_sha256":digest,
        })
    if not records:
        raise ValueError("Official source lacks valid issuer income rows")
    return records


def asof_quarterly(records,*,market,stock_id,signal_cutoff):
    asof=aware(signal_cutoff)
    if (asof.hour,asof.minute,asof.second,asof.microsecond)!=(13,30,0,0):
        raise ValueError("Taiwan 13:30 close timestamp required")
    if market not in SOURCES or not re.fullmatch(r"[0-9]{4,6}",str(stock_id)):
        raise ValueError("Bad quarterly issuer")
    if not isinstance(records,list) or len(records)>100:
        raise ValueError("Bounded saved issuer revisions required")
    admitted=[]
    for row in records:
        if row.get("market")!=market or row.get("stock_id")!=stock_id:
            continue
        first=aware(row.get("first_observed_at"))
        end=date.fromisoformat(row["period_end"])
        if end>first.date():
            raise ValueError("Quarterly source period exceeds first observed date")
        if first<=asof:
            admitted.append(row)
    latest=max(admitted,key=lambda r:(
        r["period_end"],aware(r["first_observed_at"]),r["payload_sha256"]
    )) if admitted else None
    return {
      "market":market,"stock_id":stock_id,"signal_cutoff":asof.isoformat(),
      "quarterly_income":latest,
      "covered":latest is not None,
      "company_publication_timestamp_known":False,
      "first_observed_before_signal_enforced":True,
      "historical_backdating_prohibited":True,
      "financial_factors_added_to_production_model":False,
      "live_trading_approved":False,
    }
