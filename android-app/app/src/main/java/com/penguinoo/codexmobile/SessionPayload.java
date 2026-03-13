package com.penguinoo.codexmobile;

import java.util.List;

public final class SessionPayload {
    public final SessionSummary session;
    public final List<ChatMessage> messages;
    public final PortalJob activeJob;
    public final List<String> modelOptions;
    public final List<String> approvalOptions;
    public final List<String> sandboxOptions;
    public final String proxySummary;

    public SessionPayload(
            SessionSummary session,
            List<ChatMessage> messages,
            PortalJob activeJob,
            List<String> modelOptions,
            List<String> approvalOptions,
            List<String> sandboxOptions,
            String proxySummary
    ) {
        this.session = session;
        this.messages = messages;
        this.activeJob = activeJob;
        this.modelOptions = modelOptions;
        this.approvalOptions = approvalOptions;
        this.sandboxOptions = sandboxOptions;
        this.proxySummary = proxySummary;
    }
}
