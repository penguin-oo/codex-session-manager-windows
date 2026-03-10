package com.penguinoo.codexmobile;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;

public final class ReplyNotificationSupport {
    public static final String REPLY_NOTIFICATION_CHANNEL_ID = "codex_reply_notifications";

    private ReplyNotificationSupport() {
    }

    public static void ensureChannel(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) {
            return;
        }
        NotificationChannel channel = manager.getNotificationChannel(REPLY_NOTIFICATION_CHANNEL_ID);
        if (channel != null) {
            return;
        }
        channel = new NotificationChannel(
                REPLY_NOTIFICATION_CHANNEL_ID,
                context.getString(R.string.notification_reply_channel_name),
                NotificationManager.IMPORTANCE_DEFAULT
        );
        channel.setDescription(context.getString(R.string.notification_reply_channel_description));
        manager.createNotificationChannel(channel);
    }

    public static boolean canPostNotifications(Context context) {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) {
            return false;
        }
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU
                || ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
    }

    public static void showReplyNotification(Context context, String portalUrl, SessionSummary session) {
        if (session == null || session.sessionId == null || session.sessionId.isEmpty()) {
            return;
        }
        ensureChannel(context);
        if (!canPostNotifications(context)) {
            return;
        }
        String displayTitle = SessionCollections.displayTitle(session);
        String title = context.getString(R.string.notification_reply_title, displayTitle);
        String body = context.getString(R.string.notification_reply_completed_body);
        Intent intent = new Intent(context, ChatActivity.class)
                .putExtra(ChatActivity.EXTRA_PORTAL_URL, portalUrl)
                .putExtra(ChatActivity.EXTRA_SESSION_ID, session.sessionId)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                context,
                session.sessionId.hashCode(),
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, REPLY_NOTIFICATION_CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_chat)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
                .setContentIntent(pendingIntent)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_DEFAULT);
        NotificationManagerCompat.from(context).notify(session.sessionId.hashCode(), builder.build());
    }
}