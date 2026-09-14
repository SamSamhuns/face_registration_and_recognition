// Identify a face: send one image to /recognitions and show the answer.

const video = document.getElementById("video");
const shot = document.getElementById("shot");
const status = document.getElementById("status");
const result = document.getElementById("result");
const capture = document.getElementById("capture");
let stream = null;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

/** List every face. `matched: false` is a normal answer, not a failure. */
function render(reply) {
  if (reply.faces.length === 0) {
    result.innerHTML = `<p class="match">No faces</p>`;
    return;
  }
  result.innerHTML =
    reply.faces
      .map((face) => {
        if (!face.matched) {
          return `<div class="face"><p class="match">Unknown</p>
            <p class="muted">detector confidence ${(face.score * 100).toFixed(0)}%</p></div>`;
        }
        const person = face.match.person;
        const city = person.city ? ", " + escapeHtml(person.city) : "";
        return `<div class="face"><p class="match">${escapeHtml(person.name)}</p>
          <p class="muted">id ${person.id} &middot; ${escapeHtml(person.country)}${city}</p>
          <p class="muted">similarity ${(face.match.similarity * 100).toFixed(1)}%</p></div>`;
      })
      .join("") + `<p class="muted">${reply.detector} + ${reply.recognizer}</p>`;
}

/**
 * Draw the probe image with a box around each face.
 *
 * The canvas is set to the image's own pixel size and the boxes are drawn in those
 * same coordinates, because that is the frame the API measured them in. CSS then
 * scales the whole canvas down to fit. Drawing at the on-screen size instead would
 * need every box rescaled by hand.
 */
async function drawBoxes(blob, faces) {
  const bitmap = await createImageBitmap(blob);
  shot.width = bitmap.width;
  shot.height = bitmap.height;
  const ctx = shot.getContext("2d");
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();

  const line = Math.max(2, bitmap.width / 250);
  ctx.lineWidth = line;
  ctx.font = `${Math.max(16, bitmap.width / 32)}px system-ui, sans-serif`;
  ctx.textBaseline = "bottom";

  for (const face of faces) {
    const { x1, y1, x2, y2 } = face.box;
    const label = face.matched ? face.match.person.name : "unknown";
    ctx.strokeStyle = face.matched ? "#3fb950" : "#f85149";
    ctx.fillStyle = ctx.strokeStyle;
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    ctx.fillText(label, x1, Math.max(y1 - line, parseInt(ctx.font)));
  }
}

async function identify(blob) {
  const data = new FormData();
  data.append("image", blob, "probe.jpg");

  capture.disabled = true;
  setStatus(status, "Searching...", "info");
  try {
    const reply = await request(`${API}/recognitions`, { method: "POST", body: data });
    await drawBoxes(blob, reply.faces);
    shot.hidden = false;
    video.hidden = true;
    render(reply);
    clearStatus(status);
  } catch (error) {
    result.innerHTML = "";
    setStatus(status, error.message, "bad");
  } finally {
    capture.disabled = false;
  }
}

document.getElementById("start").addEventListener("click", async () => {
  try {
    stream = await startCamera(video);
    video.hidden = false;
    shot.hidden = true;
    capture.disabled = false;
    clearStatus(status);
  } catch (error) {
    setStatus(status, error.message, "bad");
  }
});

capture.addEventListener("click", async () => {
  try {
    await identify(await captureBlob(video));
  } catch (error) {
    setStatus(status, error.message, "bad");
  }
});

document.getElementById("file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) {
    stopCamera(stream);
    identify(file);
  }
});
