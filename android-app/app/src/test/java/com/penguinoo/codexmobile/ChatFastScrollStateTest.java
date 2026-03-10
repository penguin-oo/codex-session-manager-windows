package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class ChatFastScrollStateTest {
    @Test
    public void shouldShowThumb_whenConversationIsLong_returnsTrue() {
        assertTrue(ChatFastScrollState.shouldShowThumb(2400, 800));
    }

    @Test
    public void shouldShowThumb_whenConversationFitsViewport_returnsFalse() {
        assertFalse(ChatFastScrollState.shouldShowThumb(860, 800));
    }

    @Test
    public void thumbOffsetPx_tracksScrollFraction() {
        float offset = ChatFastScrollState.thumbOffsetPx(600, 72, 2400, 800, 800);

        assertEquals(264f, offset, 0.5f);
    }

    @Test
    public void targetScrollOffset_mapsTouchToScrollableRange() {
        int targetOffset = ChatFastScrollState.targetScrollOffset(600, 72, 564f, 2400, 800);

        assertEquals(1600, targetOffset);
    }
}
