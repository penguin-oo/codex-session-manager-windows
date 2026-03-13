package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

public final class SessionPayloadParsingTest {
    @Test
    public void parseSessionPayload_readsActiveRunningJob() throws Exception {
        JSONObject json = new JSONObject()
                .put("session", new JSONObject()
                        .put("session_id", "session-1")
                        .put("ts", 1)
                        .put("text", "hello")
                        .put("note", "")
                        .put("cwd", "D:/repo")
                        .put("model", "gpt-5")
                        .put("approval_policy", "default")
                        .put("sandbox_mode", "workspace-write")
                        .put("is_replying", true))
                .put("messages", new JSONArray())
                .put("active_job", new JSONObject()
                        .put("job_id", "job-1")
                        .put("status", "running")
                        .put("session_id", "session-1")
                        .put("last_message", "")
                        .put("error", "")
                        .put("live_text", "partial")
                        .put("live_chunks_version", 2)
                        .put("owner_kind", "mobile")
                        .put("owner_label", "Mobile"))
                .put("models", new JSONArray().put("default").put("gpt-5").put("gpt-5.4"))
                .put("approval_options", new JSONArray().put("default").put("never"))
                .put("sandbox_options", new JSONArray().put("default").put("danger-full-access"))
                .put("proxy_summary", "socks5h://127.0.0.1:7897");

        SessionPayload payload = PortalApiClient.parseSessionPayload(json);

        assertNotNull(payload.activeJob);
        assertEquals("job-1", payload.activeJob.jobId);
        assertEquals("partial", payload.activeJob.liveText);
        assertEquals(true, payload.session.isReplying);
        assertEquals("gpt-5.4", payload.modelOptions.get(2));
        assertEquals("never", payload.approvalOptions.get(1));
        assertEquals("danger-full-access", payload.sandboxOptions.get(1));
        assertEquals("socks5h://127.0.0.1:7897", payload.proxySummary);
    }
}
