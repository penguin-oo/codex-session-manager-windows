package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Test;

public final class BackendStatusPayloadParsingTest {
    @Test
    public void parseBackendStatus_readsTokenPoolFields() throws Exception {
        JSONObject json = new JSONObject()
                .put("backend_mode", "built_in_token_pool")
                .put("token_dir", "C:\\Users\\MECHREVO\\.cli-proxy-api")
                .put("proxy_port", 8317)
                .put("proxy_running", true)
                .put("proxy_summary", "http://127.0.0.1:8317")
                .put("token_count", 4)
                .put("last_error", "");

        BackendStatusPayload payload = PortalApiClient.parseBackendStatus(json);

        assertEquals("built_in_token_pool", payload.backendMode);
        assertEquals(8317, payload.proxyPort);
        assertEquals(4, payload.tokenCount);
        assertTrue(payload.proxyRunning);
        assertTrue(payload.isTokenPoolMode());
    }
}
