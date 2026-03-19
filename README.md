# shop-mcp-server

**Autonomous agent shop MCP server.** Buy physical products with USDC on Base — no credit card, no human checkout.

Live at: **https://mcp.masonborda.com**  
MCP manifest: **https://mcp.masonborda.com/.well-known/mcp.json**

## How It Works

1. **Search** → browse products (hats, merch)
2. **Get Quote** → receive USDC price + payment wallet
3. **Send USDC** on Base to the payment wallet
4. **Place Order** → submit tx hash → server verifies on-chain → Shopify order created → Printful ships

No credit card. No human in the loop. Fully autonomous.

## Tools

| Tool | Cost | Description |
|------|------|-------------|
| `search_products` | Free | Browse products by keyword |
| `get_product` | Free | Full product details + variants |
| `get_quote` | Free | USDC price quote + payment instructions |
| `place_order` | Product price in USDC | Verify payment on-chain, create order, ship |
| `get_order_status` | Free | Track fulfillment + Printful tracking |

## Payment

- **Network:** Base (Ethereum L2)
- **Token:** USDC
- **Contract:** `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- **Wallet:** `0xaB967e23686CDD52238723A1DDa9BAb8f81b181C`

## Example Flow

```json
// 1. Search
POST https://mcp.masonborda.com/tools/search_products
{"query": "hat"}

// 2. Get quote
POST https://mcp.masonborda.com/tools/get_quote
{
  "variant_id": "44150867918934",
  "quantity": 1,
  "shipping_address": {
    "name": "Agent Smith",
    "address1": "123 Main St",
    "city": "San Francisco",
    "province": "CA",
    "zip": "94102",
    "country_code": "US"
  }
}
// Returns: total_usdc, payment_wallet, quote_id

// 3. Send USDC on Base, get tx hash

// 4. Place order
POST https://mcp.masonborda.com/tools/place_order
{
  "quote_id": "q_...",
  "tx_hash": "0x...",
  "variant_id": "44150867918934",
  "quantity": 1,
  "shipping_address": { ... }
}
// Returns: order_id, tracking info
```

## Stack

- **FastAPI** — MCP server
- **Shopify Admin API** — order creation
- **Printful** — production + fulfillment
- **Base (on-chain)** — USDC payment verification
- **fly.io** — hosting

## Products

- Accredited Investor Hat — $30 USDC
- Fiduciary Hat — $20 USDC
- Retail Investor Hat — $15 USDC
- Qualified Institutional Buyer Hat — $500 USDC

## License

MIT
