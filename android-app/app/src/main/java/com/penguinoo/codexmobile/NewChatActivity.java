package com.penguinoo.codexmobile;

import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.ArrayAdapter;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;

import com.penguinoo.codexmobile.databinding.ActivityNewChatBinding;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class NewChatActivity extends AppCompatActivity {
    public static final String EXTRA_PORTAL_URL = "portal_url";
    public static final String EXTRA_MODELS = "models";
    public static final String EXTRA_APPROVALS = "approvals";
    public static final String EXTRA_SANDBOXES = "sandboxes";
    public static final String EXTRA_REASONINGS = "reasonings";
    public static final String EXTRA_DEFAULT_CWD = "default_cwd";

    private ActivityNewChatBinding binding;
    private PortalApiClient apiClient;
    private ExecutorService executor;
    private PortalEndpoint endpoint;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        binding = ActivityNewChatBinding.inflate(getLayoutInflater());
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
            getSupportActionBar().setTitle(R.string.title_new_chat);
            getSupportActionBar().setSubtitle(R.string.subtitle_new_chat);
        }

        binding.cwdInput.setText(getIntent().getStringExtra(EXTRA_DEFAULT_CWD));
        setupSpinner(binding.modelSpinner, getIntent().getStringArrayListExtra(EXTRA_MODELS), defaultValues("default"));
        setupSpinner(binding.approvalSpinner, getIntent().getStringArrayListExtra(EXTRA_APPROVALS), defaultValues("default", "on-request", "never"));
        setupSpinner(binding.sandboxSpinner, getIntent().getStringArrayListExtra(EXTRA_SANDBOXES), defaultValues("default", "workspace-write", "danger-full-access"));
        setupSpinner(binding.reasoningSpinner, getIntent().getStringArrayListExtra(EXTRA_REASONINGS), defaultValues("default", "low", "medium", "high", "xhigh"));
        binding.browseCwdButton.setOnClickListener(view -> browseFolders(textValue(binding.cwdInput)));
        binding.createChatButton.setOnClickListener(view -> createChat());
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        executor.shutdownNow();
    }

    @Override
    public boolean onOptionsItemSelected(@NonNull android.view.MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            finish();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    private void setupSpinner(android.widget.Spinner spinner, ArrayList<String> values, List<String> fallback) {
        List<String> source = values == null || values.isEmpty() ? fallback : values;
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, source);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(adapter);
    }

    private ArrayList<String> defaultValues(String... values) {
        ArrayList<String> items = new ArrayList<>();
        for (String value : values) {
            items.add(value);
        }
        return items;
    }

    private void createChat() {
        String cwd = textValue(binding.cwdInput);
        String prompt = textValue(binding.promptInput);
        if (!NewChatFormState.isReady(cwd, prompt)) {
            showBanner(getString(R.string.banner_new_chat_incomplete));
            return;
        }
        setFormEnabled(false);
        showBanner(getString(R.string.banner_creating_chat));
        executor.execute(() -> {
            try {
                PortalJob queuedJob = apiClient.createChat(
                        endpoint,
                        cwd,
                        prompt,
                        textValue(binding.noteInput),
                        String.valueOf(binding.modelSpinner.getSelectedItem()),
                        String.valueOf(binding.approvalSpinner.getSelectedItem()),
                        String.valueOf(binding.sandboxSpinner.getSelectedItem()),
                        String.valueOf(binding.reasoningSpinner.getSelectedItem())
                );
                PortalJob finalJob = queuedJob;
                while (!NewChatLaunchState.shouldOpenChat(finalJob) && finalJob.isRunning()) {
                    Thread.sleep(1800L);
                    finalJob = apiClient.fetchJob(endpoint, queuedJob.jobId);
                }
                if (NewChatLaunchState.shouldOpenChat(finalJob)) {
                    String createdSessionId = finalJob.sessionId;
                    runOnUiThread(() -> {
                        Intent intent = new Intent(this, ChatActivity.class);
                        intent.putExtra(ChatActivity.EXTRA_PORTAL_URL, endpoint.getRawUrl());
                        intent.putExtra(ChatActivity.EXTRA_SESSION_ID, createdSessionId);
                        startActivity(intent);
                        finish();
                    });
                    return;
                }
                if (!finalJob.isCompleted() || finalJob.sessionId == null || finalJob.sessionId.isEmpty()) {
                    PortalJob failedJob = finalJob;
                    runOnUiThread(() -> {
                        setFormEnabled(true);
                        showBanner(failedJob.error == null || failedJob.error.isEmpty() ? getString(R.string.banner_create_failed) : failedJob.error);
                    });
                    return;
                }
            } catch (Exception exception) {
                runOnUiThread(() -> {
                    setFormEnabled(true);
                    showBanner(exception.getMessage());
                });
            }
        });
    }

    private void browseFolders(String path) {
        showBanner(getString(R.string.banner_loading_folders));
        executor.execute(() -> {
            try {
                DirectoryListing listing = apiClient.browseDirectory(endpoint, path);
                runOnUiThread(() -> {
                    showBanner("");
                    showDirectoryBrowser(listing);
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void showDirectoryBrowser(DirectoryListing listing) {
        CharSequence[] items = new CharSequence[listing.directories.size()];
        for (int index = 0; index < listing.directories.size(); index++) {
            DirectoryEntry entry = listing.directories.get(index);
            items[index] = entry.name == null || entry.name.isEmpty() ? entry.path : entry.name;
        }
        AlertDialog.Builder builder = new AlertDialog.Builder(this)
                .setTitle(listing.path == null || listing.path.isEmpty() ? getString(R.string.title_browse_folders) : listing.path)
                .setNegativeButton(android.R.string.cancel, null);
        if (listing.path != null && !listing.path.isEmpty()) {
            builder.setPositiveButton(R.string.action_use_folder, (dialog, which) -> {
                binding.cwdInput.setText(listing.path);
                showBanner(getString(R.string.banner_folder_selected));
            });
        }
        if (listing.parentPath != null && !listing.parentPath.isEmpty()) {
            builder.setNeutralButton(R.string.action_up, (dialog, which) -> browseFolders(listing.parentPath));
        }
        if (items.length == 0) {
            builder.setMessage(R.string.message_no_subfolders);
        } else {
            builder.setItems(items, (dialog, which) -> browseFolders(listing.directories.get(which).path));
        }
        builder.show();
    }

    private void setFormEnabled(boolean enabled) {
        binding.cwdInput.setEnabled(enabled);
        binding.promptInput.setEnabled(enabled);
        binding.noteInput.setEnabled(enabled);
        binding.modelSpinner.setEnabled(enabled);
        binding.approvalSpinner.setEnabled(enabled);
        binding.sandboxSpinner.setEnabled(enabled);
        binding.reasoningSpinner.setEnabled(enabled);
        binding.browseCwdButton.setEnabled(enabled);
        binding.createChatButton.setEnabled(enabled);
    }

    private String textValue(android.widget.EditText editText) {
        return editText.getText() == null ? "" : editText.getText().toString().trim();
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

