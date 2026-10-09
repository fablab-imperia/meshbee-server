// The apiary sharing panel. These are the owner's /api/user routes; admins
// pass the owner check, so there is no admin copy of them. Mixed into admin().

function sharesMixin() {
  return {
    // The panel's data: { apiario, rows, form: { email, ruolo } }.
    shares: null,

    async openShares(apiario) {
      this.shares = { apiario, rows: [], form: { email: "", ruolo: "viewer" } };
      this.resetPage("shares"); // pagination.js
      this.dialogError = "";
      this.dialog = { kind: "shares", title: `Condivisioni: ${apiario.nome_apiario}` };
      await this.loadShares();
    },

    sharesPath(suffix = "") {
      return `/api/user/apiari/${id(this.shares.apiario.id_apiario)}/condivisioni${suffix}`;
    },

    async loadShares() {
      const rows = await this.api("GET", this.sharesPath(), undefined, (m) => (this.dialogError = m));
      if (rows) this.shares.rows = rows;
    },

    // Every change ends by reloading the list, so it shows what the API kept.
    async shareCall(method, suffix, body) {
      this.dialogError = "";
      const data = await this.api(method, this.sharesPath(suffix), body, (m) => (this.dialogError = m));
      await this.loadShares();
      return data;
    },

    async addShare() {
      if (await this.shareCall("POST", "", this.shares.form)) this.shares.form.email = "";
    },

    async changeShare(share, ruolo) {
      await this.shareCall("PUT", `/${id(share.id_utente)}`, { ruolo });
    },

    async revokeShare(share) {
      if (!confirm(`Smettere di condividere l'apiario con ${share.email}?`)) return;
      await this.shareCall("DELETE", `/${id(share.id_utente)}`);
    },
  };
}
