package com.penguinoo.codexmobile;

import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.AppCompatButton;
import androidx.core.content.ContextCompat;

public final class AccountCenterDialogSupport {
    public interface Callbacks {
        void onRefresh();
        void onCreateSlot();
        void onBindCurrent(AccountSlotSummary slot);
        void onSwitch(AccountSlotSummary slot);
        void onRename(AccountSlotSummary slot);
        void onDelete(AccountSlotSummary slot);
        void onUseCodexAuth(BackendStatusPayload backend);
        void onUseTokenPool(BackendStatusPayload backend);
        void onConfigureOpenAi(BackendStatusPayload backend);
        void onStartBackend();
        void onStopBackend();
        void onRestartBackend();
    }

    public interface OpenAiConfigListener {
        void onSave(String baseUrl, String apiKey, String model);
    }

    private enum ButtonTone {
        ACCENT,
        SOFT,
        DANGER
    }

    private static final class ActionSpec {
        final int textRes;
        final View.OnClickListener listener;
        final boolean enabled;
        final ButtonTone tone;

        ActionSpec(int textRes, View.OnClickListener listener, boolean enabled, ButtonTone tone) {
            this.textRes = textRes;
            this.listener = listener;
            this.enabled = enabled;
            this.tone = tone;
        }
    }

    private AccountCenterDialogSupport() {
    }

    public static void show(
            AppCompatActivity activity,
            AccountSlotsPayload payload,
            Callbacks callbacks
    ) {
        final AlertDialog[] dialogRef = new AlertDialog[1];

        int outer = dp(activity, 20);
        int sectionGap = dp(activity, 18);
        int cardGap = dp(activity, 12);

        ScrollView scrollView = new ScrollView(activity);
        scrollView.setFillViewport(true);
        LinearLayout container = new LinearLayout(activity);
        container.setOrientation(LinearLayout.VERTICAL);
        container.setPadding(outer, outer, outer, outer);
        scrollView.addView(container, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        addSectionLabel(activity, container, activity.getString(R.string.label_current_login_title));
        container.addView(buildCurrentAccountCard(activity, payload));

        if (payload.backend != null) {
            addSpacer(activity, container, sectionGap);
            addSectionLabel(activity, container, activity.getString(R.string.label_backend_title));
            container.addView(buildBackendCard(activity, payload.backend, callbacks, dialogRef));
        }

        addSpacer(activity, container, sectionGap);
        addSectionLabel(activity, container, activity.getString(R.string.label_saved_slots_title));
        if (payload.slots == null || payload.slots.isEmpty()) {
            container.addView(buildEmptySlotsCard(activity, callbacks, dialogRef));
        } else {
            for (AccountSlotSummary slot : payload.slots) {
                container.addView(buildSlotCard(activity, slot, callbacks, dialogRef));
                addSpacer(activity, container, cardGap);
            }
        }

        LinearLayout footer = buildActionGrid(
                activity,
                new ActionSpec(R.string.action_new_slot, view -> {
                    dismiss(dialogRef);
                    callbacks.onCreateSlot();
                }, true, ButtonTone.ACCENT),
                new ActionSpec(R.string.action_refresh_accounts, view -> {
                    dismiss(dialogRef);
                    callbacks.onRefresh();
                }, true, ButtonTone.SOFT)
        );
        footer.setPadding(0, dp(activity, 4), 0, 0);
        container.addView(footer);

        dialogRef[0] = new AlertDialog.Builder(activity)
                .setTitle(R.string.title_accounts)
                .setView(scrollView)
                .setNegativeButton(android.R.string.cancel, null)
                .show();
        if (dialogRef[0].getWindow() != null) {
            int width = (int) (activity.getResources().getDisplayMetrics().widthPixels * 0.96f);
            dialogRef[0].getWindow().setLayout(width, ViewGroup.LayoutParams.WRAP_CONTENT);
        }
    }

    private static View buildCurrentAccountCard(AppCompatActivity activity, AccountSlotsPayload payload) {
        LinearLayout card = buildCard(activity, R.color.bg_card_active, R.color.accent_main);
        String activeSlotLabel = resolveActiveSlotLabel(payload);

        TextView heading = buildCardHeading(activity, activity.getString(R.string.label_current_login_title));
        TextView body = buildBodyText(
                activity,
                AccountCenterPresentation.currentAccountSummary(
                        payload,
                        activity.getString(R.string.label_account_unbound),
                        activity.getString(R.string.label_quota_unavailable),
                        activeSlotLabel
                ),
                true
        );
        TextView hint = buildMutedText(activity, activity.getString(R.string.label_account_center_hint));
        hint.setPadding(0, dp(activity, 12), 0, 0);

        card.addView(heading);
        card.addView(body);
        card.addView(hint);
        return card;
    }

    private static View buildBackendCard(
            AppCompatActivity activity,
            BackendStatusPayload backend,
            Callbacks callbacks,
            AlertDialog[] dialogRef
    ) {
        LinearLayout card = buildCard(activity, R.color.bg_card, R.color.stroke_soft);
        card.addView(buildCardHeading(activity, activity.getString(R.string.label_backend_title)));
        card.addView(buildBodyText(
                activity,
                AccountCenterPresentation.backendSummary(
                        backend,
                        activity.getString(R.string.label_backend_running),
                        activity.getString(R.string.label_backend_stopped)
                ),
                false
        ));

        LinearLayout actions = buildActionGrid(
                activity,
                new ActionSpec(
                        R.string.action_use_current_login,
                        view -> {
                            dismiss(dialogRef);
                            callbacks.onUseCodexAuth(backend);
                        },
                        !backend.isCodexAuthMode(),
                        ButtonTone.ACCENT
                ),
                new ActionSpec(
                        R.string.action_use_token_pool,
                        view -> {
                            dismiss(dialogRef);
                            callbacks.onUseTokenPool(backend);
                        },
                        !backend.isTokenPoolMode(),
                        ButtonTone.SOFT
                ),
                new ActionSpec(R.string.action_openai_backend, view -> {
                    dismiss(dialogRef);
                    callbacks.onConfigureOpenAi(backend);
                }, true, ButtonTone.SOFT),
                new ActionSpec(R.string.action_refresh_accounts, view -> {
                    dismiss(dialogRef);
                    callbacks.onRefresh();
                }, true, ButtonTone.SOFT),
                new ActionSpec(R.string.action_start_backend, view -> {
                    dismiss(dialogRef);
                    callbacks.onStartBackend();
                }, backend.isTokenPoolMode(), ButtonTone.SOFT),
                new ActionSpec(R.string.action_restart_backend, view -> {
                    dismiss(dialogRef);
                    callbacks.onRestartBackend();
                }, backend.isTokenPoolMode(), ButtonTone.SOFT),
                new ActionSpec(R.string.action_stop_backend, view -> {
                    dismiss(dialogRef);
                    callbacks.onStopBackend();
                }, backend.isTokenPoolMode(), ButtonTone.DANGER)
        );
        actions.setPadding(0, dp(activity, 12), 0, 0);
        card.addView(actions);
        return card;
    }

    public static void promptOpenAiBackendConfig(
            AppCompatActivity activity,
            BackendStatusPayload backend,
            OpenAiConfigListener listener
    ) {
        ScrollView scrollView = new ScrollView(activity);
        LinearLayout container = new LinearLayout(activity);
        container.setOrientation(LinearLayout.VERTICAL);
        int horizontalPadding = dp(activity, 20);
        int verticalPadding = dp(activity, 12);
        container.setPadding(horizontalPadding, verticalPadding, horizontalPadding, 0);
        scrollView.addView(container, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        TextView hintView = new TextView(activity);
        hintView.setText(
                backend.hasOpenAiApiKey
                        ? R.string.message_openai_backend_hint_saved_key
                        : R.string.message_openai_backend_hint
        );
        container.addView(hintView);

        EditText baseUrlInput = new EditText(activity);
        baseUrlInput.setHint(R.string.hint_openai_base_url);
        String initialBaseUrl = backend.openaiBaseUrl == null || backend.openaiBaseUrl.trim().isEmpty()
                ? "https://api.openai.com/v1"
                : backend.openaiBaseUrl.trim();
        baseUrlInput.setText(initialBaseUrl);
        baseUrlInput.setSelection(baseUrlInput.getText().length());
        baseUrlInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        container.addView(baseUrlInput);

        EditText apiKeyInput = new EditText(activity);
        apiKeyInput.setHint(backend.hasOpenAiApiKey
                ? R.string.hint_openai_api_key_keep_saved
                : R.string.hint_openai_api_key);
        apiKeyInput.setInputType(
                InputType.TYPE_CLASS_TEXT
                        | InputType.TYPE_TEXT_VARIATION_PASSWORD
                        | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        );
        container.addView(apiKeyInput);

        EditText modelInput = new EditText(activity);
        modelInput.setHint(R.string.hint_openai_model);
        String initialModel = backend.openaiModel == null || backend.openaiModel.trim().isEmpty()
                ? (backend.openaiModels.isEmpty() ? "gpt-5.5" : backend.openaiModels.get(0))
                : backend.openaiModel.trim();
        modelInput.setText(initialModel);
        modelInput.setSelection(modelInput.getText().length());
        modelInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        container.addView(modelInput);

        if (!backend.openaiModels.isEmpty()) {
            TextView knownModelsView = new TextView(activity);
            knownModelsView.setPadding(0, dp(activity, 12), 0, 0);
            knownModelsView.setText(activity.getString(
                    R.string.label_openai_known_models,
                    joinValues(backend.openaiModels)
            ));
            container.addView(knownModelsView);
        }

        new AlertDialog.Builder(activity)
                .setTitle(R.string.title_openai_backend)
                .setView(scrollView)
                .setPositiveButton(R.string.action_save, (dialog, which) -> listener.onSave(
                        valueOf(baseUrlInput),
                        valueOf(apiKeyInput),
                        valueOf(modelInput)
                ))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private static View buildEmptySlotsCard(
            AppCompatActivity activity,
            Callbacks callbacks,
            AlertDialog[] dialogRef
    ) {
        LinearLayout card = buildCard(activity, R.color.bg_card, R.color.stroke_soft);
        card.addView(buildCardHeading(activity, activity.getString(R.string.label_no_saved_slots_title)));
        card.addView(buildBodyText(activity, activity.getString(R.string.label_no_saved_slots), false));
        LinearLayout actions = buildActionGrid(
                activity,
                new ActionSpec(R.string.action_new_slot, view -> {
                    dismiss(dialogRef);
                    callbacks.onCreateSlot();
                }, true, ButtonTone.ACCENT),
                new ActionSpec(R.string.action_refresh_accounts, view -> {
                    dismiss(dialogRef);
                    callbacks.onRefresh();
                }, true, ButtonTone.SOFT)
        );
        actions.setPadding(0, dp(activity, 12), 0, 0);
        card.addView(actions);
        return card;
    }

    private static View buildSlotCard(
            AppCompatActivity activity,
            AccountSlotSummary slot,
            Callbacks callbacks,
            AlertDialog[] dialogRef
    ) {
        LinearLayout card = buildCard(
                activity,
                slot.active ? R.color.bg_card_active : R.color.bg_card,
                slot.active ? R.color.accent_main : R.color.stroke_soft
        );
        card.addView(buildCardHeading(activity, AccountCenterPresentation.slotDisplayName(slot)));
        card.addView(buildChipRow(activity, slot));
        TextView summary = buildBodyText(
                activity,
                AccountCenterPresentation.slotSummary(
                        slot,
                        activity.getString(R.string.label_account_unbound),
                        activity.getString(R.string.label_account_active),
                        activity.getString(R.string.label_slot_ready_to_switch),
                        activity.getString(R.string.label_slot_bind_hint)
                ),
                false
        );
        summary.setPadding(0, dp(activity, 12), 0, 0);
        card.addView(summary);

        LinearLayout actions = buildActionGrid(
                activity,
                new ActionSpec(R.string.action_bind_current_here, view -> {
                    dismiss(dialogRef);
                    callbacks.onBindCurrent(slot);
                }, true, ButtonTone.ACCENT),
                new ActionSpec(R.string.action_switch_here, view -> {
                    dismiss(dialogRef);
                    callbacks.onSwitch(slot);
                }, AccountCenterPresentation.canSwitch(slot), ButtonTone.SOFT),
                new ActionSpec(R.string.action_rename, view -> {
                    dismiss(dialogRef);
                    callbacks.onRename(slot);
                }, true, ButtonTone.SOFT),
                new ActionSpec(R.string.action_delete, view -> {
                    dismiss(dialogRef);
                    callbacks.onDelete(slot);
                }, true, ButtonTone.DANGER)
        );
        actions.setPadding(0, dp(activity, 14), 0, 0);
        card.addView(actions);
        return card;
    }

    private static LinearLayout buildChipRow(AppCompatActivity activity, AccountSlotSummary slot) {
        LinearLayout row = new LinearLayout(activity);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, dp(activity, 10), 0, 0);
        row.addView(buildChip(
                activity,
                slot.bound ? activity.getString(R.string.label_slot_bound_chip) : activity.getString(R.string.label_slot_unbound_chip),
                slot.bound ? R.color.accent_main : R.color.accent_warn,
                slot.bound ? R.color.bg_panel : R.color.bg_panel
        ));
        if (slot.active) {
            View spacer = new View(activity);
            spacer.setLayoutParams(new LinearLayout.LayoutParams(dp(activity, 8), 1));
            row.addView(spacer);
            row.addView(buildChip(
                    activity,
                    activity.getString(R.string.label_account_active),
                    R.color.white,
                    R.color.bg_user
            ));
        }
        return row;
    }

    private static TextView buildChip(AppCompatActivity activity, String text, int textColorRes, int backgroundColorRes) {
        TextView chip = new TextView(activity);
        chip.setText(text);
        chip.setTextSize(12f);
        chip.setTypeface(Typeface.DEFAULT_BOLD);
        chip.setTextColor(ContextCompat.getColor(activity, textColorRes));
        chip.setPadding(dp(activity, 10), dp(activity, 5), dp(activity, 10), dp(activity, 5));
        GradientDrawable background = new GradientDrawable();
        background.setCornerRadius(dp(activity, 999));
        background.setColor(ContextCompat.getColor(activity, backgroundColorRes));
        chip.setBackground(background);
        return chip;
    }

    private static LinearLayout buildCard(AppCompatActivity activity, int backgroundColorRes, int strokeColorRes) {
        LinearLayout card = new LinearLayout(activity);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(activity, 16), dp(activity, 16), dp(activity, 16), dp(activity, 16));
        GradientDrawable background = new GradientDrawable();
        background.setCornerRadius(dp(activity, 22));
        background.setColor(ContextCompat.getColor(activity, backgroundColorRes));
        background.setStroke(dp(activity, 1), ContextCompat.getColor(activity, strokeColorRes));
        card.setBackground(background);
        return card;
    }

    private static LinearLayout buildActionGrid(AppCompatActivity activity, ActionSpec... specs) {
        LinearLayout grid = new LinearLayout(activity);
        grid.setOrientation(LinearLayout.VERTICAL);
        for (int index = 0; index < specs.length; index += 2) {
            LinearLayout row = new LinearLayout(activity);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(0, index == 0 ? 0 : dp(activity, 8), 0, 0);
            row.addView(buildActionButton(activity, specs[index], true));
            if (index + 1 < specs.length) {
                View gap = new View(activity);
                gap.setLayoutParams(new LinearLayout.LayoutParams(dp(activity, 10), 1));
                row.addView(gap);
                row.addView(buildActionButton(activity, specs[index + 1], true));
            } else {
                View filler = new View(activity);
                filler.setLayoutParams(new LinearLayout.LayoutParams(0, 1, 1f));
                row.addView(filler);
            }
            grid.addView(row);
        }
        return grid;
    }

    private static AppCompatButton buildActionButton(AppCompatActivity activity, ActionSpec spec, boolean weighted) {
        AppCompatButton button = new AppCompatButton(activity);
        button.setAllCaps(false);
        button.setText(spec.textRes);
        button.setTextSize(14f);
        button.setTypeface(Typeface.DEFAULT_BOLD);
        button.setPadding(dp(activity, 12), dp(activity, 12), dp(activity, 12), dp(activity, 12));
        button.setEnabled(spec.enabled);
        button.setOnClickListener(spec.listener);
        button.setTextColor(resolveButtonTextColor(activity, spec));
        button.setBackground(buildButtonBackground(activity, spec, spec.enabled));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                weighted ? 0 : ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                weighted ? 1f : 0f
        );
        button.setLayoutParams(params);
        return button;
    }

    private static GradientDrawable buildButtonBackground(AppCompatActivity activity, ActionSpec spec, boolean enabled) {
        GradientDrawable background = new GradientDrawable();
        background.setCornerRadius(dp(activity, 16));
        int fillColor;
        int strokeColor;
        if (!enabled) {
            fillColor = ContextCompat.getColor(activity, R.color.bg_panel);
            strokeColor = ContextCompat.getColor(activity, R.color.stroke_soft);
        } else if (spec.tone == ButtonTone.ACCENT) {
            fillColor = ContextCompat.getColor(activity, R.color.accent_main);
            strokeColor = fillColor;
        } else if (spec.tone == ButtonTone.DANGER) {
            fillColor = ContextCompat.getColor(activity, R.color.bg_panel);
            strokeColor = ContextCompat.getColor(activity, R.color.danger_main);
        } else {
            fillColor = ContextCompat.getColor(activity, R.color.bg_panel_alt);
            strokeColor = ContextCompat.getColor(activity, R.color.stroke_soft);
        }
        background.setColor(fillColor);
        background.setStroke(dp(activity, 1), strokeColor);
        return background;
    }

    private static int resolveButtonTextColor(AppCompatActivity activity, ActionSpec spec) {
        if (!spec.enabled) {
            return ContextCompat.getColor(activity, R.color.text_muted);
        }
        if (spec.tone == ButtonTone.ACCENT) {
            return ContextCompat.getColor(activity, R.color.bg_panel);
        }
        if (spec.tone == ButtonTone.DANGER) {
            return ContextCompat.getColor(activity, R.color.danger_main);
        }
        return ContextCompat.getColor(activity, R.color.text_main);
    }

    private static TextView buildCardHeading(AppCompatActivity activity, String text) {
        TextView view = new TextView(activity);
        view.setText(text);
        view.setTextSize(17f);
        view.setTypeface(Typeface.DEFAULT_BOLD);
        view.setTextColor(ContextCompat.getColor(activity, R.color.text_main));
        return view;
    }

    private static TextView buildBodyText(AppCompatActivity activity, String text, boolean emphasize) {
        TextView view = new TextView(activity);
        view.setText(text);
        view.setTextSize(14f);
        view.setLineSpacing(0f, 1.16f);
        view.setTextColor(ContextCompat.getColor(activity, emphasize ? R.color.text_main : R.color.text_muted));
        view.setPadding(0, dp(activity, 10), 0, 0);
        return view;
    }

    private static TextView buildMutedText(AppCompatActivity activity, String text) {
        TextView view = new TextView(activity);
        view.setText(text);
        view.setTextSize(13f);
        view.setLineSpacing(0f, 1.14f);
        view.setTextColor(ContextCompat.getColor(activity, R.color.text_muted));
        return view;
    }

    private static void addSectionLabel(AppCompatActivity activity, LinearLayout container, String text) {
        TextView label = new TextView(activity);
        label.setText(text);
        label.setTextSize(13f);
        label.setTypeface(Typeface.DEFAULT_BOLD);
        label.setTextColor(ContextCompat.getColor(activity, R.color.accent_main));
        container.addView(label);
    }

    private static void addSpacer(AppCompatActivity activity, LinearLayout container, int height) {
        View spacer = new View(activity);
        spacer.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                height
        ));
        container.addView(spacer);
    }

    private static void dismiss(AlertDialog[] dialogRef) {
        if (dialogRef == null || dialogRef.length == 0) {
            return;
        }
        AlertDialog dialog = dialogRef[0];
        if (dialog != null) {
            dialog.dismiss();
        }
    }

    private static String resolveActiveSlotLabel(AccountSlotsPayload payload) {
        if (payload == null || payload.slots == null) {
            return "";
        }
        for (AccountSlotSummary slot : payload.slots) {
            if (slot == null) {
                continue;
            }
            if (slot.active) {
                return AccountCenterPresentation.slotDisplayName(slot);
            }
            if (payload.activeSlot != null && payload.activeSlot.equals(slot.slotId)) {
                return AccountCenterPresentation.slotDisplayName(slot);
            }
        }
        return "";
    }

    private static int dp(AppCompatActivity activity, int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }

    private static String valueOf(EditText input) {
        return input.getText() == null ? "" : input.getText().toString().trim();
    }

    private static String joinValues(java.util.List<String> values) {
        StringBuilder builder = new StringBuilder();
        for (String value : values) {
            if (value == null || value.trim().isEmpty()) {
                continue;
            }
            if (builder.length() > 0) {
                builder.append(", ");
            }
            builder.append(value.trim());
        }
        return builder.toString();
    }
}
