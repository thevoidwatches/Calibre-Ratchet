package io.github.thevoidwatches.ratchet;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(RatchetNativePlugin.class);
        super.onCreate(savedInstanceState);
        // For the bundled offline page, which Capacitor's injected runtime
        // does not reach (see OfflineBridge). Attached to the WebView itself,
        // so it exists on every page regardless of origin.
        if (getBridge() != null) {
            getBridge().getWebView().addJavascriptInterface(
                    new OfflineBridge(this), "RatchetOffline");
        }
    }
}
