---
target: web/templates/webapp.html
total_score: 29
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 2
target_identity: "file:C:\\Users\\pokok\\Documents\\antigravity\\bot-univer\\web\\templates\\webapp.html"
target_fingerprint: "sha256:fe8fac8337085ac008c75bc997806e8268377f80f3c64a332806dea96248715b"
target_path: "C:\\Users\\pokok\\Documents\\antigravity\\bot-univer\\web\\templates\\webapp.html"
timestamp: 2026-10-05T09-32-03Z
slug: web-templates-webapp-html
---
# Impeccable Design Critique: StudMatch Campus Economy & Shop
**Target Surface:** Campus Market, Credit Packs, Gifts, Quests & Backpack Inventory (`#shopModal`, `#sendGiftModal`, `#spendConfirmModal`)  
**Product:** StudMatch (Telegram Mini App)  
**Evaluator:** Impeccable Dual-Agent System (Assessment A: Design Review + Assessment B: Deterministic Detector)

---

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Real-time balance chips and reset countdowns work well; raw text loaders ('Загрузка...') violate shimmer standard. |
| 2 | Match System / Real World | 4 | Genuine collegiate metaphors: «Зачёты» (🎓), «Ежедневная стипендия», «Шпоры» (🔄), «Справка» (🩺), «Староста» (👔). |
| 3 | User Control and Freedom | 3 | Seamless frame equip/unequip toggles; however, top promo banners cannot be collapsed or dismissed. |
| 4 | Consistency and Standards | 2 | Fragmented spend confirmation (`#spendConfirmModal` vs browser `confirm()`); arcade dark mode (#1E1B4B) in `#fortuneWinModal`. |
| 5 | Error Prevention | 3 | Disabled states on unaffordable items and 1-time limit on Starter Pack; lacks direct top-up flow from failed purchase. |
| 6 | Recognition Rather Than Recall | 4 | Live interactive avatar frame preview in Backpack; clear before-and-after spend arithmetic sheet. |
| 7 | Flexibility and Efficiency | 3 | Quick category filter pills and 1-tap balance top-up shortcuts across views. |
| 8 | Aesthetic and Minimalist Design | 2 | Top of catalog congested by 2 tall promo banners; 31 undersized UI text elements (8.5px–10.5px); cramped badge padding. |
| 9 | Error Recovery | 3 | Insufficient funds feedback exists, but redirects to general view instead of contextual pack selection. |
| 10 | Help and Documentation | 2 | Mechanics of active boosts, streak freeze expiry, and rewind limits lack inline tooltip explanations. |
| **Total** | | **29/40** | **Moderate / High-Potential (72.5%)** |

---

## Design Specificity Verdict

### LLM Assessment (8.5 / 10)
StudMatch achieves high collegiate specificity. Unlike generic freemium dating apps with generic coins and neon chests, the economy is authentically framed around university life: academic credits («Зачёты»), daily stipends, medical excuses for streaks, and faculty titles.
The friction points stem from two stylistic compromises:
1. An arcade casino visual disconnect in the Fortune Wheel and dark `#1E1B4B` win celebration card.
2. An overly promotional hero stack at the top of the catalog that feels like an e-commerce flash sale rather than a curated student campus marketplace.

### Deterministic Scan (Assessment B)
- **162 findings** detected (157 warnings, 5 advisories).
- **Quality (115):** 49 low-contrast alerts (amber `#f59e0b` and light slate), 31 undersized functional UI text instances below the 11px floor (down to 8.5px in wheel cap and 9px in navigation tabs), 27 tiny text instances in secondary labels, and 2 cramped padding badges.
- **Slop (47):** 12 instances of bouncy `cubic-bezier(0.175, 0.885, 0.32, 1.275)` curves, 11 nested cards, 10 dark-glow box shadows, and 6 gradient clipped texts.

---

## Overall Impression
The Campus Economy is conceptually rich and culturally resonant, but mechanically split between two distinct eras of the app. High-trust surfaces like the Backpack frame preview and the Spend Confirmation sheet feel polished and native, while the main Catalog and Fortune win modal carry visual noise, undersized mobile text, and inconsistent confirmation flows.

---

## What's Working
1. **Live Avatar Frame Preview in Backpack:** Immediate tactile gratification when equipping frames directly on the student avatar with unequip safety.
2. **High-Trust Spend Confirmation Sheet (`#spendConfirmModal`):** Transparent before-and-after balance calculator eliminating accidental credit drain anxiety.
3. **Collegiate Identity Grounding:** Academic naming («Шпоры», «Справка», «Стипендия») removes freemium cynicism.

---

## Priority Issues

### [P0] Inconsistent Spend Confirmation in Main Catalog
- **What:** Purchasing items in the main catalog (`buyShopItem`) invokes a generic browser `confirm()` / `Telegram.WebApp.showConfirm()` instead of the high-trust `#spendConfirmModal`.
- **Why it matters:** Inconsistent spend UX damages user trust and breaks the financial safety patterns established for gifts and blur unmasking.
- **Fix:** Wire `buyShopItem` to trigger `showSpendConfirmModal()` with item icon, title, deduction, and before/after arithmetic.
- **Suggested command:** `$impeccable harden web/templates/webapp.html`

### [P1] Promo Banner Stacking in Маркет (Catalog View)
- **What:** The Grant Wheel banner (80px) and Special Offer banner (120px) stack at the very top of `#shopViewCatalog`, pushing all catalog items below the mobile fold.
- **Why it matters:** Users landing on "Маркет" expect to see products, not two massive promo billboards before any item card.
- **Fix:** Condense the Grant Wheel callout into a compact ticket pill header and move the Special Offer into a featured card within the catalog grid.
- **Suggested command:** `$impeccable distill web/templates/webapp.html`

### [P1] Dark Arcade Theme Disconnect in `#fortuneWinModal`
- **What:** When a user claims their daily grant or spins the wheel, `#fortuneWinModal` pops up with a dark `#1E1B4B` container, glowing halos, and bouncy easing, clashing with the light collegiate design system.
- **Why it matters:** Breaks visual immersion and creates an unwanted "online casino" association.
- **Fix:** Refactor `#fortuneWinModal` to a collegiate white sheet card (`#FFFFFF`) with gold foil laurel border, JetBrains Mono reward typography, and ease-out-expo spring motion.
- **Suggested command:** `$impeccable quieter web/templates/webapp.html`

### [P2] Undersized Functional Text Across Shop & Tabs (11px Floor Violation)
- **What:** Tab labels (`.shop-tab-text`) are 9px, badge headers are 9px–10px, and wheel cap label is 8.5px.
- **Why it matters:** Difficult to read on high-DPI smartphones, causing eye strain and misclicks.
- **Fix:** Elevate all functional labels to a strict 11px–12px floor and increase badge padding from 2px to 4px–6px.
- **Suggested command:** `$impeccable typeset web/templates/webapp.html`

### [P2] Choice Overload in Top-up Packages (7 Simultaneous Tiers)
- **What:** `#shopCreditPacksGrid` presents 7 different credit packages with dense pricing calculations at once.
- **Why it matters:** Violates Hick's Law, causing conversion drop-off and decision fatigue.
- **Fix:** Curate into 3 highlighted tiers (Студенческий, Сессия закрыта, Красный диплом) + a discreet expander for extra tiers.
- **Suggested command:** `$impeccable distill web/templates/webapp.html`

### [P3] Sticky Action Placement in Send Gift Modal
- **What:** `#sendGiftModal` is a tall single-column scroll where the "Подарить" button is pushed off-screen when the keyboard opens for the greeting text.
- **Why it matters:** Friction during gift checkout; requires manual scrolling while keyboard is active.
- **Fix:** Pin the submit button to a sticky bottom dock with safe-area inset inside the modal.
- **Suggested command:** `$impeccable adapt web/templates/webapp.html`

---

## Persona Red Flags

- **Casey (Single-Handed Mobile User):**
  - Cannot reach the gift submission button without closing keyboard and scrolling.
  - 9px tab buttons in the bottom dock require precise thumb placement.
- **Jordan (First-Time Frosh):**
  - Confused by the difference between "Маркет" and "Зачёты" tabs.
  - Sees 7 top-up tiers and abandons due to pricing comparison fatigue.
- **Alex (Active Campus Power User):**
  - Annoyed that daily grant wheel cannot be spun quickly without full-screen modal transition.
  - Wants 1-click equip on newly purchased frames without manually navigating to Backpack.

---

## Minor Observations
1. Raw `"Загрузка каталога..."` text strings should be replaced with CSS skeleton shimmers.
2. Inconsistent category naming: "Бусты ленты" in catalog vs "Расходные бусты" in backpack.
3. Empty state in Send Gift recipient selector lacks a direct CTA to explore students in Dating or Projects.

---

## Questions to Consider
1. What if the daily Grant Wheel were accessible as a 1-tap "Scratch Card" or "Stipend Ticket" directly in the Quests tab instead of an arcade spinning wheel?
2. Should purchasing a profile frame immediately offer a prompt: *«Установить на профиль прямо сейчас?»*
3. Can the "Маркет" and "Зачёты" tabs be unified into a cleaner "Витрина" with an inline balance top-up bar?
