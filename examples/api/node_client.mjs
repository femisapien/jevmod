// Call a running `jevmod api` from Node 18+ (global fetch): mint a tenant key, moderate a batch.
const URL = process.env.JEVMOD_API_URL ?? "http://localhost:8080";

async function post(path, token, body) {
  const res = await fetch(URL + path, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path}: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function moderate(apiKey, texts, topic = "") {
  const messages = texts.map((text, i) => ({ id: String(i), text, channel_topic: topic }));
  return (await post("/v1/moderate", apiKey, { messages })).decisions;
}

const admin = process.env.JEVMOD_ADMIN_TOKEN;
if (!admin) throw new Error("set JEVMOD_ADMIN_TOKEN to the value the API was started with");
const { api_key } = await post("/v1/keys", admin, { tenant: "example-node", label: "node_client.mjs" });
for (const d of await moderate(api_key, ["FREE NITRO!! claim at discord-gifts.ru/nitro", "did the patch fix the bug?"])) {
  console.log(d.message_id, d.action, d.category, d.probability);
}
