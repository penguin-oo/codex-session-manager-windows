package com.penguinoo.codexmobile;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class LocalFilePathDetector {
    private static final Pattern WINDOWS_PATH_PATTERN = Pattern.compile(
            "(?i)([A-Z]:\\\\(?:[^\\\\/:*?\"<>|\\r\\n]+\\\\)*[^\\\\/:*?\"<>|\\r\\n]+\\.(?:png|jpe?g|webp|gif|pdf))"
    );

    private LocalFilePathDetector() {
    }

    public static List<String> extractSupportedPaths(String messageText) {
        LinkedHashSet<String> results = new LinkedHashSet<>();
        if (messageText == null || messageText.isEmpty()) {
            return new ArrayList<>();
        }
        Matcher matcher = WINDOWS_PATH_PATTERN.matcher(messageText);
        while (matcher.find()) {
            String path = sanitizePath(matcher.group(1));
            if (!path.isEmpty() && isSupported(path)) {
                results.add(path);
            }
        }
        return new ArrayList<>(results);
    }

    private static String sanitizePath(String rawPath) {
        if (rawPath == null) {
            return "";
        }
        String value = rawPath.trim();
        while (!value.isEmpty() && ".,;:)]}\"'`".indexOf(value.charAt(value.length() - 1)) >= 0) {
            value = value.substring(0, value.length() - 1).trim();
        }
        while (!value.isEmpty() && "([{`'\"".indexOf(value.charAt(0)) >= 0) {
            value = value.substring(1).trim();
        }
        return value;
    }

    private static boolean isSupported(String rawPath) {
        String lower = rawPath.toLowerCase(Locale.ROOT);
        return lower.endsWith(".png")
                || lower.endsWith(".jpg")
                || lower.endsWith(".jpeg")
                || lower.endsWith(".webp")
                || lower.endsWith(".gif")
                || lower.endsWith(".pdf");
    }
}
