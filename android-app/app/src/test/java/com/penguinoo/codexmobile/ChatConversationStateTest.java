package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.junit.Test;

public final class ChatConversationStateTest {
    @Test
    public void compose_addsPendingUserMessageBeforeStreamingAssistantBubble() {
        List<ChatMessage> persisted = new ArrayList<>();
        persisted.add(new ChatMessage("assistant", "earlier", 1L));

        List<ChatMessage> display = ChatConversationState.compose(
                persisted,
                new ChatMessage("user", "new prompt", 2L, true),
                "partial answer"
        );

        assertEquals(3, display.size());
        assertEquals("new prompt", display.get(1).text);
        assertTrue(display.get(1).isUser());
        assertTrue(display.get(1).isEphemeral);
        assertEquals("partial answer", display.get(2).text);
        assertTrue(display.get(2).isEphemeral);
    }

    @Test
    public void compose_keepsMultipleQueuedUserMessagesInOrder() {
        List<ChatMessage> persisted = new ArrayList<>();
        persisted.add(new ChatMessage("assistant", "earlier", 1L));

        List<ChatMessage> display = ChatConversationState.compose(
                persisted,
                Arrays.asList(
                        new ChatMessage("user", "first queued", 2L, true),
                        new ChatMessage("user", "second queued", 3L, true)
                ),
                "partial answer"
        );

        assertEquals(4, display.size());
        assertEquals("first queued", display.get(1).text);
        assertEquals("second queued", display.get(2).text);
        assertEquals("partial answer", display.get(3).text);
    }

    @Test
    public void resolveLiveText_fallsBackToLastMessageWhileJobIsRunning() {
        PortalJob job = new PortalJob(
                "job-1",
                "running",
                "session-1",
                "partial answer",
                "",
                "",
                0,
                "mobile",
                "Mobile"
        );

        assertEquals("partial answer", ChatStreamingState.resolveLiveText(job));
    }
}
