package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

public final class AccountSlotsPayloadParsingTest {
    @Test
    public void parseAccountSlotsPayload_readsSlotsAndCurrentAccount() throws Exception {
        JSONObject json = new JSONObject()
                .put("active_slot", "account-b")
                .put("has_running_jobs", false)
                .put("current_auth", new JSONObject()
                        .put("email", "b@example.com")
                        .put("account_id", "acct-b")
                        .put("auth_mode", "chatgpt"))
                .put("slots", new JSONArray()
                        .put(new JSONObject()
                                .put("slot_id", "account-a")
                                .put("email", "a@example.com")
                                .put("account_id", "acct-a")
                                .put("auth_mode", "chatgpt")
                                .put("active", "no"))
                        .put(new JSONObject()
                                .put("slot_id", "account-b")
                                .put("email", "b@example.com")
                                .put("account_id", "acct-b")
                                .put("auth_mode", "chatgpt")
                                .put("active", "yes")));

        AccountSlotsPayload payload = PortalApiClient.parseAccountSlotsPayload(json);

        assertEquals("account-b", payload.activeSlot);
        assertEquals("b@example.com", payload.currentEmail);
        assertEquals(2, payload.slots.size());
        assertTrue(payload.slots.get(1).active);
        assertTrue(payload.slots.get(0).bound);
    }
}
