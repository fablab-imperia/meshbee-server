// A hive's photo panel (#3): see it, replace it, remove it. These are the
// hive's /api/user routes; admins pass their access check, so there is no
// admin copy of them. Mixed into admin().
//
// An <img src> cannot send the bearer token, so the photo is fetched like any
// other request and shown from an object URL. The server does the processing
// (upright, scaled, WebP, no metadata) and the 5 MB limit: the page sends the
// file as it is and shows the API's own message when it is refused.

function photosMixin() {
  return {
    // The panel's data: { arnia, id_foto, url, file, busy }.
    photo: null,

    async openPhoto(arnia) {
      this.closePhoto();
      this.photo = { arnia, id_foto: arnia.id_foto, url: null, file: null, busy: false };
      this.dialogError = "";
      this.dialog = { kind: "photo", title: `Foto: ${arnia.nome_arnia || arnia.id_arnia}` };
      await this.loadPhoto();
    },

    // Releases the previous image, which would otherwise stay in memory until
    // the page is closed.
    closePhoto() {
      if (this.photo?.url) URL.revokeObjectURL(this.photo.url);
      this.photo = null;
    },

    photoPath() {
      return `/api/user/arnie/${id(this.photo.arnia.id_arnia)}/foto`;
    },

    // The panel may be closed, or opened on another hive, while a request is
    // under way: `photo` is the panel the request was made for.
    async loadPhoto() {
      const photo = this.photo;
      if (photo.url) URL.revokeObjectURL(photo.url);
      photo.url = null;
      if (photo.id_foto == null) return;
      const res = await this.send("GET", this.photoPath(), undefined, (m) => (this.dialogError = m));
      if (!res) return;
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        if (this.photo === photo) this.dialogError = describeError(res.status, data);
        return;
      }
      const blob = await res.blob();
      if (this.photo === photo) photo.url = URL.createObjectURL(blob);
    },

    // Uploading replaces the photo the hive had, file and all.
    async uploadPhoto() {
      if (!this.photo.file) return;
      const body = new FormData();
      body.append("file", this.photo.file);
      await this.photoCall("PUT", body, (photo, data) => (photo.id_foto = data.id_allegato));
    },

    async removePhoto() {
      if (!confirm("Rimuovere la foto dell'arnia?")) return;
      await this.photoCall("DELETE", undefined, (photo) => (photo.id_foto = null));
    },

    // Every change shows the photo the API kept, and refreshes the table's
    // Foto column behind the panel.
    async photoCall(method, body, apply) {
      const photo = this.photo;
      this.dialogError = "";
      photo.busy = true;
      try {
        const data = await this.api(method, this.photoPath(), body, (m) => (this.dialogError = m));
        if (!data) return;
        apply(photo, data);
        photo.file = null;
        // The file input still names the file just sent.
        if (this.$refs.photoFile) this.$refs.photoFile.value = "";
        if (this.photo === photo) await this.loadPhoto();
        await this.refresh();
      } finally {
        photo.busy = false;
      }
    },
  };
}
