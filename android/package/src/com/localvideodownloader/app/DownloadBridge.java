package com.localvideodownloader.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.webkit.CookieManager;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.Button;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.ConcurrentHashMap;

public final class DownloadBridge {
    static Activity activity;
    static volatile String sharedText = "";
    static volatile JSONObject result;
    static final ConcurrentHashMap<String, JSONObject> results = new ConcurrentHashMap<>();
    static final int PICK_VIDEO_REQUEST = 202;
    static volatile int pickerBitrate = 192;
    static final ConcurrentLinkedQueue<String> events = new ConcurrentLinkedQueue<>();

    static void attach(Activity value) { activity = value; }
    public static String takeSharedText() {
        String text = sharedText; sharedText = ""; return text;
    }
    public static String takeEvents() {
        StringBuilder text = new StringBuilder();
        for (int n = 0; n < 100; n++) {
            String line = events.poll();
            if (line == null) break;
            text.append(line).append('\n');
        }
        return text.toString();
    }
    static void emit(String line) { events.add(line); }
    static void error(String message) {
        error("video", message);
    }
    static void error(String mode, String message) {
        try { emit(new JSONObject().put("event","error").put("mode",mode).put("message",message).toString()); }
        catch (Exception ignored) { }
    }
    public static void start(String text) {
        start(text, "video", "mp4", "png", 192);
    }
    public static void start(String text, String mode, String videoFormat, String imageFormat, int bitrate) {
        if (activity == null) return;
        activity.runOnUiThread(() -> {
            if (!DownloadService.isRunning()) results.remove(mode);
            if (Build.VERSION.SDK_INT >= 33 && activity.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != 0)
                activity.requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 101);
            Intent job = new Intent(activity, DownloadService.class).putExtra("text",text).putExtra("mode",mode)
                    .putExtra("video_format",videoFormat).putExtra("image_format",imageFormat).putExtra("audio_bitrate",bitrate);
            activity.startForegroundService(job);
        });
    }
    public static void pickVideo(int bitrate) {
        if (activity == null) return;
        if (DownloadService.isRunning()) { error("audio", "请等待当前任务结束后再选择视频。"); return; }
        pickerBitrate = bitrate;
        activity.runOnUiThread(() -> {
            try {
                Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("video/*")
                        .addCategory(Intent.CATEGORY_OPENABLE)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
                activity.startActivityForResult(picker, PICK_VIDEO_REQUEST);
            } catch (Exception e) { error("audio", "无法打开视频选择器，请使用系统文件应用选择视频。"); }
        });
    }
    static void videoPicked(Uri uri) {
        if (uri == null) {
            try { emit(new JSONObject().put("event","local_cancelled").put("mode","audio").toString()); }
            catch (Exception ignored) { }
            return;
        }
        startLocalAudio(uri, pickerBitrate);
    }
    private static void startLocalAudio(Uri uri, int bitrate) {
        if (activity == null) return;
        if (DownloadService.isRunning()) { error("audio", "请等待当前任务结束后再提取。"); return; }
        activity.runOnUiThread(() -> {
            try {
                String title = DownloadService.displayName(activity, uri);
                emit(new JSONObject().put("event","local_selected").put("mode","audio").put("title",title).toString());
                results.remove("audio");
                if (Build.VERSION.SDK_INT >= 33 && activity.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != 0)
                    activity.requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 101);
                activity.startForegroundService(new Intent(activity, DownloadService.class).putExtra("mode","audio")
                        .putExtra("source_uri",uri.toString()).putExtra("source_name",title)
                        .putExtra("video_format","mp4").putExtra("image_format","png").putExtra("audio_bitrate",bitrate));
            } catch (Exception e) { error("audio", "无法读取选中的视频，请重新选择。"); }
        });
    }
    public static void extractLastAudio(int bitrate) {
        JSONObject video = results.get("video");
        if (video == null || video.optJSONArray("assets") != null || !video.optString("mime").startsWith("video/")) {
            error("audio", "请先下载一个视频，或选择本地视频提取 MP3。");
            return;
        }
        String uri = video.optString("public_uri");
        if (uri.isEmpty()) { error("audio", "原视频文件不可用，请重新选择。"); return; }
        startLocalAudio(Uri.parse(uri), bitrate);
    }
    public static void cancel() { DownloadService.cancelDownload(); }
    public static void checkForUpdates(boolean manual) { AppUpdater.check(manual); }
    public static void startUpdate() { UpdateDownload.start(); }
    public static void cancelUpdate() { UpdateDownload.cancel(); }
    public static void installUpdate() { UpdateDownload.install(); }
    public static void refreshUpdate() { UpdateDownload.refresh(); }
    /** Match exact supported hosts; never leak a site session to a lookalike. */
    static String platformKey(String text) {
        if (text == null) return "";
        Matcher links = Pattern.compile("https?://[^\\s<>\"“”。；！？]+", Pattern.CASE_INSENSITIVE).matcher(text);
        while (links.find()) {
            String candidate = links.group().replaceAll("[,）)\\]};、。]+$", "");
            Uri uri = Uri.parse(candidate);
            String host = uri.getHost();
            if (host == null || uri.getPort() != -1 || uri.getUserInfo() != null) continue;
            host = host.toLowerCase(Locale.ROOT);
            String path = uri.getPath() == null ? "" : uri.getPath().replaceAll("/+$", "");
            if (host.equals("b23.tv") && path.matches("/[A-Za-z0-9_-]{3,}")) return "bilibili";
            if (Arrays.asList("bilibili.com","www.bilibili.com","m.bilibili.com").contains(host)
                    && path.matches("/(?:video/(?:BV[0-9A-Za-z]+|av[0-9]+)|bangumi/play/(?:ep|ss)[0-9]+)")) return "bilibili";
            if (host.equals("v.douyin.com") && path.matches("/[A-Za-z0-9_-]{3,}")) return "douyin";
            if (Arrays.asList("douyin.com","www.douyin.com","m.douyin.com","iesdouyin.com","www.iesdouyin.com").contains(host)) {
                String selected = uri.getQueryParameter("modal_id");
                if (selected == null) selected = uri.getQueryParameter("vid");
                if (path.matches("/(?:share/)?(?:video|note|slides)/[0-9]+") || (selected != null && selected.matches("[0-9]+"))) return "douyin";
            }
            if (host.equals("t.co") && path.matches("/[A-Za-z0-9_-]{3,}")) return "x";
            if (Arrays.asList("x.com","www.x.com","mobile.x.com","twitter.com","www.twitter.com","mobile.twitter.com","m.twitter.com").contains(host)
                    && path.matches("/[^/]+/status/[0-9]+(?:/video/[0-9]+)?")) return "x";
            if (Arrays.asList("instagram.com","www.instagram.com","m.instagram.com").contains(host)
                    && path.matches("/(?:reel|reels|p|tv)/[A-Za-z0-9_-]+")) return "instagram";
            if (host.equals("youtu.be") && path.matches("/[A-Za-z0-9_-]{11}")) return "youtube";
            if (Arrays.asList("youtube.com","www.youtube.com","m.youtube.com","music.youtube.com").contains(host)) {
                java.util.List<String> ids = uri.getQueryParameters("v");
                if ((path.equals("/watch") && ids.size() == 1 && ids.get(0).matches("[A-Za-z0-9_-]{11}"))
                        || path.matches("/(?:shorts|embed|live)/[A-Za-z0-9_-]{11}")) return "youtube";
            }
        }
        return "";
    }
    public static void login(String platform) {
        if (activity == null) return;
        activity.runOnUiThread(() -> {
            String site = platform.equals("bilibili") ? "https://www.bilibili.com/" :
                          platform.equals("douyin") ? "https://www.douyin.com/" :
                          platform.equals("instagram") ? "https://www.instagram.com/accounts/login/" :
                          platform.equals("youtube") ? "https://www.youtube.com/" : "https://x.com/i/flow/login";
            WebView web = new WebView(activity);
            web.getSettings().setJavaScriptEnabled(true);
            web.getSettings().setDomStorageEnabled(true);
            CookieManager.getInstance().setAcceptCookie(true);
            CookieManager.getInstance().setAcceptThirdPartyCookies(web,true);
            web.setWebViewClient(new WebViewClient());
            LinearLayout root = new LinearLayout(activity);
            root.setOrientation(LinearLayout.VERTICAL);
            Button done = new Button(activity); done.setText("完成登录，返回下载器");
            root.addView(done);
            root.addView(web,new LinearLayout.LayoutParams(-1,0,1));
            AlertDialog dialog = new AlertDialog.Builder(activity).setView(root).create();
            done.setOnClickListener(v -> dialog.dismiss());
            dialog.setOnDismissListener(v -> { CookieManager.getInstance().flush(); web.destroy(); });
            dialog.show();
            if (dialog.getWindow() != null) dialog.getWindow().setLayout(-1,-1);
            web.loadUrl(site);
        });
    }
    static JSONObject session(String platform) throws Exception {
        String domain;
        switch (platform) {
            case "bilibili": domain = ".bilibili.com"; break;
            case "douyin": domain = ".douyin.com"; break;
            case "instagram": domain = ".instagram.com"; break;
            case "youtube": domain = ".youtube.com"; break;
            case "x": domain = ".x.com"; break;
            default: return new JSONObject().put("cookies", new JSONArray());
        }
        String cookieHeader = CookieManager.getInstance().getCookie("https://" + domain.substring(1) + "/");
        JSONArray cookies = new JSONArray();
        if (cookieHeader != null) for (String pair : cookieHeader.split(";")) {
            int split = pair.indexOf('='); if (split < 1) continue;
            cookies.put(new JSONObject().put("domain",domain).put("path","/").put("secure",true)
                    .put("name",pair.substring(0,split).trim()).put("value",pair.substring(split+1).trim()));
        }
        return new JSONObject().put("cookies",cookies);
    }
    public static void openResult(boolean share) {
        openResultValue(result, share);
    }
    public static void openResultForMode(String mode, boolean share) {
        openResultValue(results.get(mode), share);
    }
    private static void openResultValue(JSONObject saved, boolean share) {
        if (activity == null || saved == null) return;
        activity.runOnUiThread(() -> {
            try {
                JSONArray assets = saved.optJSONArray("assets");
                if (assets != null && !share) {
                    String[] labels = new String[assets.length()];
                    for (int n=0;n<labels.length;n++) {
                        JSONObject a=assets.getJSONObject(n);
                        labels[n] = a.optString("display_name", "文件 " + (n+1));
                    }
                    new AlertDialog.Builder(activity).setTitle("作品文件")
                            .setItems(labels,(dialog,n)-> { try { view(assets.getJSONObject(n)); } catch(Exception e) { error(saved.optString("mode","video"),"无法打开文件："+e.getMessage()); } })
                            .setNegativeButton("关闭",null).show();
                } else if (share) {
                    ArrayList<Uri> uris = new ArrayList<>();
                    if (assets != null) for(int n=0;n<assets.length();n++) uris.add(Uri.parse(assets.getJSONObject(n).getString("public_uri")));
                    else uris.add(Uri.parse(saved.getString("public_uri")));
                    Intent intent = new Intent(uris.size()>1 ? Intent.ACTION_SEND_MULTIPLE : Intent.ACTION_SEND);
                    intent.setType(assets!=null ? "*/*" : saved.optString("mime", "application/octet-stream"));
                    if (uris.size()>1) intent.putParcelableArrayListExtra(Intent.EXTRA_STREAM,uris);
                    else intent.putExtra(Intent.EXTRA_STREAM,uris.get(0));
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    ClipData clips = ClipData.newRawUri("作品",uris.get(0));
                    for(int n=1;n<uris.size();n++) clips.addItem(new ClipData.Item(uris.get(n)));
                    intent.setClipData(clips);
                    activity.startActivity(Intent.createChooser(intent,"分享下载文件"));
                } else view(saved);
            } catch(Exception e) { error(saved.optString("mode","video"),"无法打开文件，可在系统“下载”中查看。" ); }
        });
    }
    private static void view(JSONObject file) throws Exception {
        Intent intent = new Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse(file.getString("public_uri")),file.optString("mime","video/*"));
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        activity.startActivity(Intent.createChooser(intent,"打开文件"));
    }
}
