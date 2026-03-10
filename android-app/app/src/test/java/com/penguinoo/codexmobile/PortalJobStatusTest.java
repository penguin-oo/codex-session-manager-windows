package com.penguinoo.codexmobile;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class PortalJobStatusTest {
    @Test
    public void cancelledJob_isCancelledAndNotRunning() {
        PortalJob job = new PortalJob("job-1", "cancelled", "session-1", "partial", "", "partial", 1, "mobile", "Mobile");

        assertTrue(job.isCancelled());
        assertFalse(job.isRunning());
        assertFalse(job.isCompleted());
    }
}