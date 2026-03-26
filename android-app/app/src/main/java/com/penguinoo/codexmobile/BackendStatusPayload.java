package com.penguinoo.codexmobile;

public final class BackendStatusPayload {
    public final String backendMode;
    public final String tokenDir;
    public final int proxyPort;
    public final boolean proxyRunning;
    public final String proxySummary;
    public final int tokenCount;
    public final String lastError;

    public BackendStatusPayload(
            String backendMode,
            String tokenDir,
            int proxyPort,
            boolean proxyRunning,
            String proxySummary,
            int tokenCount,
            String lastError
    ) {
        this.backendMode = backendMode;
        this.tokenDir = tokenDir;
        this.proxyPort = proxyPort;
        this.proxyRunning = proxyRunning;
        this.proxySummary = proxySummary;
        this.tokenCount = tokenCount;
        this.lastError = lastError;
    }

    public boolean isTokenPoolMode() {
        return "built_in_token_pool".equalsIgnoreCase(backendMode);
    }
}
