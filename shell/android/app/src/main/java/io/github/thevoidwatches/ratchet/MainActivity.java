package io.github.thevoidwatches.ratchet;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(RatchetNativePlugin.class);
        super.onCreate(savedInstanceState);
    }
}
