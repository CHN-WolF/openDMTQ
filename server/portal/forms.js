// The site's own check of what a form needs before it goes, in place of the browser's: its bubbles speak the browser's
// language rather than the page's, and look like nothing on the site. Every form marked novalidate is checked here: a field
// it needs left empty (data-missing), or one its own rules refuse (data-invalid: a pattern, a number's bounds, a type),
// stops the form; that field's words show right under the field (.field-error in style.css) when it stands in a .field,
// otherwise in the site's error box above the form (.error), and the field takes the focus, marked for screen readers too.
// The server checks the same again, so a browser without scripts loses nothing but this early word. A form that goes says
// so on its button while the next page comes (aria-busy, style.css).
//
// Also here, for every form: a password field's Show (.pw-toggle), and the ID last used on this browser back in a sign-in
// form marked data-remember="<name>".
//
// For another page's forms (the admin pages', say): novalidate on the form; on each field it checks, data-missing="<the
// words, in the page's language>" when it must be filled and data-invalid="<the words>" when its pattern, min, max or type
// must hold; and this file, loaded with defer.
(() => {
  // What is wrong with a field, in its own words, or '' when nothing is: empty first, then its own rules.
  const fault = f => {
    if (f.disabled) return '';
    if (f.dataset.missing !== undefined && f.value.trim() === '') return f.dataset.missing;
    if (f.dataset.invalid !== undefined && f.value.trim() !== '' && !f.validity.valid) return f.dataset.invalid;
    return '';
  };
  // A field's own line of words under it, made when first needed, named by the field for screen readers.
  const lineOf = f => {
    const field = f.closest('.field');
    if (!field) return null;
    let line = field.querySelector('.field-error');
    if (!line) {
      line = document.createElement('span');
      line.className = 'field-error';
      line.setAttribute('role', 'alert');
      line.id = `${f.id || f.name}-error`;
      field.append(line);
    }
    return line;
  };
  // A field put right, or about to be checked again: its mark and its words go.
  const clear = f => {
    f.removeAttribute('aria-invalid');
    const line = f.closest('.field') && f.closest('.field').querySelector('.field-error');
    if (line) {
      line.remove();
      f.removeAttribute('aria-describedby');
    }
  };
  for (const form of document.querySelectorAll('form[novalidate]')) {
    form.addEventListener('submit', e => {
      // The first field, in the order of the form, that cannot go as it is.
      const wrong = [...form.querySelectorAll('[data-missing], [data-invalid]')].find(f => fault(f) !== '');
      if (!wrong) {
        // On its way: the button that sent it shows that it is working (a wrong password takes a second to answer).
        const button = e.submitter || form.querySelector('button:not([type=button])');
        if (button) button.setAttribute('aria-busy', 'true');
        return;
      }
      e.preventDefault();
      for (const f of form.querySelectorAll('[aria-invalid]')) clear(f);
      let box = lineOf(wrong);
      if (box) {
        // Under the field: the server's last word above the form (a wrong password) is about another try, so it goes.
        const said = form.previousElementSibling;
        if (said && said.matches('.error')) said.remove();
      } else {
        // The box right above the form: the one the server's answer put there, or a new one in the same place.
        box = form.previousElementSibling;
        if (!box || !box.matches('.error')) {
          box = document.createElement('p');
          box.className = 'error';
          box.setAttribute('role', 'alert');
          form.before(box);
        }
        if (!box.id) box.id = `${form.className.split(' ')[0] || 'form'}-says`;
      }
      box.textContent = fault(wrong);
      // The field marked, and named by its words, for whoever cannot see where the words are.
      wrong.setAttribute('aria-invalid', 'true');
      wrong.setAttribute('aria-describedby', box.id);
      wrong.focus();
    });
    // Typing into a marked field takes its mark away: what it says is up to the next press of the button.
    form.addEventListener('input', e => {
      if (e.target.getAttribute('aria-invalid') === 'true') clear(e.target);
    });
  }

  // Show: the password as typed, until pressed again. The field keeps the focus and its cursor where it was, so typing goes
  // on; a form that goes takes the password hidden again (a browser keeps no plain copy in its form history).
  for (const toggle of document.querySelectorAll('.pw-toggle')) {
    const field = document.getElementById(toggle.getAttribute('aria-controls'));
    if (!field) continue;
    toggle.hidden = false;
    const set = shown => {
      field.type = shown ? 'text' : 'password';
      toggle.classList.toggle('on', shown);
      toggle.textContent = shown ? toggle.dataset.hide : toggle.dataset.show;
      toggle.setAttribute('aria-label', shown ? toggle.dataset.hideLabel : toggle.dataset.showLabel);
    };
    // A press with the mouse leaves the focus in the field (the button does not take it).
    toggle.addEventListener('mousedown', e => e.preventDefault());
    toggle.addEventListener('click', () => {
      const at = [field.selectionStart, field.selectionEnd];
      set(field.type === 'password');
      if (document.activeElement !== toggle) {
        field.focus();
        try { field.setSelectionRange(at[0], at[1]); } catch (_) { /* a field that keeps no cursor */ }
      }
    });
    if (field.form) field.form.addEventListener('submit', e => { if (!e.defaultPrevented) set(false); });
  }

  // The ID last used to sign in on this browser, back in its field: the focus then goes to the password, the field left to
  // type. Kept when the form goes (a wrong password keeps it too: the server sends the same ID back). Browser storage may be
  // off (a private window): then nothing is kept and nothing breaks.
  for (const form of document.querySelectorAll('form[data-remember]')) {
    const key = `opendmtq.id.${form.dataset.remember}`;
    const id = form.querySelector('input[autocomplete=username]');
    const password = form.querySelector('input[type=password]');
    if (!id) continue;
    let kept = '';
    try { kept = localStorage.getItem(key) || ''; } catch (_) { /* storage off */ }
    if (!id.value && kept) id.value = kept;
    // The first field left to fill takes the focus: not where a finger is the pointer (a phone, a tablet), whose keyboard
    // would come up over the page, and not over a field the server's answer already chose.
    if (!matchMedia('(pointer: coarse)').matches && !form.querySelector('[autofocus]')) (id.value && password ? password : id).focus();
    form.addEventListener('submit', e => {
      if (e.defaultPrevented || !id.value.trim()) return;
      try { localStorage.setItem(key, id.value.trim()); } catch (_) { /* storage off */ }
    });
  }
})();
