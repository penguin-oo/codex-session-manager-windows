package com.penguinoo.codexmobile;

import static org.junit.Assert.assertEquals;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

public final class DirectoryListingParsingTest {
    @Test
    public void parseDirectoryListing_readsPathParentAndDirectories() throws Exception {
        JSONObject json = new JSONObject()
                .put("path", "D:/repo")
                .put("parent", "D:/")
                .put("directories", new JSONArray()
                        .put(new JSONObject()
                                .put("name", "src")
                                .put("path", "D:/repo/src")));

        DirectoryListing listing = PortalApiClient.parseDirectoryListing(json);

        assertEquals("D:/repo", listing.path);
        assertEquals("D:/", listing.parentPath);
        assertEquals(1, listing.directories.size());
        assertEquals("src", listing.directories.get(0).name);
    }
}
