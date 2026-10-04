package com.yuyi.app;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.AssetFileDescriptor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.util.Log;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URLDecoder;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 语忆 · 离线整站外壳（无 Gradle / 无 androidx，纯框架 API）
 *
 * 为什么不用 file:///android_asset/index.html
 * ---------------------------------------------------------------------------
 * 实测：file:// 来源下 Chrome 内核的 indexedDB.open() 既不触发 success 也不触发
 * error，回调永远不来。后果是 43MB 离线语音模型无法缓存进 IDBFS、本地 JSON
 * fetch 也被同源策略挡掉 —— 识别、持久化、盲文导出全废。
 *
 * 所以这里把整站跑在一个 **https 安全上下文** 里：WebView 加载
 * https://appassets.local/index.html，由 shouldInterceptRequest 从 assets/ 读字节
 * 并自己组装 WebResourceResponse（含正确 MIME + charset=utf-8）。
 * 这样 IndexedDB / Service Worker / getUserMedia 的行为与正常
 * https 站点一致。
 *
 * 原生桥 window.YuyiNative（页面侧只认这一个名字）
 * ---------------------------------------------------------------------------
 * 页面代码已经改成"优先走原生桥"，本类必须把下面几个方法都用
 * @JavascriptInterface 暴露出来，否则对应功能在 App 里静默失效：
 *
 *   speak(text, rate)      →  Android TextToSpeech 播报（WebView 没有
 *                            window.speechSynthesis，这是"为啥不能发声音"的根因）
 *   stop()                 →  tts.stop()
 *   available()            →  引擎是否真的可用（false = 没中文 TTS 引擎 / 初始化失败）
 *   saveFile(name,b64,mime)→  同步落盘到公共「下载」目录，返回落点字符串
 *   status()               →  诊断用 JSON（引擎名 / init 状态 / speak 返回码 / 回调计数）
 *   assetLog(n)            →  最近 n 条 assets 伺服记录（验证 /lib/* 映射通不通）
 *
 * 注意 speechSynthesis 那一段是**故意**留在注释里的历史结论：WebView 就是不实现它。
 */
public class MainActivity extends Activity {

    private static final String TAG = "YUYI";
    private static final String TAG_CONSOLE = "YUYICONSOLE";
    private static final String TAG_EVAL = "YUYIEVAL";
    private static final String TAG_TTS = "YUYITTS";

    /** 内置站点的安全来源。请求全部由 AssetClient 拦截，不会真的走网络。 */
    private static final String ORIGIN = "https://appassets.local";
    private static final String START_URL = ORIGIN + "/index.html";

    private static final int REQ_PERMS = 4711;

    /** Android 的可用语速区间；超出就夹住并记账（status().rateClamped）。 */
    private static final float RATE_MIN = 0.1f;
    private static final float RATE_MAX = 2.0f;

    private WebView web;

    /* ---------------- TTS 状态（全部只在探针里读，不影响播报逻辑） ---------------- */

    private TextToSpeech tts;
    private volatile boolean ttsReady = false;      // onInit == SUCCESS
    private volatile boolean ttsShutdown = false;
    private volatile int  ttsInitStatus = Integer.MIN_VALUE;
    private volatile int  ttsLangResult = Integer.MIN_VALUE;   // setLanguage(Locale.CHINESE)
    private volatile String ttsEnginePkg = "";
    private volatile int  ttsVoiceCount = -1;
    private volatile int  ttsSpeakCalls = 0;
    private volatile int  ttsSpeakOkCalls = 0;
    private volatile int  ttsLastSpeakRet = Integer.MIN_VALUE;
    private volatile float ttsLastRate = 0f;
    private volatile boolean ttsRateClamped = false;
    private volatile String ttsLastText = "";
    private volatile String ttsLastErr = "";
    private volatile int  ttsEvents = 0;
    private volatile String ttsLastEvent = "";
    private volatile int  ttsUtterSeq = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        WebView.setWebContentsDebuggingEnabled(true);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        // 诊断入口：--es yuyi_page selftest.html 可以把首屏换成内置自检页
        String startUrl = START_URL;
        String wantPage = normalizePagePath(getIntent() == null ? null
                : getIntent().getStringExtra("yuyi_page"));
        if (wantPage != null) startUrl = ORIGIN + "/" + wantPage;

        FrameLayout root = new FrameLayout(this);
        root.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.setBackgroundColor(Color.WHITE);

        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);                       // 页面全靠 JS
        s.setDomStorageEnabled(true);                       // localStorage 必需
        s.setDatabaseEnabled(true);                         // WebSQL/IDB 老路径
        s.setMediaPlaybackRequiresUserGesture(false);       // 允许自动播放 / TTS
        s.setAllowFileAccess(false);                        // 不需要 file:// —— 正是要避开它
        s.setAllowContentAccess(false);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setJavaScriptCanOpenWindowsAutomatically(true);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        if (Build.VERSION.SDK_INT >= 21) {
            // 用户可能把 AI 端点配成局域网 http:// 地址，别把明文掐死
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }
        if (Build.VERSION.SDK_INT >= 26) {
            s.setSafeBrowsingEnabled(false);
        }

        web.setWebViewClient(new AssetClient());
        web.setWebChromeClient(new Chrome());

        // 导出下载桥。为什么必须自己搭：
        // 页面用 downloadBlob() —— 造一个 blob: URL 再 <a download> 点一下。
        // 这在桌面 Chrome 能存盘，但在 WebView 里**什么都不发生**（不报错、不回调、
        // 文件不落地，logcat 也一片安静）。实测确认：/sdcard/Download 没有文件。
        // 结果就是「导出 DOCX / 导出盲文 / 下载音频」全废。
        // 这里自己接住 DownloadListener，把 blob 用 fetch 读成 base64、分片喂回 Java，
        // 再经 MediaStore 落到系统「下载」目录。只动外壳，不碰产品代码。
        web.addJavascriptInterface(new DownloadBridge(), "YuyiBridge");

        // ★ 原生 TTS + 原生落盘桥。页面侧（index.html §6.7 / downloadBlob）只要看到
        //   window.YuyiNative.speak / .saveFile 存在就直接走它，所以这里必须注册，
        //   而且方法上必须有 @JavascriptInterface —— 少一个注解，JS 侧拿到的是
        //   undefined，页面会**静默**退回浏览器路径，在 WebView 里就是"没声音 / 没文件"。
        web.addJavascriptInterface(new NativeBridge(), "YuyiNative");
        initTts();

        web.setDownloadListener(new android.webkit.DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                                        String mimetype, long contentLength) {
                String name = guessFileName(contentDisposition, url, mimetype);
                Log.i(TAG, "onDownloadStart mime=" + mimetype + " name=" + name
                        + " url=" + (url == null ? "null" : url.substring(0, Math.min(48, url.length()))));
                if (url != null && (url.startsWith("blob:") || url.startsWith("data:"))) {
                    pullBlob(url, name, mimetype == null ? "application/octet-stream" : mimetype);
                } else if (url != null) {
                    try {
                        Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(i);
                    } catch (Throwable t) {
                        toast("打不开下载链接：" + t);
                    }
                }
            }
        });

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            web.loadUrl(startUrl);
        }

        askPermissions();
        handleEvalIntent(getIntent());
        dumpProbe("APP_START", "{\"startUrl\":\"" + startUrl + "\",\"sdk\":" + Build.VERSION.SDK_INT
                + ",\"model\":" + Build.MODEL + "}");
    }

    /**
     * 允许外部指定首屏页面（诊断用）：--es yuyi_page selftest.html
     * 只接受本站相对路径 —— 带 ".." 或 ":" 一律拒绝，避免被当成任意 URL 加载。
     */
    private static String normalizePagePath(String raw) {
        if (raw == null) return null;
        String p = raw.trim();
        while (p.startsWith("/")) p = p.substring(1);
        if (p.length() == 0 || p.contains("..") || p.contains(":") || p.contains("\\")) return null;
        return p;
    }

    /* =================================================================== */
    /*  权限                                                               */
    /* =================================================================== */

    private void askPermissions() {
        if (Build.VERSION.SDK_INT < 23) return;             // 6.0 以下安装即授予
        List<String> need = new ArrayList<String>();
        if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            need.add(android.Manifest.permission.RECORD_AUDIO);
        }
        // 页面用 ServiceWorkerRegistration.showNotification 弹常驻提醒，
        // Android 13+ 需要 POST_NOTIFICATIONS 运行时权限
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                != PackageManager.PERMISSION_GRANTED) {
            need.add("android.permission.POST_NOTIFICATIONS");
        }
        if (!need.isEmpty()) {
            requestPermissions(need.toArray(new String[need.size()]), REQ_PERMS);
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        super.onRequestPermissionsResult(code, perms, results);
        if (code != REQ_PERMS) return;
        for (int i = 0; i < perms.length; i++) {
            Log.i(TAG, "perm " + perms[i] + " -> "
                    + (results[i] == PackageManager.PERMISSION_GRANTED ? "GRANTED" : "DENIED"));
        }
    }

    /* =================================================================== */
    /*  资源伺服：https://appassets.local/<path>  ->  assets/<path>        */
    /* =================================================================== */

    private class AssetClient extends WebViewClient {

        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            if (request == null) return null;
            Uri u = request.getUrl();
            if (u == null || !isOurs(u)) return null;
            return serve(u.getPath());
        }

        @Override
        @SuppressWarnings("deprecation")
        public WebResourceResponse shouldInterceptRequest(WebView view, String url) {
            if (url == null) return null;
            Uri u = Uri.parse(url);
            if (!isOurs(u)) return null;
            return serve(u.getPath());
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            Log.i(TAG, "onPageFinished " + url);
            // 先装「记住 <a download> 文件名」的补丁，再跑验收快照
            web.evaluateJavascript(DL_PATCH_JS, null);
            // 装 TTS 事件记录器：原生 UtteranceProgressListener 的 start/done/error
            // 会回调到 window.__nativeTtsEvent（页面本身不定义它，这里补上，
            // 这样"桥真的被调用 + 引擎真的动了"才有页面侧可读的证据）
            web.evaluateJavascript(TTS_LOG_JS, null);
            autoProbe();
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            // 站内任何 http(s) 跳转都留在 WebView 里（页面里的 AI 端点等）
            return false;
        }
    }

    private static boolean isOurs(Uri u) {
        String host = u.getHost();
        return host != null && "appassets.local".equalsIgnoreCase(host);
    }

    /**
     * 把一个「根路径」映射到 assets 里的真实文件。
     *
     * 映射规则（导出依赖就靠这几条，破一条「导出文档」就废）：
     *   https://appassets.local/lib/x.js      →  assets/lib/x.js
     *   https://appassets.local/data/x.json   →  assets/data/x.json
     *   https://appassets.local/              →  assets/index.html
     *   https://appassets.local/lib/          →  assets/lib/index.html（目录兜底）
     * 每次伺服都记一条进 assetLog，页面侧可用 YuyiNative.assetLog(n) 读回来 ——
     * 这样"拦截器到底把 /lib/* 映射对没有"不用开控制台就能验。
     */
    private WebResourceResponse serve(String rawPath) {
        String path = rawPath;
        if (path == null || path.length() == 0 || "/".equals(path)) path = "/index.html";
        try {
            path = URLDecoder.decode(path, "UTF-8");
        } catch (Exception ignored) {
        }
        while (path.startsWith("/")) path = path.substring(1);
        if (path.length() == 0) path = "index.html";
        if (path.endsWith("/")) path += "index.html";

        // 目录穿越防护：assets 里不需要 ".."，直接拒
        if (path.contains("..")) {
            noteAsset(path, 400, "text/plain", -1);
            return error(400, "bad path");
        }

        InputStream in = openAsset(path);
        if (in == null) {
            Log.w(TAG, "ASSET 404: " + path);
            noteAsset(path, 404, "text/plain", -1);
            return error(404, "not found: " + path);
        }

        String mime = mimeOf(path);
        String enc = isTextual(mime) ? "utf-8" : null;
        noteAsset(path, 200, mime, lengthOf(path, in));
        Map<String, String> headers = new HashMap<String, String>();
        // 内置资源不可变，长缓存能少走几次 AssetManager
        headers.put("Cache-Control", "public, max-age=31536000");
        headers.put("Access-Control-Allow-Origin", ORIGIN);

        WebResourceResponse r = new WebResourceResponse(mime, enc, 200, "OK", headers, in);
        // 注意：不要调 r.setImmutable(true) —— 那是 @hide API，public android.jar 里没有，
        // javac 会直接报「找不到符号」。
        return r;
    }

    /** 未压缩资源能直接问出长度；压缩过的退回 available()。拿不到就 -1。 */
    private long lengthOf(String assetPath, InputStream in) {
        try {
            AssetFileDescriptor fd = getAssets().openFd(assetPath);
            try {
                long n = fd.getLength();
                if (n >= 0) return n;
            } finally {
                fd.close();
            }
        } catch (Throwable ignored) {
            // 压缩过的 asset 打不开 fd，正常
        }
        try {
            return in.available();
        } catch (Throwable ignored) {
            return -1;
        }
    }

    private InputStream openAsset(String path) {
        try {
            return getAssets().open(path);
        } catch (IOException e) {
            // 目录请求兜底：/lib/ -> /lib/index.html
            try {
                return getAssets().open(path + "/index.html");
            } catch (IOException e2) {
                return null;
            }
        }
    }

    private static WebResourceResponse error(int code, String msg) {
        byte[] body;
        try {
            body = msg.getBytes("UTF-8");
        } catch (Exception e) {
            body = new byte[0];
        }
        return new WebResourceResponse("text/plain", "utf-8", code,
                code == 404 ? "Not Found" : "Bad Request", null,
                new ByteArrayInputStream(body));
    }

    private static boolean isTextual(String mime) {
        return mime.startsWith("text/")
                || "application/javascript".equals(mime)
                || "application/json".equals(mime)
                || "application/manifest+json".equals(mime)
                || "image/svg+xml".equals(mime)
                || "application/xml".equals(mime);
    }

    /**
     * MIME 表。给错会直接导致「脚本不执行 / JSON 解析失败」，所以这里按
     * 需求逐条钉死：
     *   .js   → text/javascript   （application/javascript 也对，但按约定用前者）
     *   .json → application/json
     *   .html → text/html
     *   .gz   → application/gzip  （vosk 的 model.tar.gz；以前落到 octet-stream）
     */
    private static String mimeOf(String p) {
        String s = p.toLowerCase();
        if (s.endsWith(".html") || s.endsWith(".htm")) return "text/html";
        if (s.endsWith(".js") || s.endsWith(".mjs")) return "text/javascript";
        if (s.endsWith(".json") || s.endsWith(".map")) return "application/json";
        if (s.endsWith(".css")) return "text/css";
        if (s.endsWith(".svg")) return "image/svg+xml";
        if (s.endsWith(".wasm")) return "application/wasm";
        if (s.endsWith(".png")) return "image/png";
        if (s.endsWith(".jpg") || s.endsWith(".jpeg")) return "image/jpeg";
        if (s.endsWith(".webp")) return "image/webp";
        if (s.endsWith(".gif")) return "image/gif";
        if (s.endsWith(".ico")) return "image/x-icon";
        if (s.endsWith(".woff2")) return "font/woff2";
        if (s.endsWith(".woff")) return "font/woff";
        if (s.endsWith(".ttf")) return "font/ttf";
        if (s.endsWith(".txt") || s.endsWith(".md")) return "text/plain";
        if (s.endsWith(".webmanifest")) return "application/manifest+json";
        if (s.endsWith(".gz") || s.endsWith(".tgz")) return "application/gzip";
        if (s.endsWith(".zip")) return "application/zip";
        if (s.endsWith(".docx")) {
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
        }
        // 其它二进制：交给应用自己解析，别猜语义
        return "application/octet-stream";
    }

    /* ------------------------------------------------------------------ */
    /*  assets 伺服记录（验证 /lib/* 映射用，最多留 64 条）                  */
    /* ------------------------------------------------------------------ */

    private final ArrayList<String> assetLog = new ArrayList<String>();

    private synchronized void noteAsset(String path, int status, String mime, long len) {
        Log.i(TAG, "ASSET " + status + " " + path + " mime=" + mime + " len=" + len);
        assetLog.add("{\"path\":\"" + esc(path) + "\",\"status\":" + status
                + ",\"mime\":\"" + esc(mime) + "\",\"len\":" + len + "}");
        while (assetLog.size() > 64) assetLog.remove(0);
    }

    private synchronized String assetLogJson(int limit) {
        int n = assetLog.size();
        int from = (limit > 0 && limit < n) ? n - limit : 0;
        StringBuilder sb = new StringBuilder("[");
        for (int i = from; i < n; i++) {
            if (sb.length() > 1) sb.append(',');
            sb.append(assetLog.get(i));
        }
        return sb.append(']').toString();
    }

    /* =================================================================== */
    /*  WebChromeClient：麦克风授权 + 控制台捕获                            */
    /* =================================================================== */

    private class Chrome extends WebChromeClient {

        /**
         * getUserMedia 在 WebView 里走这里。不实现它，麦克风永远拿不到
         * —— 不管 Android 侧 RECORD_AUDIO 有没有给。
         */
        @Override
        public void onPermissionRequest(final PermissionRequest request) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    String[] res = request.getResources();
                    boolean wantAudio = false;
                    for (String r : res) {
                        if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(r)) wantAudio = true;
                    }
                    if (wantAudio) {
                        Log.i(TAG, "grant WebView audio capture");
                        request.grant(res);
                    } else {
                        Log.i(TAG, "deny WebView request: " + java.util.Arrays.toString(res));
                        request.deny();
                    }
                }
            });
        }

        @Override
        public boolean onConsoleMessage(ConsoleMessage m) {
            if (m == null) return true;
            // 转发到 logcat（本机 vivo 把第三方 app 日志关了，persist.sys.log.ctrl=no，
            // 所以真正可靠的是 takePendingConsole() 那条文件通道）
            Log.i(TAG_CONSOLE, m.messageLevel() + " | " + m.sourceId() + ":" + m.lineNumber()
                    + " | " + m.message());
            noteConsole(m.messageLevel() + " | " + m.sourceId() + ":" + m.lineNumber()
                    + " | " + m.message());
            return true;
        }
    }

    /* =================================================================== */
    /*  原生桥 window.YuyiNative —— TTS + 落盘 + 诊断                       */
    /* =================================================================== */

    /**
     * 页面侧只认 window.YuyiNative，方法签名见 index.html：
     *   speak(text, rate)        ttsSpeakRaw() 优先调用它
     *   stop()                   ttsStop() 调用它
     *   saveFile(name, b64, mime)downloadBlob() 调用它（同步返回落点字符串）
     * 另外三个是本壳自己加的诊断出口（页面不依赖，加不到不影响产品功能）：
     *   available()              引擎是否真的能用（无中文引擎 / init 失败 → false）
     *   status()                 引擎名 / init 状态 / setLanguage 结果 / speak 返回码 / 回调计数
     *   assetLog(n)              最近 n 条 assets 伺服记录（验 /lib/* 映射）
     *
     * 每个方法都必须有 @JavascriptInterface：Android 4.2+ 起没有这个注解的方法
     * 对 JS 不可见，页面会拿到 undefined 然后**静默**走浏览器退化路径。
     */
    public class NativeBridge {

        /* ------------------------------ TTS ------------------------------ */

        @JavascriptInterface
        public boolean available() {
            return ttsReady && ttsLangOk() && !ttsShutdown;
        }

        @JavascriptInterface
        public void speak(final String text, final double rate) {
            ttsSpeakCalls++;
            float r = (float) rate;
            boolean clamped = false;
            if (Float.isNaN(r) || r <= 0f) {
                r = 1.0f;
                clamped = true;
            }
            if (r < RATE_MIN) { r = RATE_MIN; clamped = true; }
            if (r > RATE_MAX) { r = RATE_MAX; clamped = true; }
            if (clamped) ttsRateClamped = true;
            ttsLastRate = r;
            ttsLastText = shorten(text, 80);
            Log.i(TAG_TTS, "speak #" + ttsSpeakCalls + " len=" + (text == null ? 0 : text.length())
                    + " rate=" + r + " ready=" + ttsReady + " text=" + ttsLastText);

            final TextToSpeech t = tts;
            if (t == null || !ttsReady || ttsShutdown) {
                // 没引擎 / 还没 init 完 / 已 shutdown：**静默无害**，不崩，
                // 但如实记账，页面可以用 available()/status() 知道。
                ttsLastSpeakRet = -1000;
                ttsLastErr = ttsShutdown ? "tts 已 shutdown" : "tts 未就绪";
                Log.w(TAG_TTS, "speak 忽略：" + ttsLastErr);
                dumpProbe("TTS_SPEAK_SKIPPED", ttsStatusJson(), false);
                return;
            }
            final float rateFinal = r;
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    doSpeak(t, text, rateFinal);
                }
            });
        }

        @JavascriptInterface
        public void stop() {
            final TextToSpeech t = tts;
            Log.i(TAG_TTS, "stop()");
            if (t == null || ttsShutdown) return;
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    try {
                        t.stop();
                    } catch (Throwable th) {
                        Log.w(TAG_TTS, "stop 抛错", th);
                    }
                }
            });
        }

        @JavascriptInterface
        public String status() {
            return ttsStatusJson();
        }

        /* ---------------------------- 落盘 ---------------------------- */

        /**
         * 同步把 base64 写成文件，返回落点字符串（页面把它 toast 出来）。
         * 失败**抛异常**——页面 catch 到会明确说「保存到本机失败」，
         * 不会出现"看起来导出成功其实没文件"。
         */
        @JavascriptInterface
        public String saveFile(String name, String b64, String mime) {
            long t0 = System.currentTimeMillis();
            try {
                if (b64 == null || b64.length() == 0) throw new IOException("内容为空");
                byte[] data = android.util.Base64.decode(b64, android.util.Base64.DEFAULT);
                String safe = sanitizeName(name);
                String m = (mime == null || mime.length() == 0)
                        ? "application/octet-stream" : mime;
                String where;
                if (Build.VERSION.SDK_INT >= 29) {
                    ContentValues cv = new ContentValues();
                    cv.put(MediaStore.Downloads.DISPLAY_NAME, safe);
                    cv.put(MediaStore.Downloads.MIME_TYPE, m);
                    cv.put(MediaStore.Downloads.IS_PENDING, 1);
                    Uri uri = getContentResolver()
                            .insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
                    if (uri == null) throw new IOException("MediaStore.insert 返回 null");
                    java.io.OutputStream os = null;
                    try {
                        os = getContentResolver().openOutputStream(uri);
                        if (os == null) throw new IOException("openOutputStream 返回 null");
                        os.write(data);
                        os.flush();
                    } finally {
                        if (os != null) {
                            try {
                                os.close();
                            } catch (Throwable ignored) {
                            }
                        }
                    }
                    ContentValues done = new ContentValues();
                    done.put(MediaStore.Downloads.IS_PENDING, 0);
                    getContentResolver().update(uri, done, null, null);
                    where = "Download/" + safe;
                } else {
                    File dir = Environment.getExternalStoragePublicDirectory(
                            Environment.DIRECTORY_DOWNLOADS);
                    if (!dir.exists() && !dir.mkdirs()) throw new IOException("建不了下载目录");
                    File f = new File(dir, safe);
                    FileOutputStream fo = new FileOutputStream(f);
                    try {
                        fo.write(data);
                        fo.flush();
                    } finally {
                        fo.close();
                    }
                    where = f.getAbsolutePath();
                }
                Log.i(TAG, "saveFile ok name=" + safe + " bytes=" + data.length + " -> " + where);
                dumpProbe("SAVE_FILE", "{\"ok\":true,\"name\":\"" + esc(safe) + "\",\"bytes\":"
                        + data.length + ",\"mime\":\"" + esc(m) + "\",\"where\":\"" + esc(where)
                        + "\",\"ms\":" + (System.currentTimeMillis() - t0) + "}", false);
                return where;
            } catch (Throwable t) {
                Log.w(TAG, "saveFile 失败", t);
                dumpProbe("SAVE_FILE_FAIL", "{\"ok\":false,\"name\":\"" + esc(String.valueOf(name))
                        + "\",\"err\":\"" + esc(String.valueOf(t)) + "\"}", false);
                throw new RuntimeException("保存失败：" + t);
            }
        }

        /* ---------------------------- 诊断 ---------------------------- */

        @JavascriptInterface
        public String assetLog(int limit) {
            return assetLogJson(limit);
        }
    }

    /* ------------------------------------------------------------------ */
    /*  TTS 引擎                                                           */
    /* ------------------------------------------------------------------ */

    /**
     * 为什么必须自己接 TextToSpeech：
     * Android WebView **不实现** Web Speech API 的 speechSynthesis，所以页面的
     * ttsSpeakRaw() 在浏览器里能出声、套进 App 里一声不响。这是"为啥不能发声音"
     * 的根因；页面侧已改成优先调 window.YuyiNative.speak，这里把引擎接上。
     *
     * targetSdk 30+ 还必须在 AndroidManifest 里声明
     * <queries><intent><action android:name="android.intent.action.TTS_SERVICE"/>
     * 否则包可见性会把 TTS 引擎挡在外面，onInit 直接 ERROR。
     */
    private void initTts() {
        try {
            tts = new TextToSpeech(getApplicationContext(), new TextToSpeech.OnInitListener() {
                @Override
                public void onInit(int status) {
                    ttsInitStatus = status;
                    Log.i(TAG_TTS, "TextToSpeech.onInit status=" + status
                            + " (0=SUCCESS, -1=ERROR)");
                    if (status != TextToSpeech.SUCCESS || tts == null) {
                        ttsReady = false;
                        ttsLastErr = "onInit status=" + status;
                        dumpProbe("TTS_INIT", ttsStatusJson(), false);
                        return;
                    }
                    try {
                        int r = tts.setLanguage(Locale.CHINESE);
                        ttsLangResult = r;
                        Log.i(TAG_TTS, "setLanguage(Locale.CHINESE) -> " + r
                                + " (" + langLabel(r) + ")");
                    } catch (Throwable t) {
                        ttsLastErr = "setLanguage 抛错: " + t;
                        Log.w(TAG_TTS, "setLanguage 抛错", t);
                    }
                    try {
                        ttsEnginePkg = String.valueOf(tts.getDefaultEngine());
                    } catch (Throwable ignored) {
                    }
                    try {
                        java.util.List<TextToSpeech.EngineInfo> es = tts.getEngines();
                        ttsVoiceCount = (es == null) ? -1 : es.size();
                    } catch (Throwable ignored) {
                    }
                    try {
                        tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                            @Override
                            public void onStart(String id) {
                                noteTtsEvent("start", id, "");
                            }

                            @Override
                            public void onDone(String id) {
                                noteTtsEvent("done", id, "");
                            }

                            @Override
                            public void onError(String id) {
                                noteTtsEvent("error", id, "");
                            }

                            @Override
                            public void onError(String id, int code) {
                                noteTtsEvent("error", id, "code=" + code);
                            }

                            @Override
                            public void onStop(String id, boolean interrupted) {
                                noteTtsEvent("stop", id, "interrupted=" + interrupted);
                            }
                        });
                    } catch (Throwable t) {
                        Log.w(TAG_TTS, "setOnUtteranceProgressListener 抛错", t);
                    }
                    ttsReady = true;
                    if (!ttsLangOk()) {
                        ttsLastErr = "中文不可用: " + langLabel(ttsLangResult);
                    }
                    Log.i(TAG_TTS, "TTS READY engine=" + ttsEnginePkg
                            + " voices=" + ttsVoiceCount + " langOk=" + ttsLangOk());
                    dumpProbe("TTS_INIT", ttsStatusJson(), false);
                }
            });
        } catch (Throwable t) {
            tts = null;
            ttsReady = false;
            ttsLastErr = "构造 TextToSpeech 抛错: " + t;
            Log.w(TAG_TTS, "构造 TextToSpeech 失败", t);
            dumpProbe("TTS_INIT_FAIL", ttsStatusJson(), false);
        }
    }

    /** 真正调引擎那一下：必须已经在主线程上。 */
    private void doSpeak(TextToSpeech t, String text, float rate) {
        if (text == null || text.trim().length() == 0) {
            ttsLastSpeakRet = -1001;
            ttsLastErr = "空文本";
            return;
        }
        try {
            t.setSpeechRate(rate);
            String id = "yuyi-" + (++ttsUtterSeq);
            int ret = t.speak(text, TextToSpeech.QUEUE_FLUSH, null, id);
            ttsLastSpeakRet = ret;
            if (ret == TextToSpeech.SUCCESS) ttsSpeakOkCalls++;
            Log.i(TAG_TTS, "TextToSpeech.speak -> " + ret + " (0=SUCCESS) id=" + id
                    + " rate=" + rate);
            if (ret != TextToSpeech.SUCCESS) {
                ttsLastErr = "speak 返回 " + ret;
                dumpProbe("TTS_SPEAK_ERR", ttsStatusJson(), false);
            }
        } catch (Throwable th) {
            ttsLastSpeakRet = -1002;
            ttsLastErr = "speak 抛错: " + th;
            Log.w(TAG_TTS, "speak 抛错", th);
            dumpProbe("TTS_SPEAK_THROW", ttsStatusJson(), false);
        }
    }

    private static boolean ttsLangOkResult(int r) {
        return r == TextToSpeech.LANG_AVAILABLE
                || r == TextToSpeech.LANG_COUNTRY_AVAILABLE
                || r == TextToSpeech.LANG_COUNTRY_VAR_AVAILABLE;
    }

    private boolean ttsLangOk() {
        return ttsLangOkResult(ttsLangResult);
    }

    private static String langLabel(int r) {
        switch (r) {
            case TextToSpeech.LANG_AVAILABLE: return "LANG_AVAILABLE";
            case TextToSpeech.LANG_COUNTRY_AVAILABLE: return "LANG_COUNTRY_AVAILABLE";
            case TextToSpeech.LANG_COUNTRY_VAR_AVAILABLE: return "LANG_COUNTRY_VAR_AVAILABLE";
            case TextToSpeech.LANG_MISSING_DATA: return "LANG_MISSING_DATA";
            case TextToSpeech.LANG_NOT_SUPPORTED: return "LANG_NOT_SUPPORTED";
            default: return "未调用/未知(" + r + ")";
        }
    }

    /** UtteranceProgressListener 的回调：记账 + 回报页面 + 落 probe.txt。 */
    private void noteTtsEvent(String kind, String id, String extra) {
        ttsEvents++;
        ttsLastEvent = kind + ":" + id + (extra == null || extra.length() == 0 ? "" : ":" + extra);
        Log.i(TAG_TTS, "event " + ttsLastEvent);
        dumpProbe("TTS_EVENT", ttsLastEvent, false);
        final WebView w = web;
        if (w == null) return;
        final String js = "window.__nativeTtsEvent && window.__nativeTtsEvent("
                + jsStr(kind) + "," + jsStr(id) + "," + jsStr(extra == null ? "" : extra) + ")";
        w.post(new Runnable() {
            @Override
            public void run() {
                WebView ww = web;
                if (ww == null) return;
                try {
                    ww.evaluateJavascript(js, null);
                } catch (Throwable ignored) {
                }
            }
        });
    }

    /**
     * 页面侧的 TTS 事件记录器。
     * 页面本身不定义 window.__nativeTtsEvent（那是壳的约定），这里补上，
     * 于是"原生的 start/done/error 到底有没有来"在页面里也能读到
     * （window.__yuyiTtsLog），不依赖控制台。
     */
    private static final String TTS_LOG_JS =
            "(function(){try{"
            + "if(window.__yuyiTtsLog)return 'already';"
            + "window.__yuyiTtsLog=[];"
            + "window.__nativeTtsEvent=function(kind,id,extra){try{"
            + "  window.__yuyiTtsLog.push({t:Date.now(),kind:String(kind),id:String(id),extra:String(extra||'')});"
            + "  if(window.__yuyiTtsLog.length>200)window.__yuyiTtsLog.shift();"
            + "}catch(e){}};"
            + "return 'tts-log-installed'}catch(e){return 'ERR:'+e.message}})()";

    private String ttsStatusJson() {
        return "{\"ready\":" + ttsReady
                + ",\"available\":" + (ttsReady && ttsLangOk() && !ttsShutdown)
                + ",\"shutdown\":" + ttsShutdown
                + ",\"initStatus\":" + ttsInitStatus
                + ",\"langResult\":" + ttsLangResult
                + ",\"langLabel\":\"" + langLabel(ttsLangResult) + "\""
                + ",\"langOk\":" + (ttsLangResult == Integer.MIN_VALUE ? false : ttsLangOk())
                + ",\"engine\":\"" + esc(ttsEnginePkg) + "\""
                + ",\"engineCount\":" + ttsVoiceCount
                + ",\"rateClamped\":" + ttsRateClamped
                + ",\"speakCalls\":" + ttsSpeakCalls
                + ",\"speakOkCalls\":" + ttsSpeakOkCalls
                + ",\"lastSpeakRet\":" + ttsLastSpeakRet
                + ",\"lastRate\":" + ttsLastRate
                + ",\"lastSpeakText\":\"" + esc(ttsLastText) + "\""
                + ",\"events\":" + ttsEvents
                + ",\"lastEvent\":\"" + esc(ttsLastEvent) + "\""
                + ",\"lastError\":\"" + esc(ttsLastErr) + "\"}";
    }

    /** 最小 JSON 字符串转义（诊断 JSON 都是自己拼的，别让引号把结构打穿）。 */
    private static String esc(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) sb.append(' ');
                    else sb.append(c);
            }
        }
        return sb.toString();
    }

    private static String shorten(String s, int max) {
        if (s == null) return "";
        String t = s.replace('\n', ' ').replace('\r', ' ');
        return t.length() <= max ? t : t.substring(0, max) + "…";
    }

    /** MediaStore 的 DISPLAY_NAME 不能带路径分隔符和一堆保留字符。 */
    private static String sanitizeName(String n) {
        String s = (n == null || n.trim().length() == 0) ? "yuyi-file.bin" : n.trim();
        StringBuilder sb = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c < 0x20 || c == '\\' || c == '/' || c == ':' || c == '*'
                    || c == '?' || c == '"' || c == '<' || c == '>' || c == '|') {
                sb.append('_');
            } else {
                sb.append(c);
            }
        }
        String r = sb.toString();
        if (r.length() > 120) {
            int dot = r.lastIndexOf('.');
            String ext = (dot > 0 && r.length() - dot <= 8) ? r.substring(dot) : "";
            r = r.substring(0, 120 - ext.length()) + ext;
        }
        return r;
    }

    /* =================================================================== */
    /*  导出下载：blob: -> 真正落盘                                          */
    /* =================================================================== */

    private android.widget.Toast lastToast;

    private void toast(final String msg) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    if (lastToast != null) lastToast.cancel();
                    lastToast = android.widget.Toast.makeText(MainActivity.this, msg,
                            android.widget.Toast.LENGTH_LONG);
                    lastToast.show();
                } catch (Throwable ignored) {
                }
            }
        });
    }

    /**
     * 让页面把 blob 读成 base64 分片回传。
     * 分片是因为 JavascriptInterface 的字符串走 binder，单次约 1MB 上限
     * （一段 750KB 的录音 base64 之后就有 1MB，整块传会直接崩）。
     */
    private void pullBlob(String url, String name, String mime) {
        // 名字优先用页面 <a download="..."> 上写的那个 —— WebView 的 DownloadListener
        // 对 blob: 不传 contentDisposition，光靠它只会得到 yuyi-<时间戳>.bin 这种名字。
        // DL_PATCH_JS 在页面加载完时挂了个钩子，把 href -> download 记在
        // window.__yuyiDlNames 里，这里查一下。
        String js = "(function(){try{"
                + "var u=" + jsStr(url) + ";"
                + "var nm=(window.__yuyiDlNames&&window.__yuyiDlNames[u])||" + jsStr(name) + ";"
                + "fetch(u).then(function(r){return r.blob()}).then(function(b){"
                + "  var fr=new FileReader();"
                + "  fr.onload=function(){"
                + "    var s=String(fr.result), i=s.indexOf(',');"
                + "    var b64=i>=0?s.slice(i+1):'';"
                + "    YuyiBridge.begin(nm," + jsStr(mime) + ");"
                + "    var CH=131072;"
                + "    for(var k=0;k<b64.length;k+=CH){ YuyiBridge.chunk(b64.substr(k,CH)); }"
                + "    YuyiBridge.end();"
                + "  };"
                + "  fr.onerror=function(){ YuyiBridge.fail('FileReader 读取失败') };"
                + "  fr.readAsDataURL(b);"
                + "}).catch(function(e){ YuyiBridge.fail(String(e&&e.message||e)) });"
                + "return 'started'}catch(e){return 'ERR:'+e.message}})()";
        web.evaluateJavascript(js, null);
    }

    /**
     * 记住每个 blob URL 对应的 <a download> 文件名。
     * 只挂 HTMLAnchorElement.prototype.click，不改任何业务逻辑；
     * 页面还是照样点它自己的链接，我们只是顺手把名字抄下来。
     */
    private static final String DL_PATCH_JS =
            "(function(){try{"
            + "if(window.__yuyiDlPatched)return 'already';"
            + "window.__yuyiDlPatched=1;window.__yuyiDlNames={};"
            + "var proto=HTMLAnchorElement.prototype,orig=proto.click;"
            + "proto.click=function(){"
            + "  try{ if(this.href&&this.download){window.__yuyiDlNames[this.href]=this.download;} }catch(e){}"
            + "  return orig.apply(this,arguments);"
            + "};"
            + "return 'patched'}catch(e){return 'ERR:'+e.message}})()";

    /** 把 Java 字符串安全地嵌进 JS 单引号字面量。 */
    private static String jsStr(String s) {
        if (s == null) return "''";
        StringBuilder sb = new StringBuilder("'");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '\\' || c == '\'') sb.append('\\').append(c);
            else if (c == '\n') sb.append("\\n");
            else if (c == '\r') sb.append("\\r");
            else if (c < 0x20) sb.append(' ');
            else sb.append(c);
        }
        return sb.append('\'').toString();
    }

    private static String guessFileName(String cd, String url, String mime) {
        String name = null;
        try {
            if (cd != null) {
                java.util.regex.Matcher m = java.util.regex.Pattern
                        .compile("filename\\*\\s*=\\s*[^']*''([^;\\n]+)",
                                java.util.regex.Pattern.CASE_INSENSITIVE).matcher(cd);
                if (m.find()) {
                    try {
                        name = URLDecoder.decode(m.group(1).trim(), "UTF-8");
                    } catch (Exception e) {
                        name = m.group(1);
                    }
                }
                if (name == null) {
                    m = java.util.regex.Pattern
                            .compile("filename\\s*=\\s*\"?([^\";\\n]+)\"?",
                                    java.util.regex.Pattern.CASE_INSENSITIVE).matcher(cd);
                    if (m.find()) name = m.group(1).trim();
                }
            }
        } catch (Throwable ignored) {
        }
        if (name == null || name.length() == 0) {
            name = "yuyi-" + new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date());
            if (mime == null) name += ".bin";
            else if (mime.contains("word")) name += ".docx";
            else if (mime.contains("json")) name += ".json";
            else if (mime.contains("zip")) name += ".zip";
            else if (mime.contains("text")) name += ".txt";
            else name += ".bin";
        }
        return name;
    }

    /** 只对本站内容开 addJavascriptInterface（不加载任何外部页面），所以风险可控。 */
    public class DownloadBridge {
        private java.io.OutputStream out;
        private Uri uri;
        private String name = "";

        @android.webkit.JavascriptInterface
        public void begin(String n, String mime) {
            try {
                closeQuietly(true);
                name = n;
                if (Build.VERSION.SDK_INT >= 29) {
                    ContentValues cv = new ContentValues();
                    cv.put(MediaStore.Downloads.DISPLAY_NAME, n);
                    cv.put(MediaStore.Downloads.MIME_TYPE, mime);
                    cv.put(MediaStore.Downloads.IS_PENDING, 1);
                    uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
                    if (uri == null) {
                        toast("下载失败：MediaStore 插入失败");
                        return;
                    }
                    out = getContentResolver().openOutputStream(uri);
                } else {
                    File dir = Environment.getExternalStoragePublicDirectory(
                            Environment.DIRECTORY_DOWNLOADS);
                    if (!dir.exists()) dir.mkdirs();
                    out = new FileOutputStream(new File(dir, n));
                }
                Log.i(TAG, "download begin name=" + n + " mime=" + mime);
            } catch (Throwable t) {
                Log.w(TAG, "download begin 失败", t);
                toast("下载失败：" + t);
                out = null;
            }
        }

        @android.webkit.JavascriptInterface
        public void chunk(String b64) {
            if (out == null || b64 == null) return;
            try {
                out.write(android.util.Base64.decode(b64, android.util.Base64.DEFAULT));
            } catch (Throwable t) {
                Log.w(TAG, "download chunk 失败", t);
                closeQuietly(true);
            }
        }

        @android.webkit.JavascriptInterface
        public void end() {
            boolean ok = (out != null);
            closeQuietly(false);
            toast(ok ? ("已保存到「下载」：" + name) : "下载失败");
            dumpProbe("DOWNLOAD", "{\"ok\":" + ok + ",\"name\":\"" + name + "\"}");
        }

        @android.webkit.JavascriptInterface
        public void fail(String msg) {
            closeQuietly(true);
            toast("下载失败：" + msg);
            dumpProbe("DOWNLOAD_FAIL", String.valueOf(msg));
        }

        private void closeQuietly(boolean discard) {
            try {
                if (out != null) out.close();
            } catch (Throwable ignored) {
            }
            out = null;
            if (uri != null) {
                try {
                    if (discard) {
                        getContentResolver().delete(uri, null, null);
                    } else if (Build.VERSION.SDK_INT >= 29) {
                        ContentValues cv = new ContentValues();
                        cv.put(MediaStore.Downloads.IS_PENDING, 0);
                        getContentResolver().update(uri, cv, null, null);
                    }
                } catch (Throwable ignored) {
                }
                uri = null;
            }
        }
    }

    /* =================================================================== */
    /*  验收用的证据通道                                                    */
    /*  本机 vivo（V2270A）persist.sys.log.ctrl=no，第三方 app 的 Log.i       */
    /*  根本不会进 logcat（系统日志有、应用日志没有），所以结果另外落一份到   */
    /*  /sdcard/Android/data/com.yuyi.app/files/probe.txt，用 adb shell cat 读。*/
    /* =================================================================== */

    private final ArrayList<String> consoleLines = new ArrayList<String>();
    private int consoleFlushed = 0;

    private synchronized void noteConsole(String line) {
        consoleLines.add(line);
        if (consoleLines.size() > 800) {
            int drop = consoleLines.size() - 800;
            for (int i = 0; i < drop; i++) consoleLines.remove(0);
            consoleFlushed = Math.max(0, consoleFlushed - drop);
        }
    }

    private synchronized String takePendingConsole() {
        StringBuilder sb = new StringBuilder();
        for (int i = consoleFlushed; i < consoleLines.size(); i++) {
            sb.append(consoleLines.get(i)).append('\n');
        }
        consoleFlushed = consoleLines.size();
        return sb.toString();
    }

    /** 把一条「标记 + 值 + 自上次以来新增的控制台输出」追加进 probe.txt。 */
    private void dumpProbe(String marker, String value) {
        dumpProbe(marker, value, true);
    }

    /**
     * withConsole=false 只写标记 + 值。
     * TTS 的 start/done/error 回调很密，每条都带一份控制台尾巴会把 probe.txt
     * 撑爆，所以事件类记录走 false。
     */
    private void dumpProbe(String marker, String value, boolean withConsole) {
        Log.i(TAG_EVAL, marker + " " + value);
        String pending = withConsole ? takePendingConsole() : "";
        try {
            File dir = getExternalFilesDir(null);
            if (dir == null) return;
            if (!dir.exists()) dir.mkdirs();
            File f = new File(dir, "probe.txt");
            StringBuilder sb = new StringBuilder();
            sb.append("\n=== ").append(marker).append(" @ ")
              .append(new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US).format(new Date()))
              .append('\n');
            sb.append("VALUE: ").append(value).append('\n');
            if (pending.length() > 0) {
                sb.append("--- console since last dump ---\n").append(pending);
            }
            FileOutputStream fo = new FileOutputStream(f, true);
            try {
                fo.write(sb.toString().getBytes("UTF-8"));
                fo.flush();
            } finally {
                fo.close();
            }
        } catch (Throwable t) {
            Log.w(TAG_EVAL, "dumpProbe 失败: " + t);
        }
    }

    /* =================================================================== */
    /*  诊断钩子（纯本地、只读页面状态，不改产品代码）                       */
    /* =================================================================== */

    /**
     * 页面加载完自动打一份环境快照（probe.txt）。
     * 分两步：先跑异步采集塞进 window.__yuyiDiag，再同步读回来。
     * 为什么不能一步：实测这台机器的 WebView，evaluateJavascript **不会等 Promise**，
     * 直接返回的话拿到的是 Promise 对象序列化后的 "{}"，一点信息都没有。
     */
    private void autoProbe() {
        web.postDelayed(new Runnable() {
            @Override
            public void run() {
                web.evaluateJavascript(PROBE_ASYNC_JS, null);
                web.postDelayed(new Runnable() {
                    @Override
                    public void run() {
                        web.evaluateJavascript(PROBE_JS, new android.webkit.ValueCallback<String>() {
                            @Override
                            public void onReceiveValue(String v) {
                                dumpProbe("PROBE", v);
                            }
                        });
                    }
                }, 2500);
            }
        }, 2500);
    }

    /**
     * 允许外部现场求值：结果写进 probe.txt（见 dumpProbe）。
     * 两种传参：
     *   --es yuyi_eval     "<js>"       短表达式，走 adb shell 引号
     *   --es yuyi_eval_b64 "<base64>"   长 JS 走这个 —— adb shell 对含引号/括号/空格的
     *                                   长字符串转义极易出错，base64 只含 URL-safe 字符，
     *                                   怎么传都不会被 shell 吃掉。用 URL_SAFE + NO_PADDING。
     * 可选 --el yuyi_eval_delay <毫秒>，默认 2500。
     */
    private void handleEvalIntent(Intent it) {
        if (it == null || web == null) return;
        String js = it.getStringExtra("yuyi_eval");
        String b64 = it.getStringExtra("yuyi_eval_b64");
        if (b64 != null && b64.length() > 0) {
            try {
                byte[] raw = android.util.Base64.decode(b64,
                        android.util.Base64.URL_SAFE | android.util.Base64.NO_WRAP
                                | android.util.Base64.NO_PADDING);
                js = new String(raw, "UTF-8");
            } catch (Throwable t) {
                dumpProbe("EVAL_B64_DECODE_FAIL", String.valueOf(t));
                return;
            }
        }
        if (js == null) return;
        final String expr = js;
        long delay = it.getLongExtra("yuyi_eval_delay", 2500L);
        web.postDelayed(new Runnable() {
            @Override
            public void run() {
                web.evaluateJavascript(expr, new android.webkit.ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String v) {
                        dumpProbe("EVAL", v);
                    }
                });
            }
        }, delay);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        // 诊断用：可以把当前页切到内置自检页
        String page = normalizePagePath(intent == null ? null : intent.getStringExtra("yuyi_page"));
        if (page != null && web != null) {
            String u = ORIGIN + "/" + page;
            Log.i(TAG, "onNewIntent yuyi_page -> " + u);
            web.loadUrl(u);
        }
        handleEvalIntent(intent);
    }

    /**
     * 验收快照。返回 Promise —— evaluateJavascript 会等它 resolve 再回值，
     * 所以能顺带把 IndexedDB / Storage 这些异步信息一并捞出来。
     */
    private static final String PROBE_JS =
            "(function(){"
            + "var g=function(f){try{return f()}catch(e){return 'ERR:'+e.message}};"
            + "var out={};"
            + "out.url=location.href;"
            + "out.origin=location.origin;"
            + "out.secure=!!window.isSecureContext;"
            + "out.title=document.title;"
            + "out.ready=document.readyState;"
            + "out.bodyLen=document.body?document.body.innerHTML.length:0;"
            + "var nav=document.querySelectorAll('nav a,nav button,[role=tab],.tabbar>*,.tab-bar>*,.tabs>*');"
            + "out.navCount=nav.length;"
            + "out.navText=g(function(){var s=[];for(var i=0;i<nav.length&&i<12;i++){var t=(nav[i].innerText||'').trim();if(t)s.push(t.replace(/\\s+/g,' '))}return s.join(' | ')});"
            + "out.idb=typeof indexedDB;"
            + "out.lsOk=g(function(){localStorage.setItem('__p','1');var v=localStorage.getItem('__p');localStorage.removeItem('__p');return v==='1'});"
            + "out.sw=typeof navigator.serviceWorker;"
            + "out.yuyiASR=typeof window.YuyiASR;"
            + "out.yuyiASRver=g(function(){return window.YuyiASR&&window.YuyiASR.version});"
            + "out.docxMini=typeof window.DocxMini;"
            + "out.brailleZH=typeof window.BrailleZH;"
            + "out.brailleLoaded=g(function(){return !!(window.BrailleZH&&window.BrailleZH.ready)});"
            + "out.audioCtx=typeof (window.AudioContext||window.webkitAudioContext);"
            + "out.mediaDevices=typeof navigator.mediaDevices;"
            + "out.err=window.__err||null;"
            + "out.async=window.__yuyiDiag||null;"
            /* 原生桥体检：TTS 引擎状态 + 最近几条 assets 伺服记录。
               这两条不依赖 logcat（本机 vivo 把应用日志关了），是"桥接上了没有"
               最直接的证据。 */
            + "out.nativeBridge=typeof (window.YuyiNative&&window.YuyiNative.speak);"
            + "out.ttsNative=g(function(){return (window.YuyiNative&&window.YuyiNative.status)?window.YuyiNative.status():'NO-BRIDGE'});"
            + "out.ttsEvents=g(function(){return (window.__yuyiTtsLog||[]).length});"
            + "out.assetLog=g(function(){return (window.YuyiNative&&window.YuyiNative.assetLog)?window.YuyiNative.assetLog(14):'NO-BRIDGE'});"
            + "out.bodyHead=g(function(){return document.body.innerText.replace(/\\s+/g,' ').slice(0,400)});"
            + "return JSON.stringify(out)"
            + "})()";

    /**
     * 异步采集：跑完塞进 window.__yuyiDiag，由上面的同步 PROBE_JS 读回。
     * （本机 WebView 的 evaluateJavascript 不 await Promise，所以只能这么分两步。）
     */
    private static final String PROBE_ASYNC_JS =
            "(function(){"
            + "var d={};window.__yuyiDiag=d;"
            + "try{"
            + "  if(indexedDB.databases){"
            + "    indexedDB.databases().then(function(l){"
            + "      d.idbDbs=(l||[]).map(function(x){return x.name+':v'+x.version});"
            + "    }).catch(function(e){d.idbDbs='ERR:'+e.message});"
            + "  } else { d.idbDbs='databases() 不支持'; }"
            + "  if(navigator.storage&&navigator.storage.estimate){"
            + "    navigator.storage.estimate().then(function(e){"
            + "      d.quotaMB=Math.round((e.quota||0)/1048576);"
            + "      d.usageMB=Math.round((e.usage||0)/1048576);"
            + "      d.usageDetails=e.usageDetails||null;"
            + "    }).catch(function(e){d.quotaMB='ERR:'+e.message});"
            + "  }"
            + "  if(navigator.serviceWorker&&navigator.serviceWorker.getRegistrations){"
            + "    navigator.serviceWorker.getRegistrations().then(function(r){"
            + "      d.swRegs=(r||[]).map(function(x){return x.scope+' active='+(x.active?x.active.scriptURL:'null')});"
            + "    }).catch(function(e){d.swRegs='ERR:'+e.message});"
            + "  }"
            + "}catch(e){d.fatal=String(e)}"
            + "return 'async-started'"
            + "})()";

    /** 只问「休眠/唤醒」相关的轻量状态，用于 tap 之后复查。 */
    private static final String ASR_PROBE_JS =
            "(function(){var o={};try{"
            + "o.status=document.querySelector('.asr-status,.voice-status,[data-asr-status]')"
            + "  ?document.querySelector('.asr-status,.voice-status,[data-asr-status]').innerText:null;"
            + "o.pill=(function(){var el=document.querySelector('.wake,.voice-pill,#wakePill');return el?el.innerText:null})();"
            + "o.bodyHead=document.body?document.body.innerText.slice(0,600):null;"
            + "}catch(e){o.err=String(e)}return JSON.stringify(o)})()";

    /* =================================================================== */
    /*  生命周期                                                            */
    /* =================================================================== */

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        if (web != null) web.saveState(out);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (web != null) web.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
    }

    @Override
    protected void onDestroy() {
        // TTS 引擎是系统级绑定，不 shutdown 会一直挂着（引擎进程泄漏 + 播报继续）。
        if (tts != null) {
            try {
                tts.stop();
            } catch (Throwable ignored) {
            }
            try {
                tts.shutdown();
                ttsShutdown = true;
                Log.i(TAG_TTS, "TextToSpeech.shutdown() 完成");
                dumpProbe("TTS_SHUTDOWN", ttsStatusJson(), false);
            } catch (Throwable t) {
                Log.w(TAG_TTS, "shutdown 抛错", t);
            }
            tts = null;
        }
        if (web != null) {
            web.setWebChromeClient(null);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}