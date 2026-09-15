"""Which vision-capable OpenRouter models can this key actually call?

The account is behind a model allowlist (issue #15), not a privacy setting, so the
reachable set cannot be read off `GET /api/v1/models` — it has to be probed. A blocked
model 404s before any billing, so probing the blocked ones is free; a reachable one
bills for a 32x32 image, which is fractions of a cent.

    ./venv/bin/python eval/vision_sweep/probe.py            # probe, write reachable.json
    ./venv/bin/python eval/vision_sweep/probe.py --list     # print the candidate set only
"""

import argparse
import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parents[1]
BASE_URL = "https://openrouter.ai/api/v1"

# A 32x32 white PNG: the probe asks whether an endpoint exists, not whether the model
# can read. 32x32 and not 1x1 because a 1x1 image makes several providers answer
# HTTP 400 "Provider returned error", which is indistinguishable from a real block —
# 32x32 is the smallest size that every provider tested accepts. Kept inline so the
# probe has no asset dependency.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAN0lEQVR4nO3RwQ0AMAjDwJT9d05H"
    "MB9+vgGCZF7bXJrT9XhgwR8gEyETIRMhEyETIRMhEyEThXzH8QM9OMM6fAAAAABJRU5ErkJggg=="
)

# Aliases and image-generation models are not candidates: an alias measures whatever it
# currently points at, which is not reproducible, and an image generator cannot read.
def is_candidate(model: dict) -> bool:
    mid = model["id"]
    if mid.endswith("-latest") or mid.startswith("openrouter/"):
        return False
    out = (model.get("architecture") or {}).get("output_modalities") or []
    if "image" in out:
        return False
    return "image" in ((model.get("architecture") or {}).get("input_modalities") or [])


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env = BACKEND_ROOT / ".env"
    for line in env.read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("no OPENROUTER_API_KEY in the environment or packages/backend/.env")


async def fetch_vision_models(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get(f"{BASE_URL}/models")
    r.raise_for_status()
    return [m for m in r.json()["data"] if is_candidate(m)]


async def probe_one(
    client: httpx.AsyncClient, key: str, model_id: str, sem, zdr: bool = True
) -> dict:
    body = {
        "model": model_id,
        # zdr is the policy decided in issue #15 — probe under the conditions the
        # product will run in, or the reachable set measured here is not the one
        # the product gets. `--no-zdr` measures what the account allowlist alone
        # permits, which is what tells the two barriers apart.
        **({"provider": {"zdr": True}} if zdr else {}),
        # 16 and not 4: a small budget makes reasoning models spend it all on thinking
        # and answer nothing, and one provider rejects the request outright.
        "max_tokens": 16,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hi"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(TINY_PNG).decode()
                        },
                    },
                ],
            }
        ],
    }
    async with sem:
        r = None
        # A bare "Provider returned error" 400 is transient often enough that one
        # attempt would report a reachable model as blocked.
        for attempt in range(2):
            try:
                r = await client.post(
                    f"{BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                    timeout=120.0,
                )
            except Exception as exc:  # network, not an API verdict
                if attempt:
                    return {"model": model_id, "status": None, "error": repr(exc)}
                await asyncio.sleep(2)
                continue
            if r.status_code != 400 or attempt:
                break
            await asyncio.sleep(2)
    out = {"model": model_id, "status": r.status_code}
    try:
        payload = r.json()
    except Exception:
        out["error"] = r.text[:200]
        return out
    if r.status_code == 200:
        out["cost"] = ((payload.get("usage") or {}).get("cost"))
        out["prompt_tokens"] = ((payload.get("usage") or {}).get("prompt_tokens"))
    else:
        out["error"] = ((payload.get("error") or {}).get("message") or "")[:200]
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="print candidates, probe nothing")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument(
        "--no-zdr",
        action="store_true",
        help="drop provider.zdr, to separate the allowlist barrier from the ZDR one",
    )
    ap.add_argument("--out", default="reachable.json")
    ap.add_argument("--only", help="comma-separated models, instead of the full list")
    args = ap.parse_args()

    key = api_key()
    async with httpx.AsyncClient() as client:
        models = await fetch_vision_models(client)
        ids = sorted(m["id"] for m in models)
        if args.only:
            ids = [m.strip() for m in args.only.split(",") if m.strip()]
        print(f"{len(ids)} vision-capable candidates after dropping aliases and generators")
        if args.list:
            for i in ids:
                print(" ", i)
            return
        sem = asyncio.Semaphore(args.concurrency)
        results = await asyncio.gather(
            *(probe_one(client, key, i, sem, zdr=not args.no_zdr) for i in ids)
        )

    reachable = sorted(r["model"] for r in results if r["status"] == 200)
    spent = sum(r.get("cost") or 0 for r in results)
    out = HERE / args.out
    out.write_text(json.dumps({"reachable": reachable, "probe": results}, indent=2))
    print(f"reachable: {len(reachable)} of {len(ids)}   probe cost ${spent:.4f}")
    for m in reachable:
        print("  ", m)
    print(f"written to {out}")


if __name__ == "__main__":
    asyncio.run(main())
