package io.github.thevoidwatches.ratchet;

import android.app.Activity;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * What the screen shows while a page is being waited for.
 *
 * Between asking for the served UI and hearing anything back, the WebView
 * shows nothing — and with the PC on but Ratchet stopped that nothing lasts
 * the full wait before the offline page (see RatchetWebViewClient), which
 * looks exactly like the app having died. So a sign is laid over the WebView
 * for as long as a load is being waited on, and taken away the moment the
 * page paints anything, or the offline page takes over.
 *
 * Built in code rather than as a layout resource, since it is two lines of
 * text and building it here keeps everything about it in one place. Black
 * on white or white on black to match the system's setting, like the rest
 * of Ratchet; the served UI keeps its own choice in its own storage, which
 * the app cannot read before the UI has loaded.
 */
class ConnectingSign {

    private final FrameLayout cover;
    private final TextView where;

    ConnectingSign(Activity activity) {
        boolean dark = (activity.getResources().getConfiguration().uiMode
                & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
        int fg = dark ? Color.WHITE : Color.BLACK;
        int bg = dark ? Color.BLACK : Color.WHITE;

        TextView what = new TextView(activity);
        what.setText("Connecting…");
        what.setTextColor(fg);
        what.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        what.setTypeface(Typeface.DEFAULT_BOLD);
        what.setGravity(Gravity.CENTER_HORIZONTAL);

        where = new TextView(activity);
        where.setTextColor(dark ? Color.LTGRAY : Color.DKGRAY);
        where.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        where.setGravity(Gravity.CENTER_HORIZONTAL);
        where.setPadding(0, dp(activity, 8), 0, 0);

        LinearLayout column = new LinearLayout(activity);
        column.setOrientation(LinearLayout.VERTICAL);
        column.setGravity(Gravity.CENTER);
        int pad = dp(activity, 24);
        column.setPadding(pad, pad, pad, pad);
        column.addView(what);
        column.addView(where);

        cover = new FrameLayout(activity);
        cover.setBackgroundColor(bg);
        // Absorbs touches: there is nothing to reach underneath yet, and a
        // tap that fell through to a half-loaded page would be a surprise.
        cover.setClickable(true);
        cover.addView(column, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        cover.setVisibility(View.GONE);
        activity.addContentView(cover, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
    }

    /** Show it, naming the machine being waited on — the one thing worth
     *  knowing while waiting, since a wrong name looks the same as a PC
     *  that is off. */
    void show(String url) {
        String host = url == null ? null : Uri.parse(url).getHost();
        where.setText(host == null || host.isEmpty() ? "" : host);
        where.setVisibility(where.getText().length() == 0 ? View.GONE : View.VISIBLE);
        cover.setVisibility(View.VISIBLE);
    }

    void hide() {
        cover.setVisibility(View.GONE);
    }

    private static int dp(Activity activity, int dp) {
        return Math.round(dp * activity.getResources().getDisplayMetrics().density);
    }
}
