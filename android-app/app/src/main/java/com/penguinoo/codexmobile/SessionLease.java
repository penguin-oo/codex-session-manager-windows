package com.penguinoo.codexmobile;

public final class SessionLease {
    public final String sessionId;
    public final String leaseId;
    public final String ownerKind;
    public final String ownerLabel;
    public final String mode;

    public SessionLease(String sessionId, String leaseId, String ownerKind, String ownerLabel, String mode) {
        this.sessionId = sessionId;
        this.leaseId = leaseId;
        this.ownerKind = ownerKind;
        this.ownerLabel = ownerLabel;
        this.mode = mode;
    }
}
