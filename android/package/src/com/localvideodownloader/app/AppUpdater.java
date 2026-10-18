package com.localvideodownloader.app;

import android.net.ConnectivityManager;
import android.net.ProxyInfo;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** Public GitHub release checks; site login cookies never enter this request. */
public final class AppUpdater {
    private static final AtomicBoolean checking = new AtomicBoolean();

    private static int compare(String left, String right) throws Exception {
        if (!left.matches("v?\\d{1,4}\\.\\d{1,4}\\.\\d{1,4}")) throw new Exception("version");
        String[] a = left.replaceFirst("^v", "").split("\\.");
        String[] b = right.replaceFirst("^v", "").split("\\.");
        for (int n = 0; n < 3; n++) {
            int result = Integer.compare(Integer.parseInt(a[n]), Integer.parseInt(b[n]));
            if (result != 0) return result;
        }
        return 0;
    }

    public static void check(boolean manual) {
        if (!checking.compareAndSet(false, true)) return;
        new Thread(() -> {
            HttpURLConnection connection = null;
            try {
                URL url = new URL(AppVersion.UPDATE_URL + "?t=" + System.currentTimeMillis());
                Proxy route = Proxy.NO_PROXY;
                if (DownloadBridge.activity != null) {
                    ProxyInfo proxy = DownloadBridge.activity.getSystemService(ConnectivityManager.class).getDefaultProxy();
                    if (proxy != null && proxy.getHost() != null && proxy.getPort() > 0)
                        route = new Proxy(Proxy.Type.HTTP, new InetSocketAddress(proxy.getHost(), proxy.getPort()));
                }
                connection = (HttpURLConnection) url.openConnection(route);
                connection.setConnectTimeout(5000);
                connection.setReadTimeout(5000);
                connection.setRequestProperty("Cache-Control", "no-cache");
                connection.setRequestProperty("User-Agent", "VideoDownloader/" + AppVersion.VERSION);
                ByteArrayOutputStream body = new ByteArrayOutputStream();
                try (InputStream input = connection.getInputStream()) {
                    byte[] buffer = new byte[8192];
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        body.write(buffer, 0, count);
                        if (body.size() > 131072) throw new Exception("manifest size");
                    }
                }
                if (!connection.getURL().getProtocol().equals("https")) throw new Exception("HTTPS");
                JSONObject data = new JSONObject(body.toString(StandardCharsets.UTF_8.name()));
                if (data.getInt("schema") != 1 || !data.getString("product").equals("LocalVideoDownloader"))
                    throw new Exception("product");
                JSONObject entry = data.getJSONObject("platforms").getJSONObject("android");
                String version = entry.getString("version");
                URL target = new URL(entry.getString("url"));
                if (!target.getProtocol().equals("https") || !target.getHost().equals("github.com")
                        || target.getUserInfo() != null || target.getPort() != -1
                        || !target.getPath().startsWith("/" + AppVersion.REPOSITORY + "/releases/download/")
                        || !target.getPath().endsWith("/VideoDownloader-Android.apk")
                        || !entry.getString("sha256").matches("[0-9a-fA-F]{64}") || entry.getLong("size") <= 0)
                    throw new Exception("package");
                DownloadBridge.emit(new JSONObject().put("event", "update").put("manual", manual)
                        .put("available", compare(version, AppVersion.VERSION) > 0).put("version", version)
                        .put("url", target.toString()).toString());
            } catch (Exception error) {
                try { DownloadBridge.emit(new JSONObject().put("event", "update").put("manual", manual)
                        .put("error", "暂时无法连接 GitHub，请检查网络后重试。").toString()); }
                catch (Exception ignored) { }
            } finally {
                if (connection != null) connection.disconnect();
                checking.set(false);
            }
        }, "release-check").start();
    }
}
