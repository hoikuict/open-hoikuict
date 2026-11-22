// No fetch handler or cache: child data never enters an offline cache.
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data.json(); } catch (_) {}
  if (data.expires_at && new Date(data.expires_at) < new Date()) return;
  event.waitUntil(self.registration.showNotification('クラスへの連絡', {
    body: data.body === '通知のテストです。' ? data.body : '新しい連絡があります。内容を確認してください。',
    tag: data.tag || 'class-kiosk', data: {url: '/class-kiosk/'}, renotify: true
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async () => {
    const windows = await clients.matchAll({type:'window', includeUncontrolled:true});
    for (const client of windows) {
      if (new URL(client.url).pathname === '/class-kiosk/') {
        client.postMessage({type:'refresh'});
        await client.focus();
        return;
      }
    }
    await clients.openWindow('/class-kiosk/');
  })());
});
