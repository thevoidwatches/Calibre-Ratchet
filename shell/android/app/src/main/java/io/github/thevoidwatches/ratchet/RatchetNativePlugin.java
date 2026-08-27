package io.github.thevoidwatches.ratchet;

import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.Settings;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * The shell's own native surface, kept deliberately tiny.
 *
 * Ratchet keeps books in a visible top-level folder (/storage/emulated/0/
 * Ratchet/<Library>/) so Moon+ and file managers can see them. Writing real
 * paths in shared storage on Android 11+ needs "All files access"
 * (MANAGE_EXTERNAL_STORAGE) — acceptable for a personal sideloaded app; a
 * Play Store app would have to use SAF instead. These two methods let the
 * served UI check for and request that grant; everything else (mkdir, write,
 * delete) goes through the stock Filesystem plugin.
 */
@CapacitorPlugin(name = "RatchetNative")
public class RatchetNativePlugin extends Plugin {

    @PluginMethod
    public void hasAllFilesAccess(PluginCall call) {
        boolean granted = Build.VERSION.SDK_INT < Build.VERSION_CODES.R
                || Environment.isExternalStorageManager();
        JSObject ret = new JSObject();
        ret.put("granted", granted);
        call.resolve(ret);
    }

    /** Open an http(s) URL in the system browser. The WebView has no download
     *  handler, so in-app navigation to the APK would go nowhere; the browser
     *  downloads it and hands off to the package installer. */
    @PluginMethod
    public void openUrl(PluginCall call) {
        String url = call.getString("url");
        if (url == null || !(url.startsWith("http://") || url.startsWith("https://"))) {
            call.reject("http(s) URLs only");
            return;
        }
        getActivity().startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        call.resolve();
    }

    @PluginMethod
    public void openAllFilesSettings(PluginCall call) {
        Intent intent;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            intent = new Intent(
                    Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                    Uri.parse("package:" + getContext().getPackageName()));
        } else {
            intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:" + getContext().getPackageName()));
        }
        getActivity().startActivity(intent);
        call.resolve();
    }
}
