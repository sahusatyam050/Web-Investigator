import asyncio
import time
import uuid
import logging
from typing import Dict, List, Any, Optional, Callable
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from config import DEFAULT_MAX_PAGES, DEFAULT_RENDER_TIMEOUT, HEADLESS
from database.db_manager import DatabaseManager
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

    async def check_login_required(self, page: Page, html_content: str, url: str) -> bool:
        """Step 6: Checks if page or visible DOM overlays contain login forms, password inputs, or auth triggers."""
        url_lower = url.lower()
        if any(term in url_lower for term in ["/login", "/signin", "/auth", "/register"]):
            return True
            
        content_lower = html_content.lower()
        login_text_triggers = [
            "please login", "login required", "sign in to continue", 
            "forgot your password", "log in to your account", 
            "don't have an account? sign up"
        ]
        if any(trigger in content_lower for trigger in login_text_triggers):
            return True

        # Check for visible password input fields or login forms in DOM
        try:
            pass_inputs = page.locator("input[type='password'], input[name*='pass']")
            for i in range(await pass_inputs.count()):
                if await pass_inputs.nth(i).is_visible():
                    return True
        except Exception:
            pass

        return False

    async def highlight_and_click(self, locator, delay_after: float = 1.5):
        """Highlights a DOM element with a glowing red highlight before clicking it (with forced overlay fallback)."""
        try:
            if await locator.is_visible():
                await locator.evaluate("""el => {
                    el.style.outline = '4px solid #FF0055';
                    el.style.boxShadow = '0 0 20px #FF0055';
                    el.style.transition = 'all 0.2s ease-in-out';
                }""")
                await asyncio.sleep(0.4)
                try:
                    await locator.click(timeout=3000)
                except Exception:
                    # Fallback to forced click if modal overlay intercepts pointer events
                    await locator.click(force=True, timeout=3000)
                await asyncio.sleep(delay_after)
                return True
        except Exception as e:
            logger.debug(f"Click warning ({e})")
        return False

    async def scroll_page(self, max_scroll_px: int = 2500):
        """Smoothly scrolls down the page to trigger lazy loading of images and links."""
        try:
            await self.page.evaluate(f"""async () => {{
                await new Promise((resolve) => {{
                    let totalHeight = 0;
                    let distance = 350;
                    let timer = setInterval(() => {{
                        let scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if(totalHeight >= scrollHeight || totalHeight >= {max_scroll_px}){{
                            clearInterval(timer);
                            resolve();
                        }}
                    }}, 100);
                }});
            }}""")
            await asyncio.sleep(1.0)
        except Exception:
            pass

    async def run_investigation(
        self, 
        target_url: str, 
        investigation_id: str,
        log_callback: Optional[Callable[[str, str], None]] = None,
        auth_callback: Optional[Callable[[], None]] = None
    ) -> Dict[str, Any]:
        """
        Executes the full automated behavioral collection workflow (Deposit, Sports, Casino).
        """
        start_time = __import__("time").time()
        self.db.create_investigation(investigation_id, target_url)
        self._log(log_callback, investigation_id, f"Started behavioral investigation for {target_url}", "INFO")

        deposit_inspected = False
        login_encountered = False

        try:
            await self.init_browser()
            
            # Step 3: Launch Playwright & Open Homepage
            self._log(log_callback, investigation_id, "Opening Homepage...", "INFO")
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=DEFAULT_RENDER_TIMEOUT)
            await asyncio.sleep(2) # Wait for dynamic rendering

            homepage_url = self.page.url
            homepage_html = await self.page.content()

            # Add homepage as initial target
            queue.append({"url": homepage_url, "anchor_text": "Homepage", "priority": "High"})

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

                    # Auto-trigger Login Modal ONCE if login button is visible and auth not done
                    if not login_encountered:
                        try:
                            login_btn = self.page.locator("button:has-text('Log in'), a:has-text('Log in'), button:has-text('Sign in'), a:has-text('Sign in')").first
                            if await login_btn.is_visible():
                                self._log(log_callback, investigation_id, "Found visible 'Log in' button. Clicking to open login modal...", "INFO")
                                await login_btn.click()
                                await asyncio.sleep(1.5)
                        except Exception:
                            pass

            # Refresh DOM state because clicking login might have spawned a modal or SPA route
            page_html = await self.page.content()
            page_url = self.page.url

                    # Step 6: Per-Page Auth / Login Modal Detection & Manual Auth Pause
                    if await self.check_login_required(self.page, page_html, page_url):
                        login_encountered = True
                        self._log(log_callback, investigation_id, f"🔑 Login Required / Auth Form detected on {page_url}! Please log in in the browser window on screen...", "WARNING")
                        
                        try:
                            await self.page.bring_to_front()
                        except Exception:
                            pass

                        self.pause_for_auth = True
                        if auth_callback:
                            auth_callback()
                        
                        self.auth_resumed.clear()

                        # Smart Auto-Resume Polling Loop
                        while self.pause_for_auth and not self.stop_requested:
                            if self.auth_resumed.is_set():
                                self.pause_for_auth = False
                                break
                            
                            await asyncio.sleep(1)
                            
                            try:
                                current_url = self.page.url
                                current_html = await self.page.content()
                                if not await self.check_login_required(self.page, current_html, current_url):
                                    self._log(log_callback, investigation_id, f"✅ Manual login detected in browser ({current_url})! Auto-resuming crawl...", "INFO")
                                    self.pause_for_auth = False
                                    break
                            except Exception:
                                pass

                        if self.stop_requested:
                            self._log(log_callback, investigation_id, "Investigation stopped during authentication pause.", "WARNING")
                            break

                        # Refresh page details after manual login
                        page_url = self.page.url
                        page_html = await self.page.content()
                        page_title = await self.page.title() or page_url
                        self._log(log_callback, investigation_id, f"Resumed investigation after manual authentication.", "INFO")

                    # Deep Deposit & Payment QR Code Inspection Flow (Runs ONCE after login)
                    if login_encountered and not deposit_inspected:
                        try:
                            deposit_selector = "button:has-text('Deposit'), a:has-text('Deposit'), button:has-text('Recharge'), a:has-text('Recharge'), button:has-text('Cashier'), a:has-text('Cashier'), button:has-text('Add Money')"
                            deposit_btn = self.page.locator(deposit_selector).first
                            if await deposit_btn.is_visible():
                                deposit_inspected = True
                                self._log(log_callback, investigation_id, f"Navigating to Deposit section to inspect payment options & QR codes...", "INFO")
                                await deposit_btn.click()
                                await asyncio.sleep(2.5)

                                # 1. Locate and click UPI / Paytm / PhonePe method card
                                upi_card_selectors = [
                                    "div:has-text('UPI'):not(:has(*))",
                                    "div:has-text('Pay Tm'):not(:has(*))",
                                    "div:has-text('Paytm'):not(:has(*))",
                                    "div:has-text('Phone Pe'):not(:has(*))",
                                    "text=/UPI|Pay Tm|Paytm|Phone Pe/i"
                                ]
                                
                                payment_clicked = False
                                for sel in upi_card_selectors:
                                    try:
                                        card = self.page.locator(sel).first
                                        if await card.is_visible():
                                            self._log(log_callback, investigation_id, f"Clicking Payment Method card: '{sel}'...", "INFO")
                                            await card.click()
                                            await asyncio.sleep(2.0)
                                            payment_clicked = True
                                            break
                                    except Exception:
                                        continue

                                # 2. Handle pre-set deposit amount or Continue button if prompted
                                if payment_clicked:
                                    try:
                                        amount_btn = self.page.locator("button:has-text('500'), button:has-text('1000'), div:has-text('500')").first
                                        if await amount_btn.is_visible():
                                            await amount_btn.click()
                                            await asyncio.sleep(1.0)

                                        submit_pay_btn = self.page.locator("button:has-text('Continue'), button:has-text('Deposit'), button:has-text('Pay')").first
                                        if await submit_pay_btn.is_visible():
                                            self._log(log_callback, investigation_id, "Clicking 'Continue/Deposit' to generate active QR code & UPI VPA...", "INFO")
                                            await submit_pay_btn.click()
                                            await asyncio.sleep(3.0) # Wait for QR code image or payment gateway iframe to render
                                    except Exception as sub_err:
                                        logger.debug(f"Amount submit error: {sub_err}")

                                page_url = self.page.url
                                page_html = await self.page.content()
                                page_title = await self.page.title() or "Deposit Payment Page"
                        except Exception as dep_err:
                            logger.debug(f"Deposit flow error: {dep_err}")

                    # Step 4 & 5: Dynamic Queue Expansion (Extract new links on this page)
                    new_discovered = nav_engine.extract_and_prioritize_links(page_html, page_url)
                    for link in new_discovered:
                        if link["url"] not in visited_urls and link["url"] not in [q["url"] for q in queue]:
                            queue.append(link)

                    # Re-sort queue by priority: High -> Medium -> Low
                    priority_rank = {"High": 1, "Medium": 2, "Low": 3}
                    queue.sort(key=lambda x: priority_rank.get(x["priority"], 2))

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
