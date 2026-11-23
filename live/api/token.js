// Vercel serverless function: hands the live-call page a short-lived LiveKit token.
// Keeps the LiveKit secret off the web page. Environment variables (set in Vercel, never in the repo):
//   LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, DEMO_PASSCODE (optional)
import { AccessToken } from "livekit-server-sdk";
import { randomBytes } from "node:crypto";

const recent = []; // per-instance rate limit: a soft guard, LiveKit's own concurrency cap is the hard one
const PER_MINUTE = 6;

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "content-type");
  res.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
  if (req.method === "OPTIONS") return res.status(204).end();

  const passcode = process.env.DEMO_PASSCODE || "";
  if (req.method === "GET") return res.status(200).json({ ok: true, passcode_required: Boolean(passcode) });
  if (process.env.DEMO_DISABLED === "1") return res.status(503).json({ error: "The live demo is switched off right now." });

  const now = Date.now();
  while (recent.length && now - recent[0] > 60000) recent.shift();
  if (recent.length >= PER_MINUTE) return res.status(429).json({ error: "Too many calls started in the last minute. Try again shortly." });

  const body = typeof req.body === "string" ? JSON.parse(req.body || "{}") : req.body || {};
  if (passcode && body.passcode !== passcode) return res.status(401).json({ error: "That passcode is not right." });
  recent.push(now);

  const cfg = {
    mode: body.mode === "existing" ? "existing" : "new",
    persona: String(body.persona || "").slice(0, 30),
    business: String(body.business || "").slice(0, 60),
    keyterms: (Array.isArray(body.keyterms) ? body.keyterms : []).slice(0, 30).map((k) => String(k).slice(0, 40)),
    hours: String(body.hours || "").slice(0, 60),
    voice: String(body.voice || "").slice(0, 40),
    greeting: String(body.greeting || "").slice(0, 300),
    rules: String(body.rules || "").slice(0, 700),
    service_area: String(body.service_area || "").slice(0, 120),
    services: (Array.isArray(body.services) ? body.services : []).slice(0, 6).map((k) => String(k).slice(0, 40)),
  };
  const room = `demo-${randomBytes(4).toString("hex")}`;
  const at = new AccessToken(process.env.LIVEKIT_API_KEY, process.env.LIVEKIT_API_SECRET, {
    identity: `caller-${randomBytes(3).toString("hex")}`,
    name: "Caller",
    metadata: JSON.stringify(cfg),
    ttl: "10m",
  });
  at.addGrant({ roomJoin: true, room, canPublish: true, canSubscribe: true, canPublishData: true });
  return res.status(200).json({ token: await at.toJwt(), url: process.env.LIVEKIT_URL, room });
}
