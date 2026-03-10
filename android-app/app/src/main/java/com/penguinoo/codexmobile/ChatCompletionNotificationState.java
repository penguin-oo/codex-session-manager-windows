package com.penguinoo.codexmobile;

public final class ChatCompletionNotificationState {
    private ChatCompletionNotificationState() {
    }

    public static boolean shouldNotify(boolean isActivityVisible) {
        return !isActivityVisible;
    }
}
