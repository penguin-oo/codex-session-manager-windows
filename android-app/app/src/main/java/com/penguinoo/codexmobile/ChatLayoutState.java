package com.penguinoo.codexmobile;

public final class ChatLayoutState {
    public static final int AUTO_SCROLL_THRESHOLD_PX = 48;

    private ChatLayoutState() {
    }

    public static int contentTopPadding(int systemBarsTop) {
        return Math.max(0, systemBarsTop);
    }

    public static int extraImeInset(int systemBarsBottom, int imeBottom) {
        return Math.max(0, imeBottom - systemBarsBottom);
    }

    public static int recyclerBottomPadding(int baseBottomPadding, int systemBarsBottom, int imeBottom) {
        return baseBottomPadding + Math.max(systemBarsBottom, imeBottom);
    }

    public static boolean shouldAutoScroll(int scrollRange, int scrollOffset, int viewportExtent, int thresholdPx) {
        int distanceToBottom = Math.max(0, scrollRange - (scrollOffset + viewportExtent));
        return distanceToBottom <= Math.max(0, thresholdPx);
    }
}
