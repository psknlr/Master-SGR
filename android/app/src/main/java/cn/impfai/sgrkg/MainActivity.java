package cn.impfai.sgrkg;

/*
 * 国医大师孙光荣中医知识图谱 · Android 宿主
 * Sun Guangrong TCM Knowledge Graph — Android host activity
 *
 * 研发：孙光荣大师弟子田建辉团队 联合 医哲未来人工智能研究院 (IMPF-AI Institute)
 *
 * 说明：图谱本体是一套自带的离线 Web 应用（assets/web），本类只做三件事——
 *   1. 用一个受控的虚拟域名把 assets 里的文件喂给 WebView（保证同源，XHR 可用）；
 *   2. 把 Android 的返回键、系统栏配色和 Web 层打通；
 *   3. WebView 层禁止任何对外网络访问；「问道」的模型调用由原生 LlmClient 代发，
 *      主机白名单只放行 Poe / MiniMax 官方接口。
 */

import android.annotation.SuppressLint;
import android.content.Intent;
import android.content.res.AssetManager;
import android.content.res.Configuration;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.app.Activity;
import android.view.View;
import android.view.Window;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import android.os.Handler;
import android.os.Looper;

import org.json.JSONObject;

import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {

    /** 保留域名，公网不可解析；WebViewAssetLoader 用的也是它。 */
    private static final String ORIGIN = "https://appassets.androidplatform.net";
    private static final String ASSET_ROOT = "web";
    private static final String PREFS = "sgr_kg";

    private WebView web;
    private long lastBackAt = 0L;

    /* 问道：原生侧的 LLM 请求池。WebView 层禁止外联，只有这里能出网，且主机受白名单约束。 */
    private final ExecutorService llmPool = Executors.newFixedThreadPool(2);
    private final Map<String, LlmClient> llmActive = new ConcurrentHashMap<String, LlmClient>();
    private final Handler main = new Handler(Looper.getMainLooper());

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);

        String theme = getSharedPreferences(PREFS, MODE_PRIVATE).getString("theme", null);
        if (theme == null) {
            int mode = getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK;
            theme = (mode == Configuration.UI_MODE_NIGHT_YES) ? "night" : "paper";
        }
        applySystemBars(theme);

        web = new WebView(this);
        web.setBackgroundColor(paperColor(theme));
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(false);
        s.setUseWideViewPort(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setTextZoom(100);                       // 忽略系统字号，保证版式稳定
        s.setAllowFileAccess(false);              // 数据一律走 assets 拦截器
        s.setAllowContentAccess(false);
        s.setGeolocationEnabled(false);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            web.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false);
        }
        WebView.setWebContentsDebuggingEnabled(false);

        web.setWebViewClient(new AssetClient());
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage m) { return true; }
        });
        web.addJavascriptInterface(new Bridge(), "NativeApp");

        web.loadUrl(ORIGIN + "/assets/index.html?t=" + Uri.encode(theme));
    }

    /* ------------------------------------------------------------------ */
    /* assets 拦截：把 https://appassets.androidplatform.net/assets/... 映射到 APK  */
    /* ------------------------------------------------------------------ */
    private class AssetClient extends WebViewClient {

        @Override
        @SuppressWarnings("deprecation")
        public WebResourceResponse shouldInterceptRequest(WebView v, String url) {
            return serve(url);
        }

        @Override
        public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest req) {
            return serve(req.getUrl().toString());
        }

        @Override
        @SuppressWarnings("deprecation")
        public boolean shouldOverrideUrlLoading(WebView v, String url) {
            return handleNav(url);
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest req) {
            return handleNav(req.getUrl().toString());
        }
    }

    /** 应用自身的页面放行，其余一律交给系统浏览器（本应用目前不含外链）。 */
    private boolean handleNav(String url) {
        if (url != null && url.startsWith(ORIGIN)) return false;
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception ignored) {
            Toast.makeText(this, R.string.cannot_open_link, Toast.LENGTH_SHORT).show();
        }
        return true;
    }

    private static final Map<String, String> MIME = new HashMap<String, String>();
    static {
        MIME.put("html", "text/html");
        MIME.put("js", "application/javascript");
        MIME.put("css", "text/css");
        MIME.put("json", "application/json");
        MIME.put("svg", "image/svg+xml");
        MIME.put("png", "image/png");
        MIME.put("jpg", "image/jpeg");
        MIME.put("woff2", "font/woff2");
    }

    private WebResourceResponse serve(String url) {
        if (url == null || !url.startsWith(ORIGIN + "/assets/")) {
            // 任何非本地请求都掐掉，保证完全离线
            if (url != null && (url.startsWith("http://") || url.startsWith("https://"))) {
                return new WebResourceResponse("text/plain", "UTF-8", 403, "Blocked",
                        new HashMap<String, String>(), null);
            }
            return null;
        }
        String path = Uri.parse(url).getPath();          // /assets/....
        if (path == null) return null;
        path = path.substring("/assets/".length());
        if (path.isEmpty()) path = "index.html";
        if (path.contains("..")) return null;            // 目录穿越保护

        String ext = "";
        int dot = path.lastIndexOf('.');
        if (dot >= 0) ext = path.substring(dot + 1).toLowerCase();
        String mime = MIME.containsKey(ext) ? MIME.get(ext) : "application/octet-stream";
        String enc = mime.startsWith("text/") || "application/javascript".equals(mime)
                || "application/json".equals(mime) || "image/svg+xml".equals(mime) ? "UTF-8" : null;

        try {
            AssetManager am = getAssets();
            InputStream in = am.open(ASSET_ROOT + "/" + path);
            Map<String, String> headers = new HashMap<String, String>();
            headers.put("Cache-Control", "no-store");
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                return new WebResourceResponse(mime, enc, 200, "OK", headers, in);
            }
            return new WebResourceResponse(mime, enc, in);
        } catch (IOException e) {
            return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found",
                    new HashMap<String, String>(), null);
        }
    }

    /* ------------------------------------------------------------------ */
    /* JS ↔ Native 桥                                                      */
    /* ------------------------------------------------------------------ */
    private class Bridge {
        /** Web 层切换宣纸/夜读后同步系统栏配色。 */
        @JavascriptInterface
        public void setTheme(final String t) {
            final String theme = "night".equals(t) ? "night" : "paper";
            getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString("theme", theme).apply();
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    applySystemBars(theme);
                    web.setBackgroundColor(paperColor(theme));
                }
            });
        }

        @JavascriptInterface
        public void ready() { /* 图谱装载完成，占位以便后续扩展 */ }

        /* ---- 问道：流式对话 ---- */
        @JavascriptInterface
        public void llmStart(final String reqId, final String cfgJson) {
            final LlmClient client = new LlmClient();
            llmActive.put(reqId, client);
            llmPool.execute(new Runnable() {
                @Override public void run() {
                    JSONObject cfg;
                    try { cfg = new JSONObject(cfgJson); }
                    catch (Exception e) { emit(reqId, "error", "请求参数无效"); llmActive.remove(reqId); return; }
                    client.streamChat(cfg, new LlmClient.Listener() {
                        // 增量按 ~40ms 合批，避免每个 token 都跨进程刷一次 WebView
                        private final StringBuilder buf = new StringBuilder();
                        private boolean scheduled = false;
                        private final Runnable flush = new Runnable() {
                            @Override public void run() {
                                String s; synchronized (buf) { s = buf.toString(); buf.setLength(0); scheduled = false; }
                                if (!s.isEmpty()) emitNow(reqId, "chunk", s);
                            }
                        };
                        @Override public void onChunk(String text) {
                            synchronized (buf) { buf.append(text); if (scheduled) return; scheduled = true; }
                            main.postDelayed(flush, 40);
                        }
                        @Override public void onDone() { main.post(flush); emit(reqId, "done", ""); llmActive.remove(reqId); }
                        @Override public void onError(String m) { main.post(flush); emit(reqId, "error", m); llmActive.remove(reqId); }
                    });
                }
            });
        }

        @JavascriptInterface
        public void llmCancel(String reqId) {
            LlmClient c = llmActive.remove(reqId);
            if (c != null) c.cancel();
        }

        /* ---- 问道：受白名单约束的 GET（读取 Poe 公开模型目录） ---- */
        @JavascriptInterface
        public void httpGet(final String reqId, final String url) {
            llmPool.execute(new Runnable() {
                @Override public void run() {
                    String[] r = LlmClient.httpGet(url);
                    JSONObject o = new JSONObject();
                    try { o.put("status", Integer.parseInt(r[0])); o.put("body", r[1]); } catch (Exception ignored) { }
                    emit(reqId, "http", o.toString());
                }
            });
        }

        @JavascriptInterface
        public void share(final String text) {
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    Intent i = new Intent(Intent.ACTION_SEND);
                    i.setType("text/plain");
                    i.putExtra(Intent.EXTRA_TEXT, text);
                    startActivity(Intent.createChooser(i, getString(R.string.share_title)));
                }
            });
        }
    }

    /** 把事件送回 Web 层：window.__llmEvent(id, type, payload)。字符串用 JSONObject.quote 安全转义。 */
    private void emit(final String id, final String type, final String payload) {
        main.post(new Runnable() { @Override public void run() { emitNow(id, type, payload); } });
    }
    private void emitNow(String id, String type, String payload) {
        if (web == null) return;
        web.evaluateJavascript("window.__llmEvent&&__llmEvent(" + JSONObject.quote(id) + ","
                + JSONObject.quote(type) + "," + JSONObject.quote(payload == null ? "" : payload) + ")", null);
    }

    /* ------------------------------------------------------------------ */
    /* 系统栏配色                                                          */
    /* ------------------------------------------------------------------ */
    private int paperColor(String theme) {
        return "night".equals(theme) ? 0xFF16130F : 0xFFF3E9D6;
    }

    private void applySystemBars(String theme) {
        boolean night = "night".equals(theme);
        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            w.setStatusBarColor(night ? 0xFF16130F : 0xFFE3D5B9);
            w.setNavigationBarColor(night ? 0xFF1E1A15 : 0xFFEDE1CA);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            View dv = w.getDecorView();
            int flags = dv.getSystemUiVisibility();
            // 浅色背景需要深色图标
            if (night) flags &= ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            else flags |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                if (night) flags &= ~View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
                else flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            }
            dv.setSystemUiVisibility(flags);
        }
    }

    /* ------------------------------------------------------------------ */
    /* 返回键：先交给 Web 层收拢浮层，再考虑退出                             */
    /* ------------------------------------------------------------------ */
    @Override
    public void onBackPressed() {
        if (web == null) { super.onBackPressed(); return; }
        web.evaluateJavascript(
                "(function(){try{return window.__appBack&&window.__appBack()?1:0}catch(e){return 0}})()",
                new ValueCallback<String>() {
                    @Override public void onReceiveValue(String value) {
                        if ("1".equals(value)) return;      // Web 层已消费
                        confirmExit();
                    }
                });
    }

    private void confirmExit() {
        long now = System.currentTimeMillis();
        if (now - lastBackAt < 2000) { finish(); return; }
        lastBackAt = now;
        Toast.makeText(this, R.string.press_again_exit, Toast.LENGTH_SHORT).show();
    }

    @Override protected void onPause()   { super.onPause();   if (web != null) web.onPause(); }
    @Override protected void onResume()  { super.onResume();  if (web != null) web.onResume(); }
    @Override protected void onDestroy() {
        for (LlmClient c : llmActive.values()) c.cancel();
        llmActive.clear();
        llmPool.shutdownNow();
        if (web != null) { web.destroy(); web = null; }
        super.onDestroy();
    }
}
