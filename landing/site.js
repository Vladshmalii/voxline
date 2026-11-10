/* Shared behaviour for every page: language, theme, mobile menu. */
(function () {
  var COMMON = {
    uk: {
      c_nav_problem: 'Втрати', c_nav_cases: 'Сценарії', c_nav_features: 'Можливості', c_nav_roi: 'Калькулятор', c_nav_faq: 'Питання',
      c_demo: 'Демо', c_menu: 'Меню',
      c_tagline: 'Голосовий ШІ, який не спить і не зливає ліди.',
      c_col_product: 'Продукт', c_col_legal: 'Правова інформація', c_col_contact: 'Контакти',
      c_how: 'Як це працює', c_compare: 'Порівняння',
      c_privacy: 'Політика конфіденційності', c_terms: 'Умови використання', c_cookies: 'Політика cookies', c_contacts: 'Контакти',
      c_rights: '© 2026 Allo AI. Всі права захищено.', c_back: 'На головну'
    },
    en: {
      c_nav_problem: 'Losses', c_nav_cases: 'Use cases', c_nav_features: 'Features', c_nav_roi: 'Calculator', c_nav_faq: 'FAQ',
      c_demo: 'Demo', c_menu: 'Menu',
      c_tagline: 'Voice AI that never sleeps and never drops a lead.',
      c_col_product: 'Product', c_col_legal: 'Legal', c_col_contact: 'Contact',
      c_how: 'How it works', c_compare: 'Comparison',
      c_privacy: 'Privacy Policy', c_terms: 'Terms of Use', c_cookies: 'Cookie Policy', c_contacts: 'Contacts',
      c_rights: '© 2026 Allo AI. All rights reserved.', c_back: 'Back to home'
    }
  };
  var root = document.documentElement;
  function get(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }
  function put(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  var MOON = 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z';
  var SUN = 'M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z';

  function setTheme(t) {
    root.setAttribute('data-theme', t); put('allo-theme', t);
    [].forEach.call(document.querySelectorAll('.theme-path'), function (p) { p.setAttribute('d', t === 'dark' ? MOON : SUN); });
    var m = document.querySelector('meta[name=theme-color]'); if (m) m.content = t === 'dark' ? '#050711' : '#f6f7fb';
  }
  function setLang(l) {
    root.lang = l; put('allo-lang', l); site.lang = l;
    var d = COMMON[l];
    [].forEach.call(document.querySelectorAll('[data-i]'), function (el) { if (d[el.dataset.i] !== undefined) el.textContent = d[el.dataset.i]; });
    [].forEach.call(document.querySelectorAll('[data-l]'), function (el) { el.hidden = el.dataset.l !== l; });
    [].forEach.call(document.querySelectorAll('[data-lang]'), function (b) { b.setAttribute('aria-pressed', String(b.dataset.lang === l)); });
    var m = document.getElementById('menu-btn'); if (m) m.setAttribute('aria-label', d.c_menu);
    var tt = document.querySelector('title[data-uk]'); if (tt) document.title = tt.getAttribute('data-' + l);
    document.dispatchEvent(new CustomEvent('allo:lang', { detail: l }));
  }

  var site = window.AlloSite = { lang: get('allo-lang', 'uk') === 'en' ? 'en' : 'uk', setLang: setLang, setTheme: setTheme };

  [].forEach.call(document.querySelectorAll('[data-lang]'), function (b) { b.addEventListener('click', function () { setLang(b.dataset.lang); }); });
  [].forEach.call(document.querySelectorAll('.js-theme'), function (b) { b.addEventListener('click', function () { setTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'); }); });

  /* mobile drawer */
  var menu = document.getElementById('menu-btn'), drawer = document.getElementById('drawer');
  function drawerSet(open) {
    if (!menu || !drawer) return;
    drawer.classList.toggle('open', open); menu.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('drawer-open', open);
  }
  if (menu) {
    menu.addEventListener('click', function () { drawerSet(!drawer.classList.contains('open')); });
    drawer.addEventListener('click', function (e) { if (e.target.closest('a')) drawerSet(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') drawerSet(false); });
    window.addEventListener('resize', function () { if (innerWidth > 980) drawerSet(false); });
  }
  window.addEventListener('scroll', function () {
    var h = document.getElementById('hdr'); if (h) h.classList.toggle('scrolled', scrollY > 8);
  }, { passive: true });

  setTheme(get('allo-theme', 'dark') === 'light' ? 'light' : 'dark');
  setLang(site.lang);
})();
