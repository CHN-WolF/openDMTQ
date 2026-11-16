// What can be measured about the room between things on a page, run inside the page beside layout.js. Used by audit.js.
// Returns a list of findings:
//   touching      two boxes, or a box and a line of text beside it, with no room between them, or on top of each other
//   edge-touch    a box inside another box against that box's inner edge
//   tight-padding text nearer to the edge of the box it is in than that box's padding, or with no room at a drawn edge
//   uneven-gaps   boxes side by side, or one under another, in one row or column, with gaps of different sizes
//   off-scale     a gap between two panels other than the page's own gap (--gap), or a gap no stylesheet asked for
//                 (the spaces between words that inline boxes keep, a stray line)
// A box is what a person sees as one: something with a background of its own, a border all round, an outer shadow, a
// picture, or a drawn control. Marks on an element: data-spacing-ok says why its room is as it is; decoration
// (aria-hidden) does not count.
window.spacingAudit = function spacingAudit() {
  const out = [];
  const say = (kind, el, detail) => out.push({ kind, at: describe(el), detail });
  // An element as the findings name it: its tag, its first two classes, its id.
  function describe(el) {
    if (!el || !el.tagName) return 'page';
    const cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.');
    return el.tagName.toLowerCase() + (cls ? '.' + cls : '') + (el.id ? '#' + el.id : '');
  }
  // How a pair is named: both ends, so that one finding says which two things meet.
  const pair = (a, b) => `${describe(a)} / ${describe(b)}`;
  const px = v => parseFloat(v) || 0;
  const round = v => Math.round(v * 10) / 10;
  // Drawn and on the page: not hidden, not see-through, not folded away in a closed <details>, with a size.
  const seen = el => {
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) return false;
    if (el.closest('details:not([open])') && !el.closest('summary')) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  // Not drawn for reading, or laid out as it is on purpose: the hidden page title, the wordmark, a chart's tip, and
  // whatever is marked so.
  const decoration = el => !!el.closest('[aria-hidden="true"], .chart-tip, script, style, option, .page-title, .logo, [data-spacing-ok]');

  // A colour as numbers; null when there is none to read.
  const parse = c => { const m = /rgba?\(([^)]+)\)/.exec(c || ''); if (!m) return null; const v = m[1].split(/[ ,/]+/).map(Number); return { r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1 }; };
  // The sides of a box that a border is drawn on (at least a pixel wide and not see-through).
  const borderSides = s => ['Top', 'Right', 'Bottom', 'Left'].filter(k => px(s[`border${k}Width`]) >= 1 && !['none', 'hidden'].includes(s[`border${k}Style`]) && (parse(s[`border${k}Color`]) || { a: 0 }).a > 0.15);
  // An outer shadow (not one drawn inside the box, as the glass's rim is): it shows the box's outline too.
  const outerShadow = s => s.boxShadow !== 'none' && s.boxShadow.split(/,(?![^(]*\))/).some(x => !/inset/.test(x) && !/^\s*rgba?\([^)]*,\s*0\)/.test(x));
  const MEDIA = 'img, video, canvas, svg, picture, iframe';
  const CONTROL = 'button, input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea';
  const ALL = ['Top', 'Right', 'Bottom', 'Left'];
  // What a person sees as a box, and which of its edges are drawn: null for what is not one.
  const boxCache = new Map();
  const boxOf = el => {
    if (!el || el === document.body || el === document.documentElement) return null;
    if (boxCache.has(el)) return boxCache.get(el);
    let found = null;
    const s = getComputedStyle(el);
    // Laid out as one box: a run of inline text is a line of text, whose marks are words, not boxes.
    if (s.display !== 'inline' && s.display !== 'contents' && seen(el) && !decoration(el) && !(el.closest('svg') && !el.matches('svg'))) {
      const bg = parse(s.backgroundColor);
      // A fill painted only inside the letters (the leading place's gradient) is the text's colour, not a box.
      const inLetters = s.webkitBackgroundClip === 'text' || s.backgroundClip === 'text';
      const filled = !inLetters && ((bg && bg.a > 0.06) || s.backgroundImage !== 'none');
      const sides = borderSides(s);
      // A picture, also one a box paints as its background or holds with no words (a jacket's frame): it may run to its
      // box's edge.
      if (el.matches(MEDIA) || (!inLetters && /url\(/.test(s.backgroundImage)) || (el.querySelector(MEDIA) && !el.textContent.trim() && !el.querySelector(CONTROL))) found = { kind: 'media', sides: ALL };
      else if (el.matches(CONTROL) && (filled || sides.length)) found = { kind: 'control', sides: filled ? ALL : sides };
      else if (filled || sides.length === 4 || outerShadow(s)) found = { kind: 'box', sides: ALL };
    }
    boxCache.set(el, found);
    return found;
  };
  // The box something is drawn on: the nearest box around it (itself first when asked), or null for the page.
  const holder = (el, self = false) => { for (let a = self ? el : el.parentElement; a && a !== document.body; a = a.parentElement) if (boxOf(a)) return a; return null; };
  // A box's edges inside its border: where its own room for what it holds begins.
  const inner = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return { left: r.left + px(s.borderLeftWidth), right: r.right - px(s.borderRightWidth), top: r.top + px(s.borderTopWidth), bottom: r.bottom - px(s.borderBottomWidth) }; };
  // The layer something is laid out in: the nearest element around it (itself first) placed over the page (absolutely,
  // fixed, sticky, or a dialog in the browser's top layer), or the page's own flow (null). Things in different layers are
  // placed against each other by design: a badge on a picture, a menu over a card, the bar over the page as it scrolls.
  const layerCache = new Map();
  const layerOf = el => {
    if (!el) return null;
    if (layerCache.has(el)) return layerCache.get(el);
    let found = null;
    for (let a = el; a && a !== document.body; a = a.parentElement) {
      const p = getComputedStyle(a).position;
      if (p === 'absolute' || p === 'fixed' || p === 'sticky' || a.matches('dialog[open]')) { found = a; break; }
    }
    layerCache.set(el, found);
    return found;
  };
  // Joined on purpose: the cells of a table, a segmented control's buttons, the tabs on their rule, the language switch's
  // two halves, a menu's or a list's rows with a line between them. Short, and each one a look the game itself has.
  // A gauge's fill runs from its track's edge, and a strip's or a calendar's cells stand a hair apart: they are drawings.
  const JOINED = 'td, th, tr, thead, tbody, tfoot, caption, .seg > *, .tabs > *, .tabbar > *, .lang-switch > *, [role=tablist] > *, [role=menu] > *, [role=listbox] > *, .meter > *, .tile-meter > *, .strip > *, .daycells > *';
  // A drawing's parts: a box with no words and nothing to press in a box with none either (a gauge's track and its fill,
  // a stacked bar's segments) is drawn as one figure.
  const wordless = el => !el.textContent.trim() && !el.querySelector(CONTROL) && !el.matches(CONTROL);
  const joined = el => el.matches(JOINED) || (wordless(el) && !!el.parentElement && wordless(el.parentElement));

  // The room between two rectangles across each axis: negative when they overlap along it.
  const apart = (a, b) => ({ x: Math.max(a.left, b.left) - Math.min(a.right, b.right), y: Math.max(a.top, b.top) - Math.min(a.bottom, b.bottom) });
  // Whole in view of every box around it that cuts off or scrolls what passes its edge, up to the box it is in (that one
  // too): what a scrolling list holds past its edge is reached by scrolling, not set against anything.
  const clips = el => { const s = getComputedStyle(el); return s.overflowX !== 'visible' || s.overflowY !== 'visible'; };
  const inView = (el, r, stop) => {
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      if (clips(a)) {
        const v = a.getBoundingClientRect();
        if (r.left < v.left - 1 || r.right > v.right + 1 || r.top < v.top - 1 || r.bottom > v.bottom + 1) return false;
      }
      if (a === stop) break;
    }
    return true;
  };
  // Every box on the page, with its place, the box it sits in and its layer.
  const boxes = [];
  for (const el of document.body.querySelectorAll('*')) {
    const kind = boxOf(el);
    if (!kind) continue;
    const r = el.getBoundingClientRect(), parent = holder(el);
    // Only what is whole in view: what a scrolling box holds past its edge is not set against anything now.
    if (!inView(el, r, parent)) continue;
    boxes.push({ el, kind: kind.kind, sides: kind.sides, r, parent, layer: layerOf(el) });
  }
  const byParent = new Map();
  for (const b of boxes) byParent.set(b.parent, [...(byParent.get(b.parent) || []), b]);

  // Two boxes in one box (or both on the page) and one layer, neither inside the other, with no room between them where
  // they face each other, or on top of each other.
  for (const [, kids] of byParent) {
    for (let i = 0; i < kids.length; i++) {
      for (let j = i + 1; j < kids.length; j++) {
        const a = kids[i], b = kids[j];
        if (a.el.contains(b.el) || b.el.contains(a.el) || a.layer !== b.layer) continue;
        if (joined(a.el) && joined(b.el)) continue;
        const d = apart(a.r, b.r);
        // Facing each other across one axis: they share more than a few pixels along the other.
        const facesX = d.y < -2, facesY = d.x < -2;
        if ((facesX && d.x < 1.5) || (facesY && d.y < 1.5)) {
          const room = facesX && facesY ? 'on top of each other' : `${round(facesX ? d.x : d.y)}px apart`;
          say('touching', a.el, `${pair(a.el, b.el)}: ${room}`);
        }
      }
    }
  }

  // A box inside a box, against its inner edge: no room left between the two outlines. Pictures may run to the edge (a
  // full-bleed jacket); what floats in the box is placed there on purpose (a badge in a corner).
  for (const b of boxes) {
    if (!b.parent || b.kind === 'media' || joined(b.el) || b.layer !== layerOf(b.parent)) continue;
    const p = boxOf(b.parent);
    const r = inner(b.parent);
    const gaps = { Left: b.r.left - r.left, Right: r.right - b.r.right, Top: b.r.top - r.top, Bottom: r.bottom - b.r.bottom };
    // What runs past a box that scrolls is reached by scrolling: not against its edge.
    const ps = getComputedStyle(b.parent);
    const scrolls = ['auto', 'scroll'].includes(ps.overflowX) || ['auto', 'scroll'].includes(ps.overflowY);
    const against = Object.entries(gaps).filter(([side, g]) => g < 1.5 && !(scrolls && g < -1) && p.sides.includes(side));
    if (against.length) say('edge-touch', b.el, `in ${describe(b.parent)}: ${against.map(([side, g]) => `${side.toLowerCase()} ${round(g)}px`).join(', ')}`);
  }

  // Text and the box it is in: where its letters are, against the box's edges and padding, and the boxes beside it.
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  const tight = new Map();
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if (!n.nodeValue.trim()) continue;
    const el = n.parentElement;
    if (!el || decoration(el) || !seen(el) || el.closest('svg')) continue;
    // The words without the spaces around them: a space before the next box is room, not letters.
    const v = n.nodeValue, first = v.search(/\S/), last = v.length - v.match(/\s*$/)[0].length;
    range.setStart(n, first);
    range.setEnd(n, last);
    const lines = [...range.getClientRects()].filter(r => r.width > 0.5 && r.height > 0.5);
    if (!lines.length) continue;
    const s = getComputedStyle(el);
    // Where the letters are: a line's rectangle is the font's whole height; about this much of the font size is letters, in
    // its middle (as layout.js reads them). Korean syllables stand a little taller.
    const size = px(s.fontSize), letters = (/[ㄱ-힣]/.test(n.nodeValue) ? 0.86 : 0.76) * size;
    const ink = lines.map(r => ({ left: r.left, right: r.right, top: (r.top + r.bottom) / 2 - letters / 2, bottom: (r.top + r.bottom) / 2 + letters / 2 }));
    const own = holder(el, true);
    // Only text whole in view: lines scrolled past a list's edge are reached by scrolling.
    const inkBox = { left: Math.min(...ink.map(r => r.left)), right: Math.max(...ink.map(r => r.right)), top: Math.min(...ink.map(r => r.top)), bottom: Math.max(...ink.map(r => r.bottom)) };
    if (!inView(el, inkBox, own)) continue;
    // The text is placed in its box by the flow of the box, not laid over it.
    const sameLayer = layerOf(el) === layerOf(own);
    if (own && sameLayer) {
      // Scrolled out of its box's view: not on the page now, and reached by scrolling.
      const os = getComputedStyle(own);
      const scrolls = ['auto', 'scroll'].includes(os.overflowX) || ['auto', 'scroll'].includes(os.overflowY);
      const r = inner(own);
      const pad = { Left: px(os.paddingLeft), Right: px(os.paddingRight), Top: px(os.paddingTop), Bottom: px(os.paddingBottom) };
      const drawn = boxOf(own).sides;
      // The nearest the letters come to each edge, over all of this text's lines.
      const near = {
        Left: Math.min(...ink.map(x => x.left - r.left)), Right: Math.min(...ink.map(x => r.right - x.right)),
        Top: Math.min(...ink.map(x => x.top - r.top)), Bottom: Math.min(...ink.map(x => r.bottom - x.bottom)),
      };
      // Cut off on purpose by its box (an ellipsis, a clamp): layout.js says so when it should not be.
      const cuts = [os.overflowX, os.overflowY, s.overflowX, s.overflowY].some(v => v === 'hidden' || v === 'clip');
      for (const side of ALL) {
        const g = near[side];
        if ((scrolls || cuts) && g < 0) continue;
        // Into the padding, past what a line's own leading explains (a little more across the lines' height).
        const into = pad[side] - g > (side === 'Top' || side === 'Bottom' ? 3 : 2);
        // At a drawn edge with no room at all: the letters on the border, or on the fill's edge.
        const flush = drawn.includes(side) && g < 3;
        if (into || flush) {
          const key = `${describe(own)} ${side}`;
          const t = tight.get(key);
          if (!t || g < t.g) tight.set(key, { el: own, side, g, pad: pad[side], text: n.nodeValue.trim().slice(0, 30) });
        }
      }
    }
    // A line of text beside a box in the same box and layer, with no room between them: a heading on a table's border, a
    // note on a field. Only the boxes that do not hold it, and not the words of what is pressed (a button's own words).
    if (el.closest('.btn, .button, button, label, summary') || !sameLayer && own) continue;
    // The letters, not the font's whole height: a tall face's line box may reach past its own element without anything
    // showing there.
    for (const b of byParent.get(own) || []) {
      if (b.el.contains(el) || joined(b.el) || b.layer !== layerOf(el)) continue;
      const d = apart(inkBox, b.r);
      const facesX = d.y < -2, facesY = d.x < -2;
      if ((facesX && d.x < 2 && d.x > -1) || (facesY && d.y < 2 && d.y > -1)) say('touching', el, `"${n.nodeValue.trim().slice(0, 30)}" / ${describe(b.el)}: ${round(facesX ? d.x : d.y)}px apart`);
    }
  }
  for (const t of tight.values()) say('tight-padding', t.el, `${t.side.toLowerCase()}: "${t.text}" ${round(t.g)}px from the edge, padding ${round(t.pad)}px`);
  // Fields: their words are drawn by the browser, inside the padding the stylesheet gives them.
  for (const el of document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=range]):not([type=file]), select, textarea')) {
    if (!boxOf(el)) continue;
    const s = getComputedStyle(el);
    const least = Math.min(px(s.paddingLeft), px(s.paddingRight));
    if (least < 6) say('tight-padding', el, `a field's words ${round(least)}px from its edge`);
  }

  // Gaps between boxes that stand together: in one row or one column of a box, each gap the same, and between panels the
  // page's own gap. The scale is the page's: --gap, as the stylesheet sets it for this width (read where the boxes are).
  // The boxes that stand together: every element's own children that are boxes, in the markup's order.
  const groups = new Map();
  for (const b of boxes) {
    const p = b.el.parentElement;
    if (!p || joined(b.el) || b.layer !== layerOf(p) && b.layer === b.el) continue;
    groups.set(p, [...(groups.get(p) || []), b]);
  }
  // A margin set to auto: it pushes its box to the far end on purpose, and the gap beside it is whatever is left.
  const autoMargin = (el, side) => { try { return String(el.computedStyleMap().get(`margin-${side}`)) === 'auto'; } catch (_) { return false; } };
  for (const [parent, kids] of groups) {
    if (kids.length < 2) continue;
    const ps = getComputedStyle(parent);
    const pageGap = px(ps.getPropertyValue('--gap'));
    // Spread out on purpose: the free room goes between them.
    const spread = /space-(between|around|evenly)/.test(ps.justifyContent) || /space-(between|around|evenly)/.test(ps.alignContent);
    const flex = ps.display.includes('flex'), grid = ps.display.includes('grid');
    const across = [], down = [];
    // Something drawn in the room between two boxes (a heading, a line of text, a box of another layer) makes its own
    // room: the two are not neighbours.
    const children = [...parent.childNodes];
    const drawnIn = (room, a, b) => children.some(x => {
      if (x === a.el || x === b.el) return false;
      let rects = [];
      if (x.nodeType === Node.TEXT_NODE && x.nodeValue.trim()) { range.selectNodeContents(x); rects = [...range.getClientRects()]; }
      else if (x.nodeType === Node.ELEMENT_NODE && seen(x)) rects = [x.getBoundingClientRect()];
      return rects.some(r => Math.min(r.right, room.right) - Math.max(r.left, room.left) > 1 && Math.min(r.bottom, room.bottom) - Math.max(r.top, room.top) > 1);
    });
    // Each box with its nearest neighbour to the right (on its line) and below (in its column), wherever the markup has
    // them: a podium's places, put in order by the stylesheet, stand side by side in another order than the markup's.
    for (const a of kids) {
      let right = null, below = null;
      for (const b of kids) {
        if (b === a) continue;
        const d = apart(a.r, b.r);
        if (d.y < -2 && b.r.left >= a.r.right - 1 && (!right || b.r.left < right.r.left)) right = b;
        if (d.x < -2 && b.r.top >= a.r.bottom - 1 && (!below || b.r.top < below.r.top)) below = b;
      }
      const sa = getComputedStyle(a.el);
      if (right && !autoMargin(a.el, 'right') && !autoMargin(right.el, 'left')) {
        const room = { left: a.r.right, right: right.r.left, top: Math.max(a.r.top, right.r.top), bottom: Math.min(a.r.bottom, right.r.bottom) };
        if (!drawnIn(room, a, right)) across.push({ a, b: right, gap: right.r.left - a.r.right, want: (flex || grid ? px(ps.columnGap) : 0) + px(sa.marginRight) + px(getComputedStyle(right.el).marginLeft) });
      }
      if (below && !autoMargin(a.el, 'bottom') && !autoMargin(below.el, 'top')) {
        const room = { top: a.r.bottom, bottom: below.r.top, left: Math.max(a.r.left, below.r.left), right: Math.min(a.r.right, below.r.right) };
        // One under the other: in a flow of blocks the two margins between them become the larger one.
        const sb = getComputedStyle(below.el);
        const margins = flex || grid ? px(sa.marginBottom) + px(sb.marginTop) : Math.max(px(sa.marginBottom), px(sb.marginTop));
        if (!drawnIn(room, a, below)) down.push({ a, b: below, gap: below.r.top - a.r.bottom, want: (flex || grid ? px(ps.rowGap) : 0) + margins });
      }
    }
    // A grid's cells wider or taller than what is in them (placed at a start, an end or a middle) leave gaps of their own:
    // only stretched ones are held to one gap.
    const stretched = axis => !grid || ['normal', 'stretch', 'legacy'].includes(axis === 'across' ? ps.justifyItems : ps.alignItems);
    for (const [list, axis] of [[across, 'across'], [down, 'down']]) {
      // Each gap the same in one row or column (three boxes at least, so two gaps to compare).
      const sizes = list.map(g => g.gap);
      if (!spread && stretched(axis) && list.length >= 2 && Math.max(...sizes) - Math.min(...sizes) > 1.5) say('uneven-gaps', parent, `${axis}: ${sizes.map(round).join(', ')}px`);
      for (const g of list) {
        // Panels: boxes with the page's own inner spacing (--pad, "one inner spacing for every box"). The page's gap
        // between them, as main, .two and .stack set it.
        const pad = px(ps.getPropertyValue('--pad'));
        const panels = [g.a, g.b].every(x => x.kind === 'box' && pad && Math.abs(px(getComputedStyle(x.el).paddingLeft) - pad) <= 1 && Math.abs(px(getComputedStyle(x.el).paddingTop) - pad) <= 1);
        if (panels && pageGap && g.gap > 1.5 && Math.abs(g.gap - pageGap) > 1) say('off-scale', parent, `${pair(g.a.el, g.b.el)} ${axis}: ${round(g.gap)}px, the page's gap is ${round(pageGap)}px`);
        // A gap no stylesheet asked for: inline boxes keep the space between words in the markup, a line's leading adds to
        // one under another. Not where the room is shared out on purpose, nor a grid's columns wider than what is in them.
        else if (!panels && !spread && !grid && g.gap > 1.5 && Math.abs(g.gap - g.want) > 2) say('off-scale', parent, `${pair(g.a.el, g.b.el)} ${axis}: ${round(g.gap)}px where the stylesheet gives ${round(g.want)}px`);
      }
    }
  }
  return out;
};
