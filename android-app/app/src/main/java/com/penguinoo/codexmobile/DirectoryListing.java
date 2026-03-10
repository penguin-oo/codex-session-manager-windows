package com.penguinoo.codexmobile;

import java.util.List;

public final class DirectoryListing {
    public final String path;
    public final String parentPath;
    public final List<DirectoryEntry> directories;

    public DirectoryListing(String path, String parentPath, List<DirectoryEntry> directories) {
        this.path = path;
        this.parentPath = parentPath;
        this.directories = directories;
    }
}
