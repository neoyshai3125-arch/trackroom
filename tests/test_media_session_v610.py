from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def content(path):
    return (ROOT/path).read_text()


def test_android_notification_listener_and_media_permissions():
    manifest = content('android/app/src/main/AndroidManifest.xml')
    assert '<service' in manifest and '.TrackroomNotificationListener' in manifest
    assert 'android.permission.BIND_NOTIFICATION_LISTENER_SERVICE' in manifest
    assert 'android.service.notification.NotificationListenerService' in manifest
    assert 'android.permission.MEDIA_CONTENT_CONTROL' not in manifest
    assert 'QUERY_ALL_PACKAGES' not in manifest
    assert 'SYSTEM_ALERT_WINDOW' not in manifest


def test_session_explicitly_scoped_to_media_packages_and_read_only():
    kt = content('android/app/src/main/java/com/trackroom/mobile/ExternalMediaSessions.kt')
    for package in ('com.iloen.melon','com.ktmusic.geniemusic','skplanet.musicmate',
                    'com.neowiz.android.bugs','com.spotify.music'):
        assert package in kt
    assert 'getActiveSessions(listenerComponent)' in kt
    assert 'Settings.Secure' in kt
    assert 'registerCallback(mediaCallback' in kt
    assert 'metadata?.getString(MediaMetadata.METADATA_KEY_TITLE)' in kt
    assert 'notification.extras' not in kt
    assert 'getActiveNotifications' not in kt
    assert 'sendBroadcast' not in kt


def test_actions_check_playbackstate_capabilities_and_report_command_sent():
    kt = content('android/app/src/main/java/com/trackroom/mobile/ExternalMediaSessions.kt')
    for action in ('ACTION_PLAY', 'ACTION_PAUSE','ACTION_SKIP_TO_NEXT','ACTION_SKIP_TO_PREVIOUS',
                   'ACTION_SEEK_TO','ACTION_PLAY_FROM_SEARCH'):
        assert action in kt
    assert 'playFromSearch' in kt
    assert 'transport.seekTo' in kt
    assert 'MediaCommandResult(true' in kt
    assert '"sent", NOT "played"' in kt


def test_android_browser_safety_and_origin_scope():
    kt=content('android/app/src/main/java/com/trackroom/mobile/MainActivity.kt')
    assert 'request.isForMainFrame && isTrustedOrigin(view?.url)' in kt
    assert 'addJavascriptInterface' not in kt
    assert 'Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS' in kt
    assert 'trackroom:media-session' in kt
    assert 'webView.evaluateJavascript' in kt


def test_web_panel_deployed_with_cache_busting():
    html=content('public/index.html')
    css=content('public/native-streaming.css')
    js=content('public/native-streaming.js')
    sw=content('public/sw.js')
    assert 'v6.10.0</span>' in html
    assert '/native-streaming.js?v=6.10.0' in html
    assert '/native-streaming.css?v=6.10.0' in html
    assert 'trackroom-shell-v6.10.0' in sw
    assert 'trackroom-media-panel' in css
    assert 'trackroom:media-session' in js
    assert 'data-media-command="playFromSearch"' in js
    assert 'data-media-permission' in js
    assert 'window.TrackroomPauseLocalPreview?.()' in js


def test_previous_preview_and_dj_scrub_preserved():
    app=content('public/app.js')
    assert 'TrackroomRoomStreamActiveSong' in app
    assert 'TrackroomPauseLocalPreview' in app
    assert 'roomPlaybackScrub' in app
    assert 'dashboard.pausePreview()' in app
