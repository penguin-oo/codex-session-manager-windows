package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.List;

import org.junit.Test;

public final class ChatStreamingStateTest {
    @Test
    public void resolveLiveText_keepsPartialTextForCancelledJobs() {
        PortalJob job = new PortalJob(
                "job-1",
                "cancelled",
                "session-1",
                "partial answer",
                "",
                "",
                0,
                "",
                ""
        );

        assertEquals("partial answer", ChatStreamingState.resolveLiveText(job));
    }

    @Test
    public void applyLiveText_appendsEphemeralAssistantBubble() {
        List<ChatMessage> messages = new ArrayList<>();
        messages.add(new ChatMessage("user", "hello", 1L));

        List<ChatMessage> updated = ChatStreamingState.applyLiveText(messages, "partial");

        ChatMessage last = updated.get(updated.size() - 1);
        assertEquals("partial", last.text);
        assertTrue(last.isEphemeral);
        assertEquals("assistant", last.role);
    }
}
