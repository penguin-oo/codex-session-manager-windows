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
                .put("active_slot", "slot-2")
                .put("has_running_jobs", false)
                .put("current_auth", new JSONObject()
                        .put("email", "b@example.com")
                        .put("account_id", "acct-b")
                        .put("auth_mode", "chatgpt"))
                .put("quota", new JSONObject()
                        .put("summary", "Weekly quota: 76% used")
                        .put("state", "ok"))
                .put("slots", new JSONArray()
                        .put(new JSONObject()
                                .put("slot_id", "slot-1")
                                .put("label", "Work")
                                .put("email", "a@example.com")
                                .put("account_id", "acct-a")
                                .put("auth_mode", "chatgpt")
                                .put("active", "no"))
                        .put(new JSONObject()
                                .put("slot_id", "slot-2")
                                .put("label", "Backup")
                                .put("email", "b@example.com")
                                .put("account_id", "acct-b")
                                .put("auth_mode", "chatgpt")
                                .put("active", "yes")));

        AccountSlotsPayload payload = PortalApiClient.parseAccountSlotsPayload(json);

        assertEquals("slot-2", payload.activeSlot);
        assertEquals("b@example.com", payload.currentEmail);
        assertEquals("Weekly quota: 76% used", payload.quotaSummary);
        assertEquals(2, payload.slots.size());
        assertTrue(payload.slots.get(1).active);
        assertTrue(payload.slots.get(0).bound);
        assertEquals("Work", payload.slots.get(0).label);
    }
}
