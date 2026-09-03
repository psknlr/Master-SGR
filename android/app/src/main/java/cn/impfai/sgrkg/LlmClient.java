package cn.impfai.sgrkg;

/*
 * Poe / MiniMax 流式对话客户端（纯 Java，不依赖 Android 类，便于桌面单元测试）
 * Streaming chat client for Poe and MiniMax — plain Java, no Android imports.
 *
 * 研发：孙光荣大师弟子田建辉团队 联合 医哲未来人工智能研究院 (IMPF-AI Institute)
 *
 * 为什么放在原生层而不是让 WebView 直接 fetch：
 *   1. 免去跨域（CORS）问题——两家接口并不保证给浏览器返回 CORS 头；
 *   2. WebView 层继续保持「只能读 APK 内置资源」的沙箱，外联只从这一个口子出去；
 *   3. 主机白名单在这里硬编码，应用只可能访问用户所选的这两家 AI 服务。
 */

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.Charset;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

public final class LlmClient {

    public interface Listener {
        void onChunk(String text);
        void onDone();
        void onError(String message);
    }

    /** 允许外联的主机。任何其它地址一律拒绝，保证应用不会跟别的服务器说话。 */
    public static final Set<String> ALLOWED_HOSTS = new HashSet<String>(Arrays.asList(
            "api.poe.com", "api.minimax.chat", "api.minimaxi.chat"));

    public static final String POE_BASE = "https://api.poe.com/v1";
    public static final String MINIMAX_CN = "https://api.minimax.chat/v1";
    public static final String MINIMAX_INTL = "https://api.minimaxi.chat/v1";

    private static final Charset UTF8 = Charset.forName("UTF-8");
    private static final int CONNECT_TIMEOUT = 20000;
    private static final int READ_TIMEOUT = 150000;

    private volatile HttpURLConnection conn;
    private volatile boolean cancelled;

    /* ------------------------------------------------------------------ */
    /* 请求装配                                                             */
    /* ------------------------------------------------------------------ */

    static boolean isPoe(String provider) {
        return provider != null && provider.toLowerCase().startsWith("poe");
    }

    static String chatUrl(String provider, String baseUrl, String groupId) {
        String base = (baseUrl == null || baseUrl.trim().isEmpty())
                ? (isPoe(provider) ? POE_BASE : MINIMAX_CN) : baseUrl.trim();
        while (base.endsWith("/")) base = base.substring(0, base.length() - 1);
        if (isPoe(provider)) return base + "/chat/completions";
        String u = base + "/text/chatcompletion_v2";
        if (groupId != null && !groupId.trim().isEmpty()) u += "?GroupId=" + groupId.trim();
        return u;
    }

    static String buildBody(String provider, String model, JSONArray messages,
                            double temperature, int maxTokens) throws JSONException {
        JSONObject body = new JSONObject();
        body.put("model", model);
        body.put("messages", messages);
        body.put("stream", true);
        // MiniMax 不接受 0 温度
        body.put("temperature", isPoe(provider) ? temperature : Math.max(0.01, temperature));
        body.put("max_tokens", maxTokens);
        return body.toString();
    }

    static void checkHost(String url) throws IOException {
        String host;
        try { host = new URL(url).getHost(); } catch (Exception e) { throw new IOException("地址无效：" + url); }
        if (host == null || !ALLOWED_HOSTS.contains(host.toLowerCase())) {
            throw new IOException("出于安全考虑，应用只允许访问 Poe / MiniMax 官方接口，已拒绝：" + host);
        }
    }

    /* ------------------------------------------------------------------ */
    /* 流式分片解析（两家格式都是 SSE + choices[].delta.content）            */
    /* ------------------------------------------------------------------ */

    /**
     * 从一条 SSE 负载里取出增量文本。返回 null 表示这一片没有文本。
     * @param streamed 是否已经收到过增量；MiniMax 最后一片会把全文重复放进 message.content，
     *                 只有在此前什么都没收到时才用它（非流式兜底）。
     * @throws IOException 服务端在负载里报错（Poe 的 error / MiniMax 的 base_resp）
     */
    static String extractDelta(String provider, String payload, boolean streamed) throws IOException {
        JSONObject o;
        try { o = new JSONObject(payload); } catch (JSONException e) { return null; }

        if (!isPoe(provider)) {
            JSONObject br = o.optJSONObject("base_resp");
            if (br != null && br.optInt("status_code", 0) != 0) {
                throw new IOException("MiniMax 错误 " + br.optInt("status_code") + "：" + br.optString("status_msg"));
            }
        } else if (o.has("error")) {
            Object err = o.opt("error");
            String msg = err instanceof JSONObject ? ((JSONObject) err).optString("message", err.toString()) : String.valueOf(err);
            throw new IOException("Poe 错误：" + msg);
        }

        JSONArray choices = o.optJSONArray("choices");
        if (choices == null) return null;
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < choices.length(); i++) {
            JSONObject ch = choices.optJSONObject(i);
            if (ch == null) continue;
            JSONObject delta = ch.optJSONObject("delta");
            String piece = delta != null ? delta.optString("content", "") : "";
            if (!piece.isEmpty()) { sb.append(piece); continue; }
            if (!streamed) {
                JSONObject msg = ch.optJSONObject("message");
                if (msg != null) {
                    String full = msg.optString("content", "");
                    if (!full.isEmpty()) sb.append(full);
                }
            }
        }
        return sb.length() > 0 ? sb.toString() : null;
    }

    /* ------------------------------------------------------------------ */
    /* 发起对话（阻塞；请在工作线程调用）                                   */
    /* ------------------------------------------------------------------ */

    /**
     * cfg 字段：provider, baseUrl, groupId, apiKey, model, temperature, maxTokens, messages[]
     */
    public void streamChat(JSONObject cfg, Listener l) {
        String provider = cfg.optString("provider", "minimax");
        String apiKey = cfg.optString("apiKey", "").trim();
        if (apiKey.isEmpty()) {
            l.onError(isPoe(provider)
                    ? "未配置 Poe API Key（在 https://poe.com/api_key 获取）"
                    : "未配置 MiniMax API Key（在 MiniMax 开放平台「账户管理 - 接口密钥」获取）");
            return;
        }
        HttpURLConnection c = null;
        try {
            String url = chatUrl(provider, cfg.optString("baseUrl", ""), cfg.optString("groupId", ""));
            checkHost(url);
            String body = buildBody(provider, cfg.optString("model", ""),
                    cfg.optJSONArray("messages") == null ? new JSONArray() : cfg.optJSONArray("messages"),
                    cfg.optDouble("temperature", 0.3), cfg.optInt("maxTokens", 2048));

            c = (HttpURLConnection) new URL(url).openConnection();
            conn = c;
            c.setConnectTimeout(CONNECT_TIMEOUT);
            c.setReadTimeout(READ_TIMEOUT);
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setRequestProperty("Authorization", "Bearer " + apiKey);
            c.setRequestProperty("Content-Type", "application/json");
            c.setRequestProperty("Accept", "text/event-stream");
            byte[] bytes = body.getBytes(UTF8);
            c.setFixedLengthStreamingMode(bytes.length);
            OutputStream os = c.getOutputStream();
            os.write(bytes);
            os.flush();
            os.close();

            int status = c.getResponseCode();
            if (status >= 400) {
                String err = readAll(c.getErrorStream());
                l.onError((isPoe(provider) ? "Poe" : "MiniMax") + " 返回 " + status + "：" + trim(err, 400));
                return;
            }

            BufferedReader br = new BufferedReader(new InputStreamReader(c.getInputStream(), UTF8));
            String line;
            boolean streamed = false;
            StringBuilder raw = new StringBuilder();   // 非 SSE 行（MiniMax 鉴权失败时 200 + 纯 JSON）
            while (!cancelled && (line = br.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty()) continue;
                if (!line.startsWith("data:")) { if (raw.length() < 20000) raw.append(line); continue; }
                String payload = line.substring(5).trim();
                if (payload.isEmpty() || "[DONE]".equals(payload)) continue;
                String piece = extractDelta(provider, payload, streamed);
                if (piece != null) { streamed = true; l.onChunk(piece); }
            }
            if (cancelled) return;
            if (!streamed && raw.length() > 0) {
                // 整个响应不是 SSE：要么是错误对象，要么是非流式的完整回答
                String piece = extractDelta(provider, raw.toString(), false);   // 有错会抛
                if (piece != null) { streamed = true; l.onChunk(piece); }
            }
            if (!streamed) { l.onError("模型未返回内容（请检查模型名是否正确、账户是否有余额）"); return; }
            l.onDone();
        } catch (IOException e) {
            if (!cancelled) l.onError(friendly(e));
        } catch (JSONException e) {
            l.onError("请求装配失败：" + e.getMessage());
        } finally {
            if (c != null) c.disconnect();
            conn = null;
        }
    }

    public void cancel() {
        cancelled = true;
        HttpURLConnection c = conn;
        if (c != null) {
            try { c.disconnect(); } catch (Exception ignored) { }
        }
    }

    /* ------------------------------------------------------------------ */
    /* 简单 GET（用于读取 Poe 公开模型目录）                                  */
    /* ------------------------------------------------------------------ */

    /** 返回 {statusCode, body}；网络异常时 status = -1，body 为错误说明。 */
    public static String[] httpGet(String url) {
        HttpURLConnection c = null;
        try {
            checkHost(url);
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(CONNECT_TIMEOUT);
            c.setReadTimeout(30000);
            c.setRequestMethod("GET");
            int status = c.getResponseCode();
            InputStream in = status >= 400 ? c.getErrorStream() : c.getInputStream();
            return new String[]{String.valueOf(status), readAll(in)};
        } catch (IOException e) {
            return new String[]{"-1", friendly(e)};
        } finally {
            if (c != null) c.disconnect();
        }
    }

    /* ------------------------------------------------------------------ */

    private static String readAll(InputStream in) throws IOException {
        if (in == null) return "";
        BufferedReader br = new BufferedReader(new InputStreamReader(in, UTF8));
        StringBuilder sb = new StringBuilder();
        char[] buf = new char[4096];
        int n;
        while ((n = br.read(buf)) > 0) sb.append(buf, 0, n);
        return sb.toString();
    }

    private static String trim(String s, int max) {
        if (s == null) return "";
        s = s.replace('\n', ' ').trim();
        return s.length() > max ? s.substring(0, max) + "…" : s;
    }

    private static String friendly(IOException e) {
        String m = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
        if (e instanceof java.net.UnknownHostException) return "无法解析服务器地址，请检查网络：" + m;
        if (e instanceof java.net.SocketTimeoutException) return "连接超时，请稍后重试";
        if (e instanceof javax.net.ssl.SSLException) return "安全连接失败：" + m;
        return m;
    }
}
