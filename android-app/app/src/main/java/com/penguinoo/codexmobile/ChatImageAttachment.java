package com.penguinoo.codexmobile;

public final class ChatImageAttachment {
    public final String displayName;
    public final String mimeType;
    public final byte[] bytes;

    public ChatImageAttachment(String displayName, String mimeType, byte[] bytes) {
        this.displayName = displayName == null || displayName.isEmpty() ? "image" : displayName;
        this.mimeType = mimeType == null || mimeType.isEmpty() ? "image/*" : mimeType;
        this.bytes = bytes == null ? new byte[0] : bytes.clone();
    }
}
