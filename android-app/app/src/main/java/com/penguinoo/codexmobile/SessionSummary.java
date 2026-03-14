package com.penguinoo.codexmobile;

public final class SessionSummary {
    public final String sessionId;
    public final long timestamp;
    public final String text;
    public final String note;
    public final String cwd;
    public final String model;
    public final String approvalPolicy;
    public final String sandboxMode;
    public final String reasoningEffort;
    public final boolean isReplying;

    public SessionSummary(
            String sessionId,
            long timestamp,
            String text,
            String note,
            String cwd,
            String model,
            String approvalPolicy,
            String sandboxMode
    ) {
        this(sessionId, timestamp, text, note, cwd, model, approvalPolicy, sandboxMode, "", false);
    }

    public SessionSummary(
            String sessionId,
            long timestamp,
            String text,
            String note,
            String cwd,
            String model,
            String approvalPolicy,
            String sandboxMode,
            boolean isReplying
    ) {
        this(sessionId, timestamp, text, note, cwd, model, approvalPolicy, sandboxMode, "", isReplying);
    }

    public SessionSummary(
            String sessionId,
            long timestamp,
            String text,
            String note,
            String cwd,
            String model,
            String approvalPolicy,
            String sandboxMode,
            String reasoningEffort,
            boolean isReplying
    ) {
        this.sessionId = sessionId;
        this.timestamp = timestamp;
        this.text = text;
        this.note = note;
        this.cwd = cwd;
        this.model = model;
        this.approvalPolicy = approvalPolicy;
        this.sandboxMode = sandboxMode;
        this.reasoningEffort = reasoningEffort;
        this.isReplying = isReplying;
    }
}
