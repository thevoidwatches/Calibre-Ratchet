package io.github.thevoidwatches.ratchet;

import android.content.Intent;
import android.os.Bundle;

import androidx.activity.OnBackPressedCallback;

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
            // Installed after the bridge has set its own: ours only corrects
            // prompt(), inheriting the rest (file chooser, permissions).
            getBridge().getWebView().setWebChromeClient(
                    new RatchetChromeClient(getBridge()));
        }
        handOverBackButton();
    }

    /** Send the back button to the page before letting it close the app.
     *
     *  Capacitor 8 registers nothing for the back button, so without this the
     *  press reaches the activity and finishes it -- from any screen, however
     *  deep. The web app keeps its own history, so the WebView knows whether
     *  there is somewhere to go back to; only when there is not does this fall
     *  through to the default, which closes Ratchet as it should from the
     *  book list.
     */
    private void handOverBackButton() {
        if (getBridge() == null) return;
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (getBridge() != null && getBridge().getWebView().canGoBack()) {
                    getBridge().getWebView().goBack();
                    return;
                }
                // Nothing left in the page's history: step aside and let the
                // activity's own handling finish the app.
                setEnabled(false);
                getOnBackPressedDispatcher().onBackPressed();
                setEnabled(true);
            }
        });
    }

    @Override
    public void onNewIntent(Intent intent) {
        remember(intent);
        super.onNewIntent(intent);
    }
}
