package io.github.thevoidwatches.ratchet;

import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.StrictMode;
import android.provider.Settings;

import androidx.core.content.FileProvider;

import com.getcapacitor.JSArray;

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

    /** Open a local file in a specific app when one of the preferred
     *  packages is installed, falling back to Android's default resolution.
     *
     *  Exists because "default app" choices are keyed to the intent's exact
     *  shape: on Boox devices the built-in reader wins generic epub VIEW
     *  intents even when the user has picked Moon+ elsewhere. Targeting the
     *  package sidesteps resolution entirely.
     *
     *  A targeted reader is given the file's path (a file: URI); the
     *  fallback gets a content: URI from the app's FileProvider, the
     *  sanctioned form. The targeted readers are Moon+, and Moon+ imports
     *  whatever reaches it as a content: URI — the FileProvider's, and
     *  MediaStore's too, which was tried — into Download/, then reads the
     *  copy and keeps its place in that. Given a path it opens the file
     *  where it lies, as from its own browser. Android 7 began refusing
     *  file: URIs in intents, but the refusal is a StrictMode check in the
     *  sending process (see startAllowingFileUri), and Moon+ reads shared
     *  storage under its own grant.
     *
     *  Shared with ShellBridge, which opens books from the bundled offline
     *  page where the Capacitor plugin runtime is unavailable.
     */
    static String openWithPackages(android.app.Activity activity, java.io.File file,
                                   String contentType, java.util.List<String> preferred) {
        Intent byPath = new Intent(Intent.ACTION_VIEW);
        byPath.setDataAndType(Uri.fromFile(file), contentType);
        byPath.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        for (String pkg : preferred) {
            try {
                byPath.setPackage(pkg);
                startAllowingFileUri(activity, byPath);
                return pkg;
            } catch (ActivityNotFoundException e) {
                // not installed (or not visible) — try the next preference
            }
        }
        Uri shared = FileProvider.getUriForFile(activity,
                activity.getPackageName() + ".fileprovider", file);
        Intent byContent = new Intent(Intent.ACTION_VIEW);
        byContent.setDataAndType(shared, contentType);
        byContent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_ACTIVITY_NEW_TASK);
        activity.startActivity(byContent);   // ActivityNotFoundException if none
        return "default";
    }

    /** startActivity with the file: URI check suspended for the call.
     *
     *  FileUriExposedException is raised by this process's own StrictMode
     *  policy, which is process-wide; so the check is lifted for the one
     *  call and the policy put back as it was. The receiving app still needs
     *  its own right to read the path — the readers this is used for have
     *  all-files access.
     */
    private static void startAllowingFileUri(android.app.Activity activity, Intent intent) {
        StrictMode.VmPolicy was = StrictMode.getVmPolicy();
        StrictMode.setVmPolicy(new StrictMode.VmPolicy.Builder().build());
        try {
            activity.startActivity(intent);
        } finally {
            StrictMode.setVmPolicy(was);
        }
    }

    @PluginMethod
    public void openFile(PluginCall call) {
        String path = call.getString("path");
        String contentType = call.getString("contentType", "application/epub+zip");
        if (path == null) { call.reject("path is required"); return; }

        java.io.File file = new java.io.File(path);
        if (!file.exists()) { call.reject("file not found: " + path); return; }

        java.util.List<String> preferred = new java.util.ArrayList<>();
        JSArray packages = call.getArray("packages", new JSArray());
        for (int i = 0; i < packages.length(); i++) {
            try {
                preferred.add(packages.getString(i));
            } catch (org.json.JSONException e) {
                break;
            }
        }
        try {
            String openedWith = openWithPackages(getActivity(), file,
                    contentType, preferred);
            JSObject ret = new JSObject();
            ret.put("openedWith", openedWith);
            call.resolve(ret);
        } catch (ActivityNotFoundException e) {
            call.reject("no app can open " + contentType);
        }
    }

    /** Text shared into Ratchet since the last call, or "" — collected once
     *  and cleared, so returning to the app later does not re-add a story. */
    @PluginMethod
    public void consumeSharedText(PluginCall call) {
        JSObject ret = new JSObject();
        ret.put("text", MainActivity.pendingSharedText == null
                ? "" : MainActivity.pendingSharedText);
        MainActivity.pendingSharedText = null;
        call.resolve(ret);
    }

    /** The clipboard's text, for pre-filling the add-by-URL prompt.
     *
     *  Native rather than navigator.clipboard: that API needs a secure
     *  context, and Ratchet is served over plain http on the tailnet. Reading
     *  is allowed here because the activity is in the foreground.
     */
    @PluginMethod
    public void readClipboard(PluginCall call) {
        String text = "";
        try {
            android.content.ClipboardManager cb = (android.content.ClipboardManager)
                    getContext().getSystemService(android.content.Context.CLIPBOARD_SERVICE);
            if (cb != null && cb.hasPrimaryClip() && cb.getPrimaryClip() != null
                    && cb.getPrimaryClip().getItemCount() > 0) {
                CharSequence cs = cb.getPrimaryClip().getItemAt(0)
                        .coerceToText(getContext());
                if (cs != null) text = cs.toString().trim();
            }
        } catch (Exception e) {
            text = "";      // a clipboard we cannot read is not an error here
        }
        JSObject ret = new JSObject();
        ret.put("text", text);
        call.resolve(ret);
    }

    /** When this build was installed, so the UI can tell whether the APK on
     *  the server is newer without either side tracking version numbers. */
    @PluginMethod
    public void appInfo(PluginCall call) {
        JSObject ret = new JSObject();
        try {
            android.content.pm.PackageInfo info = getContext().getPackageManager()
                    .getPackageInfo(getContext().getPackageName(), 0);
            ret.put("installedAt", info.lastUpdateTime);
            ret.put("versionName", info.versionName);
        } catch (Exception e) {
            ret.put("installedAt", 0);
        }
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
