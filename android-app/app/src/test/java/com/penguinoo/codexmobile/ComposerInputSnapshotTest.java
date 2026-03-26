package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;

import android.text.Editable;
import android.text.SpannableStringBuilder;
import android.view.inputmethod.BaseInputConnection;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

@RunWith(RobolectricTestRunner.class)
public class ComposerInputSnapshotTest {
    @Test
    public void captureRemovesComposingSpansBeforeReadingText() {
        Editable editable = new SpannableStringBuilder("认可，开始改动");
        BaseInputConnection.setComposingSpans(editable);

        ComposerInputSnapshot snapshot = ComposerInputSnapshot.capture(editable);

        assertEquals("认可，开始改动", snapshot.prompt);
        assertEquals("认可，开始改动", snapshot.draftText);
        assertEquals(-1, BaseInputConnection.getComposingSpanStart(editable));
    }

    @Test
    public void captureTrimsPromptButKeepsDraftText() {
        Editable editable = new SpannableStringBuilder("  你好  ");

        ComposerInputSnapshot snapshot = ComposerInputSnapshot.capture(editable);

        assertEquals("你好", snapshot.prompt);
        assertEquals("  你好  ", snapshot.draftText);
    }
}
