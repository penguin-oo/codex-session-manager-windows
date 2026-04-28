package com.penguinoo.codexmobile;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.text.InputType;
import android.view.LayoutInflater;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.SwitchCompat;
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
        if (itemId == R.id.action_accounts) {
            showAccountsDialog();
            return true;
        }
        if (itemId == R.id.action_proxy_settings) {
            showProxySettingsDialog();
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

    private void showAccountsDialog() {
        String rawUrl = configStore.getPortalUrl();
        if (rawUrl.isEmpty()) {
            showBanner(getString(R.string.banner_paste_portal));
            return;
        }
        showBanner(getString(R.string.banner_loading_accounts));
        executor.execute(() -> {
            try {
                PortalEndpoint endpoint = PortalEndpoint.parse(rawUrl);
                AccountSlotsPayload payload = apiClient.fetchAccountSlots(endpoint);
                runOnUiThread(() -> presentAccountsDialog(endpoint, payload));
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void showProxySettingsDialog() {
        String rawUrl = configStore.getPortalUrl();
        if (rawUrl.isEmpty()) {
            showBanner(getString(R.string.banner_paste_portal));
            return;
        }
        showBanner(getString(R.string.banner_loading_proxy_settings));
        executor.execute(() -> {
            try {
                PortalEndpoint endpoint = PortalEndpoint.parse(rawUrl);
                PortalProxySettings settings = apiClient.fetchProxySettings(endpoint);
                runOnUiThread(() -> presentProxySettingsDialog(endpoint, settings));
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void presentProxySettingsDialog(PortalEndpoint endpoint, PortalProxySettings settings) {
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        int horizontalPadding = dpToPx(20);
        int verticalPadding = dpToPx(12);
        container.setPadding(horizontalPadding, verticalPadding, horizontalPadding, 0);

        TextView hintView = new TextView(this);
        hintView.setText(R.string.message_proxy_settings_hint);
        container.addView(hintView);

        SwitchCompat enabledSwitch = new SwitchCompat(this);
        enabledSwitch.setText(R.string.label_proxy_enabled);
        enabledSwitch.setChecked(settings.proxyEnabled);
        enabledSwitch.setPadding(0, dpToPx(16), 0, 0);
        container.addView(enabledSwitch);

        EditText portInput = new EditText(this);
        portInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        portInput.setHint(R.string.label_proxy_port);
        portInput.setText(String.valueOf(settings.proxyPort));
        portInput.setSelection(portInput.getText().length());
        portInput.setEnabled(settings.proxyEnabled);
        container.addView(portInput);

        TextView summaryView = new TextView(this);
        summaryView.setText(getString(
                R.string.label_proxy_summary,
                settings.proxySummary == null || settings.proxySummary.isEmpty() ? "direct" : settings.proxySummary
        ));
        summaryView.setPadding(0, dpToPx(16), 0, 0);
        container.addView(summaryView);

        enabledSwitch.setOnCheckedChangeListener((buttonView, isChecked) -> portInput.setEnabled(isChecked));

        new AlertDialog.Builder(this)
                .setTitle(R.string.title_proxy_settings)
                .setView(container)
                .setPositiveButton(R.string.action_save, (dialog, which) -> saveProxySettings(
                        endpoint,
                        enabledSwitch.isChecked(),
                        portInput.getText() == null ? "" : portInput.getText().toString()
                ))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void saveProxySettings(PortalEndpoint endpoint, boolean proxyEnabled, String rawPort) {
        int proxyPort;
        try {
            proxyPort = Integer.parseInt((rawPort == null ? "" : rawPort).trim());
        } catch (NumberFormatException exception) {
            showBanner(getString(R.string.message_proxy_port_required));
            return;
        }
        if (proxyPort < 1 || proxyPort > 65535) {
            showBanner(getString(R.string.message_proxy_port_required));
            return;
        }
        showBanner(getString(R.string.banner_saving_proxy_settings));
        executor.execute(() -> {
            try {
                PortalProxySettings result = apiClient.saveProxySettings(endpoint, proxyEnabled, proxyPort);
                runOnUiThread(() -> {
                    showBanner(getString(
                            R.string.banner_proxy_settings_saved,
                            result.proxySummary == null || result.proxySummary.isEmpty() ? "direct" : result.proxySummary
                    ));
                    loadBootstrap();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void presentAccountsDialog(PortalEndpoint endpoint, AccountSlotsPayload payload) {
        AccountCenterDialogSupport.show(this, payload, new AccountCenterDialogSupport.Callbacks() {
            @Override
            public void onRefresh() {
                refreshCurrentAccount(endpoint);
            }

            @Override
            public void onCreateSlot() {
                promptCreateAccountSlot(endpoint);
            }

            @Override
            public void onBindCurrent(AccountSlotSummary slot) {
                bindCurrentAccount(endpoint, slot);
            }

            @Override
            public void onSwitch(AccountSlotSummary slot) {
                switchAccount(endpoint, slot);
            }

            @Override
            public void onRename(AccountSlotSummary slot) {
                promptRenameAccountSlot(endpoint, slot);
            }

            @Override
            public void onDelete(AccountSlotSummary slot) {
                confirmDeleteAccountSlot(endpoint, slot);
            }

            @Override
            public void onToggleBackendMode(BackendStatusPayload backend) {
                toggleBackendMode(endpoint, backend);
            }

            @Override
            public void onStartBackend() {
                startBackendProxy(endpoint);
            }

            @Override
            public void onStopBackend() {
                stopBackendProxy(endpoint);
            }

            @Override
            public void onRestartBackend() {
                restartBackendProxy(endpoint);
            }
        });
    }

    private void showAccountSlotActions(PortalEndpoint endpoint, AccountSlotSummary slot) {
        List<String> actions = new ArrayList<>();
        actions.add(getString(R.string.action_bind_current_here));
        if (slot.bound) {
            actions.add(getString(R.string.action_switch_here));
        }
        actions.add(getString(R.string.action_rename));
        actions.add(getString(R.string.action_delete));
        new AlertDialog.Builder(this)
                .setTitle(slotDisplayName(slot))
                .setItems(actions.toArray(new CharSequence[0]), (dialog, which) -> {
                    String selected = actions.get(which);
                    if (selected.equals(getString(R.string.action_bind_current_here))) {
                        bindCurrentAccount(endpoint, slot);
                    } else if (selected.equals(getString(R.string.action_switch_here))) {
                        switchAccount(endpoint, slot);
                    } else if (selected.equals(getString(R.string.action_rename))) {
                        promptRenameAccountSlot(endpoint, slot);
                    } else if (selected.equals(getString(R.string.action_delete))) {
                        confirmDeleteAccountSlot(endpoint, slot);
                    }
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void promptCreateAccountSlot(PortalEndpoint endpoint) {
        EditText input = new EditText(this);
        input.setHint(R.string.hint_account_slot_label);
        new AlertDialog.Builder(this)
                .setTitle(R.string.action_new_slot)
                .setView(input)
                .setPositiveButton(R.string.action_save, (dialog, which) -> createAccountSlot(endpoint, input.getText().toString()))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void promptRenameAccountSlot(PortalEndpoint endpoint, AccountSlotSummary slot) {
        EditText input = new EditText(this);
        input.setText(slot.label);
        input.setSelection(input.getText().length());
        new AlertDialog.Builder(this)
                .setTitle(R.string.action_rename)
                .setView(input)
                .setPositiveButton(R.string.action_save, (dialog, which) -> renameAccountSlot(endpoint, slot, input.getText().toString()))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void bindCurrentAccount(PortalEndpoint endpoint, AccountSlotSummary slot) {
        showBanner(getString(R.string.banner_loading_accounts));
        executor.execute(() -> {
            try {
                apiClient.bindCurrentAccount(endpoint, slot.slotId);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_account_bound, slotDisplayName(slot)));
                    loadBootstrap();
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void refreshCurrentAccount(PortalEndpoint endpoint) {
        showBanner(getString(R.string.banner_refreshing_current_login));
        executor.execute(() -> {
            try {
                AccountSlotsPayload payload = apiClient.refreshCurrentAccount(endpoint);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_current_login_refreshed));
                    loadBootstrap();
                    presentAccountsDialog(endpoint, payload);
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void switchAccount(PortalEndpoint endpoint, AccountSlotSummary slot) {
        if (!slot.bound) {
            showBanner(getString(R.string.message_account_not_bound, slotDisplayName(slot)));
            return;
        }
        showBanner(getString(R.string.banner_loading_accounts));
        executor.execute(() -> {
            try {
                apiClient.switchAccount(endpoint, slot.slotId);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_account_switched, slotDisplayName(slot)));
                    loadBootstrap();
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void createAccountSlot(PortalEndpoint endpoint, String rawLabel) {
        String label = rawLabel == null ? "" : rawLabel.trim();
        if (label.isEmpty()) {
            showBanner(getString(R.string.message_account_label_required));
            return;
        }
        showBanner(getString(R.string.banner_loading_accounts));
        executor.execute(() -> {
            try {
                apiClient.createAccountSlot(endpoint, label);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_account_slot_created, label));
                    loadBootstrap();
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void renameAccountSlot(PortalEndpoint endpoint, AccountSlotSummary slot, String rawLabel) {
        String label = rawLabel == null ? "" : rawLabel.trim();
        if (label.isEmpty()) {
            showBanner(getString(R.string.message_account_label_required));
            return;
        }
        showBanner(getString(R.string.banner_loading_accounts));
        executor.execute(() -> {
            try {
                apiClient.renameAccountSlot(endpoint, slot.slotId, label);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_account_slot_renamed, label));
                    loadBootstrap();
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void confirmDeleteAccountSlot(PortalEndpoint endpoint, AccountSlotSummary slot) {
        new AlertDialog.Builder(this)
                .setTitle(R.string.action_delete)
                .setMessage(getString(R.string.message_delete_account_slot, slotDisplayName(slot)))
                .setPositiveButton(R.string.action_delete, (dialog, which) -> {
                    showBanner(getString(R.string.banner_loading_accounts));
                    executor.execute(() -> {
                        try {
                            apiClient.deleteAccountSlot(endpoint, slot.slotId);
                            runOnUiThread(() -> {
                                showBanner(getString(R.string.banner_account_slot_deleted, slotDisplayName(slot)));
                                loadBootstrap();
                                showAccountsDialog();
                            });
                        } catch (Exception exception) {
                            runOnUiThread(() -> showBanner(exception.getMessage()));
                        }
                    });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void toggleBackendMode(PortalEndpoint endpoint, BackendStatusPayload backend) {
        String nextMode = backend.isTokenPoolMode() ? "codex_auth" : "built_in_token_pool";
        int proxyPort = backend.proxyPort > 0 ? backend.proxyPort : 8317;
        showBanner(getString(R.string.banner_loading_backend));
        executor.execute(() -> {
            try {
                apiClient.saveBackendStatus(endpoint, nextMode, backend.tokenDir, proxyPort);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_backend_mode_saved, nextMode));
                    loadBootstrap();
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void startBackendProxy(PortalEndpoint endpoint) {
        showBanner(getString(R.string.banner_loading_backend));
        executor.execute(() -> {
            try {
                apiClient.startBackendProxy(endpoint);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_backend_proxy_started));
                    loadBootstrap();
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void stopBackendProxy(PortalEndpoint endpoint) {
        showBanner(getString(R.string.banner_loading_backend));
        executor.execute(() -> {
            try {
                apiClient.stopBackendProxy(endpoint);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_backend_proxy_stopped));
                    loadBootstrap();
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void restartBackendProxy(PortalEndpoint endpoint) {
        showBanner(getString(R.string.banner_loading_backend));
        executor.execute(() -> {
            try {
                apiClient.restartBackendProxy(endpoint);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_backend_proxy_restarted));
                    loadBootstrap();
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private CharSequence describeAccountSlot(AccountSlotSummary slot) {
        String identity = !slot.email.isEmpty()
                ? slot.email
                : (!slot.accountId.isEmpty() ? slot.accountId : getString(R.string.label_account_unbound));
        String mode = slot.authMode == null || slot.authMode.isEmpty() ? "" : "\nMode: " + slot.authMode;
        String active = slot.active ? "\n" + getString(R.string.label_account_active) : "";
        return slotDisplayName(slot) + "\n" + identity + mode + active;
    }

    private String slotDisplayName(AccountSlotSummary slot) {
        String label = slot.label == null ? "" : slot.label.trim();
        return label.isEmpty() ? slot.slotId : label;
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

    private int dpToPx(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private CodexMobileApp app() {
        return (CodexMobileApp) getApplication();
    }
}

