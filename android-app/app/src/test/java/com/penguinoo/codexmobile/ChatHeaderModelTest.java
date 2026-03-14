package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class ChatHeaderModelTest {
    @Test
    public void metadataLine_includesLaunchSettingsAndProxySummary() {
        SessionSummary session = new SessionSummary(
                "session-1",
                1L,
                "hello",
                "",
                "D:\\project",
                "gpt-5.4",
                "never",
                "danger-full-access",
                "xhigh",
                false
        );

        String metadata = ChatHeaderModel.metadataLine(session, "socks5h://127.0.0.1:7897");

        assertEquals(
                "D:\\project\nModel gpt-5.4 | Approval never | Sandbox danger-full-access | Reasoning xhigh | Proxy socks5h://127.0.0.1:7897",
                metadata
        );
    }

    @Test
    public void metadataLine_prefersNoteAsPrimaryLine() {
        SessionSummary session = new SessionSummary(
                "session-1",
                1L,
                "hello",
                "movie export",
                "D:\\project",
                "default",
                "default",
                "default",
                "default",
                false
        );

        String metadata = ChatHeaderModel.metadataLine(session, "default");

        assertEquals(
                "movie export\nModel default | Approval default | Sandbox default | Reasoning default | Proxy default",
                metadata
        );
    }
}
