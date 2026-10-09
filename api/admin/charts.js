// The readings tab as charts, drawn as inline SVG paths, no chart library.
// The table holds one page, so the charts load their own readings: the
// picked hive's in the picked period, up to CHART_LIMIT. Mixed into admin().

// The measurements the readings charts draw.
const MEASURES = [
  { name: "temperatura", label: "Temperatura", unit: "°C" },
  { name: "umidita", label: "Umidità", unit: "%" },
  { name: "peso", label: "Peso", unit: "kg" },
  { name: "batteria", label: "Batteria", unit: "V" },
];

// The most readings a chart draws: the readings route's largest page.
const CHART_LIMIT = 10000;

// The charts' SVG viewBox; index.html writes the same numbers literally.
const CHART_W = 300;
const CHART_H = 100;

function chartsMixin() {
  return {
    measures: MEASURES,
    // The readings tab shows charts instead of the table.
    showChart: false,
    // What the charts draw, and how many readings the period holds in all.
    chartRows: [],
    chartTotal: 0,

    get chartShown() {
      return !!(this.resource.chart && this.filters.id_arnia && this.showChart);
    },

    async toggleChart() {
      this.showChart = !this.showChart;
      if (this.chartShown) await this.loadChart();
    },

    // The same route and filters as the table, in one window from the newest.
    async loadChart() {
      const page = await this.list(this.listPath(CHART_LIMIT, 0));
      this.chartRows = page ? page.rows : [];
      this.chartTotal = page ? page.total : 0;
    },

    // One measurement of the loaded readings, as an SVG path over
    // CHART_W × CHART_H. A missing value lifts the pen, so gaps show.
    chart(measure) {
      const points = this.chartRows
        .map((r) => ({ t: new Date(r.timestamp).getTime(), v: r[measure] == null ? null : Number(r[measure]) }))
        .sort((a, b) => a.t - b.t);
      const values = points.filter((p) => p.v != null).map((p) => p.v);
      if (values.length === 0) return { empty: true, d: "" };
      const min = Math.min(...values);
      const max = Math.max(...values);
      const t0 = points[0].t;
      const tSpan = points[points.length - 1].t - t0 || 1;
      const vSpan = max - min || 1;
      let d = "";
      let pen = "M";
      for (const p of points) {
        if (p.v == null) {
          pen = "M";
          continue;
        }
        const x = ((p.t - t0) / tSpan) * CHART_W;
        // A flat series runs through the middle, not along the bottom edge.
        const y = max === min ? CHART_H / 2 : CHART_H - ((p.v - min) / vSpan) * CHART_H;
        // A zero-length stroke after each move: a lone value still shows, as a dot.
        d += `${pen}${x.toFixed(1)},${y.toFixed(1)} ${pen === "M" ? "l0,0 " : ""}`;
        pen = "L";
      }
      const date = (t) => new Date(t).toLocaleString("it-IT");
      return {
        empty: false,
        d,
        min,
        max,
        last: values[values.length - 1],
        from: date(t0),
        to: date(points[points.length - 1].t),
      };
    },
  };
}
