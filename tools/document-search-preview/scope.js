// The preview only serves the planning home, list, and read-only sample documents.
for (const link of document.querySelectorAll('a[href]')) {
  if (link.hash && link.pathname === location.pathname) continue;
  if (link.origin === location.origin && /^\/plans\/(?:documents\/(?:\d+)?)?$/.test(link.pathname)) continue;
  link.removeAttribute('href');
  link.setAttribute('aria-disabled', 'true');
  link.title = 'このモックでは帳票の検索と閲覧を試せます';
}
for (const form of document.querySelectorAll('form:not(#document-search)')) {
  form.addEventListener('submit', event => event.preventDefault());
  for (const control of form.elements) control.disabled = true;
}
