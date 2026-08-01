import asyncio
from scraper import run_scrape_job

async def main():
    res = await run_scrape_job("test_job", "https://example.com", {"title": "string", "paragraph": "string"})
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
