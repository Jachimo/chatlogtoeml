import unittest

try:
    # Prefer package import
    from chatlogtoeml.parsers import apple_db as apple_db_module
except Exception:
    import apple_db as apple_db_module

class TestAppleDBScaffold(unittest.TestCase):
    def test_parse_file_exists(self):
        self.assertTrue(callable(getattr(apple_db_module, 'parse_file', None)))

    def test_apple_ts_conversion(self):
        # Apple timestamp 0 should convert to year 2001 (2001-01-01)
        dt = apple_db_module.apple_ts_to_dt(0)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2001)


if __name__ == '__main__':
    unittest.main()
