package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class ChatHeaderModelTest {
    @Test
    public void metadataLine_prefersNoteSummary_thenWorkingDirectory() {
        SessionSummary withNote = new SessionSummary("id", 1L, "Chat", "Remember this", "D:/repo", "gpt-5", "never", "workspace-write");
        SessionSummary withoutNote = new SessionSummary("id", 1L, "Chat", "", "D:/repo", "gpt-5", "never", "workspace-write");

        assertEquals("Remember this", ChatHeaderModel.metadataLine(withNote));
        assertEquals("D:/repo", ChatHeaderModel.metadataLine(withoutNote));
    }
}
