package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import androidx.test.core.app.ApplicationProvider;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

@RunWith(RobolectricTestRunner.class)
public final class ChatDraftStoreTest {
    private ChatDraftStore store;

    @Before
    public void setUp() {
        store = new ChatDraftStore(ApplicationProvider.getApplicationContext());
        store.clearDraft("session-1");
    }

    @Test
    public void saveAndLoadDraft_roundTripsTextAndImageMetadata() {
        store.saveDraft("session-1", "hello", "content://images/1", "photo.jpg");

        ChatDraftStore.Draft draft = store.loadDraft("session-1");

        assertEquals("hello", draft.text);
        assertEquals("content://images/1", draft.imageUri);
        assertEquals("photo.jpg", draft.imageName);
        assertTrue(draft.hasImage());
    }

    @Test
    public void clearDraft_removesSavedValues() {
        store.saveDraft("session-1", "hello", "content://images/1", "photo.jpg");

        store.clearDraft("session-1");

        ChatDraftStore.Draft draft = store.loadDraft("session-1");
        assertEquals("", draft.text);
        assertEquals("", draft.imageUri);
        assertEquals("", draft.imageName);
        assertFalse(draft.hasImage());
    }
}