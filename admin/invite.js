// The invitation page (#55), served at /invite. Plain script, no Alpine, like
// reset-password.js.
//
// An invitation email links here as /invite#token=…. The fragment never reaches
// the server, and the page drops it from the address bar as soon as it has read it.

const UNREACHABLE = "Server non raggiungibile";

// FastAPI answers `detail` as a string, or as a list of field errors (422).
function describeError(status, data) {
  const detail = data?.detail;
  if (Array.isArray(detail)) {
    return detail.map((e) => e.msg).join("; ");
  }
  return detail || `Errore ${status}`;
}

const $ = (id) => document.getElementById(id);

function show(kind, text) {
  $("error").textContent = kind === "error" ? text : "";
  $("notice").textContent = kind === "notice" ? text : "";
}

async function accept(form, token) {
  if (form.password.value !== form.confirm.value) {
    show("error", "Le due password non coincidono");
    return;
  }
  let res;
  try {
    res = await fetch("/api/auth/invite/accept", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token,
        nome: form.nome.value.trim(),
        cognome: form.cognome.value.trim(),
        password: form.password.value,
      }),
    });
  } catch {
    show("error", UNREACHABLE);
    return;
  }
  if (res.ok) {
    // The tokens are for an app; this page only confirms. Nothing is kept.
    form.hidden = true;
    show("notice", "Account creato. Ora puoi accedere dall'app Meshbee con la tua email e la password scelta.");
  } else {
    show("error", describeError(res.status, await res.json().catch(() => null)));
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const token = new URLSearchParams(location.hash.slice(1)).get("token");
  history.replaceState(null, "", location.pathname);

  if (!token) {
    show("error", "Link di invito incompleto: aprilo di nuovo dall'email ricevuta.");
    return;
  }
  const form = $("accept");
  form.hidden = false;
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    show(null, "");
    accept(form, token);
  });
});
