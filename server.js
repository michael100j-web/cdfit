// Serves ./src over HTTPS on https://localhost:3000 using Office's trusted dev certificate.
// `node server.js --http` serves plain HTTP (browser preview only; Word needs HTTPS).
const fs = require("fs");
const path = require("path");
const PORT = Number(process.env.PORT) || 3000;
const ROOT = path.join(__dirname, "src");
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json", ".ico": "image/x-icon" };

function handler(req, res) {
  let p = decodeURIComponent(new URL(req.url, "https://localhost").pathname);
  if (p === "/") p = "/taskpane.html";
  const file = path.normalize(path.join(ROOT, p));
  if (!file.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); return res.end("Not found"); }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream", "Cache-Control": "no-cache" });
    res.end(data);
  });
}

(async () => {
  if (process.argv.includes("--http")) {
    require("http").createServer(handler).listen(PORT, () => console.log(`CD Fit preview: http://localhost:${PORT}/taskpane.html`));
    return;
  }
  const devCerts = require("office-addin-dev-certs");
  const options = await devCerts.getHttpsServerOptions(); // installs/trusts the localhost dev certificate on first run
  require("https").createServer(options, handler).listen(PORT, () => console.log(`CD Fit add-in: https://localhost:${PORT}/taskpane.html`));
})();
