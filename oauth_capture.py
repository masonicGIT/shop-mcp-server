"""
Shopify OAuth token capture server.
Run this, visit the auth URL, approve, and it captures the access token.

Usage:
  SHOPIFY_STORE=yourstore.myshopify.com \
  CLIENT_ID=your_client_id \
  CLIENT_SECRET=your_client_secret \
  python oauth_capture.py
"""
import os
import urllib.parse
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

SHOPIFY_STORE   = os.environ["SHOPIFY_STORE"]
CLIENT_ID       = os.environ["CLIENT_ID"]
CLIENT_SECRET   = os.environ["CLIENT_SECRET"]
REDIRECT_URI    = os.environ.get("REDIRECT_URI", "http://localhost:8082/auth/callback")
SCOPES          = "read_products,read_inventory,write_draft_orders,write_orders,read_orders,read_fulfillments"

@app.get("/")
async def index():
    auth_url = (
        f"https://{SHOPIFY_STORE}/admin/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&scope={SCOPES}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&state=shop_mcp"
    )
    return HTMLResponse(f"""
    <h2>Shopify OAuth</h2>
    <p><a href="{auth_url}" style="font-size:18px; padding:10px; background:#5c6ac4; color:white; text-decoration:none; border-radius:4px">
    Click to authorize Shopify
    </a></p>
    """)

@app.get("/auth/callback")
async def callback(request: Request):
    params = dict(request.query_params)
    code = params.get("code")

    if not code:
        return HTMLResponse(f"<h2>Error</h2><pre>{params}</pre>")

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
            json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "code": code},
        )

    data = r.json()
    token = data.get("access_token", "")
    scope = data.get("scope", "")

    if token:
        with open("/tmp/shopify_token.txt", "w") as f:
            f.write(token)
        print(f"\n✓ ACCESS TOKEN: {token}\n  Scopes: {scope}")
        return HTMLResponse(f"<h2>✅ Success!</h2><p><strong>Token:</strong> <code>{token}</code></p>")
    else:
        return HTMLResponse(f"<h2>Error</h2><pre>{data}</pre>")

if __name__ == "__main__":
    print("\n=== Shopify OAuth Capture ===\nOpen: http://localhost:8082\n")
    uvicorn.run(app, host="0.0.0.0", port=8082)
