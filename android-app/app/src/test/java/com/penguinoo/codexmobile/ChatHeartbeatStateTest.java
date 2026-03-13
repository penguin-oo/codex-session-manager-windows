package com.penguinoo.codexmobile;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class ChatHeartbeatStateTest {
    @Test
    public void shouldInvalidateLease_requiresThreeConsecutiveFailures() {
        assertFalse(ChatHeartbeatState.shouldInvalidateLease(1));
        assertFalse(ChatHeartbeatState.shouldInvalidateLease(2));
        assertTrue(ChatHeartbeatState.shouldInvalidateLease(3));
    }

    @Test
    public void nextFailureCount_resetsAfterSuccess() {
        assertTrue(ChatHeartbeatState.nextFailureCount(true, 2) == 0);
        assertTrue(ChatHeartbeatState.nextFailureCount(false, 2) == 3);
    }
}
