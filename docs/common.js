/* Plugga – gemensamma hjälpfunktioner */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const NIVA = {
  E: { namn: 'E-nivå', kort: 'Grundläggande', hint: 'Fakta och enkla beskrivningar' },
  C: { namn: 'C-nivå', kort: 'Goda kunskaper', hint: 'Förklara samband' },
  A: { namn: 'A-nivå', kort: 'Mycket goda', hint: 'Resonera, jämföra, dra slutsatser' }
};
const lv = n => `<span class="lv lv-${n}" title="${NIVA[n]?.namn || ''}">${n}</span>`;

/* Statisk sida (GitHub Pages, byggd med server.py --bygg-sida): läser färdiga JSON-filer i data/ */
async function apiStatisk(path) {
  const [p, qs] = path.split('?'), q = new URLSearchParams(qs || '');
  const file = p === 'info' ? null : p === 'amnen' ? 'amnen' : p.startsWith('amne/') ? p : p === 'fragor' ? 'fragor/' + q.get('amne') : undefined;
  if (file === null) return { admin: false, statisk: true };
  if (file === undefined) throw new Error('Finns inte i den statiska sidan');
  const r = await fetch(`data/${file}.json`, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`Hittar inte data/${file}.json`);
  return r.json();
}

async function api(path, { method = 'GET', body } = {}) {
  if (window.PLUGGA_STATISK) return apiStatisk(path);
  const headers = { 'X-Plugga': '1' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const r = await fetch('/api/' + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json().catch(() => ({ fel: `Servern svarade ${r.status}` }));
  if (!r.ok) throw new Error(j.fel || r.statusText);
  return j;
}

/* Text i frågor/svar: tillåten HTML (strong, em, sub, sup, br, listor, span.nb),
   **fetstil**, radbrytningar och kemiska formler i klamrar: {H2O} -> H₂O */
const ALLOWED = new Set(['STRONG', 'B', 'EM', 'I', 'U', 'SUB', 'SUP', 'BR', 'UL', 'OL', 'LI', 'P', 'SPAN', 'CODE']);
function render(src) {
  let s = String(src ?? '');
  s = s.replace(/\{([^{}<>]+)\}/g, (_, x) => x.replace(/([A-Za-z\)\]])(\d+)/g, '$1<sub>$2</sub>'));
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/\r?\n/g, '<br>');
  const t = document.createElement('template');
  t.innerHTML = s;
  const walk = node => {
    [...node.childNodes].forEach(ch => {
      if (ch.nodeType === 1) {
        if (!ALLOWED.has(ch.tagName)) { ch.replaceWith(document.createTextNode(ch.textContent)); return; }
        const cls = ch.getAttribute('class');
        [...ch.attributes].forEach(a => ch.removeAttribute(a.name));
        if (ch.tagName === 'SPAN' && cls === 'nb') ch.className = 'nb';
        walk(ch);
      } else if (ch.nodeType !== 3) ch.remove();
    });
  };
  walk(t.content);
  return t.innerHTML;
}
const plain = s => { const d = document.createElement('div'); d.innerHTML = render(s); return d.textContent; };

function toast(msg, err = false) {
  let t = $('#toast');
  if (!t) { t = document.createElement('div'); t.id = 'toast'; t.setAttribute('role', 'status'); document.body.appendChild(t); }
  t.textContent = msg; t.className = 'show' + (err ? ' err' : '');
  clearTimeout(toast.h); toast.h = setTimeout(() => t.className = '', err ? 5000 : 2600);
}

const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } };
const store = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { } };
