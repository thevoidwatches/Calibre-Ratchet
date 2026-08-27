package io.github.thevoidwatches.ratchet;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.os.Environment;
import android.webkit.JavascriptInterface;

import org.json.JSONArray;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

/**
 * Native access for the bundled offline page (error.html), which the
 * Capacitor plugin runtime never reaches: with an external server.url,
 * Capacitor injects window.Capacitor via addDocumentStartJavaScript
 * restricted to that origin, so the locally-served error page
 * (http://localhost) gets no bridge at all. An addJavascriptInterface
 * object, by contrast, exists on every page the WebView loads — the offline
 * library talks to this instead.
 *
 * Both methods return plain strings because addJavascriptInterface only
 * carries primitives; the page parses/reads them as needed.
 */
public class OfflineBridge {

    private final Activity activity;

    public OfflineBridge(Activity activity) {
        this.activity = activity;
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
