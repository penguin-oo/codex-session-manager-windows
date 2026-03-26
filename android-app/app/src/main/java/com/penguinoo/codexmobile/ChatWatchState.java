package com.penguinoo.codexmobile;

public final class ChatWatchState {
    private static final int INVALIDATE_AFTER_FAILURES = 5;

    private ChatWatchState() {
    }

    public static int nextFailureCount(boolean succeeded, int currentFailures) {
        if (succeeded) {
            return 0;
        }
        return Math.max(0, currentFailures) + 1;
    }

    public static boolean shouldInvalidateWatch(int failureCount) {
        return failureCount >= INVALIDATE_AFTER_FAILURES;
    }

    public static boolean shouldApplyLiveUpdate(String watchingJobId, int currentGeneration, int callbackGeneration, PortalJob job) {
        if (job == null || !job.isRunning()) {
            return false;
        }
        if (watchingJobId == null || watchingJobId.isEmpty()) {
            return false;
        }
        if (callbackGeneration != currentGeneration) {
            return false;
        }
        return watchingJobId.equals(job.jobId);
    }
}
