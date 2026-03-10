package com.penguinoo.codexmobile;

public final class ChatHeaderModel {
    private ChatHeaderModel() {
    }

    public static String metadataLine(SessionSummary session) {
        if (session.note != null && !session.note.isEmpty()) {
            return session.note;
        }
        return session.cwd == null ? "" : session.cwd;
    }
}
