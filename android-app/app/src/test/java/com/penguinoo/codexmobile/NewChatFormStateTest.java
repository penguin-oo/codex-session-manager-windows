package com.penguinoo.codexmobile;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class NewChatFormStateTest {
    @Test
    public void isReady_requiresCwdAndPrompt() {
        assertFalse(NewChatFormState.isReady("", "hello"));
        assertFalse(NewChatFormState.isReady("D:/repo", ""));
        assertTrue(NewChatFormState.isReady("D:/repo", "hello"));
    }
}
