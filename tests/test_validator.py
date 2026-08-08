"""Unit tests for spreadsheet pre-flight validator."""
import os
import unittest
from pathlib import Path
from src.netbox_importer.template_generator import create_template_excel
from src.netbox_importer.validator import validate_excel_file, _clean_str


class TestValidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_excel = "test_output.xlsx"
        create_template_excel(cls.test_excel)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_excel):
            os.remove(cls.test_excel)

    def test_generated_template_validation(self):
        res = validate_excel_file(self.test_excel)
        self.assertTrue(res.is_valid, f"Validation errors found: {res.errors}")
        self.assertEqual(len(res.devices), 10)
        self.assertEqual(res.config["NETBOX_HOST"], "192.168.1.172")
        self.assertEqual(res.config["INTERFACE_NAME"], "eth0")

    def test_custom_mask_preservation(self):
        res = validate_excel_file(self.test_excel)
        # Device 9 in sample dataset has explicit /16 mask
        dev9 = [d for d in res.devices if "/16" in d["cidr_ip"]]
        self.assertEqual(len(dev9), 1)
        self.assertTrue(dev9[0]["cidr_ip"].endswith("/16"))

    def test_overwrite_column_parsing(self):
        res = validate_excel_file(self.test_excel)
        # Device 10 in sample dataset has Overwrite set to TRUE
        dev10 = res.devices[9]
        self.assertTrue(dev10["overwrite"], "Device 10 should have overwrite=True")
        dev1 = res.devices[0]
        self.assertFalse(dev1["overwrite"], "Device 1 should have overwrite=False")

    def test_prefixes_sheet_parsing(self):
        res = validate_excel_file(self.test_excel)
        self.assertEqual(len(res.prefixes), 2)
        self.assertEqual(res.prefixes[0]["prefix"], "192.168.70.0/24")
        self.assertEqual(res.prefixes[0]["description"], "Lab Test Devices Subnet")

    def test_clean_str(self):
        self.assertEqual(_clean_str(123), "123")
        self.assertEqual(_clean_str("  test  "), "test")
        self.assertEqual(_clean_str(None), "")


if __name__ == "__main__":
    unittest.main()
