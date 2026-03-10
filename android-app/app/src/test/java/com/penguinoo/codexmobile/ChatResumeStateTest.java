package com.penguinoo.codexmobile;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class ChatResumeStateTest {
    @Test
    public void shouldReloadSessionOnResume_whenSessionLoaded_returnsTrue() {
        assertTrue(ChatResumeState.shouldReloadSessionOnResume(true));
    }

    @Test
    public void shouldReloadSessionOnResume_whenSessionMissing_returnsFalse() {
        assertFalse(ChatResumeState.shouldReloadSessionOnResume(false));
    }
}
