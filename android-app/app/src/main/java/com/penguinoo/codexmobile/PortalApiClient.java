package com.penguinoo.codexmobile;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;

public final class PortalApiClient {
    private static final int CONNECT_TIMEOUT_MS = 12_000;
    private static final int READ_TIMEOUT_MS = 30_000;

    public PortalBootstrap fetchBootstrap(PortalEndpoint endpoint) throws IOException {
        JSONObject json = getJson(endpoint, "/api/bootstrap");
        return new PortalBootstrap(
                parseSessions(json.optJSONArray("sessions")),
                parseStringList(json.optJSONArray("models")),
                parseStringList(json.optJSONArray("approval_options")),
                parseStringList(json.optJSONArray("sandbox_options")),
                parseStringList(json.optJSONArray("reasoning_options"))
        );
    }

    public SessionPayload fetchSession(PortalEndpoint endpoint, String sessionId) throws IOException {
        JSONObject json = getJson(endpoint, "/api/sessions/" + sessionId);
        return parseSessionPayload(json);
    }

    public AccountSlotsPayload fetchAccountSlots(PortalEndpoint endpoint) throws IOException {
        JSONObject json = getJson(endpoint, "/api/accounts");
        return parseAccountSlotsPayload(json);
    }

    public AccountSlotsPayload bindCurrentAccount(PortalEndpoint endpoint, String slotId) throws IOException {
        JSONObject json = postJson(endpoint, "/api/accounts/" + slotId + "/bind", new JSONObject());
        return parseAccountSlotsPayload(json);
    }

    public AccountSlotsPayload switchAccount(PortalEndpoint endpoint, String slotId) throws IOException {
        JSONObject json = postJson(endpoint, "/api/accounts/" + slotId + "/switch", new JSONObject());
        return parseAccountSlotsPayload(json);
    }

    public PortalJob sendMessage(
            PortalEndpoint endpoint,
            String sessionId,
            String prompt,
            String model,
            String approval,
            String sandbox,
            String reasoningEffort,
            String leaseId,
            ChatImageAttachment imageAttachment
    ) throws IOException {
        JSONObject body = buildSendMessageBody(prompt, model, approval, sandbox, reasoningEffort, leaseId, imageAttachment);
        JSONObject json = postJson(endpoint, "/api/sessions/" + sessionId + "/message", body);
        return parseJob(json);
    }

    static JSONObject buildSendMessageBody(
            String prompt,
            String model,
            String approval,
            String sandbox,
            String reasoningEffort,
            String leaseId,
            ChatImageAttachment imageAttachment
    ) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("prompt", prompt);
            body.put("model", model);
            body.put("approval", approval);
            body.put("sandbox", sandbox);
            body.put("reasoning_effort", reasoningEffort);
            body.put("lease_id", leaseId);
            body.put("owner_kind", "mobile");
            body.put("owner_label", "Mobile");
            if (imageAttachment != null && imageAttachment.bytes.length > 0) {
                JSONObject image = new JSONObject();
                image.put("name", imageAttachment.displayName);
                image.put("mime_type", imageAttachment.mimeType);
                image.put("data_base64", Base64.getEncoder().encodeToString(imageAttachment.bytes));
                body.put("image", image);
            }
        } catch (JSONException exception) {
            throw new IOException("Failed to build request body.", exception);
        }
        return body;
    }

    public PortalJob createChat(
            PortalEndpoint endpoint,
            String cwd,
            String prompt,
            String note,
            String model,
            String approval,
            String sandbox,
            String reasoningEffort
    ) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("cwd", cwd);
            body.put("prompt", prompt);
            body.put("note", note);
            body.put("model", model);
            body.put("approval", approval);
            body.put("sandbox", sandbox);
            body.put("reasoning_effort", reasoningEffort);
        } catch (JSONException exception) {
            throw new IOException("Failed to build new chat request.", exception);
        }
        JSONObject json = postJson(endpoint, "/api/chats", body);
        return parseJob(json);
    }

    public PortalJob fetchJob(PortalEndpoint endpoint, String jobId) throws IOException {
        JSONObject json = getJson(endpoint, "/api/jobs/" + jobId);
        return parseJob(json);
    }

    public PortalJob cancelJob(PortalEndpoint endpoint, String jobId) throws IOException {
        JSONObject json = postJson(endpoint, "/api/jobs/" + jobId + "/cancel", new JSONObject());
        return parseJob(json);
    }

    public SessionLease claimSession(PortalEndpoint endpoint, String sessionId) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("owner_kind", "mobile");
            body.put("owner_label", "Mobile");
            body.put("mode", "write");
        } catch (JSONException exception) {
            throw new IOException("Failed to build claim request.", exception);
        }
        JSONObject json = postJson(endpoint, "/api/sessions/" + sessionId + "/claim", body);
        return parseLease(json);
    }

    public SessionLease heartbeatSession(PortalEndpoint endpoint, String sessionId, String leaseId) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("lease_id", leaseId);
        } catch (JSONException exception) {
            throw new IOException("Failed to build heartbeat request.", exception);
        }
        JSONObject json = postJson(endpoint, "/api/sessions/" + sessionId + "/heartbeat", body);
        return parseLease(json);
    }

    public void releaseSession(PortalEndpoint endpoint, String sessionId, String leaseId) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("lease_id", leaseId);
        } catch (JSONException exception) {
            throw new IOException("Failed to build release request.", exception);
        }
        postJson(endpoint, "/api/sessions/" + sessionId + "/release", body);
    }

    public void saveNote(PortalEndpoint endpoint, String sessionId, String note) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("note", note);
        } catch (JSONException exception) {
            throw new IOException("Failed to build note request.", exception);
        }
        postJson(endpoint, "/api/sessions/" + sessionId + "/note", body);
    }

    public SessionPayload saveSessionSettings(
            PortalEndpoint endpoint,
            String sessionId,
            String model,
            String approvalPolicy,
            String sandboxMode,
            String reasoningEffort
    ) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("model", model);
            body.put("approval_policy", approvalPolicy);
            body.put("sandbox_mode", sandboxMode);
            body.put("reasoning_effort", reasoningEffort);
        } catch (JSONException exception) {
            throw new IOException("Failed to build session-settings request.", exception);
        }
        JSONObject json = postJson(endpoint, "/api/sessions/" + sessionId + "/settings", body);
        return parseSessionPayload(json);
    }

    public void requestDesktopRefresh(PortalEndpoint endpoint) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("source", "android_app");
        } catch (JSONException exception) {
            throw new IOException("Failed to build desktop refresh request.", exception);
        }
        postJson(endpoint, "/api/desktop/refresh", body);
    }

    public void deleteSession(PortalEndpoint endpoint, String sessionId) throws IOException {
        openConnection(endpoint, "/api/sessions/" + sessionId, "DELETE", null);
    }

    public DirectoryListing browseDirectory(PortalEndpoint endpoint, String path) throws IOException {
        JSONObject json = getJson(endpoint, "/api/fs?path=" + java.net.URLEncoder.encode(path == null ? "" : path, StandardCharsets.UTF_8));
        return parseDirectoryListing(json);
    }

    public DirectoryListing createDirectory(PortalEndpoint endpoint, String path) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("path", path);
        } catch (JSONException exception) {
            throw new IOException("Failed to build create-directory request.", exception);
        }
        JSONObject json = postJson(endpoint, "/api/fs/mkdir", body);
        return parseDirectoryListing(json);
    }

    public PortalSharedFileLink createFileShare(PortalEndpoint endpoint, String sessionId, String path) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("session_id", sessionId);
            body.put("path", path);
        } catch (JSONException exception) {
            throw new IOException("Failed to build file-share request.", exception);
        }
        JSONObject json = postJson(endpoint, "/api/files/share", body);
        return new PortalSharedFileLink(
                json.optString("share_id"),
                json.optString("relative_url"),
                json.optString("file_name"),
                json.optString("content_type"),
                json.optLong("expires_at", 0L)
        );
    }

    private JSONObject getJson(PortalEndpoint endpoint, String path) throws IOException {
        return openConnection(endpoint, path, "GET", null);
    }

    private JSONObject postJson(PortalEndpoint endpoint, String path, JSONObject body) throws IOException {
        return openConnection(endpoint, path, "POST", body);
    }

    static PortalJob parseJob(JSONObject json) {
        return new PortalJob(
                json.optString("job_id"),
                json.optString("status"),
                json.optString("session_id"),
                json.optString("last_message"),
                json.optString("error"),
                json.optString("live_text"),
                json.optInt("live_chunks_version"),
                json.optString("owner_kind"),
                json.optString("owner_label")
        );
    }

    static SessionPayload parseSessionPayload(JSONObject json) {
        return new SessionPayload(
                parseSession(json.optJSONObject("session")),
                parseMessages(json.optJSONArray("messages")),
                parseNullableJob(json.optJSONObject("active_job")),
                parseStringList(json.optJSONArray("models")),
                parseStringList(json.optJSONArray("approval_options")),
                parseStringList(json.optJSONArray("sandbox_options")),
                parseStringList(json.optJSONArray("reasoning_options")),
                json.optString("proxy_summary")
        );
    }

    static AccountSlotsPayload parseAccountSlotsPayload(JSONObject json) {
        JSONObject currentAuth = json.optJSONObject("current_auth");
        return new AccountSlotsPayload(
                json.optString("active_slot"),
                currentAuth == null ? "" : currentAuth.optString("email"),
                currentAuth == null ? "" : currentAuth.optString("account_id"),
                currentAuth == null ? "" : currentAuth.optString("auth_mode"),
                json.optBoolean("has_running_jobs", false),
                parseAccountSlots(json.optJSONArray("slots"))
        );
    }

    private static PortalJob parseNullableJob(JSONObject json) {
        if (json == null || json.length() == 0) {
            return null;
        }
        return parseJob(json);
    }

    private static java.util.List<AccountSlotSummary> parseAccountSlots(JSONArray array) {
        java.util.List<AccountSlotSummary> slots = new ArrayList<>();
        if (array == null) {
            return slots;
        }
        for (int index = 0; index < array.length(); index++) {
            JSONObject item = array.optJSONObject(index);
            if (item == null) {
                continue;
            }
            boolean bound = !(item.optString("email").isEmpty() && item.optString("account_id").isEmpty());
            slots.add(new AccountSlotSummary(
                    item.optString("slot_id"),
                    item.optString("email"),
                    item.optString("account_id"),
                    item.optString("auth_mode"),
                    item.optString("active").equalsIgnoreCase("yes"),
                    bound
            ));
        }
        return slots;
    }

    private SessionLease parseLease(JSONObject json) {
        return new SessionLease(
                json.optString("session_id"),
                json.optString("lease_id"),
                json.optString("owner_kind"),
                json.optString("owner_label"),
                json.optString("mode")
        );
    }

    private JSONObject openConnection(PortalEndpoint endpoint, String path, String method, JSONObject body) throws IOException {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(endpoint.apiUrl(path)).openConnection();
            connection.setRequestMethod(method);
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(READ_TIMEOUT_MS);
            connection.setRequestProperty("X-Access-Token", endpoint.getToken());
            connection.setRequestProperty("Accept", "application/json");
            if (body != null) {
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                byte[] payload = body.toString().getBytes(StandardCharsets.UTF_8);
                try (OutputStream outputStream = connection.getOutputStream()) {
                    outputStream.write(payload);
                }
            }

            int statusCode = connection.getResponseCode();
            String responseText = readBody(statusCode >= 400 ? connection.getErrorStream() : connection.getInputStream());
            if (statusCode >= 400) {
                throw new IOException(extractErrorMessage(responseText, statusCode));
            }
            if (responseText.isEmpty()) {
                return new JSONObject();
            }
            return new JSONObject(responseText);
        } catch (JSONException exception) {
            throw new IOException("Invalid response from portal.", exception);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private String extractErrorMessage(String body, int statusCode) {
        if (body == null || body.isEmpty()) {
            return "Portal request failed with status " + statusCode + ".";
        }
        try {
            JSONObject json = new JSONObject(body);
            String error = json.optString("error");
            if (!error.isEmpty()) {
                return error;
            }
        } catch (JSONException ignored) {
        }
        return body;
    }

    private String readBody(InputStream inputStream) throws IOException {
        if (inputStream == null) {
            return "";
        }
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(inputStream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line);
            }
        }
        return builder.toString();
    }

    private static List<String> parseStringList(JSONArray array) {
        List<String> values = new ArrayList<>();
        if (array == null) {
            return values;
        }
        for (int index = 0; index < array.length(); index++) {
            values.add(array.optString(index));
        }
        return values;
    }

    private List<SessionSummary> parseSessions(JSONArray array) {
        List<SessionSummary> sessions = new ArrayList<>();
        if (array == null) {
            return sessions;
        }
        for (int index = 0; index < array.length(); index++) {
            JSONObject item = array.optJSONObject(index);
            if (item != null) {
                sessions.add(parseSession(item));
            }
        }
        return sessions;
    }

    private static SessionSummary parseSession(JSONObject item) {
        if (item == null) {
            return new SessionSummary("", 0L, "", "", "", "", "", "", "", false);
        }
        return new SessionSummary(
                item.optString("session_id"),
                item.optLong("ts"),
                item.optString("text"),
                item.optString("note"),
                item.optString("cwd"),
                item.optString("model"),
                item.optString("approval_policy"),
                item.optString("sandbox_mode"),
                item.optString("reasoning_effort"),
                item.optBoolean("is_replying", false)
        );
    }

    private static List<ChatMessage> parseMessages(JSONArray array) {
        List<ChatMessage> messages = new ArrayList<>();
        if (array == null) {
            return messages;
        }
        for (int index = 0; index < array.length(); index++) {
            JSONObject item = array.optJSONObject(index);
            if (item == null) {
                continue;
            }
            messages.add(new ChatMessage(
                    item.optString("role"),
                    item.optString("text"),
                    item.optLong("ts")
            ));
        }
        return messages;
    }

    static DirectoryListing parseDirectoryListing(JSONObject json) {
        if (json == null) {
            return new DirectoryListing("", "", new ArrayList<>());
        }
        return new DirectoryListing(
                json.optString("path"),
                json.optString("parent"),
                parseDirectories(json.optJSONArray("directories"))
        );
    }

    private static List<DirectoryEntry> parseDirectories(JSONArray array) {
        List<DirectoryEntry> directories = new ArrayList<>();
        if (array == null) {
            return directories;
        }
        for (int index = 0; index < array.length(); index++) {
            JSONObject item = array.optJSONObject(index);
            if (item == null) {
                continue;
            }
            directories.add(new DirectoryEntry(
                    item.optString("name"),
                    item.optString("path")
            ));
        }
        return directories;
    }
}

