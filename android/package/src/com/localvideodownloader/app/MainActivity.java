package com.localvideodownloader.app;

import android.os.Bundle;
import android.content.Intent;
import org.qtproject.qt.android.bindings.QtActivity;

public class MainActivity extends QtActivity {
    @Override public void onCreate(Bundle state) {
        DownloadBridge.attach(this);
        super.onCreate(state);
        android.webkit.CookieManager.getInstance().setAcceptCookie(true);
        acceptIntent(getIntent());
    }
    @Override public void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        acceptIntent(intent);
    }
    @Override public void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == DownloadBridge.PICK_VIDEO_REQUEST) {
            android.net.Uri uri = result == RESULT_OK && data != null ? data.getData() : null;
            if (uri != null) {
                try { getContentResolver().takePersistableUriPermission(uri,
                        data.getFlags() & Intent.FLAG_GRANT_READ_URI_PERMISSION); }
                catch (SecurityException ignored) { }
            }
            DownloadBridge.videoPicked(uri);
        }
    }
    private void acceptIntent(Intent intent) {
        if (intent == null) return;
        if (Intent.ACTION_SEND.equals(intent.getAction())) {
            String text = intent.getStringExtra(Intent.EXTRA_TEXT);
            if (text != null) DownloadBridge.sharedText = text;
        } else if (Intent.ACTION_VIEW.equals(intent.getAction()) && intent.getData() != null) {
            DownloadBridge.sharedText = intent.getDataString();
        }
    }
}
