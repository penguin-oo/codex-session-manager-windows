import subprocess
import unittest
from pathlib import Path
from unittest import mock

import process_singleton


class ProcessSingletonTests(unittest.TestCase):
    def test_cleanup_discards_taskkill_output_without_text_decoding(self) -> None:
        app_dir = Path("D:/workspace/codex-manager")
        process = {
            "ProcessId": 321,
            "CommandLine": "python D:/workspace/codex-manager/app.py",
        }

        with (
            mock.patch.object(
                process_singleton,
                "_list_windows_processes",
                return_value=[process],
            ),
            mock.patch.object(process_singleton.os, "name", "nt"),
            mock.patch.object(process_singleton.os, "getppid", return_value=111),
            mock.patch.object(process_singleton.subprocess, "run") as run,
        ):
            killed = process_singleton.cleanup_previous_project_instances(
                app_dir=app_dir,
                current_pid=222,
            )

        self.assertEqual([321], killed)
        run.assert_called_once_with(
            ["taskkill.exe", "/PID", "321", "/F", "/T"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
