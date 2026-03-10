package com.penguinoo.codexmobile;

public final class PortalJob {
    public final String jobId;
    public final String status;
    public final String sessionId;
    public final String lastMessage;
    public final String error;
    public final String liveText;
    public final int liveChunksVersion;
    public final String ownerKind;
    public final String ownerLabel;

    public PortalJob(
            String jobId,
            String status,
            String sessionId,
            String lastMessage,
            String error,
            String liveText,
            int liveChunksVersion,
            String ownerKind,
            String ownerLabel
    ) {
        this.jobId = jobId;
        this.status = status;
        this.sessionId = sessionId;
        this.lastMessage = lastMessage;
        this.error = error;
        this.liveText = liveText;
        this.liveChunksVersion = liveChunksVersion;
        this.ownerKind = ownerKind;
        this.ownerLabel = ownerLabel;
    }

    public boolean isRunning() {
        return "running".equalsIgnoreCase(status);
    }

    public boolean isCompleted() {
        return "completed".equalsIgnoreCase(status);
    }

    public boolean isCancelled() {
        return "cancelled".equalsIgnoreCase(status);
    }
}
