// Identify a face: send one image to /recognitions and show the answer.

const video = document.getElementById("video");
const shot = document.getElementById("shot");
const status = document.getElementById("status");
const result = document.getElementById("result");
const capture = document.getElementById("capture");
let stream = null;

/** Draw the reply. `matched: false` is a normal answer, not a failure. */
function render(reply) {
  if (!reply.matched) {
    result.innerHTML = `<p class="match">No match</p>
      <p class="muted">Nobody in the database is close enough.</p>
      <p class="muted">${reply.detector} + ${reply.recognizer}</p>`;
    return;
  }
  const person = reply.match.person;
  const percent = (reply.match.similarity * 100).toFixed(1);
  result.innerHTML = `<p class="match">${person.name}</p>
    <p class="muted">id ${person.id} &middot; ${person.country}${person.city ? ", " + person.city : ""}</p>
    <p class="muted">similarity ${percent}%</p>
    <p class="muted">${reply.detector} + ${reply.recognizer}</p>`;
}

async function identify(blob) {
  shot.src = URL.createObjectURL(blob);
  shot.hidden = false;
  video.hidden = true;

  const data = new FormData();
  data.append("image", blob, "probe.jpg");

  capture.disabled = true;
  setStatus(status, "Searching...", "info");
  try {
    render(await request(`${API}/recognitions`, { method: "POST", body: data }));
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
