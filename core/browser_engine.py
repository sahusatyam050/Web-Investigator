import asyncio
import time
import uuid
import logging
from typing import Dict, List, Any, Optional, Callable
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from config import DEFAULT_MAX_PAGES, DEFAULT_RENDER_TIMEOUT, HEADLESS
from database.db_manager import DatabaseManager
from core.nav_engine import NavigationEngine
from core.keyword_detector import KeywordDetector
from core.payment_detector import PaymentDetector
from core.image_annotator import ImageAnnotator

logger = logging.getLogger(__name__)

class PlaywrightInvestigationEngine:
    """
    Core Evidence Collection Engine:
    Manages Playwright headed browser session, Priority Navigation, Auth Pause/Resume,
    Keyword & Payment detection, Bounding box extraction, and Evidence Persistence.
    """

    def __init__(self, db_manager: DatabaseManager, max_pages: int = DEFAULT_MAX_PAGES):
        self.db = db_manager
        self.max_pages = max_pages
        self.stop_requested = False
        self.pause_for_auth = False
        self.auth_resumed = asyncio.Event()

        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        self.keyword_detector = KeywordDetector()
        self.payment_detector = PaymentDetector()

    def request_stop(self):
        """Called when user clicks Stop Investigation button."""
        self.stop_requested = True
        self.auth_resumed.set() # Unblock pause if waiting

    def resume_investigation(self):
        """Called when user completes manual login and clicks Resume Investigation."""
        self.pause_for_auth = False
        self.auth_resumed.set()

    async def init_browser(self):
        """Launches Playwright Chromium browser in Headed mode."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=HEADLESS,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.page = await self.context.new_page()

    async def close_browser(self):
        """Safely closes Playwright browser instance."""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.error(f"Error closing browser: {e}")

    def check_login_required(self, html_content: str, url: str) -> bool:
        """Step 6: Checks if page requires authentication or manual login."""
        url_lower = url.lower()
        if any(term in url_lower for term in ["/login", "/signin", "/auth", "/register"]):
            return True
            
        content_lower = html_content.lower()
        login_triggers = ["please login", "login required", "sign in to continue", "enter password", "enter otp"]
        return any(trigger in content_lower for trigger in login_triggers)

    async def run_investigation(
        self, 
        target_url: str, 
        investigation_id: str,
        log_callback: Optional[Callable[[str, str], None]] = None,
        auth_callback: Optional[Callable[[], None]] = None
    ) -> Dict[str, Any]:
        """
        Executes the full automated evidence collection workflow (Steps 3-11).
        """
        start_time = time.time()
        nav_engine = NavigationEngine(target_url)
        visited_urls: Set[str] = set()
        queue: List[Dict[str, str]] = []
        
        self.db.create_investigation(investigation_id, target_url)
        self._log(log_callback, investigation_id, f"Started investigation for {target_url}", "INFO")

        login_encountered = False

        try:
            await self.init_browser()
            
            # Step 3: Launch Playwright & Open Homepage
            self._log(log_callback, investigation_id, "Opening Homepage...", "INFO")
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=DEFAULT_RENDER_TIMEOUT)
            await asyncio.sleep(2) # Wait for dynamic rendering

            homepage_url = self.page.url
            homepage_html = await self.page.content()
            homepage_title = await self.page.title() or "Homepage"

            # Check Auth requirement on Homepage
            if self.check_login_required(homepage_html, homepage_url):
                login_encountered = True
                self._log(log_callback, investigation_id, "Login Required detected! Pausing for manual login...", "WARNING")
                self.pause_for_auth = True
                if auth_callback:
                    auth_callback()
                
                # Wait for user to click Resume or Stop
                self.auth_resumed.clear()
                await self.auth_resumed.wait()

                if self.stop_requested:
                    self._log(log_callback, investigation_id, "Investigation stopped during authentication pause.", "WARNING")
                    self.db.update_investigation(investigation_id, "STOPPED", time.time() - start_time, 0, login_encountered)
                    return {"status": "STOPPED", "investigation_id": investigation_id}

                # Re-fetch page state after manual login
                homepage_url = self.page.url
                homepage_html = await self.page.content()
                homepage_title = await self.page.title() or "Authenticated Homepage"
                self._log(log_callback, investigation_id, "Resumed investigation after manual authentication.", "INFO")

            # Step 4 & 5: Build Navigation Queue
            discovered_links = nav_engine.extract_and_prioritize_links(homepage_html, homepage_url)
            
            # Add homepage itself as first item
            queue.append({"url": homepage_url, "anchor_text": "Homepage", "priority": "High"})
            for link in discovered_links:
                if link["url"] not in [q["url"] for q in queue]:
                    queue.append(link)

            self._log(log_callback, investigation_id, f"Discovered {len(queue)} internal pages. High Priority first.", "INFO")

            # Step 7: Investigate Pages in Priority Queue
            pages_visited_count = 0

            while queue and pages_visited_count < self.max_pages:
                if self.stop_requested:
                    self._log(log_callback, investigation_id, "Investigation manually stopped by user.", "WARNING")
                    break

                target = queue.pop(0)
                page_url = target["url"]
                priority = target["priority"]

                if page_url in visited_urls:
                    continue

                visited_urls.add(page_url)
                pages_visited_count += 1

                self._log(log_callback, investigation_id, f"[{pages_visited_count}/{self.max_pages}] Investigating ({priority}): {page_url}", "INFO")

                try:
                    if page_url != self.page.url:
                        await self.page.goto(page_url, wait_until="domcontentloaded", timeout=DEFAULT_RENDER_TIMEOUT)
                        await asyncio.sleep(1.5)

                    page_title = await self.page.title() or page_url
                    page_html = await self.page.content()

                    # Save Page Record
                    page_id = self.db.add_page(investigation_id, page_url, page_title, priority)

                    # Save Navigation Link Graph
                    self.db.add_navigation_link(investigation_id, homepage_url if pages_visited_count > 1 else "ROOT", page_url, 1 if pages_visited_count > 1 else 0)

                    # Step 8: Keyword Detection
                    keyword_findings = await self.keyword_detector.detect_and_locate_keywords(self.page)
                    if keyword_findings:
                        self.db.add_keyword_findings(page_id, keyword_findings)

                    # Step 10: Payment Detection
                    payment_findings = await self.payment_detector.detect_payment_indicators(self.page, page_html)
                    if payment_findings:
                        self.db.add_payment_findings(page_id, payment_findings)

                    # Step 9: Screenshot Capture & OpenCV Annotation
                    raw_screenshot = await self.page.screenshot(full_page=False)
                    screenshot_filename = f"inv_{investigation_id}_page_{page_id}.png"
                    
                    highlighted_path = ImageAnnotator.annotate_and_save_screenshot(
                        raw_screenshot, screenshot_filename, keyword_findings, payment_findings
                    )

                    self.db.add_screenshot(page_id, highlighted_path)

                except Exception as page_err:
                    self._log(log_callback, investigation_id, f"Error investigating {page_url}: {page_err}", "ERROR")

            # Finalize Investigation Status
            status = "STOPPED" if self.stop_requested else "COMPLETED"
            duration = time.time() - start_time
            self.db.update_investigation(investigation_id, status, duration, pages_visited_count, login_encountered)
            self._log(log_callback, investigation_id, f"Investigation {status}. Total pages: {pages_visited_count}, Duration: {duration:.2f}s", "INFO")

            return {
                "status": status,
                "investigation_id": investigation_id,
                "total_pages": pages_visited_count,
                "duration": duration
            }

        except Exception as err:
            self._log(log_callback, investigation_id, f"Fatal Investigation Error: {err}", "ERROR")
            self.db.update_investigation(investigation_id, "FAILED", time.time() - start_time, 0, login_encountered)
            return {"status": "FAILED", "error": str(err), "investigation_id": investigation_id}
        finally:
            await self.close_browser()

    def _log(self, callback: Optional[Callable[[str, str], None]], inv_id: str, action: str, status: str):
        self.db.log_action(inv_id, action, status)
        if callback:
            callback(action, status)
