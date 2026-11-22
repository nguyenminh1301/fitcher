// Loaded before the Next.js server (`node --require ./peer-address.cjs server.js`): every request the web
// server accepts carries X-Fitcher-Peer set to the address of the connection it arrived on, and X-Fitcher-Proxy
// set to the signs that a reverse proxy relayed it (empty when there are none). Values the client sent are
// replaced, never trusted, so the api can tell a browser on this computer from another machine that only claims
// `Host: localhost`, and from a proxy on this computer that relays the internet to the port
// (apps/api/app/auth/origin.py). Route handlers pass both headers on to the api with the browser's other address
// headers (lib/server/api.ts).

const http = require("node:http");

const PEER_HEADER = "x-fitcher-peer";
const PROXY_HEADER = "x-fitcher-proxy";

// Headers a browser never sends itself and a reverse proxy or tunnel adds to say whom it relays.
const PROXY_HEADERS = [
  "forwarded", "via", "x-real-ip", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port",
  "x-forwarded-server", "cf-connecting-ip", "true-client-ip", "x-client-ip",
];

/**
 * The signs that a reverse proxy relayed a request. A stock nginx `proxy_pass` adds no forwarding header but
 * always asks its upstream to close the connection (and speaks HTTP/1.0 unless configured otherwise), which no
 * browser does; a script that does the same is told to drop it rather than being taken for the owner.
 */
function proxyEvidence(request) {
  const evidence = PROXY_HEADERS.filter((name) => request.headers[name] !== undefined);
  const connection = String(request.headers.connection ?? "").toLowerCase().split(",").map((token) => token.trim());
  if (connection.includes("close")) evidence.push("connection: close");
  if (request.httpVersion === "1.0") evidence.push("http/1.0");
  return evidence.join(", ");
}

function markPeer(request) {
  const peer = request.socket?.remoteAddress ?? "";
  const proxy = proxyEvidence(request);
  request.headers[PEER_HEADER] = peer;
  request.headers[PROXY_HEADER] = proxy;
  const raw = [];
  for (let index = 0; index + 1 < request.rawHeaders.length; index += 2) {
    const name = request.rawHeaders[index].toLowerCase();
    if (name !== PEER_HEADER && name !== PROXY_HEADER) raw.push(request.rawHeaders[index], request.rawHeaders[index + 1]);
  }
  raw.push(PEER_HEADER, peer, PROXY_HEADER, proxy);
  request.rawHeaders.splice(0, request.rawHeaders.length, ...raw);
}

if (!http.Server.prototype.__fitcherPeerAddress) {
  const emit = http.Server.prototype.emit;
  http.Server.prototype.emit = function emitWithPeer(event, request, ...rest) {
    if ((event === "request" || event === "upgrade") && request?.headers) markPeer(request);
    return emit.call(this, event, request, ...rest);
  };
  http.Server.prototype.__fitcherPeerAddress = true;
}

module.exports = { PEER_HEADER, PROXY_HEADER, markPeer, proxyEvidence };
