// Shared helpers for the three pages.
//
// Every request goes to a path that starts with /api. nginx serves these pages and
// proxies /api to the API container, so the browser sees one origin. That means no
// CORS preflight, and no mixed content warning on an https page.

const API = "/api/v1";

// --------------------------------------------------------------------- requests

/** Read a message out of an error reply. */
function readError(body, status) {
  if (!body) return `request failed with status ${status}`;
  // The API answers a domain error with {error, detail}.
  if (typeof body.detail === "string") return body.detail;
  // FastAPI answers a bad form field with {detail: [{loc, msg}, ...]}.
  if (Array.isArray(body.detail)) {
    return body.detail.map((d) => `${d.loc?.slice(-1)}: ${d.msg}`).join("; ");
  }
  return `request failed with status ${status}`;
}

/** Send a request. Returns parsed JSON, or null for 204. Throws on any error. */
async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(readError(body, response.status));
  return body;
}

// ----------------------------------------------------------------------- status

/** Show a message under a form. kind is "ok", "bad" or "info". */
function setStatus(element, message, kind = "info") {
  element.textContent = message;
  element.className = `status show ${kind}`;
}

function clearStatus(element) {
  element.className = "status";
}

// ----------------------------------------------------------------------- camera

/**
 * Turn on the camera and show it in a video element.
 *
 * getUserMedia only exists in a secure context: https, or localhost. On a plain
 * http page opened by address, navigator.mediaDevices is undefined, and the
 * failure gives no explanation of its own. So say it here.
 */
async function startCamera(video) {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error(
      "The browser gives no camera here. A camera needs a secure context: " +
        "open the page over https, or on localhost.",
    );
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "user", width: { ideal: 1280 } },
  });
  video.srcObject = stream;
  await video.play();
  return stream;
}

/**
 * Take one frame from the live video and return it as a JPEG Blob.
 *
 * The canvas is sized from video.videoWidth and video.videoHeight, which give the
 * real frame size. The size the element is drawn at on screen is a different
 * number, and using it would rescale the picture for no reason.
 *
 * On the numbers, measured on one face at 1280 px wide:
 *
 *   quality 1.00 -> 1227 KB      quality 0.85 ->  324 KB
 *   quality 0.92 ->  449 KB      quality 0.60 ->  185 KB
 *
 * JPEG quality has very little effect on the embedding. Every setting from 0.30
 * upwards stayed within 0.97 to 0.99 cosine of the quality 1.00 result, with no
 * clear trend, so the differences are noise. Capture width matters more, and even
 * that is forgiving: 640 px wide scored 0.969 and 160 px wide still scored 0.909,
 * against a match threshold of 0.40.
 *
 * So 0.85 is a safe middle. It holds the upload near 300 KB, far below both
 * MAX_UPLOAD_BYTES (10 MB) and the nginx client_max_body_size (12 MB), and loses
 * nothing measurable.
 *
 * Keep the frame at the camera's own size. The recogniser samples the original
 * image, not the 640 x 640 copy the detector works on, so capture detail reaches
 * the embedding.
 */
function captureBlob(video) {
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const context = canvas.getContext("2d");
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => {
    canvas.toBlob(resolve, "image/jpeg", 0.85);
  });
}

/** Stop the camera. A camera left running keeps its light on and drains a laptop. */
function stopCamera(stream) {
  stream?.getTracks().forEach((track) => track.stop());
}

// -------------------------------------------------------------------------- nav

/** Mark the current page in the header. */
function markActiveLink() {
  const here = location.pathname.split("/").pop() || "enroll.html";
  document.querySelectorAll("header a").forEach((a) => {
    if (a.getAttribute("href") === here) a.classList.add("active");
  });
}
document.addEventListener("DOMContentLoaded", markActiveLink);
