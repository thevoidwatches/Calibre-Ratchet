package io.github.thevoidwatches.ratchet;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Environment;
import android.webkit.JavascriptInterface;

import org.json.JSONArray;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

/**
 * Native access for the two pages bundled into the app: the setup page
 * (index.html), shown until the app knows where its server is, and the
 * offline page (error.html), shown when that server does not answer.
 *
 * The Capacitor plugin runtime cannot serve them both. With an external
 * server.url, Capacitor injects window.Capacitor via
 * addDocumentStartJavaScript restricted to that origin, so the locally-served
 * error page (http://localhost) gets no bridge at all. An
 * addJavascriptInterface object, by contrast, exists on every page the
 * WebView loads — so both pages talk to this, and there is one way to reach
 * native code from a bundled page rather than one per page.
 *
 * Methods return plain strings because addJavascriptInterface only carries
 * primitives; the page parses/reads them as needed.
 */
public class ShellBridge {

    private static final String PREFS = "ratchet";
    private static final String KEY_SERVER = "server";
    private static final String KEY_PREVIOUS = "previous_server";

    private final Activity activity;

    public ShellBridge(Activity activity) {
        this.activity = activity;
    }

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** The server this device was pointed at, as an origin
     *  ("http://host:8484"), or null when it has not been told yet. */
    static String savedServer(Context context) {
        String value = prefs(context).getString(KEY_SERVER, null);
        return value == null || value.trim().isEmpty() ? null : value.trim();
    }

    /** The address as an origin, or null when it is not one the app could
     *  load: anything but http(s), or nothing naming a host. Only the origin
     *  is kept — the path is the app's to choose, not the address's. */
    static String originOf(String address) {
        if (address == null) return null;
        Uri uri = Uri.parse(address.trim());
        String scheme = uri.getScheme();
        String authority = uri.getEncodedAuthority();
        if (scheme == null || authority == null || authority.isEmpty()) return null;
        scheme = scheme.toLowerCase();
        if (!scheme.equals("http") && !scheme.equals("https")) return null;
        return scheme + "://" + authority;
    }

    /** The bridge reads its server once, as it is built, so a new address
     *  takes a new activity to act on. */
    private void restart() {
        activity.runOnUiThread(activity::recreate);
    }

    @JavascriptInterface
    public String getServer() {
        String server = savedServer(activity);
        return server == null ? "" : server;
    }

    /** What the server was before it was last forgotten, so that correcting
     *  a typo starts from the typo rather than from an empty box. */
    @JavascriptInterface
    public String getPreviousServer() {
        return prefs(activity).getString(KEY_PREVIOUS, "");
    }

    /** Point the app at a server and reload into it. Returns "" on success,
     *  else a message for the page to show. */
    @JavascriptInterface
    public String setServer(String address) {
        String origin = originOf(address);
        if (origin == null) return "that is not an http(s) address";
        prefs(activity).edit().putString(KEY_SERVER, origin).apply();
        restart();
        return "";
    }

    /** Back to the setup page, remembering the address being left. */
    @JavascriptInterface
    public void forgetServer() {
        String server = savedServer(activity);
        SharedPreferences.Editor edit = prefs(activity).edit().remove(KEY_SERVER);
        if (server != null) edit.putString(KEY_PREVIOUS, server);
        edit.apply();
        restart();
    }

    /** The device catalog (Ratchet/.catalog.json) as its JSON text, or null
     *  when it is absent or unreadable. */
    @JavascriptInterface
    public String readCatalog() {
        try {
            File f = new File(Environment.getExternalStorageDirectory(),
                    "Ratchet/.catalog.json");
            if (!f.isFile()) return null;
            return new String(Files.readAllBytes(f.toPath()),
                    StandardCharsets.UTF_8);
        } catch (Exception e) {
            return null;
        }
    }

    /** Open a downloaded book in the preferred reader (same package
     *  targeting as RatchetNative.openFile). Returns "" on success, else a
     *  message for the page to show. */
    @JavascriptInterface
    public String openBook(String library, String file, String packagesJson) {
        try {
            File f = new File(Environment.getExternalStorageDirectory(),
                    "Ratchet/" + library + "/" + file);
            if (!f.isFile()) return "file not found on device";
            List<String> preferred = new ArrayList<>();
            JSONArray arr = new JSONArray(packagesJson);
            for (int i = 0; i < arr.length(); i++) preferred.add(arr.getString(i));
            RatchetNativePlugin.openWithPackages(activity, f,
                    "application/epub+zip", preferred);
            return "";
        } catch (ActivityNotFoundException e) {
            return "no app can open epubs";
        } catch (Exception e) {
            return String.valueOf(e.getMessage());
        }
    }
}
