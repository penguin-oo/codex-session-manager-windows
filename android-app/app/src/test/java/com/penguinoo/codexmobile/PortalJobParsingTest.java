package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;

import org.json.JSONObject;
import org.junit.Test;

public final class PortalJobParsingTest {
    @Test
    public void parseJob_readsLiveTextAndOwnerFields() throws Exception {
        JSONObject json = new JSONObject()
                .put("job_id", "job-1")
                .put("status", "running")
                .put("session_id", "session-1")
                .put("last_message", "done")
                .put("error", "")
                .put("live_text", "thinking...")
                .put("live_chunks_version", 3)
                .put("owner_kind", "mobile")
                .put("owner_label", "Mobile");

        PortalJob job = PortalApiClient.parseJob(json);

        assertEquals("thinking...", job.liveText);
        assertEquals(3, job.liveChunksVersion);
        assertEquals("mobile", job.ownerKind);
        assertEquals("Mobile", job.ownerLabel);
    }
}
