package com.penguinoo.codexmobile;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class ChatScrollButtonsStateTest {
    @Test
    public void shouldShowJumpToTop_whenScrolledDown_returnsTrue() {
        assertTrue(ChatScrollButtonsState.shouldShowJumpToTop(60));
    }

    @Test
    public void shouldShowJumpToTop_whenNearTop_returnsFalse() {
        assertFalse(ChatScrollButtonsState.shouldShowJumpToTop(10));
    }

    @Test
    public void shouldShowJumpToBottom_whenFarFromBottom_returnsTrue() {
        assertTrue(ChatScrollButtonsState.shouldShowJumpToBottom(1600, 900, 400));
    }

    @Test
    public void shouldShowJumpToBottom_whenNearBottom_returnsFalse() {
        assertFalse(ChatScrollButtonsState.shouldShowJumpToBottom(1600, 1185, 400));
    }
}
