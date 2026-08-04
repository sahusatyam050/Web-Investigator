import re
import logging
from typing import Dict, List, Any
from rapidfuzz import fuzz
from config import CATEGORIZED_KEYWORDS

logger = logging.getLogger(__name__)

class KeywordDetector:
    """Step 8: Detects categorized keywords inside DOM & extracts element bounding boxes."""

    def __init__(self, categories: Dict[str, List[str]] = CATEGORIZED_KEYWORDS):
        self.categories = categories

    async def detect_and_locate_keywords(self, page) -> List[Dict[str, Any]]:
        """
        Executes JavaScript in Playwright to find matching keyword elements
        and extracts their exact bounding box (x, y, width, height).
        """
        findings = []
        
        # Pass categories into Playwright JS context
        js_script = """
        (categories) => {
            const results = [];
            const walkTextNodes = (element) => {
                const elements = document.querySelectorAll('button, a, span, p, h1, h2, h3, h4, h5, h6, label, div.card, nav, input[type="button"], input[type="submit"]');
                elements.forEach((el) => {
                    const text = el.innerText || el.textContent || '';
                    if (!text || text.trim().length === 0 || text.length > 200) return;
                    
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0 || rect.top < 0) return;

                    const cleanText = text.trim().toLowerCase();
                    
                    for (const [category, keywords] of Object.entries(categories)) {
                        for (const kw of keywords) {
                            const kwLower = kw.toLowerCase();
                            if (cleanText.includes(kwLower)) {
                                results.push({
                                    keyword: kw,
                                    category: category,
                                    matched_text: text.trim().substring(0, 50),
                                    bounding_box: {
                                        x: Math.round(rect.left + window.scrollX),
                                        y: Math.round(rect.top + window.scrollY),
                                        width: Math.round(rect.width),
                                        height: Math.round(rect.height)
                                    }
                                });
                                break; // Limit 1 category match per element
                            }
                        }
                    }
                });
            };
            walkTextNodes(document.body);
            return results;
        }
        """
        
        try:
            raw_results = await page.evaluate(js_script, self.categories)
            
            # Deduplicate findings by bounding box & keyword
            seen = set()
            for r in raw_results:
                bbox = r["bounding_box"]
                key = (r["keyword"], r["category"], bbox["x"], bbox["y"])
                if key not in seen:
                    seen.add(key)
                    findings.append({
                        "keyword": r["keyword"],
                        "category": r["category"],
                        "count": 1,
                        "matched_text": r["matched_text"],
                        "bounding_box": bbox
                    })
                    
        except Exception as e:
            logger.error(f"Error during keyword detection JS evaluation: {e}")
            
        return findings
