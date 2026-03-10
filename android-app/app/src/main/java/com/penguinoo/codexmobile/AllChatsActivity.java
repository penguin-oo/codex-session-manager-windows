package com.penguinoo.codexmobile;

import android.content.Intent;
import android.os.Bundle;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.penguinoo.codexmobile.databinding.ActivityAllChatsBinding;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class AllChatsActivity extends AppCompatActivity {
    public static final String EXTRA_PORTAL_URL = "portal_url";

    private ActivityAllChatsBinding binding;
    private PortalApiClient apiClient;
    private ExecutorService executor;
    private SessionListAdapter adapter;
    private PortalEndpoint endpoint;
    private final ReplyMonitor.Listener replyMonitorListener = () -> runOnUiThread(this::loadChats);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        binding = ActivityAllChatsBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        String portalUrl = getIntent().getStringExtra(EXTRA_PORTAL_URL);
        if (portalUrl == null || portalUrl.isEmpty()) {
            finish();
            return;
        }
        endpoint = PortalEndpoint.parse(portalUrl);

        apiClient = new PortalApiClient();
        executor = Executors.newSingleThreadExecutor();

        setSupportActionBar(binding.toolbar);
        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setTitle(R.string.title_all_chats);
            getSupportActionBar().setSubtitle(R.string.subtitle_all_chats);
        }

        adapter = new SessionListAdapter(this::openChat);
        binding.sessionRecyclerView.setLayoutManager(new LinearLayoutManager(this));
        binding.sessionRecyclerView.setAdapter(adapter);

        ((CodexMobileApp) getApplication()).getReplyMonitor().start(endpoint.getRawUrl());
        loadChats();
    }

    @Override
    protected void onStart() {
        super.onStart();
        ((CodexMobileApp) getApplication()).getReplyMonitor().addListener(replyMonitorListener);
    }

    @Override
    protected void onResume() {
        super.onResume();
        loadChats();
    }

    @Override
    protected void onStop() {
        super.onStop();
        ((CodexMobileApp) getApplication()).getReplyMonitor().removeListener(replyMonitorListener);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        executor.shutdownNow();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        getMenuInflater().inflate(R.menu.menu_all_chats, menu);
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(@NonNull MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            finish();
            return true;
        }
        if (item.getItemId() == R.id.action_refresh) {
            loadChats();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    private void loadChats() {
        showBanner(getString(R.string.banner_loading_chats));
        executor.execute(() -> {
            try {
                PortalBootstrap bootstrap = apiClient.fetchBootstrap(endpoint);
                runOnUiThread(() -> {
                    adapter.submitList(bootstrap.sessions);
                    boolean isEmpty = bootstrap.sessions.isEmpty();
                    binding.emptyView.setVisibility(isEmpty ? View.VISIBLE : View.GONE);
                    binding.sessionRecyclerView.setVisibility(isEmpty ? View.GONE : View.VISIBLE);
                    showBanner(getString(R.string.banner_connected));
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void openChat(SessionSummary session) {
        Intent intent = new Intent(this, ChatActivity.class);
        intent.putExtra(ChatActivity.EXTRA_PORTAL_URL, endpoint.getRawUrl());
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
}

