package com.penguinoo.codexmobile;

import android.content.Context;
import android.content.SharedPreferences;

public final class PortalConfigStore {
    private static final String PREFS_NAME = "codex_mobile_prefs";
    private static final String KEY_PORTAL_URL = "portal_url";

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

    public void clearPortalUrl() {
        preferences.edit().remove(KEY_PORTAL_URL).apply();
    }
}
