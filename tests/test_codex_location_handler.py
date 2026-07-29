import copy
import ctypes
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import winreg
from pathlib import Path
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[1]
HANDLER = REPO_ROOT / "tools" / "codex-clickable" / "codex-location-handler.ps1"
INSTALLER = (
    REPO_ROOT
    / "tools"
    / "codex-clickable"
    / "install-codex-location-handler.ps1"
)
REGISTRY_KEY = r"HKCU\Software\Classes\codex-location"
REGISTRY_SUBKEY = r"Software\Classes\codex-location"
REGISTRY_DESCRIPTION = "URL:codex-location Protocol"
OWNER_NAME = "Codex Location Owner"
OWNER_VALUE = "codex-session-manager-windows/v1"


def windows_powershell_executable() -> Path:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::Out.Write($PSHOME)",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout:
        raise RuntimeError(f"could not resolve Windows PowerShell: {completed.stderr}")
    return Path(completed.stdout) / "powershell.exe"


WINDOWS_POWERSHELL = windows_powershell_executable()


def registry_value(name: str, data: str) -> dict[str, object]:
    return {
        "name": name,
        "type": winreg.REG_SZ,
        "data": data,
    }


def registry_node(
    *,
    values: list[dict[str, object]] | None = None,
    subkeys: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "values": values or [],
        "subkeys": subkeys or [],
    }


def named_registry_node(
    name: str,
    node: dict[str, object],
) -> dict[str, object]:
    return {
        "name": name,
        **node,
    }


def owned_registry_state(command: str) -> dict[str, object]:
    command_node = registry_node(values=[registry_value("", command)])
    open_node = registry_node(
        subkeys=[named_registry_node("command", command_node)]
    )
    shell_node = registry_node(
        subkeys=[named_registry_node("open", open_node)]
    )
    root = registry_node(
        values=[
            registry_value("", REGISTRY_DESCRIPTION),
            registry_value("URL Protocol", ""),
            registry_value(OWNER_NAME, OWNER_VALUE),
        ],
        subkeys=[named_registry_node("shell", shell_node)],
    )
    return {
        "exists": True,
        "tree": root,
    }


def normalize_registry_data(data: object) -> object:
    if isinstance(data, bytes):
        return {"bytes": data.hex()}
    if isinstance(data, (list, tuple)):
        return [normalize_registry_data(item) for item in data]
    if data is None or isinstance(data, (int, str)):
        return data
    return repr(data)


def read_registry_tree(key: int) -> dict[str, object]:
    _, value_count, _ = winreg.QueryInfoKey(key)
    values = []
    for index in range(value_count):
        name, data, value_type = winreg.EnumValue(key, index)
        values.append(
            {
                "name": name,
                "type": value_type,
                "data": normalize_registry_data(data),
            }
        )

    subkeys: dict[str, object] = {}
    subkey_count, _, _ = winreg.QueryInfoKey(key)
    for index in range(subkey_count):
        name = winreg.EnumKey(key, index)
        with winreg.OpenKey(key, name, 0, winreg.KEY_READ) as child:
            subkeys[name] = read_registry_tree(child)

    return {
        "values": sorted(values, key=lambda value: value["name"]),
        "subkeys": subkeys,
    }


def registry_state_and_hash() -> tuple[bool, str]:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REGISTRY_SUBKEY,
            0,
            winreg.KEY_READ,
        ) as key:
            state: dict[str, object] = {
                "exists": True,
                "tree": read_registry_tree(key),
            }
    except FileNotFoundError:
        state = {"exists": False}

    serialized = json.dumps(
        state,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return bool(state["exists"]), hashlib.sha256(serialized).hexdigest()


def parse_explorer_argument(argument: str) -> list[str]:
    command_line_to_argv = ctypes.windll.shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = [
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_int),
    ]
    command_line_to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)
    local_free = ctypes.windll.kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    argument_count = ctypes.c_int()
    argument_vector = command_line_to_argv(
        f"explorer.exe {argument}",
        ctypes.byref(argument_count),
    )
    if not argument_vector:
        raise ctypes.WinError()

    try:
        return [
            argument_vector[index]
            for index in range(1, argument_count.value)
        ]
    finally:
        local_free(ctypes.cast(argument_vector, ctypes.c_void_p))


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

    def run_handler(
        self,
        uri: str,
        *,
        extra_environment: dict[str, str] | None = None,
    ) -> dict[str, object]:
        completed = self.invoke_handler(uri, extra_environment=extra_environment)
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

    def test_existing_directory_with_parentheses_is_opened(self) -> None:
        directory = self.root / "Program Files (x86)"
        directory.mkdir()

        payload = self.run_handler(location_uri(directory))

        self.assertEqual("open-directory", payload["action"])
        self.assert_path_equal(directory, payload["path"])
        self.assertEqual([f'"{directory}"'], payload["arguments"])

    def test_trailing_separator_directory_argument_round_trips(self) -> None:
        directory = self.root / "trailing-separator"
        directory.mkdir()
        directory_with_separator = f"{directory}\\"

        payload = self.run_handler(location_uri(directory_with_separator))

        self.assertEqual(directory_with_separator, payload["path"])
        self.assertEqual(
            [directory_with_separator],
            parse_explorer_argument(payload["arguments"][0]),
        )

    def test_drive_root_argument_round_trips(self) -> None:
        drive_root = self.root.anchor

        payload = self.run_handler(location_uri(drive_root))

        self.assertEqual(drive_root, payload["path"])
        self.assertEqual(
            [drive_root],
            parse_explorer_argument(payload["arguments"][0]),
        )

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

    def test_legal_windows_path_characters_are_accepted(self) -> None:
        file_path = self.root / "legal ! # $ % & ' ; @ ^ ` { }.txt"
        file_path.write_text("content", encoding="utf-8")

        payload = self.run_handler(location_uri(file_path))

        self.assertEqual("select-file", payload["action"])
        self.assert_path_equal(file_path, payload["path"])

    def test_invalid_windows_characters_and_controls_are_rejected(self) -> None:
        unsafe_paths = [
            f"{self.root}\\bad{character}name.txt"
            for character in '<>"|?*'
        ]
        unsafe_paths.extend(
            (
                f"{self.root}\\bad\nname.txt",
                f"{self.root}\\bad\uFFFDname.txt",
            )
        )

        for path in unsafe_paths:
            uri = location_uri(path)
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

    def test_single_slash_uri_is_rejected(self) -> None:
        directory = self.root / "single-slash"
        directory.mkdir()
        uri = location_uri(directory).replace(
            "codex-location:///",
            "codex-location:/",
            1,
        )

        self.assert_rejected(uri)

    def test_unc_device_namespace_and_ads_paths_are_rejected(self) -> None:
        unsafe_uris = (
            "codex-location:////server/share/file.txt",
            "codex-location:///%5C%5C%3F%5CC%3A%5CWindows%5Cfile.txt",
            "codex-location:///%5C%5C.%5CPhysicalDrive0",
            f"{location_uri(self.root)}%5Cchild.txt",
            f"{location_uri(self.root / 'safe.txt')}:stream",
        )

        for uri in unsafe_uris:
            with self.subTest(uri=uri):
                self.assert_rejected(uri)

    def test_malformed_percent_escape_is_rejected(self) -> None:
        self.assert_rejected(f"{location_uri(self.root)}/bad%ZZname.txt")

    def test_double_encoded_text_remains_literal(self) -> None:
        literal_paths = (
            self.root / "bad%22name.txt",
            self.root / "bad%3Astream.txt",
        )
        for path in literal_paths:
            path.write_text("content", encoding="utf-8")

        for path in literal_paths:
            with self.subTest(path=path):
                payload = self.run_handler(location_uri(path))
                self.assertEqual("select-file", payload["action"])
                self.assert_path_equal(path, payload["path"])

    def test_environment_variable_text_remains_literal(self) -> None:
        literal_directory = self.root / "%CODEX_LOCATION_SENTINEL%"
        literal_directory.mkdir()
        expanded_directory = self.root / "expanded"
        expanded_directory.mkdir()

        payload = self.run_handler(
            location_uri(literal_directory),
            extra_environment={"CODEX_LOCATION_SENTINEL": str(expanded_directory)},
        )

        self.assertEqual("open-directory", payload["action"])
        self.assert_path_equal(literal_directory, payload["path"])

    def test_command_text_is_treated_as_path_without_side_effects(self) -> None:
        marker = self.root / "handler-side-effect.txt"
        injected_path = (
            f"{self.root}\\missing.txt; "
            "New-Item -ItemType File -Path handler-side-effect.txt"
        )

        payload = self.run_handler(location_uri(injected_path))

        self.assertEqual("open-parent", payload["action"])
        self.assert_path_equal(self.root, payload["path"])
        self.assertFalse(marker.exists())


class CodexLocationInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="codex-location-installer-")
        self.root = Path(self.temp_dir.name)
        self.install_root = self.root / "bin"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def expected_command(self, handler: Path) -> str:
        return (
            f'"{WINDOWS_POWERSHELL}" '
            "-NoProfile -NonInteractive -WindowStyle Hidden "
            f'-ExecutionPolicy Bypass -File "{handler}" -Uri "%1"'
        )

    def registry_state_arguments(
        self,
        state: dict[str, object],
    ) -> tuple[str, str]:
        return (
            "-DryRunRegistryStateJson",
            json.dumps(state, ensure_ascii=True, separators=(",", ":")),
        )

    def invoke_installer(
        self,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        self.assertTrue(INSTALLER.is_file(), msg=f"installer missing: {INSTALLER}")
        registry_before = registry_state_and_hash()
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(INSTALLER),
                *arguments,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        registry_after = registry_state_and_hash()
        self.assertEqual(registry_before, registry_after)
        return completed

    def parse_payload(
        self,
        completed: subprocess.CompletedProcess[str],
    ) -> dict[str, object]:
        lines = completed.stdout.strip().splitlines()
        self.assertEqual(1, len(lines), msg=completed.stdout)
        self.assertTrue(lines[0].startswith("{"), msg=completed.stdout)
        return json.loads(lines[0])

    def run_installer(self, *arguments: str) -> dict[str, object]:
        completed = self.invoke_installer(*arguments)
        self.assertEqual(
            0,
            completed.returncode,
            msg=f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}",
        )
        return self.parse_payload(completed)

    def test_install_dry_run_targets_temporary_install_root(self) -> None:
        payload = self.run_installer(
            "-DryRun",
            "-InstallRoot",
            str(self.install_root),
            *self.registry_state_arguments({"exists": False}),
        )

        self.assertEqual("Install", payload["mode"])
        self.assertIs(payload["dryRun"], True)
        self.assertEqual(
            self.install_root / "codex-location-handler.ps1",
            Path(payload["handler"]),
        )
        self.assertEqual(HANDLER, Path(payload["sourceHandler"]))
        self.assertEqual("create", payload["registrationAction"])
        self.assertFalse(self.install_root.exists())

    def test_install_dry_run_uses_default_current_user_target(self) -> None:
        payload = self.run_installer(
            "-DryRun",
            *self.registry_state_arguments({"exists": False}),
        )

        expected_handler = (
            Path(os.environ["USERPROFILE"])
            / ".codex"
            / "bin"
            / "codex-location-handler.ps1"
        )
        self.assertEqual(expected_handler, Path(payload["handler"]))

    def test_install_dry_run_has_exact_command_and_registry_values(self) -> None:
        payload = self.run_installer(
            "-DryRun",
            "-InstallRoot",
            str(self.install_root),
            *self.registry_state_arguments({"exists": False}),
        )
        expected_handler = self.install_root / "codex-location-handler.ps1"

        self.assertEqual(REGISTRY_KEY, payload["registryKey"])
        self.assertEqual(
            self.expected_command(expected_handler),
            payload["command"],
        )
        self.assertEqual(REGISTRY_DESCRIPTION, payload["description"])
        self.assertEqual("", payload["urlProtocol"])
        self.assertEqual(OWNER_NAME, payload["ownerName"])
        self.assertEqual(OWNER_VALUE, payload["ownerValue"])
        self.assertNotIn("HKLM", completed_text := json.dumps(payload))
        self.assertNotIn("HKEY_LOCAL_MACHINE", completed_text)

    def test_inspect_dry_run_reports_absent_key_without_other_configuration(
        self,
    ) -> None:
        payload = self.run_installer(
            "-Mode",
            "Inspect",
            "-DryRun",
            *self.registry_state_arguments({"exists": False}),
        )

        self.assertEqual(
            {
                "mode": "Inspect",
                "registryKey": REGISTRY_KEY,
                "exists": False,
                "owned": False,
            },
            payload,
        )

    def test_complete_registration_is_owned_and_can_be_updated(self) -> None:
        handler = self.install_root / "codex-location-handler.ps1"
        state = owned_registry_state(self.expected_command(handler))

        inspect_payload = self.run_installer(
            "-Mode",
            "Inspect",
            "-DryRun",
            "-InstallRoot",
            str(self.install_root),
            *self.registry_state_arguments(state),
        )
        install_payload = self.run_installer(
            "-DryRun",
            "-InstallRoot",
            str(self.install_root),
            *self.registry_state_arguments(state),
        )

        self.assertIs(inspect_payload["exists"], True)
        self.assertIs(inspect_payload["owned"], True)
        self.assertEqual("preserve", install_payload["registrationAction"])
        self.assertIs(install_payload["owned"], True)
        self.assertFalse(self.install_root.exists())

    def test_registration_drift_is_never_owned(self) -> None:
        handler = self.install_root / "codex-location-handler.ps1"
        expected_state = owned_registry_state(self.expected_command(handler))
        drifted_states: list[tuple[str, dict[str, object]]] = []

        missing_owner = copy.deepcopy(expected_state)
        missing_owner["tree"]["values"] = [
            value
            for value in missing_owner["tree"]["values"]
            if value["name"] != OWNER_NAME
        ]
        drifted_states.append(("missing-owner", missing_owner))

        wrong_description = copy.deepcopy(expected_state)
        wrong_description["tree"]["values"][0]["data"] = "External protocol"
        drifted_states.append(("wrong-description", wrong_description))

        wrong_url_protocol = copy.deepcopy(expected_state)
        wrong_url_protocol["tree"]["values"][1]["data"] = "present"
        drifted_states.append(("wrong-url-protocol", wrong_url_protocol))

        wrong_owner = copy.deepcopy(expected_state)
        wrong_owner["tree"]["values"][2]["data"] = "another-owner"
        drifted_states.append(("wrong-owner", wrong_owner))

        extra_value = copy.deepcopy(expected_state)
        extra_value["tree"]["values"].append(registry_value("Extra", "value"))
        drifted_states.append(("extra-root-value", extra_value))

        extra_subkey = copy.deepcopy(expected_state)
        extra_subkey["tree"]["subkeys"].append(
            named_registry_node("extra", registry_node())
        )
        drifted_states.append(("extra-root-subkey", extra_subkey))

        shell_value = copy.deepcopy(expected_state)
        shell_value["tree"]["subkeys"][0]["values"].append(
            registry_value("", "unexpected")
        )
        drifted_states.append(("shell-value", shell_value))

        wrong_command = copy.deepcopy(expected_state)
        wrong_command["tree"]["subkeys"][0]["subkeys"][0]["subkeys"][0][
            "values"
        ][0]["data"] = "different command"
        drifted_states.append(("wrong-command", wrong_command))

        command_subkey = copy.deepcopy(expected_state)
        command_subkey["tree"]["subkeys"][0]["subkeys"][0]["subkeys"][0][
            "subkeys"
        ].append(named_registry_node("extra", registry_node()))
        drifted_states.append(("command-subkey", command_subkey))

        for name, state in drifted_states:
            with self.subTest(name=name):
                payload = self.run_installer(
                    "-Mode",
                    "Inspect",
                    "-DryRun",
                    "-InstallRoot",
                    str(self.install_root),
                    *self.registry_state_arguments(state),
                )
                self.assertIs(payload["exists"], True)
                self.assertIs(payload["owned"], False)

    def test_install_dry_run_rejects_drifted_registration(self) -> None:
        handler = self.install_root / "codex-location-handler.ps1"
        state = owned_registry_state(self.expected_command(handler))
        state["tree"]["values"] = [
            value
            for value in state["tree"]["values"]
            if value["name"] != OWNER_NAME
        ]

        completed = self.invoke_installer(
            "-DryRun",
            "-InstallRoot",
            str(self.install_root),
            *self.registry_state_arguments(state),
        )

        self.assertNotEqual(0, completed.returncode)
        payload = self.parse_payload(completed)
        self.assertEqual("reject", payload["registrationAction"])
        self.assertIs(payload["owned"], False)
        self.assertFalse(self.install_root.exists())

    def test_uninstall_dry_run_refuses_unowned_registration(self) -> None:
        handler = self.install_root / "codex-location-handler.ps1"
        state = owned_registry_state(self.expected_command(handler))
        state["tree"]["values"] = [
            value
            for value in state["tree"]["values"]
            if value["name"] != OWNER_NAME
        ]

        completed = self.invoke_installer(
            "-Mode",
            "Uninstall",
            "-DryRun",
            "-InstallRoot",
            str(self.install_root),
            *self.registry_state_arguments(state),
        )

        self.assertNotEqual(0, completed.returncode)
        payload = self.parse_payload(completed)
        self.assertEqual("Uninstall", payload["mode"])
        self.assertIs(payload["exists"], True)
        self.assertIs(payload["owned"], False)
        self.assertIs(payload["removeRegistryKey"], False)
        self.assertFalse(self.install_root.exists())

    def test_uninstall_dry_run_accepts_exact_owned_registration(self) -> None:
        handler = self.install_root / "codex-location-handler.ps1"
        state = owned_registry_state(self.expected_command(handler))
        payload = self.run_installer(
            "-Mode",
            "Uninstall",
            "-DryRun",
            "-InstallRoot",
            str(self.install_root),
            *self.registry_state_arguments(state),
        )

        self.assertIs(payload["exists"], True)
        self.assertIs(payload["owned"], True)
        self.assertIs(payload["removeRegistryKey"], True)
        self.assertFalse(self.install_root.exists())

    def test_registry_state_override_requires_dry_run(self) -> None:
        completed = self.invoke_installer(
            "-Mode",
            "Inspect",
            "-DryRunRegistryStateJson",
            json.dumps({"exists": False}),
        )

        self.assertNotEqual(0, completed.returncode)
        self.assertEqual("", completed.stdout.strip())

    def test_custom_install_root_requires_dry_run(self) -> None:
        completed = self.invoke_installer(
            "-InstallRoot",
            str(self.install_root),
            "-SourceHandler",
            str(self.root / "missing-handler.ps1"),
        )

        self.assertNotEqual(0, completed.returncode)
        self.assertIn(
            "custom InstallRoot requires -DryRun",
            completed.stderr,
        )
        self.assertFalse(self.install_root.exists())

    def test_unsafe_install_roots_are_rejected(self) -> None:
        drive = self.root.drive or "C:"
        unsafe_roots = (
            r"\\server\share\codex-bin",
            r"\\?\C:\codex-bin",
            f"{drive}\\codex%bin",
            f'{drive}\\bad"name',
            f"{drive}\\bad\nname",
        )

        for install_root in unsafe_roots:
            with self.subTest(install_root=install_root):
                completed = self.invoke_installer(
                    "-DryRun",
                    "-InstallRoot",
                    install_root,
                    *self.registry_state_arguments({"exists": False}),
                )
                self.assertNotEqual(0, completed.returncode)
                self.assertIn(
                    "trusted local fixed-drive path",
                    completed.stderr,
                )

    def create_junction(self, junction: Path, target: Path) -> None:
        environment = os.environ.copy()
        environment["CODEX_TEST_JUNCTION"] = str(junction)
        environment["CODEX_TEST_TARGET"] = str(target)
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "New-Item -ItemType Junction "
                    "-Path $env:CODEX_TEST_JUNCTION "
                    "-Target $env:CODEX_TEST_TARGET | Out-Null"
                ),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )
        self.assertEqual(
            0,
            completed.returncode,
            msg=f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}",
        )

    def test_reparse_install_root_and_source_are_rejected(self) -> None:
        target = self.root / "junction-target"
        target.mkdir()
        source = target / "source-handler.ps1"
        source.write_text("source", encoding="utf-8")
        junction = self.root / "junction"
        self.create_junction(junction, target)

        install_completed = self.invoke_installer(
            "-DryRun",
            "-InstallRoot",
            str(junction / "bin"),
            *self.registry_state_arguments({"exists": False}),
        )
        source_completed = self.invoke_installer(
            "-DryRun",
            "-InstallRoot",
            str(self.install_root),
            "-SourceHandler",
            str(junction / "source-handler.ps1"),
            *self.registry_state_arguments({"exists": False}),
        )

        self.assertNotEqual(0, install_completed.returncode)
        self.assertIn("reparse point", install_completed.stderr.lower())
        self.assertNotEqual(0, source_completed.returncode)
        self.assertIn("reparse point", source_completed.stderr.lower())
        self.assertFalse(self.install_root.exists())

    def invoke_file_transaction_probe(
        self,
        source: Path,
        handler: Path,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["CODEX_TEST_INSTALLER"] = str(INSTALLER)
        environment["CODEX_TEST_SOURCE"] = str(source)
        environment["CODEX_TEST_HANDLER"] = str(handler)
        command = r"""
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:CODEX_TEST_INSTALLER,
    [ref] $tokens,
    [ref] $errors
)
$functionAst = $ast.Find({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-CodexHandlerFileTransaction"
}, $true)
if ($null -eq $functionAst) {
    throw "Transaction function is missing."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$caughtInjectedFailure = $false
$failureMessage = $null
try {
    Invoke-CodexHandlerFileTransaction `
        -SourceHandlerPath $env:CODEX_TEST_SOURCE `
        -HandlerPath $env:CODEX_TEST_HANDLER `
        -CommitAction { throw "Injected registration failure." }
}
catch {
    $failureMessage = $_.Exception.Message
    $caughtInjectedFailure = $_.Exception.Message.Contains(
        "Injected registration failure."
    )
}

$handlerDirectory = [IO.Path]::GetDirectoryName($env:CODEX_TEST_HANDLER)
[object[]] $temporaryFiles = @(
    Get-ChildItem -LiteralPath $handlerDirectory -Force |
        Where-Object {
            $_.Name -like ".codex-location-handler.*"
        } |
        ForEach-Object { $_.Name }
)
$result = [ordered] @{
    caughtInjectedFailure = $caughtInjectedFailure
    failureMessage = $failureMessage
    handlerExists = [IO.File]::Exists($env:CODEX_TEST_HANDLER)
    handlerContent = if ([IO.File]::Exists($env:CODEX_TEST_HANDLER)) {
        [IO.File]::ReadAllText($env:CODEX_TEST_HANDLER)
    } else {
        $null
    }
    temporaryFiles = $temporaryFiles
}
[Console]::Out.WriteLine(($result | ConvertTo-Json -Compress))
"""
        registry_before = registry_state_and_hash()
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )
        registry_after = registry_state_and_hash()
        self.assertEqual(registry_before, registry_after)
        return completed

    def test_file_transaction_rolls_back_after_commit_failure(self) -> None:
        for existing_content in ("old handler", None):
            with self.subTest(existing_content=existing_content):
                case_root = self.root / (
                    "existing" if existing_content is not None else "new"
                )
                source = case_root / "source.ps1"
                handler = case_root / "bin" / "codex-location-handler.ps1"
                source.parent.mkdir(parents=True)
                handler.parent.mkdir(parents=True)
                source.write_text("new handler", encoding="utf-8")
                if existing_content is not None:
                    handler.write_text(existing_content, encoding="utf-8")

                completed = self.invoke_file_transaction_probe(source, handler)

                self.assertEqual(
                    0,
                    completed.returncode,
                    msg=f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}",
                )
                payload = self.parse_payload(completed)
                self.assertIs(
                    payload["caughtInjectedFailure"],
                    True,
                    msg=payload["failureMessage"],
                )
                self.assertEqual(
                    existing_content is not None,
                    payload["handlerExists"],
                )
                self.assertEqual(existing_content, payload["handlerContent"])
                self.assertEqual([], payload["temporaryFiles"])

    def test_installer_does_not_use_shell_evaluation_or_machine_registry(
        self,
    ) -> None:
        self.assertTrue(INSTALLER.is_file(), msg=f"installer missing: {INSTALLER}")
        source = INSTALLER.read_text(encoding="utf-8").lower()

        self.assertNotIn("invoke-expression", source)
        self.assertNotIn("cmd.exe", source)
        self.assertNotIn("hkey_local_machine", source)
        self.assertNotIn("hklm", source)
        self.assertIn("$pshome", source)
        self.assertIn(OWNER_NAME.lower(), source)
        self.assertIn(OWNER_VALUE.lower(), source)
        self.assertNotIn(
            "new-item -path $registryproviderpath -force",
            " ".join(source.split()),
        )


if __name__ == "__main__":
    unittest.main()
