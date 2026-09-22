package io.github.thevoidwatches.ratchet;

import android.graphics.Bitmap;
import android.os.Handler;
import android.os.Looper;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;

import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebViewClient;

/**
 * Capacitor's WebView client, with a limit on how long a page may take to
 * answer before the offline page is shown instead.
 *
 * Capacitor shows the offline page when a load FAILS — and a connection the
 * PC refuses fails at once. But a PC that is on with Ratchet stopped does
 * not refuse the connection: Windows Firewall's stealth mode, on by default,
 * silently drops a connection to a port with nothing listening rather than
 * answering it. The phone is then not told anything, and waits — Android
 * gives up after about two minutes — and for all of that time the WebView
 * shows a blank screen, which is indistinguishable from the app being
 * broken. (Tailscale off on the device fails instantly, the name not
 * resolving; that is why this was not seen sooner.)
 *
 * So a load gets PATIENCE_MS to show something, and then the offline page
 * is loaded in its place. That page asks /ping every twenty seconds with a
 * short timeout of its own, so it never hangs, and walks back into the app
 * by itself when Ratchet answers. And for as long as a load is being waited
 * on, a "Connecting…" sign covers the blank WebView (see ConnectingSign),
 * so that waiting looks like waiting.
 *
 * The first load of all starts inside Bridge's constructor, before the
 * activity can install this client, so the activity arms the limit for
 * that one itself (see MainActivity); every load after it — the offline
 * page's Retry included — passes through onPageStarted here.
 */
public class RatchetWebViewClient extends BridgeWebViewClient {

    /** Long enough for a slow tailnet path to bring back a small page, and
     *  short enough that nobody wonders whether the app has died. */
    static final long PATIENCE_MS = 8000;

    private final Bridge bridge;
    private final ConnectingSign sign;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private Runnable giveUp;

    public RatchetWebViewClient(Bridge bridge, ConnectingSign sign) {
        super(bridge);
        this.bridge = bridge;
        this.sign = sign;
    }

    /** Start the clock for a load of `url`; the offline page is loaded if
     *  nothing has finished or failed by the time it runs out. Loading the
     *  offline page itself is not timed — it is local, and it is the
     *  fallback. */
    void arm(WebView view, String url) {
        settled();
        String errorUrl = bridge.getErrorUrl();
        if (errorUrl == null || url == null || url.startsWith(errorUrl)) return;
        // A new load replaces the one still waiting; nothing to stop first.
        giveUp = () -> {
            giveUp = null;
            view.loadUrl(errorUrl);
        };
        handler.postDelayed(giveUp, PATIENCE_MS);
        sign.show(url);
    }

    /** The wait is over, one way or another: stop the clock and uncover
     *  whatever the WebView is showing now. */
    private void settled() {
        if (giveUp != null) handler.removeCallbacks(giveUp);
        giveUp = null;
        sign.hide();
    }

    @Override
    public void onPageStarted(WebView view, String url, Bitmap favicon) {
        super.onPageStarted(view, url, favicon);
        arm(view, url);
    }

    @Override
    public void onPageCommitVisible(WebView view, String url) {
        // The first paint: the page is on screen, whatever else is still
        // on its way. Sooner than onPageFinished, which waits for all of it.
        settled();
        super.onPageCommitVisible(view, url);
    }

    @Override
    public void onPageFinished(WebView view, String url) {
        settled();
        super.onPageFinished(view, url);
    }

    @Override
    public void onReceivedError(WebView view, WebResourceRequest request,
                                WebResourceError error) {
        // Only the page itself failing settles the matter: an image that
        // did not load says nothing about whether the page will.
        if (request.isForMainFrame()) settled();
        super.onReceivedError(view, request, error);
    }

    @Override
    public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                    WebResourceResponse errorResponse) {
        if (request.isForMainFrame()) settled();
        super.onReceivedHttpError(view, request, errorResponse);
    }
}
