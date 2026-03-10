package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

@RunWith(RobolectricTestRunner.class)
public final class PortalEndpointTest {
    @Test
    public void parse_addsHttpSchemeWhenMissing() {
        PortalEndpoint endpoint = PortalEndpoint.parse("192.168.1.8:8765/?token=abc123");

        assertEquals("abc123", endpoint.getToken());
        assertEquals("http://192.168.1.8:8765/api/bootstrap", endpoint.apiUrl("/api/bootstrap"));
    }

    @Test
    public void parse_rejectsPortalUrlWithoutToken() {
        try {
            PortalEndpoint.parse("http://192.168.1.8:8765/");
            fail("Expected missing token to be rejected.");
        } catch (IllegalArgumentException exception) {
            assertEquals("Portal URL must include the token query parameter.", exception.getMessage());
        }
    }
}
