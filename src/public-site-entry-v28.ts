import publicSite from "./public-site-entry-v27.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v28-win5-view-switch-20260816";

function switcherStyles(): string {
  return `<style>
    .win5-view-switch{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:16px 0 6px;padding:4px;border:1px solid var(--line);border-radius:14px;background:var(--panel)}
    .win5-view-button{appearance:none;border:1px solid transparent;border-radius:10px;background:transparent;color:var(--muted);font:inherit;font-size:13px;font-weight:900;min-height:42px;cursor:pointer}
    .win5-view-button[aria-selected="true"]{background:var(--green2);border-color:var(--green);color:#c7f8e5;box-shadow:0 1px 0 rgba(255,255,255,.04) inset}
    .win5-view-panel[hidden]{display:none!important}
    .win5-view-panel{min-width:0}
    .win5-other-heading{margin-top:18px}
    .win5-other-heading h2{margin:0;font-size:19px}
    .win5-other-heading p{margin:4px 0 0;color:var(--muted);font-size:10px}
    .win5-view-panel[data-win5-view="other"] .win5-quick{margin-top:10px}
    @media(max-width:760px){.win5-view-switch{position:sticky;top:8px;z-index:20;margin:12px 0 4px;background:rgba(15,23,32,.96);backdrop-filter:blur(8px)}.win5-view-button{min-height:44px;font-size:13px}.win5-other-heading h2{font-size:17px}}
  </style>`;
}

function switcherScript(): string {
  return `<script>
  (() => {
    const hero = document.querySelector('.win5-hero');
    if (!hero || document.querySelector('.win5-view-switch')) return;

    const sections = Array.from(document.querySelectorAll('.win5-section'));
    const findSection = (label) => sections.find((section) => (section.querySelector('h2')?.textContent || '').trim() === label);
    const targetSection = findSection('対象5レース');
    const plansSection = findSection('3パターン比較');
    const ticketsSection = findSection('買い目');
    const diagnosticsSection = sections.find((section) => section.querySelector('.win5-tech'));
    const quick = document.querySelector('.win5-quick');
    const note = document.querySelector('.win5-note');

    const switcher = document.createElement('div');
    switcher.className = 'win5-view-switch';
    switcher.setAttribute('role', 'tablist');
    switcher.setAttribute('aria-label', 'WIN5表示切替');
    switcher.innerHTML = '<button class="win5-view-button" type="button" role="tab" data-win5-tab="tickets" aria-selected="true" aria-controls="win5-view-tickets">買い目</button><button class="win5-view-button" type="button" role="tab" data-win5-tab="other" aria-selected="false" aria-controls="win5-view-other">その他</button>';

    const ticketsPanel = document.createElement('div');
    ticketsPanel.id = 'win5-view-tickets';
    ticketsPanel.className = 'win5-view-panel';
    ticketsPanel.dataset.win5View = 'tickets';
    ticketsPanel.setAttribute('role', 'tabpanel');

    const otherPanel = document.createElement('div');
    otherPanel.id = 'win5-view-other';
    otherPanel.className = 'win5-view-panel';
    otherPanel.dataset.win5View = 'other';
    otherPanel.setAttribute('role', 'tabpanel');
    otherPanel.hidden = true;

    for (const section of [targetSection, plansSection, ticketsSection]) {
      if (section) ticketsPanel.append(section);
    }

    const heading = document.createElement('div');
    heading.className = 'win5-other-heading';
    heading.innerHTML = '<h2>その他</h2><p>更新時刻・ルール・1着確率・直近学習の詳細</p>';
    otherPanel.append(heading);
    if (quick) otherPanel.append(quick);
    if (diagnosticsSection) otherPanel.append(diagnosticsSection);
    if (note) otherPanel.append(note);

    hero.insertAdjacentElement('afterend', switcher);
    switcher.insertAdjacentElement('afterend', ticketsPanel);
    ticketsPanel.insertAdjacentElement('afterend', otherPanel);

    const buttons = Array.from(switcher.querySelectorAll('[data-win5-tab]'));
    const activate = (view) => {
      const ticketsActive = view === 'tickets';
      ticketsPanel.hidden = !ticketsActive;
      otherPanel.hidden = ticketsActive;
      for (const button of buttons) {
        const active = button.getAttribute('data-win5-tab') === view;
        button.setAttribute('aria-selected', active ? 'true' : 'false');
        button.tabIndex = active ? 0 : -1;
      }
    };

    for (const button of buttons) {
      button.addEventListener('click', () => activate(button.getAttribute('data-win5-tab') || 'tickets'));
      button.addEventListener('keydown', (event) => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        const next = button.getAttribute('data-win5-tab') === 'tickets' ? 'other' : 'tickets';
        activate(next);
        switcher.querySelector('[data-win5-tab="' + next + '"]')?.focus();
      });
    }

    activate('tickets');
  })();
  </script>`;
}

async function enhanceWin5(response: Response): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  let html = await response.text();
  html = html.replace("</head>", `${switcherStyles()}</head>`).replace("</body>", `${switcherScript()}</body>`);
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("x-race-ui-version", UI_VERSION);
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    return new URL(request.url).pathname === "/win5" ? enhanceWin5(response) : response;
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
