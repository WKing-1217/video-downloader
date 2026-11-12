package com.localvideodownloader.app;

import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.provider.DocumentsContract;
import android.provider.MediaStore;
import android.provider.OpenableColumns;
import android.util.AtomicFile;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;

/** App-owned public media catalogue; never delete files merely by directory name. */
public final class MediaLibrary {
    public static final int PICK_DIRECTORY_REQUEST=203;
    private static final ExecutorService IO=Executors.newSingleThreadExecutor();
    private static volatile boolean storageBusy;
    private static Context context() { return DownloadBridge.activity; }
    public static boolean isStorageBusy() {
        Context c=context();if(storageBusy)return true;if(c==null)return false;
        File journal=file(c,"media-migration.json").getBaseFile();
        // API 29 may have renamed the base to .bak when a write was interrupted.
        return journal.exists() || new File(journal.getPath()+".bak").exists();
    }
    private static AtomicFile file(Context c,String name) { return new AtomicFile(new File(c.getFilesDir(),name)); }
    private static synchronized JSONObject read(Context c,String name) throws Exception {
        AtomicFile f=file(c,name);
        // Let AtomicFile restore its backup before deciding that a file is absent.
        try(InputStream in=f.openRead()) { ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int size;while((size=in.read(buffer))!=-1)out.write(buffer,0,size);return new JSONObject(out.toString("UTF-8")); }
        catch(FileNotFoundException absent) { return new JSONObject(); }
    }
    private static synchronized void write(Context c,String name,JSONObject value) throws Exception {
        AtomicFile f=file(c,name);FileOutputStream out=f.startWrite();
        try { out.write(value.toString().getBytes(StandardCharsets.UTF_8));f.finishWrite(out); }
        catch(Exception e) { f.failWrite(out);throw e; }
    }
    private static JSONArray works(Context c) throws Exception { JSONArray rows=read(c,"media-library.json").optJSONArray("items");return rows==null?new JSONArray():rows; }
    private static void save(Context c,JSONArray rows) throws Exception {
        write(c,"media-library.json",new JSONObject().put("items",rows));
        synchronizeResults(rows);
    }
    private static JSONObject matchingWork(JSONArray rows,JSONObject previous) throws Exception {
        String id=previous.optString("library_id");
        for(int n=0;n<rows.length();n++){
            JSONObject item=rows.getJSONObject(n);
            if(!id.isEmpty() && id.equals(item.optString("library_id")))return item;
            if(id.isEmpty()){
                JSONArray before=assets(previous),after=assets(item);
                for(int a=0;a<before.length();a++)for(int b=0;b<after.length();b++){
                    String uri=before.getJSONObject(a).optString("public_uri");
                    if(!uri.isEmpty() && uri.equals(after.getJSONObject(b).optString("public_uri")))return item;
                }
            }
        }
        return null;
    }
    private static void synchronizeResults(JSONArray rows) throws Exception {
        // Completed-task actions must follow the catalogue after a move or
        // deletion; they must not keep opening a deleted original public URI.
        for(Map.Entry<String,JSONObject> entry:DownloadBridge.results.entrySet()){
            JSONObject current=entry.getValue(),replacement=matchingWork(rows,current);
            if(replacement==null)DownloadBridge.results.remove(entry.getKey(),current);
            else DownloadBridge.results.replace(entry.getKey(),current,new JSONObject(replacement.toString()));
        }
        JSONObject last=DownloadBridge.result;
        if(last!=null){JSONObject replacement=matchingWork(rows,last);DownloadBridge.result=replacement==null?null:new JSONObject(replacement.toString());}
    }
    private static JSONArray assets(JSONObject work) throws Exception {
        JSONArray a=work.optJSONArray("assets");return a==null?new JSONArray().put(work):a;
    }
    private static void emit(JSONObject event) { DownloadBridge.emit(event.toString()); }
    private static void notice(String message) { try {emit(new JSONObject().put("event","library_error").put("message",message));}catch(Exception ignored){} }
    public static synchronized void record(Context c,JSONObject result) throws Exception {
        JSONArray rows=works(c);
        // The service also persists this exact result as last-result.json. Give
        // both representations one durable ID so deletion cannot reimport it.
        String identifier=UUID.randomUUID().toString();long savedAt=System.currentTimeMillis();
        JSONObject copy=new JSONObject(result.toString());copy.put("library_id",identifier).put("saved_at",savedAt);
        rows.put(copy);save(c,rows);
        // Only mark the service result after the durable catalogue save; if it
        // fails, last-result remains eligible for legacy recovery.
        result.put("library_id",identifier).put("saved_at",savedAt);
        requestSnapshot();
    }
    private static void recover(Context c) throws Exception {
        JSONObject journal=read(c,"media-migration.json");if(journal.length()==0)return;
        if(journal.optString("phase").equals("switching")) {
            write(c,"media-library.json",journal.getJSONObject("after"));
            synchronizeResults(journal.getJSONObject("after").getJSONArray("items"));
            if(!c.getSharedPreferences("media-storage",0).edit().putString("tree",journal.optString("tree")).commit())throw new IOException("保存位置设置未能写入。");
            journal.put("phase","switched");write(c,"media-migration.json",journal);
        }
        boolean switched=journal.optString("phase").equals("switched");
        JSONArray discard=journal.optJSONArray(switched?"old":"created");
        if(discard!=null) for(int i=0;i<discard.length();i++) {
            JSONObject entry=discard.optJSONObject(i);
            Uri uri=Uri.parse(entry==null?discard.getString(i):entry.getString("uri"));
            if(switched && entry!=null && readable(c,uri.toString()) && !Arrays.equals(Base64.getDecoder().decode(entry.getString("sha")),hash(c,uri)))throw new IOException("原文件已发生变化，保留原文件，请检查后再清理。");
            if(!deleteUri(c,uri))throw new IOException("部分旧文件仍被占用，可稍后重试清理。");
        }
        file(c,"media-migration.json").delete();
    }
    /** Import earlier releases' result and app-owned Download rows without broad storage access. */
    private static synchronized void importEarlier(Context c) throws Exception {
        JSONArray rows=works(c);Set<String> known=new HashSet<>();
        for(int n=0;n<rows.length();n++){JSONArray a=assets(rows.getJSONObject(n));for(int i=0;i<a.length();i++)known.add(a.getJSONObject(i).optString("public_uri"));}
        JSONObject last=read(c,"last-result.json");
        if(last.length()>0 && last.optString("library_id").isEmpty()){
            JSONArray oldAssets=assets(last);String existingId="";
            // Earlier releases did not tag last-result with its catalogue ID.
            // A known member means that result has already been handled, even
            // when another member was subsequently deleted from the album.
            for(int n=0;n<rows.length() && existingId.isEmpty();n++){
                JSONObject row=rows.getJSONObject(n);JSONArray rowAssets=assets(row);
                for(int i=0;i<rowAssets.length() && existingId.isEmpty();i++)
                    for(int k=0;k<oldAssets.length();k++)
                        if(!rowAssets.getJSONObject(i).optString("public_uri").isEmpty()
                                && rowAssets.getJSONObject(i).optString("public_uri").equals(oldAssets.getJSONObject(k).optString("public_uri"))){
                            existingId=row.optString("library_id");break;
                        }
            }
            if(!existingId.isEmpty()){
                last.put("library_id",existingId);write(c,"last-result.json",last);
            }else{
                JSONArray present=new JSONArray();
                for(int i=0;i<oldAssets.length();i++){
                    JSONObject item=oldAssets.getJSONObject(i);
                    if(readable(c,item.optString("public_uri")))present.put(item);
                }
                if(present.length()>0){
                    if(last.has("assets")){last.put("assets",present);refreshCounts(last,present);}
                    last.put("library_id",UUID.randomUUID().toString());rows.put(last);
                    for(int i=0;i<present.length();i++)known.add(present.getJSONObject(i).optString("public_uri"));
                    write(c,"last-result.json",last);
                }
            }
        }
        if(Build.VERSION.SDK_INT>=29) {
            String[] columns={MediaStore.Downloads._ID,MediaStore.Downloads.DISPLAY_NAME,MediaStore.Downloads.MIME_TYPE,MediaStore.Downloads.SIZE,MediaStore.Downloads.RELATIVE_PATH};
            try(Cursor cursor=c.getContentResolver().query(MediaStore.Downloads.EXTERNAL_CONTENT_URI,columns,
                MediaStore.MediaColumns.OWNER_PACKAGE_NAME+"=? AND "+MediaStore.Downloads.IS_PENDING+"=0",new String[]{c.getPackageName()},MediaStore.Downloads.DATE_ADDED+" DESC")) {
                while(cursor!=null && cursor.moveToNext()) {
                    String uri=ContentUris.withAppendedId(MediaStore.Downloads.EXTERNAL_CONTENT_URI,cursor.getLong(0)).toString();
                    if(known.contains(uri)||!cursor.getString(4).startsWith("Download/视频下载器/"))continue;
                    JSONObject item=new JSONObject().put("library_id",UUID.randomUUID().toString()).put("public_uri",uri).put("title",cursor.getString(1))
                        .put("display_name",cursor.getString(1)).put("mime",cursor.getString(2)).put("size",cursor.getLong(3));
                    String mime=item.optString("mime");item.put("kind",mime.startsWith("audio/")?"audio":mime.startsWith("image/")?"image":"video");rows.put(item);known.add(uri);
                }
            } catch(SecurityException ignored) { /* Old result remains usable; no read-all permission. */ }
        }
        save(c,rows);
    }
    public static void requestSnapshot() {
        Context c=context();if(c==null)return;
        IO.execute(()->{try{
            recover(c);importEarlier(c);JSONArray list=new JSONArray();JSONArray rows=works(c);
            for(int n=rows.length()-1;n>=0;n--){JSONObject work=rows.getJSONObject(n);JSONArray a=assets(work);
                String kind=work.optString("kind",work.optString("content_type","video"));
                list.put(new JSONObject().put("id",work.getString("library_id")).put("title",work.optString("title",work.optString("display_name","作品")))
                    .put("kind",kind).put("assetCount",a.length()).put("details",a.length()>1?a.length()+" 个文件":"audio".equals(kind)?"MP3":"image".equals(kind)?"图片":"视频"));}
            emit(new JSONObject().put("event","library").put("items",list).put("save_location",saveLocation()).put("storage_busy",isStorageBusy()));
        }catch(Exception e){notice("作品库："+e.getMessage());}});
    }
    private static boolean readable(Context c,String value) {
        if(value.isEmpty())return false;
        try(InputStream stream=c.getContentResolver().openInputStream(Uri.parse(value))){return stream!=null;}catch(Exception e){return false;}
    }
    private static JSONObject find(Context c,String id) throws Exception {
        JSONArray rows=works(c);for(int n=0;n<rows.length();n++)if(rows.getJSONObject(n).optString("library_id").equals(id))return rows.getJSONObject(n);throw new IOException("作品记录不存在。");
    }
    private static void view(JSONObject a) throws Exception {
        Intent intent=new Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse(a.getString("public_uri")),a.optString("mime","video/*"));
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);DownloadBridge.activity.startActivity(Intent.createChooser(intent,"打开文件"));
    }
    public static void open(String id) {
        Activity activity=DownloadBridge.activity;if(activity==null)return;
        IO.execute(()->{try{JSONObject work=find(activity,id);JSONArray list=assets(work);activity.runOnUiThread(()->{
            try{
                if(list.length()==1){view(list.getJSONObject(0));return;}
                String[] labels=new String[list.length()];for(int n=0;n<labels.length;n++){
                    JSONObject a=list.getJSONObject(n);String k=a.optString("kind");labels[n]=(k.equals("live_photo")?"实况 · ":k.equals("image")?"图片 · ":"文件 · ")+a.optString("display_name","文件 "+(n+1));}
                new AlertDialog.Builder(activity).setTitle(work.optString("title","作品")) .setItems(labels,(d,n)->{
                    new AlertDialog.Builder(activity).setItems(new String[]{"打开","删除此文件"},(dialog,option)->{
                        try{if(option==0)view(list.getJSONObject(n));else new AlertDialog.Builder(activity).setTitle("删除此文件？").setMessage("将删除本地文件。").setNegativeButton("取消",null).setPositiveButton("删除",(x,y)->remove(id,n)).show();}catch(Exception e){notice("无法打开文件，请检查是否已被移动。");}
                    }).show();
                }).setNegativeButton("关闭",null).show();
            }catch(Exception e){notice("无法打开作品，请检查系统播放器。");}
        });}catch(Exception e){notice(e.getMessage());}});
    }
    public static void share(String id) {
        Activity activity=DownloadBridge.activity;if(activity==null)return;
        IO.execute(()->{try{JSONObject work=find(activity,id);JSONArray a=assets(work);ArrayList<Uri> uris=new ArrayList<>();for(int n=0;n<a.length();n++)uris.add(Uri.parse(a.getJSONObject(n).getString("public_uri")));
            activity.runOnUiThread(()->{try{Intent i=new Intent(uris.size()>1?Intent.ACTION_SEND_MULTIPLE:Intent.ACTION_SEND).setType(uris.size()>1?"*/*":work.optString("mime","*/*"));
                if(uris.size()>1)i.putParcelableArrayListExtra(Intent.EXTRA_STREAM,uris);else i.putExtra(Intent.EXTRA_STREAM,uris.get(0));
                ClipData clips=ClipData.newRawUri("作品",uris.get(0));for(int n=1;n<uris.size();n++)clips.addItem(new ClipData.Item(uris.get(n)));i.setClipData(clips);i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);activity.startActivity(Intent.createChooser(i,"分享作品"));}catch(Exception e){notice("无法分享文件。");}});
        }catch(Exception e){notice(e.getMessage());}});
    }
    public static void extractAudio(String id,int bitrate) {
        Activity activity=DownloadBridge.activity;if(activity==null)return;
        IO.execute(()->{try{JSONObject work=find(activity,id);JSONArray a=assets(work);for(int n=0;n<a.length();n++){JSONObject asset=a.getJSONObject(n);if(asset.optString("mime").startsWith("video/")){
            Uri uri=Uri.parse(asset.getString("public_uri"));String name=asset.optString("display_name","视频.mp4");activity.runOnUiThread(()->{
                try{if(DownloadService.isRunning()||isStorageBusy())throw new IOException("请等待当前任务完成。");
                    DownloadBridge.emit(new JSONObject().put("event","local_selected").put("mode","audio").put("title",name).toString());
                    activity.startForegroundService(new Intent(activity,DownloadService.class).putExtra("mode","audio").putExtra("source_uri",uri.toString()).putExtra("source_name",name).putExtra("video_format","mp4").putExtra("image_format","png").putExtra("audio_bitrate",bitrate));
                }catch(Exception e){notice(e.getMessage());}
            });return;
        }}notice("作品没有可提取的音轨视频。");}catch(Exception e){notice(e.getMessage());}});
    }
    private static void refreshCounts(JSONObject work,JSONArray members) throws Exception {
        int images=0,live=0,music=0;long bytes=0;
        for(int i=0;i<members.length();i++){
            JSONObject a=members.getJSONObject(i);String kind=a.optString("kind");
            if(kind.equals("image"))images++;else if(kind.equals("live_photo"))live++;else if(kind.equals("music"))music++;
            bytes+=a.optLong("size");
        }
        work.put("image_count",images).put("live_photo_count",live).put("music_count",music).put("size",bytes);
    }
    public static void remove(String id) {remove(id,-1);}
    private static void remove(String id,int selected) {
        Context c=context();if(c==null)return;
        IO.execute(()->{try{if(isStorageBusy()||DownloadService.isRunning())throw new IOException("请等待当前任务完成再删除。");
            synchronized(MediaLibrary.class){
            JSONArray rows=works(c),next=new JSONArray();boolean incomplete=false;
            for(int n=0;n<rows.length();n++){JSONObject w=rows.getJSONObject(n);if(!w.optString("library_id").equals(id)){next.put(w);continue;}
                JSONArray a=assets(w),kept=new JSONArray();for(int k=0;k<a.length();k++){JSONObject asset=a.getJSONObject(k);if(selected>=0 && selected!=k){kept.put(asset);continue;}
                    if(!deleteUri(c,Uri.parse(asset.getString("public_uri")))){kept.put(asset);incomplete=true;}}
                if(kept.length()>0){if(w.has("assets")){w.put("assets",kept);refreshCounts(w,kept);}next.put(w);}
            }
            save(c,next);
            if(incomplete)notice("部分文件无法删除，已保留记录，请检查文件权限后重试。");
            }
            requestSnapshot();
        }catch(Exception e){notice("删除失败："+e.getMessage());}});
    }
    public static boolean deleteUri(Context c,Uri uri) {
        try {
            if(DocumentsContract.isDocumentUri(c,uri)){
                if(DocumentsContract.deleteDocument(c.getContentResolver(),uri))return true;
            }else if(c.getContentResolver().delete(uri,null,null)>0)return true;
        }catch(FileNotFoundException gone){return true;}
        catch(Exception refused){return false;}
        // Inaccessible is not the same as absent: revoked SAF permissions must
        // keep both the record and any migration cleanup journal for retry.
        try(InputStream in=c.getContentResolver().openInputStream(uri)){return false;}
        catch(FileNotFoundException gone){return true;}
        catch(Exception unknown){return false;}
    }
    public static Uri outputTree(Context c) {String saved=c.getSharedPreferences("media-storage",0).getString("tree","");return saved.isEmpty()?null:Uri.parse(saved);}
    public static String saveLocation() {Context c=context();if(c==null)return "下载 / 视频下载器";Uri uri=outputTree(c);if(uri==null)return "下载 / 视频下载器";try{return DocumentsContract.getTreeDocumentId(uri);}catch(Exception e){return "已选择的保存文件夹";}}
    private static Uri rootDocument(Uri tree) {return DocumentsContract.buildDocumentUriUsingTree(tree,DocumentsContract.getTreeDocumentId(tree));}
    private static Uri child(Context c,Uri parent,String name) throws Exception {
        try(Cursor cur=c.getContentResolver().query(DocumentsContract.buildChildDocumentsUriUsingTree(parent,DocumentsContract.getDocumentId(parent)),new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID,DocumentsContract.Document.COLUMN_DISPLAY_NAME,DocumentsContract.Document.COLUMN_MIME_TYPE},null,null,null)){
            while(cur!=null&&cur.moveToNext())if(name.equals(cur.getString(1))&&DocumentsContract.Document.MIME_TYPE_DIR.equals(cur.getString(2)))return DocumentsContract.buildDocumentUriUsingTree(parent,cur.getString(0));}
        Uri created=DocumentsContract.createDocument(c.getContentResolver(),parent,DocumentsContract.Document.MIME_TYPE_DIR,name);if(created==null)throw new IOException("保存文件夹不可写。");return created;
    }
    private static Uri createUnique(Context c,Uri parent,String mime,String name) throws Exception {
        Set<String> existing=new HashSet<>();
        try(Cursor cur=c.getContentResolver().query(DocumentsContract.buildChildDocumentsUriUsingTree(parent,DocumentsContract.getDocumentId(parent)),new String[]{DocumentsContract.Document.COLUMN_DISPLAY_NAME},null,null,null)) {while(cur!=null && cur.moveToNext())existing.add(cur.getString(0));}
        String chosen=name;int dot=name.lastIndexOf('.'),number=2;
        while(existing.contains(chosen))chosen=(dot>0?name.substring(0,dot):name)+" ("+(number++)+")"+(dot>0?name.substring(dot):"");
        return DocumentsContract.createDocument(c.getContentResolver(),parent,mime,chosen);
    }
    private static byte[] copyHash(InputStream in,OutputStream out) throws Exception {MessageDigest sha=MessageDigest.getInstance("SHA-256");byte[] b=new byte[256*1024];int n;while((n=in.read(b))!=-1){out.write(b,0,n);sha.update(b,0,n);}out.flush();return sha.digest();}
    private static byte[] hash(Context c,Uri uri) throws Exception {try(InputStream in=c.getContentResolver().openInputStream(uri)){if(in==null)throw new IOException("无法校验保存的文件。");MessageDigest sha=MessageDigest.getInstance("SHA-256");byte[] b=new byte[256*1024];int n;while((n=in.read(b))!=-1)sha.update(b,0,n);return sha.digest();}}
    public static Uri publishToTree(Context c,JSONObject asset,String folder) throws Exception {
        Uri parent=rootDocument(outputTree(c));String[] parts=folder.split("/");for(String part:parts)if(!part.isEmpty()&&!part.equals("Download"))parent=child(c,parent,part);
        File source=new File(asset.getString("path"));String mime=asset.optString("mime","application/octet-stream");Uri uri=createUnique(c,parent,mime,source.getName());if(uri==null)throw new IOException("无法创建媒体文件。");
        try{
            byte[] before;
            try(InputStream in=new FileInputStream(source);OutputStream out=c.getContentResolver().openOutputStream(uri)){
                if(out==null)throw new IOException("无法写入媒体文件。");before=copyHash(in,out);
            }
            if(!Arrays.equals(before,hash(c,uri)))throw new IOException("媒体复制校验失败。");
        }catch(Exception e){deleteUri(c,uri);throw e;}asset.put("public_uri",uri.toString()).put("display_name",source.getName());return uri;
    }
    public static void chooseDirectory() {
        Activity activity=DownloadBridge.activity;if(activity==null)return;activity.runOnUiThread(()->{if(storageBusy||DownloadService.isRunning()){notice("请等待当前任务结束后更改位置。");return;}
            Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);activity.startActivityForResult(intent,PICK_DIRECTORY_REQUEST);});
    }
    public static void directoryPicked(Uri uri,int flags) {
        Context c=context();if(c==null||uri==null)return;
        try{c.getContentResolver().takePersistableUriPermission(uri,flags&(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_WRITE_URI_PERMISSION));}
        catch(Exception e){notice("未取得所选文件夹权限。");return;}
        migrate(uri);
    }
    public static void resetDirectory() {migrate(null);}
    private static void migrate(Uri tree) {
        Context c=context();if(c==null||storageBusy)return;
        storageBusy=true;try{emit(new JSONObject().put("event","storage").put("busy",true).put("message","正在迁移作品…"));}catch(Exception ignored){}
        IO.execute(()->{String migrationMessage="";try{
            if(DownloadService.isRunning())throw new IOException("请等待当前下载完成。");recover(c);importEarlier(c);
            Uri original=outputTree(c);if(Objects.equals(original,tree))return;
            JSONArray rows=works(c);JSONObject journal=new JSONObject().put("phase","copying").put("created",new JSONArray()).put("old",new JSONArray());write(c,"media-migration.json",journal);
            for(int n=0;n<rows.length();n++){JSONObject work=rows.getJSONObject(n);JSONArray a=assets(work);
                for(int k=0;k<a.length();k++){JSONObject asset=a.getJSONObject(k);Uri old=Uri.parse(asset.getString("public_uri"));String name=asset.optString("display_name","作品"),mime=asset.optString("mime","application/octet-stream");Uri dest;
                    if(tree!=null){Uri parent=child(c,rootDocument(tree),"视频下载器");if(a.length()>1)parent=child(c,parent,work.optString("library_id"));dest=createUnique(c,parent,mime,name);}
                    else{ContentValues values=new ContentValues();values.put(MediaStore.Downloads.DISPLAY_NAME,name);values.put(MediaStore.Downloads.MIME_TYPE,mime);values.put(MediaStore.Downloads.RELATIVE_PATH,"Download/视频下载器/"+(a.length()>1?work.optString("library_id")+"/":""));values.put(MediaStore.Downloads.IS_PENDING,1);dest=c.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,values);}
                    if(dest==null)throw new IOException("目标位置不可写。");journal.getJSONArray("created").put(dest.toString());write(c,"media-migration.json",journal);
                    byte[] sha;try(InputStream in=c.getContentResolver().openInputStream(old);OutputStream out=c.getContentResolver().openOutputStream(dest)){if(in==null||out==null)throw new IOException("无法读取作品。");sha=copyHash(in,out);}
                    if(!Arrays.equals(sha,hash(c,dest)))throw new IOException("迁移文件校验失败。");
                    journal.getJSONArray("old").put(new JSONObject().put("uri",old.toString()).put("sha",Base64.getEncoder().encodeToString(hash(c,dest))));asset.put("public_uri",dest.toString());
                }
            }
            if(tree==null)for(int i=0;i<journal.getJSONArray("created").length();i++){ContentValues ready=new ContentValues();ready.put(MediaStore.Downloads.IS_PENDING,0);c.getContentResolver().update(Uri.parse(journal.getJSONArray("created").getString(i)),ready,null,null);}
            // Save durable destination identity before deleting any original.
            journal.put("phase","switching").put("after",new JSONObject().put("items",rows)).put("tree",tree==null?"":tree.toString());write(c,"media-migration.json",journal);
            save(c,rows);if(!c.getSharedPreferences("media-storage",0).edit().putString("tree",tree==null?"":tree.toString()).commit())throw new IOException("无法保存位置设置。");
            journal.put("phase","switched");write(c,"media-migration.json",journal);recover(c);
        }catch(Exception e){migrationMessage="保存位置："+e.getMessage();notice(migrationMessage);}finally{
            storageBusy=false;
            // A failed cleanup journal still blocks new work. Keep its error
            // visible while the user refreshes the library to retry recovery.
            try{emit(new JSONObject().put("event","storage").put("busy",isStorageBusy()).put("message",migrationMessage).put("save_location",saveLocation()));}catch(Exception ignored){}
            requestSnapshot();
        }});
    }
}
