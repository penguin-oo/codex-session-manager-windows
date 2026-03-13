package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;

import androidx.test.core.app.ApplicationProvider;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

import java.util.Arrays;
import java.util.Collections;

@RunWith(RobolectricTestRunner.class)
public final class PortalConfigStoreTest {
    private PortalConfigStore store;

    @Before
    public void setUp() {
        store = new PortalConfigStore(ApplicationProvider.getApplicationContext());
        store.clearPortalUrl();
        store.clearRecentPortalUrls();
    }

    @Test
    public void rememberPortalUrl_keepsNewestFirstWithoutDuplicates() {
        store.rememberPortalUrl("http://one:8765/?token=a");
        store.rememberPortalUrl("http://two:8765/?token=b");
        store.rememberPortalUrl("http://one:8765/?token=a");

        assertEquals(
                Arrays.asList(
                        "http://one:8765/?token=a",
                        "http://two:8765/?token=b"
                ),
                store.getRecentPortalUrls()
        );
    }

    @Test
    public void rememberPortalUrl_capsHistoryAtFiveEntries() {
        store.rememberPortalUrl("1");
        store.rememberPortalUrl("2");
        store.rememberPortalUrl("3");
        store.rememberPortalUrl("4");
        store.rememberPortalUrl("5");
        store.rememberPortalUrl("6");

        assertEquals(Arrays.asList("6", "5", "4", "3", "2"), store.getRecentPortalUrls());
    }

    @Test
    public void clearPortalUrl_removesCurrentAndHistory() {
        store.rememberPortalUrl("http://one:8765/?token=a");

        store.clearPortalUrl();
        store.clearRecentPortalUrls();

        assertEquals("", store.getPortalUrl());
        assertEquals(Collections.emptyList(), store.getRecentPortalUrls());
    }
}
