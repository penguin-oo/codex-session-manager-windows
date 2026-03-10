package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class ChatLayoutStateTest {
    @Test
    public void contentTopPadding_matchesSystemBarInset() {
        int padding = ChatLayoutState.contentTopPadding(36);

        assertEquals(36, padding);
    }

    @Test
    public void recyclerBottomPadding_usesImeInsetWhenKeyboardIsVisible() {
        int padding = ChatLayoutState.recyclerBottomPadding(12, 16, 320);

        assertEquals(332, padding);
    }

    @Test
    public void extraImeInset_subtractsSystemBarsInset() {
        int extra = ChatLayoutState.extraImeInset(16, 320);

        assertEquals(304, extra);
    }

    @Test
    public void shouldAutoScroll_whenAlreadyNearBottom_returnsTrue() {
        boolean result = ChatLayoutState.shouldAutoScroll(1200, 900, 280, 48);

        assertTrue(result);
    }

    @Test
    public void shouldAutoScroll_whenUserScrolledUp_returnsFalse() {
        boolean result = ChatLayoutState.shouldAutoScroll(1200, 420, 280, 48);

        assertFalse(result);
    }
}
