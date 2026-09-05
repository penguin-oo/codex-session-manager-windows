# Models-Only Preset Validation Design

## Goal

Replace the hidden `skip_validation` behavior with a visible `models_only_validation` option in the desktop and mobile API preset interfaces. When enabled, refresh, save, and apply operations validate credentials only by retrieving a non-empty model list and never send a conversation request.

## User Experience

Both interfaces expose a checkbox labelled `Only fetch models (do not test a conversation)`. Its value is loaded from the selected preset and saved with that preset.

When enabled:

- Refresh, save, and apply use only the provider's models endpoint.
- The operation succeeds when at least one model ID is returned.
- Network, authentication, malformed-response, and empty-list failures are shown as errors.
- No configuration or active-preset change is persisted when validation fails.
- The existing model remains selected when it is still returned.
- Otherwise `gpt-5.6-sol` is preferred, followed by the first returned model.
- The configured protocol is preserved and no protocol probe is performed.

When disabled, the existing full Responses/Chat Completions validation remains unchanged.

## Architecture

`token_pool_settings.py` owns a shared models-only resolver. It normalizes the Base URL, fetches `/models` (including the existing automatic `/v1` handling), requires a non-empty list, and selects a model without issuing POST requests.

Preset normalization and top-level synchronization persist `models_only_validation`. Legacy `skip_validation` is accepted only as a migration source so old presets retain their intent, but new writes use the explicit field and do not preserve the hidden bypass behavior.

Desktop services in `app.py` and mobile services in `mobile_portal.py` choose between the models-only resolver and the existing full resolver. Each operation validates first and writes only after success. UI controls pass the explicit value through every refresh, save, and apply path.

## Error Handling

Validation errors propagate to the existing desktop dialog or mobile JSON error response. Save and apply stage all input in memory, perform validation, and only then write the settings file. Applying a preset must not switch the active preset before validation succeeds.

## Testing

Automated tests cover:

- Models-only resolution never calls protocol detection or another POST path.
- Empty model results fail.
- Existing model, `gpt-5.6-sol`, and first-model selection precedence.
- Preset field persistence and legacy migration.
- Desktop save and apply pass the option through and preserve files on failure.
- Mobile save and apply pass the option through and preserve files on failure.
- Desktop and mobile markup expose the visible control.
