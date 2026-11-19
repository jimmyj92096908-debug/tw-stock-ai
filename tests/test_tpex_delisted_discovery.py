import unittest
from scripts.discover_tpex_delisted_query import PageParser, inspect_asset

class TpexDelistedDiscoveryTests(unittest.TestCase):
    def test_extracts_form_fields_and_script_assets(self):
        parser = PageParser()
        parser.feed('<form action="/search" method="post"><input name="code"><select name="year"></select></form><script src="/app.js"></script>')
        self.assertEqual(parser.forms[0]["action"], "/search")
        self.assertEqual(parser.forms[0]["method"], "post")
        self.assertEqual(parser.forms[0]["inputs"][0]["name"], "code")
        self.assertEqual(parser.forms[0]["selects"][0]["name"], "year")
        self.assertEqual(parser.scripts, ["/app.js"])

    def test_extracts_frontend_api_hints_but_does_not_confirm_endpoint(self):
        hits = inspect_asset('fetch("/api/delist/search"); $.post("/query")', "test.js")
        self.assertTrue(any("/api/delist/search" in h for h in hits))
        self.assertTrue(any("$.post" in h for h in hits)

if __name__ == "__main__":
    unittest.main()
