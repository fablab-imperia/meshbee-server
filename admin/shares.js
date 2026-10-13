// The apiary sharing panel. These are the owner's /api/user routes; admins
// pass the owner check, so there is no admin copy of them. Mixed into admin().
//
// The list holds active shares and pending invitations to emails with no
// account yet (#40), told apart by `stato`. Each has its own routes.

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

    // Where one entry is changed or removed: …/condivisioni/{id_utente} for a
    // share, …/inviti/{id_invito} for a pending invitation.
    sharePath(share) {
      if (share.stato === "in_attesa") {
        return `/api/user/apiari/${id(this.shares.apiario.id_apiario)}/inviti/${id(share.id_invito)}`;
      }
      return this.sharesPath(`/${id(share.id_utente)}`);
    },

    shareKey(share) {
      return share.stato === "in_attesa" ? `invito-${share.id_invito}` : `utente-${share.id_utente}`;
    },

    async entryCall(method, share, body) {
      this.dialogError = "";
      await this.api(method, this.sharePath(share), body, (m) => (this.dialogError = m));
      await this.loadShares();
    },

    async changeShare(share, ruolo) {
      await this.entryCall("PUT", share, { ruolo });
    },

    async revokeShare(share) {
      const question =
        share.stato === "in_attesa"
          ? `Ritirare l'invito a ${share.email}?`
          : `Smettere di condividere l'apiario con ${share.email}?`;
      if (!confirm(question)) return;
      await this.entryCall("DELETE", share);
    },
  };
}
