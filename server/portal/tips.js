// One tooltip for every mark with words of its own (data-tip), on every page: what a mark means, a day's plays, a level's
// records. Nothing is said only under a mouse pointer, where a finger and the keyboard never reach:
// - a mouse pointer over a mark shows its words until the pointer leaves it;
// - a finger's press shows them beside the mark, and a second press on it, a press anywhere else or Escape takes them away;
// - the keyboard's focus on a mark (each one can be reached with Tab) shows them until the focus moves on, or Escape.
// A mark that is itself a link or a button does what it does when pressed; its words show to the pointer and the focus.
// The box is the page's one, on top of everything and inside the window; its words go in as text, and a screen reader hears
// them as the mark's description while they show. The admin pages have the same in admin.js.
(() => {
  const box = document.createElement('div');
  box.className = 'chart-tip';
  box.id = 'odq-tip';
  box.setAttribute('role', 'tooltip');
  box.hidden = true;
  document.body.append(box);
  // The mark whose words show, and whether a press or the focus holds them up (a pointer's leaving then does not end them).
  let shown = null;
  let held = false;
  // The mark an element belongs to, if any.
  const markOf = el => (el && el.closest ? el.closest('[data-tip]') : null);
  // Marks a press already does something with: their words are for the pointer and the focus only.
  const acts = mark => mark.matches('a, button, summary, input, select, textarea, label');
  // The words of a mark, over the point given (a mouse pointer), or else just over the mark, below it when there is no room
  // above; never past the window's edges.
  const show = (mark, x, y) => {
    if (shown && shown !== mark) shown.removeAttribute('aria-describedby');
    shown = mark;
    box.textContent = mark.dataset.tip;
    box.hidden = false;
    mark.setAttribute('aria-describedby', box.id);
    const w = box.offsetWidth, h = box.offsetHeight;
    let top;
    if (x === undefined) {
      const r = mark.getBoundingClientRect();
      x = r.left + r.width / 2;
      top = r.top - h - 8 >= 4 ? r.top - h - 8 : r.bottom + 8;
    } else {
      top = y - h - 12 >= 4 ? y - h - 12 : y + 18;
    }
    box.style.left = `${Math.min(innerWidth - w - 8, Math.max(8, x - w / 2))}px`;
    box.style.top = `${Math.min(innerHeight - h - 4, Math.max(4, top))}px`;
  };
  const hide = () => {
    box.hidden = true;
    held = false;
    if (shown) shown.removeAttribute('aria-describedby');
    shown = null;
  };
  // A mouse (or a pen held over the screen): the words of the mark under it, gone when it leaves. Words a press or the focus
  // holds up stay, until the pointer comes over another mark.
  document.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch') return;
    const mark = markOf(e.target);
    if (held) {
      if (mark && mark !== shown) { held = false; show(mark, e.clientX, e.clientY); }
      return;
    }
    if (mark) show(mark, e.clientX, e.clientY); else if (shown) hide();
  }, { passive: true });
  // A press: a finger's on a mark shows its words, or takes them away when they already show; a press anywhere else takes
  // them away.
  document.addEventListener('pointerdown', e => {
    const mark = markOf(e.target);
    if (e.pointerType === 'mouse') {
      if (held && mark !== shown) hide();
      return;
    }
    if (!mark || acts(mark)) { if (shown) hide(); return; }
    if (held && shown === mark) { hide(); return; }
    show(mark);
    held = true;
  }, { passive: true });
  // The focus (the keyboard's, or a press that gave it): the words of the mark it is on, until it moves on.
  document.addEventListener('focusin', e => {
    const mark = markOf(e.target);
    if (!mark) return;
    show(mark);
    held = true;
  });
  document.addEventListener('focusout', e => {
    if (shown && !(e.relatedTarget && shown.contains(e.relatedTarget)) && shown.contains(e.target)) hide();
  });
  // Escape takes them away, wherever the focus is.
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && shown) hide();
  });
  // Marks that come many together (a chart's, a grid of days: data-tips on their box) are one stop of the Tab key, not one
  // each: the arrow keys go from mark to mark by where they are drawn (the next one to the right, below and so on), Home and
  // End to the first and the last, and the mark reached shows its words. The stop is the mark last reached.
  const marksIn = group => [...group.querySelectorAll('[data-tip]')].filter(m => m.getClientRects().length);
  const rove = group => {
    const marks = marksIn(group);
    const current = marks.find(m => m.tabIndex === 0 && m.dataset.stop) || marks[0];
    for (const m of group.querySelectorAll('[data-tip]')) m.tabIndex = m === current ? 0 : -1;
    if (current) current.dataset.stop = '1';
  };
  for (const group of document.querySelectorAll('[data-tips]')) rove(group);
  // The nearest mark in a direction (dx, dy: -1, 0 or 1) from one, on its row or its column.
  const toward = (marks, from, dx, dy) => {
    const a = from.getBoundingClientRect(), ax = a.left + a.width / 2, ay = a.top + a.height / 2;
    let best = null, far = Infinity;
    for (const m of marks) {
      if (m === from) continue;
      const b = m.getBoundingClientRect(), bx = b.left + b.width / 2, by = b.top + b.height / 2;
      const along = dx ? (bx - ax) * dx : (by - ay) * dy, across = dx ? Math.abs(by - ay) : Math.abs(bx - ax);
      if (along <= 0 || across > (dx ? a.height : a.width) / 2) continue;
      if (along < far) { far = along; best = m; }
    }
    return best;
  };
  document.addEventListener('keydown', e => {
    const mark = markOf(e.target);
    const group = mark && mark.closest('[data-tips]');
    if (!group || e.altKey || e.ctrlKey || e.metaKey) return;
    const marks = marksIn(group);
    const ways = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] };
    const next = e.key === 'Home' ? marks[0] : e.key === 'End' ? marks[marks.length - 1]
      : ways[e.key] ? toward(marks, mark, ...ways[e.key]) : undefined;
    if (next === undefined) return;
    // At the edge: nothing moves, and the page does not scroll either.
    e.preventDefault();
    if (!next) return;
    for (const m of group.querySelectorAll('[data-tip]')) { m.tabIndex = -1; delete m.dataset.stop; }
    next.tabIndex = 0;
    next.dataset.stop = '1';
    next.focus();
  });
  // Words held up follow their mark as the page scrolls; a pointer's go.
  addEventListener('scroll', () => {
    if (held && shown) show(shown); else if (shown) hide();
  }, { passive: true, capture: true });
  addEventListener('resize', () => { if (shown) hide(); }, { passive: true });
})();
