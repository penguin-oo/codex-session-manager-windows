package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Set;

public final class ReplyMonitorStateTest {
    @Test
    public void replyingSessionIds_returnsOnlyRunningSessions() {
        List<SessionSummary> sessions = Arrays.asList(
                session("a", true),
                session("b", false),
                session("c", true)
        );

        Set<String> ids = ReplyMonitorState.replyingSessionIds(sessions);

        assertEquals(2, ids.size());
        assertTrue(ids.contains("a"));
        assertTrue(ids.contains("c"));
    }

    @Test
    public void completedSessions_returnsSessionsThatStoppedReplying() {
        Set<String> previousReplying = Set.of("a", "b");
        List<SessionSummary> currentSessions = Arrays.asList(
                session("a", false),
                session("b", true),
                session("c", false)
        );

        List<SessionSummary> completed = ReplyMonitorState.completedSessions(previousReplying, currentSessions);

        assertEquals(1, completed.size());
        assertEquals("a", completed.get(0).sessionId);
    }

    @Test
    public void completedSessions_doesNotNotifyOnInitialSnapshot() {
        List<SessionSummary> completed = ReplyMonitorState.completedSessions(Collections.emptySet(), Arrays.asList(
                session("a", false),
                session("b", false)
        ));

        assertTrue(completed.isEmpty());
    }

    private static SessionSummary session(String id, boolean isReplying) {
        return new SessionSummary(id, 1L, id, "", "", "", "", "", isReplying);
    }
}