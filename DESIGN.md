# Design System: StudMatch Campus Platform
**Skill:** stitch-design-taste  
**Target Platform:** Google Stitch (labs.google/stitch) & Telegram Mini App (TWA)  
**Product:** StudMatch — Student Dating, Campus Networking, Career & Project Matchmaker

---

## Configuration — Set Your Style
These dials control the aesthetic intensity, density, and layout variance for all screens generated in Google Stitch:

| Dial | Level | Description |
|------|-------|-------------|
| **Creativity** | `8` | Expressive student editorial, confident asymmetry, contextual inline image typography in headlines, tactile floating island navigation. |
| **Density** | `5` | Balanced social-mobile density: generous touch targets (≥44px), breathing room for candidate photos, compact stats badges for academic scores and ratings. |
| **Variance** | `8` | Dynamic layout shifts: asymmetric split discovery decks, podium-style Hall of Fame leaderboards, offset Bento grid for economy and quests. |
| **Motion Intent** | `7` | Weighty spring physics (`stiffness: 110, damping: 22`), micro-haptics, card flip/drag gestures, and staggered cascade reveals. |

---

## 1. Visual Theme & Atmosphere
StudMatch merges high-end collegiate editorial design with tactile iOS-style island docks. The mood is authentic, optimistic, and energetic — like an Ivy League design studio or modern European campus incubator. It completely eschews generic dating app templates (loud gradients, generic neon glows, flat stock avatars).

Surfaces feel physical and warm: ultra-clean canvas backgrounds (`#F8F9FE`), pure white card surfaces (`#FFFFFF`) with diffused soft ambient shadows, deep charcoal typography (`#18181B`), and calibrated accents that signify academic prestige (Iris `#6C5CE7` and Collegiate Amber `#D97706`).

---

## 2. Color Calibration & Semantic Roles

### Neutral Core Foundation
- **Canvas Base** (`#F8F9FE`) — Primary page surface. Soft, clean, slightly cool-tinted paper white. Never clinical hospital blue or sterile gray.
- **Card Surface** (`#FFFFFF`) — High-elevation surface for candidate cards, bottom sheets, and island menus.
- **Surface Muted** (`#F1F5F9`) — Neutral background for segmented pills, search inputs, and inactive tabs.
- **Charcoal Ink** (`#18181B`) — Primary headline and body typography (Zinc-950 equivalent). Pure black (`#000000`) is strictly banned.
- **Steel Secondary** (`#64748B`) — Subtitles, university majors, metadata, time ago, and secondary labels.
- **Muted Slate** (`#94A3B8`) — Placeholders, inactive icons, locked days, and disabled states.
- **Whisper Border** (`rgba(226, 232, 240, 0.8)`) — Structural 1px separation lines. Transparent and delicate.
- **Ambient Elevation Shadow** (`0 14px 34px -10px rgba(30, 31, 46, 0.08)`) — Soft, diffused shadow tinted to charcoal background hue.

### Singular Primary Accent & Status Tokens
- **Collegiate Iris** (`#6C5CE7`) — Single primary brand accent for active navigation, main CTA buttons, verified badges, and key interactive highlights.
- **Campus Gold / Зачёты** (`#D97706`, fill background `#FEF3C7`, border `rgba(245, 158, 11, 0.4)`) — Economy badge, credits balance (`🎓`), and premium tier indicators.
- **Streak Fire** (`#EA580C`, fill background `#FFEDD5`) — Daily streak counter (`🔥`) and stipend claims.
- **Emerald Affirm** (`#10B981`, fill background `#DCFCE7`) — Success messages, like match confirmation, and completed quest badges.
- **Crimson Heart** (`#FF4B72`) — Romance / Like interactions in Dating mode.

### Banned Color Patterns
- Neon purple / cyan glowing drop shadows (the "AI Cyberpunk" tell)
- Pure Pitch Black (`#000000`) — always use Charcoal Ink (`#18181B`)
- Oversaturated backgrounds with saturation > 80%
- Fluctuating between warm yellow-grays and cool slate within the same view

---

## 3. Typographic Architecture

- **Display & Headlines:** `Cabinet Grotesk` or `Satoshi` (Weight: 800/900). Track-tight (`letter-spacing: -0.03em`), compressed line height (`line-height: 1.15`). Weight-driven hierarchy rather than gigantic font sizes.
- **Body & Captions:** `Satoshi` or `Geist` (Weight: 500/600). Relaxed leading (`line-height: 1.5`), max 60 characters per line.
- **Numbers, Ratings & Academic Metadata:** `JetBrains Mono` or `Geist Mono` (Weight: 700). Applied to student ratings (`⭐ 4.92`), balance (`1 250 🎓`), and streaks (`14 дн.`).
- **Scale Hierarchy:**
  - Screen Titles: `clamp(1.5rem, 5vw, 1.85rem)` (Weight 800)
  - Section Headings: `1.15rem` (Weight 700)
  - Card Titles (Name, Age): `1.35rem` (Weight 800)
  - Body Text: `0.9375rem` / `15px` (Weight 500)
  - Metadata / Badges: `0.75rem` / `12px` (Weight 700, uppercase letter-spacing `+0.5px`)

### Banned Typography
- `Inter` — banned for creative student editorial contexts.
- Default system serifs (`Times New Roman`, `Georgia`, `Garamond`).
- Screaming all-caps body text.

---

## 4. Screen-by-Screen Semantic Blueprint for Stitch

### Screen A: Candidate Discovery Deck (`#screen-explore`)
- **Top Header Bar:** Left: full brand wordmark StudMatch. Center: dynamic iOS segmented pill toggle `[💘 Знакомства | 💼 Карьера | 🚀 Проекты]`. Right: expanding campus economy pill `🎓 350` and trophy button for Hall of Fame.
- **Hero Card (Candidate Card):** 
  - Massive rounded corners (`28px`), full viewport aspect ratio (approx. 4:5).
  - High-res photo container with top stories-style progress bar for multiple photos.
  - Floating bottom info plate with frosted glass pill badges: University (`НИУ ВШЭ`, `МГУ`, `МГТУ им. Баумана`), Faculty/Major (`Дизайн`, `CS & AI`, `Экономика`), and Course (`3 курс`).
  - Name, verified student checkmark (`🎓`), and bio excerpt in clean typography — never covering the student's face.
- **Floating Island Dock Action Deck:**
  - Round tactile buttons with distinct weights:
    - Pass (`✕`, soft slate `#64748B`, white card fill)
    - Rewind / Шпора (`🔄`, amber `#D97706`, inventory count badge)
    - Superlike (`⭐`, blue sapphire `#3B82F6`)
    - Like (`❤️`, primary crimson `#FF4B72`, primary gradient pulse)

### Screen B: Campus Economy & Market Modal (`#shopModal`)
- **Container:** Sliding bottom sheet with drag handle, white card background (`#FFFFFF`), rounded top corners (`28px`), height `88dvh`.
- **Header:** Title badge `КАМПУС-МАРКЕТ`, header title `Магазин и Зачётка`, and dual balance chips (`🎓 350 зачётов` and `🔥 7 дн. серия`).
- **Segmented Tabs:** `[🛍 Витрина | 📋 Задания | 🎒 Инвентарь]`.
- **Tab 1 — Catalog:**
  - Vertical list of shop items with icon box (44x44px), title, description, and price pill button (`80 🎓` with subtle ruble equivalent).
- **Tab 2 — Quests & Streak:**
  - 7-day streak card banner with gradient tint (`#FFF7ED`), claim button, and day pills (Д1..Д7) highlighting current claimable day.
  - Daily quest cards with percentage progress bar and green claim button (`Забрать +15 🎓`).
- **Tab 3 — Inventory:**
  - Active profile frames (`🥇 Отличник`, `👔 Староста`, `🌌 Неон`) with equip/unequip toggles (`Надето ✅` / `Надеть`).

### Screen C: Hall of Fame / Зал Славы (`#hallOfFameModal`)
- **Header:** Trophy badge `ТОП СТУДЕНТОВ`, title `Зал славы`, subtitle `Лучшие студенты кампуса по академическому рейтингу`.
- **Top 3 Podium Component:**
  - Asymmetric 3-column podium: 2nd place (left), 1st place (elevated center with gold wreath crown), 3rd place (right).
  - Real circular avatars with ranking badges, student name, and rating score (`⭐ 98.4`).
- **Leaderboard List:**
  - Ranked rows with position badge (`#4`, `#5`), user avatar with equipped frame, university tag, and rating progress.

### Screen D: Student Profile (`#screen-profile`)
- **Hero Photo Slider:** Horizontal carousel with dot indicators and quick-edit button.
- **Academic Verification Banner:** Official student verification status with university seal.
- **Quick Economy Widget:** Gold campus card banner displaying balance, streak, and `В магазин 🏪` action button.
- **Photo Grid (Bento):** 6-slot masonry/bento gallery with add-photo dashed placeholder tiles.
- **Settings & Privacy Group:** Grouped iOS-style card list with chevron indicators.

---

## 5. Component Stylings & Interaction Rules

- **Buttons:**
  - Primary CTA: Collegiate Iris (`#6C5CE7`) or Accent Gradient with pure white text.
  - Active Push Feedback: `transform: scale(0.96) translateY(1px)` with smooth cubic-bezier (`0.16, 1, 0.3, 1`). No outer neon glow.
  - Disabled State: Slate background (`#94A3B8`), opacity `0.5`, no pointer events.
- **Floating Island Dock (`.floating-nav`):**
  - Pill shape suspended `16px` above screen bottom (`margin-bottom: max(env(safe-area-inset-bottom), 16px)`).
  - Background: Frosted glass (`rgba(255, 255, 255, 0.88)` with `backdrop-filter: blur(20px)`).
  - SVG navigation icons with active indicator pill transition.
- **Cards & Bottom Sheets:**
  - Generous border-radius (`24px` to `28px`).
  - Subtle structural border (`1px solid rgba(226, 232, 240, 0.8)`).
  - Never stack card inside card inside card — use horizontal dividers (`border-top: 1px solid #F1F5F9`) or spatial breathing gaps.
- **Inputs & Fields:**
  - Label strictly above the input.
  - Background `#F8FAFC`, border `1px solid #E2E8F0`, focus ring `2px solid #6C5CE7`.
  - Native caret color `#6C5CE7`.
- **Loaders & Skeletons:**
  - Fluid skeletal shimmer matching exact layout shapes and radii. Circular spinners are banned.

---

## 6. Layout & Responsive Principles (Telegram Mini App Viewports)

- **Mobile Viewport Targets:** 
  - Standard iPhone (`390px × 844px`)
  - Compact Phone / SE (`375px × 667px`)
  - Tablet / Desktop Preview (`768px+`)
- **Safe Area Inset Handling:**
  - Top header padding: `padding-top: max(var(--safe-top, 0px), 12px)`.
  - Bottom dock spacing: `padding-bottom: max(var(--safe-bottom, 0px), 16px)`.
  - Full-height containers strictly use `min-height: 100dvh` (never `100vh` to avoid mobile address bar jumps).
- **No Horizontal Scroll:** All headers, tabs, and action docks have `max-width: 100%`, `overflow-x: hidden` with `box-sizing: border-box`.
- **Expanding Header Badges:** Header actions (`openShopBtn`) must use `width: auto; min-width: 36px; padding: 0 10px; display: inline-flex;` to naturally expand when balance reaches thousands (`1 250 🎓`).

---

## 7. Motion & Physics Directives (Implementation Intent)

- **Physics Spec:** Spring physics for all card swipes and modal sheets: `stiffness: 110, damping: 22, mass: 1`.
- **Cascade Reveals:** Card decks and shop lists stagger entrance by `50ms` per item (`animation: slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards`).
- **Hardware Acceleration:** Animations restricted exclusively to `transform` and `opacity`. Zero animations on `height`, `width`, `top`, or `left`.
- **Perpetual Micro-Motions:**
  - Daily streak fire has a subtle breathing pulse (`transform: scale(1.05)` at 2s interval).
  - Floating action buttons have micro-spring depression on tap.

---

## 8. Anti-Patterns (Strictly Banned in Stitch Prompts)

- ❌ **No generic AI copywriting:** Banned words: "Elevate your journey", "Seamlessly connect", "Unleash potential", "Next-Gen matchmaking". Use natural student campus language.
- ❌ **No placeholder emojis in headers:** Avoid excessive emoji clutter in typographic headers. Keep iconography semantic and deliberate.
- ❌ **No `Inter` or generic browser serifs (`Times`, `Georgia`).**
- ❌ **No pure black backgrounds or text (`#000000`).**
- ❌ **No neon purple/cyan glowing buttons.**
- ❌ **No fake symmetric 3-column card rows on mobile.**
- ❌ **No filler navigation cues:** "Scroll down to see more", "Swipe to discover".
- ❌ **No broken image links:** Use verified student portraits with real faces, authentic campus settings, and natural lighting.
- ❌ **No card-inside-card UI Russian nesting dolls.**

---

## 9. Google Stitch Production Prompts (Ready-to-Paste)

### Prompt 1: Candidate Discovery & Match Card Deck
> "A mobile screen for StudMatch, a collegiate student networking and dating app. Clean light aesthetic, Canvas White #F8F9FE background, Charcoal Ink typography #18181B. At the top, a refined header with a dynamic segmented pill switch (Dating, Career, Projects) and an expanding amber badge for academic credits (🎓 350). The centerpiece is a large student profile card with rounded corners (28px) and soft shadow, showing an authentic university student photo, campus tags (HSE University, Computer Science, 3rd year), verified student badge, and concise bio. Floating above the bottom is an island action dock with tactile circular buttons (Rewind, Pass, Superlike, Like) and a sleek frosted glass bottom navigation bar."

### Prompt 2: Campus Market, Quests & Streak Modal
> "A mobile bottom sheet modal for StudMatch Campus Market & Economy. Off-white card surface #FFFFFF, rounded top corners 28px. Header has a gold badge 'CAMPUS MARKET', balance chips (350 credits, 7-day streak fire), and a clean close button. Three segmented tabs: Catalog, Quests, Inventory. Active tab shows an orange-tinted 7-day daily streak card with daily reward pills and claim button, followed by daily quest cards with micro progress bars and green claim badges (+15 credits). Clean typographic hierarchy, Satoshi font, zero neon glows."

### Prompt 3: Hall of Fame Leaderboard
> "A mobile bottom-sheet modal for StudMatch Hall of Fame. Creamy white background, crisp charcoal typography. Top features a gold trophy badge and header 'Hall of Fame: Top Campus Students'. Below is an asymmetric 3-column podium: 1st place in the elevated center with a gold laurel crown and student avatar, flanked by 2nd and 3rd place. Underneath is a clean ranked list of students with verification tags, faculty badges, and academic rating scores (⭐ 98.4)."
