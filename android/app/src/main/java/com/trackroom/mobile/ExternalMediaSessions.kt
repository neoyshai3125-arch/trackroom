package com.trackroom.mobile

import android.content.ComponentName
import android.content.Context
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import org.json.JSONObject

/** Reads ONLY media-session metadata exposed by user-approved music apps.
 *  No notification bodies, credentials, audio data or media artwork are collected.
 *  No background network communication occurs here.
 */
data class MediaCommandResult(val sent: Boolean, val message: String)

class ExternalMediaSessions(
    private val context: Context,
    private val publishToSite: (JSONObject) -> Unit
) {
    private val manager = context.getSystemService(Context.MEDIA_SESSION_SERVICE) as MediaSessionManager
    private val mainHandler = Handler(Looper.getMainLooper())
    private val listenerComponent = ComponentName(context, TrackroomNotificationListener::class.java)
    private var started = false
    private var callbackRegistered = false
    private var activeController: MediaController? = null
    private var provider = "melon"
    private var latestState: JSONObject = JSONObject()

    companion object {
        // Exact package allowlist: unrelated notification/media information stays private.
        val PACKAGES = mapOf(
            "melon" to "com.iloen.melon",
            "genie" to "com.ktmusic.geniemusic",
            "flo" to "skplanet.musicmate",
            "bugs" to "com.neowiz.android.bugs",
            "youtube" to "com.google.android.apps.youtube.music",
            "spotify" to "com.spotify.music"
        )
        val LABELS = mapOf(
            "melon" to "멜론", "genie" to "지니뮤직", "flo" to "FLO",
            "bugs" to "벅스", "youtube" to "YouTube Music", "spotify" to "Spotify"
        )
    }

    /** Notification access is a Settings toggle, NOT a regular runtime permission. */
    fun hasAccess(): Boolean {
        val enabled = Settings.Secure.getString(
            context.contentResolver, "enabled_notification_listeners"
        ).orEmpty()
        return enabled.split(':').any { item ->
            ComponentName.unflattenFromString(item) == listenerComponent
        }
    }

    private val sessionListener = MediaSessionManager.OnActiveSessionsChangedListener {
        refreshSessions()
    }
    private val mediaCallback = object : MediaController.Callback() {
        override fun onMetadataChanged(metadata: MediaMetadata?) = publish()
        override fun onPlaybackStateChanged(state: PlaybackState?) = publish()
        override fun onSessionDestroyed() = refreshSessions()
    }
    private val ticker = object : Runnable {
        override fun run() {
            if (!started) return
            publish()
            mainHandler.postDelayed(this, 1000L)
        }
    }

    fun start() {
        if (started) return
        started = true
        refreshSessions()
        mainHandler.removeCallbacks(ticker)
        mainHandler.postDelayed(ticker, 1000L)
    }

    fun stop() {
        started = false
        mainHandler.removeCallbacks(ticker)
        if (callbackRegistered) {
            try { manager.removeOnActiveSessionsChangedListener(sessionListener) }
            catch (_: Exception) { /* Android listener may have been revoked */ }
            callbackRegistered = false
        }
        replaceController(null)
    }

    fun selectProvider(id: String) {
        if (PACKAGES.containsKey(id) && provider != id) {
            provider = id
            refreshSessions()
        } else publish()
    }

    fun currentProvider(): String = provider
    fun snapshot(): JSONObject = latestState

    fun refreshSessions() {
        if (!hasAccess()) {
            if (callbackRegistered) {
                try { manager.removeOnActiveSessionsChangedListener(sessionListener) }
                catch (_: Exception) { }
                callbackRegistered = false
            }
            replaceController(null)
            publish()
            return
        }
        if (started && !callbackRegistered) {
            try {
                manager.addOnActiveSessionsChangedListener(sessionListener, listenerComponent, mainHandler)
                callbackRegistered = true
            } catch (_: SecurityException) { /* Permission or service is not yet ready */ }
              catch (_: Exception) { }
        }
        val controllers = try { manager.getActiveSessions(listenerComponent) }
            catch (_: SecurityException) { emptyList() }
            catch (_: Exception) { emptyList() }
        val expectedPackage = PACKAGES[provider]
        val chosen = controllers.filter { it.packageName == expectedPackage }
            .sortedByDescending { it.playbackState?.state == PlaybackState.STATE_PLAYING }
            .firstOrNull()
        replaceController(chosen)
        publish()
    }

    private fun replaceController(next: MediaController?) {
        val previous = activeController
        if (previous?.sessionToken == next?.sessionToken) return
        if (previous != null) {
            try { previous.unregisterCallback(mediaCallback) } catch (_: Exception) { }
        }
        activeController = next
        if (next != null) {
            try { next.registerCallback(mediaCallback, mainHandler) }
            catch (_: Exception) { activeController = null }
        }
    }

    fun command(action: String, requestedPosition: Long = 0L, searchQuery: String = ""): MediaCommandResult {
        if (!hasAccess()) return MediaCommandResult(false, "알림 접근 권한을 먼저 허용해 줘.")
        // Refresh immediately before controlling a session; no stale cached session token.
        refreshSessions()
        val controller = activeController ?: return MediaCommandResult(false, "${LABELS[provider]}의 활성 재생 세션이 없어. 앱에서 먼저 곡을 재생해 줘.")
        val state = controller.playbackState ?: return MediaCommandResult(false, "음악 앱이 재생 명령 정보를 제공하지 않아.")
        val actions = state.actions
        val transport = controller.transportControls
        val valid = when (action) {
            "play" -> (actions and PlaybackState.ACTION_PLAY) != 0L
            "pause" -> (actions and PlaybackState.ACTION_PAUSE) != 0L
            "next" -> (actions and PlaybackState.ACTION_SKIP_TO_NEXT) != 0L
            "previous" -> (actions and PlaybackState.ACTION_SKIP_TO_PREVIOUS) != 0L
            "seek" -> (actions and PlaybackState.ACTION_SEEK_TO) != 0L
            "playFromSearch" -> (actions and PlaybackState.ACTION_PLAY_FROM_SEARCH) != 0L && searchQuery.isNotBlank()
            else -> false
        }
        if (!valid) return MediaCommandResult(false, "${LABELS[provider]}에서 이 명령을 지원한다고 표시하지 않았어.")
        try {
            when (action) {
                "play" -> transport.play()
                "pause" -> transport.pause()
                "next" -> transport.skipToNext()
                "previous" -> transport.skipToPrevious()
                "seek" -> {
                    val duration = controller.metadata?.getLong(MediaMetadata.METADATA_KEY_DURATION) ?: 0L
                    transport.seekTo(requestedPosition.coerceIn(0L, if (duration > 0L) duration else Long.MAX_VALUE))
                }
                "playFromSearch" -> transport.playFromSearch(searchQuery.take(320), Bundle.EMPTY)
            }
            // TransportControls methods return void, so this means "sent", NOT "played".
            return MediaCommandResult(true, if (action == "playFromSearch") "곡 재생 요청을 보냈어. 실제 곡과 재생 상태를 확인해 줘."
                else "음악 앱에 명령을 보냈어. 재생 상태를 다시 확인해 줘.")
        } catch (_: SecurityException) { return MediaCommandResult(false, "음악 앱 제어 권한이 없어.")
        } catch (_: Exception) { return MediaCommandResult(false, "음악 앱에 명령을 전달하지 못했어.") }
    }

    /** Deliberately does not include notification contents or unrelated sessions. */
    private fun publish() {
        val permitted = hasAccess()
        val controller = if (permitted) activeController else null
        val metadata = controller?.metadata
        val playback = controller?.playbackState
        val duration = metadata?.getLong(MediaMetadata.METADATA_KEY_DURATION)?.coerceAtLeast(0L) ?: 0L
        val position = if (playback != null && playback.position >= 0L) {
            val elapsed = (SystemClock.elapsedRealtime() - playback.lastPositionUpdateTime).coerceAtLeast(0L)
            val projected = if (playback.state == PlaybackState.STATE_PLAYING)
                playback.position + (elapsed * playback.playbackSpeed).toLong()
                else playback.position
            projected.coerceIn(0L, if (duration > 0) duration else Long.MAX_VALUE)
        } else -1L
        val flags = playback?.actions ?: 0L
        val snapshot = JSONObject().apply {
            put("permission", permitted)
            put("connected", controller != null)
            put("provider", provider)
            put("providerName", LABELS[provider] ?: provider)
            put("title", metadata?.getString(MediaMetadata.METADATA_KEY_TITLE).orEmpty().take(160))
            put("artist", metadata?.getString(MediaMetadata.METADATA_KEY_ARTIST).orEmpty().take(160))
            put("album", metadata?.getString(MediaMetadata.METADATA_KEY_ALBUM).orEmpty().take(160))
            put("durationMs", duration)
            put("positionMs", position)
            put("state", when (playback?.state) {
                PlaybackState.STATE_PLAYING -> "playing"
                PlaybackState.STATE_PAUSED -> "paused"
                PlaybackState.STATE_BUFFERING, PlaybackState.STATE_CONNECTING -> "buffering"
                PlaybackState.STATE_STOPPED -> "stopped"
                else -> "unknown"
            })
            put("canPlay", (flags and PlaybackState.ACTION_PLAY) != 0L)
            put("canPause", (flags and PlaybackState.ACTION_PAUSE) != 0L)
            put("canNext", (flags and PlaybackState.ACTION_SKIP_TO_NEXT) != 0L)
            put("canPrevious", (flags and PlaybackState.ACTION_SKIP_TO_PREVIOUS) != 0L)
            put("canSeek", (flags and PlaybackState.ACTION_SEEK_TO) != 0L)
            put("canPlayFromSearch", (flags and PlaybackState.ACTION_PLAY_FROM_SEARCH) != 0L)
        }
        latestState = snapshot
        publishToSite(snapshot)
    }
}
