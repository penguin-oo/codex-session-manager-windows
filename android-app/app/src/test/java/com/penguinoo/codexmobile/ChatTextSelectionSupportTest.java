package com.penguinoo.codexmobile;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import android.view.View;
import android.widget.FrameLayout;
import android.widget.TextView;

import androidx.test.core.app.ApplicationProvider;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

@RunWith(RobolectricTestRunner.class)
public final class ChatTextSelectionSupportTest {
    @Test
    public void configure_enablesTextSelectionAndDisablesRootLongClickCopy() {
        TextView messageText = new TextView(ApplicationProvider.getApplicationContext());
        View rootView = new FrameLayout(ApplicationProvider.getApplicationContext());
        rootView.setOnLongClickListener(view -> true);

        ChatTextSelectionSupport.configure(messageText, rootView);

        assertTrue(messageText.isTextSelectable());
        assertFalse(rootView.isLongClickable());
    }
}
