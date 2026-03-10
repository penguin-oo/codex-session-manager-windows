package com.penguinoo.codexmobile;

import java.util.List;

public final class SessionPayload {
    public final SessionSummary session;
    public final List<ChatMessage> messages;
    public final PortalJob activeJob;

    public SessionPayload(SessionSummary session, List<ChatMessage> messages, PortalJob activeJob) {
        this.session = session;
        this.messages = messages;
        this.activeJob = activeJob;
    }
}
