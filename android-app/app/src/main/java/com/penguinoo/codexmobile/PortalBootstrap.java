package com.penguinoo.codexmobile;

import java.util.List;

public final class PortalBootstrap {
    public final List<SessionSummary> sessions;
    public final List<String> models;
    public final List<String> approvalOptions;
    public final List<String> sandboxOptions;
    public final List<String> reasoningOptions;

    public PortalBootstrap(
            List<SessionSummary> sessions,
            List<String> models,
            List<String> approvalOptions,
            List<String> sandboxOptions,
            List<String> reasoningOptions
    ) {
        this.sessions = sessions;
        this.models = models;
        this.approvalOptions = approvalOptions;
        this.sandboxOptions = sandboxOptions;
        this.reasoningOptions = reasoningOptions;
    }
}
