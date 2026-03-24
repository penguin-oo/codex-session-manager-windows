package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

import org.json.JSONObject;
import org.junit.Test;

public final class PortalProxySettingsParsingTest {
    @Test
    public void parseProxySettings_readsGlobalMobileProxyPayload() throws Exception {
        JSONObject json = new JSONObject()
                .put("proxy_enabled", false)
                .put("proxy_port", 9010)
                .put("proxy_scheme", "socks5h")
                .put("proxy_host", "127.0.0.1")
                .put("proxy_summary", "direct");

        PortalProxySettings settings = PortalApiClient.parseProxySettings(json);

        assertFalse(settings.proxyEnabled);
        assertEquals(9010, settings.proxyPort);
        assertEquals("socks5h", settings.proxyScheme);
        assertEquals("127.0.0.1", settings.proxyHost);
        assertEquals("direct", settings.proxySummary);
    }
}
