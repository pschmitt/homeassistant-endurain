/*
 * activity-heatmap-card: GitHub-style calendar heatmap of active days.
 *
 * type: custom:activity-heatmap-card
 * entity: sensor.endurain_pschmitt_active_days
 * attribute: days          # {"YYYY-MM-DD": [count, km], ...}
 * weeks: 13                # number of week columns
 * week_start: 0            # 0 = Sunday, 1 = Monday
 * color: "#ff6529"
 * title: null             # text prefix in the header
 * gap: 8                  # px between cells
 * show_header: true       # summary line (active days)
 * show_legend: true       # active/rest legend
 * show_day_labels: true   # weekday labels on the left
 * show_month_labels: true # month names above the columns
 * tooltip: true           # rich hover tooltip
 * highlight_today: true   # outline today's cell
 */
class ActivityHeatmapCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("entity is required");
    this._config = {
      attribute: "days",
      weeks: 13,
      week_start: 0,
      color: "#ff6529",
      title: null,
      gap: 8,
      show_header: true,
      show_legend: true,
      show_day_labels: true,
      show_month_labels: true,
      tooltip: true,
      highlight_today: true,
      ...config,
    };
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    const sig = st ? st.last_updated : "";
    if (sig !== this._sig) {
      this._sig = sig;
      this._render();
    }
  }

  getCardSize() {
    return 4;
  }

  static getConfigForm() {
    const bool = (name) => ({ name, default: true, selector: { boolean: {} } });
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: "sensor" } } },
        { name: "title", selector: { text: {} } },
        { name: "attribute", default: "days", selector: { text: {} } },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "weeks", default: 13, selector: { number: { min: 4, max: 53, step: 1, mode: "box" } } },
            { name: "gap", default: 8, selector: { number: { min: 0, max: 20, step: 1, mode: "box", unit_of_measurement: "px" } } },
            {
              name: "week_start",
              default: 0,
              selector: {
                select: {
                  mode: "dropdown",
                  options: [
                    { value: 0, label: "Sunday" },
                    { value: 1, label: "Monday" },
                  ],
                },
              },
            },
            { name: "color", default: "#ff6529", selector: { text: { type: "color" } } },
          ],
        },
        {
          type: "grid",
          name: "",
          schema: [
            bool("show_header"),
            bool("show_legend"),
            bool("show_day_labels"),
            bool("show_month_labels"),
            bool("tooltip"),
            bool("highlight_today"),
          ],
        },
      ],
      computeLabel: (item) =>
        ({
          entity: "Active days sensor",
          title: "Title",
          attribute: "Attribute holding the days",
          weeks: "Weeks to show",
          gap: "Cell gap",
          week_start: "Week starts on",
          color: "Active color",
          show_header: "Show summary header",
          show_legend: "Show legend",
          show_day_labels: "Show weekday labels",
          show_month_labels: "Show month labels",
          tooltip: "Hover tooltip",
          highlight_today: "Highlight today",
        })[item.name] || item.name,
    };
  }

  static getStubConfig() {
    return { entity: "sensor.endurain_pschmitt_active_days" };
  }

  _render() {
    if (!this._config || !this.shadowRoot) return;
    const c = this._config;
    const st = this._hass && this._hass.states[c.entity];
    const days = (st && st.attributes[c.attribute]) || {};
    const pad = (n) => String(n).padStart(2, "0");
    const key = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

    const today = new Date();
    today.setHours(12, 0, 0, 0);
    const offset = (today.getDay() - c.week_start + 7) % 7;
    const start = new Date(today);
    start.setDate(today.getDate() - offset - (c.weeks - 1) * 7);

    const monthFmt = new Intl.DateTimeFormat(this._hass?.locale?.language || undefined, { month: "short" });
    const dayFmt = new Intl.DateTimeFormat(this._hass?.locale?.language || undefined, { weekday: "short" });
    const fullFmt = new Intl.DateTimeFormat(this._hass?.locale?.language || undefined, {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    });

    let cols = "";
    let months = "";
    let lastMonth = -1;
    let active = 0;
    for (let w = 0; w < c.weeks; w++) {
      let cells = "";
      for (let r = 0; r < 7; r++) {
        const d = new Date(start);
        d.setDate(start.getDate() + w * 7 + r);
        if (d > today) {
          cells += `<div class="cell empty"></div>`;
          continue;
        }
        const info = days[key(d)];
        let tip = fullFmt.format(d);
        if (info) {
          active++;
          tip += `\n${info[0]}× active · ${info[1]} km`;
        } else {
          tip += "\nRest day";
        }
        const isToday = c.highlight_today && key(d) === key(today);
        cells += `<div class="cell${info ? " on" : ""}${isToday ? " now" : ""}" data-tip="${tip}"></div>`;
      }
      const first = new Date(start);
      first.setDate(start.getDate() + w * 7);
      const m = first.getMonth();
      months += `<div class="mlabel">${m !== lastMonth ? monthFmt.format(first) : ""}</div>`;
      lastMonth = m;
      cols += `<div class="col">${cells}</div>`;
    }

    const labels = [0, 1, 2, 3, 4, 5, 6]
      .map((r) => {
        const d = new Date(2024, 0, 7 + ((c.week_start + r) % 7)); // 2024-01-07 is a Sunday
        return `<div class="dlabel">${r % 2 === 1 ? dayFmt.format(d) : ""}</div>`;
      })
      .join("");

    const title = c.title ?? "";
    this.shadowRoot.innerHTML = `
      <style>
        :host { --hm-on: ${c.color}; --gap: ${c.gap}px; display: block; }
        ha-card { padding: 12px 16px; overflow: hidden; }
        .head { display: flex; justify-content: space-between; align-items: baseline;
                color: var(--secondary-text-color); font-size: 0.85em; margin-bottom: 8px; }
        .legend { display: flex; align-items: center; gap: 6px; }
        .sw { width: 12px; height: 12px; border-radius: 4px; display: inline-block; }
        .sw.on { background: var(--hm-on); }
        .sw.off { background: var(--divider-color); opacity: .6; }
        .grid { display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: var(--gap); }
        .months { display: grid; grid-template-columns: repeat(${c.weeks}, minmax(0, 1fr));
                  grid-column: 2; font-size: 0.75em; color: var(--secondary-text-color); height: ${c.show_month_labels ? "1.4em" : "0"}; }
        .mlabel { overflow: visible; min-width: 0; white-space: nowrap; }
        .dlabels { display: grid; grid-template-rows: repeat(7, 1fr); row-gap: var(--gap);
                   font-size: 0.75em; color: var(--secondary-text-color); }
        .dlabel { display: flex; align-items: center; }
        .cols { display: grid; grid-template-columns: repeat(${c.weeks}, minmax(0, 1fr)); column-gap: var(--gap); }
        .col { display: grid; grid-template-rows: repeat(7, 1fr); row-gap: var(--gap); }
        .cell { aspect-ratio: 1; border-radius: 28%; background: var(--divider-color); opacity: .6; }
        .cell.on { background: var(--hm-on); opacity: 1; box-shadow: 0 0 0 1.5px rgba(255,255,255,.7); }
        .cell.empty { background: transparent; }
        .cell.now { outline: 3px solid var(--primary-color); outline-offset: 2px; }
        .cell { transition: transform .1s; }
        .cell:not(.empty):hover { transform: scale(1.12); }
        .tip { position: fixed; display: none; z-index: 10; pointer-events: none; white-space: pre; font-size: 0.8em;
               line-height: 1.4; padding: 6px 10px; border-radius: 8px; color: var(--primary-text-color);
               background: var(--card-background-color, #fff); border: 1px solid var(--divider-color);
               box-shadow: 0 2px 8px rgba(0,0,0,.35); }
        .tip b { display: block; }
      </style>
      <ha-card>
        ${c.show_header ? `<div class="head">
          <span>${title}${title ? " · " : ""}${active} active days</span>
          ${c.show_legend ? `<span class="legend"><span class="sw on"></span>active <span class="sw off"></span>rest</span>` : ""}
        </div>` : ""}
        <div class="grid">
          <div></div><div class="months">${c.show_month_labels ? months : ""}</div>
          <div class="dlabels">${c.show_day_labels ? labels : ""}</div>
          <div class="cols">${cols}</div>
        </div>
        <div class="tip"></div>
      </ha-card>`;
    const tip = this.shadowRoot.querySelector(".tip");
    const esc = (v) => String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;");
    for (const el of c.tooltip ? this.shadowRoot.querySelectorAll(".cell[data-tip]") : []) {
      el.addEventListener("mouseenter", () => {
        const [head, ...rest] = el.dataset.tip.split("\n");
        tip.innerHTML = `<b>${esc(head)}</b>${esc(rest.join("\n"))}`;
        tip.style.display = "block";
        const r = el.getBoundingClientRect();
        const t = tip.getBoundingClientRect();
        tip.style.left = `${Math.max(4, Math.min(innerWidth - t.width - 4, r.left + r.width / 2 - t.width / 2))}px`;
        tip.style.top = `${r.top - t.height - 8 < 4 ? r.bottom + 8 : r.top - t.height - 8}px`;
      });
      el.addEventListener("mouseleave", () => (tip.style.display = "none"));
    }
  }
}

if (!customElements.get("activity-heatmap-card")) {
  customElements.define("activity-heatmap-card", ActivityHeatmapCard);
}
window.customCards = window.customCards || [];
window.customCards.push({
  type: "activity-heatmap-card",
  name: "Activity Heatmap",
  description: "GitHub-style calendar of active days",
});
