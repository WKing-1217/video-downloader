package com.localvideodownloader.app;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ActivityInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.net.ConnectivityManager;
import android.net.ProxyInfo;
import android.net.Uri;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** Public GitHub release checks; site login cookies never enter this request. */
public final class AppUpdater {
    private static final AtomicBoolean checking = new AtomicBoolean();

    private static boolean officialPackage(URL target) {
        String prefix = "/" + AppVersion.REPOSITORY + "/releases/download/";
        String path = target.getPath();
        if (!target.getProtocol().equals("https") || !target.getHost().equals("github.com")
                || target.getUserInfo() != null || target.getPort() != -1
                || target.getQuery() != null || target.getRef() != null || !path.startsWith(prefix)) return false;
        String releasePath = path.substring(prefix.length());
        return !releasePath.startsWith("./") && !releasePath.startsWith("../")
                && releasePath.matches("[A-Za-z0-9._-]+/VideoDownloader-Android\\.apk");
    }

    private static void openResult(boolean success, String message) {
        try { DownloadBridge.emit(new JSONObject().put("event", "update_open")
                .put("success", success).put("message", message).toString()); }
        catch (Exception ignored) { }
    }

    private static boolean externalBrowser(Activity activity, ResolveInfo handler, Set<String> browserPackages) {
        ActivityInfo info = handler.activityInfo;
        if (info == null || !info.enabled || !info.exported || info.applicationInfo == null
                || !info.applicationInfo.enabled || info.packageName.equals(activity.getPackageName())) return false;
        // The SDK's demonstration WebView shell handles every HTTPS URL but is
        // not a browser with a normal download list. Never hand updates to it.
        if (info.packageName.equals("org.chromium.webview_shell")
                || info.packageName.equals("com.android.webview")) return false;
        IntentFilter filter = handler.filter;
        boolean allHosts = filter != null && filter.countDataAuthorities() == 0;
        if (filter != null) for (int n = 0; n < filter.countDataAuthorities(); n++)
            if ("*".equals(filter.getDataAuthority(n).getHost())) allHosts = true;
        boolean unrestricted = allHosts && filter.countDataPaths() == 0
                && filter.countDataSchemeSpecificParts() == 0;
        return unrestricted || browserPackages.contains(info.packageName);
    }

    private static Intent browserIntent(Uri uri, ResolveInfo browser) {
        return new Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE)
                .setComponent(new ComponentName(browser.activityInfo.packageName, browser.activityInfo.name))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    }

    /** Use a real external browser and its own task/download manager, never a custom tab. */
    public static void openUpdateInBrowser(String value) {
        Activity activity = DownloadBridge.activity;
        if (activity == null) { openResult(false, "无法打开浏览器，请返回软件后重试。"); return; }
        final Uri uri;
        try {
            if (value == null || !officialPackage(new URL(value))) throw new Exception("package");
            uri = Uri.parse(value);
        } catch (Exception invalid) { openResult(false, "更新安装包地址无效，请重新检查更新。"); return; }
        activity.runOnUiThread(() -> {
            try {
                PackageManager manager = activity.getPackageManager();
                Set<String> browserPackages = new HashSet<>();
                Intent category = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_APP_BROWSER);
                ArrayList<ResolveInfo> browserEntries = new ArrayList<>(manager.queryIntentActivities(category, 0));
                for (ResolveInfo item : browserEntries)
                    if (item.activityInfo != null) browserPackages.add(item.activityInfo.packageName);
                // Resolve a neutral web page rather than the APK URL. A GitHub
                // app or package installer is not the user's default browser.
                Intent probe = new Intent(Intent.ACTION_VIEW, Uri.parse("https://example.com/"))
                        .addCategory(Intent.CATEGORY_BROWSABLE);
                LinkedHashMap<String, ResolveInfo> browsers = new LinkedHashMap<>();
                int flags = PackageManager.MATCH_DEFAULT_ONLY | PackageManager.GET_RESOLVED_FILTER;
                for (ResolveInfo item : manager.queryIntentActivities(probe, flags))
                    if (externalBrowser(activity, item, browserPackages)) browsers.putIfAbsent(item.activityInfo.packageName, item);
                // Some real browsers (including Firefox) expose their HTTPS
                // entry only with text/html, while still advertising APP_BROWSER.
                // Discover that entry before falling back to the browser category.
                Intent htmlProbe = new Intent(probe).setDataAndType(probe.getData(), "text/html");
                for (ResolveInfo item : manager.queryIntentActivities(htmlProbe, flags))
                    if (externalBrowser(activity, item, browserPackages)) browsers.putIfAbsent(item.activityInfo.packageName, item);
                for (ResolveInfo item : browserEntries)
                    if (externalBrowser(activity, item, browserPackages)) browsers.putIfAbsent(item.activityInfo.packageName, item);
                ResolveInfo preferred = manager.resolveActivity(probe, flags);
                if (preferred == null || !externalBrowser(activity, preferred, browserPackages)
                        || !browsers.containsKey(preferred.activityInfo.packageName))
                    preferred = manager.resolveActivity(htmlProbe, flags);
                if (preferred != null && externalBrowser(activity, preferred, browserPackages)
                        && browsers.containsKey(preferred.activityInfo.packageName)) {
                    activity.startActivity(browserIntent(uri, preferred));
                } else if (browsers.size() == 1) {
                    activity.startActivity(browserIntent(uri, browsers.values().iterator().next()));
                } else if (browsers.size() > 1) {
                    ArrayList<Intent> choices = new ArrayList<>();
                    for (ResolveInfo item : browsers.values()) choices.add(browserIntent(uri, item));
                    Intent chooser = Intent.createChooser(choices.remove(0), "选择浏览器下载更新")
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, choices.toArray(new Intent[0]));
                    activity.startActivity(chooser);
                    openResult(true, "请选择手机浏览器下载更新，安装包和进度可在浏览器下载列表中查看。");
                    return;
                } else {
                    openResult(false, "未找到可用的手机浏览器，请启用或安装浏览器后重试。");
                    return;
                }
                openResult(true, "已交给手机浏览器，下载进度和安装包请在浏览器下载列表中查看。");
            } catch (Exception unavailable) {
                openResult(false, "无法打开手机浏览器，请检查浏览器是否已启用后重试。");
            }
        });
    }

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
                if (!officialPackage(target)
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
