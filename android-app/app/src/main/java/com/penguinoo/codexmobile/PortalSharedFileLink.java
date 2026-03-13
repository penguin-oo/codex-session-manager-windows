package com.penguinoo.codexmobile;

public final class PortalSharedFileLink {
    public final String shareId;
    public final String relativeUrl;
    public final String fileName;
    public final String contentType;
    public final long expiresAt;

    public PortalSharedFileLink(
            String shareId,
            String relativeUrl,
            String fileName,
            String contentType,
            long expiresAt
    ) {
        this.shareId = shareId;
        this.relativeUrl = relativeUrl;
        this.fileName = fileName;
        this.contentType = contentType;
        this.expiresAt = expiresAt;
    }
}
