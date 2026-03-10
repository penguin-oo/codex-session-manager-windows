package com.penguinoo.codexmobile;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class ChatCompletionNotificationStateTest {
    @Test
    public void shouldNotify_whenChatIsVisible_returnsFalse() {
        assertFalse(ChatCompletionNotificationState.shouldNotify(true));
    }

    @Test
    public void shouldNotify_whenChatIsInBackground_returnsTrue() {
        assertTrue(ChatCompletionNotificationState.shouldNotify(false));
    }
}
