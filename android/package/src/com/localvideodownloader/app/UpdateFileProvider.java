package com.localvideodownloader.app;

/** A dedicated provider avoids exposing unrelated app or media directories. */
public final class UpdateFileProvider extends androidx.core.content.FileProvider {
    public UpdateFileProvider() { super(); }
}
