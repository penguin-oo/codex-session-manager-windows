package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class SessionRowModelTest {
    @Test
    public void primarySubtitle_prefersNotePreview_overWorkingDirectory() {
        SessionSummary session = new SessionSummary("id", 1L, "Chat", "Pinned idea", "D:/repo", "gpt-5", "", "");

        assertEquals("Pinned idea", SessionCollections.primarySubtitle(session));
    }
}
