package com.penguinoo.codexmobile;

import android.app.Application;

public final class CodexMobileApp extends Application {
    private ReplyMonitor replyMonitor;

    @Override
    public void onCreate() {
        super.onCreate();
        replyMonitor = new ReplyMonitor(this);
    }

    public ReplyMonitor getReplyMonitor() {
        return replyMonitor;
    }
}