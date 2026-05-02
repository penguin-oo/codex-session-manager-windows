package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;

import org.json.JSONArray;
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

    @Test
    public void parseBackendStatus_readsOpenAiCompatibleFields() throws Exception {
        JSONObject json = new JSONObject()
                .put("backend_mode", "openai_compatible")
                .put("token_dir", "")
                .put("proxy_port", 0)
                .put("proxy_running", false)
                .put("proxy_summary", "stopped")
                .put("token_count", 0)
                .put("openai_base_url", "https://api.openai.com/v1")
                .put("openai_model", "gpt-5.5")
                .put("openai_model_count", 2)
                .put("has_openai_api_key", true)
                .put("openai_models", new JSONArray().put("gpt-5.5").put("gpt-4.1"))
                .put("last_error", "");

        BackendStatusPayload payload = PortalApiClient.parseBackendStatus(json);

        assertEquals("openai_compatible", payload.backendMode);
        assertEquals("https://api.openai.com/v1", payload.openaiBaseUrl);
        assertEquals("gpt-5.5", payload.openaiModel);
        assertEquals(2, payload.openaiModelCount);
        assertTrue(payload.hasOpenAiApiKey);
        assertEquals(Arrays.asList("gpt-5.5", "gpt-4.1"), payload.openaiModels);
        assertTrue(payload.isOpenAiCompatibleMode());
    }

    @Test
    public void buildBackendSettingsBody_includesOpenAiFields() throws Exception {
        JSONObject body = PortalApiClient.buildBackendSettingsBody(
                "openai_compatible",
                "C:\\tokens",
                8317,
                "https://api.openai.com/v1",
                "sk-test",
                "gpt-5.5"
        );

        assertEquals("openai_compatible", body.getString("backend_mode"));
        assertEquals("C:\\tokens", body.getString("token_dir"));
        assertEquals(8317, body.getInt("proxy_port"));
        assertEquals("https://api.openai.com/v1", body.getString("openai_base_url"));
        assertEquals("sk-test", body.getString("openai_api_key"));
        assertEquals("gpt-5.5", body.getString("openai_model"));
    }
}
