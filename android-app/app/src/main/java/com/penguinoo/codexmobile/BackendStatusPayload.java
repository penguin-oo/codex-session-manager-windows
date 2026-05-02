package com.penguinoo.codexmobile;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class BackendStatusPayload {
    public final String backendMode;
    public final String tokenDir;
    public final int proxyPort;
    public final boolean proxyRunning;
    public final String proxySummary;
    public final int tokenCount;
    public final String openaiBaseUrl;
    public final String openaiModel;
    public final int openaiModelCount;
    public final boolean hasOpenAiApiKey;
    public final List<String> openaiModels;
    public final String lastError;

    public BackendStatusPayload(
            String backendMode,
            String tokenDir,
            int proxyPort,
            boolean proxyRunning,
            String proxySummary,
            int tokenCount,
            String openaiBaseUrl,
            String openaiModel,
            int openaiModelCount,
            boolean hasOpenAiApiKey,
            List<String> openaiModels,
            String lastError
    ) {
        this.backendMode = backendMode;
        this.tokenDir = tokenDir;
        this.proxyPort = proxyPort;
        this.proxyRunning = proxyRunning;
        this.proxySummary = proxySummary;
        this.tokenCount = tokenCount;
        this.openaiBaseUrl = openaiBaseUrl;
        this.openaiModel = openaiModel;
        this.openaiModelCount = openaiModelCount;
        this.hasOpenAiApiKey = hasOpenAiApiKey;
        this.openaiModels = openaiModels == null
                ? Collections.emptyList()
                : Collections.unmodifiableList(new ArrayList<>(openaiModels));
        this.lastError = lastError;
    }

    public boolean isTokenPoolMode() {
        return "built_in_token_pool".equalsIgnoreCase(backendMode);
    }

    public boolean isOpenAiCompatibleMode() {
        return "openai_compatible".equalsIgnoreCase(backendMode);
    }

    public boolean isCodexAuthMode() {
        return "codex_auth".equalsIgnoreCase(backendMode) || backendMode == null || backendMode.trim().isEmpty();
    }
}
