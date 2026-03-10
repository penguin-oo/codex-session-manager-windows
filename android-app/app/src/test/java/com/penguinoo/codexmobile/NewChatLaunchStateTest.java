package com.penguinoo.codexmobile;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class NewChatLaunchStateTest {
    @Test
    public void shouldOpenChat_whenRunningJobAlreadyHasSessionId() {
        PortalJob job = new PortalJob("job-1", "running", "session-1", "", "", "", 0, "", "");

        assertTrue(NewChatLaunchState.shouldOpenChat(job));
    }

    @Test
    public void shouldNotOpenChat_whenRunningJobHasNoSessionId() {
        PortalJob job = new PortalJob("job-1", "running", "", "", "", "", 0, "", "");

        assertFalse(NewChatLaunchState.shouldOpenChat(job));
    }

    @Test
    public void shouldNotOpenChat_whenJobFailedWithoutSessionId() {
        PortalJob job = new PortalJob("job-1", "failed", "", "", "boom", "", 0, "", "");

        assertFalse(NewChatLaunchState.shouldOpenChat(job));
    }

    @Test
    public void shouldOpenChat_whenCompletedJobHasSessionId() {
        PortalJob job = new PortalJob("job-1", "completed", "session-1", "done", "", "", 0, "", "");

        assertTrue(NewChatLaunchState.shouldOpenChat(job));
    }
}
