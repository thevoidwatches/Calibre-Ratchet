package io.github.thevoidwatches.ratchet;

import android.app.AlertDialog;
import android.webkit.JsPromptResult;
import android.webkit.WebView;
import android.widget.EditText;

import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebChromeClient;

/**
 * Capacitor's WebView chrome, with one correction: its prompt dialog accepts
 * the page's default value and never puts it in the box.
 *
 * On the web, prompt(message, value) opens pre-filled. Capacitor's
 * BridgeWebChromeClient.onJsPrompt builds an empty EditText and ignores the
 * defaultValue argument, so every pre-filled prompt in Ratchet silently
 * arrived blank on Android — the URL suggested from the clipboard, the
 * current title when renaming a book, and the suggested name when saving a
 * filter set. All three are the cases where the default is the whole point.
 *
 * The dialog is rebuilt here rather than delegated to, because the parent
 * creates and shows its own; overriding means replacing it.
 */
public class RatchetChromeClient extends BridgeWebChromeClient {

    private final Bridge bridge;

    public RatchetChromeClient(Bridge bridge) {
        super(bridge);
        this.bridge = bridge;
    }

    @Override
    public boolean onJsPrompt(WebView view, String url, String message,
                              String defaultValue, final JsPromptResult result) {
        if (bridge.getActivity().isFinishing()) return true;

        final EditText input = new EditText(view.getContext());
        if (defaultValue != null && !defaultValue.isEmpty()) {
            input.setText(defaultValue);
            input.setSelection(input.getText().length());   // caret at the end
        }

        new AlertDialog.Builder(view.getContext())
                .setMessage(message)
                .setView(input)
                .setPositiveButton("OK", (dialog, which) -> {
                    dialog.dismiss();
                    result.confirm(input.getText().toString().trim());
                })
                .setNegativeButton("Cancel", (dialog, which) -> {
                    dialog.dismiss();
                    result.cancel();
                })
                .setOnCancelListener(dialog -> {
                    dialog.dismiss();
                    result.cancel();
                })
                .create()
                .show();
        return true;
    }
}
