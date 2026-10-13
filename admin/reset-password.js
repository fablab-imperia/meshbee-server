// The password-reset page (#54), served at /reset-password. Plain script, no
// Alpine: two small forms, and one of them shows.
//
// A reset email links here as /reset-password#token=…. The fragment never
// reaches the server, and the page drops it from the address bar (and so from
// the history) as soon as it has read it.

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

// POST JSON; returns [response, body] or null if the server could not be reached.
async function post(path, payload) {
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return [res, await res.json().catch(() => null)];
  } catch {
    show("error", UNREACHABLE);
    return null;
  }
}

async function requestLink(form) {
  const result = await post("/api/auth/password/forgot", { email: form.email.value });
  if (!result) return;
  const [res, data] = result;
  if (res.status === 202) {
    form.hidden = true;
    show("notice", data.message);
  } else {
    show("error", describeError(res.status, data));
  }
}

async function resetPassword(form, token) {
  if (form.password.value !== form.confirm.value) {
    show("error", "Le due password non coincidono");
    return;
  }
  const result = await post("/api/auth/password/reset", {
    token,
    new_password: form.password.value,
  });
  if (!result) return;
  const [res, data] = result;
  if (res.ok) {
    form.hidden = true;
    show("notice", `${data.message}.`);
  } else {
    show("error", describeError(res.status, data));
    // An expired or used link cannot be retried: offer a new one.
    if (res.status === 400) $("again").hidden = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const token = new URLSearchParams(location.hash.slice(1)).get("token");
  history.replaceState(null, "", location.pathname);

  const form = $(token ? "reset" : "forgot");
  form.hidden = false;
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    show(null, "");
    if (token) resetPassword(form, token);
    else requestLink(form);
  });
});
