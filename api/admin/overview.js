// The Panoramica tab: counts and silent nodes, all from the lookup lists the
// page loads anyway, so it has no request of its own. Mixed into admin().

// An active node with no message for this long is listed as silent.
const SILENT_HOURS = 24;

function overviewMixin() {
  return {
    silentHours: SILENT_HOURS,

    get stats() {
      const l = this.lookups;
      const count = (list, test) => list.filter(test).length;
      return [
        { label: "Utenti attivi", value: `${count(l.utenti, (u) => u.attivo)} / ${l.utenti.length}` },
        { label: "Nodi attivi", value: `${count(l.nodi, (n) => n.attivo)} / ${l.nodi.length}` },
        { label: "Nodi silenziosi", value: this.silentNodes.length },
        { label: "Arnie attive", value: `${count(l.arnie, (a) => a.attiva)} / ${l.arnie.length}` },
        { label: "Apiari", value: l.apiari.length },
      ];
    },

    // Active nodes with no MQTT message in SILENT_HOURS, never-heard ones first.
    get silentNodes() {
      const since = Date.now() - SILENT_HOURS * 3600 * 1000;
      const time = (n) => (n.ultimo_messaggio ? new Date(n.ultimo_messaggio).getTime() : 0);
      return this.lookups.nodi.filter((n) => n.attivo && time(n) < since).sort((a, b) => time(a) - time(b));
    },
  };
}
