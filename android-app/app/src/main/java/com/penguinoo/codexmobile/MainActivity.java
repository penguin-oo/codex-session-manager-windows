package com.penguinoo.codexmobile;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.view.Menu;
import android.view.MenuItem;
import android.view.LayoutInflater;
import android.view.View;
import android.widget.TextView;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.penguinoo.codexmobile.databinding.ActivityMainBinding;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends AppCompatActivity {
    private static final int RECENT_CHAT_LIMIT = 3;
    private final ActivityResultLauncher<String> requestNotificationsPermissionLauncher =
            registerForActivityResult(new ActivityResultContracts.RequestPermission(), granted -> {
            });

    private ActivityMainBinding binding;
    private PortalConfigStore configStore;
    private PortalApiClient apiClient;
    private ExecutorService executor;
    private RecentSessionAdapter recentAdapter;
    private PortalBootstrap bootstrap;
    private final ReplyMonitor.Listener replyMonitorListener = () -> runOnUiThread(this::loadBootstrap);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        binding = ActivityMainBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        configStore = new PortalConfigStore(this);
        apiClient = new PortalApiClient();
        executor = Executors.newSingleThreadExecutor();
        ensureNotificationPermission();

        setSupportActionBar(binding.toolbar);
        binding.toolbar.setTitle(R.string.app_name);
        binding.toolbar.setSubtitle(R.string.home_subtitle);

        recentAdapter = new RecentSessionAdapter(this::openChat);
        binding.recentRecyclerView.setLayoutManager(new LinearLayoutManager(this));
        binding.recentRecyclerView.setAdapter(recentAdapter);
        binding.recentRecyclerView.setNestedScrollingEnabled(false);

        binding.connectButton.setOnClickListener(view -> connectAndLoad(true));
        binding.manageConnectionButton.setOnClickListener(view -> showConnectionEditor(true));
        binding.actionRecentCard.setOnClickListener(view -> openLatestChat());
        binding.actionAllChatsCard.setOnClickListener(view -> openAllChats());
        binding.actionNewChatCard.setOnClickListener(view -> openNewChat());

        binding.portalUrlInput.setText(configStore.getPortalUrl());
        refreshPortalHistorySuggestions();
        if (configStore.getPortalUrl().isEmpty()) {
            showDisconnectedState();
            showBanner(getString(R.string.banner_paste_portal));
        } else {
            startReplyMonitor();
            showConnectionEditor(false);
            loadBootstrap();
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        app().getReplyMonitor().addListener(replyMonitorListener);
    }

    @Override
    protected void onResume() {
        super.onResume();
        ensureNotificationPermission();
        if (!configStore.getPortalUrl().isEmpty()) {
            startReplyMonitor();
            loadBootstrap();
        }
    }

    @Override
    protected void onStop() {
        super.onStop();
        app().getReplyMonitor().removeListener(replyMonitorListener);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        executor.shutdownNow();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        getMenuInflater().inflate(R.menu.menu_main, menu);
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(@NonNull MenuItem item) {
        int itemId = item.getItemId();
        if (itemId == R.id.action_refresh) {
            loadBootstrap();
            return true;
        }
        if (itemId == R.id.action_connection) {
            showConnectionEditor(true);
            return true;
        }
        if (itemId == R.id.action_clear_saved) {
            configStore.clearPortalUrl();
            configStore.clearRecentPortalUrls();
            app().getReplyMonitor().stop();
            binding.portalUrlInput.setText("");
            refreshPortalHistorySuggestions();
            bootstrap = null;
            recentAdapter.submitList(Collections.emptyList());
            showDisconnectedState();
            showBanner(getString(R.string.banner_saved_portal_cleared));
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    private void connectAndLoad(boolean saveConfig) {
        String rawUrl = binding.portalUrlInput.getText() == null ? "" : binding.portalUrlInput.getText().toString();
        try {
            PortalEndpoint.parse(rawUrl);
        } catch (IllegalArgumentException exception) {
            showBanner(exception.getMessage());
            return;
        }
        if (saveConfig) {
            configStore.rememberPortalUrl(rawUrl);
            refreshPortalHistorySuggestions();
        }
        startReplyMonitor();
        binding.portalUrlInput.clearFocus();
        showConnectionEditor(false);
        loadBootstrap();
    }

    private void loadBootstrap() {
        String rawUrl = configStore.getPortalUrl();
        if (rawUrl.isEmpty()) {
            showDisconnectedState();
            return;
        }
        showBanner(getString(R.string.banner_loading_home));
        executor.execute(() -> {
            try {
                PortalEndpoint endpoint = PortalEndpoint.parse(rawUrl);
                PortalBootstrap result = apiClient.fetchBootstrap(endpoint);
                runOnUiThread(() -> renderBootstrap(result));
            } catch (Exception exception) {
                runOnUiThread(() -> {
                    showDisconnectedState();
                    showBanner(exception.getMessage());
                });
            }
        });
    }

    private void renderBootstrap(PortalBootstrap bootstrap) {
        this.bootstrap = bootstrap;
        List<SessionSummary> recentChats = SessionCollections.recentChats(bootstrap.sessions, RECENT_CHAT_LIMIT);
        recentAdapter.submitList(recentChats);
        binding.connectionPanelTitleText.setText(R.string.connection_ready_title);
        binding.connectionSummaryText.setText(getString(R.string.connection_ready_summary, bootstrap.sessions.size()));
        binding.recentEmptyView.setVisibility(recentChats.isEmpty() ? View.VISIBLE : View.GONE);
        binding.recentRecyclerView.setVisibility(recentChats.isEmpty() ? View.GONE : View.VISIBLE);
        binding.quickActionsHeaderText.setVisibility(View.VISIBLE);
        binding.quickActionsContainer.setVisibility(View.VISIBLE);
        binding.recentSectionTitle.setVisibility(View.VISIBLE);
        showConnectionEditor(false);
        showBanner(getString(R.string.banner_connected));
    }

    private void showDisconnectedState() {
        binding.connectionPanelTitleText.setText(R.string.connection_needed_title);
        binding.connectionSummaryText.setText(R.string.connection_needed_summary);
        recentAdapter.submitList(Collections.emptyList());
        binding.quickActionsHeaderText.setVisibility(View.GONE);
        binding.quickActionsContainer.setVisibility(View.GONE);
        binding.recentSectionTitle.setVisibility(View.GONE);
        binding.recentEmptyView.setVisibility(View.GONE);
        binding.recentRecyclerView.setVisibility(View.GONE);
        showConnectionEditor(true);
    }

    private void showConnectionEditor(boolean editing) {
        binding.connectionFormGroup.setVisibility(editing ? View.VISIBLE : View.GONE);
        binding.manageConnectionButton.setVisibility(editing ? View.GONE : View.VISIBLE);
        boolean hasRecentConnections = !PortalConnectionHistoryState.suggestions(
                configStore.getPortalUrl(),
                configStore.getRecentPortalUrls()
        ).isEmpty();
        binding.recentConnectionsGroup.setVisibility(editing && hasRecentConnections ? View.VISIBLE : View.GONE);
        if (editing) {
            binding.portalUrlInput.requestFocus();
        }
    }

    private void refreshPortalHistorySuggestions() {
        List<String> suggestions = PortalConnectionHistoryState.suggestions(
                configStore.getPortalUrl(),
                configStore.getRecentPortalUrls()
        );
        binding.recentConnectionsContainer.removeAllViews();
        LayoutInflater inflater = LayoutInflater.from(this);
        for (String suggestion : suggestions) {
            TextView itemView = (TextView) inflater.inflate(
                    R.layout.item_portal_history,
                    binding.recentConnectionsContainer,
                    false
            );
            itemView.setText(suggestion);
            itemView.setOnClickListener(view -> {
                binding.portalUrlInput.setText(suggestion);
                connectAndLoad(true);
            });
            binding.recentConnectionsContainer.addView(itemView);
        }
        boolean editing = binding.connectionFormGroup.getVisibility() == View.VISIBLE;
        binding.recentConnectionsGroup.setVisibility(editing && !suggestions.isEmpty() ? View.VISIBLE : View.GONE);
    }

    private void openLatestChat() {
        if (bootstrap == null || bootstrap.sessions.isEmpty()) {
            showBanner(getString(R.string.banner_no_recent_chats));
            return;
        }
        openChat(SessionCollections.recentChats(bootstrap.sessions, 1).get(0));
    }

    private void openAllChats() {
        if (configStore.getPortalUrl().isEmpty()) {
            showBanner(getString(R.string.banner_paste_portal));
            return;
        }
        Intent intent = new Intent(this, AllChatsActivity.class);
        intent.putExtra(AllChatsActivity.EXTRA_PORTAL_URL, configStore.getPortalUrl());
        startActivity(intent);
    }

    private void openNewChat() {
        if (bootstrap == null) {
            showBanner(getString(R.string.banner_loading_home));
            return;
        }
        Intent intent = new Intent(this, NewChatActivity.class);
        intent.putExtra(NewChatActivity.EXTRA_PORTAL_URL, configStore.getPortalUrl());
        intent.putStringArrayListExtra(NewChatActivity.EXTRA_MODELS, new ArrayList<>(bootstrap.models));
        intent.putStringArrayListExtra(NewChatActivity.EXTRA_APPROVALS, new ArrayList<>(bootstrap.approvalOptions));
        intent.putStringArrayListExtra(NewChatActivity.EXTRA_SANDBOXES, new ArrayList<>(bootstrap.sandboxOptions));
        intent.putStringArrayListExtra(NewChatActivity.EXTRA_REASONINGS, new ArrayList<>(bootstrap.reasoningOptions));
        String defaultCwd = "";
        for (SessionSummary session : bootstrap.sessions) {
            if (session.cwd != null && !session.cwd.isEmpty()) {
                defaultCwd = session.cwd;
                break;
            }
        }
        intent.putExtra(NewChatActivity.EXTRA_DEFAULT_CWD, defaultCwd);
        startActivity(intent);
    }

    private void openChat(SessionSummary session) {
        Intent intent = new Intent(this, ChatActivity.class);
        intent.putExtra(ChatActivity.EXTRA_PORTAL_URL, configStore.getPortalUrl());
        intent.putExtra(ChatActivity.EXTRA_SESSION_ID, session.sessionId);
        startActivity(intent);
    }

    private void showBanner(String message) {
        if (message == null || message.isEmpty()) {
            binding.statusBanner.setVisibility(View.GONE);
            binding.statusBanner.setText("");
            return;
        }
        binding.statusBanner.setVisibility(View.VISIBLE);
        binding.statusBanner.setText(message);
    }

    private void ensureNotificationPermission() {
        ReplyNotificationSupport.ensureChannel(this);
        if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.TIRAMISU) {
            return;
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
            return;
        }
        requestNotificationsPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS);
    }

    private void startReplyMonitor() {
        app().getReplyMonitor().start(configStore.getPortalUrl());
    }

    private CodexMobileApp app() {
        return (CodexMobileApp) getApplication();
    }
}

