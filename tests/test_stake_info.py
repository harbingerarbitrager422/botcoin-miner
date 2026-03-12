"""Tests for staking/stake_info.py — contract query + display logic."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.staking.stake_info import (
    StakeInfo,
    _decode_bool,
    _decode_uint256,
    _encode_address_call,
    _format_tokens,
    get_stake_info,
)


# -- Unit tests: encoding helpers ----------------------------------------------


class TestEncodeAddressCall:
    def test_basic(self):
        result = _encode_address_call(
            "0xf9931855",
            "0x6b6a07ecb5e36fc0f2663f91ddcf6df172db6526",
        )
        assert result.startswith("0xf9931855")
        # Address should be 64 hex chars (32 bytes, left-padded with zeros)
        addr_part = result[len("0xf9931855"):]
        assert len(addr_part) == 64
        assert addr_part.endswith("6b6a07ecb5e36fc0f2663f91ddcf6df172db6526")
        assert addr_part.startswith("000000000000000000000000")

    def test_no_0x_prefix(self):
        result = _encode_address_call(
            "0xf9931855",
            "6b6a07ecb5e36fc0f2663f91ddcf6df172db6526",
        )
        addr_part = result[len("0xf9931855"):]
        assert addr_part.endswith("6b6a07ecb5e36fc0f2663f91ddcf6df172db6526")

    def test_uppercase_address(self):
        result = _encode_address_call(
            "0xf9931855",
            "0x6B6A07ECB5E36FC0F2663F91DDCF6DF172DB6526",
        )
        # Should lowercase the address
        addr_part = result[len("0xf9931855"):]
        assert addr_part == "0000000000000000000000006b6a07ecb5e36fc0f2663f91ddcf6df172db6526"


# -- Unit tests: decoders -----------------------------------------------------


class TestDecodeUint256:
    def test_zero(self):
        assert _decode_uint256("0x0000000000000000000000000000000000000000000000000000000000000000") == 0

    def test_empty(self):
        assert _decode_uint256("0x") == 0

    def test_none(self):
        assert _decode_uint256("") == 0

    def test_one(self):
        assert _decode_uint256("0x0000000000000000000000000000000000000000000000000000000000000001") == 1

    def test_large_value(self):
        # 25_000_000 * 10^18 = 25000000000000000000000000
        val = 25_000_000 * 10**18
        hex_val = hex(val)
        assert _decode_uint256(hex_val) == val

    def test_padded(self):
        # 100 in hex = 0x64, padded to 32 bytes
        assert _decode_uint256("0x0000000000000000000000000000000000000000000000000000000000000064") == 100


class TestDecodeBool:
    def test_true(self):
        assert _decode_bool("0x0000000000000000000000000000000000000000000000000000000000000001") is True

    def test_false(self):
        assert _decode_bool("0x0000000000000000000000000000000000000000000000000000000000000000") is False

    def test_empty(self):
        assert _decode_bool("0x") is False


# -- Unit tests: formatting ---------------------------------------------------


class TestFormatTokens:
    def test_whole_tokens(self):
        assert _format_tokens(25_000_000 * 10**18) == "25,000,000"

    def test_zero(self):
        assert _format_tokens(0) == "0"

    def test_fractional(self):
        # 1.75 tokens
        wei = 1_750_000_000_000_000_000
        result = _format_tokens(wei)
        assert result == "1.75"

    def test_tiny_fraction(self):
        # 1.01 tokens
        wei = 1_010_000_000_000_000_000
        result = _format_tokens(wei)
        assert result == "1.01"


# -- Unit tests: StakeInfo -----------------------------------------------------


class TestStakeInfo:
    def _make_info(self, **overrides):
        defaults = dict(
            staked_wei=25_000_000 * 10**18,
            is_eligible=True,
            withdrawable_at=0,
            total_staked_wei=4_000_000_000 * 10**18,
            tier1_wei=25_000_000 * 10**18,
            tier2_wei=50_000_000 * 10**18,
            tier3_wei=100_000_000 * 10**18,
        )
        defaults.update(overrides)
        return StakeInfo(**defaults)

    def test_tier_1(self):
        info = self._make_info(staked_wei=25_000_000 * 10**18)
        assert info.tier == 1

    def test_tier_2(self):
        info = self._make_info(staked_wei=50_000_000 * 10**18)
        assert info.tier == 2

    def test_tier_3(self):
        info = self._make_info(staked_wei=100_000_000 * 10**18)
        assert info.tier == 3

    def test_tier_0(self):
        info = self._make_info(staked_wei=1_000_000 * 10**18)
        assert info.tier == 0

    def test_tier_between(self):
        # 30M -- above T1 (25M) but below T2 (50M)
        info = self._make_info(staked_wei=30_000_000 * 10**18)
        assert info.tier == 1

    def test_no_unstake_pending(self):
        info = self._make_info(withdrawable_at=0)
        assert info.unstake_pending is False
        assert info.cooldown_remaining is None

    def test_unstake_pending_future(self):
        future = int(time.time()) + 3600
        info = self._make_info(withdrawable_at=future)
        assert info.unstake_pending is True
        remaining = info.cooldown_remaining
        assert remaining is not None
        assert 3500 < remaining <= 3600

    def test_unstake_pending_past(self):
        past = int(time.time()) - 100
        info = self._make_info(withdrawable_at=past)
        assert info.unstake_pending is True
        assert info.cooldown_remaining == 0

    def test_display_basic(self):
        info = self._make_info()
        display = info.display()
        assert "25,000,000 BOTCOIN" in display
        assert "Eligible: yes" in display
        assert "Tier: 1" in display
        assert "Tier thresholds:" in display

    def test_display_with_cooldown(self):
        future = int(time.time()) + 7200
        info = self._make_info(withdrawable_at=future)
        display = info.display()
        assert "cooldown" in display.lower()
        assert "remaining" in display.lower()

    def test_display_ready_to_withdraw(self):
        past = int(time.time()) - 100
        info = self._make_info(withdrawable_at=past)
        display = info.display()
        assert "ready to withdraw" in display.lower()

    def test_staked_formatted(self):
        info = self._make_info(staked_wei=25_000_000 * 10**18)
        assert info.staked_formatted == "25,000,000"


# -- Integration test: get_stake_info with mocked RPC -------------------------


class TestGetStakeInfo:
    @pytest.mark.asyncio
    async def test_get_stake_info_mocked(self):
        """Test full flow with mocked RPC responses."""
        staked_25m = hex(25_000_000 * 10**18)
        bool_true = "0x0000000000000000000000000000000000000000000000000000000000000001"
        zero = "0x0000000000000000000000000000000000000000000000000000000000000000"
        total = hex(4_000_000_000 * 10**18)
        t1 = hex(25_000_000 * 10**18)
        t2 = hex(50_000_000 * 10**18)
        t3 = hex(100_000_000 * 10**18)

        call_count = 0
        results = [staked_25m, bool_true, zero, total, t1, t2, t3]

        async def mock_eth_call(client, data, to=None):
            nonlocal call_count
            idx = call_count
            call_count += 1
            return results[idx]

        with patch("src.staking.stake_info._eth_call", side_effect=mock_eth_call):
            info = await get_stake_info("0x6b6a07ecb5e36fc0f2663f91ddcf6df172db6526")

        assert call_count == 7
        assert info.staked_wei == 25_000_000 * 10**18
        assert info.is_eligible is True
        assert info.withdrawable_at == 0
        assert info.tier == 1

    @pytest.mark.asyncio
    async def test_get_stake_info_rpc_error(self):
        """RPC errors propagate cleanly."""
        async def mock_eth_call(client, data, to=None):
            raise RuntimeError("eth_call error: {'code': -32000, 'message': 'execution reverted'}")

        with patch("src.staking.stake_info._eth_call", side_effect=mock_eth_call):
            with pytest.raises(RuntimeError, match="eth_call error"):
                await get_stake_info("0x6b6a07ecb5e36fc0f2663f91ddcf6df172db6526")

    @pytest.mark.asyncio
    async def test_rate_limit_retry(self):
        """Verify _eth_call retries on rate limit then succeeds."""
        from src.staking.stake_info import _eth_call

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()  # sync mock -- resp.json() is sync in httpx
            if call_count <= 2:
                mock_resp.json.return_value = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32016, "message": "over rate limit"},
                    "id": 1,
                }
            else:
                mock_resp.json.return_value = {
                    "jsonrpc": "2.0",
                    "result": "0x0000000000000000000000000000000000000000000000000000000000000001",
                    "id": 1,
                }
            return mock_resp

        mock_client = MagicMock()
        mock_client.post = mock_post

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _eth_call(mock_client, "0x817b1cd2")

        assert result == "0x0000000000000000000000000000000000000000000000000000000000000001"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_rate_limit_exhausted(self):
        """If all retries rate-limited, raises RuntimeError."""
        from src.staking.stake_info import _eth_call

        async def mock_post(*args, **kwargs):
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "jsonrpc": "2.0",
                "error": {"code": -32016, "message": "over rate limit"},
                "id": 1,
            }
            return mock_resp

        mock_client = MagicMock()
        mock_client.post = mock_post

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="eth_call error"):
                await _eth_call(mock_client, "0x817b1cd2")
