// Loaded before the Next.js server (`node --require ./peer-address.cjs server.js`): every request the web
// server accepts carries X-Fitcher-Peer set to the address of the connection it arrived on. A value the
// client sent is replaced, never trusted, so the api can tell a browser on this computer from another
// machine that only claims `Host: localhost` (apps/api/app/auth/origin.py). Route handlers pass the header
// on to the api with the browser's other address headers (lib/server/api.ts).

const http = require("node:http");

const PEER_HEADER = "x-fitcher-peer";

function markPeer(request) {
  const peer = request.socket?.remoteAddress ?? "";
  request.headers[PEER_HEADER] = peer;
  const raw = [];
  for (let index = 0; index + 1 < request.rawHeaders.length; index += 2) {
    if (request.rawHeaders[index].toLowerCase() !== PEER_HEADER) raw.push(request.rawHeaders[index], request.rawHeaders[index + 1]);
  }
  raw.push(PEER_HEADER, peer);
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

module.exports = { PEER_HEADER, markPeer };
