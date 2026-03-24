package com.penguinoo.codexmobile;

public final class PortalProxySettings {
    public final boolean proxyEnabled;
    public final int proxyPort;
    public final String proxyScheme;
    public final String proxyHost;
    public final String proxySummary;

    public PortalProxySettings(
            boolean proxyEnabled,
            int proxyPort,
            String proxyScheme,
            String proxyHost,
            String proxySummary
    ) {
        this.proxyEnabled = proxyEnabled;
        this.proxyPort = proxyPort;
        this.proxyScheme = proxyScheme;
        this.proxyHost = proxyHost;
        this.proxySummary = proxySummary;
    }
}
