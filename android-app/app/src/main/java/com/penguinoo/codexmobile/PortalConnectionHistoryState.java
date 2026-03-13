package com.penguinoo.codexmobile;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;

public final class PortalConnectionHistoryState {
    private PortalConnectionHistoryState() {
    }

    public static List<String> suggestions(String currentUrl, List<String> recentUrls) {
        LinkedHashSet<String> ordered = new LinkedHashSet<>();
        if (currentUrl != null && !currentUrl.isEmpty()) {
            ordered.add(currentUrl);
        }
        if (recentUrls != null) {
            for (String url : recentUrls) {
                if (url != null && !url.isEmpty()) {
                    ordered.add(url);
                }
            }
        }
        return new ArrayList<>(ordered);
    }
}
