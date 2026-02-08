from playwright.async_api import Browser, Playwright, async_playwright


class BrowserManager:
    _instance = None
    _playwright: Playwright = None
    _browser: Browser = None

    @classmethod
    async def get_browser(cls, headless=True) -> Browser:
        if cls._browser is None:
            cls._playwright = await async_playwright().start()
            cls._browser = await cls._playwright.chromium.launch(
                headless=headless,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
        return cls._browser

    @classmethod
    async def close(cls):
        if cls._browser:
            await cls._browser.close()
            cls._browser = None
        if cls._playwright:
            await cls._playwright.stop()
            cls._playwright = None
