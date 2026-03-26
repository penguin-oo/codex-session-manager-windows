package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class AccountCenterPresentationTest {
    @Test
    public void currentAccountSummary_includesIdentityModeSlotAndQuota() {
        AccountSlotsPayload payload = new AccountSlotsPayload(
                "slot-2",
                "b@example.com",
                "acct-b",
                "chatgpt",
                "Weekly quota: 76% used",
                "ok",
                false,
                new BackendStatusPayload("codex_auth", "", 0, false, "", 0, ""),
                java.util.Collections.emptyList()
        );

        String summary = AccountCenterPresentation.currentAccountSummary(
                payload,
                "Not bound yet",
                "Quota unavailable",
                "Backup"
        );

        assertEquals(
                "b@example.com\nMode: chatgpt\nActive slot: Backup\nWeekly quota: 76% used",
                summary
        );
    }

    @Test
    public void slotSummary_marksUnboundSlotsClearly() {
        AccountSlotSummary slot = new AccountSlotSummary(
                "slot-3",
                "Travel",
                "",
                "",
                "",
                false,
                false
        );

        String summary = AccountCenterPresentation.slotSummary(
                slot,
                "Not bound yet",
                "Active now",
                "Ready to switch",
                "Bind the current login here first"
        );

        assertEquals("Not bound yet\nBind the current login here first", summary);
        assertFalse(AccountCenterPresentation.canSwitch(slot));
    }

    @Test
    public void slotSummary_marksActiveBoundSlotsClearly() {
        AccountSlotSummary slot = new AccountSlotSummary(
                "slot-2",
                "Backup",
                "b@example.com",
                "acct-b",
                "chatgpt",
                true,
                true
        );

        String summary = AccountCenterPresentation.slotSummary(
                slot,
                "Not bound yet",
                "Active now",
                "Ready to switch",
                "Bind the current login here first"
        );

        assertEquals("b@example.com\nMode: chatgpt\nActive now", summary);
        assertTrue(AccountCenterPresentation.canSwitch(slot));
    }
}
