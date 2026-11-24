# 1101 August 2025: official trading suspension evidence

TWSE's August 12, 2025 notice establishes suspension of 1101 ordinary shares from August 13:
https://wwwc.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d697fc438f01989dd5fa3502a6.pdf

TWSE's August 13, 2025 notice establishes resumption on August 14:
https://wwwc.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d697fc438f0198a36441f702b8.pdf

Owner's actual capture stopped at 1101 / 2025-08 / OFFICIAL_PARSE / ValueError.
151/235 prior cache pairs and 3,008 valid rows passed owner offline replay.
The actual failing STOCK_DAY response body was not available to the reviewer.
The observed halt is an independently confirmed event, not proof of the exact
failed field. The parser change is intentionally conditional: only the exact
halt date and issuer, zero volume and turnover, and four missing price markers
may be skipped. Other invalid rows still fail closed. Raw official response
bytes and original receipt remain preserved, and the skipped day does not
become a synthetic bar. A month with no valid traded bars still fails.
The exact raw response needs a real owner-side replay. Unknown parse failures
report only allowlisted static error descriptions. No database or LINE writes;
no historical vintage, calendar completeness, model performance, or release
approval is implied.
