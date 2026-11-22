package com.trackroom.mobile

import android.service.notification.NotificationListenerService

/** Permission anchor for MediaSessionManager; intentionally does NOT read or store notifications. */
class TrackroomNotificationListener : NotificationListenerService()
