package com.penguinoo.codexmobile;

public final class AccountCenterPresentation {
    private AccountCenterPresentation() {
    }

    public static String currentAccountSummary(
            AccountSlotsPayload payload,
            String unboundLabel,
            String quotaUnavailableLabel,
            String activeSlotLabel
    ) {
        String identity = firstNonBlank(payload.currentEmail, payload.currentAccountId, unboundLabel);
        StringBuilder summary = new StringBuilder(identity);
        if (!isBlank(payload.currentAuthMode)) {
            summary.append("\nMode: ").append(payload.currentAuthMode.trim());
        }
        if (!isBlank(activeSlotLabel)) {
            summary.append("\nActive slot: ").append(activeSlotLabel.trim());
        }
        summary.append("\n").append(firstNonBlank(payload.quotaSummary, quotaUnavailableLabel));
        return summary.toString();
    }

    public static String backendSummary(
            BackendStatusPayload backend,
            String runningLabel,
            String stoppedLabel
    ) {
        String mode = firstNonBlank(backend.backendMode, "codex_auth");
        String proxy = firstNonBlank(backend.proxySummary, backend.proxyRunning ? runningLabel : stoppedLabel);
        StringBuilder summary = new StringBuilder();
        summary.append("Mode: ").append(mode);
        summary.append("\nProxy: ").append(proxy);
        summary.append("\nToken files: ").append(Math.max(backend.tokenCount, 0));
        if (backend.isOpenAiCompatibleMode()) {
            summary.append("\nBase URL: ").append(firstNonBlank(backend.openaiBaseUrl, "https://api.openai.com/v1"));
            if (!isBlank(backend.openaiModel)) {
                summary.append("\nModel: ").append(backend.openaiModel.trim());
            }
            summary.append("\nDiscovered models: ").append(Math.max(backend.openaiModelCount, 0));
            summary.append("\nAPI key: ").append(backend.hasOpenAiApiKey ? "configured" : "missing");
        }
        if (!isBlank(backend.lastError)) {
            summary.append("\n").append(backend.lastError.trim());
        }
        return summary.toString();
    }

    public static String slotSummary(
            AccountSlotSummary slot,
            String unboundLabel,
            String activeLabel,
            String readyLabel,
            String bindHint
    ) {
        String identity = firstNonBlank(slot.email, slot.accountId, unboundLabel);
        StringBuilder summary = new StringBuilder(identity);
        if (!isBlank(slot.authMode)) {
            summary.append("\nMode: ").append(slot.authMode.trim());
        }
        if (slot.active) {
            summary.append("\n").append(activeLabel);
        } else if (slot.bound) {
            summary.append("\n").append(readyLabel);
        } else {
            summary.append("\n").append(bindHint);
        }
        return summary.toString();
    }

    public static boolean canSwitch(AccountSlotSummary slot) {
        return slot != null && slot.bound;
    }

    public static String slotDisplayName(AccountSlotSummary slot) {
        if (slot == null) {
            return "";
        }
        return firstNonBlank(slot.label, slot.slotId, "Account Slot");
    }

    private static String firstNonBlank(String... values) {
        if (values == null) {
            return "";
        }
        for (String value : values) {
            if (!isBlank(value)) {
                return value.trim();
            }
        }
        return "";
    }

    private static boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
