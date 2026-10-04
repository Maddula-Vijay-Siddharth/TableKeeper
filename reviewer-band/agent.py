import os
import asyncio

from dotenv import load_dotenv
from band import Agent
from band.config import load_agent_config
from band.adapters import CodexAdapter, CodexAdapterConfig


async def main():
    print("1. Starting Reviewer", flush=True)

    load_dotenv()
    print("2. .env loaded", flush=True)

    agent_id, api_key = load_agent_config(
        "reviewer_tablekeeper",
        config_path=r"C:\Siddu\Tablekeeper\reviewer-band\agent_config.yaml",
    )
    print("3. Agent config loaded", flush=True)

    os.chdir(r"C:\Siddu\Tablekeeper")
    print("4. Working directory set", flush=True)

    adapter = CodexAdapter(
        config=CodexAdapterConfig(
            transport="stdio",
            custom_section="""You are the Review Agent in an autonomous software development factory.

Review completed implementation work independently against requirements,
architecture, acceptance criteria, tests, and verification evidence.

Do not modify production code.
Return REVIEW_PASS only when the implementation and evidence satisfy the requirements.
Return REVIEW_FAIL with specific actionable findings when they do not.
""",
        )
    )
    print("5. Codex adapter created", flush=True)

    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
        ws_url=os.getenv(
            "BAND_WS_URL",
            "wss://app.band.ai/api/v1/socket/websocket",
        ),
        rest_url=os.getenv(
            "BAND_REST_URL",
            "https://app.band.ai",
        ),
    )
    print("6. BAND agent created", flush=True)

    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
