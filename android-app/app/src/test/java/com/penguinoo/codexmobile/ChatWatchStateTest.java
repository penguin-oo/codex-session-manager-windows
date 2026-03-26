package com.penguinoo.codexmobile;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class ChatWatchStateTest {
    @Test
    public void shouldInvalidateWatch_requiresFiveConsecutiveFailures() {
        assertFalse(ChatWatchState.shouldInvalidateWatch(1));
        assertFalse(ChatWatchState.shouldInvalidateWatch(4));
        assertTrue(ChatWatchState.shouldInvalidateWatch(5));
    }

    @Test
    public void nextFailureCount_resetsAfterSuccess() {
        assertTrue(ChatWatchState.nextFailureCount(true, 3) == 0);
        assertTrue(ChatWatchState.nextFailureCount(false, 3) == 4);
    }

    @Test
    public void shouldApplyLiveUpdate_whenWatcherMatchesCurrentJob_returnsTrue() {
        PortalJob job = new PortalJob("job-1", "running", "session-1", "", "", "partial", 1, "mobile", "Mobile");

        assertTrue(ChatWatchState.shouldApplyLiveUpdate("job-1", 3, 3, job));
    }

    @Test
    public void shouldApplyLiveUpdate_whenGenerationIsStale_returnsFalse() {
        PortalJob job = new PortalJob("job-1", "running", "session-1", "", "", "partial", 1, "mobile", "Mobile");

        assertFalse(ChatWatchState.shouldApplyLiveUpdate("job-1", 4, 3, job));
    }

    @Test
    public void shouldApplyLiveUpdate_whenWatchingJobWasCleared_returnsFalse() {
        PortalJob job = new PortalJob("job-1", "running", "session-1", "", "", "partial", 1, "mobile", "Mobile");

        assertFalse(ChatWatchState.shouldApplyLiveUpdate("", 3, 3, job));
    }
}
