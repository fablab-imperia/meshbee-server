// The readings tab as charts: the rows already listed, drawn as inline SVG
// paths. No chart library and no extra request. Mixed into admin().

// The measurements the readings charts draw.
const MEASURES = [
  { name: "temperatura", label: "Temperatura", unit: "°C" },
  { name: "umidita", label: "Umidità", unit: "%" },
  { name: "peso", label: "Peso", unit: "kg" },
  { name: "batteria", label: "Batteria", unit: "V" },
];

// The charts' SVG viewBox; index.html writes the same numbers literally.
const CHART_W = 300;
const CHART_H = 100;

function chartsMixin() {
  return {
    measures: MEASURES,
    // The readings tab shows charts instead of the table.
    showChart: false,

    get chartShown() {
      return !!(this.resource.chart && this.filters.id_arnia && this.showChart);
    },

    // One measurement of the listed readings, as an SVG path over
    // CHART_W × CHART_H. A missing value lifts the pen, so gaps show.
    chart(measure) {
      const points = this.rows
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
