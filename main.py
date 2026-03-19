"""
shop.masonborda.com — Autonomous Agent Shop MCP Server
Fully autonomous: agent pays USDC on Base → order created → Printful ships

Tools:
  search_products   — free
  get_product       — free
  get_quote         — free (returns USDC price + payment address)
  place_order       — agent sends USDC, server verifies on-chain, creates order
  get_order_status  — free
"""

import os
import time
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.requests import Request
from typing import Optional

app = FastAPI(title="shop.masonborda.com MCP", version="2.0.0")

# --- Config ---
SHOPIFY_STORE   = os.environ.get("SHOPIFY_STORE", "t0uqna-qr.myshopify.com")
SHOPIFY_TOKEN   = os.environ.get("SHOPIFY_TOKEN", "")
PRINTFUL_TOKEN  = os.environ.get("PRINTFUL_TOKEN", "")
PAYMENT_WALLET  = os.environ.get("X402_WALLET", "0xaB967e23686CDD52238723A1DDa9BAb8f81b181C")

# Base network USDC contract
USDC_CONTRACT   = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_RPC        = "https://mainnet.base.org"

SHOPIFY_BASE    = f"https://{SHOPIFY_STORE}/admin/api/2024-01"
SHOPIFY_HEADERS = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json",
}
PRINTFUL_BASE    = "https://api.printful.com"
PRINTFUL_HEADERS = {"Authorization": f"Bearer {PRINTFUL_TOKEN}"}


# --- MCP Manifest ---
@app.get("/.well-known/mcp.json")
async def mcp_manifest():
    return {
        "name": "shop.masonborda.com",
        "description": (
            "Autonomous agent shop. Browse products, get a USDC price quote, "
            "send USDC on Base, and place a fully paid physical order — no credit card, "
            "no human checkout. Printful handles production and shipping."
        ),
        "version": "2.0.0",
        "payment": {
            "wallet": PAYMENT_WALLET,
            "network": "base",
            "token": "USDC",
            "contract": USDC_CONTRACT,
        },
        "tools": [
            {
                "name": "search_products",
                "description": "Search products by keyword. Returns id, title, price in USD, variants.",
                "price": None,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                },
            },
            {
                "name": "get_product",
                "description": "Get full details for a product including all variants and images.",
                "price": None,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                    },
                    "required": ["product_id"],
                },
            },
            {
                "name": "get_quote",
                "description": (
                    "Get a USDC price quote for a product + shipping. "
                    "Returns total USDC amount to send, payment wallet address, and a quote_id. "
                    "Quote is valid for 10 minutes."
                ),
                "price": None,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "variant_id": {"type": "string"},
                        "quantity": {"type": "integer", "default": 1},
                        "shipping_address": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "address1": {"type": "string"},
                                "city": {"type": "string"},
                                "province": {"type": "string", "description": "State/province code e.g. CA"},
                                "zip": {"type": "string"},
                                "country_code": {"type": "string", "description": "ISO 2-letter e.g. US"},
                            },
                            "required": ["name", "address1", "city", "zip", "country_code"],
                        },
                    },
                    "required": ["variant_id", "shipping_address"],
                },
            },
            {
                "name": "place_order",
                "description": (
                    "Place a fully paid order. "
                    "Send the exact USDC amount from get_quote to the payment wallet on Base, "
                    "then call this tool with the transaction hash. "
                    "Server verifies payment on-chain and creates the order. "
                    "Printful produces and ships the item."
                ),
                "price": "product price in USDC (see get_quote)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "quote_id": {"type": "string", "description": "From get_quote"},
                        "tx_hash": {"type": "string", "description": "Base transaction hash of USDC payment"},
                        "variant_id": {"type": "string"},
                        "quantity": {"type": "integer", "default": 1},
                        "shipping_address": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "address1": {"type": "string"},
                                "address2": {"type": "string"},
                                "city": {"type": "string"},
                                "province": {"type": "string"},
                                "zip": {"type": "string"},
                                "country_code": {"type": "string"},
                                "phone": {"type": "string"},
                            },
                            "required": ["name", "address1", "city", "zip", "country_code"],
                        },
                        "email": {"type": "string", "description": "Optional — for order confirmation"},
                    },
                    "required": ["quote_id", "tx_hash", "variant_id", "shipping_address"],
                },
            },
            {
                "name": "get_order_status",
                "description": "Get order status and Printful tracking info by order ID.",
                "price": None,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                    },
                    "required": ["order_id"],
                },
            },
        ],
    }


# --- Helpers ---

async def shopify_get(path: str, params: dict = {}):
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{SHOPIFY_BASE}/{path}", headers=SHOPIFY_HEADERS, params=params)
        r.raise_for_status()
        return r.json()

async def shopify_post(path: str, body: dict):
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{SHOPIFY_BASE}/{path}", headers=SHOPIFY_HEADERS, json=body)
        r.raise_for_status()
        return r.json()

async def verify_usdc_payment(tx_hash: str, expected_amount_usdc: float, to_wallet: str) -> dict:
    """Verify a USDC transfer on Base via eth_getTransactionReceipt."""
    # USDC Transfer event topic
    TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    
    async with httpx.AsyncClient(timeout=20) as client:
        # Get transaction receipt
        r = await client.post(BASE_RPC, json={
            "jsonrpc": "2.0",
            "method": "eth_getTransactionReceipt",
            "params": [tx_hash],
            "id": 1,
        })
        receipt = r.json().get("result")
        
        if not receipt:
            return {"verified": False, "reason": "Transaction not found or not confirmed yet"}
        
        if receipt.get("status") != "0x1":
            return {"verified": False, "reason": "Transaction failed on-chain"}
        
        # Check logs for USDC Transfer to our wallet
        expected_usdc_wei = int(expected_amount_usdc * 1_000_000)  # USDC has 6 decimals
        to_wallet_padded = "0x000000000000000000000000" + to_wallet[2:].lower()
        
        for log in receipt.get("logs", []):
            if (log.get("address", "").lower() == USDC_CONTRACT.lower()
                and len(log.get("topics", [])) >= 3
                and log["topics"][0].lower() == TRANSFER_TOPIC.lower()
                and log["topics"][2].lower() == to_wallet_padded.lower()):
                
                amount_hex = log.get("data", "0x0")
                amount = int(amount_hex, 16)
                
                # Allow up to 1% slippage
                if amount >= int(expected_usdc_wei * 0.99):
                    return {
                        "verified": True,
                        "amount_usdc": amount / 1_000_000,
                        "block": int(receipt.get("blockNumber", "0x0"), 16),
                    }
        
        return {"verified": False, "reason": f"No USDC transfer found to {to_wallet} in this transaction"}


# In-memory quote store (replace with Redis in production)
_quotes = {}

def make_quote_id(variant_id: str, quantity: int) -> str:
    return f"q_{variant_id}_{quantity}_{int(time.time())}"


# --- Tool: search_products ---
@app.post("/tools/search_products")
async def search_products(request: Request):
    body = await request.json()
    query = body.get("query", "")
    limit = body.get("limit", 10)

    # Use full-text search if available, fall back to title filter
    params = {"limit": limit, "status": "active"}
    if query:
        params["title"] = query
    data = await shopify_get("products.json", params)
    products = data.get("products", [])

    return {
        "products": [
            {
                "id": str(p["id"]),
                "title": p["title"],
                "handle": p["handle"],
                "url": f"https://shop.masonborda.com/products/{p['handle']}",
                "variants": [
                    {
                        "id": str(v["id"]),
                        "title": v["title"],
                        "price_usd": float(v["price"]),
                        "price_usdc": float(v["price"]),  # 1:1 peg
                        "sku": v.get("sku", ""),
                    }
                    for v in p.get("variants", [])
                ],
                "images": [img["src"] for img in p.get("images", [])[:1]],
            }
            for p in products
        ],
        "count": len(products),
    }


# --- Tool: get_product ---
@app.post("/tools/get_product")
async def get_product(request: Request):
    body = await request.json()
    product_id = body.get("product_id")

    data = await shopify_get(f"products/{product_id}.json")
    p = data["product"]

    return {
        "id": str(p["id"]),
        "title": p["title"],
        "description": p.get("body_html", "").replace("<p>", "").replace("</p>", "\n").strip(),
        "handle": p["handle"],
        "url": f"https://shop.masonborda.com/products/{p['handle']}",
        "variants": [
            {
                "id": str(v["id"]),
                "title": v["title"],
                "price_usd": float(v["price"]),
                "price_usdc": float(v["price"]),
                "sku": v.get("sku", ""),
                "available": v.get("inventory_quantity", 1) > 0,
            }
            for v in p.get("variants", [])
        ],
        "images": [img["src"] for img in p.get("images", [])],
    }


# --- Tool: get_quote ---
@app.post("/tools/get_quote")
async def get_quote(request: Request):
    body = await request.json()
    variant_id = body.get("variant_id")
    quantity = body.get("quantity", 1)
    address = body.get("shipping_address", {})

    # Get variant price from Shopify
    data = await shopify_get(f"variants/{variant_id}.json")
    variant = data["variant"]
    unit_price = float(variant["price"])
    subtotal = unit_price * quantity

    # Standard shipping estimate (US $5, international $15)
    country = address.get("country_code", "US")
    shipping = 5.0 if country == "US" else 15.0
    total_usdc = round(subtotal + shipping, 2)

    quote_id = make_quote_id(variant_id, quantity)
    _quotes[quote_id] = {
        "variant_id": variant_id,
        "quantity": quantity,
        "total_usdc": total_usdc,
        "shipping_address": address,
        "expires_at": time.time() + 600,  # 10 min
        "product_title": variant.get("title", ""),
    }

    return {
        "quote_id": quote_id,
        "product": variant.get("title", ""),
        "quantity": quantity,
        "subtotal_usdc": subtotal,
        "shipping_usdc": shipping,
        "total_usdc": total_usdc,
        "payment_wallet": PAYMENT_WALLET,
        "network": "base",
        "token": "USDC",
        "token_contract": USDC_CONTRACT,
        "instructions": (
            f"Send exactly {total_usdc} USDC on Base network to {PAYMENT_WALLET}, "
            f"then call place_order with the transaction hash and this quote_id."
        ),
        "expires_in": "10 minutes",
    }


# --- Tool: place_order ---
@app.post("/tools/place_order")
async def place_order(request: Request):
    body = await request.json()
    quote_id = body.get("quote_id")
    tx_hash = body.get("tx_hash")
    variant_id = body.get("variant_id")
    quantity = body.get("quantity", 1)
    address = body.get("shipping_address", {})
    email = body.get("email", "")

    # Validate quote
    quote = _quotes.get(quote_id)
    if not quote:
        raise HTTPException(400, "Quote not found. Call get_quote first.")
    if time.time() > quote["expires_at"]:
        raise HTTPException(400, "Quote expired. Call get_quote again.")

    expected_usdc = quote["total_usdc"]

    # Verify payment on Base
    verification = await verify_usdc_payment(tx_hash, expected_usdc, PAYMENT_WALLET)
    if not verification["verified"]:
        raise HTTPException(402, f"Payment not verified: {verification['reason']}")

    # Build Shopify order (already paid)
    name_parts = address.get("name", "Agent Buyer").split(" ", 1)
    order_payload = {
        "order": {
            "line_items": [{"variant_id": int(variant_id), "quantity": quantity}],
            "financial_status": "paid",
            "fulfillment_status": None,
            "send_receipt": bool(email),
            "send_fulfillment_receipt": True,
            "note": f"Paid via USDC on Base | tx: {tx_hash} | quote: {quote_id}",
            "shipping_address": {
                "first_name": name_parts[0],
                "last_name": name_parts[1] if len(name_parts) > 1 else "",
                "address1": address.get("address1", ""),
                "address2": address.get("address2", ""),
                "city": address.get("city", ""),
                "province": address.get("province", ""),
                "zip": address.get("zip", ""),
                "country_code": address.get("country_code", "US"),
                "phone": address.get("phone", ""),
            },
            "transactions": [
                {
                    "kind": "sale",
                    "status": "success",
                    "amount": str(expected_usdc),
                    "gateway": "USDC on Base",
                }
            ],
        }
    }
    if email:
        order_payload["order"]["email"] = email

    result = await shopify_post("orders.json", order_payload)
    order = result["order"]

    # Remove used quote
    _quotes.pop(quote_id, None)

    return {
        "success": True,
        "order_id": str(order["id"]),
        "order_number": order.get("order_number"),
        "status": order.get("fulfillment_status") or "unfulfilled",
        "payment_verified": True,
        "tx_hash": tx_hash,
        "amount_paid_usdc": verification.get("amount_usdc", expected_usdc),
        "shipping_to": address.get("name"),
        "message": "Order created. Printful will produce and ship your item. Use get_order_status to track.",
    }


# --- Tool: get_order_status ---
@app.post("/tools/get_order_status")
async def get_order_status(request: Request):
    body = await request.json()
    order_id = body.get("order_id")

    data = await shopify_get(f"orders/{order_id}.json")
    order = data["order"]

    # Try Printful
    printful_data = None
    async with httpx.AsyncClient(timeout=10) as client:
        pf = await client.get(f"{PRINTFUL_BASE}/orders/@{order_id}", headers=PRINTFUL_HEADERS)
        if pf.status_code == 200:
            pf_result = pf.json().get("result", {})
            shipments = pf_result.get("shipments", [])
            printful_data = {
                "status": pf_result.get("status"),
                "tracking": {
                    "carrier": shipments[0].get("carrier") if shipments else None,
                    "tracking_number": shipments[0].get("tracking_number") if shipments else None,
                    "tracking_url": shipments[0].get("tracking_url") if shipments else None,
                } if shipments else None,
            }

    return {
        "order_id": str(order["id"]),
        "order_number": order.get("order_number"),
        "financial_status": order.get("financial_status"),
        "fulfillment_status": order.get("fulfillment_status") or "unfulfilled",
        "created_at": order.get("created_at"),
        "printful": printful_data,
    }


# --- Health ---
@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0", "store": SHOPIFY_STORE, "payment_wallet": PAYMENT_WALLET}
