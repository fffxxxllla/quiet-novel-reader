import unittest

from global_hotkey import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, windows_hotkey


class GlobalHotkeyTests(unittest.TestCase):
    def test_default_shortcut_maps_to_windows_codes(self):
        self.assertEqual(windows_hotkey("Ctrl+Alt+Q"), (MOD_NOREPEAT | MOD_CONTROL | MOD_ALT, ord("Q")))

    def test_function_key_and_shift(self):
        self.assertEqual(windows_hotkey("Ctrl+Shift+F12"), (MOD_NOREPEAT | MOD_CONTROL | MOD_SHIFT, 0x7B))

    def test_unmodified_key_is_rejected(self):
        with self.assertRaises(ValueError):
            windows_hotkey("Q")


if __name__ == "__main__":
    unittest.main()
