package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

import java.util.Arrays;
import java.util.List;

public final class SessionCollectionsTest {
    @Test
    public void recentChats_returnsNewestSessionsFirst_andCapsList() {
        List<SessionSummary> sessions = Arrays.asList(
                new SessionSummary("a", 10L, "Older", "", "", "", "", ""),
                new SessionSummary("b", 50L, "Newest", "", "", "", "", ""),
                new SessionSummary("c", 30L, "Middle", "", "", "", "", "")
        );

        List<SessionSummary> recent = SessionCollections.recentChats(sessions, 2);

        assertEquals(Arrays.asList("b", "c"), idsOf(recent));
    }

    @Test
    public void displayTitle_fallsBackToSessionIdWhenTextMissing() {
        SessionSummary session = new SessionSummary("abc123", 99L, "", "", "D:/repo", "", "", "");

        assertEquals("abc123", SessionCollections.displayTitle(session));
    }

    private List<String> idsOf(List<SessionSummary> sessions) {
        return Arrays.asList(
                sessions.get(0).sessionId,
                sessions.get(1).sessionId
        );
    }
}
