self.addEventListener('install', event => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', event => {
  event.waitUntil(clients.claim());
});

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
    // openWindow must be started directly from the click handler. Reusing an
    // arbitrary existing tab can focus the demo top page without navigating.
    const navigationPromise = openActionUrl(actionUrl);
    const receiptPromise = postReceipt(event.notification.data, 'clicked');
    await Promise.allSettled([navigationPromise, receiptPromise]);
  })());
});

async function openActionUrl(actionUrl) {
  try {
    const openedClient = await clients.openWindow(actionUrl);
    if (openedClient) {
      if ('focus' in openedClient) await openedClient.focus();
      return;
    }
  } catch (_) {
    // Fall back to an existing same-origin window when opening is unavailable.
  }

  const windows = await clients.matchAll({type: 'window', includeUncontrolled: true});
  for (const client of windows) {
    try {
      if ('navigate' in client) {
        const navigatedClient = await client.navigate(actionUrl);
        if (navigatedClient) {
          await navigatedClient.focus();
          return;
        }
      }
      await client.focus();
      return;
    } catch (_) {
      // Try another controlled window if this one can no longer be used.
    }
  }
}

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
