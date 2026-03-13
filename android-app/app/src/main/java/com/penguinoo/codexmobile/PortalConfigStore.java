package com.penguinoo.codexmobile;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;

import java.util.ArrayList;
import java.util.List;

public final class PortalConfigStore {
    private static final String PREFS_NAME = "codex_mobile_prefs";
    private static final String KEY_PORTAL_URL = "portal_url";
    private static final String KEY_RECENT_PORTAL_URLS = "recent_portal_urls";
    private static final int MAX_RECENT_PORTAL_URLS = 5;

    private final SharedPreferences preferences;

    public PortalConfigStore(Context context) {
        this.preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public String getPortalUrl() {
        return preferences.getString(KEY_PORTAL_URL, "");
    }

    public void savePortalUrl(String portalUrl) {
        preferences.edit().putString(KEY_PORTAL_URL, portalUrl).apply();
    }

    public void rememberPortalUrl(String portalUrl) {
        savePortalUrl(portalUrl);
        List<String> recentUrls = new ArrayList<>(getRecentPortalUrls());
        recentUrls.remove(portalUrl);
        recentUrls.add(0, portalUrl);
        if (recentUrls.size() > MAX_RECENT_PORTAL_URLS) {
            recentUrls = new ArrayList<>(recentUrls.subList(0, MAX_RECENT_PORTAL_URLS));
        }
        preferences.edit().putString(KEY_RECENT_PORTAL_URLS, encodeList(recentUrls)).apply();
    }

    public List<String> getRecentPortalUrls() {
        return decodeList(preferences.getString(KEY_RECENT_PORTAL_URLS, "[]"));
    }

    public void clearPortalUrl() {
        preferences.edit().remove(KEY_PORTAL_URL).apply();
    }

    public void clearRecentPortalUrls() {
        preferences.edit().remove(KEY_RECENT_PORTAL_URLS).apply();
    }

    private static String encodeList(List<String> values) {
        JSONArray array = new JSONArray();
        for (String value : values) {
            array.put(value);
        }
        return array.toString();
    }

    private static List<String> decodeList(String rawJson) {
        List<String> values = new ArrayList<>();
        if (rawJson == null || rawJson.isEmpty()) {
            return values;
        }
        try {
            JSONArray array = new JSONArray(rawJson);
            for (int i = 0; i < array.length(); i++) {
                String value = array.optString(i, "");
                if (!value.isEmpty()) {
                    values.add(value);
                }
            }
        } catch (JSONException ignored) {
            return new ArrayList<>();
        }
        return values;
    }
}
