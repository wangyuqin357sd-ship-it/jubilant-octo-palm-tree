/*
  语忆 · 系统通知 Service Worker
  ============================================================================
  为什么必须有这个文件：
    Chrome for Android 上 `new Notification(...)` 会直接抛
      TypeError: Illegal constructor. Use ServiceWorkerRegistration.showNotification() instead.
    所以在手机端想弹出「常驻通知」，只能由页面调用
      registration.showNotification(title, options)

  本文件只做两件事：
    1. 装好就立刻接管（skipWaiting + clients.claim），避免要刷新两次才生效
    2. 点通知时把页面切到前台；页面已经关了就把预览重新打开

  注意：这里**故意不注册 fetch 事件**——预览不需要离线缓存，
  加了 fetch 反而容易让「改完看不到最新效果」。
*/

self.addEventListener('install', function (e) {
  self.skipWaiting();
});

self.addEventListener('activate', function (e) {
  e.waitUntil(self.clients.claim());
});

/* 点击系统通知：优先聚焦已有页面，否则重新打开预览 */
self.addEventListener('notificationclick', function (e) {
  e.notification.close();
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
      for (var i = 0; i < list.length; i++) {
        var c = list[i];
        if ('focus' in c) return c.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow('./index.html');
    })
  );
});

/* 关闭通知（页面侧 close() 会走到这里，保持与页面记录一致） */
self.addEventListener('notificationclose', function () { /* 预留 */ });