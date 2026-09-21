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
  const headers = { ...(options.headers || {}), Authorization: `Bearer ${accessToken()}` };
  const response = await fetch(path, { ...options, headers });
  // 401 and 403 are different answers and deserve different words. 401 means the
  // token is missing or stale; 403 means it is fine and this person simply may not.
  if (response.status === 401) {
    throw new Error("You are not signed in, or the session has expired. Sign in again.");
  }
  if (response.status === 403) {
    throw new Error("Your account is not in a group that permits this action.");
  }
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

/**
 * Fetch an image from a protected route and return an object URL for it.
 *
 * An <img src="..."> is a plain GET that carries no custom header, so it cannot
 * send the bearer token and would come back 401. Fetching it here, then handing the
 * element a blob: URL, is the way to show an image from an authenticated route.
 *
 * The caller should revokeObjectURL when the image is gone, or the blob stays in
 * memory for the life of the page.
 */
async function fetchImageUrl(path) {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${accessToken()}` } });
  if (!response.ok) throw new Error(`image request failed with status ${response.status}`);
  return URL.createObjectURL(await response.blob());
}

// -------------------------------------------------------------------------- nav

/** Mark the current page in the header. */
function markActiveLink() {
  const here = location.pathname.split("/").pop() || "enroll.html";
  document.querySelectorAll("header a").forEach((a) => {
    if (a.getAttribute("href") === here) a.classList.add("active");
  });
}

/**
 * Show who is signed in, with a way out. Or a way in, when nobody is.
 *
 * The name is read out of the token without verifying it, which is fine for a label:
 * faking it changes what this header says and nothing else. Every route is decided
 * by the API, from the signature.
 */
function addAuthControl() {
  const header = document.querySelector("header");
  if (!header) return;
  const claims = tokenClaims();

  if (!claims) {
    const button = document.createElement("button");
    button.textContent = "Sign in";
    button.addEventListener("click", () => login());
    header.append(button);
    return;
  }

  const who = document.createElement("span");
  who.className = "who";
  who.textContent = claims.preferred_username || claims.email || claims.sub;
  const button = document.createElement("button");
  button.className = "secondary";
  button.textContent = "Sign out";
  button.addEventListener("click", logout);
  header.append(who, button);
}

document.addEventListener("DOMContentLoaded", async () => {
  markActiveLink();
  // A redirect back from Authentik arrives with ?code=. Handling it ends in a
  // navigation, so there is nothing else to draw.
  if (await completeLogin()) return;
  addAuthControl();
  // Nobody is signed in, so go and do that rather than showing a page of 401s.
  if (!accessToken()) await login();
});
