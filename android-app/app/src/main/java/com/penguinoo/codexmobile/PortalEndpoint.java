package com.penguinoo.codexmobile;

import android.net.Uri;

public final class PortalEndpoint {
    private final String rawUrl;
    private final String origin;
    private final String token;

    private PortalEndpoint(String rawUrl, String origin, String token) {
        this.rawUrl = rawUrl;
        this.origin = origin;
        this.token = token;
    }

    public static PortalEndpoint parse(String input) {
        String value = input == null ? "" : input.trim();
        if (value.isEmpty()) {
            throw new IllegalArgumentException("Portal URL is required.");
        }
        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            value = "http://" + value;
        }

        Uri uri = Uri.parse(value);
        String scheme = uri.getScheme();
        String host = uri.getHost();
        int port = uri.getPort();
        String token = uri.getQueryParameter("token");

        if (scheme == null || host == null || host.isEmpty()) {
            throw new IllegalArgumentException("Invalid portal URL.");
        }
        if (token == null || token.isEmpty()) {
            throw new IllegalArgumentException("Portal URL must include the token query parameter.");
        }

        StringBuilder originBuilder = new StringBuilder();
        originBuilder.append(scheme).append("://").append(host);
        if (port > 0) {
            originBuilder.append(":").append(port);
        }
        return new PortalEndpoint(value, originBuilder.toString(), token);
    }

    public String getRawUrl() {
        return rawUrl;
    }

    public String getToken() {
        return token;
    }

    public String apiUrl(String path) {
        return origin + path;
    }

    public String browserUrl(String path) {
        if (path == null || path.isEmpty()) {
            return origin;
        }
        if (path.startsWith("http://") || path.startsWith("https://")) {
            return path;
        }
        if (path.startsWith("/")) {
            return origin + path;
        }
        return origin + "/" + path;
    }
}
