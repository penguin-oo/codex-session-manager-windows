package com.penguinoo.codexmobile;

public final class ChatResumeState {
    private ChatResumeState() {
    }

    public static boolean shouldReloadSessionOnResume(boolean hasCurrentSession) {
        return hasCurrentSession;
    }
}
