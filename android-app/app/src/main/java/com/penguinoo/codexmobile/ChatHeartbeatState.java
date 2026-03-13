package com.penguinoo.codexmobile;

public final class ChatHeartbeatState {
    private static final int INVALIDATE_AFTER_FAILURES = 3;

    private ChatHeartbeatState() {
    }

    public static int nextFailureCount(boolean succeeded, int currentFailures) {
        if (succeeded) {
            return 0;
        }
        return Math.max(0, currentFailures) + 1;
    }

    public static boolean shouldInvalidateLease(int failureCount) {
        return failureCount >= INVALIDATE_AFTER_FAILURES;
    }
}
