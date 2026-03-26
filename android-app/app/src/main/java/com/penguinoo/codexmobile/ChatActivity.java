package com.penguinoo.codexmobile;

import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Menu;
import android.view.MenuItem;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.penguinoo.codexmobile.databinding.ActivityChatBinding;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class ChatActivity extends AppCompatActivity {
    public static final String EXTRA_PORTAL_URL = "portal_url";
    public static final String EXTRA_SESSION_ID = "session_id";
    private static final long HEARTBEAT_INTERVAL_MS = 10_000L;
    private static final int MAX_IMAGE_BYTES = 8 * 1024 * 1024;

    private final ActivityResultLauncher<String[]> pickImageLauncher =
            registerForActivityResult(new ActivityResultContracts.OpenDocument(), this::handlePickedImage);

    private ActivityChatBinding binding;
    private PortalApiClient apiClient;
    private ChatDraftStore draftStore;
    private ExecutorService executor;
    private ExecutorService jobExecutor;
    private ChatMessageAdapter adapter;
    private PortalEndpoint endpoint;
    private String sessionId;
    private SessionSummary currentSession;
    private SessionLease currentLease;
    private ChatMessage pendingUserMessage;
    private ChatImageAttachment selectedImageAttachment;
    private Uri selectedImageUri;
    private String selectedImageDisplayName = "";
    private String attachedJobId = "";
    private String watchingJobId = "";
    private int watchGeneration = 0;
    private int messageListBaseBottomPadding;
    private int composerBaseBottomMargin;
    private boolean autoFollowConversation = true;
    private boolean isActivityVisible = false;
    private boolean suppressDraftPersistence = false;
    private int heartbeatFailureCount = 0;
    private int watchFailureCount = 0;
    private List<String> sessionModelOptions = new ArrayList<>();
    private List<String> sessionApprovalOptions = new ArrayList<>();
    private List<String> sessionSandboxOptions = new ArrayList<>();
    private List<String> sessionReasoningOptions = new ArrayList<>();
    private String currentProxySummary = "";
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final List<ChatMessage> persistedMessages = new ArrayList<>();
    private String stickyBanner = "";
    private final Runnable heartbeatRunnable = new Runnable() {
        @Override
        public void run() {
            SessionLease lease = currentLease;
            if (lease == null) {
                return;
            }
            executor.execute(() -> {
                try {
                    currentLease = apiClient.heartbeatSession(endpoint, sessionId, lease.leaseId);
                    heartbeatFailureCount = ChatHeartbeatState.nextFailureCount(true, heartbeatFailureCount);
                } catch (Exception exception) {
                    heartbeatFailureCount = ChatHeartbeatState.nextFailureCount(false, heartbeatFailureCount);
                    if (ChatHeartbeatState.shouldInvalidateLease(heartbeatFailureCount)) {
                        runOnUiThread(() -> handlePortalUnavailable(exception.getMessage()));
                        return;
                    }
                    runOnUiThread(() -> showBanner("Lease heartbeat missed. Retrying..."));
                    mainHandler.postDelayed(this, HEARTBEAT_INTERVAL_MS);
                    return;
                }
                mainHandler.postDelayed(this, HEARTBEAT_INTERVAL_MS);
            });
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        binding = ActivityChatBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        apiClient = new PortalApiClient();
        draftStore = new ChatDraftStore(this);
        executor = Executors.newSingleThreadExecutor();
        jobExecutor = Executors.newSingleThreadExecutor();

        String portalUrl = getIntent().getStringExtra(EXTRA_PORTAL_URL);
        sessionId = getIntent().getStringExtra(EXTRA_SESSION_ID);
        if (portalUrl == null || sessionId == null || sessionId.isEmpty()) {
            finish();
            return;
        }
        endpoint = PortalEndpoint.parse(portalUrl);
        ((CodexMobileApp) getApplication()).getReplyMonitor().start(portalUrl);

        setSupportActionBar(binding.toolbar);
        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setTitle("Chat");
        }

        adapter = new ChatMessageAdapter(this::openLocalPathsOnPhone);
        LinearLayoutManager layoutManager = new LinearLayoutManager(this);
        binding.messageRecyclerView.setLayoutManager(layoutManager);
        binding.messageRecyclerView.setAdapter(adapter);
        binding.messageRecyclerView.addOnScrollListener(new androidx.recyclerview.widget.RecyclerView.OnScrollListener() {
            @Override
            public void onScrolled(@NonNull androidx.recyclerview.widget.RecyclerView recyclerView, int dx, int dy) {
                autoFollowConversation = shouldAutoFollowConversation();
                updateScrollJumpButtons();
            }
        });

        messageListBaseBottomPadding = binding.messageRecyclerView.getPaddingBottom();
        ViewGroup.MarginLayoutParams composerLayoutParams = (ViewGroup.MarginLayoutParams) binding.composerPanel.getLayoutParams();
        composerBaseBottomMargin = composerLayoutParams.bottomMargin;

        binding.sendButton.setOnClickListener(view -> sendMessage());
        binding.stopButton.setOnClickListener(view -> stopReply());
        binding.attachImageButton.setOnClickListener(view -> pickImageLauncher.launch(new String[]{"image/*"}));
        binding.clearAttachmentButton.setOnClickListener(view -> clearSelectedImage());
        binding.jumpToTopButton.setOnClickListener(view -> jumpConversationToTop());
        binding.jumpToBottomButton.setOnClickListener(view -> jumpConversationToBottom());
        binding.fastScrollTrackContainer.setOnTouchListener((view, event) -> handleFastScrollTouch(event));
        binding.messageInput.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {
            }

            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
            }

            @Override
            public void afterTextChanged(Editable s) {
                if (!suppressDraftPersistence) {
                    persistDraft();
                }
            }
        });
        binding.composerPanel.addOnLayoutChangeListener((view, left, top, right, bottom, oldLeft, oldTop, oldRight, oldBottom) -> {
            if ((bottom - top) != (oldBottom - oldTop)) {
                scrollConversationToBottom(autoFollowConversation);
            }
        });

        setupInsets();
        updateAttachmentPreview();
        restoreDraft();
        updateScrollJumpButtons();
        claimSessionAndLoad();
    }

    @Override
    protected void onResume() {
        super.onResume();
        isActivityVisible = true;
        if (currentLease != null) {
            startLeaseHeartbeat();
        }
        if (ChatResumeState.shouldReloadSessionOnResume(currentSession != null)) {
            loadSession();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        isActivityVisible = false;
        mainHandler.removeCallbacks(heartbeatRunnable);
        persistDraft();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        mainHandler.removeCallbacks(heartbeatRunnable);
        SessionLease lease = currentLease;
        if (lease != null && attachedJobId.isEmpty()) {
            Executors.newSingleThreadExecutor().execute(() -> {
                try {
                    apiClient.releaseSession(endpoint, sessionId, lease.leaseId);
                } catch (Exception ignored) {
                }
            });
        }
        executor.shutdownNow();
        jobExecutor.shutdownNow();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        getMenuInflater().inflate(R.menu.menu_chat, menu);
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(@NonNull MenuItem item) {
        int itemId = item.getItemId();
        if (itemId == android.R.id.home) {
            finish();
            return true;
        }
        if (itemId == R.id.action_refresh) {
            if (currentLease == null) {
                claimSessionAndLoad();
            } else {
                loadSession();
            }
            return true;
        }
        if (itemId == R.id.action_refresh_desktop) {
            requestDesktopRefresh();
            return true;
        }
        if (itemId == R.id.action_accounts) {
            showAccountsDialog();
            return true;
        }
        if (itemId == R.id.action_session_settings) {
            editSessionSettings();
            return true;
        }
        if (itemId == R.id.action_edit_note) {
            editNote();
            return true;
        }
        if (itemId == R.id.action_delete) {
            confirmDelete();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    private void setupInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(binding.getRoot(), (view, windowInsets) -> {
            Insets systemBars = windowInsets.getInsets(WindowInsetsCompat.Type.systemBars());
            Insets ime = windowInsets.getInsets(WindowInsetsCompat.Type.ime());
            int extraImeInset = ChatLayoutState.extraImeInset(systemBars.bottom, ime.bottom);
            view.setPadding(
                    view.getPaddingLeft(),
                    ChatLayoutState.contentTopPadding(systemBars.top),
                    view.getPaddingRight(),
                    view.getPaddingBottom()
            );
            binding.composerPanel.setTranslationY(-extraImeInset);
            binding.scrollJumpButtons.setTranslationY(-extraImeInset);
            binding.fastScrollTrackContainer.setTranslationY(-extraImeInset);
            ViewGroup.MarginLayoutParams composerLayoutParams = (ViewGroup.MarginLayoutParams) binding.composerPanel.getLayoutParams();
            composerLayoutParams.bottomMargin = composerBaseBottomMargin + systemBars.bottom;
            binding.composerPanel.setLayoutParams(composerLayoutParams);

            binding.messageRecyclerView.setPadding(
                    binding.messageRecyclerView.getPaddingLeft(),
                    binding.messageRecyclerView.getPaddingTop(),
                    binding.messageRecyclerView.getPaddingRight(),
                    ChatLayoutState.recyclerBottomPadding(messageListBaseBottomPadding, systemBars.bottom, ime.bottom)
            );
            scrollConversationToBottom(autoFollowConversation);
            updateScrollJumpButtons();
            return windowInsets;
        });
        ViewCompat.requestApplyInsets(binding.getRoot());
    }

    private void loadSession() {
        showBanner("Loading conversation...");
        executor.execute(() -> {
            try {
                SessionPayload payload = apiClient.fetchSession(endpoint, sessionId);
                runOnUiThread(() -> renderPayload(payload));
            } catch (Exception exception) {
                runOnUiThread(() -> handlePortalUnavailable(exception.getMessage()));
            }
        });
    }

    private void renderPayload(SessionPayload payload) {
        currentSession = payload.session;
        sessionModelOptions = new ArrayList<>(payload.modelOptions);
        sessionApprovalOptions = new ArrayList<>(payload.approvalOptions);
        sessionSandboxOptions = new ArrayList<>(payload.sandboxOptions);
        sessionReasoningOptions = new ArrayList<>(payload.reasoningOptions);
        currentProxySummary = payload.proxySummary == null ? "" : payload.proxySummary;
        if (payload.session != null && payload.session.sessionId != null && !payload.session.sessionId.isEmpty()) {
            adoptSessionId(payload.session.sessionId);
        }
        if (getSupportActionBar() != null) {
            getSupportActionBar().setTitle(SessionCollections.displayTitle(payload.session));
            getSupportActionBar().setSubtitle("");
        }
        String metadata = ChatHeaderModel.metadataLine(payload.session, payload.proxySummary);
        binding.headerMetaText.setText(metadata);
        binding.headerMetaText.setVisibility(metadata.isEmpty() ? View.GONE : View.VISIBLE);
        persistedMessages.clear();
        persistedMessages.addAll(payload.messages);
        PortalJob activeJob = payload.activeJob;
        if (activeJob != null && activeJob.isRunning()) {
            attachedJobId = activeJob.jobId;
            setComposerEnabled(false);
            String liveText = ChatStreamingState.resolveLiveText(activeJob);
            renderConversation(liveText);
            startWatchingJob(activeJob);
            showBanner(!liveText.isEmpty()
                    ? "Codex is replying..."
                    : "Codex is thinking...");
            return;
        }
        attachedJobId = "";
        watchingJobId = "";
        setComposerEnabled(currentLease != null);
        renderConversation(null);
        if (stickyBanner != null && !stickyBanner.isEmpty()) {
            showBanner(stickyBanner);
        } else {
            showBanner("Connected.");
        }
    }

    private void renderConversation(String liveAssistantText) {
        List<ChatMessage> displayMessages = ChatConversationState.compose(persistedMessages, pendingUserMessage, liveAssistantText);
        boolean shouldFollow = autoFollowConversation || adapter.getItemCount() == 0;
        adapter.submitList(displayMessages);
        scrollConversationToBottom(shouldFollow);
        binding.messageRecyclerView.post(this::updateScrollJumpButtons);
    }

    private void sendMessage() {
        ComposerInputSnapshot inputSnapshot = ComposerInputSnapshot.capture(binding.messageInput.getText());
        String prompt = inputSnapshot.prompt;
        ChatImageAttachment imageAttachment = selectedImageAttachment;
        if (prompt.isEmpty() && imageAttachment == null) {
            showBanner(getString(R.string.banner_message_or_image_needed));
            return;
        }
        if (selectedImageUri != null && imageAttachment == null) {
            showBanner("Image is still loading.");
            return;
        }
        if (currentSession == null) {
            showBanner("Conversation is still loading.");
            return;
        }
        if (currentLease == null || currentLease.leaseId == null || currentLease.leaseId.isEmpty()) {
            attemptLeaseRecoveryAndSend();
            return;
        }

        String draftText = inputSnapshot.draftText;
        Uri draftImageUri = selectedImageUri;
        ChatImageAttachment draftImageAttachment = selectedImageAttachment;
        String draftImageDisplayName = selectedImageDisplayName;
        pendingUserMessage = new ChatMessage("user", buildOutgoingPreviewText(prompt, imageAttachment), nowEpochSeconds(), true);
        renderConversation(null);
        setMessageInputSilently("");
        clearSelectedImage(false);
        setComposerEnabled(false);
        showBanner("Codex is thinking...");

        executor.execute(() -> {
            try {
                PortalJob queuedJob = apiClient.sendMessage(
                        endpoint,
                        sessionId,
                        prompt,
                        safeLaunchValue(currentSession.model),
                        safeLaunchValue(currentSession.approvalPolicy),
                        safeLaunchValue(currentSession.sandboxMode),
                        safeLaunchValue(currentSession.reasoningEffort),
                        currentLease.leaseId,
                        imageAttachment
                );
                runOnUiThread(() -> {
                    clearDraft();
                    attachedJobId = queuedJob.jobId;
                    renderLiveJob(queuedJob);
                    startWatchingJob(queuedJob);
                });
            } catch (Exception exception) {
                runOnUiThread(() -> {
                    pendingUserMessage = null;
                    restoreDraftAfterFailedSend(draftText, draftImageUri, draftImageAttachment, draftImageDisplayName);
                    setComposerEnabled(true);
                    renderConversation(null);
                    showBanner(exception.getMessage());
                });
            }
        });
    }

    private void claimSessionAndLoad() {
        showBanner("Claiming mobile control...");
        executor.execute(() -> {
            try {
                currentLease = apiClient.claimSession(endpoint, sessionId);
                heartbeatFailureCount = 0;
                stickyBanner = "Mobile is controlling this session.";
                runOnUiThread(() -> {
                    setComposerEnabled(true);
                    startLeaseHeartbeat();
                    loadSession();
                });
            } catch (Exception exception) {
                currentLease = null;
                stickyBanner = exception.getMessage();
                runOnUiThread(() -> {
                    setComposerEnabled(false);
                    loadSession();
                });
            }
        });
    }

    private void startLeaseHeartbeat() {
        mainHandler.removeCallbacks(heartbeatRunnable);
        if (currentLease != null) {
            mainHandler.postDelayed(heartbeatRunnable, HEARTBEAT_INTERVAL_MS);
        }
    }

    private void attemptLeaseRecoveryAndSend() {
        showBanner("Reclaiming mobile control...");
        executor.execute(() -> {
            try {
                currentLease = apiClient.claimSession(endpoint, sessionId);
                heartbeatFailureCount = 0;
                stickyBanner = "Mobile is controlling this session.";
                runOnUiThread(() -> {
                    startLeaseHeartbeat();
                    sendMessage();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void renderLiveJob(PortalJob job) {
        if (!job.isRunning()) {
            return;
        }
        attachedJobId = job.jobId;
        String liveText = ChatStreamingState.resolveLiveText(job);
        renderConversation(liveText);
        if (!liveText.isEmpty()) {
            showBanner("Codex is replying...");
        } else if (job.ownerLabel != null && !job.ownerLabel.isEmpty()) {
            showBanner(job.ownerLabel + " is controlling this session.");
        } else {
            showBanner("Codex is thinking...");
        }
    }

    private void startWatchingJob(PortalJob job) {
        if (job == null || job.jobId == null || job.jobId.isEmpty() || !job.isRunning()) {
            return;
        }
        if (job.jobId.equals(watchingJobId) && watchGeneration > 0) {
            return;
        }
        attachedJobId = job.jobId;
        watchingJobId = job.jobId;
        watchFailureCount = 0;
        setComposerEnabled(false);
        int generation = ++watchGeneration;
        jobExecutor.execute(() -> watchJobLoop(job.jobId, generation));
    }

    private void watchJobLoop(String jobId, int generation) {
        try {
            PortalJob finalJob = null;
            while (generation == watchGeneration) {
                try {
                    finalJob = apiClient.fetchJob(endpoint, jobId);
                    watchFailureCount = ChatWatchState.nextFailureCount(true, watchFailureCount);
                } catch (Exception pollException) {
                    watchFailureCount = ChatWatchState.nextFailureCount(false, watchFailureCount);
                    if (generation != watchGeneration) {
                        return;
                    }
                    if (ChatWatchState.shouldInvalidateWatch(watchFailureCount)) {
                        throw pollException;
                    }
                    runOnUiThread(() -> showBanner("Connection lost. Retrying..."));
                    Thread.sleep(1800L);
                    continue;
                }
                if (!finalJob.isRunning()) {
                    break;
                }
                PortalJob streamingJob = finalJob;
                int callbackGeneration = generation;
                runOnUiThread(() -> {
                    if (!ChatWatchState.shouldApplyLiveUpdate(watchingJobId, watchGeneration, callbackGeneration, streamingJob)) {
                        return;
                    }
                    renderLiveJob(streamingJob);
                });
                Thread.sleep(1800L);
            }
            if (generation != watchGeneration) {
                return;
            }
            if (finalJob == null) {
                throw new IllegalStateException("Job state unavailable.");
            }
            watchFailureCount = 0;
            if (finalJob.isCancelled()) {
                String cancelledSessionId = finalJob.sessionId == null || finalJob.sessionId.isEmpty() ? sessionId : finalJob.sessionId;
                SessionPayload payload = apiClient.fetchSession(endpoint, cancelledSessionId);
                String cancelledText = ChatStreamingState.resolveLiveText(finalJob);
                watchGeneration++;
                runOnUiThread(() -> {
                    attachedJobId = "";
                    watchingJobId = "";
                    pendingUserMessage = null;
                    adoptSessionId(cancelledSessionId);
                    setComposerEnabled(currentLease != null);
                    renderPayload(payload);
                    if (!cancelledText.isEmpty()) {
                        renderConversation(cancelledText);
                    }
                    showBanner(getString(R.string.banner_reply_stopped));
                });
                return;
            }
            if (!finalJob.isCompleted()) {
                PortalJob failedJob = finalJob;
                watchGeneration++;
                runOnUiThread(() -> {
                    attachedJobId = "";
                    watchingJobId = "";
                    setComposerEnabled(currentLease != null);
                    renderConversation(ChatStreamingState.resolveLiveText(failedJob));
                    showBanner(failedJob.error == null || failedJob.error.isEmpty() ? "Job failed." : failedJob.error);
                });
                return;
            }

            String requestedSessionId = finalJob.sessionId == null || finalJob.sessionId.isEmpty() ? sessionId : finalJob.sessionId;
            SessionPayload payload = apiClient.fetchSession(endpoint, requestedSessionId);
            String nextSessionId = requestedSessionId;
            if (payload.session != null && payload.session.sessionId != null && !payload.session.sessionId.isEmpty()) {
                nextSessionId = payload.session.sessionId;
            }
            SessionLease nextLease = currentLease;
            if (nextSessionId != null && !nextSessionId.isEmpty() && !nextSessionId.equals(sessionId) && currentLease != null) {
                try {
                    apiClient.releaseSession(endpoint, sessionId, currentLease.leaseId);
                } catch (Exception ignored) {
                }
                try {
                    nextLease = apiClient.claimSession(endpoint, nextSessionId);
                } catch (Exception ignored) {
                    nextLease = null;
                }
            }
            final SessionLease resolvedLease = nextLease;
            final String resolvedSessionId = nextSessionId;
            watchGeneration++;
            runOnUiThread(() -> {
                attachedJobId = "";
                watchingJobId = "";
                pendingUserMessage = null;
                currentLease = resolvedLease;
                adoptSessionId(resolvedSessionId);
                setComposerEnabled(currentLease != null);
                renderPayload(payload);
                showBanner("Reply received.");
            });
        } catch (Exception exception) {
            if (generation != watchGeneration) {
                return;
            }
            watchGeneration++;
            runOnUiThread(() -> handlePortalUnavailable("Connection lost. Keep run-mobile.bat open, then refresh."));
        }
    }

    private void handlePickedImage(Uri uri) {
        if (uri == null) {
            return;
        }
        try {
            getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (SecurityException ignored) {
        }
        showBanner(getString(R.string.banner_loading_image));
        executor.execute(() -> {
            try {
                ChatImageAttachment imageAttachment = readImageAttachment(uri);
                runOnUiThread(() -> {
                    selectedImageUri = uri;
                    selectedImageAttachment = imageAttachment;
                    selectedImageDisplayName = imageAttachment.displayName;
                    updateAttachmentPreview();
                    persistDraft();
                    showBanner(getString(R.string.banner_image_selected));
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(getString(R.string.banner_image_failed) + " " + exception.getMessage()));
            }
        });
    }

    private ChatImageAttachment readImageAttachment(Uri uri) throws IOException {
        String displayName = "image";
        try (android.database.Cursor cursor = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (index >= 0) {
                    displayName = cursor.getString(index);
                }
            }
        }

        try (InputStream inputStream = getContentResolver().openInputStream(uri)) {
            if (inputStream == null) {
                throw new IOException("Unable to open selected image.");
            }
            Bitmap bitmap = BitmapFactory.decodeStream(inputStream);
            if (bitmap == null) {
                throw new IOException("Unable to decode selected image.");
            }
            ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
            boolean compressed = bitmap.compress(Bitmap.CompressFormat.JPEG, 92, outputStream);
            bitmap.recycle();
            if (!compressed) {
                throw new IOException("Unable to encode selected image.");
            }
            if (outputStream.size() > MAX_IMAGE_BYTES) {
                throw new IOException("Image is too large.");
            }
            String jpegName = displayName.replaceAll("\\.[^.]+$", "") + ".jpg";
            return new ChatImageAttachment(jpegName, "image/jpeg", outputStream.toByteArray());
        }
    }

    private void updateAttachmentPreview() {
        boolean hasAttachment = selectedImageUri != null || selectedImageAttachment != null;
        binding.attachmentPreviewContainer.setVisibility(hasAttachment ? View.VISIBLE : View.GONE);
        if (!hasAttachment) {
            binding.attachmentPreviewSubtitle.setText("");
            binding.attachmentPreviewImage.setImageDrawable(null);
            return;
        }
        binding.attachmentPreviewSubtitle.setText(selectedImageDisplayName);
        binding.attachmentPreviewImage.setImageURI(selectedImageUri);
    }

    private void clearSelectedImage() {
        clearSelectedImage(true);
    }

    private void clearSelectedImage(boolean persist) {
        selectedImageAttachment = null;
        selectedImageUri = null;
        selectedImageDisplayName = "";
        updateAttachmentPreview();
        if (persist) {
            persistDraft();
        }
    }

    private String buildOutgoingPreviewText(String prompt, ChatImageAttachment imageAttachment) {
        String cleanPrompt = prompt == null ? "" : prompt.trim();
        if (imageAttachment == null) {
            return cleanPrompt;
        }
        String imageLabel = getString(R.string.label_image_prefix, imageAttachment.displayName);
        if (cleanPrompt.isEmpty()) {
            return getString(R.string.label_image_only_message, imageAttachment.displayName);
        }
        return cleanPrompt + "\n\n" + imageLabel;
    }

    private long nowEpochSeconds() {
        return System.currentTimeMillis() / 1000L;
    }

    private void editNote() {
        EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        input.setText(currentSession == null ? "" : currentSession.note);
        input.setSelection(input.getText().length());
        new AlertDialog.Builder(this)
                .setTitle(R.string.label_note)
                .setView(input)
                .setPositiveButton(R.string.action_save, (dialog, which) -> saveNote(input.getText() == null ? "" : input.getText().toString()))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void editSessionSettings() {
        if (currentSession == null) {
            showBanner("Conversation is still loading.");
            return;
        }
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        int padding = dpToPx(18);
        container.setPadding(padding, padding, padding, 0);

        Spinner modelSpinner = buildSettingsSpinner(sessionModelOptions, effectiveSessionValue(currentSession.model));
        Spinner approvalSpinner = buildSettingsSpinner(sessionApprovalOptions, effectiveSessionValue(currentSession.approvalPolicy));
        Spinner sandboxSpinner = buildSettingsSpinner(sessionSandboxOptions, effectiveSessionValue(currentSession.sandboxMode));
        Spinner reasoningSpinner = buildSettingsSpinner(sessionReasoningOptions, effectiveSessionValue(currentSession.reasoningEffort));

        container.addView(buildSettingsLabel(R.string.label_model));
        container.addView(modelSpinner);
        container.addView(buildSettingsLabel(R.string.label_approval));
        container.addView(approvalSpinner);
        container.addView(buildSettingsLabel(R.string.label_sandbox));
        container.addView(sandboxSpinner);
        container.addView(buildSettingsLabel(R.string.label_reasoning));
        container.addView(reasoningSpinner);

        TextView proxyText = buildSettingsLabelText(getString(R.string.label_proxy_summary, currentProxySummary.isEmpty() ? "direct" : currentProxySummary));
        proxyText.setPadding(0, dpToPx(16), 0, 0);
        container.addView(proxyText);

        new AlertDialog.Builder(this)
                .setTitle(R.string.title_session_settings)
                .setView(container)
                .setPositiveButton(R.string.action_save, (dialog, which) -> saveSessionSettings(
                        selectedSpinnerValue(modelSpinner),
                        selectedSpinnerValue(approvalSpinner),
                        selectedSpinnerValue(sandboxSpinner),
                        selectedSpinnerValue(reasoningSpinner)
                ))
                .setNeutralButton(R.string.action_reset_defaults, (dialog, which) -> saveSessionSettings("default", "default", "default", "default"))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private Spinner buildSettingsSpinner(List<String> options, String currentValue) {
        Spinner spinner = new Spinner(this);
        List<String> values = new ArrayList<>();
        values.add("default");
        for (String option : options) {
            if (option == null || option.isEmpty() || values.contains(option)) {
                continue;
            }
            values.add(option);
        }
        if (currentValue != null && !currentValue.isEmpty() && !values.contains(currentValue)) {
            values.add(currentValue);
        }
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, values);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(adapter);
        spinner.setSelection(values.indexOf(currentValue));
        return spinner;
    }

    private TextView buildSettingsLabel(int resId) {
        TextView textView = buildSettingsLabelText(getString(resId));
        textView.setPadding(0, dpToPx(12), 0, dpToPx(6));
        return textView;
    }

    private TextView buildSettingsLabelText(String text) {
        TextView textView = new TextView(this);
        textView.setText(text);
        return textView;
    }

    private String selectedSpinnerValue(Spinner spinner) {
        Object selectedItem = spinner.getSelectedItem();
        if (selectedItem == null) {
            return "default";
        }
        String value = selectedItem.toString().trim();
        return value.isEmpty() ? "default" : value;
    }

    private String effectiveSessionValue(String value) {
        return value == null || value.isEmpty() ? "default" : value;
    }

    private int dpToPx(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void saveNote(String note) {
        showBanner("Saving note...");
        executor.execute(() -> {
            try {
                apiClient.saveNote(endpoint, sessionId, note);
                SessionPayload payload = apiClient.fetchSession(endpoint, sessionId);
                runOnUiThread(() -> {
                    renderPayload(payload);
                    showBanner("Note saved.");
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void saveSessionSettings(String model, String approvalPolicy, String sandboxMode, String reasoningEffort) {
        showBanner(getString(R.string.banner_saving_session_settings));
        executor.execute(() -> {
            try {
                SessionPayload payload = apiClient.saveSessionSettings(endpoint, sessionId, model, approvalPolicy, sandboxMode, reasoningEffort);
                runOnUiThread(() -> {
                    renderPayload(payload);
                    showBanner(getString(R.string.banner_session_settings_saved));
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void confirmDelete() {
        new AlertDialog.Builder(this)
                .setTitle(R.string.action_delete)
                .setMessage("Delete this session from the local Codex history?")
                .setPositiveButton(R.string.action_delete, (dialog, which) -> deleteSession())
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void deleteSession() {
        showBanner("Deleting session...");
        executor.execute(() -> {
            try {
                apiClient.deleteSession(endpoint, sessionId);
                runOnUiThread(this::finish);
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void requestDesktopRefresh() {
        showBanner(getString(R.string.banner_refreshing_desktop));
        executor.execute(() -> {
            try {
                apiClient.requestDesktopRefresh(endpoint);
                runOnUiThread(() -> showBanner(getString(R.string.banner_desktop_refreshed)));
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void showAccountsDialog() {
        showBanner(getString(R.string.banner_loading_accounts));
        executor.execute(() -> {
            try {
                AccountSlotsPayload payload = apiClient.fetchAccountSlots(endpoint);
                runOnUiThread(() -> presentAccountsDialog(payload));
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void presentAccountsDialog(AccountSlotsPayload payload) {
        AccountCenterDialogSupport.show(this, payload, new AccountCenterDialogSupport.Callbacks() {
            @Override
            public void onRefresh() {
                showAccountsDialog();
            }

            @Override
            public void onCreateSlot() {
                promptCreateAccountSlot();
            }

            @Override
            public void onBindCurrent(AccountSlotSummary slot) {
                bindCurrentAccount(slot);
            }

            @Override
            public void onSwitch(AccountSlotSummary slot) {
                switchAccount(slot);
            }

            @Override
            public void onRename(AccountSlotSummary slot) {
                promptRenameAccountSlot(slot);
            }

            @Override
            public void onDelete(AccountSlotSummary slot) {
                confirmDeleteAccountSlot(slot);
            }

            @Override
            public void onToggleBackendMode(BackendStatusPayload backend) {
                toggleBackendMode(backend);
            }

            @Override
            public void onStartBackend() {
                startBackendProxy();
            }

            @Override
            public void onStopBackend() {
                stopBackendProxy();
            }

            @Override
            public void onRestartBackend() {
                restartBackendProxy();
            }
        });
    }

    private void showAccountSlotActions(AccountSlotSummary slot) {
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
                        bindCurrentAccount(slot);
                    } else if (selected.equals(getString(R.string.action_switch_here))) {
                        switchAccount(slot);
                    } else if (selected.equals(getString(R.string.action_rename))) {
                        promptRenameAccountSlot(slot);
                    } else if (selected.equals(getString(R.string.action_delete))) {
                        confirmDeleteAccountSlot(slot);
                    }
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void promptCreateAccountSlot() {
        EditText input = new EditText(this);
        input.setHint(R.string.hint_account_slot_label);
        new AlertDialog.Builder(this)
                .setTitle(R.string.action_new_slot)
                .setView(input)
                .setPositiveButton(R.string.action_save, (dialog, which) -> createAccountSlot(input.getText().toString()))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void promptRenameAccountSlot(AccountSlotSummary slot) {
        EditText input = new EditText(this);
        input.setText(slot.label);
        input.setSelection(input.getText().length());
        new AlertDialog.Builder(this)
                .setTitle(R.string.action_rename)
                .setView(input)
                .setPositiveButton(R.string.action_save, (dialog, which) -> renameAccountSlot(slot, input.getText().toString()))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void bindCurrentAccount(AccountSlotSummary slot) {
        showBanner(getString(R.string.banner_loading_accounts));
        executor.execute(() -> {
            try {
                apiClient.bindCurrentAccount(endpoint, slot.slotId);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_account_bound, slotDisplayName(slot)));
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void switchAccount(AccountSlotSummary slot) {
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
                    loadSession();
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void createAccountSlot(String rawLabel) {
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
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void renameAccountSlot(AccountSlotSummary slot, String rawLabel) {
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
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void confirmDeleteAccountSlot(AccountSlotSummary slot) {
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

    private void toggleBackendMode(BackendStatusPayload backend) {
        String nextMode = backend.isTokenPoolMode() ? "codex_auth" : "built_in_token_pool";
        int proxyPort = backend.proxyPort > 0 ? backend.proxyPort : 8317;
        showBanner(getString(R.string.banner_loading_backend));
        executor.execute(() -> {
            try {
                apiClient.saveBackendStatus(endpoint, nextMode, backend.tokenDir, proxyPort);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_backend_mode_saved, nextMode));
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void startBackendProxy() {
        showBanner(getString(R.string.banner_loading_backend));
        executor.execute(() -> {
            try {
                apiClient.startBackendProxy(endpoint);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_backend_proxy_started));
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void stopBackendProxy() {
        showBanner(getString(R.string.banner_loading_backend));
        executor.execute(() -> {
            try {
                apiClient.stopBackendProxy(endpoint);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_backend_proxy_stopped));
                    showAccountsDialog();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void restartBackendProxy() {
        showBanner(getString(R.string.banner_loading_backend));
        executor.execute(() -> {
            try {
                apiClient.restartBackendProxy(endpoint);
                runOnUiThread(() -> {
                    showBanner(getString(R.string.banner_backend_proxy_restarted));
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

    private void openLocalPathsOnPhone(List<String> paths) {
        if (paths == null || paths.isEmpty()) {
            return;
        }
        if (paths.size() == 1) {
            openLocalPathOnPhone(paths.get(0));
            return;
        }
        CharSequence[] labels = paths.toArray(new CharSequence[0]);
        new AlertDialog.Builder(this)
                .setTitle(R.string.dialog_choose_file_title)
                .setItems(labels, (dialog, which) -> openLocalPathOnPhone(paths.get(which)))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void openLocalPathOnPhone(String path) {
        showBanner(getString(R.string.banner_creating_browser_link));
        executor.execute(() -> {
            try {
                PortalSharedFileLink sharedFileLink = apiClient.createFileShare(endpoint, sessionId, path);
                String browserUrl = endpoint.browserUrl(sharedFileLink.relativeUrl);
                runOnUiThread(() -> {
                    try {
                        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(browserUrl));
                        startActivity(intent);
                        showBanner(getString(R.string.banner_opening_in_browser));
                    } catch (ActivityNotFoundException exception) {
                        showBanner(exception.getMessage() == null || exception.getMessage().isEmpty()
                                ? "No browser is available."
                                : exception.getMessage());
                    }
                });
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void stopReply() {
        if (attachedJobId == null || attachedJobId.isEmpty()) {
            return;
        }
        String jobId = attachedJobId;
        showBanner(getString(R.string.banner_stopping_reply));
        executor.execute(() -> {
            try {
                apiClient.cancelJob(endpoint, jobId);
            } catch (Exception exception) {
                runOnUiThread(() -> showBanner(exception.getMessage()));
            }
        });
    }

    private void handlePortalUnavailable(String message) {
        attachedJobId = "";
        watchingJobId = "";
        currentLease = null;
        heartbeatFailureCount = 0;
        setComposerEnabled(false);
        stickyBanner = (message == null || message.isEmpty())
                ? "Portal offline. Keep run-mobile.bat open, then refresh."
                : message;
        showBanner(stickyBanner);
    }

    private void setComposerEnabled(boolean enabled) {
        boolean canStop = attachedJobId != null && !attachedJobId.isEmpty();
        binding.sendButton.setVisibility(canStop ? View.GONE : View.VISIBLE);
        binding.stopButton.setVisibility(canStop ? View.VISIBLE : View.GONE);
        binding.sendButton.setEnabled(enabled && !canStop);
        binding.stopButton.setEnabled(canStop);
        binding.attachImageButton.setEnabled(enabled && !canStop);
        binding.clearAttachmentButton.setEnabled(enabled && !canStop);
        binding.messageInput.setEnabled(true);
    }

    private boolean shouldAutoFollowConversation() {
        return ChatLayoutState.shouldAutoScroll(
                binding.messageRecyclerView.computeVerticalScrollRange(),
                binding.messageRecyclerView.computeVerticalScrollOffset(),
                binding.messageRecyclerView.computeVerticalScrollExtent(),
                ChatLayoutState.AUTO_SCROLL_THRESHOLD_PX
        );
    }

    private void updateScrollJumpButtons() {
        int scrollOffset = binding.messageRecyclerView.computeVerticalScrollOffset();
        int scrollRange = binding.messageRecyclerView.computeVerticalScrollRange();
        int viewportExtent = binding.messageRecyclerView.computeVerticalScrollExtent();
        binding.jumpToTopButton.setVisibility(
                ChatScrollButtonsState.shouldShowJumpToTop(scrollOffset) ? View.VISIBLE : View.GONE
        );
        binding.jumpToBottomButton.setVisibility(
                ChatScrollButtonsState.shouldShowJumpToBottom(scrollRange, scrollOffset, viewportExtent) ? View.VISIBLE : View.GONE
        );
        updateFastScrollThumb(scrollRange, scrollOffset, viewportExtent);
    }

    private void updateFastScrollThumb(int scrollRange, int scrollOffset, int viewportExtent) {
        boolean showThumb = ChatFastScrollState.shouldShowThumb(scrollRange, viewportExtent);
        binding.fastScrollTrackContainer.setVisibility(showThumb ? View.VISIBLE : View.GONE);
        if (!showThumb) {
            binding.fastScrollThumb.setTranslationY(0f);
            return;
        }
        binding.fastScrollTrackContainer.post(() -> {
            int trackHeight = binding.fastScrollTrackContainer.getHeight()
                    - binding.fastScrollTrackContainer.getPaddingTop()
                    - binding.fastScrollTrackContainer.getPaddingBottom();
            int thumbHeight = binding.fastScrollThumb.getHeight();
            float offset = ChatFastScrollState.thumbOffsetPx(trackHeight, thumbHeight, scrollRange, scrollOffset, viewportExtent);
            binding.fastScrollThumb.setTranslationY(binding.fastScrollTrackContainer.getPaddingTop() + offset);
        });
    }

    private boolean handleFastScrollTouch(MotionEvent event) {
        int action = event.getActionMasked();
        if (action != MotionEvent.ACTION_DOWN && action != MotionEvent.ACTION_MOVE) {
            return action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL;
        }
        int scrollRange = binding.messageRecyclerView.computeVerticalScrollRange();
        int viewportExtent = binding.messageRecyclerView.computeVerticalScrollExtent();
        if (!ChatFastScrollState.shouldShowThumb(scrollRange, viewportExtent)) {
            return false;
        }
        int trackHeight = binding.fastScrollTrackContainer.getHeight()
                - binding.fastScrollTrackContainer.getPaddingTop()
                - binding.fastScrollTrackContainer.getPaddingBottom();
        int thumbHeight = Math.max(1, binding.fastScrollThumb.getHeight());
        float localY = event.getY() - binding.fastScrollTrackContainer.getPaddingTop();
        int targetOffset = ChatFastScrollState.targetScrollOffset(trackHeight, thumbHeight, localY, scrollRange, viewportExtent);
        int currentOffset = binding.messageRecyclerView.computeVerticalScrollOffset();
        binding.messageRecyclerView.scrollBy(0, targetOffset - currentOffset);
        autoFollowConversation = ChatLayoutState.shouldAutoScroll(
                scrollRange,
                targetOffset,
                viewportExtent,
                ChatLayoutState.AUTO_SCROLL_THRESHOLD_PX
        );
        binding.messageRecyclerView.post(this::updateScrollJumpButtons);
        return true;
    }

    private void jumpConversationToTop() {
        autoFollowConversation = false;
        binding.messageRecyclerView.scrollToPosition(0);
        binding.messageRecyclerView.post(this::updateScrollJumpButtons);
    }

    private void jumpConversationToBottom() {
        autoFollowConversation = true;
        scrollConversationToBottom(true);
        binding.messageRecyclerView.post(this::updateScrollJumpButtons);
    }

    private void scrollConversationToBottom() {
        scrollConversationToBottom(true);
    }

    private void scrollConversationToBottom(boolean force) {
        if (!force) {
            return;
        }
        int itemCount = adapter.getItemCount();
        if (itemCount <= 0) {
            return;
        }
        binding.messageRecyclerView.post(() -> {
            binding.messageRecyclerView.scrollBy(0, binding.messageRecyclerView.computeVerticalScrollRange());
            autoFollowConversation = true;
        });
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

    private String safeLaunchValue(String value) {
        return value == null || value.isEmpty() ? "default" : value;
    }

    private void adoptSessionId(String nextSessionId) {
        if (nextSessionId == null || nextSessionId.isEmpty()) {
            return;
        }
        migrateDraftToSession(nextSessionId);
        sessionId = nextSessionId;
        getIntent().putExtra(EXTRA_SESSION_ID, nextSessionId);
    }

    private void restoreDraft() {
        ChatDraftStore.Draft draft = draftStore.loadDraft(sessionId);
        if (!draft.text.isEmpty()) {
            setMessageInputSilently(draft.text);
        }
        if (draft.hasImage()) {
            Uri draftUri = Uri.parse(draft.imageUri);
            selectedImageUri = draftUri;
            selectedImageDisplayName = draft.imageName;
            updateAttachmentPreview();
            restoreDraftAttachment(draftUri);
        }
    }

    private void restoreDraftAttachment(Uri draftUri) {
        executor.execute(() -> {
            try {
                ChatImageAttachment imageAttachment = readImageAttachment(draftUri);
                runOnUiThread(() -> {
                    if (!draftUri.equals(selectedImageUri)) {
                        return;
                    }
                    selectedImageAttachment = imageAttachment;
                    selectedImageDisplayName = imageAttachment.displayName;
                    updateAttachmentPreview();
                    persistDraft();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> {
                    if (!draftUri.equals(selectedImageUri)) {
                        return;
                    }
                    clearSelectedImage();
                    showBanner("Saved image is no longer available.");
                });
            }
        });
    }

    private void persistDraft() {
        if (draftStore == null || sessionId == null || sessionId.isEmpty()) {
            return;
        }
        String text = binding.messageInput.getText() == null ? "" : binding.messageInput.getText().toString();
        String imageUri = selectedImageUri == null ? "" : selectedImageUri.toString();
        if (text.isEmpty() && imageUri.isEmpty()) {
            draftStore.clearDraft(sessionId);
            return;
        }
        draftStore.saveDraft(sessionId, text, imageUri, selectedImageDisplayName);
    }

    private void clearDraft() {
        if (draftStore == null || sessionId == null || sessionId.isEmpty()) {
            return;
        }
        draftStore.clearDraft(sessionId);
    }

    private void setMessageInputSilently(String text) {
        suppressDraftPersistence = true;
        binding.messageInput.setText(text);
        if (binding.messageInput.getText() != null) {
            binding.messageInput.setSelection(binding.messageInput.getText().length());
        }
        suppressDraftPersistence = false;
    }

    private void restoreDraftAfterFailedSend(String text, Uri imageUri, ChatImageAttachment imageAttachment, String imageDisplayName) {
        setMessageInputSilently(text);
        selectedImageUri = imageUri;
        selectedImageAttachment = imageAttachment;
        selectedImageDisplayName = imageDisplayName == null ? "" : imageDisplayName;
        updateAttachmentPreview();
        persistDraft();
    }

    private void migrateDraftToSession(String nextSessionId) {
        if (draftStore == null || sessionId == null || sessionId.isEmpty() || sessionId.equals(nextSessionId)) {
            return;
        }
        ChatDraftStore.Draft storedDraft = draftStore.loadDraft(sessionId);
        String currentText = binding != null && binding.messageInput.getText() != null
                ? binding.messageInput.getText().toString()
                : "";
        String currentImageUri = selectedImageUri == null ? "" : selectedImageUri.toString();
        String currentImageName = selectedImageDisplayName == null ? "" : selectedImageDisplayName;
        String text = currentText.isEmpty() ? storedDraft.text : currentText;
        String imageUri = currentImageUri.isEmpty() ? storedDraft.imageUri : currentImageUri;
        String imageName = currentImageName.isEmpty() ? storedDraft.imageName : currentImageName;
        if (!text.isEmpty() || !imageUri.isEmpty()) {
            draftStore.saveDraft(nextSessionId, text, imageUri, imageName);
        }
        draftStore.clearDraft(sessionId);
    }
}
