package com.penguinoo.codexmobile;

import android.content.Context;
import android.content.SharedPreferences;

public final class ChatDraftStore {
    private static final String PREFS_NAME = "codex_mobile_chat_drafts";
    private static final String KEY_TEXT_PREFIX = "draft_text_";
    private static final String KEY_IMAGE_URI_PREFIX = "draft_image_uri_";
    private static final String KEY_IMAGE_NAME_PREFIX = "draft_image_name_";

    private final SharedPreferences preferences;

    public ChatDraftStore(Context context) {
        this.preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public void saveDraft(String sessionId, String text, String imageUri, String imageName) {
        preferences.edit()
                .putString(textKey(sessionId), normalize(text))
                .putString(imageUriKey(sessionId), normalize(imageUri))
                .putString(imageNameKey(sessionId), normalize(imageName))
                .apply();
    }

    public Draft loadDraft(String sessionId) {
        return new Draft(
                preferences.getString(textKey(sessionId), ""),
                preferences.getString(imageUriKey(sessionId), ""),
                preferences.getString(imageNameKey(sessionId), "")
        );
    }

    public void clearDraft(String sessionId) {
        preferences.edit()
                .remove(textKey(sessionId))
                .remove(imageUriKey(sessionId))
                .remove(imageNameKey(sessionId))
                .apply();
    }

    private static String textKey(String sessionId) {
        return KEY_TEXT_PREFIX + sessionId;
    }

    private static String imageUriKey(String sessionId) {
        return KEY_IMAGE_URI_PREFIX + sessionId;
    }

    private static String imageNameKey(String sessionId) {
        return KEY_IMAGE_NAME_PREFIX + sessionId;
    }

    private static String normalize(String value) {
        return value == null ? "" : value;
    }

    public static final class Draft {
        public final String text;
        public final String imageUri;
        public final String imageName;

        Draft(String text, String imageUri, String imageName) {
            this.text = text == null ? "" : text;
            this.imageUri = imageUri == null ? "" : imageUri;
            this.imageName = imageName == null ? "" : imageName;
        }

        public boolean hasImage() {
            return !imageUri.isEmpty();
        }

        public boolean hasContent() {
            return !text.isEmpty() || hasImage();
        }
    }
}