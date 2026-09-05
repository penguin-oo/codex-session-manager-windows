import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import window_runtime


class WindowRuntimeTests(unittest.TestCase):
    def make_base_home(self, root: Path) -> Path:
        base_home = root / "codex-home"
        base_home.mkdir()
        (base_home / "config.toml").write_text('model = "test-model"\n', encoding="utf-8")
        (base_home / "models_cache.json").write_text('{"models":[]}\n', encoding="utf-8")
        (base_home / "auth.json").write_text('{"tokens":"private"}\n', encoding="utf-8")
        (base_home / "installation_id").write_text("current-installation\n", encoding="utf-8")
        (base_home / "installation_id.original").write_text(
            "baseline-installation\n",
            encoding="utf-8",
        )
        (base_home / "history.jsonl").write_text('{"session_id":"shared"}\n', encoding="utf-8")
        (base_home / "memory.jsonl").write_text('{"memory":"shared"}\n', encoding="utf-8")
        sessions = base_home / "sessions"
        sessions.mkdir()
        (sessions / "shared-session.jsonl").write_text("{}\n", encoding="utf-8")
        skills = base_home / "skills"
        skills.mkdir()
        (skills / "shared-skill.txt").write_text("shared\n", encoding="utf-8")
        generated_images = base_home / "generated_images"
        generated_images.mkdir()
        (generated_images / "shared-image.txt").write_text("shared\n", encoding="utf-8")
        plugin_cache = base_home / ".tmp"
        plugin_cache.mkdir()
        (plugin_cache / "shared-cache.txt").write_text("shared\n", encoding="utf-8")
        return base_home

    def test_isolated_runtime_uses_private_snapshot_and_shared_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_home = self.make_base_home(Path(temp_dir))

            runtime = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=True,
                installation_id="preset-installation",
                session_id="session-a",
                launch_id="launch-a",
            )

            self.assertTrue(runtime.isolated)
            self.assertNotEqual(base_home, runtime.codex_home)
            self.assertEqual(base_home, runtime.sqlite_home)
            self.assertEqual(
                'model = "test-model"\n',
                (runtime.codex_home / "config.toml").read_text(encoding="utf-8"),
            )
            self.assertTrue((runtime.codex_home / "models_cache.json").exists())
            self.assertFalse((runtime.codex_home / "auth.json").exists())
            self.assertEqual(
                "preset-installation",
                (runtime.codex_home / "installation_id").read_text(encoding="utf-8").strip(),
            )
            self.assertEqual(
                (base_home / "sessions").resolve(),
                (runtime.codex_home / "sessions").resolve(),
            )
            self.assertEqual(
                (base_home / "skills").resolve(),
                (runtime.codex_home / "skills").resolve(),
            )
            self.assertEqual(
                (base_home / "generated_images").resolve(),
                (runtime.codex_home / "generated_images").resolve(),
            )
            self.assertEqual(
                (base_home / ".tmp").resolve(),
                (runtime.codex_home / ".tmp").resolve(),
            )
            self.assertTrue(
                (base_home / "history.jsonl").samefile(runtime.codex_home / "history.jsonl")
            )
            self.assertTrue(
                (base_home / "memory.jsonl").samefile(runtime.codex_home / "memory.jsonl")
            )

            manifest = json.loads(runtime.manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(
                {"launch_id", "session_id", "created_at", "isolated"},
                set(manifest),
            )
            self.assertNotIn("preset-installation", runtime.manifest_file.read_text(encoding="utf-8"))

            window_runtime.cleanup_window_runtime(runtime.runtime_dir, runtime.runtime_root)

            self.assertFalse(runtime.runtime_dir.exists())
            self.assertTrue((base_home / "sessions" / "shared-session.jsonl").exists())
            self.assertTrue((base_home / "skills" / "shared-skill.txt").exists())
            self.assertTrue((base_home / "generated_images" / "shared-image.txt").exists())

    def test_isolated_runtime_uses_original_installation_as_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_home = self.make_base_home(Path(temp_dir))

            runtime = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=True,
                launch_id="launch-baseline",
            )
            try:
                self.assertEqual(
                    "baseline-installation",
                    (runtime.codex_home / "installation_id").read_text(encoding="utf-8").strip(),
                )
            finally:
                window_runtime.cleanup_window_runtime(runtime.runtime_dir, runtime.runtime_root)

    def test_isolated_runtime_supports_unicode_and_spaces_in_home_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir) / "unicode-\u914d\u7f6e path"
            parent.mkdir()
            base_home = self.make_base_home(parent)

            runtime = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=True,
                launch_id="launch-path",
            )
            try:
                self.assertEqual(
                    (base_home / "sessions").resolve(),
                    (runtime.codex_home / "sessions").resolve(),
                )
            finally:
                window_runtime.cleanup_window_runtime(runtime.runtime_dir, runtime.runtime_root)

    def test_missing_baseline_installation_id_is_created_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_home = self.make_base_home(Path(temp_dir))
            (base_home / "installation_id").unlink()
            (base_home / "installation_id.original").unlink()

            first = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=True,
                launch_id="launch-generated-first",
            )
            first_id = (first.codex_home / "installation_id").read_text(encoding="utf-8").strip()
            window_runtime.cleanup_window_runtime(first.runtime_dir, first.runtime_root)
            second = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=True,
                launch_id="launch-generated-second",
            )
            try:
                second_id = (
                    second.codex_home / "installation_id"
                ).read_text(encoding="utf-8").strip()
                self.assertEqual(first_id, second_id)
                self.assertEqual(
                    first_id,
                    (base_home / "installation_id").read_text(encoding="utf-8").strip(),
                )
            finally:
                window_runtime.cleanup_window_runtime(second.runtime_dir, second.runtime_root)

    def test_auth_runtime_keeps_shared_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_home = self.make_base_home(Path(temp_dir))

            runtime = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=False,
                launch_id="launch-auth",
            )
            try:
                self.assertFalse(runtime.isolated)
                self.assertEqual(base_home, runtime.codex_home)
                self.assertEqual(base_home, runtime.sqlite_home)
                self.assertTrue((runtime.codex_home / "auth.json").exists())
            finally:
                window_runtime.cleanup_window_runtime(runtime.runtime_dir, runtime.runtime_root)

    def test_runtime_can_use_separate_sqlite_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_home = self.make_base_home(Path(temp_dir))
            sqlite_home = Path(temp_dir) / "legacy-cli-sqlite"

            runtime = window_runtime.prepare_window_runtime(
                base_home=base_home,
                sqlite_home=sqlite_home,
                isolate_home=False,
                launch_id="launch-separate-sqlite",
            )
            try:
                self.assertEqual(sqlite_home, runtime.sqlite_home)
                self.assertTrue(sqlite_home.exists())
                self.assertEqual(base_home, runtime.codex_home)
            finally:
                window_runtime.cleanup_window_runtime(runtime.runtime_dir, runtime.runtime_root)

    def test_pending_runtime_blocks_duplicate_writable_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_home = self.make_base_home(Path(temp_dir))
            first = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=False,
                session_id="session-locked",
                launch_id="launch-first",
            )
            try:
                with self.assertRaises(window_runtime.SessionAlreadyOpenError):
                    window_runtime.prepare_window_runtime(
                        base_home=base_home,
                        isolate_home=True,
                        session_id="session-locked",
                        launch_id="launch-second",
                    )
            finally:
                window_runtime.cleanup_window_runtime(first.runtime_dir, first.runtime_root)

    def test_stale_runtime_is_removed_before_duplicate_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_home = self.make_base_home(Path(temp_dir))
            stale = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=False,
                session_id="session-reusable",
                launch_id="launch-stale",
                now=100.0,
            )
            stale.pid_file.write_text("424242\n", encoding="ascii")

            fresh = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=False,
                session_id="session-reusable",
                launch_id="launch-fresh",
                now=200.0,
                process_alive=lambda _pid: False,
                pending_grace_seconds=60.0,
            )
            try:
                self.assertFalse(stale.runtime_dir.exists())
                self.assertTrue(fresh.runtime_dir.exists())
            finally:
                window_runtime.cleanup_window_runtime(fresh.runtime_dir, fresh.runtime_root)

    def test_current_process_is_reported_alive(self) -> None:
        self.assertTrue(window_runtime.is_process_alive(os.getpid()))

    @unittest.skipUnless(os.name == "nt", "junction fallback is Windows-specific")
    def test_directory_links_fall_back_to_cmd_when_native_creation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_home = self.make_base_home(root)
            private_home = root / "private-home"
            private_home.mkdir()
            with (
                mock.patch.object(
                    window_runtime,
                    "_create_windows_junction",
                    side_effect=OSError("native junction unavailable"),
                ),
                mock.patch.object(
                    window_runtime,
                    "_create_windows_junctions_with_cmd",
                ) as fallback,
            ):
                window_runtime._create_directory_links(base_home, private_home)

            fallback.assert_called_once()

    def test_runtime_powershell_wrapper_binds_home_pid_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_home = self.make_base_home(root)
            runtime = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=True,
                installation_id="wrapper-installation",
                launch_id="launch-wrapper",
            )
            helper = root / "window runtime helper.py"
            python = root / "python executable.exe"
            try:
                command = window_runtime.build_runtime_powershell_wrapper(
                    "Write-Output 'run codex'",
                    runtime=runtime,
                    python_executable=python,
                    helper_path=helper,
                )

                self.assertIn("$PID", command)
                self.assertIn("$env:CODEX_HOME", command)
                self.assertIn(str(runtime.codex_home).replace("'", "''"), command)
                self.assertIn("$env:CODEX_SQLITE_HOME", command)
                self.assertIn(str(base_home).replace("'", "''"), command)
                self.assertIn("try {", command)
                self.assertIn("finally {", command)
                self.assertIn("cleanup", command)
                self.assertIn(str(runtime.pid_file).replace("'", "''"), command)
                self.assertIn(str(helper).replace("'", "''"), command)
                self.assertNotIn("wrapper-installation", command)
            finally:
                window_runtime.cleanup_window_runtime(runtime.runtime_dir, runtime.runtime_root)

    def test_runtime_wrapper_accepts_packaged_cleanup_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_home = self.make_base_home(root)
            runtime = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=False,
                launch_id="launch-packaged",
            )
            try:
                command = window_runtime.build_runtime_powershell_wrapper(
                    "Write-Output 'run codex'",
                    runtime=runtime,
                    cleanup_command=[
                        root / "CodexPlus.exe",
                        "--window-runtime-cleanup",
                    ],
                )
                self.assertIn("CodexPlus.exe", command)
                self.assertIn("--window-runtime-cleanup", command)
                self.assertIn("--runtime-root", command)
                self.assertIn("--runtime-dir", command)
            finally:
                window_runtime.cleanup_window_runtime(runtime.runtime_dir, runtime.runtime_root)

    def test_cleanup_removes_read_only_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_home = self.make_base_home(Path(temp_dir))
            runtime = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=True,
                launch_id="launch-read-only",
            )
            read_only_file = runtime.codex_home / ".private-tmp" / "clone" / "pack.idx"
            read_only_file.parent.mkdir(parents=True)
            read_only_file.write_text("read-only\n", encoding="utf-8")
            read_only_file.chmod(stat.S_IREAD)

            window_runtime.cleanup_window_runtime(runtime.runtime_dir, runtime.runtime_root)

            self.assertFalse(runtime.runtime_dir.exists())

    @unittest.skipUnless(os.name == "nt", "PowerShell wrapper is Windows-specific")
    def test_powershell_wrapper_executes_final_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_home = self.make_base_home(Path(temp_dir))
            runtime = window_runtime.prepare_window_runtime(
                base_home=base_home,
                isolate_home=True,
                launch_id="launch-powershell",
            )
            command = window_runtime.build_runtime_powershell_wrapper(
                "Write-Output 'runtime-wrapper-ok' | Out-Null",
                runtime=runtime,
                python_executable=Path(sys.executable),
                helper_path=Path(window_runtime.__file__).resolve(),
            )

            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(runtime.runtime_dir.exists())


if __name__ == "__main__":
    unittest.main()
