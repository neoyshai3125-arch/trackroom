package com.trackroom.mobile

import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import android.os.SystemClock
import android.util.Base64
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.ServerSocket
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.Executors

/** Spotify Web API + browser-based Authorization Code with PKCE.
 *  Playback happens in the user's existing Spotify app / Spotify Connect device.
 *  The Android prototype does not decode, relay or store any audio.
 */
class SpotifyConnector(
    private val activity: MainActivity,
    private val prefs: SharedPreferences,
    private val outcome: (Boolean, String) -> Unit
) {
    private val worker = Executors.newSingleThreadExecutor()
    private val rng = SecureRandom()
    private var pending: StreamTrack? = null
    @Volatile private var isAuthorizing = false

    fun play(track: StreamTrack) {
        pending = track
        val client = prefs.getString("spotify_client_id", "").orEmpty()
        if (client.isBlank()) {
            activity.promptSpotifyClientId { requestPlay(track, it) }
        } else requestPlay(track, client)
    }

    private fun requestPlay(track: StreamTrack, clientId: String) {
        worker.execute {
            try {
                val accessToken = validAccessToken(clientId)
                if (accessToken.isNullOrBlank()) {
                    startAuthorization(clientId)
                } else searchAndPlay(track, accessToken)
            } catch (e: Exception) {
                outcome(false, "Spotify 연결 오류: ${e.message ?: "알 수 없는 오류"}")
            }
        }
    }

    private fun validAccessToken(clientId: String): String? {
        val token = prefs.getString("spotify_access_token", "")?.takeIf { it.isNotBlank() }
        if (token != null && prefs.getLong("spotify_expiry",0) > System.currentTimeMillis()+30_000) return token
        val refresh = prefs.getString("spotify_refresh_token", "").orEmpty()
        if (refresh.isBlank()) return null
        val body = mapOf(
            "grant_type" to "refresh_token", "refresh_token" to refresh, "client_id" to clientId
        )
        return try { saveToken(requestToken(body)).getString("access_token") }
        catch (_: Exception) { null }
    }

    private fun startAuthorization(clientId: String) {
        if (isAuthorizing) { outcome(false,"이미 Spotify 계정 인증을 진행 중이야."); return }
        isAuthorizing = true
        var server: ServerSocket? = null
        try {
            server = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
            server.soTimeout = 120_000
            val redirect = "http://127.0.0.1:${server.localPort}/callback"
            val verifier = randomString(48)
            val state = randomString(24)
            val challengeBytes = MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray(Charsets.US_ASCII))
            val challenge = Base64.encodeToString(challengeBytes, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
            val query = encodeForm(mapOf(
                "response_type" to "code", "client_id" to clientId, "redirect_uri" to redirect,
                "scope" to "user-modify-playback-state user-read-playback-state",
                "state" to state, "code_challenge_method" to "S256", "code_challenge" to challenge
            ))
            activity.runOnUiThread {
                outcome(true,"Spotify 계정 인증을 승인하고 TRACKROOM 앱으로 돌아와 줘.")
                activity.openExternal(Uri.parse("https://accounts.spotify.com/authorize?$query"))
            }
            server.accept().use { socket ->
                socket.soTimeout = 10_000
                val reader = BufferedReader(InputStreamReader(socket.getInputStream(),Charsets.UTF_8))
                val firstLine = reader.readLine() ?: throw Exception("OAuth 응답이 비어 있어.")
                val target = firstLine.split(' ').getOrNull(1) ?: throw Exception("OAuth 응답 형식 오류")
                // Drain HTTP headers and respond immediately so the browser can finish.
                while (true) { val line = reader.readLine() ?: break; if (line.isBlank()) break }
                val callback = Uri.parse("http://127.0.0.1$target")
                val code = if (callback.path == "/callback" && callback.getQueryParameter("state") == state)
                    callback.getQueryParameter("code") else null
                val message = if (code != null) "Spotify 연결이 완료됐어요. TRACKROOM으로 돌아가세요."
                    else "Spotify 승인이 완료되지 않았어요. TRACKROOM으로 돌아가세요."
                val page = "<meta charset='utf-8'><h2>${message}</h2>"
                val body = page.toByteArray(Charsets.UTF_8)
                socket.getOutputStream().write(
                    "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray()
                )
                socket.getOutputStream().write(body)
                socket.getOutputStream().flush()
                if (code == null) throw Exception("Spotify 계정 인증이 취소되었거나 상태 검증에 실패했어.")
                val token = saveToken(requestToken(mapOf(
                    "grant_type" to "authorization_code", "code" to code,
                    "redirect_uri" to redirect, "client_id" to clientId, "code_verifier" to verifier
                ))).getString("access_token")
                pending?.let { searchAndPlay(it, token) }
            }
        } catch (e: Exception) {
            outcome(false,"Spotify 계정 인증 실패: ${e.message ?: "다시 시도해 줘."}")
        } finally {
            server?.close()
            isAuthorizing = false
        }
    }

    private fun searchAndPlay(track: StreamTrack, token: String) {
        val known = spotifyTrackUri(track.musicUrl)
        if (known != null) { sendPlay(token, known); return }
        val query = URLEncoder.encode("${track.title} ${track.artist}","UTF-8")
        val results = getJson("https://api.spotify.com/v1/search?q=$query&type=track&limit=5",token)
            .optJSONObject("tracks")?.optJSONArray("items")
        if (results == null || results.length()==0) {
            outcome(false,"Spotify에서 일치하는 곡을 찾지 못했어.")
            return
        }
        val uris = mutableListOf<String>()
        val labels = mutableListOf<String>()
        for (i in 0 until results.length()) {
            val item = results.optJSONObject(i) ?: continue
            val uri = item.optString("uri")
            if (!uri.matches(Regex("spotify:track:[A-Za-z0-9]{22}"))) continue
            val arr = item.optJSONArray("artists")
            val singer = (0 until (arr?.length()?:0)).mapNotNull { j -> arr?.optJSONObject(j)?.optString("name") }
                .joinToString(", ")
            val album = item.optJSONObject("album")?.optString("name").orEmpty()
            uris.add(uri)
            labels.add("${item.optString("name")} — ${singer}\n${album}")
        }
        if (uris.isEmpty()) { outcome(false,"Spotify 곡 링크를 찾지 못했어."); return }
        activity.runOnUiThread {
            activity.chooseSpotifyTrack(labels.toTypedArray()) { index ->
                worker.execute { sendPlay(token,uris[index]) }
            }
        }
    }

    private fun spotifyTrackUri(musicUrl: String): String? {
        val direct = Regex("^spotify:track:([A-Za-z0-9]{22})$").find(musicUrl)
        if (direct != null) return direct.value
        val parsed = Uri.parse(musicUrl)
        if (parsed.scheme != "https" || parsed.host != "open.spotify.com") return null
        val id = Regex("^/track/([A-Za-z0-9]{22})(?:/)?$").find(parsed.path.orEmpty())?.groupValues?.get(1)
        return if (id != null) "spotify:track:$id" else null
    }

    private fun sendPlay(token: String, trackUri: String) {
        try {
            requestJson(
                "PUT", "https://api.spotify.com/v1/me/player/play", token,
                JSONObject().put("uris",org.json.JSONArray().put(trackUri)).toString()
            )
            outcome(true,"Spotify에서 재생 명령을 전달했어. 실제 재생 여부는 Spotify 앱에서 확인해 줘.")
        } catch (e: ApiError) {
            val message = if (e.code == 404) "Spotify 활성 재생 기기가 없어. Spotify 앱에서 한 곡을 재생한 다음 다시 시도해 줘."
                else if (e.code == 403) "Spotify Premium 또는 개발 앱 권한이 부족해. (${e.message})"
                else "Spotify 재생 요청 실패: ${e.message}"
            outcome(false,message)
        } catch (e: Exception) { outcome(false,"Spotify 재생 오류: ${e.message}") }
    }

    private fun saveToken(obj: JSONObject): JSONObject {
        val editor = prefs.edit()
        editor.putString("spotify_access_token",obj.getString("access_token"))
        if (obj.has("refresh_token")) editor.putString("spotify_refresh_token",obj.getString("refresh_token"))
        editor.putLong("spotify_expiry",System.currentTimeMillis()+obj.optLong("expires_in",3600)*1000)
        editor.apply()
        return obj
    }

    private fun randomString(size: Int): String {
        val bytes=ByteArray(size);rng.nextBytes(bytes)
        return Base64.encodeToString(bytes,Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
    }
    private fun encodeForm(parts: Map<String,String>) = parts.entries.joinToString("&") {
        "${URLEncoder.encode(it.key,"UTF-8")}=${URLEncoder.encode(it.value,"UTF-8")}" }
    private fun requestToken(parts: Map<String,String>): JSONObject {
        val data = encodeForm(parts)
        val url = URL("https://accounts.spotify.com/api/token")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod="POST"; connectTimeout=10_000;readTimeout=12_000;doOutput=true
            setRequestProperty("Content-Type","application/x-www-form-urlencoded")
        }
        try {
            conn.outputStream.use {it.write(data.toByteArray(Charsets.UTF_8))}
            return parse(conn)
        } finally { conn.disconnect() }
    }
    private fun getJson(uri: String, token:String):JSONObject = requestJson("GET",uri,token,null)
    private fun requestJson(method:String, uri:String, token:String, data:String?):JSONObject {
        val conn=(URL(uri).openConnection() as HttpURLConnection).apply {
            requestMethod=method;connectTimeout=10_000;readTimeout=12_000
            setRequestProperty("Authorization","Bearer $token")
            setRequestProperty("Accept","application/json")
            if(data!=null){doOutput=true;setRequestProperty("Content-Type","application/json")}
        }
        try {
            if(data!=null) conn.outputStream.use {it.write(data.toByteArray(Charsets.UTF_8))}
            return parse(conn)
        } finally {conn.disconnect()}
    }
    private fun parse(conn: HttpURLConnection):JSONObject {
        val code=conn.responseCode
        val response=(if(code in 200..299)conn.inputStream else conn.errorStream)
            ?.bufferedReader(Charsets.UTF_8)?.use{it.readText()}.orEmpty()
        if(code !in 200..299){
            val obj=runCatching{JSONObject(response)}.getOrNull()
            val error=obj?.optJSONObject("error")?.optString("message")
                ?: obj?.optString("error_description") ?: response.take(100)
            throw ApiError(code,error.ifBlank { "HTTP $code" })
        }
        return if(response.isBlank())JSONObject() else JSONObject(response)
    }
    fun close() { worker.shutdownNow() }
    private class ApiError(val code:Int,override val message:String):Exception(message)
}
