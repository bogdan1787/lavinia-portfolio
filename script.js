/**
 * script.js — Portfolio gallery logic
 */

// ── Constants ────────────────────────────────────────────────────────────────

const BATCH_SIZE = 24;  // images rendered per scroll batch

// ── Theme ─────────────────────────────────────────────────────────────────────

const THEME_KEY = 'lgfe-theme';

const ICON_SUN  = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;
const ICON_MOON = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  themeToggle.innerHTML = theme === 'dark' ? ICON_SUN : ICON_MOON;
  themeToggle.title     = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
}

// ── State ────────────────────────────────────────────────────────────────────

let allImages      = [];   // full flat list with all metadata
let filteredImages = [];   // full current-view list (used by lightbox)
let renderQueue    = [];   // [{type:'heading'|'image', ...}] for current view
let renderedCount  = 0;    // how many renderQueue items are in the DOM
let scrollObserver = null;
let lightboxIndex  = 0;
let currentCategories = [];

// ── DOM refs ──────────────────────────────────────────────────────────────────

const gallery      = document.getElementById('gallery');
const catNavInner  = document.querySelector('.cat-nav-inner');
const catNavScroll = document.getElementById('catNavScroll');
const navScrollLeft  = document.getElementById('navScrollLeft');
const navScrollRight = document.getElementById('navScrollRight');
const themeToggle  = document.getElementById('themeToggle');
const emptyState   = document.getElementById('emptyState');
const lightbox     = document.getElementById('lightbox');
const lbImg        = document.getElementById('lbImg');
const lbVideo      = document.getElementById('lbVideo');
const lbCaption    = document.getElementById('lbCaption');
const lbClose      = document.getElementById('lbClose');
const lbPrev       = document.getElementById('lbPrev');
const lbNext       = document.getElementById('lbNext');
const sentinel     = document.getElementById('scroll-sentinel');

// ── Theme init ────────────────────────────────────────────────────────────────

applyTheme(localStorage.getItem(THEME_KEY) || 'dark');

themeToggle.addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
});

// ── Nav scroll hints ──────────────────────────────────────────────────────────

function updateNavScroll() {
  const el      = catNavInner;
  const atLeft  = el.scrollLeft <= 1;
  const atRight = el.scrollLeft + el.clientWidth >= el.scrollWidth - 1;
  navScrollLeft.classList.toggle('hidden',  atLeft);
  navScrollRight.classList.toggle('hidden', atRight);
  catNavScroll.classList.toggle('can-scroll-left',  !atLeft);
  catNavScroll.classList.toggle('can-scroll-right', !atRight);
}

navScrollLeft.addEventListener('click',  () => catNavInner.scrollBy({ left: -150, behavior: 'smooth' }));
navScrollRight.addEventListener('click', () => catNavInner.scrollBy({ left:  150, behavior: 'smooth' }));
catNavInner.addEventListener('scroll', updateNavScroll, { passive: true });
window.addEventListener('resize',       updateNavScroll, { passive: true });

// ── Gallery height estimation (reduces footer CLS) ───────────────────────────
// Uses manifest w/h to simulate CSS column layout before any image renders,
// so the footer stays anchored while lazy images load in.

function estimateGalleryHeight(categories) {
  const GAP  = 10;   // --gap: 10px
  const vw   = window.innerWidth;
  const cols = vw <= 600 ? 2 : 3;
  // Column width = (gallery width − horizontal padding − column gaps) / cols
  const colW = Math.max(160,
    ((gallery.clientWidth || vw) - GAP * 4 - GAP * (cols - 1)) / cols);

  let total = 0;
  for (const cat of categories) {
    if (!cat.images.length) continue;
    total += 44 + GAP;   // category heading + margin
    for (const img of cat.images) {
      const ratio = (img.w && img.h) ? img.w / img.h : 1;
      total += colW / ratio + GAP;   // rendered height + margin-bottom
    }
  }
  // CSS columns balances height across columns; add gallery vertical padding
  return Math.round(total / cols) + GAP * 2;
}

// ── Load manifest ─────────────────────────────────────────────────────────────

async function loadManifest() {
  try {
    const res = await fetch('image-manifest.json', { cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const manifest = await res.json();
    return manifest.categories || [];
  } catch (err) {
    console.warn('Failed to load image manifest:', err);
    gallery.innerHTML = (
      '<div class="empty-state"><div class="empty-inner">' +
      '<h2>Unable to load gallery</h2>' +
      '<p>Please check your connection and refresh the page.</p>' +
      '</div></div>'
    );
    return [];
  }
}

// ── Build gallery ─────────────────────────────────────────────────────────────

function buildGallery(categories) {
  if (!categories.length || !categories.some(c => c.images.length)) {
    emptyState.classList.remove('hidden');
    document.getElementById('catNav').classList.add('hidden');
    return;
  }

  // Flatten all images with full metadata
  allImages = [];
  categories.forEach(cat => {
    cat.images.forEach(img => {
      allImages.push({
        file        : img.file,
        thumb       : img.thumb || img.file,  // fallback to full if no thumb yet
        avif        : img.avif || null,
        alt         : img.alt,
        w           : img.w   || null,
        h           : img.h   || null,
        added       : img.added || null,
        animated    : img.animated || false,
        video       : img.video    || false,
        category    : cat.slug,
        categoryName: cat.name,
      });
    });
  });

  // Inject category nav buttons
  categories.forEach(cat => {
    const btn = document.createElement('button');
    btn.className = 'cat-btn';
    btn.dataset.slug = cat.slug;
    btn.textContent = cat.name;
    catNavInner.appendChild(btn);
  });

  showCategory('all', categories);

  // Initialise nav scroll hints + pulse the right arrow once if overflow exists
  requestAnimationFrame(() => {
    updateNavScroll();
    if (!navScrollRight.classList.contains('hidden')) {
      navScrollRight.classList.add('hint');
      navScrollRight.addEventListener('animationend', () => navScrollRight.classList.remove('hint'), { once: true });
    }
  });
}

// ── Render queue + infinite scroll ───────────────────────────────────────────

function buildRenderQueue(slug, categories) {
  filteredImages = [];
  renderQueue    = [];

  if (slug === 'all') {
    categories.forEach(cat => {
      if (!cat.images.length) return;
      renderQueue.push({ type: 'heading', name: cat.name });
      cat.images.forEach(img => {
        const idx  = filteredImages.length;
        const item = {
          file: img.file, thumb: img.thumb || img.file, avif: img.avif || null,
          alt: img.alt, w: img.w || null, h: img.h || null,
          added: img.added || null, animated: img.animated || false,
          video: img.video || false,
          category: cat.slug, categoryName: cat.name,
        };
        filteredImages.push(item);
        renderQueue.push({ type: 'image', img: item, idx });
      });
    });
  } else {
    filteredImages = allImages.filter(img => img.category === slug);
    filteredImages.forEach((img, idx) => renderQueue.push({ type: 'image', img, idx }));
  }
}

function renderNextBatch() {
  const start = renderedCount;
  const end   = Math.min(start + BATCH_SIZE, renderQueue.length);

  for (let i = start; i < end; i++) {
    const item     = renderQueue[i];
    const batchPos = i - start;
    if (item.type === 'heading') {
      const h = document.createElement('div');
      h.className = 'category-heading';
      h.innerHTML = `<h2>${item.name}</h2>`;
      gallery.appendChild(h);
    } else {
      gallery.appendChild(makeItem(item.img, item.idx, batchPos));
    }
  }
  renderedCount = end;

  // Show/hide sentinel and (re)connect observer
  if (renderedCount < renderQueue.length) {
    sentinel.classList.remove('hidden');
    if (!scrollObserver) {
      scrollObserver = new IntersectionObserver(
        entries => { if (entries[0].isIntersecting) renderNextBatch(); },
        { rootMargin: '300px' }
      );
      scrollObserver.observe(sentinel);
    }
  } else {
    sentinel.classList.add('hidden');
    if (scrollObserver) { scrollObserver.disconnect(); scrollObserver = null; }
    gallery.style.minHeight = '';   // actual content fills the space now
  }
}

function showCategory(slug, categories) {
  gallery.innerHTML = '';
  renderedCount = 0;
  if (scrollObserver) { scrollObserver.disconnect(); scrollObserver = null; }
  buildRenderQueue(slug, categories);
  renderNextBatch();
}

function makeItem(img, idx, batchPos = 0) {
  const div = document.createElement('div');
  div.className = 'gallery-item';
  div.setAttribute('role', 'button');
  div.setAttribute('tabindex', '0');
  div.setAttribute('aria-label', img.alt || img.file);
  div.dataset.index = idx;
  div.style.animationDelay = `${Math.min(batchPos, 12) * 0.04}s`;

  let image;
  if (img.avif) {
    const picture = document.createElement('picture');
    const source  = document.createElement('source');
    source.srcset = img.avif;
    source.type   = 'image/avif';
    picture.appendChild(source);
    image = document.createElement('img');
    image.src = img.thumb;   // fallback for non-AVIF browsers
    picture.appendChild(image);
    div.appendChild(picture);
  } else {
    image = document.createElement('img');
    image.src = img.thumb;
    div.appendChild(image);
  }

  image.alt       = img.alt || '';
  image.loading   = 'lazy';
  image.decoding  = 'async';
  image.draggable = false;
  // Pre-reserve exact space → prevents layout shift (CLS)
  if (img.w && img.h) image.style.aspectRatio = `${img.w} / ${img.h}`;

  const caption = document.createElement('span');
  caption.className = 'item-caption';
  caption.textContent = img.alt;

  div.appendChild(caption);

  // "New" badge — shown for 30 days after first upload
  if (img.added) {
    const age = (Date.now() - new Date(img.added).getTime()) / 86400000;
    if (age < 30) {
      const badge = document.createElement('span');
      badge.className = 'badge-new';
      badge.textContent = 'New';
      div.appendChild(badge);
    }
  }

  // Video badge (▶ in accent colour) — mutually exclusive with animated badge
  if (img.video) {
    const badge = document.createElement('span');
    badge.className = 'badge-video';
    badge.textContent = '▶';
    div.appendChild(badge);
  } else if (img.animated) {
    const badge = document.createElement('span');
    badge.className = 'badge-anim';
    badge.textContent = '▶';
    div.appendChild(badge);
  }

  div.addEventListener('click', () => openLightbox(idx));
  div.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') openLightbox(idx); });

  return div;
}

// ── Category filter ───────────────────────────────────────────────────────────

catNavInner.addEventListener('click', e => {
  const btn = e.target.closest('.cat-btn');
  if (!btn) return;
  catNavInner.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  showCategory(btn.dataset.slug, currentCategories);
});

// ── Lightbox ──────────────────────────────────────────────────────────────────

function openLightbox(index) {
  lightboxIndex = index;
  renderLightbox();
  lightbox.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  lbClose.focus();
}

function closeLightbox() {
  lightbox.classList.add('hidden');
  document.body.style.overflow = '';
  if (!lbVideo.classList.contains('hidden')) {
    lbVideo.pause();
    lbVideo.removeAttribute('src');
    lbVideo.load();
    lbVideo.classList.add('hidden');
  }
}

function renderLightbox() {
  const img = filteredImages[lightboxIndex];

  if (img.video) {
    lbImg.classList.add('hidden');
    lbVideo.classList.remove('hidden');
    lbVideo.src = img.file;
    const p = lbVideo.play();
    if (p) p.catch(() => {});
    // Reset entry animation
    lbVideo.style.animation = 'none';
    lbVideo.offsetHeight;
    lbVideo.style.animation = '';
  } else {
    // Stop video if switching away from one
    if (!lbVideo.classList.contains('hidden')) {
      lbVideo.pause();
      lbVideo.removeAttribute('src');
      lbVideo.load();
      lbVideo.classList.add('hidden');
    }
    lbImg.classList.remove('hidden');
    // Use AVIF in lightbox if available, else original file
    if (img.avif) {
      lbImg.src = img.avif;
    } else {
      lbImg.src = img.file;
    }
    lbImg.alt = img.alt;
    lbImg.style.animation = 'none';
    lbImg.offsetHeight;
    lbImg.style.animation = '';
  }

  lbCaption.textContent = img.alt
    ? `${img.alt}  ·  ${img.categoryName}`
    : img.categoryName;

  lbPrev.style.visibility = lightboxIndex > 0                         ? 'visible' : 'hidden';
  lbNext.style.visibility = lightboxIndex < filteredImages.length - 1 ? 'visible' : 'hidden';
}

function stepLightbox(dir) {
  const next = lightboxIndex + dir;
  if (next >= 0 && next < filteredImages.length) {
    lightboxIndex = next;
    renderLightbox();
  }
}

lbClose.addEventListener('click', closeLightbox);
lbPrev.addEventListener('click',  () => stepLightbox(-1));
lbNext.addEventListener('click',  () => stepLightbox(+1));

lightbox.addEventListener('click', e => { if (e.target === lightbox) closeLightbox(); });

document.addEventListener('keydown', e => {
  if (lightbox.classList.contains('hidden')) return;
  if (e.key === 'Escape')     closeLightbox();
  // Don't navigate with arrows when the video element has focus (user may be seeking)
  if (document.activeElement === lbVideo) return;
  if (e.key === 'ArrowLeft')  stepLightbox(-1);
  if (e.key === 'ArrowRight') stepLightbox(+1);
});

let touchStartX = 0;
lightbox.addEventListener('touchstart', e => { touchStartX = e.touches[0].clientX; }, { passive: true });
lightbox.addEventListener('touchend',   e => {
  // Don't navigate when swiping on the video player (may be seeking)
  if (lbVideo.contains(e.target)) return;
  const dx = e.changedTouches[0].clientX - touchStartX;
  if (Math.abs(dx) > 50) stepLightbox(dx < 0 ? +1 : -1);
});

// ── Image protection ─────────────────────────────────────────────────────────

document.addEventListener('contextmenu', e => { if (e.target.tagName === 'IMG') e.preventDefault(); });
document.addEventListener('dragstart',   e => { if (e.target.tagName === 'IMG') e.preventDefault(); });

// ── Init ──────────────────────────────────────────────────────────────────────

(async () => {
  const categories  = await loadManifest();
  currentCategories = categories;
  // Reserve estimated gallery space before any image renders → keeps footer anchored
  if (categories.some(c => c.images.length)) {
    gallery.style.minHeight = estimateGalleryHeight(categories) + 'px';
  }
  buildGallery(categories);
})();

