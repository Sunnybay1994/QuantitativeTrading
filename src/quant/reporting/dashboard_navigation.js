/* Small hash routes: only the selected view starts its expensive readers. */
(() => {
  const names = {overview:'运行总览', dataAcquisition:'数据获取', curves:'策略曲线',
    accountsView:'模拟账户', researchResults:'研究结果'};
  const loaded = new Map();
  window.dashboardPage = 'overview';
  function load(src) {
    if (!loaded.has(src)) {
      loaded.set(src, new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.onload = resolve;
        script.onerror = () => { loaded.delete(src); script.remove(); reject(Error('模块加载失败，请重试')); };
        document.body.appendChild(script);
      }));
    }
    return loaded.get(src);
  }
  async function show() {
    const key = location.hash.slice(1);
    const page = Object.hasOwn(names, key) ? key : 'overview';
    window.dashboardPage = page;
    const refresh = document.getElementById('refreshTop');
    refresh.disabled = false;
    refresh.textContent = '刷新当前页';
    document.querySelectorAll('[data-page]').forEach(el => { el.hidden = el.dataset.page !== page; });
    document.querySelectorAll('.navigation a').forEach(a => {
      if (a.hash === '#'+page) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    document.getElementById('pageTitle').textContent = names[page];
    document.getElementById('updated').textContent = '仅刷新当前页面 · 切换后保留筛选条件';
    document.title = names[page]+' · 投研工作台';
    window.scrollTo({top:0, behavior:'instant'});
    try {
      if (page === 'curves') await load('/curves.js');
      if (page === 'dataAcquisition') await load('/data.js');
      if (window.dashboardPage === page) window.dispatchEvent(new CustomEvent('dashboard:page', {detail:page}));
    } catch (error) {
      document.getElementById('updated').textContent = error.message;
    }
  }
  window.addEventListener('hashchange', show);
  document.addEventListener('DOMContentLoaded', show);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) window.dispatchEvent(new CustomEvent('dashboard:page', {detail:window.dashboardPage}));
  });
  window.addEventListener('dashboard:refresh', () => {
    if ((window.dashboardPage === 'curves' && !loaded.has('/curves.js')) ||
        (window.dashboardPage === 'dataAcquisition' && !loaded.has('/data.js'))) show();
  });
})();
