package com.penguinoo.codexmobile;

public final class AccountSlotSummary {
    public final String slotId;
    public final String label;
    public final String email;
    public final String accountId;
    public final String authMode;
    public final boolean active;
    public final boolean bound;

    public AccountSlotSummary(
            String slotId,
            String label,
            String email,
            String accountId,
            String authMode,
            boolean active,
            boolean bound
    ) {
        this.slotId = slotId;
        this.label = label;
        this.email = email;
        this.accountId = accountId;
        this.authMode = authMode;
        this.active = active;
        this.bound = bound;
    }
}
