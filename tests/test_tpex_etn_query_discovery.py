import unittest

from scripts.discover_tpex_etn_queries import PageParser, inspect_asset


class TpexEtnQueryDiscoveryTests(unittest.TestCase):
    def test_extracts_forms_external_and_inline_scripts(self):
        parser = PageParser()
        parser.feed(
            '<form action="/query" method="post"><input name="year">'
            '<select name="type"></select></form>'
            '<script src="/assets/app.js"></script>'
            '<script>const endpoint = "/api/etn/list";</script>'
        )
        self.assertEqual(parser.forms[0]["action"], "/query")
        self.assertEqual(parser.forms[0]["method"], "post")
        self.assertEqual(parser.forms[0]["inputs"][0]["name"], "year")
        self.assertEqual(parser.forms[0]["selects"][0]["name"], "type")
        self.assertEqual(parser.scripts, ["/assets/app.js"])
        self.assertEqual(len(parser.inline_scripts), 1)

    def test_extracts_query_hints_without_confirming_endpoint(self):
        hits = inspect_asset('fetch("/api/etn/list"); tables.init({action:"/query"})')
        self.assertTrue(any("/api/etn/list" in hit for hit in hits))
        self.assertTrue(any("tables.init" in hit for hit in hits))


if __name__ == "__main__":
    unittest.main()
