package com.penguinoo.codexmobile;

import java.util.List;

public final class AccountSlotsPayload {
    public final String activeSlot;
    public final String currentEmail;
    public final String currentAccountId;
    public final String currentAuthMode;
    public final String quotaSummary;
    public final String quotaState;
    public final boolean hasRunningJobs;
    public final List<AccountSlotSummary> slots;

    public AccountSlotsPayload(
            String activeSlot,
            String currentEmail,
            String currentAccountId,
            String currentAuthMode,
            String quotaSummary,
            String quotaState,
            boolean hasRunningJobs,
            List<AccountSlotSummary> slots
    ) {
        this.activeSlot = activeSlot;
        this.currentEmail = currentEmail;
        this.currentAccountId = currentAccountId;
        this.currentAuthMode = currentAuthMode;
        this.quotaSummary = quotaSummary;
        this.quotaState = quotaState;
        this.hasRunningJobs = hasRunningJobs;
        this.slots = slots;
    }
}
