package com.penguinoo.codexmobile;

public final class ChatMessage {
    public final String role;
    public final String text;
    public final long timestamp;
    public final boolean isEphemeral;

    public ChatMessage(String role, String text, long timestamp) {
        this(role, text, timestamp, false);
    }

    public ChatMessage(String role, String text, long timestamp, boolean isEphemeral) {
        this.role = role;
        this.text = text;
        this.timestamp = timestamp;
        this.isEphemeral = isEphemeral;
    }

    public boolean isUser() {
        return "user".equalsIgnoreCase(role);
    }
}
