# Frontend

Three static pages served by nginx over HTTPS: enroll, recognize and manage.

```
browser ──https://host:8443──▶ nginx ─┬─ /              static pages
                                      └─ /api/, /health ──http──▶ api:8080
```

## Why nginx also proxies the API

The camera needs a **secure context**. `navigator.mediaDevices.getUserMedia` exists
only on an HTTPS page, or on `localhost`. Open the page as `http://<address>` and the
camera is simply not there.

An HTTPS page then may not call an HTTP address. The browser calls that mixed content
and blocks it. So an HTTPS frontend and a plain HTTP API cannot talk.

Proxying the API under the same origin answers both problems at once, and removes a
third: with one origin there is no CORS, so the browser sends no preflight request
and `CORS_ALLOW_ORIGINS` does not matter. The API keeps speaking plain HTTP inside the
Docker network, where nothing outside can reach it.

## Start it

```bash
cd face_reg_recog_milvus

# Once. Add the LAN address if you open the UI from another device, because the
# browser checks the address you type against the certificate.
./scripts/generate_dev_cert.sh 192.0.2.10

docker compose up -d
```

Open `https://localhost:8443`, or `https://<lan-address>:8443`.

The certificate is self-signed, so the browser warns once and you accept it. On
`localhost` there is no warning, because localhost is already a secure context.

Certificates are written to `frontend/certs/` and are not tracked by git. They are
for development. Use a real certificate for anything else.

## Files

```
frontend/
  nginx.conf          TLS, static root, and the /api proxy
  certs/              self-signed certificate, not tracked
  public/
    enroll.html       register a person, with the form and a face
    recognize.html    identify one face
    manage.html       list registered persons, and remove one
    app.js            shared: requests, camera, status messages
    enroll.js  recognize.js  manage.js
    style.css
```

No build step, no package manager, no framework. Edit a file and reload the page.
The directory is bind-mounted, so nginx needs no restart.

## Things that will catch you

**`client_max_body_size`.** nginx allows 1 MB by default and answers 413 before the
request reaches the API. `nginx.conf` raises it to 12 MB, above the 10 MB
`MAX_UPLOAD_BYTES`. Without that line, a photograph from a modern phone fails.

**Filename on the upload.** `FormData.append("image", blob, "capture.jpg")` needs the
third argument. Without it the part carries no content type and the API answers 415.

**Stop the camera.** A stream that is not stopped keeps the camera light on. The
pages call `stopCamera()` after a capture.

**The manage page shows no photographs.** Registered images are stored in the
`person_images` volume, but no endpoint serves them. Showing them needs a new route.
