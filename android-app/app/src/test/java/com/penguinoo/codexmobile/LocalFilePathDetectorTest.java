package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Arrays;
import java.util.List;

public final class LocalFilePathDetectorTest {
    @Test
    public void extractSupportedPaths_findsWindowsImageAndPdfPaths() {
        String message = "Open D:\\素材\\movie_commentary_exports\\frame 01.png and D:\\素材\\movie_commentary_exports\\notes.pdf";

        List<String> paths = LocalFilePathDetector.extractSupportedPaths(message);

        assertEquals(
                Arrays.asList(
                        "D:\\素材\\movie_commentary_exports\\frame 01.png",
                        "D:\\素材\\movie_commentary_exports\\notes.pdf"
                ),
                paths
        );
    }

    @Test
    public void extractSupportedPaths_ignoresUnsupportedSuffixes() {
        String message = "See D:\\素材\\movie_commentary_exports\\notes.txt";

        List<String> paths = LocalFilePathDetector.extractSupportedPaths(message);

        assertTrue(paths.isEmpty());
    }
}
