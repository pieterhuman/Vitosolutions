"""Async agentic loop powering the Claude Travel Agent demo.

Simulates the plan -> tool call -> observe cycle the UI visualizes,
using mock travel tools. Run standalone to watch the agent reason:

    python3 agent.py
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

ToolFn = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


# --------------------------------------------------------------------------
# Mock tools
# --------------------------------------------------------------------------

async def search_flights(origin: str, destination: str, flexible_off_season: bool = False) -> dict[str, Any]:
    await asyncio.sleep(0.4)  # simulate network latency
    if flexible_off_season:
        return {
            "route": f"{origin} -> {destination}",
            "flight": "ANA NH 0109",
            "month": "February",
            "price_usd": 290,
            "standard_price_usd": 450,
            "status": "Best Value",
        }
    return {
        "route": f"{origin} -> {destination}",
        "flight": "ANA NH 0109",
        "month": "October",
        "price_usd": 450,
        "standard_price_usd": None,
        "status": "Standard Fare",
    }


async def search_hotels(city: str, flexible_off_season: bool = False) -> dict[str, Any]:
    await asyncio.sleep(0.3)
    nightly = 84 if flexible_off_season else 120
    return {
        "name": "Shinjuku Granbell",
        "city": city,
        "rating": 4.6,
        "nightly_rate_usd": nightly,
        "standard_rate_usd": 120,
        "tag": "30% Off-Peak Rate" if flexible_off_season else "Peak Rate",
    }


async def get_weather(city: str, month: str) -> dict[str, Any]:
    await asyncio.sleep(0.2)
    seasons = {
        "February": {"temp_c": 8, "condition": "Crisp & Clear", "season": "Off-Season"},
        "October": {"temp_c": 19, "condition": "Autumn Foliage", "season": "Peak Season"},
    }
    return {"city": city, "month": month, **seasons.get(month, seasons["October"])}


TOOLS: dict[str, ToolFn] = {
    "search_flights": search_flights,
    "search_hotels": search_hotels,
    "get_weather": get_weather,
}


# --------------------------------------------------------------------------
# Agentic loop
# --------------------------------------------------------------------------

@dataclass
class AgentStep:
    tool: str
    args: dict[str, Any]
    result: dict[str, Any] | None = None


@dataclass
class TravelAgent:
    """Minimal deterministic planner that mimics an LLM-driven tool loop."""

    off_season: bool = True
    steps: list[AgentStep] = field(default_factory=list)

    def plan(self, request: str) -> list[AgentStep]:
        month = "February" if self.off_season else "October"
        return [
            AgentStep("search_flights", {"origin": "JFK", "destination": "NRT",
                                         "flexible_off_season": self.off_season}),
            AgentStep("search_hotels", {"city": "Tokyo",
                                        "flexible_off_season": self.off_season}),
            AgentStep("get_weather", {"city": "Tokyo", "month": month}),
        ]

    async def run(self, request: str) -> dict[str, Any]:
        print(f"[agent] request: {request!r}")
        for step in self.plan(request):
            arg_str = ", ".join(f"{k}={v!r}" for k, v in step.args.items())
            print(f"[tool]  {step.tool}({arg_str})")
            step.result = await TOOLS[step.tool](**step.args)
            self.steps.append(step)
            print(f"[obs]   {json.dumps(step.result)}")

        flight, hotel, weather = (s.result for s in self.steps[-3:])
        savings = 0
        if self.off_season:
            savings = (flight["standard_price_usd"] - flight["price_usd"]) + \
                      (hotel["standard_rate_usd"] - hotel["nightly_rate_usd"])
        summary = {"flight": flight, "hotel": hotel, "weather": weather,
                   "total_savings_usd": savings}
        print(f"[agent] done — total savings: ${savings}")
        return summary


async def main() -> None:
    agent = TravelAgent(off_season=True)
    await agent.run("Find me the cheapest way to get to Tokyo, flexible dates.")


if __name__ == "__main__":
    asyncio.run(main())
