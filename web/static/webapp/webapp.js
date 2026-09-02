/**
 * StudMatch Telegram Mini App (TWA / WebApp) Core Client
 * Touch-driven swipe engine, multi-photo carousel, candidate details sheet,
 * search filters, superlike with compliment, reports, and match profile viewer.
 */

(function () {
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  // App State
  const state = {
    token: localStorage.getItem("studmatch_token") || "",
    currentUser: null,
    feed: [],
    currentCardIndex: 0,
    matches: [],
    incomingLikes: [],
    activeTab: "explore",
    isSwiping: false,
    selectedCandidateForSuperlike: null,
    selectedCandidateForReport: null,
  };

  // DOM Elements
  const deckContainer = document.getElementById("cardDeck");
  const deckEmpty = document.getElementById("deckEmpty");
  const matchModal = document.getElementById("matchModal");
  const detailsSheetOverlay = document.getElementById("detailsSheetOverlay");
  const filtersModal = document.getElementById("filtersModal");
  const superlikeModal = document.getElementById("superlikeModal");
  const reportModal = document.getElementById("reportModal");
  const matchProfileModal = document.getElementById("matchProfileModal");
  const navButtons = document.querySelectorAll(".nav-tab-btn");

  // Haptic feedback helper
  function triggerHaptic(type = "light") {
    try {
      if (tg && tg.HapticFeedback) {
        if (type === "success") {
          tg.HapticFeedback.notificationOccurred("success");
        } else if (type === "medium") {
          tg.HapticFeedback.impactOccurred("medium");
        } else if (type === "heavy") {
          tg.HapticFeedback.impactOccurred("heavy");
        } else {
          tg.HapticFeedback.impactOccurred("light");
        }
      }
    } catch (e) {
      console.warn("Haptic error", e);
    }
  }

  // API helper with Authorization header
  async function apiFetch(url, options = {}) {
    options.headers = options.headers || {};
    if (state.token) {
      options.headers["Authorization"] = `Bearer ${state.token}`;
    }
    options.headers["Content-Type"] = "application/json";

    const res = await fetch(url, options);
    if (res.status === 401) {
      console.warn("[StudMatch] Token expired or 401, re-authenticating...");
      await authenticateUser();
      return;
    }
    return await res.json();
  }

  // 1. Авторизация
  async function authenticateUser() {
    let initData = tg?.initData || "";
    if (!initData && window.location.hash) {
      try {
        const hash = window.location.hash.slice(1);
        const params = new URLSearchParams(hash);
        initData = params.get("tgWebAppData") || "";
      } catch (e) {}
    }
    if (!initData) {
      initData = "dev_mock";
    }

    console.log("[StudMatch] Authenticating, initData length:", initData.length);

    try {
      const res = await fetch("/api/webapp/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: initData }),
      });
      const data = await res.json();
      console.log("[StudMatch] Auth result:", res.status, data);

      if (data.status === "ok") {
        state.token = data.token;
        state.currentUser = data.user;
        localStorage.setItem("studmatch_token", data.token);
        updateHeaderUser();
        loadFeed();
      } else {
        deckContainer.innerHTML = `
          <div class="deck-empty" style="display:flex;">
            <div class="deck-empty-icon">🔒</div>
            <h2 class="deck-empty-title">Авторизация в Telegram</h2>
            <p class="deck-empty-desc">${data.detail || "Не удалось проверить сессию Telegram."}</p>
            <button class="btn-primary" onclick="location.reload()" style="max-width: 220px; margin: 0 auto;">
              🔄 Попробовать снова
            </button>
          </div>
        `;
      }
    } catch (err) {
      console.error("[StudMatch] Auth error:", err);
      deckContainer.innerHTML = `
        <div class="deck-empty" style="display:flex;">
          <div class="deck-empty-icon">⚠️</div>
          <h2 class="deck-empty-title">Ошибка соединения</h2>
          <p class="deck-empty-desc">Не удалось подключиться к серверу StudMatch.</p>
          <button class="btn-primary" onclick="location.reload()" style="max-width: 220px; margin: 0 auto;">
            🔄 Повторить
          </button>
        </div>
      `;
    }
  }

  function updateHeaderUser() {
    const modeBadge = document.getElementById("headerModeBadge");
    if (modeBadge && state.currentUser) {
      const isCareer = state.currentUser.mode === "career";
      modeBadge.textContent = isCareer ? "💼 Карьера" : "💘 Знакомства";
    }
  }

  // 2. Навигация по табам
  function setupNavigation() {
    navButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;
        switchTab(tab);
      });
    });

    const modeBadge = document.getElementById("headerModeBadge");
    if (modeBadge) {
      modeBadge.addEventListener("click", toggleMode);
    }

    // Кнопка открытия фильтров в шапке
    const openFiltersBtn = document.getElementById("openFiltersBtn");
    if (openFiltersBtn) {
      openFiltersBtn.addEventListener("click", openFiltersModal);
    }

    // Кнопки в Empty State колоды
    document.getElementById("resetSwipesDeckBtn")?.addEventListener("click", resetSwipesAndReload);
    document.getElementById("changeFiltersDeckBtn")?.addEventListener("click", openFiltersModal);

    setupModalListeners();
  }

  async function resetSwipesAndReload() {
    triggerHaptic("heavy");
    deckContainer.innerHTML = '<div style="text-align:center;padding:50px;color:var(--text-muted);">Сброс истории свайпов...</div>';
    deckEmpty.style.display = "none";
    try {
      await apiFetch("/api/webapp/reset_swipes", { method: "POST" });
      state.feed = [];
      state.currentCardIndex = 0;
      await loadFeed();
    } catch (e) {
      console.error("Reset swipes error:", e);
      location.reload();
    }
  }

  function switchTab(tabName) {
    if (state.activeTab === tabName) return;
    state.activeTab = tabName;
    triggerHaptic("light");

    navButtons.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tabName);
    });

    document.querySelectorAll(".app-screen").forEach((screen) => {
      screen.classList.toggle("active", screen.id === `screen-${tabName}`);
    });

    if (tabName === "matches") {
      loadMatches();
    } else if (tabName === "likes") {
      loadIncomingLikes();
    } else if (tabName === "profile") {
      loadProfile();
    }
  }

  async function toggleMode() {
    if (!state.currentUser) return;
    const nextMode = state.currentUser.mode === "career" ? "dating" : "career";
    triggerHaptic("medium");

    try {
      const res = await apiFetch("/api/webapp/profile/mode", {
        method: "POST",
        body: JSON.stringify({ mode: nextMode }),
      });
      if (res && res.status === "ok") {
        state.currentUser.mode = res.mode;
        updateHeaderUser();
        state.feed = [];
        state.currentCardIndex = 0;
        loadFeed();
      }
    } catch (e) {
      console.error("Toggle mode error:", e);
    }
  }

  // 3. Загрузка ленты свайпов (Feed)
  async function loadFeed() {
    try {
      console.log("[StudMatch] Loading feed profiles...");
      const data = await apiFetch("/api/webapp/feed");
      console.log("[StudMatch] Feed received:", data);
      if (data && data.profiles) {
        state.feed = data.profiles;
        state.currentCardIndex = 0;
        renderCardStack();
      }
    } catch (err) {
      console.error("[StudMatch] Feed error:", err);
      deckContainer.innerHTML = `
        <div class="deck-empty" style="display:flex;">
          <div class="deck-empty-icon">⚠️</div>
          <h2 class="deck-empty-title">Ошибка ленты</h2>
          <p class="deck-empty-desc">Не удалось загрузить анкеты. Проверьте соединение.</p>
          <button class="btn-primary" onclick="location.reload()" style="max-width: 220px; margin: 0 auto;">
            🔄 Обновить
          </button>
        </div>
      `;
    }
  }

  function renderCardStack() {
    deckContainer.innerHTML = "";

    const remaining = state.feed.slice(state.currentCardIndex);
    if (remaining.length === 0) {
      deckEmpty.style.display = "flex";
      return;
    }
    deckEmpty.style.display = "none";

    // Рендерим до 3 карточек в стеке
    const visibleCards = remaining.slice(0, 3).reverse();
    visibleCards.forEach((profile, index) => {
      const isTop = index === visibleCards.length - 1;
      const cardEl = createCardElement(profile, isTop);
      deckContainer.appendChild(cardEl);

      if (isTop) {
        initCardDrag(cardEl, profile);
      }
    });
  }

  // 4. Создание DOM элемента карточки с каруселью фото
  function createCardElement(profile, isTop) {
    const card = document.createElement("div");
    card.className = "swipe-card";
    card.dataset.userId = profile.user_id;

    const photos = profile.photos && profile.photos.length > 0
      ? profile.photos
      : ["https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"];

    card.dataset.photoIndex = "0";

    const verifiedBadge = profile.is_verified ? '<span class="card-badge verified">🎓 ВУЗ</span>' : "";
    const premiumBadge = profile.is_premium ? '<span class="card-badge premium">💎 VIP</span>' : "";
    const yearStr = profile.year ? `${profile.year} курс` : "";
    const univStr = profile.university ? profile.university : "";

    const tagsHtml = (profile.tags || [])
      .slice(0, 3)
      .map((t) => `<span class="card-tag">${t.emoji || "🏷"} ${t.name}</span>`)
      .join("");

    // Stories indicator bars
    const barsHtml = photos.length > 1
      ? `<div class="card-stories-bars">
           ${photos.map((_, i) => `<div class="story-bar ${i === 0 ? "active" : ""}"></div>`).join("")}
         </div>`
      : "";

    // Career specifics
    let careerSub = "";
    if (profile.career_skills && profile.career_skills.length > 0) {
      careerSub = `<div class="card-subtext" style="color:#A8A5FF;">💼 Карьерная анкета</div>`;
    }

    card.innerHTML = `
      ${barsHtml}
      <img src="${photos[0]}" class="card-photo-bg" alt="${escapeHtml(profile.name)}" />
      <div class="card-gradient-overlay"></div>

      <!-- Tap zones for photo carousel -->
      <div class="card-tap-left"></div>
      <div class="card-tap-right"></div>

      <div class="stamp like-stamp">LIKE</div>
      <div class="stamp nope-stamp">SKIP</div>
      <div class="stamp super-stamp">SUPER</div>

      <div class="card-top-bar" style="margin-top: ${photos.length > 1 ? "14px" : "0"};">
        <div class="card-tags-top">
          ${verifiedBadge}
          ${premiumBadge}
        </div>
        <div class="card-rating-badge">
          ⭐ <span>${profile.rating_score || 0}</span>
        </div>
      </div>

      <div class="card-info-bottom">
        <div class="card-title-row">
          <span class="card-name">${escapeHtml(profile.name)}</span>
          ${profile.age ? `<span class="card-age">${profile.age}</span>` : ""}
          <button class="action-btn info" data-action="info" title="Подробнее" style="margin-left:auto;">ℹ️</button>
        </div>
        ${careerSub}
        <div class="card-subtext">
          ${univStr ? `🏛 ${univStr}` : ""} ${yearStr ? `• ${yearStr}` : ""}
        </div>
        ${tagsHtml ? `<div class="card-tags">${tagsHtml}</div>` : ""}
        ${profile.goal ? `<p class="card-bio">${escapeHtml(profile.goal)}</p>` : ""}

        <div class="card-actions-row">
          <button class="action-btn dislike" data-action="skip">✕</button>
          <button class="action-btn superlike" data-action="superlike">⭐</button>
          <button class="action-btn like" data-action="like">❤️</button>
        </div>
      </div>
    `;

    // Обработка кликов по левой/правой зоне для переключения фото
    const tapLeft = card.querySelector(".card-tap-left");
    const tapRight = card.querySelector(".card-tap-right");
    const photoImg = card.querySelector(".card-photo-bg");
    const storyBars = card.querySelectorAll(".story-bar");

    if (tapLeft && tapRight && photos.length > 1) {
      tapLeft.addEventListener("click", (e) => {
        e.stopPropagation();
        let idx = parseInt(card.dataset.photoIndex || "0", 10);
        if (idx > 0) {
          idx--;
          card.dataset.photoIndex = idx.toString();
          photoImg.src = photos[idx];
          storyBars.forEach((bar, i) => bar.classList.toggle("active", i <= idx));
          triggerHaptic("light");
        }
      });

      tapRight.addEventListener("click", (e) => {
        e.stopPropagation();
        let idx = parseInt(card.dataset.photoIndex || "0", 10);
        if (idx < photos.length - 1) {
          idx++;
          card.dataset.photoIndex = idx.toString();
          photoImg.src = photos[idx];
          storyBars.forEach((bar, i) => bar.classList.toggle("active", i <= idx));
          triggerHaptic("light");
        }
      });
    }

    // Кнопки действий
    card.querySelectorAll(".action-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const action = btn.dataset.action;
        if (action === "info") {
          openDetailsSheet(profile);
        } else if (action === "superlike") {
          openSuperlikeModal(profile);
        } else {
          handleSwipeAction(profile, action);
        }
      });
    });

    return card;
  }

  // 5. Сенсорный свайп-движок (Touch & Mouse Drag)
  function initCardDrag(card, profile) {
    let startX = 0;
    let startY = 0;
    let currentX = 0;
    let currentY = 0;
    let isDragging = false;

    const likeStamp = card.querySelector(".like-stamp");
    const nopeStamp = card.querySelector(".nope-stamp");
    const superStamp = card.querySelector(".super-stamp");

    function onStart(e) {
      if (state.isSwiping) return;
      isDragging = true;
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      const clientY = e.touches ? e.touches[0].clientY : e.clientY;
      startX = clientX;
      startY = clientY;
      card.style.transition = "none";
    }

    function onMove(e) {
      if (!isDragging) return;
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      const clientY = e.touches ? e.touches[0].clientY : e.clientY;
      currentX = clientX - startX;
      currentY = clientY - startY;

      const rotate = currentX * 0.06;
      card.style.transform = `translate(${currentX}px, ${currentY}px) rotate(${rotate}deg)`;

      // Отрисовка штампов
      if (currentX > 35) {
        likeStamp.style.opacity = Math.min(1, (currentX - 35) / 80);
        nopeStamp.style.opacity = 0;
        superStamp.style.opacity = 0;
      } else if (currentX < -35) {
        nopeStamp.style.opacity = Math.min(1, (-currentX - 35) / 80);
        likeStamp.style.opacity = 0;
        superStamp.style.opacity = 0;
      } else if (currentY < -40 && Math.abs(currentX) < 40) {
        superStamp.style.opacity = Math.min(1, (-currentY - 40) / 70);
        likeStamp.style.opacity = 0;
        nopeStamp.style.opacity = 0;
      } else {
        likeStamp.style.opacity = 0;
        nopeStamp.style.opacity = 0;
        superStamp.style.opacity = 0;
      }
    }

    function onEnd() {
      if (!isDragging) return;
      isDragging = false;

      // Пороги срабатывания свайпа
      if (currentX > 90) {
        finishSwipe(card, profile, "like", 500, 0);
      } else if (currentX < -90) {
        finishSwipe(card, profile, "skip", -500, 0);
      } else if (currentY < -110 && Math.abs(currentX) < 60) {
        openSuperlikeModal(profile);
        card.style.transition = "transform 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.275)";
        card.style.transform = "translate(0, 0) rotate(0deg)";
        superStamp.style.opacity = 0;
      } else {
        // Возврат в центр
        card.style.transition = "transform 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.275)";
        card.style.transform = "translate(0, 0) rotate(0deg)";
        likeStamp.style.opacity = 0;
        nopeStamp.style.opacity = 0;
        superStamp.style.opacity = 0;
      }
    }

    card.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("touchend", onEnd);

    card.addEventListener("mousedown", onStart);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onEnd);
  }

  function finishSwipe(card, profile, action, exitX, exitY, comment = null) {
    state.isSwiping = true;
    card.style.transition = "transform 0.35s ease-out, opacity 0.35s";
    card.style.transform = `translate(${exitX}px, ${exitY}px) rotate(${exitX * 0.08}deg)`;
    card.style.opacity = 0;

    triggerHaptic(action === "superlike" ? "heavy" : "medium");

    setTimeout(() => {
      card.remove();
      state.currentCardIndex++;
      state.isSwiping = false;

      renderCardStack();
      sendSwipe(profile.user_id, action, comment);
    }, 300);
  }

  function handleSwipeAction(profile, action, comment = null) {
    if (state.isSwiping) return;
    const topCard = deckContainer.querySelector(".swipe-card:last-child");
    if (!topCard) return;

    if (action === "like") {
      finishSwipe(topCard, profile, "like", 500, 0);
    } else if (action === "superlike") {
      finishSwipe(topCard, profile, "superlike", 0, -600, comment);
    } else {
      finishSwipe(topCard, profile, "skip", -500, 0);
    }
  }

  async function sendSwipe(targetId, action, comment = null) {
    try {
      const res = await apiFetch("/api/webapp/swipe", {
        method: "POST",
        body: JSON.stringify({ target_id: targetId, action: action, comment: comment }),
      });
      if (res && res.is_match && res.match) {
        showMatchPopup(res.match);
      }
      if (res && res.superlike_balance !== undefined && state.currentUser) {
        state.currentUser.superlike_balance = res.superlike_balance;
      }
    } catch (e) {
      console.error("Swipe API error:", e);
    }
  }

  // 6. Детальный Bottom Sheet анкеты (ℹ️)
  function openDetailsSheet(profile) {
    triggerHaptic("medium");
    const body = document.getElementById("detailsSheetBody");
    if (!body) return;

    const photos = profile.photos && profile.photos.length > 0
      ? profile.photos
      : ["https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=600&q=80"];

    const galleryHtml = photos
      .map((p) => `<img src="${p}" class="sheet-photo" alt="Photo" />`)
      .join("");

    const tagsHtml = (profile.tags || [])
      .map((t) => `<span class="card-tag">${t.emoji || "🏷"} ${t.name}</span>`)
      .join("");

    // Career information
    let careerSection = "";
    if (profile.career_goal || profile.career_custom_skills || profile.career_portfolio_url || profile.career_work_format) {
      careerSection = `
        <div class="sheet-section">
          <div class="sheet-section-title">💼 Профессиональная информация</div>
          ${profile.career_work_format ? `<p class="sheet-section-text"><b>Формат:</b> ${escapeHtml(profile.career_work_format)}</p>` : ""}
          ${profile.career_custom_skills ? `<p class="sheet-section-text"><b>Навыки / Стек:</b> ${escapeHtml(profile.career_custom_skills)}</p>` : ""}
          ${profile.career_goal ? `<p class="sheet-section-text"><b>Цель:</b> ${escapeHtml(profile.career_goal)}</p>` : ""}
          ${profile.career_portfolio_url ? `<a href="${escapeHtml(profile.career_portfolio_url)}" target="_blank" class="sheet-link-btn">🔗 Открыть резюме / портфолио</a>` : ""}
        </div>
      `;
    }

    body.innerHTML = `
      <div class="sheet-gallery">${galleryHtml}</div>

      <div>
        <h2 style="font-size: 24px; font-weight: 800; margin-bottom: 4px;">
          ${escapeHtml(profile.name)}, ${profile.age || ""}
          ${profile.is_verified ? "🎓" : ""} ${profile.is_premium ? "💎" : ""}
        </h2>
        <p style="font-size: 14px; color: var(--text-muted);">
          🏛 ${profile.university || "ВУЗ"} ${profile.major ? `• ${profile.major}` : ""} ${profile.year ? `• ${profile.year} курс` : ""}
        </p>
      </div>

      ${profile.goal ? `
        <div class="sheet-section">
          <div class="sheet-section-title">О себе</div>
          <p class="sheet-section-text">${escapeHtml(profile.goal)}</p>
        </div>
      ` : ""}

      ${tagsHtml ? `
        <div class="sheet-section">
          <div class="sheet-section-title">Интересы</div>
          <div class="card-tags" style="margin-top: 6px;">${tagsHtml}</div>
          ${profile.custom_interests ? `<p class="sheet-section-text" style="margin-top: 6px;">${escapeHtml(profile.custom_interests)}</p>` : ""}
        </div>
      ` : ""}

      ${careerSection}

      <div class="card-actions-row" style="margin-top: 10px;">
        <button class="action-btn dislike" id="sheetDislikeBtn">✕</button>
        <button class="action-btn superlike" id="sheetSuperlikeBtn">⭐</button>
        <button class="action-btn like" id="sheetLikeBtn">❤️</button>
      </div>

      <button class="sheet-report-btn" id="sheetReportBtn">
        🚩 Пожаловаться на анкету
      </button>
    `;

    detailsSheetOverlay.classList.add("active");

    document.getElementById("sheetDislikeBtn")?.addEventListener("click", () => {
      closeDetailsSheet();
      handleSwipeAction(profile, "skip");
    });
    document.getElementById("sheetSuperlikeBtn")?.addEventListener("click", () => {
      closeDetailsSheet();
      openSuperlikeModal(profile);
    });
    document.getElementById("sheetLikeBtn")?.addEventListener("click", () => {
      closeDetailsSheet();
      handleSwipeAction(profile, "like");
    });
    document.getElementById("sheetReportBtn")?.addEventListener("click", () => {
      closeDetailsSheet();
      openReportModal(profile);
    });
  }

  function closeDetailsSheet() {
    detailsSheetOverlay.classList.remove("active");
  }

  detailsSheetOverlay?.addEventListener("click", (e) => {
    if (e.target === detailsSheetOverlay) closeDetailsSheet();
  });

  // 7. Фильтры поиска (Explore Filters)
  async function openFiltersModal() {
    triggerHaptic("medium");
    try {
      const data = await apiFetch("/api/webapp/filters");
      if (data) {
        document.getElementById("filterMinAge").value = data.min_age || 17;
        document.getElementById("filterMaxAge").value = data.max_age || 28;
        document.getElementById("filterMajor").value = data.major === "all" ? "" : (data.major || "");

        const pills = document.querySelectorAll(".course-pill");
        pills.forEach((p) => {
          const pmin = parseInt(p.dataset.min, 10);
          const pmax = parseInt(p.dataset.max, 10);
          p.classList.toggle("active", pmin === data.min_year && pmax === data.max_year);
        });
      }
    } catch (e) {
      console.warn("Failed to load filters:", e);
    }
    filtersModal.classList.add("active");
  }

  function setupModalListeners() {
    // Filters Modal
    document.getElementById("closeFiltersBtn")?.addEventListener("click", () => filtersModal.classList.remove("active"));
    document.querySelectorAll(".course-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        document.querySelectorAll(".course-pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
      });
    });

    document.getElementById("saveFiltersBtn")?.addEventListener("click", async () => {
      const minAge = parseInt(document.getElementById("filterMinAge").value || "16", 10);
      const maxAge = parseInt(document.getElementById("filterMaxAge").value || "35", 10);
      const major = document.getElementById("filterMajor").value.trim() || "all";

      const activePill = document.querySelector(".course-pill.active");
      const minYear = activePill ? parseInt(activePill.dataset.min, 10) : 1;
      const maxYear = activePill ? parseInt(activePill.dataset.max, 10) : 6;

      triggerHaptic("medium");
      await apiFetch("/api/webapp/filters", {
        method: "POST",
        body: JSON.stringify({
          min_age: minAge,
          max_age: maxAge,
          min_year: minYear,
          max_year: maxYear,
          major: major,
        }),
      });

      filtersModal.classList.remove("active");
      state.feed = [];
      state.currentCardIndex = 0;
      loadFeed();
    });

    document.getElementById("resetFiltersBtn")?.addEventListener("click", async () => {
      triggerHaptic("medium");
      await apiFetch("/api/webapp/filters", {
        method: "POST",
        body: JSON.stringify({
          min_age: 16,
          max_age: 35,
          min_year: 1,
          max_year: 6,
          major: "all",
        }),
      });
      filtersModal.classList.remove("active");
      state.feed = [];
      state.currentCardIndex = 0;
      loadFeed();
    });

    // Superlike Modal
    const commentInput = document.getElementById("superlikeComment");
    const charCount = document.getElementById("commentCharCount");
    commentInput?.addEventListener("input", () => {
      if (charCount) charCount.textContent = `${commentInput.value.length}/200`;
    });

    document.getElementById("closeSuperlikeBtn")?.addEventListener("click", () => superlikeModal.classList.remove("active"));
    document.getElementById("sendSuperlikeWithCommentBtn")?.addEventListener("click", () => {
      const candidate = state.selectedCandidateForSuperlike;
      const comment = commentInput.value.trim();
      superlikeModal.classList.remove("active");
      if (candidate) handleSwipeAction(candidate, "superlike", comment);
    });
    document.getElementById("sendSuperlikeQuickBtn")?.addEventListener("click", () => {
      const candidate = state.selectedCandidateForSuperlike;
      superlikeModal.classList.remove("active");
      if (candidate) handleSwipeAction(candidate, "superlike", null);
    });

    // Report Modal
    document.getElementById("closeReportBtn")?.addEventListener("click", () => reportModal.classList.remove("active"));
    document.getElementById("cancelReportBtn")?.addEventListener("click", () => reportModal.classList.remove("active"));
    document.getElementById("submitReportBtn")?.addEventListener("click", async () => {
      const candidate = state.selectedCandidateForReport;
      if (!candidate) return;
      const checkedReason = document.querySelector('input[name="reportReason"]:checked')?.value || "Другое";

      triggerHaptic("heavy");
      await apiFetch("/api/webapp/report", {
        method: "POST",
        body: JSON.stringify({
          reported_id: candidate.user_id,
          reason: checkedReason,
        }),
      });

      reportModal.classList.remove("active");
      const topCard = deckContainer.querySelector(`.swipe-card[data-user-id="${candidate.user_id}"]`);
      if (topCard) {
        topCard.style.transition = "transform 0.3s, opacity 0.3s";
        topCard.style.transform = "translate(0, 500px) scale(0.8)";
        topCard.style.opacity = "0";
        setTimeout(() => {
          topCard.remove();
          state.currentCardIndex++;
          renderCardStack();
        }, 300);
      }
    });

    document.getElementById("matchCloseBtn")?.addEventListener("click", () => {
      matchModal.classList.remove("active");
    });
  }

  function openSuperlikeModal(profile) {
    state.selectedCandidateForSuperlike = profile;
    const balanceLabel = document.getElementById("superlikeBalanceLabel");
    if (balanceLabel && state.currentUser) {
      balanceLabel.textContent = state.currentUser.superlike_balance || "0";
    }
    const input = document.getElementById("superlikeComment");
    if (input) input.value = "";
    superlikeModal.classList.add("active");
    triggerHaptic("medium");
  }

  function openReportModal(profile) {
    state.selectedCandidateForReport = profile;
    reportModal.classList.add("active");
    triggerHaptic("medium");
  }

  // 8. Всплывающее окно взаимного мэтча (Match Celebration)
  function showMatchPopup(partner) {
    triggerHaptic("success");
    const pNameEl = document.getElementById("matchPartnerName");
    const pAvatarEl = document.getElementById("matchPartnerAvatar");
    const chatBtn = document.getElementById("matchChatBtn");

    if (pNameEl) pNameEl.textContent = partner.name || "Студент";
    if (pAvatarEl && partner.photo_url) pAvatarEl.src = partner.photo_url;
    if (chatBtn) {
      chatBtn.href = partner.tg_username
        ? `https://t.me/${partner.tg_username.replace("@", "")}`
        : "https://t.me/";
    }

    matchModal.classList.add("active");
  }

  // 9. Раздел «Мэтчи» с возможностью открыть полную анкету мэтча
  async function loadMatches() {
    const container = document.getElementById("matchesContainer");
    if (!container) return;
    container.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);">Загрузка...</div>';

    try {
      const data = await apiFetch("/api/webapp/matches");
      if (!data || !data.matches || data.matches.length === 0) {
        container.innerHTML = `
          <div style="text-align:center;padding:40px 20px;">
            <div style="font-size:48px;margin-bottom:12px;">🫂</div>
            <h3 style="font-size:18px;font-weight:800;margin-bottom:6px;">Пока нет мэтчей</h3>
            <p style="font-size:13px;color:var(--text-muted);">Продолжайте свайпать в ленте, чтобы найти пару!</p>
          </div>
        `;
        return;
      }

      container.innerHTML = data.matches
        .map((m) => {
          const photoUrl = m.photo_url || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80";
          const chatUrl = m.tg_username ? `https://t.me/${m.tg_username.replace("@", "")}` : "#";
          const verified = m.is_verified ? " 🎓" : "";
          const prem = m.is_premium ? " 💎" : "";

          return `
            <div class="match-item" data-partner-id="${m.user_id}">
              <img src="${photoUrl}" class="match-avatar" alt="${escapeHtml(m.name)}" />
              <div class="match-info">
                <div class="match-name-row">
                  <span class="match-name">${escapeHtml(m.name)}${verified}${prem}</span>
                </div>
                <div class="match-univ">${m.university || "ВУЗ"} ${m.year ? `• ${m.year} курс` : ""}</div>
              </div>
              <a href="${chatUrl}" target="_blank" class="match-chat-btn" onclick="event.stopPropagation();">
                💬 Написать
              </a>
            </div>
          `;
        })
        .join("");

      container.querySelectorAll(".match-item").forEach((item) => {
        item.addEventListener("click", () => {
          const pid = item.dataset.partnerId;
          openMatchFullProfile(pid);
        });
      });
    } catch (e) {
      container.innerHTML = '<div style="text-align:center;padding:30px;color:red;">Ошибка загрузки</div>';
    }
  }

  // Открытие полной анкеты мэтча
  async function openMatchFullProfile(partnerId) {
    triggerHaptic("medium");
    const body = document.getElementById("matchProfileBody");
    if (!body) return;
    body.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted);">Загрузка анкеты...</div>';
    matchProfileModal.classList.add("active");

    try {
      const data = await apiFetch(`/api/webapp/user/${partnerId}`);
      if (!data || !data.user) {
        body.innerHTML = '<div style="text-align:center;padding:30px;color:red;">Не удалось загрузить анкету</div>';
        return;
      }
      const u = data.user;
      const photos = u.photos && u.photos.length > 0 ? u.photos : ["https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=600&q=80"];
      const gallery = photos.map((p) => `<img src="${p}" class="sheet-photo" />`).join("");
      const tags = (u.tags || []).map((t) => `<span class="card-tag">${t.emoji} ${t.name}</span>`).join("");
      const chatUrl = u.tg_username ? `https://t.me/${u.tg_username.replace("@", "")}` : "#";

      body.innerHTML = `
        <div class="sheet-gallery">${gallery}</div>
        <div>
          <h2 style="font-size: 24px; font-weight: 800; margin-bottom: 4px;">
            ${escapeHtml(u.name)}, ${u.age || ""} ${u.is_verified ? "🎓" : ""} ${u.is_premium ? "💎" : ""}
          </h2>
          <p style="font-size: 14px; color: var(--text-muted);">
            🏛 ${u.university || "ВУЗ"} ${u.major ? `• ${u.major}` : ""} ${u.year ? `• ${u.year} курс` : ""}
          </p>
        </div>

        ${u.goal ? `
          <div class="sheet-section">
            <div class="sheet-section-title">О себе</div>
            <p class="sheet-section-text">${escapeHtml(u.goal)}</p>
          </div>
        ` : ""}

        ${tags ? `
          <div class="sheet-section">
            <div class="sheet-section-title">Интересы</div>
            <div class="card-tags" style="margin-top:6px;">${tags}</div>
          </div>
        ` : ""}

        <div style="margin-top: 10px;">
          <a href="${chatUrl}" target="_blank" class="btn-primary" style="text-decoration:none;display:block;text-align:center;">
            💬 Написать в Telegram
          </a>
        </div>
      `;
    } catch (e) {
      body.innerHTML = '<div style="text-align:center;padding:30px;color:red;">Ошибка загрузки анкеты</div>';
    }
  }

  matchProfileModal?.addEventListener("click", (e) => {
    if (e.target === matchProfileModal) matchProfileModal.classList.remove("active");
  });

  // 10. Раздел «Симпатии» (Incoming Likes)
  async function loadIncomingLikes() {
    const container = document.getElementById("likesContainer");
    if (!container) return;

    try {
      const data = await apiFetch("/api/webapp/incoming_likes");
      if (!data) return;

      if (!data.is_premium) {
        container.innerHTML = `
          <div class="paywall-card">
            <div class="paywall-icon">💌</div>
            <div class="paywall-title">${data.count || 0} человек лайкнули тебя!</div>
            <p class="paywall-desc">Оформи Премиум-подписку, чтобы сразу видеть, кто проявил интерес, и отвечать взаимностью без ожидания.</p>
            <button class="btn-primary" id="openPremiumBtn">💎 Оформить Премиум</button>
          </div>
        `;
        document.getElementById("openPremiumBtn")?.addEventListener("click", () => {
          triggerHaptic("medium");
          tg?.openTelegramLink("https://t.me/" + (window.BOT_USERNAME || "edudating_bot") + "?start=premium");
        });
      } else {
        if (data.likes.length === 0) {
          container.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted);">Новых лайков пока нет</div>';
          return;
        }
        container.innerHTML = `
          <div class="likes-grid">
            ${data.likes
              .map((lk) => {
                const img = lk.photo_url || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=300&q=80";
                return `
                  <div class="like-card" onclick="window.acceptLike(${lk.user_id})">
                    <img src="${img}" class="like-card-img" />
                    <div class="like-card-overlay">
                      <div class="like-card-name">${escapeHtml(lk.name)}</div>
                      <div class="like-card-sub">${lk.university || ""}</div>
                    </div>
                  </div>
                `;
              })
              .join("")}
          </div>
        `;
      }
    } catch (e) {
      container.innerHTML = '<div style="text-align:center;padding:30px;color:red;">Ошибка загрузки</div>';
    }
  }

  window.acceptLike = async function (targetId) {
    triggerHaptic("medium");
    await sendSwipe(targetId, "like");
    loadIncomingLikes();
  };

  // 11. Раздел «Профиль»
  async function loadProfile() {
    const container = document.getElementById("profileContainer");
    if (!container) return;

    try {
      const data = await apiFetch("/api/webapp/profile");
      if (!data || !data.user) return;
      const u = data.user;

      const avatar = u.photos && u.photos.length > 0
        ? u.photos[0]
        : "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=300&q=80";

      const tags = (u.tags || []).map((t) => `<span class="card-tag">${t.emoji} ${t.name}</span>`).join("");

      container.innerHTML = `
        <div class="profile-card">
          <div class="profile-avatar-wrap ${u.is_premium ? "premium" : ""}">
            <img src="${avatar}" class="profile-avatar" />
          </div>
          <div class="profile-name">${escapeHtml(u.name || "Студент")} ${u.is_verified ? "🎓" : ""} ${u.is_premium ? "💎" : ""}</div>
          <div class="profile-univ">${u.university || ""} ${u.major ? `• ${u.major}` : ""}</div>

          <div class="profile-stats-row">
            <div class="profile-stat">
              <span class="stat-value">⭐ ${u.rating_score || 0}</span>
              <span class="stat-label">Рейтинг</span>
            </div>
            <div class="profile-stat">
              <span class="stat-value">${u.superlike_balance || 0}</span>
              <span class="stat-label">Суперлайки</span>
            </div>
            <div class="profile-stat">
              <span class="stat-value">${u.mode === "career" ? "💼" : "💘"}</span>
              <span class="stat-label">Режим</span>
            </div>
          </div>
        </div>

        <div class="profile-menu-list">
          <div class="profile-menu-item" id="btnToggleProfileMode">
            <span>Режим поиска: <b>${u.mode === "career" ? "💼 Карьера" : "💘 Знакомства"}</b></span>
            <span>⇄</span>
          </div>
          <div class="profile-menu-item" id="btnOpenSearchFilters">
            <span>🎯 Настройки фильтров поиска</span>
            <span>→</span>
          </div>
          <div class="profile-menu-item" id="btnResetSwipesProfile">
            <span>🔄 Сбросить историю свайпов</span>
            <span>→</span>
          </div>
          <div class="profile-menu-item" id="btnOpenBotSettings">
            <span>⚙️ Настройки анкеты в боте</span>
            <span>→</span>
          </div>
        </div>
      `;

      document.getElementById("btnToggleProfileMode")?.addEventListener("click", toggleMode);
      document.getElementById("btnOpenSearchFilters")?.addEventListener("click", openFiltersModal);
      document.getElementById("btnResetSwipesProfile")?.addEventListener("click", resetSwipesAndReload);
      document.getElementById("btnOpenBotSettings")?.addEventListener("click", () => {
        tg?.openTelegramLink("https://t.me/" + (window.BOT_USERNAME || "edudating_bot") + "?start=settings");
      });
    } catch (e) {
      console.error("Profile load error:", e);
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupNavigation();
    authenticateUser();
  });
})();
