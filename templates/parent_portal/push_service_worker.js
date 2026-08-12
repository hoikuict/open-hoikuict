self.addEventListener('push', event => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (_) { payload = {}; }
  const title = payload.title || '保育園から確認のお願い';
  const body = payload.body || '確認が必要な連絡があります。保護者ポータルをご確認ください。';
  const receiptData = {
    target_id: payload.target_id,
    shown_receipt_token: payload.shown_receipt_token
  };
  event.waitUntil(self.registration.showNotification(title, {
    body,
    icon: '/parent-portal/push-icon.svg',
    badge: '/parent-portal/push-icon.svg',
    tag: payload.notification_id ? `parent-notification-${payload.notification_id}` : undefined,
    data: {
      action_url: safeActionUrl(payload.action_url),
      target_id: payload.target_id,
      clicked_receipt_token: payload.clicked_receipt_token
    }
  }).then(() => postReceipt(receiptData, 'shown')));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const actionUrl = new URL(
    safeActionUrl(event.notification.data?.action_url),
    self.location.origin
  ).href;
  event.waitUntil((async () => {
    // Start receipt recording without delaying navigation. Chrome may reject
    // openWindow after waiting for a network round trip because the click's
    // transient user activation has already expired.
    const receiptPromise = postReceipt(event.notification.data, 'clicked');
    const windows = await clients.matchAll({type: 'window', includeUncontrolled: true});
    let navigationPromise;
    for (const client of windows) {
      navigationPromise = (async () => {
        if ('navigate' in client) await client.navigate(actionUrl);
        return client.focus();
      })();
      break;
    }
    navigationPromise ||= clients.openWindow(actionUrl);
    await Promise.allSettled([navigationPromise, receiptPromise]);
  })());
});

function safeActionUrl(value) {
  return typeof value === 'string' && value.startsWith('/parent-portal/') ? value : '/parent-portal/';
}

async function postReceipt(data, eventName) {
  const token = data?.[`${eventName}_receipt_token`];
  const targetId = data?.target_id;
  if (!token || !Number.isInteger(targetId)) return;
  try {
    await fetch(`/parent-portal/push/receipts/${targetId}/${eventName}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({token})
    });
  } catch (_) {
    // Receipt failure must not prevent notification navigation.
  }
}
