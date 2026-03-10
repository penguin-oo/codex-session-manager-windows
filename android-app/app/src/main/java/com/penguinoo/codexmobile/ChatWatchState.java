package com.penguinoo.codexmobile;

public final class ChatWatchState {
    private ChatWatchState() {
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
