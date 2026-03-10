package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;

import org.json.JSONObject;
import org.junit.Test;

public final class PortalSendMessageBodyTest {
    @Test
    public void buildSendMessageBody_includesImagePayloadWhenPresent() throws Exception {
        ChatImageAttachment imageAttachment = new ChatImageAttachment(
                "photo.png",
                "image/png",
                "cG5n".getBytes()
        );

        JSONObject body = PortalApiClient.buildSendMessageBody(
                "hello",
                "gpt-5",
                "never",
                "workspace-write",
                "lease-1",
                imageAttachment
        );

        assertEquals("hello", body.getString("prompt"));
        assertEquals("photo.png", body.getJSONObject("image").getString("name"));
        assertEquals("image/png", body.getJSONObject("image").getString("mime_type"));
    }
}
