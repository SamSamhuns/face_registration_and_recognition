// List registered persons, one page at a time, and remove them.

const rows = document.getElementById("rows");
const status = document.getElementById("status");
const prev = document.getElementById("prev");
const next = document.getElementById("next");
const count = document.getElementById("count");

const LIMIT = 20;
let offset = 0;

function escapeHtml(value) {
  // Names come from whoever registered them, so they are never trusted markup.
  return String(value).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

async function remove(id, name) {
  if (!confirm(`Remove ${name} (id ${id})? This deletes the record and the face vector.`)) return;
  try {
    await request(`${API}/persons/${id}`, { method: "DELETE" });
    setStatus(status, `Removed id ${id}.`, "ok");
    await load();
  } catch (error) {
    setStatus(status, error.message, "bad");
  }
}

async function load() {
  try {
    const page = await request(`${API}/persons?limit=${LIMIT}&offset=${offset}`);
    rows.innerHTML = page.items
      .map(
        (p) => `<tr>
          <td>${p.id}</td><td>${escapeHtml(p.name)}</td><td>${p.birthdate}</td>
          <td>${escapeHtml(p.country)}</td><td>${escapeHtml(p.city)}</td>
          <td><button class="danger" data-id="${p.id}" data-name="${escapeHtml(p.name)}">Remove</button></td>
        </tr>`,
      )
      .join("");

    if (page.total === 0) {
      rows.innerHTML = `<tr><td colspan="6" class="muted">Nobody registered yet.</td></tr>`;
    }
    count.textContent = `${offset + page.items.length} of ${page.total}`;
    prev.disabled = offset === 0;
    next.disabled = offset + LIMIT >= page.total;
  } catch (error) {
    setStatus(status, error.message, "bad");
  }
}

// One listener on the table, so rows added later need no listener of their own.
rows.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-id]");
  if (button) remove(button.dataset.id, button.dataset.name);
});

prev.addEventListener("click", () => {
  offset = Math.max(0, offset - LIMIT);
  load();
});
next.addEventListener("click", () => {
  offset += LIMIT;
  load();
});

load();
