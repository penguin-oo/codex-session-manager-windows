package com.penguinoo.codexmobile;

import android.content.Context;

import java.util.Collections;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArraySet;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

public final class ReplyMonitor {
    public interface Listener {
        void onReplyingStateChanged();
    }

    private static final long POLL_INTERVAL_SECONDS = 4L;

    private final Context appContext;
    private final PortalApiClient apiClient;
    private final ScheduledExecutorService executor;
    private final Set<Listener> listeners = new CopyOnWriteArraySet<>();
    private final Object lock = new Object();

    private ScheduledFuture<?> pollFuture;
    private String portalUrl = "";
    private PortalEndpoint endpoint;
    private Set<String> previousReplyingSessionIds = Collections.emptySet();
    private boolean primed;

    public ReplyMonitor(Context context) {
        this.appContext = context.getApplicationContext();
        this.apiClient = new PortalApiClient();
        this.executor = Executors.newSingleThreadScheduledExecutor();
    }

    public void start(String rawPortalUrl) {
        String cleanUrl = rawPortalUrl == null ? "" : rawPortalUrl.trim();
        if (cleanUrl.isEmpty()) {
            stop();
            return;
        }
        PortalEndpoint parsedEndpoint = PortalEndpoint.parse(cleanUrl);
        synchronized (lock) {
            if (cleanUrl.equals(portalUrl) && pollFuture != null && !pollFuture.isCancelled()) {
                return;
            }
            portalUrl = cleanUrl;
            endpoint = parsedEndpoint;
            previousReplyingSessionIds = Collections.emptySet();
            primed = false;
            if (pollFuture != null) {
                pollFuture.cancel(true);
            }
            pollFuture = executor.scheduleWithFixedDelay(this::pollOnce, 0L, POLL_INTERVAL_SECONDS, TimeUnit.SECONDS);
        }
    }

    public void stop() {
        synchronized (lock) {
            portalUrl = "";
            endpoint = null;
            previousReplyingSessionIds = Collections.emptySet();
            primed = false;
            if (pollFuture != null) {
                pollFuture.cancel(true);
                pollFuture = null;
            }
        }
    }

    public void addListener(Listener listener) {
        listeners.add(listener);
    }

    public void removeListener(Listener listener) {
        listeners.remove(listener);
    }

    private void pollOnce() {
        PortalEndpoint currentEndpoint;
        String currentPortalUrl;
        Set<String> previousIds;
        boolean wasPrimed;
        synchronized (lock) {
            currentEndpoint = endpoint;
            currentPortalUrl = portalUrl;
            previousIds = previousReplyingSessionIds;
            wasPrimed = primed;
        }
        if (currentEndpoint == null || currentPortalUrl.isEmpty()) {
            return;
        }
        try {
            PortalBootstrap bootstrap = apiClient.fetchBootstrap(currentEndpoint);
            Set<String> currentIds = ReplyMonitorState.replyingSessionIds(bootstrap.sessions);
            List<SessionSummary> completed = wasPrimed
                    ? ReplyMonitorState.completedSessions(previousIds, bootstrap.sessions)
                    : Collections.emptyList();
            boolean changed = wasPrimed && !currentIds.equals(previousIds);
            synchronized (lock) {
                if (!currentPortalUrl.equals(portalUrl)) {
                    return;
                }
                previousReplyingSessionIds = currentIds;
                primed = true;
            }
            for (SessionSummary session : completed) {
                ReplyNotificationSupport.showReplyNotification(appContext, currentPortalUrl, session);
            }
            if (changed) {
                notifyListeners();
            }
        } catch (Exception ignored) {
        }
    }

    private void notifyListeners() {
        for (Listener listener : listeners) {
            try {
                listener.onReplyingStateChanged();
            } catch (Exception ignored) {
            }
        }
    }
}