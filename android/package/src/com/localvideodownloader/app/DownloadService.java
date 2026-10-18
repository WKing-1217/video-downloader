package com.localvideodownloader.app;

import android.app.*;
import android.content.*;
import android.net.*;
import android.os.*;
import android.provider.MediaStore;
import android.webkit.MimeTypeMap;
import com.yausername.youtubedl_android.YoutubeDL;
import com.yausername.ffmpeg.FFmpeg;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

public class DownloadService extends Service {
    private static volatile java.lang.Process process;
    private static volatile boolean canceled;
    private static final String CHANNEL="downloads";
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private boolean running;
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public void onCreate() {
        super.onCreate();
        getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel(CHANNEL,"视频下载",NotificationManager.IMPORTANCE_LOW));
    }
    @Override public int onStartCommand(Intent intent,int flags,int id) {
        startForeground(1,notification("正在准备下载…"));
        if (!running && intent!=null) {
            running=true; canceled=false;
            executor.execute(() -> runDownload(intent.getStringExtra("text")));
        }
        return START_NOT_STICKY;
    }
    private Notification notification(String text) {
        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this,CHANNEL).setSmallIcon(R.drawable.ic_download)
                .setContentTitle("视频下载器").setContentText(text).setContentIntent(open).setOngoing(true).build();
    }
    private void copyAssetTree(String source,File dest) throws IOException {
        String[] names=getAssets().list(source);
        if (names!=null && names.length>0) {
            if (!dest.exists() && !dest.mkdirs()) throw new IOException("Cannot create runtime folder");
            for(String name:names) copyAssetTree(source+"/"+name,new File(dest,name));
        } else {
            try(InputStream in=getAssets().open(source);OutputStream out=new FileOutputStream(dest)) { transfer(in,out); }
        }
    }
    static void transfer(InputStream in,OutputStream out) throws IOException {
        byte[] buffer=new byte[256*1024];int count;
        while((count=in.read(buffer))!=-1) out.write(buffer,0,count);
    }
    private void runDownload(String text) {
        boolean complete=false, errorReported=false;
        try {
            YoutubeDL.getInstance().init(this);
            FFmpeg.getInstance().init(this);
            File base=new File(getNoBackupFilesDir(),"youtubedl-android");
            File engine=new File(getFilesDir(),"engine");
            copyAssetTree("engine",engine);
            File output=new File(getExternalFilesDir(null),"video");
            if (!output.exists()) output.mkdirs();
            String libs=getApplicationInfo().nativeLibraryDir;
            File packages=new File(base,"packages");
            String pythonHome=new File(packages,"python/usr").getAbsolutePath();
            ProcessBuilder builder=new ProcessBuilder(libs+"/libpython.so",new File(engine,"android_bootstrap.py").getAbsolutePath(),text,"--no-browser-cookies","--session-stdin");
            Map<String,String> env=builder.environment();
            env.put("LD_LIBRARY_PATH",new File(packages,"python/usr/lib")+":"+new File(packages,"ffmpeg/usr/lib"));
            env.put("PYTHONHOME",pythonHome);env.put("HOME",getFilesDir().getAbsolutePath());
            env.put("SSL_CERT_FILE",new File(engine,"cacert.pem").getAbsolutePath());
            env.put("TMPDIR",getCacheDir().getAbsolutePath());env.put("PYTHONUNBUFFERED","1");
            env.put("VIDEO_DOWNLOADER_OUTPUT",output.getAbsolutePath());
            env.put("VIDEO_DOWNLOADER_NATIVE_LIBS",libs);
            ProxyInfo proxy=getSystemService(ConnectivityManager.class).getDefaultProxy();
            if(proxy!=null && proxy.getHost()!=null) {
                String address="http://"+proxy.getHost()+":"+proxy.getPort();
                env.put("HTTP_PROXY",address);env.put("HTTPS_PROXY",address);
            }
            String platform=text!=null && text.contains("douyin.com") ? "douyin" : text!=null && (text.contains("bilibili.com")||text.contains("b23.tv")) ? "bilibili" : "x";
            File errors=new File(getCacheDir(),"worker-stderr.txt");builder.redirectError(errors);
            if(canceled) return;
            process=builder.start();
            try(OutputStream stdin=process.getOutputStream()) {
                stdin.write(DownloadBridge.session(platform).toString().getBytes(StandardCharsets.UTF_8));
            }
            try(BufferedReader reader=new BufferedReader(new InputStreamReader(process.getInputStream(),StandardCharsets.UTF_8))) {
                String line;
                while((line=reader.readLine())!=null) {
                    if(canceled) break;
                    JSONObject event;
                    try {event=new JSONObject(line);} catch(JSONException ignored) {continue;}
                    String type=event.optString("event");
                    if(type.equals("error")) errorReported=true;
                    if(type.equals("complete")) {
                        getSystemService(NotificationManager.class).notify(1,notification("正在保存到系统下载文件夹…"));
                        publish(event);
                        DownloadBridge.result=event;complete=true;
                        try(Writer out=new OutputStreamWriter(new FileOutputStream(new File(getFilesDir(),"last-result.json")),StandardCharsets.UTF_8)) { out.write(event.toString(2)); }
                    }
                    DownloadBridge.emit(event.toString());
                }
            }
            int code=process.waitFor();
            if(!canceled && !complete && !errorReported && code!=0) DownloadBridge.error("下载未完成，可展开运行日志查看原因或网页登录后重试。");
            else if(!canceled && !complete && !errorReported) DownloadBridge.error("下载未返回可验证的文件，请重新下载。");
        } catch(Exception e) {
            if(!canceled) DownloadBridge.error("下载服务失败："+e.getClass().getSimpleName()+" · "+e.getMessage());
        } finally {
            process=null;running=false;
            stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();
        }
    }
    private void publish(JSONObject result) throws Exception {
        JSONArray assets=result.optJSONArray("assets");
        String folder="Download/视频下载器/";
        if(assets!=null) {
            folder+=new File(result.getString("path")).getName()+"/";
            for(int n=0;n<assets.length();n++) publishFile(assets.getJSONObject(n),folder);
        } else publishFile(result,folder);
    }
    private void publishFile(JSONObject asset,String folder) throws Exception {
        File file=new File(asset.getString("path"));
        String ext=MimeTypeMap.getFileExtensionFromUrl(file.toURI().toString());
        String mime=MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext.toLowerCase(Locale.ROOT));
        if(mime==null) mime="application/octet-stream";
        if(Build.VERSION.SDK_INT>=29) {
            ContentValues row=new ContentValues();row.put(MediaStore.Downloads.DISPLAY_NAME,file.getName());
            row.put(MediaStore.Downloads.MIME_TYPE,mime);row.put(MediaStore.Downloads.RELATIVE_PATH,folder);
            row.put(MediaStore.Downloads.IS_PENDING,1);
            Uri uri=getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,row);
            if(uri==null) throw new IOException("系统下载目录不可写");
            try {
                try(InputStream in=new FileInputStream(file);OutputStream out=getContentResolver().openOutputStream(uri)) { if(out==null) throw new IOException("无法保存文件");transfer(in,out); }
                row.clear();row.put(MediaStore.Downloads.IS_PENDING,0);getContentResolver().update(uri,row,null,null);
                asset.put("public_uri",uri.toString());
            } catch(Exception e) {getContentResolver().delete(uri,null,null);throw e;}
        } else {
            // API 28 needs no broad storage access: expose the verified app file.
            Uri uri=androidx.core.content.FileProvider.getUriForFile(this,getPackageName()+".qtprovider",file);
            asset.put("public_uri",uri.toString());
        }
        asset.put("display_name",file.getName());asset.put("mime",mime);
    }
    public static void cancelDownload() {
        canceled=true;
        java.lang.Process p=process;
        if(p!=null) {
            p.destroy();
            new Thread(() -> {
                try { if(!p.waitFor(1,TimeUnit.SECONDS)) p.destroyForcibly(); }
                catch(InterruptedException ignored) { p.destroyForcibly(); }
            }).start();
        }
    }
    @Override public void onDestroy() { executor.shutdown();super.onDestroy(); }
}
