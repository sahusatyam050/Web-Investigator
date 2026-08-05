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

    async def run_investigation(
        self, 
        target_url: str, 
        investigation_id: str,
        log_callback=None,
        auth_callback=None,
        progress_callback=None,
        auth_user: str = "",
        auth_pass: str = "",
        auth_mode: str = "Auto-Detect"
    ) -> dict:
        """
        Executes the full automated behavioral collection workflow (Deposit, Sports, Casino).
        """
        start_time = __import__("time").time()
        self.db.create_investigation(investigation_id, target_url)
        self._log(log_callback, investigation_id, f"Started behavioral investigation for {target_url}", "INFO")

        login_encountered = False
        pages_visited_count = 0

        # Helper method for evidence extraction
        async def _extract_and_save_evidence(mission_name: str, priority: str):
            nonlocal pages_visited_count
            if self.stop_requested: return
            
            pages_visited_count += 1
            page_url = self.page.url
            page_html = await self.page.content()
            page_title = f"{mission_name} - {await self.page.title() or page_url}"
            
            # Save Page Record
            page_id = self.db.add_page(investigation_id, page_url, page_title, priority)
            self.db.add_navigation_link(investigation_id, "ROOT", page_url, pages_visited_count)

            import asyncio
            keyword_findings = await self.keyword_detector.detect_and_locate_keywords(self.page)
            if keyword_findings: self.db.add_keyword_findings(page_id, keyword_findings)
            payment_findings = await self.payment_detector.detect_payment_indicators(self.page, page_html)
            if payment_findings: self.db.add_payment_findings(page_id, payment_findings)

            if progress_callback: progress_callback(f"Capturing Evidence for {mission_name}...")
            
            raw_screenshot = await self.page.screenshot(full_page=False)
            screenshot_filename = f"inv_{investigation_id}_page_{page_id}.png"
            highlighted_path = __import__("core.image_annotator", fromlist=["ImageAnnotator"]).ImageAnnotator.annotate_and_save_screenshot(
                raw_screenshot, screenshot_filename, keyword_findings, payment_findings
            )
            self.db.add_screenshot(page_id, highlighted_path)

        import asyncio
        try:
            await self.init_browser()
            
            # --- PHASE 1: BOOT & AUTHENTICATION ---
            if progress_callback: progress_callback("Phase 1: Booting Homepage & Authentication...")
            self._log(log_callback, investigation_id, "Opening Homepage...", "INFO")
            try: await self.page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            except Exception: pass
            await asyncio.sleep(2) 

            page_html = await self.page.content()
            page_url = self.page.url

            try:
                login_btn = self.page.locator("button:has-text('Log in'), a:has-text('Log in'), button:has-text('Sign in'), a:has-text('Sign in')").first
                if await login_btn.is_visible():
                    self._log(log_callback, investigation_id, "Found 'Log in' button. Clicking to open login modal...", "INFO")
                    await login_btn.click()
                    await asyncio.sleep(1.5)
            except Exception: pass

            if await self.check_login_required(self.page, page_html, page_url):
                login_encountered = True
                auto_login_success = False
                if auth_user and auth_pass:
                    self._log(log_callback, investigation_id, f"🔑 Credentials provided! Executing automated login...", "INFO")
                    try:
                        if auth_mode == "Phone / Mobile Number" or (auth_user.replace("+", "").isdigit() and len(auth_user) >= 10):
                            tab = self.page.locator("text=/Phone number|Mobile No|Mobile/i").first
                            if await tab.is_visible(): await tab.click(); await asyncio.sleep(0.5)
                        elif auth_mode == "User ID / Username" or ("@" not in auth_user and not auth_user.isdigit()):
                            tab = self.page.locator("text=/User ID|Account number|Username/i").first
                            if await tab.is_visible(): await tab.click(); await asyncio.sleep(0.5)
                        elif auth_mode == "Email" or "@" in auth_user:
                            tab = self.page.locator("text=/E-mail|Email/i").first
                            if await tab.is_visible(): await tab.click(); await asyncio.sleep(0.5)

                        user_input = self.page.locator("input[type='tel'], input[type='email'], input[placeholder*='number' i], input[placeholder*='User' i], input[placeholder*='Phone' i], input[name*='user' i], input[name*='phone' i], input[type='text']").first
                        if await user_input.is_visible():
                            await user_input.click()
                            await user_input.press_sequentially(auth_user, delay=50)
                            await asyncio.sleep(0.5)
                        
                        pass_input = self.page.locator("input[type='password'], input[name='password'], input[placeholder*='Password' i]").first
                        if await pass_input.is_visible():
                            await pass_input.click()
                            await pass_input.press_sequentially(auth_pass, delay=50)
                            await asyncio.sleep(0.5)
                        submit_btn = self.page.locator("button:has-text('Log in'), button:has-text('LOGIN'), button:has-text('Sign in'), button[type='submit'], input[type='submit']").first
                        if await submit_btn.is_visible(): await submit_btn.click(); await asyncio.sleep(3.0)

                        if not await self.check_login_required(self.page, await self.page.content(), self.page.url):
                            self._log(log_callback, investigation_id, f"✅ Automated login successful!", "INFO")
                            auto_login_success = True
                    except Exception as auto_err:
                        self._log(log_callback, investigation_id, f"Auto-login failed. Falling back to manual auth...", "WARNING")

                if not auto_login_success:
                    self._log(log_callback, investigation_id, f"🔑 Manual Login Required! Please log in in the browser window...", "WARNING")
                    self.pause_for_auth = True
                    if auth_callback: auth_callback()
                    self.auth_resumed.clear()

                    while self.pause_for_auth and not self.stop_requested:
                        if self.auth_resumed.is_set(): self.pause_for_auth = False; break
                        await asyncio.sleep(1)
                        try:
                            if not await self.check_login_required(self.page, await self.page.content(), self.page.url):
                                self._log(log_callback, investigation_id, f"✅ Manual login detected! Auto-resuming...", "INFO")
                                self.pause_for_auth = False; break
                        except Exception: pass

                self._log(log_callback, investigation_id, "Waiting 4 seconds for SPA Dashboard to fully render...", "INFO")
                await asyncio.sleep(4.0)

            try:
                cancel_btn = self.page.locator("button:has-text('Cancel'), [aria-label='Close'], button:has-text('✕')").first
                if await cancel_btn.is_visible(): await cancel_btn.click(); await asyncio.sleep(0.5)
            except: pass

            # --- PHASE 2: MISSION 1 (WALLET & DEPOSIT) ---
            if not self.stop_requested:
                if progress_callback: progress_callback("Mission 1: Executing Wallet & Deposit Flow...")
                self._log(log_callback, investigation_id, "Mission 1: Starting Wallet/Deposit exploration.", "INFO")
                try:
                    deposit_selector = "button:has-text('Deposit'), a:has-text('Deposit'), button:has-text('Recharge'), a:has-text('Recharge'), button:has-text('Cashier'), a:has-text('Cashier'), button:has-text('Add Money')"
                    deposit_btn = self.page.locator(deposit_selector).first
                    if await deposit_btn.is_visible():
                        await deposit_btn.click()
                        await asyncio.sleep(3.0)

                        upi_card_selectors = [
                            "text=/Other UPI|PhonePe|Paytm|UPI|Pay Tm|Phone Pe/i",
                            "div:has-text('Other UPI'):not(:has(*))", "div:has-text('PhonePe'):not(:has(*))", 
                            "div:has-text('Paytm'):not(:has(*))", "div:has-text('UPI'):not(:has(*))"
                        ]
                        payment_clicked = False
                        for sel in upi_card_selectors:
                            try:
                                card = self.page.locator(sel).first
                                if await card.is_visible():
                                    await card.click()
                                    await asyncio.sleep(2.0)
                                    payment_clicked = True
                                    break
                            except Exception: continue

                        if payment_clicked:
                            try:
                                amount_btn = self.page.locator("button:has-text('500'), div:has-text('500')").first
                                if await amount_btn.is_visible(): await amount_btn.click(); await asyncio.sleep(1.0)
                                
                                submit_pay_btn = self.page.locator("button:has-text('Continue'), button:has-text('Deposit'), button:has-text('Pay')").first
                                if await submit_pay_btn.is_visible():
                                    await submit_pay_btn.click()
                                    await asyncio.sleep(4.0)
                            except Exception: pass

                        try: await self.page.wait_for_selector("text=/@|UPI ID|Scan QR/i", timeout=4000)
                        except Exception: pass
                        
                        await _extract_and_save_evidence("Deposit & Wallet Flow", "High")
                        
                        try:
                            cancel_btn = self.page.locator("button:has-text('Cancel'), [aria-label='Close'], button:has-text('✕')").first
                            if await cancel_btn.is_visible(): await cancel_btn.click(); await asyncio.sleep(1.0)
                            else: await self.page.keyboard.press("Escape")
                        except Exception: pass
                except Exception as e:
                    self._log(log_callback, investigation_id, f"Mission 1 failed: {e}", "WARNING")

            # --- PHASE 3: MISSION 2 (SPORTS BETTING) ---
            if not self.stop_requested:
                if progress_callback: progress_callback("Mission 2: Executing Sports Betting Flow...")
                self._log(log_callback, investigation_id, "Mission 2: Starting Sports Betting exploration.", "INFO")
                try:
                    await self.page.goto(target_url, wait_until="domcontentloaded")
                    await asyncio.sleep(2.0)
                    
                    sports_btn = self.page.locator("a:has-text('Sports'), button:has-text('Sports'), text=/Sports/i").first
                    if await sports_btn.is_visible():
                        await sports_btn.click()
                        await asyncio.sleep(3.0)
                        
                        sport_cat = self.page.locator("text=/Cricket|Football/i").first
                        if await sport_cat.is_visible():
                            await sport_cat.click()
                            await asyncio.sleep(2.0)
                            
                            odd_btn = self.page.locator("button:has-text('.'), div.odd, span.odd-value").nth(2)
                            if await odd_btn.is_visible():
                                await odd_btn.click()
                                await asyncio.sleep(2.0)
                                
                                stake_input = self.page.locator("input[placeholder*='Stake' i], input[placeholder*='Amount' i]").first
                                if await stake_input.is_visible():
                                    await stake_input.fill("10")
                                    await asyncio.sleep(1.0)
                                    
                        await _extract_and_save_evidence("Sports Betting Flow", "Medium")
                except Exception as e:
                    self._log(log_callback, investigation_id, f"Mission 2 failed: {e}", "WARNING")

            # --- PHASE 4: MISSION 3 (CASINO & INSTANT GAMES) ---
            if not self.stop_requested:
                if progress_callback: progress_callback("Mission 3: Executing Casino & Aviator Flow...")
                self._log(log_callback, investigation_id, "Mission 3: Starting Casino/Aviator exploration.", "INFO")
                try:
                    await self.page.goto(target_url, wait_until="domcontentloaded")
                    await asyncio.sleep(2.0)
                    
                    casino_btn = self.page.locator("a:has-text('Casino'), button:has-text('Casino'), a:has-text('Instant Games')").first
                    if await casino_btn.is_visible():
                        await casino_btn.click()
                        await asyncio.sleep(3.0)
                        
                        game_card = self.page.locator("text=/Aviator|JetX/i").first
                        if await game_card.is_visible():
                            await game_card.click()
                            await asyncio.sleep(4.0)
                            
                        await _extract_and_save_evidence("Casino Game Canvas Flow", "Medium")
                except Exception as e:
                    self._log(log_callback, investigation_id, f"Mission 3 failed: {e}", "WARNING")

            status = "STOPPED" if self.stop_requested else "COMPLETED"
            duration = __import__("time").time() - start_time
            self.db.update_investigation(investigation_id, status, duration, pages_visited_count, login_encountered)
            self._log(log_callback, investigation_id, f"Investigation {status}. Missions Executed: {pages_visited_count}, Duration: {duration:.2f}s", "INFO")

            return {
                "status": status,
                "investigation_id": investigation_id,
                "total_pages": pages_visited_count,
                "duration": duration
            }

        except Exception as err:
            self._log(log_callback, investigation_id, f"Fatal Investigation Error: {err}", "ERROR")
            self.db.update_investigation(investigation_id, "FAILED", __import__("time").time() - start_time, 0, login_encountered)
            return {"status": "FAILED"}
            
        finally:
            await self.close_browser()

    def _log(self, callback: Optional[Callable[[str, str], None]], inv_id: str, action: str, status: str):
        self.db.log_action(inv_id, action, status)
        if callback:
            callback(action, status)
