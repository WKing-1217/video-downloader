package com.localvideodownloader.app;

import android.app.*;
import android.content.*;
import android.net.*;
import android.os.*;
import android.provider.MediaStore;
import android.provider.OpenableColumns;
import android.database.Cursor;
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
    private static volatile boolean active;
    private static final String CHANNEL="downloads";
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private boolean running;
    public static boolean isRunning() { return active; }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public void onCreate() {
        super.onCreate();
        getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel(CHANNEL,"视频下载",NotificationManager.IMPORTANCE_LOW));
    }
    @Override public int onStartCommand(Intent intent,int flags,int id) {
        String mode = intent == null ? "video" : intent.getStringExtra("mode");
        if (mode == null) mode = "video";
        if (active) { DownloadBridge.error(mode,"已有任务正在处理，请等待完成或取消后再操作。"); return START_NOT_STICKY; }
        startForeground(1,notification("正在准备下载…"));
        if (!running && intent!=null) {
            running=true; active=true; canceled=false;
            executor.execute(() -> runDownload(intent));
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
        while((count=in.read(buffer))!=-1) {
            if(canceled) throw new InterruptedIOException("任务已取消");
            out.write(buffer,0,count);
        }
    }
    static String displayName(Context context, Uri uri) {
        try(Cursor cursor=context.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)) {
            if(cursor!=null && cursor.moveToFirst()) {
                String name=cursor.getString(0);
                if(name!=null && !name.isEmpty()) return name;
            }
        } catch(Exception ignored) { }
        return "本地视频.mp4";
    }
    private File importVideo(Uri uri, String name, File directory) throws IOException {
        if(!directory.mkdirs()) throw new IOException("无法准备本地视频");
        String safe=name.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]","_");
        if(safe.isEmpty() || safe.equals(".") || safe.equals("..")) safe="本地视频.mp4";
        if(safe.length()>100) safe=safe.substring(0,90)+".mp4";
        File imported=new File(directory,safe);
        try(InputStream in=getContentResolver().openInputStream(uri);OutputStream out=new FileOutputStream(imported)) {
            if(in==null) throw new IOException("无法读取所选视频");
            byte[] buffer=new byte[256*1024];int count;
            while((count=in.read(buffer))!=-1) {
                if(canceled) throw new InterruptedIOException("任务已取消");
                out.write(buffer,0,count);
            }
        }
        return imported;
    }
    private void clearImported(File directory) {
        if(directory==null) return;
        File[] files=directory.listFiles();
        if(files!=null) for(File file:files) file.delete();
        directory.delete();
    }
    private void runDownload(Intent job) {
        String text=job.getStringExtra("text");
        String mode=job.getStringExtra("mode");
        if(mode==null) mode="video";
        File importedDirectory=null;
        boolean complete=false, errorReported=false;
        try {
            String videoFormat=job.getStringExtra("video_format"), imageFormat=job.getStringExtra("image_format");
            int bitrate=job.getIntExtra("audio_bitrate",192);
            if(videoFormat==null) videoFormat="mp4";
            if(imageFormat==null) imageFormat="png";
            if(!Arrays.asList("video","audio").contains(mode)
                    || !Arrays.asList("mp4","mkv","mov","webm").contains(videoFormat)
                    || !Arrays.asList("png","jpg","webp").contains(imageFormat)
                    || !Arrays.asList(128,192,256,320).contains(bitrate)) throw new IOException("导出设置无效，请重新选择格式。");
            YoutubeDL.getInstance().init(this);
            FFmpeg.getInstance().init(this);
            File base=new File(getNoBackupFilesDir(),"youtubedl-android");
            File engine=new File(getFilesDir(),"engine");
            copyAssetTree("engine",engine);
            File output=new File(getFilesDir(),"media");
            if (!output.exists()) output.mkdirs();
            String libs=getApplicationInfo().nativeLibraryDir;
            File packages=new File(base,"packages");
            String pythonHome=new File(packages,"python/usr").getAbsolutePath();
            ArrayList<String> command=new ArrayList<>();
            command.add(libs+"/libpython.so");command.add(new File(engine,"android_bootstrap.py").getAbsolutePath());
            String sourceUri=job.getStringExtra("source_uri");
            if(sourceUri!=null) {
                importedDirectory=new File(getCacheDir(),"audio-input-"+UUID.randomUUID());
                String sourceName=job.getStringExtra("source_name");
                File imported=importVideo(Uri.parse(sourceUri),sourceName==null ? "本地视频.mp4" : sourceName,importedDirectory);
                command.add("--extract-audio");command.add(imported.getAbsolutePath());
            } else {
                if(text==null || text.trim().isEmpty()) throw new IOException("请提供作品链接或本地视频。");
                command.add(text);command.add("--no-browser-cookies");command.add("--session-stdin");
            }
            Collections.addAll(command,"--mode",mode,"--video-format",videoFormat,"--image-format",imageFormat,"--audio-bitrate",String.valueOf(bitrate));
            ProcessBuilder builder=new ProcessBuilder(command);
            Map<String,String> env=builder.environment();
            env.put("LD_LIBRARY_PATH",libs+":"+new File(packages,"python/usr/lib")+":"+new File(packages,"ffmpeg/usr/lib"));
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
                if(sourceUri==null) stdin.write(DownloadBridge.session(platform).toString().getBytes(StandardCharsets.UTF_8));
            }
            try(BufferedReader reader=new BufferedReader(new InputStreamReader(process.getInputStream(),StandardCharsets.UTF_8))) {
                String line;
                while((line=reader.readLine())!=null) {
                    if(canceled) break;
                    JSONObject event;
                    try {event=new JSONObject(line);} catch(JSONException ignored) {continue;}
                    event.put("mode",mode);
                    String type=event.optString("event");
                    if(type.equals("error")) errorReported=true;
                    if(type.equals("complete")) {
                        getSystemService(NotificationManager.class).notify(1,notification("正在保存到系统下载文件夹…"));
                        publish(event);
                        // Once MediaStore commit succeeds, completion wins a late cancel.
                        DownloadBridge.result=event;DownloadBridge.results.put(mode,event);complete=true;
                        try(Writer out=new OutputStreamWriter(new FileOutputStream(new File(getFilesDir(),"last-result.json")),StandardCharsets.UTF_8)) { out.write(event.toString(2)); }
                        catch(IOException ignored) { /* Public media is already complete; private history is optional. */ }
                    }
                    DownloadBridge.emit(event.toString());
                }
            }
            int code=process.waitFor();
            if(!canceled && !complete && !errorReported && code!=0) DownloadBridge.error(mode,"任务未完成，可查看日志或网页登录后重试。");
            else if(!canceled && !complete && !errorReported) DownloadBridge.error(mode,"没有取得可验证的文件，请重试。");
        } catch(Exception e) {
            if(!canceled) DownloadBridge.error(mode,"处理失败："+e.getMessage());
        } finally {
            process=null;running=false;
            clearImported(importedDirectory);
            if(canceled && !complete) {
                try { DownloadBridge.emit(new JSONObject().put("event","cancelled").put("mode",mode).toString()); }
                catch(JSONException ignored) { }
            }
            active=false;
            stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();
        }
    }
    private void publish(JSONObject result) throws Exception {
        JSONArray assets=result.optJSONArray("assets");
        String folder="Download/视频下载器/";
        ArrayList<Uri> pending=new ArrayList<>();
        try {
            if(assets!=null) {
                folder+=new File(result.getString("path")).getName()+"/";
                for(int n=0;n<assets.length();n++) pending.add(publishFile(assets.getJSONObject(n),folder));
            } else pending.add(publishFile(result,folder));
            if(canceled) throw new InterruptedIOException("任务已取消");
            if(Build.VERSION.SDK_INT>=29) for(Uri uri:pending) {
                if(canceled) throw new InterruptedIOException("任务已取消");
                ContentValues ready=new ContentValues();ready.put(MediaStore.Downloads.IS_PENDING,0);
                if(getContentResolver().update(uri,ready,null,null)!=1) throw new IOException("未能完成媒体保存");
            }
        } catch(Exception e) {
            if(Build.VERSION.SDK_INT>=29) for(Uri uri:pending) {
                try {getContentResolver().delete(uri,null,null);} catch(Exception ignored) { }
            }
            throw e;
        }
    }
    private Uri publishFile(JSONObject asset,String folder) throws Exception {
        if(canceled) throw new InterruptedIOException("任务已取消");
        File file=new File(asset.getString("path"));
        String name=file.getName();
        int dot=name.lastIndexOf('.');
        String ext=dot>=0 ? name.substring(dot+1).toLowerCase(Locale.ROOT) : "";
        String mime=MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext);
        if(ext.equalsIgnoreCase("mp3")) mime="audio/mpeg";
        else if(ext.equals("mkv")) mime="video/x-matroska";
        else if(ext.equals("mov")) mime="video/quicktime";
        else if(ext.equals("webm")) mime="video/webm";
        if(mime==null) mime="application/octet-stream";
        Uri published;
        if(Build.VERSION.SDK_INT>=29) {
            ContentValues row=new ContentValues();row.put(MediaStore.Downloads.DISPLAY_NAME,file.getName());
            row.put(MediaStore.Downloads.MIME_TYPE,mime);row.put(MediaStore.Downloads.RELATIVE_PATH,folder);
            row.put(MediaStore.Downloads.IS_PENDING,1);
            Uri uri=getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,row);
            if(uri==null) throw new IOException("系统下载目录不可写");
            try {
                try(InputStream in=new FileInputStream(file);OutputStream out=getContentResolver().openOutputStream(uri)) { if(out==null) throw new IOException("无法保存文件");transfer(in,out); }
                asset.put("public_uri",uri.toString());
                published=uri;
            } catch(Exception e) {getContentResolver().delete(uri,null,null);throw e;}
        } else {
            // API 28 needs no broad storage access: expose the verified app file.
            Uri uri=androidx.core.content.FileProvider.getUriForFile(this,getPackageName()+".qtprovider",file);
            asset.put("public_uri",uri.toString());
            published=uri;
        }
        asset.put("display_name",file.getName());asset.put("mime",mime);
        return published;
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
