package com.localvideodownloader.app;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.BroadcastReceiver;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.database.Cursor;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.StatFs;
import android.provider.Settings;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

/** Durable system download, app progress, verified APK and user-confirmed install. */
public final class UpdateDownload {
    static final int SOURCE_PERMISSION_REQUEST = 303;
    static final int INSTALL_REQUEST = 304;
    private static final Object lock = new Object();
    private static final Handler main = new Handler(Looper.getMainLooper());
    private static final ExecutorService worker = Executors.newSingleThreadExecutor();
    private static Context context;
    private static SharedPreferences prefs;
    private static JSONObject candidate, job;
    private static long downloadId = -1, downloaded, total;
    private static String state = "idle", message = "", details = "";
    private static boolean resumed, autoInstall, awaitingPermission, verifying, verified;
    private static int generation;

    private static final Runnable poll = () -> queryDownload();

    private static void initialize() {
        synchronized (lock) {
            if (context != null || DownloadBridge.activity == null) return;
            context = DownloadBridge.activity.getApplicationContext();
            prefs = context.getSharedPreferences("app-update-download", Context.MODE_PRIVATE);
            candidate = parse(prefs.getString("candidate", ""));
            job = parse(prefs.getString("job", ""));
            downloadId = prefs.getLong("download_id", -1);
            state = prefs.getString("state", "idle");
            message = prefs.getString("message", "");
            details = prefs.getString("details", "");
            autoInstall = prefs.getBoolean("auto_install", false);
            awaitingPermission = prefs.getBoolean("permission_pending", false);
            total = job == null ? 0 : job.optLong("size");
            try {
                if (job != null && AppUpdater.compare(job.getString("version"), AppVersion.VERSION) <= 0) {
                    if (downloadId >= 0) manager().remove(downloadId);
                    delete(partial()); delete(apk());
                    job = null; downloadId = -1; autoInstall = false; awaitingPermission = false;
                    state = "idle"; message = ""; details = ""; save();
                }
                if (job == null) state = "idle";
                // A previous process's verifier or installer is no longer running.
                if (state.equals("verifying") || state.equals("installing") || state.equals("permission"))
                    state = apk().isFile() ? "ready" : "downloading";
            } catch (Exception unavailable) {
                state = "error"; message = "无法恢复更新文件，请检查手机存储后重试。";
                autoInstall = false; awaitingPermission = false; save();
            }
            ContextCompat.registerReceiver(context, new BroadcastReceiver() {
                @Override public void onReceive(Context ignored, Intent intent) {
                    long id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -2);
                    synchronized (lock) { if (id != downloadId || id < 0) return; }
                    main.post(poll);
                }
            }, new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE), ContextCompat.RECEIVER_EXPORTED);
        }
    }

    private static JSONObject parse(String value) {
        try { return value == null || value.isEmpty() ? null : new JSONObject(value); }
        catch (Exception invalid) { return null; }
    }

    private static JSONObject copy(JSONObject value) {
        return value == null ? null : parse(value.toString());
    }

    private static File directory() {
        File path = context.getExternalFilesDir("updates");
        if (path == null) throw new IllegalStateException("更新存储位置不可用，请检查手机存储后重试。");
        return path;
    }

    private static File partial() { return new File(directory(), "update.part"); }
    private static File apk() { return new File(directory(), "update.apk"); }
    private static DownloadManager manager() {
        DownloadManager result = context.getSystemService(DownloadManager.class);
        if (result == null) throw new IllegalStateException("系统下载服务不可用，请启用下载管理服务后重试。");
        return result;
    }

    private static boolean transferring() {
        return state.equals("downloading") || state.equals("paused") || state.equals("verifying");
    }

    private static void save() {
        prefs.edit().putString("candidate", candidate == null ? "" : candidate.toString())
                .putString("job", job == null ? "" : job.toString()).putLong("download_id", downloadId)
                .putString("state", state).putString("message", message).putString("details", details)
                .putBoolean("auto_install", autoInstall)
                .putBoolean("permission_pending", awaitingPermission).apply();
    }

    private static void emit() {
        synchronized (lock) {
            try {
                double progress = total > 0 ? Math.min(1.0, downloaded / (double) total) : -1;
                if (state.equals("ready") || state.equals("permission") || state.equals("installing")) progress = 1;
                DownloadBridge.emit(new JSONObject().put("event", "update_transfer").put("state", state)
                        .put("version", job == null ? "" : job.optString("version"))
                        .put("downloaded", downloaded).put("total", total).put("progress", progress)
                        .put("message", message).put("details", details)
                        .put("canInstall", verified && apk().isFile()).toString());
            } catch (Exception ignored) { }
        }
    }

    private static void transition(String next, String text, String extra) {
        synchronized (lock) {
            state = next; message = text; details = extra;
            save(); emit();
        }
    }

    static void rememberCandidate(JSONObject entry) {
        initialize();
        synchronized (lock) {
            if (context == null) return;
            candidate = copy(entry); save();
        }
    }

    static void onResume() {
        initialize();
        synchronized (lock) { resumed = true; }
        main.postDelayed(() -> {
            boolean continuePermission;
            synchronized (lock) {
                if (!resumed) return;
                continuePermission = awaitingPermission;
                awaitingPermission = false;
                save();
                if (state.equals("installing")) {
                    state = "ready"; message = "安装包已就绪，可继续安装。";
                    autoInstall = false; save();
                }
            }
            if (continuePermission) {
                Activity activity = DownloadBridge.activity;
                if (activity != null && activity.getPackageManager().canRequestPackageInstalls()) {
                    synchronized (lock) {
                        // Permission changes can kill the process. Startup may
                        // already be verifying the saved APK when we return;
                        // preserve the user's install request for its completion.
                        autoInstall = true;
                        save();
                    }
                    install();
                } else transition("permission", "请允许安装此来源的应用后继续安装。", "");
            } else refresh();
        }, 350);
    }

    static void onPause() { synchronized (lock) { resumed = false; } }

    public static void refresh() {
        initialize();
        main.post(() -> {
            synchronized (lock) {
                if (context == null) return;
                emit();
                if (job == null) return;
                if ((state.equals("ready") || state.equals("permission")) && !verified) {
                    verify(false); return;
                }
                if (state.equals("ready") && verified && autoInstall && resumed) {
                    promptInstall(); return;
                }
            }
            queryDownload();
        });
    }

    public static void start() {
        initialize();
        main.post(() -> {
            synchronized (lock) {
                if (context == null) return;
                if (transferring() || state.equals("installing") || awaitingPermission) { emit(); return; }
                try {
                    if (candidate == null || !AppUpdater.officialPackage(new java.net.URL(candidate.getString("url")))
                            || !candidate.getString("sha256").matches("[0-9a-fA-F]{64}")
                            || candidate.getLong("size") <= 0 || candidate.getLong("size") > 2147483647L
                            || AppUpdater.compare(candidate.getString("version"), AppVersion.VERSION) <= 0)
                        throw new IOException("请先重新检查更新。");
                    if (verified && job != null && job.optString("sha256").equals(candidate.optString("sha256")) && apk().isFile()) {
                        install(); return;
                    }
                    File folder = directory();
                    if (!folder.isDirectory() && !folder.mkdirs()) throw new IOException("无法创建更新文件夹，请检查手机存储。");
                    if (new StatFs(folder.getAbsolutePath()).getAvailableBytes() < candidate.getLong("size") + 8 * 1024 * 1024)
                        throw new IOException("手机剩余空间不足，请清理空间后重试。");
                    if (downloadId >= 0) manager().remove(downloadId);
                    delete(partial()); delete(apk());
                    generation++; verifying = false; verified = false;
                    job = copy(candidate); downloaded = 0; total = job.getLong("size");
                    autoInstall = true; awaitingPermission = false;
                    DownloadManager.Request request = new DownloadManager.Request(Uri.parse(job.getString("url")))
                            .setTitle("视频下载器更新 " + job.getString("version"))
                            .setDescription("下载完成后将在软件内校验并打开安装界面")
                            .setMimeType("application/vnd.android.package-archive")
                            .setAllowedOverMetered(true).setAllowedOverRoaming(true)
                            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE)
                            .setDestinationInExternalFilesDir(context, "updates", "update.part");
                    request.addRequestHeader("User-Agent", "VideoDownloader/" + AppVersion.VERSION);
                    downloadId = manager().enqueue(request);
                    transition("downloading", "正在下载更新…", "");
                    main.removeCallbacks(poll); main.post(poll);
                } catch (Exception error) {
                    autoInstall = false;
                    transition("error", readable(error, "无法开始下载更新，请检查系统下载服务后重试。"), "");
                }
            }
        });
    }

    public static void cancel() {
        initialize();
        main.post(() -> {
            synchronized (lock) {
                if (context == null || !transferring()) return;
                generation++; verifying = false; verified = false;
                autoInstall = false; awaitingPermission = false;
                if (downloadId >= 0) { try { manager().remove(downloadId); } catch (Exception ignored) { } }
                downloadId = -1;
                try { delete(partial()); delete(apk()); } catch (Exception ignored) { }
                main.removeCallbacks(poll);
                transition("cancelled", "更新下载已取消。", "");
            }
        });
    }

    private static void queryDownload() {
        synchronized (lock) {
            main.removeCallbacks(poll);
            if (context == null || job == null || verifying
                    || !(state.equals("downloading") || state.equals("paused"))) return;
            if (downloadId < 0) {
                autoInstall = false;
                transition("error", "更新下载任务已失效，请重新下载。", "");
                return;
            }
            try (Cursor cursor = manager().query(new DownloadManager.Query().setFilterById(downloadId))) {
                if (cursor == null || !cursor.moveToFirst()) throw new IOException("更新下载任务已失效，请重新下载。");
                int status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));
                int reason = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON));
                downloaded = Math.max(0, cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR)));
                long serverTotal = cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES));
                if (serverTotal > 0 && serverTotal != total) throw new IOException("安装包大小与发布信息不一致，请重新检查更新。");
                if (status == DownloadManager.STATUS_SUCCESSFUL) { verify(true); return; }
                if (status == DownloadManager.STATUS_FAILED) throw new IOException(downloadFailure(reason));
                if (status == DownloadManager.STATUS_PAUSED) transition("paused", reason == DownloadManager.PAUSED_QUEUED_FOR_WIFI
                        ? "正在等待 Wi-Fi…" : "正在等待网络，恢复后继续下载…", "");
                else transition("downloading", status == DownloadManager.STATUS_PENDING ? "正在准备下载…" : "正在下载更新…", "");
                main.postDelayed(poll, 1000);
            } catch (Exception error) {
                autoInstall = false;
                if (downloadId >= 0) { try { manager().remove(downloadId); } catch (Exception ignored) { } }
                downloadId = -1;
                try { delete(partial()); } catch (Exception ignored) { }
                transition("error", readable(error, "下载更新失败，请重试。"), "");
            }
        }
    }

    private static String downloadFailure(int reason) {
        if (reason == DownloadManager.ERROR_INSUFFICIENT_SPACE) return "手机剩余空间不足，请清理空间后重试。";
        if (reason == DownloadManager.ERROR_DEVICE_NOT_FOUND) return "更新存储位置不可用，请检查手机存储。";
        if (reason == DownloadManager.ERROR_CANNOT_RESUME) return "下载连接已中断，无法续传，请重新下载。";
        if (reason == 403 || reason == 429) return "GitHub暂时限制下载，请稍后重试。";
        return "下载更新失败，请检查网络后重试。";
    }

    private static void verify(boolean fromDownload) {
        synchronized (lock) {
            if (verifying || job == null) return;
            verifying = true; verified = false;
            final int token = generation;
            final JSONObject expected = copy(job);
            transition("verifying", "正在校验安装包…", "");
            worker.execute(() -> {
                try {
                    File source;
                    synchronized (lock) { source = fromDownload ? partial() : apk(); }
                    validateBytes(source, expected, token);
                    synchronized (lock) {
                        if (token != generation) return;
                        if (fromDownload) {
                            delete(apk());
                            if (!source.renameTo(apk())) throw new IOException("无法保存更新安装包，请检查手机存储。");
                        }
                    }
                    validatePackage(apk(), expected);
                    main.post(() -> {
                        synchronized (lock) {
                            if (token != generation) return;
                            verifying = false; verified = true; downloaded = total;
                            transition("ready", "下载完成，安装包已校验。", "");
                            if (autoInstall && resumed) promptInstall();
                        }
                    });
                } catch (Exception error) {
                    main.post(() -> {
                        synchronized (lock) {
                            if (token != generation) return;
                            verifying = false; verified = false; autoInstall = false;
                            try { delete(partial()); delete(apk()); } catch (Exception ignored) { }
                            transition("error", readable(error, "安装包校验失败，请重新下载。"), "");
                        }
                    });
                }
            });
        }
    }

    private static void validateBytes(File file, JSONObject expected, int token) throws Exception {
        if (!file.isFile() || file.length() != expected.getLong("size")) throw new IOException("安装包未完整下载，请重新下载。");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (FileInputStream stream = new FileInputStream(file)) {
            byte[] buffer = new byte[256 * 1024];
            int read;
            while ((read = stream.read(buffer)) != -1) {
                synchronized (lock) { if (generation != token) throw new IOException("cancelled"); }
                digest.update(buffer, 0, read);
            }
        }
        if (!hex(digest.digest()).equalsIgnoreCase(expected.getString("sha256")))
            throw new IOException("安装包完整性校验失败，请重新下载。");
    }

    private static void validatePackage(File file, JSONObject expected) throws Exception {
        PackageManager packages = context.getPackageManager();
        PackageInfo archive = packages.getPackageArchiveInfo(file.getAbsolutePath(), PackageManager.GET_SIGNING_CERTIFICATES);
        if (archive == null || archive.applicationInfo == null) throw new IOException("手机无法解析此安装包，请重新下载或反馈手机系统版本。");
        if (!context.getPackageName().equals(archive.packageName)) throw new IOException("安装包不是本软件，已停止安装。");
        PackageInfo installed = packages.getPackageInfo(context.getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES);
        if (archive.getLongVersionCode() <= installed.getLongVersionCode()
                || AppUpdater.compare(archive.versionName, expected.getString("version")) != 0)
            throw new IOException("安装包版本与更新信息不一致，请重新检查更新。");
        if (archive.applicationInfo.minSdkVersion > android.os.Build.VERSION.SDK_INT)
            throw new IOException("此版本需要更高的Android系统版本。");
        if (archive.signingInfo == null || installed.signingInfo == null
                || !signatures(archive.signingInfo.getApkContentsSigners()).equals(signatures(installed.signingInfo.getApkContentsSigners())))
            throw new IOException("安装包签名与已安装版本不一致，已停止安装。");
    }

    private static Set<String> signatures(Signature[] values) throws Exception {
        Set<String> result = new HashSet<>();
        if (values != null) for (Signature signature : values)
            result.add(hex(MessageDigest.getInstance("SHA-256").digest(signature.toByteArray())));
        if (result.isEmpty()) throw new IOException("无法验证安装包签名。");
        return result;
    }

    private static String hex(byte[] value) {
        StringBuilder text = new StringBuilder();
        for (byte item : value) text.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
        return text.toString();
    }

    public static void install() {
        initialize();
        main.post(() -> {
            synchronized (lock) {
                if (context == null || job == null || !resumed || verifying || state.equals("installing") || awaitingPermission) return;
                if (!apk().isFile()) { transition("error", "更新安装包不可用，请重新下载。", ""); return; }
                // Verify persisted files again before every user-initiated retry.
                autoInstall = true;
                verify(false);
            }
        });
    }

    private static void promptInstall() {
        synchronized (lock) {
            Activity activity = DownloadBridge.activity;
            if (!verified || !resumed || activity == null || activity.isFinishing() || activity.isDestroyed()) return;
            try {
                if (!activity.getPackageManager().canRequestPackageInstalls()) {
                    autoInstall = false; awaitingPermission = true;
                    transition("permission", "请允许安装此来源的应用后继续安装。", "");
                    Intent permission = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                            Uri.parse("package:" + activity.getPackageName()));
                    activity.startActivityForResult(permission, SOURCE_PERMISSION_REQUEST);
                    return;
                }
                Uri uri = FileProvider.getUriForFile(activity, activity.getPackageName() + ".updateprovider", apk());
                Intent installer = new Intent(Intent.ACTION_INSTALL_PACKAGE)
                        .setDataAndType(uri, "application/vnd.android.package-archive")
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        .putExtra(Intent.EXTRA_RETURN_RESULT, true);
                installer.setClipData(ClipData.newRawUri("更新安装包", uri));
                autoInstall = false; awaitingPermission = false;
                transition("installing", "已打开系统安装界面，请确认安装。", "");
                activity.startActivityForResult(installer, INSTALL_REQUEST);
            } catch (Exception failure) {
                autoInstall = false; awaitingPermission = false;
                transition("ready", "无法打开安装界面，请重试安装并检查系统安装权限。", "");
            }
        }
    }

    private static String readable(Exception error, String fallback) {
        String text = error.getMessage();
        return error instanceof IOException || error instanceof IllegalStateException
                ? (text == null || text.isEmpty() ? fallback : text) : fallback;
    }

    private static void delete(File file) throws IOException {
        if (file.exists() && !file.delete()) throw new IOException("无法清理旧更新文件，请检查手机存储后重试。");
    }
}
