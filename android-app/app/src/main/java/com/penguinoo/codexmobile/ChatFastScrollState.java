package com.penguinoo.codexmobile;

public final class ChatFastScrollState {
    private static final int MIN_SCROLLABLE_CONTENT_PX = 120;

    private ChatFastScrollState() {
    }

    public static boolean shouldShowThumb(int scrollRange, int viewportExtent) {
        return scrollRange - viewportExtent > MIN_SCROLLABLE_CONTENT_PX;
    }

    public static float thumbOffsetPx(int trackHeight, int thumbHeight, int scrollRange, int scrollOffset, int viewportExtent) {
        int available = Math.max(0, trackHeight - thumbHeight);
        int scrollable = Math.max(1, scrollRange - viewportExtent);
        float fraction = Math.max(0f, Math.min(1f, scrollOffset / (float) scrollable));
        return available * fraction;
    }

    public static int targetScrollOffset(int trackHeight, int thumbHeight, float touchY, int scrollRange, int viewportExtent) {
        int available = Math.max(1, trackHeight - thumbHeight);
        float clampedY = Math.max(0f, Math.min(available, touchY - (thumbHeight / 2f)));
        float fraction = clampedY / available;
        int scrollable = Math.max(0, scrollRange - viewportExtent);
        return Math.round(scrollable * fraction);
    }
}
