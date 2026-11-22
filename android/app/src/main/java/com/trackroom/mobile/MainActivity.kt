package com.trackroom.mobile

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.Toast
import org.json.JSONObject

/** Prototype Android shell for an already deployed TRACKROOM website.
 *  Only verified user-selected navigation from the trusted site's main frame
 *  is allowed to call the native streaming hand-off.
 */
class MainActivity : Activity() {
    private val prefs by lazy { getSharedPreferences("trackroom_android", MODE_PRIVATE) }
    private lateinit var webView: WebView
    private lateinit var spotify: SpotifyConnector
    private lateinit var mediaSessions: ExternalMediaSessions
    private var trustedOrigin = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        spotify = SpotifyConnector(this, prefs) { ok, message -> notifySite(ok, message) }
        mediaSessions = ExternalMediaSessions(this) { snapshot -> sendMediaSnapshot(snapshot) }
        val url = prefs.getString("trackroom_url", "").orEmpty()
        if (url.isEmpty()) showSiteSetup() else openSite(url)
    }

    private fun showSiteSetup() {
        val input = EditText(this).apply {
            setText(prefs.getString("trackroom_url", "") ?: "")
            hint = "https://your-trackroom.onrender.com"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(true)
        }
        AlertDialog.Builder(this)
            .setTitle("TRACKROOM 웹사이트 연결")
            .setMessage("기존 TRACKROOM이 실제 배포된 HTTPS 주소를 입력해 줘. 이 주소만 앱 안에서 열려.")
            .setView(input)
            .setCancelable(false)
            .setPositiveButton("연결") { _, _ ->
                val value = input.text.toString().trim().trimEnd('/')
                if (!isTrustedSiteUrl(value)) {
                    Toast.makeText(this, "HTTPS 주소를 확인해 줘.", Toast.LENGTH_LONG).show()
                    showSiteSetup()
                } else {
                    prefs.edit().putString("trackroom_url", value).apply()
                    openSite(value)
                }
            }
            .setNegativeButton("종료") { _, _ -> finish() }
            .show()
    }

    private fun isTrustedSiteUrl(url: String): Boolean {
        val parsed = Uri.parse(url)
        return parsed.scheme == "https" && !parsed.host.isNullOrBlank() &&
            !parsed.authority.orEmpty().contains("@")
    }

    // Don't allow free-form origin changes by redirects. Any third party links open externally.
    private fun openSite(url: String) {
        val uri = Uri.parse(url)
        trustedOrigin = "https://${uri.host}${if (uri.port > 0 && uri.port != 443) ":${uri.port}" else ""}"
        webView = WebView(this)
        webView.setBackgroundColor(android.graphics.Color.rgb(253, 251, 255))
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            userAgentString += " TRACKROOMAndroid/0.1"
        }
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false)
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val target = request?.url ?: return true
                if (target.scheme == "trackroom-native" && target.host in listOf("play", "media")) {
                    // Only an explicit top-level navigation from our configured HTTPS origin.
                    if (request.isForMainFrame && isTrustedOrigin(view?.url)) {
                        if (target.host == "play") nativePlayback(target)
                        else nativeMediaCommand(target)
                    }
                    return true
                }
                if (target.scheme == "https" && isTrustedOrigin(target.toString())) return false
                if (request.isForMainFrame) openExternal(target)
                return true
            }
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                if (isTrustedOrigin(url)) mediaSessions.refreshSessions()
            }
        }
        setContentView(FrameLayout(this).apply { addView(webView,
            FrameLayout.LayoutParams(-1,-1)) })
        webView.loadUrl(url)
    }

    private fun isTrustedOrigin(value: String?): Boolean {
        if (value.isNullOrBlank()) return false
        val u = Uri.parse(value)
        val origin = "${u.scheme}://${u.host}${if (u.port > 0 && u.port != 443) ":${u.port}" else ""}"
        return origin == trustedOrigin
    }

    private fun nativePlayback(uri: Uri) {
        val title = uri.getQueryParameter("title")?.take(160).orEmpty().trim()
        val artist = uri.getQueryParameter("artist")?.take(160).orEmpty().trim()
        val provider = uri.getQueryParameter("provider").orEmpty()
        val musicUrl = uri.getQueryParameter("musicUrl")?.take(900).orEmpty()
        if (title.isBlank() || artist.isBlank()) return notifySite(false, "곡 정보가 부족해.")
        val track = StreamTrack(title, artist, musicUrl)
        mediaSessions.selectProvider(provider)
        if (provider == "spotify") {
            spotify.play(track)
        } else {
            // May be rejected or ignored by the external app. Never claim playback succeeded.
            val supportsSearch = mediaSessions.hasAccess() &&
                mediaSessions.snapshot().optBoolean("connected") &&
                mediaSessions.snapshot().optBoolean("canPlayFromSearch")
            if (supportsSearch) {
                mediaSessions.command("playFromSearch", searchQuery = "$title $artist").let { notifySite(it.sent, it.message) }
            } else launchSupportedService(provider, track)
        }
    }

    private fun nativeMediaCommand(uri: Uri) {
        val action = uri.getQueryParameter("action").orEmpty()
        val requested = uri.getQueryParameter("provider").orEmpty()
        if (requested in ExternalMediaSessions.PACKAGES) mediaSessions.selectProvider(requested)
        when (action) {
            "permission" -> requestNotificationAccess()
            "sync", "select" -> mediaSessions.refreshSessions()
            "play", "pause", "next", "previous", "seek", "playFromSearch" -> {
                val toMs = uri.getQueryParameter("toMs")?.toLongOrNull() ?: 0L
                val title = uri.getQueryParameter("title")?.take(160).orEmpty().trim()
                val artist = uri.getQueryParameter("artist")?.take(160).orEmpty().trim()
                val query = listOf(title, artist).filter { it.isNotBlank() }.joinToString(" ")
                val result = mediaSessions.command(action, toMs, query)
                notifySite(result.sent, result.message)
            }
            else -> notifySite(false, "알 수 없는 재생 명령이야.")
        }
    }

    private fun requestNotificationAccess() {
        if (mediaSessions.hasAccess()) {
            mediaSessions.refreshSessions()
            return notifySite(true, "알림 접근 권한이 이미 허용되어 있어.")
        }
        AlertDialog.Builder(this)
            .setTitle("음악 재생 상태 연결")
            .setMessage("Android의 '알림 접근' 권한이 필요해. 이 권한은 다른 앱의 알림에 접근할 수 있는 넓은 권한이지만, TRACKROOM은 지원 음악 앱의 미디어 세션(곡 제목·아티스트·재생 상태)만 사용하고 다른 알림 내용은 읽거나 저장하지 않아. TRACKROOM에만 권한을 허용할지 직접 선택해 줘.")
            .setPositiveButton("Android 설정 열기") { _, _ ->
                tryStart(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            }
            .setNegativeButton("취소", null)
            .show()
    }

    private fun sendMediaSnapshot(snapshot: JSONObject) {
        runOnUiThread {
            if (!::webView.isInitialized || !isTrustedOrigin(webView.url)) return@runOnUiThread
            webView.evaluateJavascript(
                "window.dispatchEvent(new CustomEvent('trackroom:media-session', {detail:${snapshot}}));", null
            )
        }
    }

    private fun launchSupportedService(provider: String, track: StreamTrack) {
        val packages = mapOf(
            "melon" to "com.iloen.melon", "genie" to "com.ktmusic.geniemusic",
            "flo" to "skplanet.musicmate", "bugs" to "com.neowiz.android.bugs",
            "youtube" to "com.google.android.apps.youtube.music"
        )
        val appPackage = packages[provider] ?: return notifySite(false, "지원하지 않는 스트리밍 서비스야.")
        val direct = providerSpecificHttpsUrl(provider, track.musicUrl)
        if (direct != null) {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(direct)).apply { addCategory(Intent.CATEGORY_BROWSABLE) }
            if (tryStart(intent)) {
                notifySite(true, "곡 페이지를 열었어. 실제 재생 시작은 해당 스트리밍 앱에서 확인해 줘.")
                return
            }
        }
        // Never fabricate a cross-service ID or claim automated playback works.
        // Open the actual installed service and put the search phrase on the clipboard.
        val launch = packageManager.getLaunchIntentForPackage(appPackage)
        if (launch != null && tryStart(launch)) {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("TRACKROOM 곡 검색", "${track.title} ${track.artist}"))
            notifySite(true, "앱을 열고 곡 제목을 복사했어. 검색창에 붙여넣어 재생해 줘. 자동 재생 연동은 아직 지원되지 않아.")
            return
        }
        val store = Uri.parse("https://play.google.com/store/apps/details?id=${Uri.encode(appPackage)}")
        openExternal(store)
        notifySite(false, "앱이 설치되어 있지 않아 스토어를 열었어.")
    }

    private fun providerSpecificHttpsUrl(provider: String, url: String): String? {
        if (url.isBlank()) return null
        val u = Uri.parse(url)
        if (u.scheme != "https" || u.host.isNullOrBlank()) return null
        val host = u.host!!.lowercase()
        val accepted = when (provider) {
            "melon" -> host == "melon.com" || host.endsWith(".melon.com")
            "genie" -> host == "genie.co.kr" || host.endsWith(".genie.co.kr")
            "flo" -> host == "music-flo.com" || host.endsWith(".music-flo.com")
            "bugs" -> host == "bugs.co.kr" || host.endsWith(".bugs.co.kr")
            "youtube" -> host == "music.youtube.com"
            else -> false
        }
        return if (accepted) url else null
    }

    fun promptSpotifyClientId(onProvided: (String) -> Unit) {
        val edit = EditText(this).apply {
            hint = "Spotify Developer Client ID"
            setSingleLine(true)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        }
        AlertDialog.Builder(this)
            .setTitle("Spotify 개발용 앱 연결")
            .setMessage("Spotify Developer 대시보드에서 생성한 Client ID를 입력해 줘. Client Secret은 입력하지 않아.")
            .setView(edit)
            .setPositiveButton("저장하고 연결") { _, _ ->
                val id = edit.text.toString().trim()
                if (id.matches(Regex("[A-Za-z0-9]{16,64}"))) {
                    prefs.edit().putString("spotify_client_id",id).apply()
                    onProvided(id)
                } else notifySite(false,"Client ID 형식을 확인해 줘.")
            }
            .setNegativeButton("취소", null)
            .show()
    }

    fun chooseSpotifyTrack(labels: Array<String>, onChoice: (Int) -> Unit) {
        AlertDialog.Builder(this)
            .setTitle("Spotify에서 재생할 곡 선택")
            .setMessage("동명이곡·리마스터·라이브 버전이 있을 수 있어. 정확한 음원을 선택해 줘.")
            .setItems(labels) { _, which -> onChoice(which) }
            .setNegativeButton("취소", null)
            .show()
    }

    fun openExternal(uri: Uri) { tryStart(Intent(Intent.ACTION_VIEW,uri).addCategory(Intent.CATEGORY_BROWSABLE)) }
    fun tryStart(intent: Intent): Boolean = try { startActivity(intent); true } catch (_:Exception) { false }
    fun notifySite(ok: Boolean, message: String) {
        runOnUiThread {
            Toast.makeText(this, message, Toast.LENGTH_LONG).show()
            if (::webView.isInitialized) {
                val details = JSONObject().put("ok",ok).put("message",message)
                webView.evaluateJavascript(
                    "window.dispatchEvent(new CustomEvent('trackroom:native-result', {detail:${details}}));", null
                )
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (::webView.isInitialized && webView.canGoBack()) webView.goBack()
        else super.onBackPressed()
    }
    override fun onResume() {
        super.onResume()
        if (::mediaSessions.isInitialized) mediaSessions.start()
    }

    override fun onPause() {
        if (::mediaSessions.isInitialized) mediaSessions.stop()
        super.onPause()
    }

    override fun onDestroy() {
        if (::mediaSessions.isInitialized) mediaSessions.stop()
        if (::webView.isInitialized) webView.destroy()
        spotify.close()
        super.onDestroy()
    }
}

data class StreamTrack(val title: String, val artist: String, val musicUrl: String)
