import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_android_ui_assets_are_linked():
    html = (ROOT/'public/index.html').read_text()
    js = (ROOT/'public/app.js').read_text()
    sw = (ROOT/'public/sw.js').read_text()
    assert 'native-streaming.css?v=6.9.9' in html
    assert 'native-streaming.js?v=6.9.9' in html
    assert 'id="roomStreamControls"' in html
    assert 'TrackroomStreaming.controls(song)' in js
    assert 'TrackroomRoomStreamActiveSong' in js
    assert 'roomStreamControls' in js
    assert 'trackroom-shell-v6.9.9' in sw
    assert 'native-streaming.js?v=6.9.9' in sw


def test_safety_and_no_unsupported_autoplay():
    native = (ROOT/'android/app/src/main/java/com/trackroom/mobile/MainActivity.kt').read_text()
    spotify = (ROOT/'android/app/src/main/java/com/trackroom/mobile/SpotifyConnector.kt').read_text()
    assert 'request.isForMainFrame' in native
    assert 'isTrustedOrigin(view?.url)' in native
    assert 'javaScriptEnabled = true' in native
    assert 'addJavascriptInterface' not in native
    assert 'getLaunchIntentForPackage' in native
    assert '자동 재생 연동은 아직 지원되지 않아' in native
    assert 'user-modify-playback-state' in spotify
    assert 'code_challenge_method" to "S256"' in spotify
    assert '127.0.0.1' in spotify
    assert 'spotify:track:' in spotify
    assert 'https://api.spotify.com/v1/me/player/play' in spotify
    assert 'com.spotify.sdk.android.player.' not in spotify


def test_js_does_not_assume_web_players_are_native():
    js=(ROOT/'public/native-streaming.js').read_text()
    assert 'TRACKROOMAndroid' in js
    for provider in ('spotify','melon','genie','flo','bugs','youtube'):
        assert re.search(rf"\['{provider}'",js)
    assert 'trackroom-native://play?' in js
    assert 'window.location.assign' in js


def test_android_gradle_manifest_and_no_privileged_permissions():
    android = ROOT/'android'
    assert (android/'settings.gradle.kts').exists()
    assert (android/'app/build.gradle.kts').exists()
    manifest = (android/'app/src/main/AndroidManifest.xml').read_text()
    assert 'android.permission.INTERNET' in manifest
    assert 'android.permission.MEDIA_CONTENT_CONTROL' not in manifest
    assert 'QUERY_ALL_PACKAGES' not in manifest
