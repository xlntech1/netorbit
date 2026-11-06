"""Shared helper: move time forward and let NetOrbit's background work finish."""

from datetime import timedelta

from pytest_homeassistant.common import async_fire_time_changed


async def advance(hass, freezer, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    for _ in range(3):
        await hass.async_block_till_done(wait_background_tasks=True)
