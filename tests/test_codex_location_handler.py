import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[1]
HANDLER = REPO_ROOT / "tools" / "codex-clickable" / "codex-location-handler.ps1"


def location_uri(path: Path | str) -> str:
    uri_path = str(path).replace("\\", "/")
    return f"codex-location:///{quote(uri_path, safe='/:')}"


class CodexLocationHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="codex-location-handler-")
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def invoke_handler(
        self,
        uri: str,
        *,
        extra_environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        if extra_environment:
            environment.update(extra_environment)

        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(HANDLER),
                "-Uri",
                uri,
                "-DryRun",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )

    def run_handler(self, uri: str) -> dict[str, object]:
        completed = self.invoke_handler(uri)
        self.assertEqual(
            0,
            completed.returncode,
            msg=f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}",
        )
        lines = completed.stdout.strip().splitlines()
        self.assertEqual(1, len(lines), msg=completed.stdout)
        payload = json.loads(lines[0])
        self.assertEqual(
            {"action", "path", "executable", "arguments"},
            set(payload),
        )
        return payload

    def assert_path_equal(self, expected: Path | str, actual: object) -> None:
        self.assertIsInstance(actual, str)
        self.assertEqual(
            os.path.normcase(os.path.normpath(str(expected))),
            os.path.normcase(os.path.normpath(actual)),
        )

    def assert_rejected(self, uri: str) -> None:
        completed = self.invoke_handler(uri)
        self.assertNotEqual(
            0,
            completed.returncode,
            msg=f"unsafe URI was accepted: {uri}\nstdout={completed.stdout!r}",
        )
        self.assertEqual("", completed.stdout.strip())

    def test_existing_file_is_selected(self) -> None:
        file_path = self.root / "selected.txt"
        file_path.write_text("content", encoding="utf-8")

        payload = self.run_handler(location_uri(file_path))

        self.assertEqual("select-file", payload["action"])
        self.assert_path_equal(file_path, payload["path"])
        self.assert_path_equal(
            Path(os.environ["WINDIR"]) / "explorer.exe",
            payload["executable"],
        )
        self.assertEqual([f'/select,"{file_path}"'], payload["arguments"])

    def test_existing_directory_is_opened(self) -> None:
        directory = self.root / "existing-directory"
        directory.mkdir()

        payload = self.run_handler(location_uri(directory))

        self.assertEqual("open-directory", payload["action"])
        self.assert_path_equal(directory, payload["path"])
        self.assertEqual([f'"{directory}"'], payload["arguments"])

    def test_missing_file_opens_existing_parent(self) -> None:
        missing_file = self.root / "missing.txt"

        payload = self.run_handler(location_uri(missing_file))

        self.assertEqual("open-parent", payload["action"])
        self.assert_path_equal(self.root, payload["path"])
        self.assertEqual([f'"{self.root}"'], payload["arguments"])

    def test_missing_parent_is_rejected(self) -> None:
        self.assert_rejected(location_uri(self.root / "missing-parent" / "missing.txt"))

    def test_spaces_and_non_ascii_paths_are_decoded(self) -> None:
        spaced_directory = self.root / "directory with spaces"
        spaced_directory.mkdir()
        unicode_file = spaced_directory / "\u4f4d\u7f6e-\u6587\u4ef6.txt"
        unicode_file.write_text("content", encoding="utf-8")

        directory_payload = self.run_handler(location_uri(spaced_directory))
        file_payload = self.run_handler(location_uri(unicode_file))

        self.assertEqual("open-directory", directory_payload["action"])
        self.assert_path_equal(spaced_directory, directory_payload["path"])
        self.assertEqual("select-file", file_payload["action"])
        self.assert_path_equal(unicode_file, file_payload["path"])

    def test_encoded_quotes_and_control_characters_are_rejected(self) -> None:
        quoted_uri = location_uri(f'{self.root}\\bad"name.txt')
        control_uri = location_uri(f"{self.root}\\bad\nname.txt")
        self.assertIn("%22", quoted_uri)
        self.assertIn("%0A", control_uri)

        for uri in (quoted_uri, control_uri):
            with self.subTest(uri=uri):
                self.assert_rejected(uri)

    def test_host_userinfo_query_fragment_and_wrong_scheme_are_rejected(self) -> None:
        file_path = self.root / "safe.txt"
        file_path.write_text("content", encoding="utf-8")
        valid_uri = location_uri(file_path)
        path_part = valid_uri.removeprefix("codex-location:///")
        unsafe_uris = (
            f"codex-location://example.invalid/{path_part}",
            f"codex-location://user@example.invalid/{path_part}",
            f"{valid_uri}?mode=select",
            f"{valid_uri}#fragment",
            valid_uri.replace("codex-location:", "file:", 1),
        )

        for uri in unsafe_uris:
            with self.subTest(uri=uri):
                self.assert_rejected(uri)

    def test_unc_device_namespace_and_ads_paths_are_rejected(self) -> None:
        unsafe_uris = (
            "codex-location:////server/share/file.txt",
            "codex-location:///%5C%5C%3F%5CC%3A%5CWindows%5Cfile.txt",
            "codex-location:///%5C%5C.%5CPhysicalDrive0",
            f"{location_uri(self.root / 'safe.txt')}:stream",
        )

        for uri in unsafe_uris:
            with self.subTest(uri=uri):
                self.assert_rejected(uri)

    def test_malformed_and_double_encoded_input_is_rejected(self) -> None:
        base_uri = location_uri(self.root)
        unsafe_uris = (
            f"{base_uri}/bad%ZZname.txt",
            f"{base_uri}/bad%2522name.txt",
            f"{base_uri}/bad%253Astream.txt",
        )

        for uri in unsafe_uris:
            with self.subTest(uri=uri):
                self.assert_rejected(uri)

    def test_environment_variable_text_is_not_expanded(self) -> None:
        literal_directory = self.root / "%CODEX_LOCATION_SENTINEL%"
        literal_directory.mkdir()
        expanded_directory = self.root / "expanded"
        expanded_directory.mkdir()

        completed = self.invoke_handler(
            location_uri(literal_directory),
            extra_environment={"CODEX_LOCATION_SENTINEL": str(expanded_directory)},
        )

        self.assertNotEqual(0, completed.returncode)
        self.assertEqual("", completed.stdout.strip())

    def test_command_text_is_rejected_without_side_effects(self) -> None:
        marker = self.root / "handler-side-effect.txt"
        injected_path = (
            f"{self.root}\\missing.txt; "
            "New-Item -ItemType File -Path handler-side-effect.txt"
        )

        completed = self.invoke_handler(location_uri(injected_path))

        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(marker.exists())
        self.assertEqual("", completed.stdout.strip())


if __name__ == "__main__":
    unittest.main()
