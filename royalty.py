"""ERC-2981 NFT royalty standard simulator in pure Python.

Implements the royalty-info logic of `EIP-2981
<https://eips.ethereum.org/EIPS/eip-2981>`_: a contract declares a default
royalty (receiver + fee numerator over a denominator of 10_000) and may
override it per token id.  Marketplaces call ``royalty_info(token_id,
sale_price)`` and pay ``receiver`` the returned amount out of the sale.

Everything is integer math, so amounts always round down -- exactly like the
on-chain reference implementation.  No dependencies, no network access.

Run the doctests::

    python -m doctest royalty.py -v
    python royalty.py --test

Run the demo::

    python royalty.py --demo
"""

from __future__ import annotations

__all__ = [
    "FEE_DENOMINATOR",
    "ERC2981_INTERFACE_ID",
    "RoyaltyRegistry",
    "settle_sale",
]

#: Royalty fee denominator fixed by EIP-2981 (basis points).
FEE_DENOMINATOR = 10_000

#: ERC-165 interface id of IERC2981 (``royaltyInfo(uint256,uint256)``).
ERC2981_INTERFACE_ID = "0x2a55205a"

#: The zero address -- never a valid royalty receiver.
ZERO_ADDRESS = "0x" + "0" * 40


def _check_receiver(receiver: str) -> str:
    """Validate a royalty receiver address.

    >>> _check_receiver("0xAbC123")
    '0xAbC123'
    >>> _check_receiver("0x0000000000000000000000000000000000000000")
    Traceback (most recent call last):
    ...
    ValueError: royalty receiver must not be the zero address
    >>> _check_receiver("")
    Traceback (most recent call last):
    ...
    ValueError: royalty receiver must not be empty
    """
    if not receiver:
        raise ValueError("royalty receiver must not be empty")
    if receiver.lower() == ZERO_ADDRESS:
        raise ValueError("royalty receiver must not be the zero address")
    return receiver


def _check_numerator(fee_numerator: int) -> int:
    """Validate a royalty fee numerator (0 .. FEE_DENOMINATOR).

    >>> _check_numerator(500)
    500
    >>> _check_numerator(10_000)
    10000
    >>> _check_numerator(10_001)
    Traceback (most recent call last):
    ...
    ValueError: fee numerator 10001 exceeds denominator 10000
    >>> _check_numerator(-1)
    Traceback (most recent call last):
    ...
    ValueError: fee numerator must not be negative
    """
    if fee_numerator < 0:
        raise ValueError("fee numerator must not be negative")
    if fee_numerator > FEE_DENOMINATOR:
        raise ValueError(
            f"fee numerator {fee_numerator} exceeds denominator {FEE_DENOMINATOR}"
        )
    return fee_numerator


class RoyaltyRegistry:
    """Default + per-token ERC-2981 royalty configuration.

    >>> reg = RoyaltyRegistry()
    >>> reg.royalty_info(1, 1_000_000)
    (None, 0)
    >>> reg.set_default_royalty("0xArtist", 500)   # 5% default
    >>> reg.royalty_info(1, 1_000_000)
    ('0xArtist', 50000)
    >>> reg.set_token_royalty(7, "0xCollab", 1_000)  # 10% for token 7
    >>> reg.royalty_info(7, 1_000_000)
    ('0xCollab', 100000)
    >>> reg.royalty_info(8, 1_000_000)  # other tokens keep the default
    ('0xArtist', 50000)
    >>> reg.reset_token_royalty(7)
    >>> reg.royalty_info(7, 1_000_000)
    ('0xArtist', 50000)
    """

    def __init__(self) -> None:
        self._default_receiver: str | None = None
        self._default_numerator: int = 0
        self._overrides: dict[int, tuple[str, int]] = {}

    def set_default_royalty(self, receiver: str, fee_numerator: int) -> None:
        """Set the fallback royalty applied to tokens without an override.

        >>> reg = RoyaltyRegistry()
        >>> reg.set_default_royalty("0xArtist", 250)  # 2.5%
        >>> reg.royalty_info(42, 400_000)
        ('0xArtist', 10000)
        >>> reg.set_default_royalty("0xNobody", 10_001)
        Traceback (most recent call last):
        ...
        ValueError: fee numerator 10001 exceeds denominator 10000
        """
        self._default_receiver = _check_receiver(receiver)
        self._default_numerator = _check_numerator(fee_numerator)

    def delete_default_royalty(self) -> None:
        """Remove the default royalty (tokens without overrides pay nothing).

        >>> reg = RoyaltyRegistry()
        >>> reg.set_default_royalty("0xArtist", 500)
        >>> reg.delete_default_royalty()
        >>> reg.royalty_info(1, 1_000_000)
        (None, 0)
        """
        self._default_receiver = None
        self._default_numerator = 0

    def set_token_royalty(
        self, token_id: int, receiver: str, fee_numerator: int
    ) -> None:
        """Override the royalty for a single token id.

        >>> reg = RoyaltyRegistry()
        >>> reg.set_token_royalty(3, "0xArtist", 750)
        >>> reg.royalty_info(3, 200_000)
        ('0xArtist', 15000)
        >>> reg.set_token_royalty(3, "0xArtist", 0)  # 0% override mutes it
        >>> reg.royalty_info(3, 200_000)
        ('0xArtist', 0)
        """
        if token_id < 0:
            raise ValueError("token id must not be negative")
        self._overrides[token_id] = (
            _check_receiver(receiver),
            _check_numerator(fee_numerator),
        )

    def reset_token_royalty(self, token_id: int) -> None:
        """Drop a token's override so the default royalty applies again.

        >>> reg = RoyaltyRegistry()
        >>> reg.set_default_royalty("0xArtist", 500)
        >>> reg.set_token_royalty(9, "0xOther", 1_000)
        >>> reg.reset_token_royalty(9)
        >>> reg.royalty_info(9, 100_000)
        ('0xArtist', 5000)
        >>> reg.reset_token_royalty(999)  # unknown token: no-op
        """
        self._overrides.pop(token_id, None)

    def royalty_info(self, token_id: int, sale_price: int) -> tuple[str | None, int]:
        """Return ``(receiver, royalty_amount)`` for a sale, per EIP-2981.

        Amounts round down (integer division), matching the reference
        implementation.  A zero sale price always pays zero, even with a
        configured royalty.

        >>> reg = RoyaltyRegistry()
        >>> reg.set_default_royalty("0xArtist", 333)  # 3.33%
        >>> reg.royalty_info(1, 100)  # 100 * 333 // 10000 == 3
        ('0xArtist', 3)
        >>> reg.royalty_info(1, 0)
        ('0xArtist', 0)
        >>> reg.royalty_info(1, -5)
        Traceback (most recent call last):
        ...
        ValueError: sale price must not be negative
        """
        if sale_price < 0:
            raise ValueError("sale price must not be negative")
        if token_id in self._overrides:
            receiver, numerator = self._overrides[token_id]
        else:
            receiver, numerator = self._default_receiver, self._default_numerator
        if receiver is None:
            return None, 0
        return receiver, sale_price * numerator // FEE_DENOMINATOR

    def has_royalty(self, token_id: int) -> bool:
        """True when a sale of this token would pay a nonzero royalty.

        >>> reg = RoyaltyRegistry()
        >>> reg.set_default_royalty("0xArtist", 500)
        >>> reg.has_royalty(1)
        True
        >>> reg.set_token_royalty(2, "0xArtist", 0)
        >>> reg.has_royalty(2)
        False
        """
        receiver, numerator = self._overrides.get(
            token_id, (self._default_receiver, self._default_numerator)
        )
        return receiver is not None and numerator > 0

    def supports_interface(self, interface_id: str) -> bool:
        """ERC-165 check: True only for the IERC2981 interface id.

        >>> reg = RoyaltyRegistry()
        >>> reg.supports_interface("0x2a55205a")
        True
        >>> reg.supports_interface("0x80ac58cd")  # ERC-721: not us
        False
        """
        return interface_id.lower() == ERC2981_INTERFACE_ID


def settle_sale(
    registry: RoyaltyRegistry, token_id: int, sale_price: int
) -> dict[str, int | str | None]:
    """Split a sale into royalty and seller proceeds.

    The royalty is paid first out of the sale price; the seller keeps the
    rest.  Royalty + seller proceeds always equal the sale price.

    >>> reg = RoyaltyRegistry()
    >>> reg.set_default_royalty("0xArtist", 500)  # 5%
    >>> settle_sale(reg, 1, 1_000_000)
    {'token_id': 1, 'sale_price': 1000000, 'receiver': '0xArtist', 'royalty_amount': 50000, 'seller_amount': 950000}
    >>> settle_sale(reg, 1, 999)  # 999 * 500 // 10000 == 49, rounds down
    {'token_id': 1, 'sale_price': 999, 'receiver': '0xArtist', 'royalty_amount': 49, 'seller_amount': 950}
    >>> reg2 = RoyaltyRegistry()
    >>> settle_sale(reg2, 1, 1_000_000)
    {'token_id': 1, 'sale_price': 1000000, 'receiver': None, 'royalty_amount': 0, 'seller_amount': 1000000}
    """
    receiver, royalty = registry.royalty_info(token_id, sale_price)
    return {
        "token_id": token_id,
        "sale_price": sale_price,
        "receiver": receiver,
        "royalty_amount": royalty,
        "seller_amount": sale_price - royalty,
    }


def _demo() -> None:
    reg = RoyaltyRegistry()
    reg.set_default_royalty("0xArtistAbC123", 500)  # 5% on every token
    reg.set_token_royalty(7, "0xCollabDeF456", 1_000)  # 10% collab piece
    print("ERC-2981 royalty demo (prices in wei)")
    print("default: 5% -> 0xArtistAbC123; token 7: 10% -> 0xCollabDeF456")
    for token_id, price in [(1, 1_000_000), (7, 1_000_000), (7, 999)]:
        sale = settle_sale(reg, token_id, price)
        print(
            f"token {token_id} sold for {price}: "
            f"royalty {sale['royalty_amount']} to {sale['receiver']}, "
            f"seller keeps {sale['seller_amount']}"
        )
    print(f"supports IERC2981 ({ERC2981_INTERFACE_ID}):",
          reg.supports_interface(ERC2981_INTERFACE_ID))


def _test() -> int:
    import doctest

    results = doctest.testmod(verbose=False)
    print(f"doctests: {results.attempted} run, {results.failed} failed")
    return 1 if results.failed else 0


if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        raise SystemExit(_test())
    if "--demo" in sys.argv:
        _demo()
    else:
        print(__doc__.strip().splitlines()[0])
        print("usage: python royalty.py [--demo | --test]")
