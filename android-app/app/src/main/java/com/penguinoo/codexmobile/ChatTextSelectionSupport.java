package com.penguinoo.codexmobile;

import android.view.View;
import android.text.method.ArrowKeyMovementMethod;
import android.widget.TextView;

public final class ChatTextSelectionSupport {
    private ChatTextSelectionSupport() {
    }

    public static void configure(TextView messageText, View rootView) {
        messageText.setTextIsSelectable(true);
        messageText.setFocusable(true);
        messageText.setFocusableInTouchMode(true);
        messageText.setClickable(true);
        messageText.setLongClickable(true);
        messageText.setMovementMethod(ArrowKeyMovementMethod.getInstance());
        rootView.setOnLongClickListener(null);
        rootView.setLongClickable(false);
    }
}
