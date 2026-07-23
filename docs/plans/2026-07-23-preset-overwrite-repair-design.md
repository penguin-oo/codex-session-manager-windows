# Preset Overwrite Repair Design

## Problem

Desktop window isolation allows the top-level OpenAI-compatible configuration
to be detached from the selected preset. The Accounts dialog currently labels
the active preset in its selector while preferring detached top-level values
for the editable fields. Applying the form then saves those unrelated values
into the selected preset.

The apply flow also writes the edited preset and marks it active before endpoint
validation finishes. A validation error can therefore leave both the preset and
the active configuration partially changed.

## Approved Behavior

1. The preset selector and every editable provider field must describe the same
   preset.
2. Edited values must still be applied directly when the user clicks
   **Apply Preset**.
3. A preset that skips validation must keep its current behavior.
4. A preset that requires validation must not change the settings file until
   validation succeeds.
5. A failed validation must restore the in-memory proxy preference and leave the
   settings file byte-for-byte unchanged.
6. Local preset recovery must be backed up and must never place provider URLs or
   credentials in the repository.

## Design

### Form Data Source

`openai_account_form_values()` will prefer the active preset whenever that
preset exists. Detached top-level values remain available as the runtime launch
configuration, but they are not presented as fields for a differently named
preset.

Selecting another preset already refreshes the fields from that preset. The
initial dialog refresh will now follow the same rule.

### Validation Before Persistence

`SessionManagerApp._apply_openai_compatible_preset_settings()` will build a
candidate configuration entirely in memory from the selected preset and current
form edits.

For validated presets, it will:

1. Temporarily activate the candidate network proxy preference.
2. Validate and normalize the candidate provider configuration.
3. Restore the previous proxy preference if validation fails.
4. Persist and activate the candidate only after validation succeeds.

For presets that skip validation, it will immediately use the in-memory
candidate without making a network request.

### Local Recovery

The current local settings file will be copied to a timestamped private backup.
The overwritten preset will then be restored from the user's supplied local
screenshot and prior local session evidence. Recovery will modify only that
preset and will preserve all other presets and detached runtime state.

## Tests

Regression tests will cover:

- An active preset winning over unrelated detached top-level form values.
- A validation exception leaving the settings file unchanged.
- A validation exception restoring the previous in-memory proxy preference.
- Existing successful apply behavior, including edited model, protocol, proxy,
  and image-generation settings.

The focused tests will run first, followed by the complete Python test suite and
a repository scan confirming that no local provider values were added.
