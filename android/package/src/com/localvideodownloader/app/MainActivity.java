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
