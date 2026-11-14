/* ============================================================
   사장님·우리집·자취방 쿠팡 실시간 최저가 — app.js
   data/deals.json 을 읽어 섹션·소분류·검색·정렬·필터를 처리한다.
   ============================================================ */
(function () {
  'use strict';

  var PAGE_SIZE = 48;
  // 첫 화면 상위 카드의 썸네일은 lazy 대기 없이 즉시 불러온다 (모바일 체감 속도).
  var EAGER_IMAGE_COUNT = 12;
  var DATA_URL = 'data/deals.json';
  var PLACEHOLDER =
    'data:image/svg+xml;charset=utf-8,' +
    encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">' +
        '<rect width="120" height="120" fill="#f3f1ec"/>' +
        '<g fill="none" stroke="#c8c3b9" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">' +
          '<path d="M36 44h48l-5 36H41z"/><path d="M50 44a10 10 0 0 1 20 0"/>' +
        '</g>' +
        '<text x="60" y="103" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#b3ada2">이미지 없음</text>' +
      '</svg>'
    );

  var SECTION_LABELS = {
    all: '전체',
    cafe: '☕ 카페 사장님 필수템',
    home: '🏠 가정 생필품',
    living: '🧺 자취·살림꿀템',
    winter: '🧥 가성비 겨울옷',
    food: '🛒 가성비 식료품',
    goldbox: '⚡ 오늘의 골드박스',
    pl: '🔥 쿠팡 PL 특가'
  };

  var state = {
    section: 'all',
    sub: 'all',
    rocketOnly: false,
    freeOnly: false,
    sort: 'recommended',
    query: '',
    shown: PAGE_SIZE
  };

  var ALL = [];
  var META = {};

  var el = {
    grid: document.getElementById('grid'),
    skeleton: document.getElementById('skeleton'),
    empty: document.getElementById('empty'),
    emptyTitle: document.querySelector('.empty__title'),
    emptyDesc: document.querySelector('.empty__desc'),
    resultCount: document.getElementById('resultCount'),
    resultHint: document.getElementById('resultHint'),
    chips: document.getElementById('chips'),
    tabs: document.querySelectorAll('.tab'),
    search: document.getElementById('searchInput'),
    searchClear: document.getElementById('searchClear'),
    searchForm: document.getElementById('searchForm'),
    rocket: document.getElementById('rocketOnly'),
    free: document.getElementById('freeOnly'),
    sort: document.getElementById('sort'),
    moreBtn: document.getElementById('moreBtn'),
    resetBtn: document.getElementById('resetBtn'),
    updatedAt: document.getElementById('updatedAt'),
    updatedAtFooter: document.getElementById('updatedAtFooter'),
    totalCountFooter: document.getElementById('totalCountFooter'),
    year: document.getElementById('year')
  };

  var wonFormatter = new Intl.NumberFormat('ko-KR');

  /* ---------------- 유틸 ---------------- */

  function formatWon(price) {
    if (price === null || price === undefined) return '가격 확인';
    return wonFormatter.format(price) + '원';
  }

  /* ---------------- 데이터 로드 ---------------- */

  function renderSkeleton() {
    var frag = document.createDocumentFragment();
    for (var i = 0; i < 10; i++) {
      var sk = document.createElement('div');
      sk.className = 'sk';
      sk.innerHTML =
        '<div class="sk__img"></div>' +
        '<div class="sk__line"></div>' +
        '<div class="sk__line sk__line--short"></div>' +
        '<div class="sk__line sk__line--price"></div>';
      frag.appendChild(sk);
    }
    el.skeleton.innerHTML = '';
    el.skeleton.appendChild(frag);
  }

  function load() {
    renderSkeleton();
    fetch(DATA_URL, { cache: 'no-cache' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        META = (data && data.meta) || {};
        ALL = (data && data.products) || [];
        ALL.forEach(function (p, i) { p._i = i; });
        if (!ALL.length) throw new Error('empty');
        applyMeta();
        buildChips();
        render();
      })
      .catch(function (err) {
        el.skeleton.hidden = true;
        el.empty.hidden = false;
        el.emptyTitle.textContent = '상품 데이터를 불러오지 못했습니다';
        el.emptyDesc.textContent =
          '데이터 파일(data/deals.json)을 읽을 수 없습니다. 잠시 후 새로고침하거나, ' +
          '로컬 파일로 열었다면 간단한 웹 서버(예: python3 -m http.server)로 열어 주세요.';
        el.resultCount.textContent = '';
        console.error('[deals] load failed:', err);
      });
  }

  function applyMeta() {
    var display = META.updatedAtDisplay || '–';
    el.updatedAt.textContent = '최근 업데이트: ' + display;
    el.updatedAtFooter.textContent = '최근 업데이트: ' + display;
    el.totalCountFooter.textContent = '총 ' + (META.totalCount || ALL.length) + '개 상품';
    var counts = META.sectionCounts || {};
    document.querySelectorAll('.tab__count').forEach(function (node) {
      var key = node.getAttribute('data-count');
      var n = key === 'all' ? (META.totalCount || ALL.length) : (counts[key] || 0);
      node.textContent = n;
    });
    if (el.year) el.year.textContent = String(new Date().getFullYear());
    if (META.disclosure) {
      document.querySelectorAll('.footer__disclosure p:nth-child(2)').forEach(function (p) {
        p.textContent =
          META.disclosure +
          ' 상품 가격은 쿠팡에서 구매하실 때와 동일하며, 이용자에게 추가 비용이 발생하지 않습니다.';
      });
    }
  }

  /* ---------------- 필터 계산 ---------------- */

  function isSearchMode() {
    return state.query.trim().length > 0;
  }

  function sectionItems(section) {
    return ALL.filter(function (p) { return section === 'all' || p.section === section; });
  }

  function matchesQuery(p) {
    var q = state.query.trim().toLowerCase();
    if (!q) return true;
    var hay = (p.productName + ' ' + p.subCategory + ' ' + (p.keyword || '') + ' ' + (p.categoryName || '')).toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  function nameMatchesQuery(p) {
    var q = state.query.trim().toLowerCase();
    if (!q) return true;
    return p.productName.toLowerCase().indexOf(q) !== -1;
  }

  function passesBase(p) {
    if (state.rocketOnly && !p.isRocket) return false;
    if (state.freeOnly && !p.isFreeShipping) return false;
    return matchesQuery(p);
  }

  function filtered() {
    var list = ALL.filter(function (p) {
      if (state.section !== 'all' && p.section !== state.section) return false;
      if (state.sub !== 'all' && p.subCategory !== state.sub) return false;
      return passesBase(p);
    });

    if (state.sort === 'price-asc' || state.sort === 'price-desc') {
      var dir = state.sort === 'price-asc' ? 1 : -1;
      list.sort(function (a, b) {
        var pa = a.productPrice === null || a.productPrice === undefined ? Number.MAX_SAFE_INTEGER : a.productPrice;
        var pb = b.productPrice === null || b.productPrice === undefined ? Number.MAX_SAFE_INTEGER : b.productPrice;
        if (pa === pb) return a._i - b._i;
        return (pa - pb) * dir;
      });
    } else if (isSearchMode()) {
      // 검색어가 상품명에 있는 상품을 먼저, 키워드로만 걸린 상품은 뒤로
      list.sort(function (a, b) {
        var na = nameMatchesQuery(a) ? 0 : 1;
        var nb = nameMatchesQuery(b) ? 0 : 1;
        if (na !== nb) return na - nb;
        return a._i - b._i;
      });
    }
    return list;
  }

  /* ---------------- 소분류 칩 ---------------- */

  function subcategoriesOf(section) {
    var seen = [];
    ALL.forEach(function (p) {
      if (section !== 'all' && p.section !== section) return;
      if (seen.indexOf(p.subCategory) === -1) seen.push(p.subCategory);
    });
    return seen;
  }

  function buildChips() {
    var subs = subcategoriesOf(state.section);
    el.chips.innerHTML = '';

    // 소분류가 하나뿐인 섹션(골드박스·PL)에서는 칩을 숨긴다
    if (subs.length <= 1) {
      el.chips.hidden = true;
      state.sub = 'all';
      return;
    }
    el.chips.hidden = false;

    if (state.sub !== 'all' && subs.indexOf(state.sub) === -1) state.sub = 'all';

    var base = sectionItems(state.section).filter(passesBase);
    var counts = {};
    base.forEach(function (p) { counts[p.subCategory] = (counts[p.subCategory] || 0) + 1; });

    var items = [{ label: '전체', value: 'all', n: base.length }].concat(
      subs.map(function (s) { return { label: s, value: s, n: counts[s] || 0 }; })
    );

    items.forEach(function (item) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chip' + (state.sub === item.value ? ' is-active' : '');
      btn.setAttribute('aria-pressed', state.sub === item.value ? 'true' : 'false');
      btn.dataset.sub = item.value;
      btn.appendChild(document.createTextNode(item.label));
      var n = document.createElement('span');
      n.className = 'chip__n';
      n.textContent = item.n;
      btn.appendChild(n);
      btn.addEventListener('click', function () {
        state.sub = item.value;
        state.shown = PAGE_SIZE;
        buildChips();
        render();
      });
      el.chips.appendChild(btn);
    });
  }

  /* ---------------- 카드 ---------------- */

  function makeBadge(text, kind) {
    var b = document.createElement('span');
    b.className = 'badge badge--' + kind;
    b.textContent = text;
    return b;
  }

  function makeCard(p, index) {
    var card = document.createElement('div');
    card.className = 'card';

    var thumb = document.createElement('a');
    thumb.className = 'card__thumb';
    thumb.href = p.productUrl;
    thumb.target = '_blank';
    thumb.rel = 'noopener noreferrer sponsored';
    thumb.setAttribute('aria-label', p.productName + ' — 쿠팡에서 보기');

    var img = document.createElement('img');
    var eager = typeof index === 'number' && index < EAGER_IMAGE_COUNT;
    img.loading = eager ? 'eager' : 'lazy';
    if (eager && 'fetchPriority' in img) img.fetchPriority = 'high';
    img.decoding = 'async';
    // 쿠팡 이미지 CDN은 리퍼러가 붙으면 막히는 경우가 있어 no-referrer로 요청한다.
    img.referrerPolicy = 'no-referrer';
    img.alt = p.productName;
    img.src = p.productImage || PLACEHOLDER;
    img.addEventListener('error', function () {
      if (img.dataset.fallback) return;
      img.dataset.fallback = '1';
      img.classList.add('is-fallback');
      img.src = PLACEHOLDER;
    });
    if (!p.productImage) img.classList.add('is-fallback');
    thumb.appendChild(img);

    var badges = document.createElement('div');
    badges.className = 'badges';
    if (p.isRocket) badges.appendChild(makeBadge('로켓배송', 'rocket'));
    if (p.isFreeShipping) badges.appendChild(makeBadge('무료배송', 'free'));
    if (p.section === 'goldbox') badges.appendChild(makeBadge('골드박스', 'gold'));
    if (p.section === 'pl') badges.appendChild(makeBadge('쿠팡PL', 'pl'));
    if (badges.children.length) thumb.appendChild(badges);

    if (p.rank && p.rank <= 3 && (p.section === 'goldbox' || p.section === 'pl')) {
      var rank = document.createElement('span');
      rank.className = 'rank';
      rank.textContent = 'TOP ' + p.rank;
      thumb.appendChild(rank);
    }

    var body = document.createElement('div');
    body.className = 'card__body';

    if (state.section === 'all' && !isSearchMode()) {
      var sub = document.createElement('div');
      sub.className = 'card__sub';
      var secName = SECTION_LABELS[p.section] || '';
      sub.textContent = p.subCategory;
      sub.title = secName + ' · ' + p.subCategory;
      body.appendChild(sub);
    } else if (isSearchMode()) {
      var sub2 = document.createElement('div');
      sub2.className = 'card__sub';
      sub2.textContent = p.subCategory;
      sub2.title = (SECTION_LABELS[p.section] || '') + ' · ' + p.subCategory;
      body.appendChild(sub2);
    }

    var nameLink = document.createElement('a');
    nameLink.className = 'card__name';
    nameLink.href = p.productUrl;
    nameLink.target = '_blank';
    nameLink.rel = 'noopener noreferrer sponsored';
    nameLink.textContent = p.productName;
    nameLink.title = p.productName;
    body.appendChild(nameLink);

    var more = document.createElement('button');
    more.type = 'button';
    more.className = 'card__more';
    more.textContent = '전체 보기';
    more.hidden = true;
    more.addEventListener('click', function () {
      var open = card.classList.toggle('is-open');
      more.textContent = open ? '접기' : '전체 보기';
    });
    body.appendChild(more);

    if (p.unitHint) {
      var unit = document.createElement('div');
      unit.className = 'card__unit';
      unit.textContent = p.unitHint;
      unit.title = '상품명에서 읽은 용량·수량 표기';
      body.appendChild(unit);
    }

    var price = document.createElement('div');
    price.className = 'card__price';
    if (p.productPrice === null || p.productPrice === undefined) {
      price.textContent = '가격 확인';
      price.style.fontSize = '15px';
    } else {
      price.appendChild(document.createTextNode(wonFormatter.format(p.productPrice)));
      var won = document.createElement('span');
      won.textContent = '원';
      price.appendChild(won);
    }
    body.appendChild(price);

    var cta = document.createElement('a');
    cta.className = 'card__cta';
    cta.href = p.productUrl;
    cta.target = '_blank';
    cta.rel = 'noopener noreferrer sponsored';
    cta.appendChild(document.createTextNode('최저가 구매하기 '));
    var arrow = document.createElement('span');
    arrow.textContent = '→';
    cta.appendChild(arrow);
    body.appendChild(cta);

    card.appendChild(thumb);
    card.appendChild(body);

    // 상품명이 2줄을 넘으면 '전체 보기' 버튼 노출
    requestAnimationFrame(function () {
      if (card.querySelector('.card__name').scrollHeight > 40) more.hidden = false;
    });

    return card;
  }

  /* ---------------- 렌더링 ---------------- */

  function render() {
    el.skeleton.hidden = true;

    var list = filtered();
    var visible = list.slice(0, state.shown);

    el.grid.innerHTML = '';
    var frag = document.createDocumentFragment();
    visible.forEach(function (p, i) { frag.appendChild(makeCard(p, i)); });
    el.grid.appendChild(frag);

    // 결과 요약
    el.resultCount.innerHTML = '';
    if (isSearchMode()) {
      el.resultCount.appendChild(document.createTextNode('‘' + state.query.trim() + '’ 검색 결과 '));
      var b = document.createElement('b');
      b.textContent = wonFormatter.format(list.length);
      el.resultCount.appendChild(b);
      el.resultCount.appendChild(document.createTextNode('개'));
    } else {
      el.resultCount.appendChild(document.createTextNode('총 '));
      var b2 = document.createElement('b');
      b2.textContent = wonFormatter.format(list.length);
      el.resultCount.appendChild(b2);
      el.resultCount.appendChild(document.createTextNode('개 상품'));
    }

    var hints = [];
    if (state.section !== 'all') hints.push(SECTION_LABELS[state.section] || '');
    if (state.sub !== 'all') hints.push(state.sub);
    if (isSearchMode()) hints.push('검색');
    if (state.rocketOnly) hints.push('로켓배송');
    if (state.freeOnly) hints.push('무료배송');
    if (state.sort === 'price-asc') hints.push('낮은 가격순');
    if (state.sort === 'price-desc') hints.push('높은 가격순');
    el.resultHint.textContent = hints.filter(Boolean).join(' · ');

    el.empty.hidden = list.length !== 0;
    if (!list.length) {
      el.emptyTitle.textContent = '조건에 맞는 상품이 없습니다';
      var elsewhere = isSearchMode() ? ALL.filter(passesBase).length : 0;
      el.emptyDesc.textContent = elsewhere
        ? '다른 섹션에는 ' + wonFormatter.format(elsewhere) + '개 있습니다. 위쪽 ‘전체’ 탭에서 확인해 보세요.'
        : '검색어를 바꾸거나 필터를 초기화해 보세요.';
    }

    var remain = list.length - visible.length;
    el.moreBtn.hidden = remain <= 0;
    if (remain > 0) el.moreBtn.textContent = '상품 더 보기 (' + wonFormatter.format(remain) + ')';
  }

  /* ---------------- 이벤트 ---------------- */

  el.tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      state.section = tab.getAttribute('data-section');
      state.sub = 'all';
      state.shown = PAGE_SIZE;
      el.tabs.forEach(function (t) {
        var on = t === tab;
        t.classList.toggle('is-active', on);
        t.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      buildChips();
      render();
    });
  });

  var searchTimer = null;
  el.search.addEventListener('input', function () {
    var value = el.search.value;
    el.searchClear.hidden = value.length === 0;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      state.query = value;
      state.shown = PAGE_SIZE;
      buildChips();
      render();
    }, 140);
  });

  el.searchForm.addEventListener('submit', function (e) {
    e.preventDefault();
    state.query = el.search.value;
    state.shown = PAGE_SIZE;
    buildChips();
    render();
  });

  el.searchClear.addEventListener('click', function () {
    el.search.value = '';
    el.searchClear.hidden = true;
    state.query = '';
    state.shown = PAGE_SIZE;
    buildChips();
    render();
    el.search.focus();
  });

  el.rocket.addEventListener('change', function () {
    state.rocketOnly = el.rocket.checked;
    state.shown = PAGE_SIZE;
    buildChips();
    render();
  });

  el.free.addEventListener('change', function () {
    state.freeOnly = el.free.checked;
    state.shown = PAGE_SIZE;
    buildChips();
    render();
  });

  el.sort.addEventListener('change', function () {
    state.sort = el.sort.value;
    state.shown = PAGE_SIZE;
    render();
  });

  el.moreBtn.addEventListener('click', function () {
    state.shown += PAGE_SIZE;
    render();
  });

  el.resetBtn.addEventListener('click', function () {
    state.query = '';
    state.sub = 'all';
    state.rocketOnly = false;
    state.freeOnly = false;
    state.sort = 'recommended';
    state.shown = PAGE_SIZE;
    el.search.value = '';
    el.searchClear.hidden = true;
    el.rocket.checked = false;
    el.free.checked = false;
    el.sort.value = 'recommended';
    el.tabs.forEach(function (t) {
      var on = t.getAttribute('data-section') === state.section;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    buildChips();
    render();
  });

  load();
})();
