package com.penguinoo.codexmobile;

public final class ChatScrollButtonsState {
    private static final int VISIBILITY_THRESHOLD_PX = 24;

    private ChatScrollButtonsState() {
    }

    public static boolean shouldShowJumpToTop(int scrollOffset) {
        return scrollOffset > VISIBILITY_THRESHOLD_PX;
    }

    public static boolean shouldShowJumpToBottom(int scrollRange, int scrollOffset, int viewportExtent) {
        int distanceToBottom = Math.max(0, scrollRange - (scrollOffset + viewportExtent));
        return distanceToBottom > VISIBILITY_THRESHOLD_PX;
    }
}
