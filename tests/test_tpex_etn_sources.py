import unittest

from scripts.audit_tpex_etn_sources import extract_etn_codes


class TpexEtnSourceTests(unittest.TestCase):
    def test_extracts_codes_only_from_etn_section(self):
        html = """
        <h2>ETF</h2><p>代號：00888</p>
        <h2>ETN</h2><p>甲ETN (代號：020027)</p>
        <p>乙ETN (代號：020041)</p>
        """
        self.assertEqual(extract_etn_codes(html), ["020027", "020041"])

    def test_extracts_codes_from_real_tpex_product_markup(self):
        html = """
        <h3 class="h3-title">ETF</h3>
        <div class="product etf"><div class="product-code">(代號：00888)</div></div>
        <h3 class="h3-title">ETN</h3>
        <div class="product etn"><div class="product-title">甲</div>
          <div class="product-code">(代號：020027)</div></div>
        <div class="product etn"><div class="product-code">(代號：020041)</div></div>
        """
        self.assertEqual(extract_etn_codes(html), ["020027", "020041"])

    def test_deduplicates_codes(self):
        html = "<h2>ETN</h2><p>代號：020027</p><p>代號：020027</p>"
        self.assertEqual(extract_etn_codes(html), ["020027"])

    def test_empty_etn_section_returns_empty(self):
        html = "<h2>ETF</h2><p>代號：00888</p><h2>ETN</h2><p>no code</p>"
        self.assertEqual(extract_etn_codes(html), [])


if __name__ == "__main__":
    unittest.main()
