package com.penguinoo.codexmobile;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

public final class ReplyMonitorState {
    private ReplyMonitorState() {
    }

    public static Set<String> replyingSessionIds(List<SessionSummary> sessions) {
        Set<String> ids = new LinkedHashSet<>();
        if (sessions == null) {
            return ids;
        }
        for (SessionSummary session : sessions) {
            if (session == null || !session.isReplying || session.sessionId == null || session.sessionId.isEmpty()) {
                continue;
            }
            ids.add(session.sessionId);
        }
        return ids;
    }

    public static List<SessionSummary> completedSessions(Set<String> previousReplying, List<SessionSummary> currentSessions) {
        List<SessionSummary> completed = new ArrayList<>();
        if (previousReplying == null || previousReplying.isEmpty() || currentSessions == null) {
            return completed;
        }
        for (SessionSummary session : currentSessions) {
            if (session == null || session.sessionId == null || session.sessionId.isEmpty()) {
                continue;
            }
            if (previousReplying.contains(session.sessionId) && !session.isReplying) {
                completed.add(session);
            }
        }
        return completed;
    }
}