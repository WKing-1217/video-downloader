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
import java.util.concurrent.ConcurrentLinkedQueue;

public final class DownloadBridge {
    static Activity activity;
    static volatile String sharedText = "";
    static volatile JSONObject result;
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
        try { emit(new JSONObject().put("event","error").put("message",message).toString()); }
        catch (Exception ignored) { }
    }
    public static void start(String text) {
        if (activity == null) return;
        activity.runOnUiThread(() -> {
            result = null;
            if (Build.VERSION.SDK_INT >= 33 && activity.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != 0)
                activity.requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 101);
            Intent job = new Intent(activity, DownloadService.class).putExtra("text",text);
            activity.startForegroundService(job);
        });
    }
    public static void cancel() { DownloadService.cancelDownload(); }
    public static void checkForUpdates(boolean manual) { AppUpdater.check(manual); }
    public static void login(String platform) {
        if (activity == null) return;
        activity.runOnUiThread(() -> {
            String site = platform.equals("bilibili") ? "https://www.bilibili.com/" :
                          platform.equals("douyin") ? "https://www.douyin.com/" : "https://x.com/i/flow/login";
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
        String domain = platform.equals("bilibili") ? ".bilibili.com" : platform.equals("douyin") ? ".douyin.com" : ".x.com";
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
        JSONObject saved = result;
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
                            .setItems(labels,(dialog,n)-> { try { view(assets.getJSONObject(n)); } catch(Exception e) { error("无法打开文件："+e.getMessage()); } })
                            .setNegativeButton("关闭",null).show();
                } else if (share) {
                    ArrayList<Uri> uris = new ArrayList<>();
                    if (assets != null) for(int n=0;n<assets.length();n++) uris.add(Uri.parse(assets.getJSONObject(n).getString("public_uri")));
                    else uris.add(Uri.parse(saved.getString("public_uri")));
                    Intent intent = new Intent(uris.size()>1 ? Intent.ACTION_SEND_MULTIPLE : Intent.ACTION_SEND);
                    intent.setType(assets!=null ? "*/*" : "video/*");
                    if (uris.size()>1) intent.putParcelableArrayListExtra(Intent.EXTRA_STREAM,uris);
                    else intent.putExtra(Intent.EXTRA_STREAM,uris.get(0));
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    ClipData clips = ClipData.newRawUri("作品",uris.get(0));
                    for(int n=1;n<uris.size();n++) clips.addItem(new ClipData.Item(uris.get(n)));
                    intent.setClipData(clips);
                    activity.startActivity(Intent.createChooser(intent,"分享下载文件"));
                } else view(saved);
            } catch(Exception e) { error("无法打开文件，可在系统“下载”中查看。" ); }
        });
    }
    private static void view(JSONObject file) throws Exception {
        Intent intent = new Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse(file.getString("public_uri")),file.optString("mime","video/*"));
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        activity.startActivity(Intent.createChooser(intent,"打开文件"));
    }
}
