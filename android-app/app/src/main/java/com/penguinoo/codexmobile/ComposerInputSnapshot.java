package com.penguinoo.codexmobile;

import android.text.Editable;
import android.view.inputmethod.BaseInputConnection;

final class ComposerInputSnapshot {
    final String prompt;
    final String draftText;

    private ComposerInputSnapshot(String prompt, String draftText) {
        this.prompt = prompt;
        this.draftText = draftText;
    }

    static ComposerInputSnapshot capture(Editable editable) {
        if (editable == null) {
            return new ComposerInputSnapshot("", "");
        }
        BaseInputConnection.removeComposingSpans(editable);
        String rawText = editable.toString();
        return new ComposerInputSnapshot(rawText.trim(), rawText);
    }
}
