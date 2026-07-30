# Preset Overwrite Repair Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent detached runtime configuration from overwriting a selected provider preset and safely restore the affected local preset.

**Architecture:** Make the Accounts dialog use the selected preset as its single form data source. Build and validate apply candidates in memory, then persist only after successful validation while restoring transient proxy state on errors.

**Tech Stack:** Python 3, Tkinter, `unittest`, JSON settings helpers

---

### Task 1: Reproduce The Form Mismatch

**Files:**
- Create: `tests/test_preset_application.py`
- Test: `tests/test_preset_application.py`

**Step 1: Write the failing test**

Add a test whose settings contain unrelated detached top-level provider values
and a different active preset. Assert that `openai_account_form_values()` returns
the active preset's URL, key, model, model list, protocol, and proxy preference.

**Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest tests.test_preset_application.PresetApplicationTests.test_form_values_follow_active_preset_when_runtime_is_detached -v
```

Expected: FAIL because the helper currently returns the detached top-level
values whenever a top-level API key exists.

### Task 2: Reproduce Pre-Validation Mutation

**Files:**
- Modify: `tests/test_preset_application.py`
- Test: `tests/test_preset_application.py`

**Step 1: Write the failing test**

Create a temporary settings file with a current preset and a different target
preset. Mock provider validation to raise an error, invoke preset application
with edited target values, and assert:

- The settings file bytes are unchanged.
- The active preset is unchanged.
- The process proxy preference is restored.

**Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest tests.test_preset_application.PresetApplicationTests.test_validation_failure_does_not_mutate_settings -v
```

Expected: FAIL because the current implementation saves and activates the target
preset before validation.

### Task 3: Correct The Form Data Source

**Files:**
- Modify: `app.py`
- Test: `tests/test_preset_application.py`

**Step 1: Implement the minimal fix**

Update `openai_account_form_values()` so an existing active preset overlays the
top-level runtime values even when the detached runtime configuration has an API
key.

**Step 2: Run the focused form test**

Run:

```powershell
python -m unittest tests.test_preset_application.PresetApplicationTests.test_form_values_follow_active_preset_when_runtime_is_detached -v
```

Expected: PASS.

### Task 4: Validate Before Writing

**Files:**
- Modify: `app.py`
- Test: `tests/test_preset_application.py`
- Test: `tests/test_proxy_routing.py`

**Step 1: Implement the minimal transaction change**

Build candidate preset fields in memory. Validate the candidate before calling
any settings writer. Restore the prior proxy preference if validation raises.
After success, save the backend and selected preset with the resolved values.

**Step 2: Run focused tests**

Run:

```powershell
python -m unittest tests.test_preset_application tests.test_proxy_routing -v
```

Expected: PASS.

### Task 5: Restore The Local Preset

**Files:**
- Back up: `%USERPROFILE%\.codex\token_pool_settings.json`
- Modify locally: `%USERPROFILE%\.codex\token_pool_settings.json`

**Step 1: Create a timestamped private backup**

Copy the settings file into a timestamped directory under
`%USERPROFILE%\.codex\private_backups`.

**Step 2: Recover only the affected preset**

Use prior local session evidence supplied by the user to restore the affected
preset's URL, key, model, protocol, proxy preference, and discovered models.
Do not print those values.

**Step 3: Verify with hashes and non-secret metadata**

Confirm the recovered preset no longer shares URL/key hashes with the unrelated
preset, and confirm all other preset objects are unchanged.

### Task 6: Full Verification

**Files:**
- Verify: `app.py`
- Verify: `tests/test_preset_application.py`
- Verify: repository contents

**Step 1: Run the complete test suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass.

**Step 2: Compile modified Python files**

Run:

```powershell
python -m py_compile app.py tests\test_preset_application.py
```

Expected: exit code 0.

**Step 3: Check for private values**

Scan tracked changes for provider URLs, API keys, installation IDs, and local
configuration paths. Expected: no private provider values in tracked files.

**Step 4: Review repository state**

Run:

```powershell
git status --short --branch
git diff --check
```

Expected: only the intended source, test, and plan files are modified.
