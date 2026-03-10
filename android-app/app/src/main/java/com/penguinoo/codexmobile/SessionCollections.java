package com.penguinoo.codexmobile;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

public final class SessionCollections {
    private SessionCollections() {
    }

    public static List<SessionSummary> recentChats(List<SessionSummary> sessions, int limit) {
        List<SessionSummary> copy = new ArrayList<>(sessions);
        copy.sort(Comparator.comparingLong((SessionSummary session) -> session.timestamp).reversed());
        return copy.subList(0, Math.min(limit, copy.size()));
    }

    public static String displayTitle(SessionSummary session) {
        return session.text == null || session.text.isEmpty() ? session.sessionId : session.text;
    }

    public static String primarySubtitle(SessionSummary session) {
        if (session.note != null && !session.note.isEmpty()) {
            return session.note;
        }
        return session.cwd == null ? "" : session.cwd;
    }
}
