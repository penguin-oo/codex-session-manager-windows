package com.penguinoo.codexmobile;

import java.util.ArrayList;
import java.util.List;

public final class ChatStreamingState {
    private ChatStreamingState() {
    }

    public static String resolveLiveText(PortalJob job) {
        if (job == null || !job.isRunning()) {
            return "";
        }
        if (job.liveText != null && !job.liveText.isBlank()) {
            return job.liveText;
        }
        if (job.lastMessage != null && !job.lastMessage.isBlank()) {
            return job.lastMessage;
        }
        return "";
    }

    public static List<ChatMessage> applyLiveText(List<ChatMessage> messages, String liveText) {
        List<ChatMessage> updated = new ArrayList<>();
        for (ChatMessage message : messages) {
            if (!message.isEphemeral) {
                updated.add(message);
            }
        }
        if (liveText != null && !liveText.isBlank()) {
            updated.add(new ChatMessage("assistant", liveText, 0L, true));
        }
        return updated;
    }
}
