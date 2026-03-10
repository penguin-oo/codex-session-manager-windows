package com.penguinoo.codexmobile;

public final class NewChatLaunchState {
    private NewChatLaunchState() {
    }

    public static boolean shouldOpenChat(PortalJob job) {
        return job != null && job.sessionId != null && !job.sessionId.isEmpty();
    }
}
