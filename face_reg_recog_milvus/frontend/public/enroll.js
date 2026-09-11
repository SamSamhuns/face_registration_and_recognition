// Register a person: collect the form fields, attach one face image, POST /persons.

const video = document.getElementById("video");
const shot = document.getElementById("shot");
const status = document.getElementById("status");
const form = document.getElementById("form");
const submit = document.getElementById("submit");
let stream = null;
let image = null; // Blob, from the camera or from the file picker

/** Show the chosen image and allow the form to be sent. */
function useImage(blob) {
  image = blob;
  shot.src = URL.createObjectURL(blob);
  shot.hidden = false;
  video.hidden = true;
  submit.disabled = false;
  setStatus(status, "Image ready. Fill the form and register.", "info");
}

document.getElementById("start").addEventListener("click", async () => {
  try {
    stream = await startCamera(video);
    video.hidden = false;
    shot.hidden = true;
    document.getElementById("capture").disabled = false;
    clearStatus(status);
  } catch (error) {
    setStatus(status, error.message, "bad");
  }
});

document.getElementById("capture").addEventListener("click", async () => {
  try {
    useImage(await captureBlob(video));
    stopCamera(stream);
  } catch (error) {
    setStatus(status, error.message, "bad");
  }
});

document.getElementById("file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) {
    stopCamera(stream);
    useImage(file);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!image) return;

  // Flat multipart fields, the same shape the API declares. The filename matters:
  // without it the browser sends the part with no content type, and the API
  // answers 415.
  const data = new FormData(form);
  data.append("image", image, "capture.jpg");

  submit.disabled = true;
  setStatus(status, "Registering...", "info");
  try {
    const person = await request(`${API}/persons`, { method: "POST", body: data });
    setStatus(status, `Registered ${person.name} with id ${person.id}.`, "ok");
    form.reset();
    image = null;
    shot.hidden = true;
  } catch (error) {
    setStatus(status, error.message, "bad");
    submit.disabled = false;
  }
});
