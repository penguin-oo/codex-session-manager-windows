package com.penguinoo.codexmobile;

public final class NewChatFormState {
    private NewChatFormState() {
    }

    public static boolean isReady(String cwd, String prompt) {
        return cwd != null && !cwd.isBlank() && prompt != null && !prompt.isBlank();
    }
}

