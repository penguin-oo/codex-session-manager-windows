import unittest
from pathlib import Path


class SourceEncodingTests(unittest.TestCase):
    def test_root_python_files_do_not_start_with_utf8_bom(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        targets = [
            repo_root / "app.py",
            repo_root / "mobile_portal.py",
            repo_root / "token_pool_proxy.py",
            repo_root / "token_pool_settings.py",
        ]
        offending = [path.name for path in targets if path.read_bytes().startswith(b"\xef\xbb\xbf")]
        self.assertEqual([], offending, f"Files unexpectedly start with UTF-8 BOM: {offending}")
