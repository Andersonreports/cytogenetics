// Sign-in per tab: opening the tool in a new tab or window always asks to sign in.
// The page right after signing in is marked "fresh" by the server; this tab then
// remembers it (sessionStorage lives as long as the tab, through reloads). A tab
// without that mark signs out and goes to the sign-in page before anything shows.
(function () {
  const root = document.documentElement;
  const user = root.dataset.user || '';
  const KEY = 'cyto_tab_signed_in';
  let ok = true;
  try {
    if (root.dataset.fresh === '1') sessionStorage.setItem(KEY, user);
    ok = !!user && sessionStorage.getItem(KEY) === user;
  } catch (e) { ok = true; }      // no sessionStorage (very locked-down browser): server rules only
  window.CYTO_TAB_OK = ok;
  if (ok) return;
  root.style.visibility = 'hidden';
  document.addEventListener('DOMContentLoaded', () => {
    const form = document.querySelector('form[data-logout]');
    if (form) form.submit(); else location.href = '/login';
  });
})();
