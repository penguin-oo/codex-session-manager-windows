package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;

public final class PortalConnectionHistoryStateTest {
    @Test
    public void suggestions_includeCurrentUrlFirst_whenHistoryEmpty() {
        assertEquals(
                Collections.singletonList("http://saved:8765/?token=a"),
                PortalConnectionHistoryState.suggestions(
                        "http://saved:8765/?token=a",
                        Collections.emptyList()
                )
        );
    }

    @Test
    public void suggestions_mergeCurrentUrlWithoutDuplicate() {
        assertEquals(
                Arrays.asList(
                        "http://saved:8765/?token=a",
                        "http://other:8765/?token=b"
                ),
                PortalConnectionHistoryState.suggestions(
                        "http://saved:8765/?token=a",
                        Arrays.asList(
                                "http://other:8765/?token=b",
                                "http://saved:8765/?token=a"
                        )
                )
        );
    }
}
