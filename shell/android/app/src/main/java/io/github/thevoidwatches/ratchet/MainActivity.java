package io.github.thevoidwatches.ratchet;

import android.content.Intent;
import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    /** Text shared into Ratchet, waiting for the web app to collect it.
     *
     *  Static because a share can arrive before the WebView has loaded (cold
     *  start) or while it is already running (onNewIntent); either way the
     *  page asks for it once it is ready, via RatchetNative.consumeSharedText.
     */
    static String pendingSharedText = null;

    private static void remember(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) return;
        String text = intent.getStringExtra(Intent.EXTRA_TEXT);
        if (text != null && !text.trim().isEmpty()) pendingSharedText = text.trim();
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(RatchetNativePlugin.class);
        remember(getIntent());
        super.onCreate(savedInstanceState);
        // For the bundled offline page, which Capacitor's injected runtime
        // does not reach (see OfflineBridge). Attached to the WebView itself,
        // so it exists on every page regardless of origin.
        if (getBridge() != null) {
            getBridge().getWebView().addJavascriptInterface(
                    new OfflineBridge(this), "RatchetOffline");
        }
    }

    @Override
    public void onNewIntent(Intent intent) {
        remember(intent);
        super.onNewIntent(intent);
    }
}
