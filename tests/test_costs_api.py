"""Tests for Costs API endpoint."""

import pytest


@pytest.mark.asyncio
async def test_get_costs(make_client):
    async with make_client() as c:
        resp = await c.get("/api/costs")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "by_provider" in data
    assert "by_month" in data
    assert "recent" in data


@pytest.mark.asyncio
async def test_costs_page(make_client):
    async with make_client() as c:
        resp = await c.get("/costs")
    assert resp.status_code == 200
    assert "Cost Dashboard" in resp.text or "コスト" in resp.text
