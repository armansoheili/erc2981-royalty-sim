# erc2981-royalty-sim

ERC-2981 NFT royalty standard simulator in pure Python — no dependencies.

A contract declares a default royalty (receiver + fee numerator over a
denominator of 10,000 basis points) and may override it per token id.
Marketplaces call `royalty_info(token_id, sale_price)` and pay the returned
amount to the receiver out of the sale. All math is integer and rounds down,
exactly like the on-chain reference implementation.

## What's in here

- `royalty.py` — the whole simulator:
  - `RoyaltyRegistry` — default royalty, per-token overrides, reset/delete,
    `royalty_info()`, `has_royalty()`, ERC-165 `supports_interface()` for
    `0x2a55205a` (IERC2981)
  - `settle_sale()` — splits a sale into royalty + seller proceeds
  - validation: receiver must not be the zero address, fee numerator must
    not exceed the 10,000 denominator, sale price must not be negative

## Run it

```bash
python royalty.py --demo   # sample sales: 5% default, 10% on token 7
python royalty.py --test   # doctests
```

## Example

```python
from royalty import RoyaltyRegistry, settle_sale

reg = RoyaltyRegistry()
reg.set_default_royalty("0xArtistAbC123", 500)      # 5% on every token
reg.set_token_royalty(7, "0xCollabDeF456", 1_000)   # 10% on token 7

reg.royalty_info(1, 1_000_000)   # ('0xArtistAbC123', 50000)
reg.royalty_info(7, 1_000_000)   # ('0xCollabDeF456', 100000)

settle_sale(reg, 1, 1_000_000)
# {'token_id': 1, 'sale_price': 1000000, 'receiver': '0xArtistAbC123',
#  'royalty_amount': 50000, 'seller_amount': 950000}
```

## Notes

- A 0% per-token override mutes the royalty for that token; `reset_token_royalty()`
  drops the override so the default applies again.
- With no default royalty configured, `royalty_info()` returns `(None, 0)` and
  the seller keeps the full price.
