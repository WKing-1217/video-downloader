package com.localvideodownloader.app;

import android.os.Bundle;
import android.os.Build;
import android.content.Intent;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import org.qtproject.qt.android.bindings.QtActivity;

public class MainActivity extends QtActivity {
    private final Runnable restoreSystemBars = () -> {
        if (isFinishing() || isDestroyed() || !hasWindowFocus()) return;
        Window window = getWindow();
        if (window == null) return;
        View decor = window.getDecorView();
        window.clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        // Qt 6.11 restores fullscreen from the previous root-insets visibility.
        // After an external fullscreen player, that snapshot can still be hidden.
        // This Activity has no fullscreen mode; Qt still owns fitting and padding.
        @SuppressWarnings("deprecation")
        int hiddenFlags = View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY;
        @SuppressWarnings("deprecation")
        int visibleFlags = decor.getSystemUiVisibility() & ~hiddenFlags;
        decor.setSystemUiVisibility(visibleFlags);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController controller = window.getInsetsController();
            if (controller != null) {
                controller.show(WindowInsets.Type.systemBars());
                controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_DEFAULT);
            }
        }
        decor.requestApplyInsets();
    };

    private void scheduleSystemBarsRestore() {
        Window window = getWindow();
        if (window == null) return;
        View decor = window.getDecorView();
        decor.removeCallbacks(restoreSystemBars);
        // Run after Qt's resume/focus restoration, once on the next UI frame.
        decor.postOnAnimation(restoreSystemBars);
    }

    @Override public void onCreate(Bundle state) {
        DownloadBridge.attach(this);
        super.onCreate(state);
        android.webkit.CookieManager.getInstance().setAcceptCookie(true);
        acceptIntent(getIntent());
    }
    @Override protected void onResume() {
        super.onResume();
        scheduleSystemBarsRestore();
        UpdateDownload.onResume();
    }
    @Override protected void onPause() {
        UpdateDownload.onPause();
        super.onPause();
    }
    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) scheduleSystemBarsRestore();
    }
    @Override public void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        acceptIntent(intent);
    }
    @Override public void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if(request == MediaLibrary.PICK_DIRECTORY_REQUEST) {
            android.net.Uri uri=result==RESULT_OK && data!=null ? data.getData():null;
            MediaLibrary.directoryPicked(uri,data==null?0:data.getFlags());
        }
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
