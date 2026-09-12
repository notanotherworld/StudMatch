/**
 * StudMatch Telegram Mini App (TWA / WebApp) Core Client
 * Touch-driven swipe engine, multi-photo carousel, candidate details sheet,
 * search filters, superlike with compliment, reports, match profile viewer,
 * Figma components integration, and hidden Superadmin Hub (God Mode, analytics, user management, reports moderation).
 */

(function () {
  const tg = window.Telegram?.WebApp;

  function syncViewportHeight() {
    try {
      const height = tg?.viewportHeight ? `${tg.viewportHeight}px` : `${window.innerHeight}px`;
      document.documentElement.style.setProperty("--tg-viewport-height", height);
      if (tg?.viewportStableHeight) {
        document.documentElement.style.setProperty("--tg-viewport-stable-height", `${tg.viewportStableHeight}px`);
      }
    } catch (e) {
      console.warn("Viewport sync error:", e);
    }
  }

  if (tg) {
    tg.ready();
    tg.expand();
    syncViewportHeight();
    tg.onEvent("viewportChanged", syncViewportHeight);
  } else {
    syncViewportHeight();
  }
  window.addEventListener("resize", syncViewportHeight);
  window.addEventListener("orientationchange", function () {
    setTimeout(syncViewportHeight, 150);
  });

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
  const adminHubModal = document.getElementById("adminHubModal");
  const navButtons = document.querySelectorAll(".nav-tab-btn");

  // Maintenance DOM Elements
  const maintenanceBanner = document.getElementById("maintenanceBanner");
  const maintenanceBannerText = document.getElementById("maintenanceBannerText");
  const maintenanceModal = document.getElementById("maintenanceModal");
  const openMaintenanceModalBtn = document.getElementById("openMaintenanceModalBtn");
  const closeMaintenanceModalBtn = document.getElementById("closeMaintenanceModalBtn");
  const maintenanceModalCustomMsg = document.getElementById("maintenanceModalCustomMsg");

  function openMaintenanceModal() {
    if (maintenanceModal) {
      maintenanceModal.style.display = "flex";
      triggerHaptic("medium");
    }
  }

  function closeMaintenanceModal() {
    if (maintenanceModal) {
      maintenanceModal.style.display = "none";
      sessionStorage.setItem("maintenance_modal_seen", "true");
      triggerHaptic("light");
    }
  }

  function updateMaintenanceUI(maintenanceData) {
    if (!maintenanceBanner) return;
    const isActive = Boolean(maintenanceData?.is_active ?? maintenanceData?.isActive);
    const msg = maintenanceData?.message || "Некоторые функции могут быть временно недоступны на время обновления. Спасибо за понимание! ❤️";

    if (isActive) {
      maintenanceBanner.style.display = "flex";
      if (maintenanceBannerText) maintenanceBannerText.textContent = msg;
      if (maintenanceModalCustomMsg) maintenanceModalCustomMsg.textContent = msg;
      if (!sessionStorage.getItem("maintenance_modal_seen")) {
        openMaintenanceModal();
      }
    } else {
      maintenanceBanner.style.display = "none";
      if (maintenanceModal) maintenanceModal.style.display = "none";
    }
  }

  function setupMaintenanceListeners() {
    openMaintenanceModalBtn?.addEventListener("click", openMaintenanceModal);
    closeMaintenanceModalBtn?.addEventListener("click", closeMaintenanceModal);
    maintenanceModal?.addEventListener("click", (e) => {
      if (e.target === maintenanceModal) {
        closeMaintenanceModal();
      }
    });
  }

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

  let isAuthenticating = false;
  let reconnectTimer = null;
  let retryCount = 0;

  // 1. Авторизация
  async function authenticateUser() {
    if (isAuthenticating) return;
    isAuthenticating = true;

    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    try {
      // Попытка восстановить активную сессию из сохранённого токена
      const savedToken = state.token || localStorage.getItem("studmatch_token");
      if (savedToken) {
        try {
          const profRes = await fetch("/api/webapp/profile", {
            headers: {
              "Authorization": `Bearer ${savedToken}`,
              "Content-Type": "application/json"
            }
          });
          if (profRes.ok) {
            const profData = await profRes.json();
            if (profData && profData.status === "ok") {
              if (profData.maintenance) {
                updateMaintenanceUI(profData.maintenance);
              }
              if (profData.user) {
                console.log("[StudMatch] Re-used valid saved session token");
                state.token = savedToken;
                state.currentUser = profData.user;
                localStorage.setItem("studmatch_token", savedToken);
                updateHeaderUser();
                retryCount = 0;
                if (state.currentUser?.mode === "career") {
                  await setMode("career");
                } else if (state.feed.length === 0) {
                  await loadFeed();
                }
                const composerAvatar = document.getElementById("composerUserAvatar");
                if (composerAvatar && state.currentUser?.avatar_url) {
                  composerAvatar.src = state.currentUser.avatar_url;
                }
                await loadStories();
                openOnboarding(false);
                return;
              }
            }
          }
        } catch (e) {
          console.warn("[StudMatch] Saved token verification failed:", e);
        }
      }

      // Получаем актуальные данные сессии Telegram
      let initData = tg?.initData || "";
      if (!initData && window.location.hash) {
        try {
          const hash = window.location.hash.slice(1);
          const params = new URLSearchParams(hash);
          initData = params.get("tgWebAppData") || "";
        } catch (e) {}
      }

      if (!initData) {
        if (state.feed.length === 0) {
          deckContainer.innerHTML = `
            <div class="deck-empty" style="display:flex;">
              <div class="deck-empty-icon">📱</div>
              <h2 class="deck-empty-title">Вход через Telegram</h2>
              <p class="deck-empty-desc">Откройте StudMatch через нашего Telegram бота, чтобы войти в свою студенческую анкету.</p>
              <a href="https://t.me/${window.BOT_USERNAME || "edudating_bot"}" class="btn-primary" style="text-decoration:none;display:block;max-width:240px;margin:0 auto;text-align:center;">
                🚀 Открыть бота
              </a>
            </div>
          `;
        }
        return;
      }

      console.log("[StudMatch] Authenticating via initData, length:", initData.length);

      const res = await fetch("/api/webapp/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: initData }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        if (res.status === 401 || res.status === 403) {
          console.warn("[StudMatch] Auth forbidden/unauthorized:", errData);
          if (state.feed.length === 0) {
            deckContainer.innerHTML = `
              <div class="deck-empty" style="display:flex;">
                <div class="deck-empty-icon">🔒</div>
                <h2 class="deck-empty-title">Сессия Telegram устарела</h2>
                <p class="deck-empty-desc">${errData.detail || "Не удалось подтвердить сессию Telegram."}<br><small style="color:var(--text-muted);font-size:12px;margin-top:4px;display:block;">Закройте приложение и откройте его заново кнопкой в боте.</small></p>
                <div style="display:flex;flex-direction:column;gap:8px;width:100%;max-width:240px;margin:12px auto 0;">
                  <button class="btn-primary" onclick="window.Telegram?.WebApp?.close();">
                    🚪 Закрыть и открыть из бота
                  </button>
                  <button class="btn-secondary" id="btnRetryAuthNow">
                    🔄 Попробовать снова
                  </button>
                </div>
              </div>
            `;
            document.getElementById("btnRetryAuthNow")?.addEventListener("click", () => authenticateUser());
          }
          return;
        }
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      if (data.status === "ok") {
        if (data.maintenance) {
          updateMaintenanceUI(data.maintenance);
        }
        retryCount = 0;
        state.token = data.token;
        state.currentUser = data.user;
        localStorage.setItem("studmatch_token", data.token);
        updateHeaderUser();
        if (state.currentUser?.mode === "career") {
          await setMode("career");
        } else if (state.feed.length === 0) {
          await loadFeed();
        }
        const composerAvatar = document.getElementById("composerUserAvatar");
        if (composerAvatar && state.currentUser?.avatar_url) {
          composerAvatar.src = state.currentUser.avatar_url;
        }
        await loadStories();
        openOnboarding(false);
        checkStartParamDeepLink();
      } else {
        if (state.feed.length === 0) {
          deckContainer.innerHTML = `
            <div class="deck-empty" style="display:flex;">
              <div class="deck-empty-icon">🔒</div>
              <h2 class="deck-empty-title">Авторизация в Telegram</h2>
              <p class="deck-empty-desc">${data.detail || "Не удалось проверить сессию Telegram."}</p>
              <button class="btn-primary" id="btnRetryAuthNow" style="max-width: 220px; margin: 0 auto;">
                🔄 Попробовать снова
              </button>
            </div>
          `;
          document.getElementById("btnRetryAuthNow")?.addEventListener("click", () => authenticateUser());
        }
      }
    } catch (err) {
      console.warn("[StudMatch] Auth attempt failed:", err);

      // Если анкеты уже загружены и отображаются — НЕ стираем колоду!
      if (state.token && state.feed.length > 0) {
        return;
      }

      retryCount++;
      deckContainer.innerHTML = `
        <div class="deck-empty" style="display:flex;">
          <div class="deck-empty-icon">🔄</div>
          <h2 class="deck-empty-title">Подключение к серверу</h2>
          <p class="deck-empty-desc">Сервер перезагружается или обновляется.<br>Автоматическое подключение (попытка ${retryCount})...</p>
          <div style="display:flex;flex-direction:column;gap:8px;width:100%;max-width:240px;margin:0 auto;">
            <button class="btn-primary" id="btnConnectManual">
              ⚡ Подключиться сейчас
            </button>
            <button class="btn-secondary" onclick="window.Telegram?.WebApp?.close()">
              Закрыть
            </button>
          </div>
        </div>
      `;

      document.getElementById("btnConnectManual")?.addEventListener("click", () => {
        authenticateUser();
      });

      if (retryCount <= 5) {
        reconnectTimer = setTimeout(() => {
          authenticateUser();
        }, 2500);
      }
    } finally {
      isAuthenticating = false;
    }
  }

  function updateHeaderUser() {
    const isCareer = state.currentUser?.mode === "career";
    document.getElementById("pillDating")?.classList.toggle("active", !isCareer);
    document.getElementById("pillCareer")?.classList.toggle("active", isCareer);
  }

  // 2. Навигация по табам
  function setupNavigation() {
    navButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;
        switchTab(tab);
      });
    });

    // Figma Mode Switcher Pills
    document.getElementById("pillDating")?.addEventListener("click", () => setMode("dating"));
    document.getElementById("pillCareer")?.addEventListener("click", () => setMode("career"));

    // Кнопка открытия фильтров в шапке
    const openFiltersBtn = document.getElementById("openFiltersBtn");
    if (openFiltersBtn) {
      openFiltersBtn.addEventListener("click", openFiltersModal);
    }

    // Кнопки в Empty State колоды
    document.getElementById("resetSwipesDeckBtn")?.addEventListener("click", resetSwipesAndReload);
    document.getElementById("changeFiltersDeckBtn")?.addEventListener("click", openFiltersModal);

    // Кнопка закрытия плавающей панели навигации
    document.getElementById("closeBottomNavBtn")?.addEventListener("click", () => {
      triggerHaptic("light");
      const navWrap = document.getElementById("bottomNavWrap");
      if (navWrap) navWrap.classList.add("collapsed");
      if (state.activeTab !== "explore") {
        switchTab("explore");
      }
    });

    setupModalListeners();
    setupAdminListeners();
  }


  // ─── Верхняя лента Stories (Реальные Премиум-пользователи) ───
  async function loadStories() {
    const row = document.getElementById("storiesRow");
    if (!row) return;

    try {
      const data = await apiFetch("/api/webapp/stories");
      if (!data) return;

      const my = data.my_story || {
        name: "Вы",
        avatar_url: "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80",
        is_premium: false,
      };

      const myBadge = my.is_premium
        ? `<div class="story-premium-badge" title="Премиум активен">💎</div>`
        : `<div class="story-add-badge" title="Попасть в топ">+</div>`;

      let html = `
        <div class="story-item" id="myStoryItem">
          <div class="story-avatar-wrap my-story ${my.is_premium ? "premium-ring" : ""}">
            <img src="${my.avatar_url}" class="story-avatar" alt="Вы" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80';" />
            ${myBadge}
          </div>
          <span class="story-name">Вы</span>
        </div>
      `;

      if (data.stories && data.stories.length > 0) {
        html += data.stories
          .map((s) => {
            const premRing = s.is_premium ? "premium-ring" : "";
            const badge = s.is_premium
              ? `<div class="story-premium-badge" title="Премиум">💎</div>`
              : (s.is_verified ? `<div class="story-premium-badge" style="background:#4834d4;" title="Студент">🎓</div>` : "");

            return `
              <div class="story-item" data-user-id="${s.user_id}">
                <div class="story-avatar-wrap ${premRing}">
                  <img src="${s.avatar_url}" class="story-avatar" alt="${escapeHtml(s.name)}" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80';" />
                  ${badge}
                </div>
                <span class="story-name">${escapeHtml(s.name)}</span>
              </div>
            `;
          })
          .join("");
      }

      row.innerHTML = html;

      // Клик по своей истории (раскрывает меню навигации и открывает профиль)
      document.getElementById("myStoryItem")?.addEventListener("click", () => {
        triggerHaptic("medium");
        const navWrap = document.getElementById("bottomNavWrap");
        if (navWrap) navWrap.classList.remove("collapsed");
        switchTab("profile");
      });

      // Клик по анкетам других пользователей
      row.querySelectorAll(".story-item[data-user-id]").forEach((item) => {
        item.addEventListener("click", () => {
          const uid = item.dataset.userId;
          if (uid) {
            triggerHaptic("light");
            openMatchFullProfile(uid);
          }
        });
      });
    } catch (e) {
      console.warn("[StudMatch] Failed to load stories:", e);
    }
  }

  function showAppToast(message, duration = 3000) {
    let toast = document.getElementById("appGlobalToast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "appGlobalToast";
      toast.className = "app-toast";
      document.body.appendChild(toast);
    }
    toast.innerHTML = message;
    toast.classList.add("visible");
    triggerHaptic("success");

    if (window._appToastTimeout) {
      clearTimeout(window._appToastTimeout);
    }
    window._appToastTimeout = setTimeout(() => {
      toast.classList.remove("visible");
    }, duration);
  }

  async function resetSwipesAndReload() {
    triggerHaptic("medium");
    if (deckContainer) {
      deckContainer.innerHTML = '<div style="text-align:center;padding:50px;color:var(--text-muted);">Сброс истории свайпов...</div>';
    }
    if (deckEmpty) {
      deckEmpty.style.display = "none";
    }
    try {
      await apiFetch("/api/webapp/reset_swipes", { method: "POST" });
      state.feed = [];
      state.currentCardIndex = 0;
      await loadFeed();
      showAppToast("🔄 История свайпов сброшена! Анкеты снова в ленте");
    } catch (e) {
      console.error("Reset swipes error:", e);
      showAppToast("🔄 История свайпов сброшена!");
    }
  }

  function switchTab(tabName) {
    const navWrap = document.getElementById("bottomNavWrap");
    if (tabName === "explore") {
      if (navWrap) navWrap.classList.add("collapsed");
    } else {
      if (navWrap) navWrap.classList.remove("collapsed");
    }

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

  let currentCareerView = "swipe";

  function setCareerSubnavView(view) {
    currentCareerView = view;
    triggerHaptic("light");
    document.getElementById("btnCareerSubnavSwipe")?.classList.toggle("active", view === "swipe");
    document.getElementById("btnCareerSubnavFeed")?.classList.toggle("active", view === "feed");

    const deckWrapper = document.querySelector(".deck-container");
    const careerView = document.getElementById("careerFeedView");
    const exploreScreen = document.getElementById("screen-explore");

    if (view === "swipe") {
      document.body.classList.remove("feed-view-active");
      if (deckWrapper) deckWrapper.style.display = "flex";
      if (careerView) careerView.style.display = "none";
      if (exploreScreen) {
        exploreScreen.style.overflowY = "hidden";
      }
      state.feed = [];
      state.currentCardIndex = 0;
      loadFeed();
    } else {
      document.body.classList.add("feed-view-active");
      if (deckWrapper) deckWrapper.style.display = "none";
      if (careerView) careerView.style.display = "flex";
      if (exploreScreen) {
        exploreScreen.style.overflowY = "auto";
        exploreScreen.style.webkitOverflowScrolling = "touch";
      }
      loadCareerFeed();
    }
  }

  async function setMode(targetMode) {
    // 1. Мгновенное визуальное переключение пилюль (Optimistic UI)
    document.getElementById("pillDating")?.classList.toggle("active", targetMode === "dating");
    document.getElementById("pillCareer")?.classList.toggle("active", targetMode === "career");
    triggerHaptic("medium");

    if (state.currentUser) {
      state.currentUser.mode = targetMode;
    }

    // Мгновенное обновление текста и иконки режима в профиле
    const modeLabel = document.getElementById("profileModeLabel");
    if (modeLabel) {
      modeLabel.textContent = targetMode === "career" ? "💼 Карьера" : "💘 Знакомства";
    }
    const modeStat = document.getElementById("profileModeStat");
    if (modeStat) {
      modeStat.textContent = targetMode === "career" ? "💼" : "💘";
    }

    const brandTitle = document.querySelector(".header-brand .brand-title");
    const careerSubnav = document.getElementById("careerSubnavToggle");
    const exploreScreen = document.getElementById("screen-explore");
    const deckWrapper = document.querySelector(".deck-container");
    const careerView = document.getElementById("careerFeedView");

    if (targetMode === "career") {
      document.body.classList.add("career-theme");
      if (brandTitle) brandTitle.textContent = "StudMatch";
      if (careerSubnav) careerSubnav.style.display = "flex";
      setCareerSubnavView(currentCareerView || "swipe");
    } else {
      document.body.classList.remove("career-theme");
      document.body.classList.remove("feed-view-active");
      if (brandTitle) brandTitle.textContent = "StudMatch";
      if (careerSubnav) careerSubnav.style.display = "none";
      if (careerView) careerView.style.display = "none";
      if (deckWrapper) deckWrapper.style.display = "flex";
      if (exploreScreen) exploreScreen.style.overflowY = "hidden";
      state.feed = [];
      state.currentCardIndex = 0;
      await loadFeed();
    }

    try {
      const res = await apiFetch("/api/webapp/profile/mode", {
        method: "POST",
        body: JSON.stringify({ mode: targetMode }),
      });
      if (res && res.status === "ok") {
        if (state.currentUser) state.currentUser.mode = res.mode;
      }
    } catch (e) {
      console.warn("Set mode API warning:", e);
    }
  }

  async function toggleMode() {
    if (!state.currentUser) return;
    const nextMode = state.currentUser.mode === "career" ? "dating" : "career";
    await setMode(nextMode);
  }

  let isFetchingMore = false;

  // 3. Загрузка ленты свайпов (Feed)
  async function loadFeed() {
    try {
      console.log("[StudMatch] Loading feed profiles...");
      const data = await apiFetch("/api/webapp/feed");
      console.log("[StudMatch] Feed received:", data);
      if (data && data.profiles) {
        state.feed = data.profiles;
        state.currentCardIndex = 0;
        if (state.feed.length === 0) {
          deckEmpty.style.display = "flex";
        } else {
          renderCardStack();
        }
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

  async function fetchMoreCards() {
    if (isFetchingMore) return;
    isFetchingMore = true;
    try {
      console.log("[StudMatch] Prefetching more cards for infinite swipe stream...");
      const data = await apiFetch("/api/webapp/feed");
      if (data && Array.isArray(data.profiles) && data.profiles.length > 0) {
        // Отрезаем уже свайпнутые карточки для экономии памяти
        const remaining = state.feed.slice(state.currentCardIndex);
        const remainingIds = new Set(remaining.map((p) => p.user_id));

        // Добавляем только новые карточки, которых еще нет в остатке колоды
        const freshProfiles = data.profiles.filter((p) => !remainingIds.has(p.user_id));

        if (freshProfiles.length > 0) {
          state.feed = remaining.concat(freshProfiles);
          state.currentCardIndex = 0;
          renderCardStack();
        } else if (remaining.length === 0) {
          // Если колода была пуста (например, при малом пуле анкет 1-2 человека)
          state.feed = data.profiles;
          state.currentCardIndex = 0;
          renderCardStack();
        }
      } else if (state.feed.slice(state.currentCardIndex).length === 0) {
        deckEmpty.style.display = "flex";
      }
    } catch (err) {
      console.warn("[StudMatch] Error prefetching feed cards:", err);
      if (state.feed.slice(state.currentCardIndex).length === 0) {
        deckEmpty.style.display = "flex";
      }
    } finally {
      isFetchingMore = false;
    }
  }

  function renderCardStack() {
    deckContainer.innerHTML = "";

    const remaining = state.feed.slice(state.currentCardIndex);
    if (remaining.length === 0) {
      if (!isFetchingMore) {
        fetchMoreCards();
      }
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

  // 4. Создание DOM элемента карточки с каруселью фото и кнопками Figma
  function createCardElement(profile, isTop) {
    const card = document.createElement("div");
    card.className = "swipe-card";
    card.dataset.userId = profile.user_id;

    const photos = profile.photos && profile.photos.length > 0
      ? profile.photos
      : ["https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"];

    card.dataset.photoIndex = "0";

    const isCareer = state.currentUser?.mode === "career";
    if (isCareer) {
      card.classList.add("career-card-swipe");
    }

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
    let careerSkillsHtml = "";
    let careerPortfolioBtn = "";
    if (isCareer) {
      careerSub = `
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin:4px 0;">
          ${profile.career_work_format ? `<span class="career-badge-format">🟢 ${escapeHtml(profile.career_work_format)}</span>` : ""}
          ${profile.major ? `<span style="font-size:12px;font-weight:700;color:#93C5FD;">💼 ${escapeHtml(profile.major)}</span>` : ""}
        </div>
      `;
      if (profile.career_custom_skills) {
        const skillsList = profile.career_custom_skills.split(",").map((s) => s.trim()).filter(Boolean);
        if (skillsList.length > 0) {
          careerSkillsHtml = `
            <div class="career-skills-chips" style="margin:4px 0;">
              ${skillsList.slice(0, 4).map((s) => `<span class="career-skill-chip">#${escapeHtml(s)}</span>`).join("")}
            </div>
          `;
        }
      }
      if (profile.career_portfolio_url) {
        careerPortfolioBtn = `
          <a href="${escapeHtml(profile.career_portfolio_url)}" target="_blank" rel="noopener noreferrer" class="career-portfolio-link" style="margin:4px 0;display:inline-flex;" onclick="event.stopPropagation();">
            🔗 Резюме / Портфолио →
          </a>
        `;
      }
    } else if (profile.career_skills && profile.career_skills.length > 0) {
      careerSub = `<div class="card-subtext" style="color:#A8A5FF;">💼 Карьерная анкета</div>`;
    }

    card.innerHTML = `
      ${barsHtml}
      <img src="${photos[0]}" class="card-photo-bg" alt="${escapeHtml(profile.name)}" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />
      <div class="card-gradient-overlay"></div>

      <!-- Tap zones for photo carousel -->
      <div class="card-tap-left"></div>
      <div class="card-tap-right"></div>

      <div class="stamp like-stamp">${isCareer ? "CONNECT" : "LIKE"}</div>
      <div class="stamp nope-stamp">SKIP</div>
      <div class="stamp super-stamp">${isCareer ? "STAR" : "SUPER"}</div>

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
          ${profile.age && !isCareer ? `<span class="card-age">${profile.age}</span>` : ""}
          <button class="action-btn info" data-action="info" title="Подробнее" style="margin-left:auto;">ℹ️</button>
        </div>
        ${careerSub}
        <div class="card-subtext">
          ${univStr ? `🏛 ${univStr}` : ""} ${yearStr ? `• ${yearStr}` : ""}
        </div>
        ${careerSkillsHtml || tagsHtml ? `<div class="card-tags">${careerSkillsHtml || tagsHtml}</div>` : ""}
        ${(profile.career_goal || profile.goal) ? `<p class="card-bio">${escapeHtml(profile.career_goal || profile.goal)}</p>` : ""}
        ${careerPortfolioBtn}

        <!-- Authentic Figma Action Buttons -->
        <div class="card-actions-row">
          <button class="action-btn dislike" data-action="skip" title="Пропустить">
            <img src="/static/webapp/assets/reaction-circle-1.svg" class="action-svg" alt="Skip" />
          </button>
          <button class="action-btn superlike" data-action="superlike" title="Суперлайк">
            ⭐
          </button>
          <button class="action-btn like" data-action="like" title="${isCareer ? 'Предложить проект' : 'Нравится'}">
            ${isCareer 
              ? '<img src="/static/webapp/assets/icon_career.svg" class="action-svg" style="border-radius:50%;" alt="Connect" />' 
              : '<img src="/static/webapp/assets/icon_dating.svg" class="action-svg" style="border-radius:50%;" alt="Like" />'}
          </button>
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
          photoImg.onerror = function() { this.onerror = null; this.src = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"; }; photoImg.src = photos[idx];
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
          photoImg.onerror = function() { this.onerror = null; this.src = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"; }; photoImg.src = photos[idx];
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
      sendSwipe(profile.user_id, action, comment, profile);

      // Фоновая подгрузка следующих анкет, когда в стеке осталось мало карточек
      const remainingCount = state.feed.length - state.currentCardIndex;
      if (remainingCount <= 3 && !isFetchingMore) {
        fetchMoreCards();
      }
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

  async function sendSwipe(targetId, action, comment = null, candidate = null) {
    try {
      const res = await apiFetch("/api/webapp/swipe", {
        method: "POST",
        body: JSON.stringify({ target_id: targetId, action: action, comment: comment }),
      });
      if (res && res.is_match) {
        showMatchPopup(res.match || { user_id: targetId }, candidate);
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
      .map((p) => `<img src="${p}" class="sheet-photo" alt="Photo" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />`)
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

      ${state.currentUser?.is_superadmin || state.currentUser?.id === 149620234 ? `
        <div class="admin-quick-toolbar" style="margin-top:14px;padding:12px;background:#f8f9fe;border-radius:14px;border:1px dashed #6c5ce7;">
          <div style="font-size:11px;font-weight:700;color:#6c5ce7;text-transform:uppercase;margin-bottom:8px;display:flex;align-items:center;gap:6px;">
            👑 Панель управления (Superadmin)
          </div>
          <div style="display:flex;gap:8px;">
            <button class="btn-primary" id="sheetAdminPremBtn" style="font-size:12px;padding:8px 12px;background:${profile.is_premium ? '#ff7675' : 'linear-gradient(135deg, #FFD700, #FFA500)'};color:#fff;border:none;">
              ${profile.is_premium ? "💎 Снять Премиум" : "👑 Выдать Премиум (1 год)"}
            </button>
            <button class="btn-secondary" id="sheetAdminVerifyBtn" style="font-size:12px;padding:8px 12px;">
              🎓 ${profile.is_verified ? "Снять статус" : "Верифицировать"}
            </button>
          </div>
        </div>
      ` : ""}

      <div class="card-actions-row" style="margin-top: 10px;">
        <button class="action-btn dislike" id="sheetDislikeBtn">
          <img src="/static/webapp/assets/reaction-circle-1.svg" class="action-svg" alt="Skip" />
        </button>
        <button class="action-btn superlike" id="sheetSuperlikeBtn">⭐</button>
        <button class="action-btn like" id="sheetLikeBtn">
          <img src="/static/webapp/assets/reaction-circle-2.svg" class="action-svg" alt="Like" />
        </button>
      </div>

      <button class="sheet-report-btn" id="sheetReportBtn">
        🚩 Пожаловаться на анкету
      </button>
    `;

    detailsSheetOverlay.classList.add("active");

    if (state.currentUser?.is_superadmin || state.currentUser?.id === 149620234) {
      const targetUserId = profile.user_id || profile.id;
      document.getElementById("sheetAdminPremBtn")?.addEventListener("click", async () => {
        triggerHaptic("medium");
        await window.adminUserAction(targetUserId, "grant_premium");
        profile.is_premium = !profile.is_premium;
        const btn = document.getElementById("sheetAdminPremBtn");
        if (btn) {
          btn.innerHTML = profile.is_premium ? "💎 Снять Премиум" : "👑 Выдать Премиум (1 год)";
          btn.style.background = profile.is_premium ? "#ff7675" : "linear-gradient(135deg, #FFD700, #FFA500)";
        }
        await loadStories();
      });
      document.getElementById("sheetAdminVerifyBtn")?.addEventListener("click", async () => {
        triggerHaptic("medium");
        await window.adminUserAction(targetUserId, "grant_verified");
        profile.is_verified = !profile.is_verified;
        const btn = document.getElementById("sheetAdminVerifyBtn");
        if (btn) {
          btn.innerHTML = `🎓 ${profile.is_verified ? "Снять статус" : "Верифицировать"}`;
        }
        await loadStories();
      });
    }

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

        const targetGender = data.gender || "all";
        document.querySelectorAll(".gender-pill").forEach((gp) => {
          gp.classList.toggle("active", gp.dataset.gender === targetGender);
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
    
    // Gender pills
    document.querySelectorAll(".gender-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        triggerHaptic("light");
        document.querySelectorAll(".gender-pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
      });
    });

    // Course pills
    document.querySelectorAll(".course-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        triggerHaptic("light");
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

      const activeGenderPill = document.querySelector(".gender-pill.active");
      const selectedGender = activeGenderPill ? activeGenderPill.dataset.gender : "all";

      triggerHaptic("medium");
      await apiFetch("/api/webapp/filters", {
        method: "POST",
        body: JSON.stringify({
          min_age: minAge,
          max_age: maxAge,
          min_year: minYear,
          max_year: maxYear,
          major: major,
          gender: selectedGender,
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
          gender: "all",
        }),
      });
      document.querySelectorAll(".gender-pill").forEach((p) => {
        p.classList.toggle("active", p.dataset.gender === "all");
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
      const balance = state.currentUser?.superlike_balance || 0;
      if (balance <= 0) {
        const msg = "⭐ У вас пока нет суперлайков. Пригласите однокурсника по ссылке в боте, чтобы получить +3 ⭐ бесплатно!";
        if (tg && tg.showAlert) tg.showAlert(msg);
        else alert(msg);
        return;
      }
      const candidate = state.selectedCandidateForSuperlike;
      const comment = commentInput.value.trim();
      superlikeModal.classList.remove("active");
      if (candidate) handleSwipeAction(candidate, "superlike", comment);
    });
    document.getElementById("sendSuperlikeQuickBtn")?.addEventListener("click", () => {
      const balance = state.currentUser?.superlike_balance || 0;
      if (balance <= 0) {
        const msg = "⭐ У вас пока нет суперлайков. Пригласите однокурсника по ссылке в боте, чтобы получить +3 ⭐ бесплатно!";
        if (tg && tg.showAlert) tg.showAlert(msg);
        else alert(msg);
        return;
      }
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
      const reportedUserId = candidate.user_id || candidate.id;
      if (candidate.matchId) {
        await apiFetch(`/api/webapp/matches/${candidate.matchId}/report`, {
          method: "POST",
          body: JSON.stringify({
            reason: checkedReason,
            details: "Жалоба отправлена из диалога",
          }),
        });
        reportModal.classList.remove("active");
        closeChat();
      } else {
        await apiFetch("/api/webapp/report", {
          method: "POST",
          body: JSON.stringify({
            reported_id: reportedUserId,
            reason: checkedReason,
          }),
        });
        reportModal.classList.remove("active");
        const topCard = deckContainer.querySelector(`.swipe-card[data-user-id="${reportedUserId}"]`);
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
      }
    });

    document.getElementById("matchCloseBtn")?.addEventListener("click", () => {
      matchModal.classList.remove("active");
    });
  }

  function openSuperlikeModal(profile) {
    state.selectedCandidateForSuperlike = profile;
    const balance = state.currentUser?.superlike_balance || 0;
    const balanceLabel = document.getElementById("superlikeBalanceLabel");
    if (balanceLabel) {
      balanceLabel.textContent = balance;
    }
    const zeroAlert = document.getElementById("superlikeZeroAlert");
    if (zeroAlert) {
      zeroAlert.style.display = balance <= 0 ? "block" : "none";
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

  // 8. Всплывающее окно взаимного мэтча с кнопкой в чат (Match Celebration)
  function showMatchPopup(partner, candidate = null) {
    triggerHaptic("success");
    const pNameEl = document.getElementById("matchPartnerName");
    const pAvatarEl = document.getElementById("matchPartnerAvatar");
    const myAvatarEl = document.getElementById("matchMyAvatar");
    const chatBtn = document.getElementById("matchChatBtn");

    const partnerName = partner?.name || candidate?.name || "Студент";
    if (pNameEl) pNameEl.textContent = partnerName;

    const fallbackAvatar = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=300&q=80";
    const partnerPhoto = partner?.photo_url || (partner?.photos && partner.photos[0]) || (candidate?.photos && candidate.photos[0]) || fallbackAvatar;
    if (pAvatarEl) {
      pAvatarEl.src = partnerPhoto;
      pAvatarEl.alt = partnerName;
      pAvatarEl.onerror = function () {
        this.onerror = null;
        this.src = fallbackAvatar;
      };
    }

    const myPhoto = (state.currentUser?.photos && state.currentUser.photos[0]) || state.currentUser?.avatar_url || state.currentUser?.photo_url || fallbackAvatar;
    if (myAvatarEl) {
      myAvatarEl.src = myPhoto;
      myAvatarEl.onerror = function () {
        this.onerror = null;
        this.src = fallbackAvatar;
      };
    }

    const matchId = partner?.match_id || candidate?.match_id;
    if (chatBtn) {
      chatBtn.onclick = () => {
        matchModal.classList.remove("active");
        if (matchId) {
          openChat(matchId);
        } else {
          switchTab("matches");
        }
      };
    }

    matchModal.classList.add("active");
  }
  window.showMatchModal = showMatchPopup;
  window.showMatchPopup = showMatchPopup;

  // 9. Раздел «Мэтчи» со встроенными чатами и открытием диалога
  async function loadMatches() {
    const container = document.getElementById("matchesContainer");
    if (!container) return;
    container.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);">Загрузка...</div>';

    try {
      const data = await apiFetch("/api/webapp/matches");
      if (!data || !data.matches || data.matches.length === 0) {
        state.matches = [];
        container.innerHTML = `
          <div style="text-align:center;padding:40px 20px;">
            <div style="font-size:48px;margin-bottom:12px;">🫂</div>
            <h3 style="font-size:18px;font-weight:800;margin-bottom:6px;">Пока нет мэтчей</h3>
            <p style="font-size:13px;color:var(--text-muted);">Продолжайте свайпать в ленте, чтобы найти пару!</p>
          </div>
        `;
        return;
      }

      state.matches = data.matches;

      container.innerHTML = data.matches
        .map((m) => {
          const photoUrl = m.photo_url || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80";
          const verified = m.is_verified ? " 🎓" : "";
          const prem = m.is_premium ? " 💎" : "";
          const unreadBadge = m.unread_count > 0 ? `<div class="match-unread-badge">${m.unread_count}</div>` : "";

          let lastMsgText = "Нажмите, чтобы начать общение";
          if (m.last_message && m.last_message.text) {
            lastMsgText = (m.last_message.is_mine ? "Вы: " : "") + escapeHtml(m.last_message.text);
          } else if (m.is_tg_unlocked) {
            lastMsgText = "✈️ Контакты Telegram открыты";
          }

          const statusBadge = m.is_tg_unlocked
            ? `<span class="match-status-pill unlocked">✈️ TG</span>`
            : `<span class="match-status-pill chat">💬 Чат</span>`;

          return `
            <div class="match-item" data-match-id="${m.match_id}" data-partner-id="${m.user_id}">
              <div class="match-avatar-wrap">
                <img src="${photoUrl}" class="match-avatar" alt="${escapeHtml(m.name)}" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />
                ${unreadBadge}
              </div>
              <div class="match-info">
                <div class="match-name-row">
                  <span class="match-name">${escapeHtml(m.name)}${verified}${prem}</span>
                  ${statusBadge}
                </div>
                <div class="match-univ">${m.university || "ВУЗ"} ${m.year ? `• ${m.year} курс` : ""}</div>
                <div class="match-last-msg">${lastMsgText}</div>
              </div>
            </div>
          `;
        })
        .join("");

      container.querySelectorAll(".match-item").forEach((item) => {
        item.addEventListener("click", () => {
          const matchId = item.dataset.matchId;
          if (matchId) {
            openChat(matchId);
          } else {
            const pid = item.dataset.partnerId;
            openMatchFullProfile(pid);
          }
        });
      });
    } catch (e) {
      container.innerHTML = '<div style="text-align:center;padding:30px;color:red;">Ошибка загрузки</div>';
    }
  }

  // 10. Открытие полной анкеты мэтча с защитой контактов Telegram
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
      const gallery = photos.map((p) => `<img src="${p}" class="sheet-photo" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />`).join("");
      const tags = (u.tags || []).map((t) => `<span class="card-tag">${t.emoji} ${t.name}</span>`).join("");

      const chatButtonHtml = u.tg_username
        ? `<a href="https://t.me/${u.tg_username.replace("@", "")}" target="_blank" class="btn-primary" style="text-decoration:none;display:block;text-align:center;">
             💬 Написать в Telegram (@${u.tg_username.replace("@", "")})
           </a>`
        : `<button class="btn-primary" id="btnOpenChatFromProfile" style="width:100%;">
             💬 Открыть чат в приложении
           </button>`;

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

        ${state.currentUser?.is_superadmin || state.currentUser?.id === 149620234 ? `
          <div class="admin-quick-toolbar" style="margin-top:14px;padding:12px;background:#f8f9fe;border-radius:14px;border:1px dashed #6c5ce7;">
            <div style="font-size:11px;font-weight:700;color:#6c5ce7;text-transform:uppercase;margin-bottom:8px;display:flex;align-items:center;gap:6px;">
              👑 Панель управления (Superadmin)
            </div>
            <div style="display:flex;gap:8px;">
              <button class="btn-primary" id="btnAdminMatchPrem-${u.id || u.user_id}" style="font-size:12px;padding:8px 12px;background:${u.is_premium ? '#ff7675' : 'linear-gradient(135deg, #FFD700, #FFA500)'};color:#fff;border:none;">
                ${u.is_premium ? "💎 Снять Премиум" : "👑 Выдать Премиум (1 год)"}
              </button>
              <button class="btn-secondary" id="btnAdminMatchVerify-${u.id || u.user_id}" style="font-size:12px;padding:8px 12px;">
                🎓 ${u.is_verified ? "Снять статус" : "Верифицировать"}
              </button>
            </div>
          </div>
        ` : ""}

        <div style="margin-top: 14px;">
          ${chatButtonHtml}
        </div>
      `;

      document.getElementById("btnOpenChatFromProfile")?.addEventListener("click", () => {
        matchProfileModal.classList.remove("active");
        const foundMatch = (state.matches || []).find(m => String(m.user_id) === String(partnerId));
        if (foundMatch && foundMatch.match_id) {
          openChat(foundMatch.match_id);
        } else {
          switchTab("matches");
        }
      });

      if (state.currentUser?.is_superadmin || state.currentUser?.id === 149620234) {
        const targetUserId = u.id || u.user_id;
        document.getElementById(`btnAdminMatchPrem-${targetUserId}`)?.addEventListener("click", async () => {
          triggerHaptic("medium");
          await window.adminUserAction(targetUserId, "grant_premium");
          u.is_premium = !u.is_premium;
          const btn = document.getElementById(`btnAdminMatchPrem-${targetUserId}`);
          if (btn) {
            btn.innerHTML = u.is_premium ? "💎 Снять Премиум" : "👑 Выдать Премиум (1 год)";
            btn.style.background = u.is_premium ? "#ff7675" : "linear-gradient(135deg, #FFD700, #FFA500)";
          }
          await loadStories();
        });
        document.getElementById(`btnAdminMatchVerify-${targetUserId}`)?.addEventListener("click", async () => {
          triggerHaptic("medium");
          await window.adminUserAction(targetUserId, "grant_verified");
          u.is_verified = !u.is_verified;
          const btn = document.getElementById(`btnAdminMatchVerify-${targetUserId}`);
          if (btn) {
            btn.innerHTML = `🎓 ${u.is_verified ? "Снять статус" : "Верифицировать"}`;
          }
          await loadStories();
        });
      }
    } catch (e) {
      body.innerHTML = '<div style="text-align:center;padding:30px;color:red;">Ошибка загрузки анкеты</div>';
    }
  }

  // ─── 11. In-App Chat Controller & Real-Time Engine ─────────────
  let currentChatMatchId = null;
  let currentChatPartner = null;
  let currentChatMatchData = null;
  let chatWebSocket = null;
  let typingTimer = null;
  let isSendingTyping = false;
  let chatPingInterval = null;

  const chatScreenModal = document.getElementById("chatScreenModal");
  const chatBackBtn = document.getElementById("chatBackBtn");
  const chatPartnerHeaderProfile = document.getElementById("chatPartnerHeaderProfile");
  const chatPartnerAvatar = document.getElementById("chatPartnerAvatar");
  const chatPartnerOnlineDot = document.getElementById("chatPartnerOnlineDot");
  const chatPartnerName = document.getElementById("chatPartnerName");
  const chatPartnerPremBadge = document.getElementById("chatPartnerPremBadge");
  const chatPartnerStatus = document.getElementById("chatPartnerStatus");
  const chatMenuBtn = document.getElementById("chatMenuBtn");
  const chatDropdownMenu = document.getElementById("chatDropdownMenu");
  const chatActionViewProfile = document.getElementById("chatActionViewProfile");
  const chatActionReport = document.getElementById("chatActionReport");
  const chatActionUnmatch = document.getElementById("chatActionUnmatch");
  const chatTgBanner = document.getElementById("chatTgBanner");
  const chatMessagesContainer = document.getElementById("chatMessagesContainer");
  const chatLoadingSpinner = document.getElementById("chatLoadingSpinner");
  const chatMessagesInner = document.getElementById("chatMessagesInner");
  const chatTypingIndicator = document.getElementById("chatTypingIndicator");
  const chatTypingName = document.getElementById("chatTypingName");
  const chatInputText = document.getElementById("chatInputText");
  const chatSendBtn = document.getElementById("chatSendBtn");
  const chatUnmatchModal = document.getElementById("chatUnmatchModal");
  const closeUnmatchModalBtn = document.getElementById("closeUnmatchModalBtn");
  const confirmUnmatchBtn = document.getElementById("confirmUnmatchBtn");
  const cancelUnmatchBtn = document.getElementById("cancelUnmatchBtn");

  // Открытие диалога
  async function openChat(matchId) {
    if (!matchId) return;
    triggerHaptic("light");
    currentChatMatchId = matchId;

    if (chatDropdownMenu) chatDropdownMenu.style.display = "none";
    if (chatScreenModal) chatScreenModal.style.display = "flex";
    if (chatLoadingSpinner) chatLoadingSpinner.style.display = "flex";
    if (chatMessagesInner) chatMessagesInner.innerHTML = "";
    if (chatTypingIndicator) chatTypingIndicator.style.display = "none";
    if (chatTgBanner) chatTgBanner.innerHTML = "";
    if (chatPartnerStatus) chatPartnerStatus.textContent = "загрузка...";

    if (chatInputText) {
      chatInputText.value = "";
      chatInputText.style.height = "auto";
    }
    if (chatSendBtn) chatSendBtn.disabled = true;

    // Интеграция с Telegram WebApp BackButton
    if (tg?.BackButton) {
      tg.BackButton.show();
      tg.BackButton.onClick(closeChat);
    }

    try {
      const data = await apiFetch(`/api/webapp/matches/${matchId}/messages`);
      if (!data || !data.match) {
        throw new Error("Не удалось загрузить диалог");
      }

      currentChatMatchData = data.match;
      currentChatPartner = data.match.partner;

      // Обновляем шапку чата
      if (chatPartnerName) {
        chatPartnerName.textContent = currentChatPartner.name || "Собеседник";
      }
      if (chatPartnerPremBadge) {
        chatPartnerPremBadge.style.display = currentChatPartner.is_premium ? "inline" : "none";
      }
      if (chatPartnerAvatar) {
        chatPartnerAvatar.src = currentChatPartner.avatar_url || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80";
        chatPartnerAvatar.onerror = function() {
          this.onerror = null;
          this.src = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80";
        };
      }
      if (chatTypingName) {
        chatTypingName.textContent = currentChatPartner.name || "Собеседник";
      }
      if (chatPartnerStatus) {
        chatPartnerStatus.textContent = "онлайн";
      }
      if (chatPartnerOnlineDot) {
        chatPartnerOnlineDot.style.display = "block";
      }

      // Отрисовываем баннер Telegram
      renderChatTgBanner(currentChatMatchData);

      // Отрисовываем сообщения
      if (chatLoadingSpinner) chatLoadingSpinner.style.display = "none";
      renderChatMessages(data.messages || []);

      // Подключаем WebSocket
      connectChatWebSocket(matchId);

    } catch (err) {
      console.error("[Chat] Error loading chat:", err);
      if (chatLoadingSpinner) chatLoadingSpinner.style.display = "none";
      if (chatMessagesInner) {
        chatMessagesInner.innerHTML = `
          <div style="text-align:center;padding:40px 20px;color:var(--text-muted);">
            <div style="font-size:36px;margin-bottom:8px;">⚠️</div>
            <div>Не удалось загрузить сообщения. Попробуйте позже.</div>
          </div>
        `;
      }
    }
  }
  window.openChat = openChat;

  // Закрытие диалога
  function closeChat() {
    triggerHaptic("light");
    if (chatScreenModal) chatScreenModal.style.display = "none";
    if (chatWebSocket) {
      try { chatWebSocket.close(); } catch(e) {}
      chatWebSocket = null;
    }
    if (chatPingInterval) {
      clearInterval(chatPingInterval);
      chatPingInterval = null;
    }
    currentChatMatchId = null;
    currentChatPartner = null;
    currentChatMatchData = null;

    if (tg?.BackButton) {
      tg.BackButton.hide();
      tg.BackButton.offClick(closeChat);
    }

    // Обновляем список мэтчей
    loadMatches();
  }
  window.closeChat = closeChat;

  // Отрисовка баннера обоюдного раскрытия Telegram
  function renderChatTgBanner(matchData) {
    if (!chatTgBanner || !matchData) return;

    if (matchData.is_tg_unlocked && matchData.partner_tg_username) {
      const cleanTg = matchData.partner_tg_username.replace("@", "");
      chatTgBanner.innerHTML = `
        <div class="chat-tg-banner-text">
          <div class="chat-tg-banner-title">🎉 Контакты Telegram открыты!</div>
          <div class="chat-tg-banner-desc">Вы и собеседник обоюдно подтвердили переход в Telegram.</div>
        </div>
        <a href="https://t.me/${cleanTg}" target="_blank" class="chat-tg-banner-btn unlocked">
          <span>💬 @${cleanTg}</span>
        </a>
      `;
    } else if (matchData.my_tg_approved) {
      chatTgBanner.innerHTML = `
        <div class="chat-tg-banner-text">
          <div class="chat-tg-banner-title">⏳ Ожидание согласия</div>
          <div class="chat-tg-banner-desc">Вы разрешили открыть контакты. Ждём ответ от ${escapeHtml(matchData.partner?.name || "собеседника")}.</div>
        </div>
        <button type="button" class="chat-tg-banner-btn pending" disabled>
          Ожидание...
        </button>
      `;
    } else {
      chatTgBanner.innerHTML = `
        <div class="chat-tg-banner-text">
          <div class="chat-tg-banner-title">✈️ Перейти в Telegram?</div>
          <div class="chat-tg-banner-desc">Контакты откроются, только когда оба участника дадут разрешение.</div>
        </div>
        <button type="button" class="chat-tg-banner-btn primary" id="btnRequestTelegram">
          ✨ Открыть TG
        </button>
      `;

      document.getElementById("btnRequestTelegram")?.addEventListener("click", requestTelegramReveal);
    }
  }

  // Запрос согласия на открытие контактов
  async function requestTelegramReveal() {
    if (!currentChatMatchId) return;
    triggerHaptic("medium");
    const btn = document.getElementById("btnRequestTelegram");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Секунду...";
    }

    try {
      const res = await apiFetch(`/api/webapp/matches/${currentChatMatchId}/request_telegram`, {
        method: "POST"
      });

      if (res && res.status === "ok") {
        triggerHaptic("success");
        currentChatMatchData.is_tg_unlocked = res.is_tg_unlocked;
        currentChatMatchData.my_tg_approved = res.my_tg_approved;
        currentChatMatchData.partner_tg_approved = res.partner_tg_approved;
        currentChatMatchData.partner_tg_username = res.partner_tg_username;
        renderChatTgBanner(currentChatMatchData);
      }
    } catch (err) {
      console.error("[Chat] Failed to request telegram:", err);
      if (btn) {
        btn.disabled = false;
        btn.textContent = "✨ Открыть TG";
      }
    }
  }
  window.requestTelegramRevealAction = requestTelegramReveal;

  // Отрисовка списка сообщений
  function renderChatMessages(messages) {
    if (!chatMessagesInner) return;
    if (!messages || messages.length === 0) {
      chatMessagesInner.innerHTML = `
        <div style="text-align:center;padding:30px 16px;color:var(--text-muted);">
          <div style="font-size:36px;margin-bottom:6px;">👋</div>
          <h4 style="font-size:15px;font-weight:700;color:var(--text-main);margin-bottom:4px;">Это взаимная симпатия!</h4>
          <p style="font-size:12px;line-height:1.4;">Напишите первое сообщение, сделайте комплимент или задайте вопрос.</p>
        </div>
      `;
      return;
    }

    chatMessagesInner.innerHTML = messages.map((msg) => renderMessageHtml(msg)).join("");
    scrollChatToBottom();
  }

  function renderMessageHtml(msg) {
    const isMine = Boolean(msg.is_mine);
    const timeStr = msg.created_at || "";

    if (msg.msg_type === "tg_request" || msg.msg_type === "system") {
      let actionBtn = "";
      if (msg.msg_type === "tg_request" && currentChatMatchData && !currentChatMatchData.my_tg_approved && !currentChatMatchData.is_tg_unlocked) {
        actionBtn = `<button class="chat-system-action-btn" onclick="window.requestTelegramRevealAction()">✨ Открыть контакты взаимно</button>`;
      }
      return `
        <div class="chat-system-card" data-msg-id="${msg.id}">
          <div class="chat-system-text">${escapeHtml(msg.text)}</div>
          ${actionBtn}
          <div class="chat-system-time">${timeStr}</div>
        </div>
      `;
    }

    const checkmarks = isMine ? (msg.is_read ? "✓✓" : "✓") : "";

    return `
      <div class="chat-msg-row ${isMine ? 'outgoing' : 'incoming'}" data-msg-id="${msg.id}">
        <div class="chat-bubble">
          <div class="chat-bubble-text">${escapeHtml(msg.text)}</div>
          <div class="chat-bubble-footer">
            <span class="chat-bubble-time">${timeStr}</span>
            ${isMine ? `<span class="chat-read-status">${checkmarks}</span>` : ""}
          </div>
        </div>
      </div>
    `;
  }

  function scrollChatToBottom(smooth = false) {
    if (!chatMessagesContainer) return;
    requestAnimationFrame(() => {
      chatMessagesContainer.scrollTo({
        top: chatMessagesContainer.scrollHeight,
        behavior: smooth ? "smooth" : "auto"
      });
    });
  }

  // Отправка текстового сообщения
  async function sendChatMessage() {
    if (!currentChatMatchId || !chatInputText) return;
    const text = chatInputText.value.trim();
    if (!text) return;

    chatInputText.value = "";
    chatInputText.style.height = "auto";
    if (chatSendBtn) chatSendBtn.disabled = true;
    triggerHaptic("light");

    const tempId = "temp_" + Date.now();
    const now = new Date();
    const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    const optimisticMsg = {
      id: tempId,
      text: text,
      msg_type: "text",
      is_mine: true,
      is_read: false,
      created_at: timeStr,
    };

    if (chatMessagesInner) {
      chatMessagesInner.insertAdjacentHTML("beforeend", renderMessageHtml(optimisticMsg));
      scrollChatToBottom(true);
    }

    try {
      const res = await apiFetch(`/api/webapp/matches/${currentChatMatchId}/messages`, {
        method: "POST",
        body: JSON.stringify({ text: text })
      });

      if (res && res.message) {
        const el = chatMessagesInner.querySelector(`[data-msg-id="${tempId}"]`);
        if (el) {
          el.dataset.msgId = res.message.id;
        }
      }
    } catch (err) {
      console.error("[Chat] Failed to send message:", err);
      const el = chatMessagesInner.querySelector(`[data-msg-id="${tempId}"]`);
      if (el) {
        el.style.opacity = "0.5";
        el.title = "Не удалось отправить";
      }
    }
  }

  // Подключение к WebSocket диалога
  function connectChatWebSocket(matchId) {
    if (chatWebSocket) {
      try { chatWebSocket.close(); } catch(e) {}
      chatWebSocket = null;
    }
    if (chatPingInterval) {
      clearInterval(chatPingInterval);
      chatPingInterval = null;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const token = state.token || "";
    const wsUrl = `${protocol}//${host}/api/webapp/ws/chat/${matchId}?token=${encodeURIComponent(token)}`;

    try {
      chatWebSocket = new WebSocket(wsUrl);

      chatWebSocket.onopen = function () {
        console.log("[Chat WS] Connected to match:", matchId);
        chatWebSocket.send(JSON.stringify({ type: "read" }));

        chatPingInterval = setInterval(() => {
          if (chatWebSocket && chatWebSocket.readyState === WebSocket.OPEN) {
            chatWebSocket.send(JSON.stringify({ type: "ping" }));
          }
        }, 25000);
      };

      chatWebSocket.onmessage = function (event) {
        try {
          const data = JSON.parse(event.data);
          handleChatWsEvent(data);
        } catch (e) {
          console.warn("[Chat WS] Parse error:", e);
        }
      };

      chatWebSocket.onclose = function () {
        console.log("[Chat WS] Closed");
        if (chatPingInterval) {
          clearInterval(chatPingInterval);
          chatPingInterval = null;
        }
      };

      chatWebSocket.onerror = function (e) {
        console.warn("[Chat WS] Error:", e);
      };
    } catch (err) {
      console.warn("[Chat WS] Connection error:", err);
    }
  }

  function handleChatWsEvent(data) {
    if (!data || !data.type) return;

    if (data.type === "new_message") {
      const msg = data.message;
      if (!msg) return;

      const isMine = String(msg.sender_id) === String(state.currentUser?.id);
      if (!isMine) {
        triggerHaptic("light");
        if (chatMessagesInner) {
          chatMessagesInner.insertAdjacentHTML("beforeend", renderMessageHtml({
            id: msg.id,
            text: msg.text,
            msg_type: msg.msg_type,
            is_mine: false,
            is_read: true,
            created_at: msg.created_at,
          }));
          scrollChatToBottom(true);
        }
        if (chatWebSocket && chatWebSocket.readyState === WebSocket.OPEN) {
          chatWebSocket.send(JSON.stringify({ type: "read" }));
        }
      }
    } else if (data.type === "read") {
      if (chatMessagesInner) {
        chatMessagesInner.querySelectorAll(".chat-msg-row.outgoing .chat-read-status").forEach((el) => {
          el.textContent = "✓✓";
        });
      }
    } else if (data.type === "typing") {
      if (String(data.user_id) !== String(state.currentUser?.id)) {
        if (chatTypingIndicator) {
          chatTypingIndicator.style.display = "flex";
          clearTimeout(typingTimer);
          typingTimer = setTimeout(() => {
            chatTypingIndicator.style.display = "none";
          }, 3000);
          scrollChatToBottom(true);
        }
      }
    } else if (data.type === "tg_approval_update") {
      triggerHaptic("success");
      if (currentChatMatchData) {
        currentChatMatchData.is_tg_unlocked = data.is_tg_unlocked;
        if (data.is_tg_unlocked && data.partner_tg_username) {
          currentChatMatchData.partner_tg_username = data.partner_tg_username;
        }
        renderChatTgBanner(currentChatMatchData);
      }
      if (data.system_message && chatMessagesInner) {
        chatMessagesInner.insertAdjacentHTML("beforeend", renderMessageHtml({
          id: data.system_message.id,
          text: data.system_message.text,
          msg_type: data.system_message.msg_type || "system",
          is_mine: false,
          created_at: data.system_message.created_at,
        }));
        scrollChatToBottom(true);
      }
    } else if (data.type === "user_online") {
      if (chatPartnerOnlineDot) chatPartnerOnlineDot.style.display = "block";
      if (chatPartnerStatus) chatPartnerStatus.textContent = "онлайн";
    } else if (data.type === "user_offline") {
      if (chatPartnerOnlineDot) chatPartnerOnlineDot.style.display = "none";
      if (chatPartnerStatus) chatPartnerStatus.textContent = "был(а) недавно";
    } else if (data.type === "unmatched") {
      alert("Собеседник удалил пару или диалог был закрыт.");
      closeChat();
    }
  }

  // Слушатели действий чата
  if (chatBackBtn) {
    chatBackBtn.addEventListener("click", closeChat);
  }

  if (chatPartnerHeaderProfile) {
    chatPartnerHeaderProfile.addEventListener("click", () => {
      if (currentChatPartner?.id) {
        openMatchFullProfile(currentChatPartner.id);
      }
    });
  }

  if (chatMenuBtn && chatDropdownMenu) {
    chatMenuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const isVisible = chatDropdownMenu.style.display === "flex";
      chatDropdownMenu.style.display = isVisible ? "none" : "flex";
      triggerHaptic("light");
    });

    document.addEventListener("click", () => {
      if (chatDropdownMenu) chatDropdownMenu.style.display = "none";
    });
  }

  if (chatActionViewProfile) {
    chatActionViewProfile.addEventListener("click", () => {
      if (chatDropdownMenu) chatDropdownMenu.style.display = "none";
      if (currentChatPartner?.id) {
        openMatchFullProfile(currentChatPartner.id);
      }
    });
  }

  if (chatActionReport) {
    chatActionReport.addEventListener("click", () => {
      if (chatDropdownMenu) chatDropdownMenu.style.display = "none";
      if (currentChatPartner) {
        openReportModal({
          id: currentChatPartner.id,
          user_id: currentChatPartner.id,
          name: currentChatPartner.name,
          matchId: currentChatMatchId,
        });
      }
    });
  }

  if (chatActionUnmatch) {
    chatActionUnmatch.addEventListener("click", () => {
      if (chatDropdownMenu) chatDropdownMenu.style.display = "none";
      if (chatUnmatchModal) chatUnmatchModal.style.display = "flex";
      triggerHaptic("medium");
    });
  }

  if (closeUnmatchModalBtn) {
    closeUnmatchModalBtn.addEventListener("click", () => {
      if (chatUnmatchModal) chatUnmatchModal.style.display = "none";
    });
  }
  if (cancelUnmatchBtn) {
    cancelUnmatchBtn.addEventListener("click", () => {
      if (chatUnmatchModal) chatUnmatchModal.style.display = "none";
    });
  }

  if (confirmUnmatchBtn) {
    confirmUnmatchBtn.addEventListener("click", async () => {
      if (!currentChatMatchId) return;
      confirmUnmatchBtn.disabled = true;
      confirmUnmatchBtn.textContent = "Удаление...";
      try {
        await apiFetch(`/api/webapp/matches/${currentChatMatchId}/unmatch`, { method: "POST" });
        triggerHaptic("medium");
        if (chatUnmatchModal) chatUnmatchModal.style.display = "none";
        closeChat();
      } catch (err) {
        console.error("Unmatch failed:", err);
      } finally {
        confirmUnmatchBtn.disabled = false;
        confirmUnmatchBtn.textContent = "Удалить пару";
      }
    });
  }

  if (chatInputText) {
    chatInputText.addEventListener("input", () => {
      chatInputText.style.height = "auto";
      chatInputText.style.height = Math.min(chatInputText.scrollHeight, 120) + "px";
      if (chatSendBtn) {
        chatSendBtn.disabled = !chatInputText.value.trim();
      }

      if (!isSendingTyping && chatWebSocket && chatWebSocket.readyState === WebSocket.OPEN) {
        isSendingTyping = true;
        chatWebSocket.send(JSON.stringify({ type: "typing" }));
        setTimeout(() => { isSendingTyping = false; }, 3000);
      }
    });

    chatInputText.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
      }
    });
  }

  if (chatSendBtn) {
    chatSendBtn.addEventListener("click", sendChatMessage);
  }

  // 12. Deep Linking (startapp=chat_{match_id})
  function checkStartParamDeepLink() {
    let startParam = "";
    try {
      if (tg?.initDataUnsafe?.start_param) {
        startParam = tg.initDataUnsafe.start_param;
      } else {
        const urlParams = new URLSearchParams(window.location.search);
        startParam = urlParams.get("startapp") || urlParams.get("tgWebAppStartParam") || "";
      }
    } catch (e) {
      console.warn("[DeepLink] Error reading start param:", e);
    }

    if (startParam && startParam.startsWith("chat_")) {
      const matchId = startParam.replace("chat_", "").trim();
      if (matchId) {
        console.log("[DeepLink] Opening chat from startapp:", matchId);
        openChat(matchId);
      }
    }
  }

  matchProfileModal?.addEventListener("click", (e) => {
    if (e.target === matchProfileModal) matchProfileModal.classList.remove("active");
  });

  document.getElementById("closeMatchProfileBtn")?.addEventListener("click", () => {
    matchProfileModal?.classList.remove("active");
    triggerHaptic("light");
  });

  document.getElementById("closeDetailsSheetBtn")?.addEventListener("click", () => {
    closeDetailsSheet();
    triggerHaptic("light");
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
                    <img src="${img}" class="like-card-img" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />
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
      if (!data) return;
      if (data.maintenance) {
        updateMaintenanceUI(data.maintenance);
      }
      if (!data.user) return;
      const u = data.user;
      state.currentUser = u;

      const avatar = u.photos && u.photos.length > 0
        ? u.photos[0]
        : "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=300&q=80";

      container.innerHTML = `
        <div class="profile-card">
          <div class="profile-avatar-wrap ${u.is_premium ? "premium" : ""}">
            <img src="${avatar}" class="profile-avatar" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />
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
              <span class="stat-value" id="profileModeStat">${u.mode === "career" ? "💼" : "💘"}</span>
              <span class="stat-label">Режим</span>
            </div>
          </div>
        </div>

        <div class="profile-menu-list">
          ${u.is_superadmin ? `
            <div class="profile-menu-item admin-btn" id="btnOpenAdminHub">
              <span>👑 Панель управления (Admin Hub)</span>
              <span style="font-size: 11px; background:linear-gradient(135deg, #FFB800, #FF6584); color:#fff; padding:3px 8px; border-radius:10px; font-weight:900;">GOD MODE</span>
            </div>
          ` : ""}
          <div class="profile-menu-item" id="btnToggleProfileMode">
            <span>Режим поиска: <b id="profileModeLabel">${u.mode === "career" ? "💼 Карьера" : "💘 Знакомства"}</b></span>
            <span>⇄</span>
          </div>
          <div class="profile-menu-item" id="btnOpenSearchFilters">
            <span>🎯 Настройки фильтров поиска</span>
            <span>→</span>
          </div>
          <div class="profile-menu-item" id="btnOpenOnboarding">
            <span>✨ О платформе и подарке</span>
            <span>→</span>
          </div>
          <div class="profile-menu-item" id="btnToggleNotifications">
            <div style="display: flex; align-items: center; gap: 12px;">
              <span style="font-size: 20px;">🔔</span>
              <div style="text-align: left;">
                <div style="font-size: 14.5px; font-weight: 700; color: var(--text-main);">Уведомления о мэтчах</div>
                <div style="font-size: 11.5px; color: var(--text-muted); font-weight: 500;">Мгновенные алерты в чат с ботом</div>
              </div>
            </div>
            <label class="ios-toggle" onclick="event.stopPropagation()">
              <input type="checkbox" id="notificationToggleInput" ${localStorage.getItem("studmatch_notifications") !== "0" ? "checked" : ""}>
              <span class="toggle-slider"></span>
            </label>
          </div>
          <div class="profile-menu-item" id="btnResetSwipesProfile">
            <span>🔄 Сбросить историю свайпов</span>
            <span>→</span>
          </div>
          <div class="profile-menu-item" id="btnOpenSupport">
            <span>💬 Поддержка и обратная связь</span>
            <span>→</span>
          </div>
          <div class="profile-menu-item" id="btnOpenPrivacyPolicy">
            <span>📜 Политика конфиденциальности (152-ФЗ)</span>
            <span>→</span>
          </div>
        </div>
      `;

      if (u.is_superadmin) {
        document.getElementById("btnOpenAdminHub")?.addEventListener("click", openAdminHubModal);
      }
      document.getElementById("btnToggleProfileMode")?.addEventListener("click", toggleMode);
      document.getElementById("btnOpenSearchFilters")?.addEventListener("click", openFiltersModal);
      document.getElementById("btnOpenOnboarding")?.addEventListener("click", () => openOnboarding(true));
      
      // Обработчик тумблера уведомлений
      const notifToggle = document.getElementById("notificationToggleInput");
      const notifItem = document.getElementById("btnToggleNotifications");
      const handleNotifChange = (newState) => {
        triggerHaptic("light");
        localStorage.setItem("studmatch_notifications", newState ? "1" : "0");
        if (tg && tg.showAlert) {
          tg.showAlert(newState ? "🔔 Уведомления о новых мэтчах и лайках включены!" : "🔕 Уведомления о мэтчах отключены.");
        }
      };
      if (notifToggle) {
        notifToggle.addEventListener("change", (e) => handleNotifChange(e.target.checked));
      }
      if (notifItem) {
        notifItem.addEventListener("click", () => {
          if (notifToggle) {
            notifToggle.checked = !notifToggle.checked;
            handleNotifChange(notifToggle.checked);
          }
        });
      }

      document.getElementById("btnResetSwipesProfile")?.addEventListener("click", resetSwipesAndReload);

      document.getElementById("btnOpenSupport")?.addEventListener("click", () => {
        triggerHaptic("light");
        const botUser = window.BOT_USERNAME || "edudating_bot";
        const supportUrl = `https://t.me/${botUser}`;
        if (tg && tg.openTelegramLink) {
          tg.openTelegramLink(supportUrl);
        } else {
          window.open(supportUrl, "_blank");
        }
      });

      document.getElementById("btnOpenPrivacyPolicy")?.addEventListener("click", () => {
        triggerHaptic("light");
        const url = window.location.origin + "/privacy";
        if (tg && tg.openLink) {
          tg.openLink(url);
        } else {
          window.open(url, "_blank");
        }
      });
    } catch (e) {
      console.error("Profile load error:", e);
    }
  }

  // 12. Скрытая Админ-Панель (Superadmin ID: 149620234)
  function setupAdminListeners() {
    // Табы внутри Admin Hub
    document.querySelectorAll(".admin-tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.adminTab;
        document.querySelectorAll(".admin-tab-btn").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".admin-pane").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");

        if (tab === "stats") {
          document.getElementById("adminPaneStats")?.classList.add("active");
          loadAdminStats();
        } else if (tab === "users") {
          document.getElementById("adminPaneUsers")?.classList.add("active");
          searchAdminUsers();
        } else if (tab === "reports") {
          document.getElementById("adminPaneReports")?.classList.add("active");
          loadAdminReports();
        }
      });
    });

    document.getElementById("adminRefreshStatsBtn")?.addEventListener("click", loadAdminStats);

    // Поиск пользователей
    document.getElementById("adminUserSearchBtn")?.addEventListener("click", searchAdminUsers);
    document.getElementById("adminUserSearchInput")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") searchAdminUsers();
    });

    adminHubModal?.addEventListener("click", (e) => {
      if (e.target === adminHubModal) adminHubModal.classList.remove("active");
    });
  }

  function openAdminHubModal() {
    triggerHaptic("heavy");
    adminHubModal.classList.add("active");
    loadAdminStats();
  }

  async function loadAdminStats() {
    try {
      const data = await apiFetch("/api/webapp/admin/stats");
      if (data && data.stats) {
        document.getElementById("statTotalUsers").textContent = data.stats.total_users;
        document.getElementById("statActive24h").textContent = data.stats.active_24h;
        document.getElementById("statTotalMatches").textContent = data.stats.total_matches;
        document.getElementById("statTotalSwipes").textContent = data.stats.total_swipes;
      }
    } catch (e) {
      console.error("Admin stats error:", e);
    }
  }

  async function searchAdminUsers() {
    const input = document.getElementById("adminUserSearchInput");
    const container = document.getElementById("adminUserSearchResults");
    if (!container) return;
    const q = input ? input.value.trim() : "";

    triggerHaptic("light");
    container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);">Загрузка списка студентов...</div>';

    try {
      const data = await apiFetch(`/api/webapp/admin/users/search?q=${encodeURIComponent(q)}`);
      if (!data || !data.users || data.users.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);">Пользователи не найдены</div>';
        return;
      }

      container.innerHTML = data.users
        .map((u) => {
          const statusBadges = `
            ${u.is_banned ? '<span style="color:#E84118;font-weight:bold;">[ЗАБАНЕН]</span> ' : ''}
            ${u.is_premium ? '💎 ' : ''}
            ${u.is_verified ? '🎓 ' : ''}
          `;

          return `
            <div class="admin-user-card" data-user-id="${u.id}">
              <div class="admin-user-header">
                <span class="admin-user-title">${escapeHtml(u.name)} (ID: ${u.id})</span>
                <span>${statusBadges}</span>
              </div>
              <div class="admin-user-sub">
                @${u.username || "нет_юзернейма"} • ${u.university || "ВУЗ не указан"}
              </div>
              <div class="admin-user-sub" style="margin-top:4px;">
                ⭐ Звёзды: ${u.superlike_balance} • Рег: ${u.created_at}
              </div>
              <div class="admin-user-actions">
                <button class="admin-action-chip ${u.is_banned ? '' : 'danger'}" onclick="window.adminUserAction(${u.id}, 'toggle_ban')">
                  ${u.is_banned ? '🟢 Разбанить' : '🚫 Забанить'}
                </button>
                <button class="admin-action-chip" style="${u.is_premium ? 'background:#ff7675;color:#fff;' : 'background:linear-gradient(135deg, #FFD700, #FFA500);color:#fff;'}" onclick="window.adminUserAction(${u.id}, 'grant_premium')">
                  ${u.is_premium ? '💎 Снять Премиум' : '👑 Дать Премиум'}
                </button>
                <button class="admin-action-chip" onclick="window.adminUserAction(${u.id}, 'grant_verified')">
                  ${u.is_verified ? 'Снять ВУЗ' : '🎓 Верифицировать'}
                </button>
                <button class="admin-action-chip" onclick="window.adminUserAction(${u.id}, 'add_superlikes')">
                  ⭐ +10 звёзд
                </button>
              </div>
            </div>
          `;
        })
        .join("");
    } catch (e) {
      container.innerHTML = '<div style="text-align:center;padding:20px;color:red;">Ошибка поиска</div>';
    }
  }

  window.adminUserAction = async function (userId, action) {
    if (!userId) {
      console.error("Invalid userId for admin action:", userId);
      return;
    }
    triggerHaptic("medium");
    try {
      const res = await apiFetch(`/api/webapp/admin/users/${userId}/action`, {
        method: "POST",
        body: JSON.stringify({ action: action }),
      });
      if (res && res.message) {
        if (tg && tg.showAlert) tg.showAlert(res.message);
        searchAdminUsers();
        await loadStories();
      }
      return res;
    } catch (e) {
      console.error("Admin user action error:", e);
    }
  };

  async function loadAdminReports() {
    const container = document.getElementById("adminReportsList");
    if (!container) return;
    container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);">Загрузка жалоб...</div>';

    try {
      const data = await apiFetch("/api/webapp/admin/reports");
      if (!data || !data.reports || data.reports.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);">🎉 Нет активных жалоб</div>';
        return;
      }

      container.innerHTML = data.reports
        .map((r) => `
          <div class="admin-report-card">
            <div class="admin-report-header">🚩 Жалоба от ${escapeHtml(r.reporter_name)} (ID ${r.reporter_id})</div>
            <div class="admin-report-text">
              <b>На кого:</b> ${escapeHtml(r.reported_name)} (ID ${r.reported_id})<br/>
              <b>Причина:</b> ${escapeHtml(r.reason)}<br/>
              <span style="font-size:11px;color:var(--text-muted);">${r.created_at}</span>
            </div>
            <div style="display:flex;gap:8px;">
              <button class="btn-primary" style="background:#E84118;padding:8px 12px;font-size:12px;" onclick="window.resolveReport('${r.id}', 'ban_reported')">
                🚫 Забанить нарушителя
              </button>
              <button class="btn-secondary" style="padding:8px 12px;font-size:12px;" onclick="window.resolveReport('${r.id}', 'dismiss')">
                ✓ Отклонить
              </button>
            </div>
          </div>
        `)
        .join("");
    } catch (e) {
      container.innerHTML = '<div style="text-align:center;padding:20px;color:red;">Ошибка загрузки</div>';
    }
  }

  window.resolveReport = async function (reportId, action) {
    triggerHaptic("heavy");
    try {
      await apiFetch(`/api/webapp/admin/reports/${reportId}/resolve`, {
        method: "POST",
        body: JSON.stringify({ action: action }),
      });
      loadAdminReports();
    } catch (e) {
      console.error("Resolve report error:", e);
    }
  };

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // ─── Onboarding Flow Controller (Figma Design System) ──────
  let currentOnboardingSlide = 0;
  const totalOnboardingSlides = 3;
  const onboardingScreen = document.getElementById("onboardingScreen");
  const onboardingNextBtn = document.getElementById("onboardingNextBtn");
  const onboardingSkipBtn = document.getElementById("onboardingSkipBtn");
  const onboardingCloseBtn = document.getElementById("onboardingCloseBtn");

  function setOnboardingSlide(idx) {
    currentOnboardingSlide = Math.max(0, Math.min(idx, totalOnboardingSlides - 1));
    const slides = document.querySelectorAll(".onboarding-slide");
    const dots = document.querySelectorAll(".onboarding-dot");
    slides.forEach((s, i) => {
      s.classList.toggle("active", i === currentOnboardingSlide);
    });
    dots.forEach((d, i) => {
      d.classList.toggle("active", i === currentOnboardingSlide);
    });
    if (onboardingNextBtn) {
      if (currentOnboardingSlide === totalOnboardingSlides - 1) {
        onboardingNextBtn.innerHTML = "🎁 Забрать 2 месяца и начать!";
      } else {
        onboardingNextBtn.innerHTML = "Далее →";
      }
    }
  }

  function openOnboarding(force = false) {
    if (!onboardingScreen) return;
    if (!force && localStorage.getItem("studmatch_onboarded") === "1") {
      return;
    }
    setOnboardingSlide(0);
    onboardingScreen.classList.add("active");
    triggerHaptic("light");
  }

  function closeOnboarding() {
    if (!onboardingScreen) return;
    localStorage.setItem("studmatch_onboarded", "1");
    triggerHaptic("success");
    onboardingScreen.classList.remove("active");
  }

  onboardingNextBtn?.addEventListener("click", () => {
    triggerHaptic("light");
    if (currentOnboardingSlide < totalOnboardingSlides - 1) {
      setOnboardingSlide(currentOnboardingSlide + 1);
    } else {
      closeOnboarding();
    }
  });

  onboardingSkipBtn?.addEventListener("click", () => {
    closeOnboarding();
  });

  onboardingCloseBtn?.addEventListener("click", () => {
    closeOnboarding();
  });

  // Touch swipe gestures for onboarding
  let touchStartX = 0;
  let touchEndX = 0;
  onboardingScreen?.addEventListener("touchstart", (e) => {
    if (e.changedTouches && e.changedTouches.length > 0) {
      touchStartX = e.changedTouches[0].screenX;
    }
  }, { passive: true });
  onboardingScreen?.addEventListener("touchend", (e) => {
    if (e.changedTouches && e.changedTouches.length > 0) {
      touchEndX = e.changedTouches[0].screenX;
      const diffX = touchEndX - touchStartX;
      if (diffX < -50 && currentOnboardingSlide < totalOnboardingSlides - 1) {
        setOnboardingSlide(currentOnboardingSlide + 1);
      } else if (diffX > 50 && currentOnboardingSlide > 0) {
        setOnboardingSlide(currentOnboardingSlide - 1);
      }
    }
  }, { passive: true });

  // ─── StudMatch Career Networking Controller ───
  let careerActiveCategory = "all";
  let careerSearchQuery = "";
  let careerSearchTimeout = null;

  async function loadCareerFeed() {
    const feedContainer = document.getElementById("careerFeedList");
    if (!feedContainer) return;

    feedContainer.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 20px;color:var(--text-muted);">
        <div style="font-size:36px;margin-bottom:12px;animation:figmaHeartPulse 1s infinite;">💼</div>
        <div style="font-size:14px;font-weight:600;color:#2563EB;">Загрузка ленты StudMatch...</div>
      </div>
    `;

    try {
      let url = `/api/webapp/career/feed?category=${encodeURIComponent(careerActiveCategory)}`;
      if (careerSearchQuery.trim()) {
        url += `&q=${encodeURIComponent(careerSearchQuery.trim())}`;
      }

      const res = await apiFetch(url);
      if (!res || !res.candidates || res.candidates.length === 0) {
        feedContainer.innerHTML = `
          <div class="career-empty-state">
            <div class="career-empty-icon">🔍</div>
            <h3 class="career-empty-title">Специалисты не найдены</h3>
            <p class="career-empty-desc">
              Попробуйте выбрать другую категорию или очистить поисковый запрос.
            </p>
            <button class="btn-primary" id="resetCareerFiltersBtn" style="background:#2563EB;margin-top:10px;width:auto;padding:10px 20px;">
              🔄 Показать всех специалистов
            </button>
          </div>
        `;
        document.getElementById("resetCareerFiltersBtn")?.addEventListener("click", () => {
          careerActiveCategory = "all";
          careerSearchQuery = "";
          const searchInput = document.getElementById("careerSearchInput");
          if (searchInput) searchInput.value = "";
          document.querySelectorAll(".career-category-chip").forEach((c) => {
            c.classList.toggle("active", c.dataset.category === "all");
          });
          loadCareerFeed();
        });
        return;
      }

      feedContainer.innerHTML = "";
      res.candidates.forEach((cand) => {
        const card = renderCareerCard(cand);
        feedContainer.appendChild(card);
      });
    } catch (e) {
      console.error("[StudMatch] Career feed error:", e);
      feedContainer.innerHTML = `
        <div class="career-empty-state">
          <div class="career-empty-icon">⚠️</div>
          <h3 class="career-empty-title">Ошибка загрузки ленты</h3>
          <p class="career-empty-desc">Не удалось связаться с сервером. Попробуйте еще раз.</p>
          <button class="btn-primary" id="retryCareerFeedBtn" style="background:#2563EB;margin-top:10px;width:auto;padding:10px 20px;">
            🔄 Повторить
          </button>
        </div>
      `;
      document.getElementById("retryCareerFeedBtn")?.addEventListener("click", () => loadCareerFeed());
    }
  }

  function renderCareerCard(cand) {
    const card = document.createElement("div");
    card.className = "career-card";
    card.dataset.userId = cand.user_id;

    const bannerUrl = cand.photos && cand.photos.length > 1 ? cand.photos[1] : (cand.avatar_url || cand.photos[0]);
    const skillsHtml = (cand.career_skills || []).map((s) => 
      `<span class="career-skill-chip">#${escapeHtml(s)}</span>`
    ).join("");

    const portfolioHtml = cand.career_portfolio_url ? `
      <a href="${escapeHtml(cand.career_portfolio_url)}" target="_blank" rel="noopener noreferrer" class="career-portfolio-link">
        🔗 Резюме / Портфолио →
      </a>
    ` : "";

    let connectBtnHtml = "";
    if (cand.is_connected) {
      connectBtnHtml = `
        <button class="btn-career-connect connected" disabled>
          🤝 Взаимный контакт ✓
        </button>
      `;
    } else if (cand.is_pending) {
      connectBtnHtml = `
        <button class="btn-career-connect pending" disabled>
          💼 Запрос отправлен ✓
        </button>
      `;
    } else {
      connectBtnHtml = `
        <button class="btn-career-connect" data-user-id="${cand.user_id}">
          💼 Предложить проект
        </button>
      `;
    }

    card.innerHTML = `
      <div class="career-card-header">
        <div class="career-card-author">
          <img src="${escapeHtml(cand.avatar_url)}" class="career-card-avatar" alt="${escapeHtml(cand.name)}" onerror="this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80'" />
          <div>
            <div class="career-card-name">
              ${escapeHtml(cand.name)}
              ${cand.is_verified ? '<span class="career-badge-verified" title="Верифицирован">🎓</span>' : ''}
              ${cand.is_premium ? '<span title="Premium">💎</span>' : ''}
            </div>
            <div class="career-card-meta">
              ${escapeHtml(cand.university || "Студент")} ${cand.year ? `• ${cand.year} курс` : ''}
            </div>
          </div>
        </div>
        <span class="career-badge-format">${escapeHtml(cand.career_work_format || "Удалённо")}</span>
      </div>

      ${bannerUrl ? `<img src="${escapeHtml(bannerUrl)}" class="career-card-banner" alt="Portfolio" loading="lazy" />` : ''}

      <div class="career-card-body">
        <div class="career-card-goal">${escapeHtml(cand.career_goal)}</div>
        ${skillsHtml ? `<div class="career-skills-chips">${skillsHtml}</div>` : ''}
        ${portfolioHtml}
      </div>

      <div class="career-card-actions">
        ${connectBtnHtml}
        <button class="btn-career-details" data-user-id="${cand.user_id}">
          📄 Анкета
        </button>
      </div>
    `;

    // Connect button click handler
    const connectBtn = card.querySelector(".btn-career-connect:not(.connected):not(.pending)");
    connectBtn?.addEventListener("click", () => sendCareerConnect(cand.user_id, connectBtn));

    // Full profile modal click handlers
    const detailsBtn = card.querySelector(".btn-career-details");
    detailsBtn?.addEventListener("click", () => {
      openMatchFullProfile(cand.user_id);
    });

    const bannerImg = card.querySelector(".career-card-banner");
    bannerImg?.addEventListener("click", () => {
      openMatchFullProfile(cand.user_id);
    });

    return card;
  }

  async function sendCareerConnect(targetUserId, btn) {
    triggerHaptic("medium");
    if (!btn) return;

    btn.disabled = true;
    btn.innerHTML = `⏳ Отправка...`;

    try {
      const res = await apiFetch("/api/webapp/swipe", {
        method: "POST",
        body: JSON.stringify({
          target_id: targetUserId,
          action: "like",
          comment: "Предложил проект в StudMatch 💼",
        }),
      });

      if (res && res.status === "ok") {
        triggerHaptic("success");
        if (res.match) {
          btn.className = "btn-career-connect connected";
          btn.innerHTML = "🤝 Взаимный контакт! Написать";
          btn.disabled = false;
          btn.onclick = () => openChatWith(res.match);
          showMatchPopup(res.match);
        } else {
          btn.className = "btn-career-connect pending";
          btn.innerHTML = "💼 Запрос отправлен ✓";
        }
      } else {
        btn.disabled = false;
        btn.innerHTML = "💼 Предложить проект";
      }
    } catch (e) {
      console.error("[StudMatch] Connect error:", e);
      btn.disabled = false;
      btn.innerHTML = "💼 Предложить проект";
    }
  }

  function setupCareerListeners() {
    // 1. Category chips
    document.querySelectorAll(".career-category-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        triggerHaptic("light");
        document.querySelectorAll(".career-category-chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        careerActiveCategory = chip.dataset.category || "all";
        loadCareerFeed();
      });
    });

    // 2. Search input with debounce
    const searchInput = document.getElementById("careerSearchInput");
    const clearBtn = document.getElementById("careerSearchClearBtn");

    searchInput?.addEventListener("input", (e) => {
      const val = e.target.value;
      if (clearBtn) clearBtn.style.display = val ? "block" : "none";
      if (careerSearchTimeout) clearTimeout(careerSearchTimeout);
      careerSearchTimeout = setTimeout(() => {
        careerSearchQuery = val;
        loadCareerFeed();
      }, 350);
    });

    clearBtn?.addEventListener("click", () => {
      if (searchInput) searchInput.value = "";
      clearBtn.style.display = "none";
      careerSearchQuery = "";
      loadCareerFeed();
    });

    // 3. Filter button
    document.getElementById("careerFilterBtn")?.addEventListener("click", () => {
      triggerHaptic("light");
      openFiltersModal();
    });

    // 4. Composer card tap -> open career profile edit modal
    document.getElementById("careerComposerCard")?.addEventListener("click", () => {
      triggerHaptic("light");
      openCareerEditModal();
    });

    // 5. Career edit modal close and save
    document.getElementById("careerEditCloseBtn")?.addEventListener("click", () => {
      document.getElementById("careerEditModal")?.classList.remove("active");
    });

    document.getElementById("careerSaveBtn")?.addEventListener("click", saveCareerProfile);

    // 6. Subnav toggle buttons (Swipes vs Feed)
    document.getElementById("btnCareerSubnavSwipe")?.addEventListener("click", () => {
      setCareerSubnavView("swipe");
    });
    document.getElementById("btnCareerSubnavFeed")?.addEventListener("click", () => {
      setCareerSubnavView("feed");
    });
  }

  function openCareerEditModal() {
    const modal = document.getElementById("careerEditModal");
    if (!modal) return;

    const u = state.currentUser;
    const goalInput = document.getElementById("careerInputGoal");
    const skillsInput = document.getElementById("careerInputSkills");
    const formatInput = document.getElementById("careerInputFormat");
    const portfolioInput = document.getElementById("careerInputPortfolio");

    if (goalInput && u?.career_goal) goalInput.value = u.career_goal;
    if (skillsInput && u?.career_custom_skills) skillsInput.value = u.career_custom_skills;
    if (formatInput && u?.career_work_format) formatInput.value = u.career_work_format;
    if (portfolioInput && u?.career_portfolio_url) portfolioInput.value = u.career_portfolio_url;

    modal.classList.add("active");
  }

  async function saveCareerProfile() {
    const saveBtn = document.getElementById("careerSaveBtn");
    const goal = document.getElementById("careerInputGoal")?.value || "";
    const skills = document.getElementById("careerInputSkills")?.value || "";
    const format = document.getElementById("careerInputFormat")?.value || "Удалённо";
    const portfolio = document.getElementById("careerInputPortfolio")?.value || "";

    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.innerHTML = "⏳ Сохранение...";
    }

    try {
      const res = await apiFetch("/api/webapp/profile/career", {
        method: "POST",
        body: JSON.stringify({
          career_goal: goal,
          career_custom_skills: skills,
          career_work_format: format,
          career_portfolio_url: portfolio,
        }),
      });

      if (res && res.status === "ok") {
        triggerHaptic("success");
        if (state.currentUser) {
          state.currentUser.career_goal = goal;
          state.currentUser.career_custom_skills = skills;
          state.currentUser.career_work_format = format;
          state.currentUser.career_portfolio_url = portfolio;
          state.currentUser.career_is_complete = true;
        }
        document.getElementById("careerEditModal")?.classList.remove("active");
        loadCareerFeed();
      }
    } catch (e) {
      console.error("[StudMatch] Save career error:", e);
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.innerHTML = "💾 Сохранить в StudMatch";
      }
    }
  }

  // ─── Hall of Fame (Зал Славы) Logic ─────────────────────────
  let hallOfFameScope = "all"; // 'all' | 'university'
  let hallOfFameData = null;

  function openHallOfFame() {
    triggerHaptic("medium");
    const modal = document.getElementById("hallOfFameModal");
    if (modal) {
      modal.classList.add("active");
      loadHallOfFame(hallOfFameScope);
    }
  }

  function closeHallOfFame() {
    triggerHaptic("light");
    const modal = document.getElementById("hallOfFameModal");
    if (modal) {
      modal.classList.remove("active");
    }
  }

  async function loadHallOfFame(scope = "all") {
    hallOfFameScope = scope;
    
    // Update tabs UI
    const tabAll = document.getElementById("hallTabAll");
    const tabUniv = document.getElementById("hallTabUniv");
    if (tabAll && tabUniv) {
      if (scope === "all") {
        tabAll.classList.add("active");
        tabUniv.classList.remove("active");
      } else {
        tabUniv.classList.add("active");
        tabAll.classList.remove("active");
      }
    }

    const podium = document.getElementById("hallPodiumContainer");
    const list = document.getElementById("hallListContainer");
    const listSection = document.getElementById("hallListSection");
    const emptyState = document.getElementById("hallEmptyState");

    if (podium) podium.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 24px; color: var(--text-muted); font-size: 13px;">Загрузка рейтинга...</div>';
    if (list) list.innerHTML = '';
    if (listSection) listSection.style.display = "flex";
    if (emptyState) emptyState.style.display = "none";

    try {
      const data = await apiFetch(`/api/webapp/hall_of_fame?scope=${scope}`);
      if (!data || data.status !== "ok") {
        if (podium) podium.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 20px; color: var(--text-muted);">Не удалось загрузить Зал Славы</div>';
        return;
      }

      hallOfFameData = data;

      // Update university tab label if available
      const univLabel = document.getElementById("hallTabUnivLabel");
      if (univLabel && data.university_name) {
        univLabel.textContent = `🎓 ${data.university_name}`;
      }

      // Update sticky user position
      const myRankDisplay = document.getElementById("hallMyRankDisplay");
      const myScoreDisplay = document.getElementById("hallMyScoreDisplay");
      if (myRankDisplay) {
        myRankDisplay.textContent = data.my_rank ? `#${data.my_rank}` : "Вне топа";
      }
      if (myScoreDisplay) {
        myScoreDisplay.textContent = `⭐ ${data.my_score || 0} б.`;
      }

      renderHallOfFame(data);
    } catch (err) {
      console.error("[StudMatch] loadHallOfFame error:", err);
      if (podium) podium.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 20px; color: var(--text-muted);">Ошибка подключения к серверу</div>';
    }
  }

  function renderHallOfFame(data) {
    const podium = document.getElementById("hallPodiumContainer");
    const list = document.getElementById("hallListContainer");
    const listSection = document.getElementById("hallListSection");
    const emptyState = document.getElementById("hallEmptyState");
    const listCount = document.getElementById("hallListCount");

    const items = data.leaderboard || [];

    if (items.length === 0) {
      if (podium) podium.innerHTML = '';
      if (list) list.innerHTML = '';
      if (listSection) listSection.style.display = "none";
      if (emptyState) {
        emptyState.style.display = "block";
        const desc = emptyState.querySelector(".hall-empty-desc");
        if (desc) {
          if (!data.has_university) {
            desc.textContent = "Укажите ваш ВУЗ в профиле, чтобы соревноваться с однокурсниками!";
          } else {
            desc.textContent = `В ${data.university_name || 'вашем ВУЗе'} пока нет студентов в рейтинге. Станьте первым!`;
          }
        }
      }
      return;
    }

    if (emptyState) emptyState.style.display = "none";
    if (listSection) listSection.style.display = "flex";

    // Top 3 Podium
    const top1 = items[0] || null;
    const top2 = items[1] || null;
    const top3 = items[2] || null;

    if (podium) {
      // Podium layout: 2nd place (left), 1st place (center), 3rd place (right)
      let html = "";

      // Rank 2
      if (top2) {
        html += renderPodiumCol(top2, 2, "🥈");
      } else {
        html += renderEmptyPodiumCol(2, "🥈");
      }

      // Rank 1
      if (top1) {
        html += renderPodiumCol(top1, 1, "🥇");
      } else {
        html += renderEmptyPodiumCol(1, "🥇");
      }

      // Rank 3
      if (top3) {
        html += renderPodiumCol(top3, 3, "🥉");
      } else {
        html += renderEmptyPodiumCol(3, "🥉");
      }

      podium.innerHTML = html;

      // Add click listeners to podium items
      podium.querySelectorAll(".podium-col[data-user-id]").forEach((el) => {
        el.addEventListener("click", () => {
          const uid = parseInt(el.getAttribute("data-user-id"));
          if (uid) openMatchFullProfile(uid);
        });
      });
    }

    // List for places 4..50
    const restItems = items.slice(3);
    if (listCount) {
      listCount.textContent = `${items.length} студентов`;
    }

    if (list) {
      if (restItems.length === 0) {
        list.innerHTML = '<div style="text-align:center;padding:16px;color:var(--text-muted);font-size:12px;">Пока нет других участников в списке</div>';
      } else {
        list.innerHTML = restItems.map((u) => {
          const verified = u.is_verified ? "🎓" : "";
          const prem = u.is_premium ? "💎" : "";
          const meTag = u.is_me ? '<span class="hall-me-pill">Вы</span>' : "";
          const metaParts = [];
          if (u.university_name) metaParts.push(u.university_name);
          if (u.faculty) metaParts.push(u.faculty);
          if (u.course) metaParts.push(`${u.course} курс`);
          const metaText = metaParts.join(" • ") || "Студент";

          return `
            <div class="hall-card ${u.is_me ? 'is-me' : ''}" data-user-id="${u.user_id}">
              <div class="hall-card-rank">#${u.rank}</div>
              <img src="${escapeHtml(u.avatar_url)}" class="hall-card-avatar" alt="${escapeHtml(u.name)}" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80';" />
              <div class="hall-card-info">
                <div class="hall-card-name-row">
                  <span class="hall-card-name">${escapeHtml(u.name)}${u.age ? `, ${u.age}` : ''} ${verified} ${prem}</span>
                  ${meTag}
                </div>
                <div class="hall-card-meta">${escapeHtml(metaText)}</div>
              </div>
              <div class="hall-card-score">⭐ ${u.rating_score}</div>
            </div>
          `;
        }).join("");

        list.querySelectorAll(".hall-card[data-user-id]").forEach((el) => {
          el.addEventListener("click", () => {
            const uid = parseInt(el.getAttribute("data-user-id"));
            if (uid) openMatchFullProfile(uid);
          });
        });
      }
    }
  }

  function renderPodiumCol(u, rank, medalEmoji) {
    const verified = u.is_verified ? "🎓" : "";
    const prem = u.is_premium ? "💎" : "";
    const metaParts = [];
    if (u.university_name) metaParts.push(u.university_name);
    else if (u.faculty) metaParts.push(u.faculty);
    const metaText = metaParts.join(" • ") || (u.course ? `${u.course} курс` : "");

    return `
      <div class="podium-col rank-${rank}" data-user-id="${u.user_id}">
        <div class="podium-avatar-wrap">
          <img src="${escapeHtml(u.avatar_url)}" class="podium-avatar" alt="${escapeHtml(u.name)}" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=200&q=80';" />
          <div class="podium-medal">${medalEmoji}</div>
        </div>
        <div class="podium-name">${escapeHtml(u.name)} ${verified}${prem}</div>
        <div class="podium-meta">${escapeHtml(metaText)}</div>
        <div class="podium-score">⭐ ${u.rating_score} б.</div>
        <div class="podium-pedestal">${rank}</div>
      </div>
    `;
  }

  function renderEmptyPodiumCol(rank, medalEmoji) {
    return `
      <div class="podium-col rank-${rank}" style="opacity: 0.45; pointer-events: none;">
        <div class="podium-avatar-wrap">
          <div class="podium-avatar" style="background:#E2E8F0;display:flex;align-items:center;justify-content:center;color:#94A3B8;font-size:20px;">?</div>
          <div class="podium-medal">${medalEmoji}</div>
        </div>
        <div class="podium-name">—</div>
        <div class="podium-meta">Свободно</div>
        <div class="podium-score">0 б.</div>
        <div class="podium-pedestal">${rank}</div>
      </div>
    `;
  }

  function setupHallOfFameListeners() {
    const openBtn = document.getElementById("openHallOfFameBtn");
    const closeBtn = document.getElementById("closeHallOfFameBtn");
    const tabAll = document.getElementById("hallTabAll");
    const tabUniv = document.getElementById("hallTabUniv");
    const boostBtn = document.getElementById("openRatingInfoBtn");
    const ratingModal = document.getElementById("ratingInfoModal");
    const closeRatingBtn = document.getElementById("closeRatingInfoBtn");

    if (openBtn) {
      openBtn.addEventListener("click", () => openHallOfFame());
    }
    if (closeBtn) {
      closeBtn.addEventListener("click", () => closeHallOfFame());
    }
    if (tabAll) {
      tabAll.addEventListener("click", () => {
        triggerHaptic("light");
        loadHallOfFame("all");
      });
    }
    if (tabUniv) {
      tabUniv.addEventListener("click", () => {
        triggerHaptic("light");
        loadHallOfFame("university");
      });
    }
    if (boostBtn) {
      boostBtn.addEventListener("click", () => {
        triggerHaptic("medium");
        if (ratingModal) ratingModal.style.display = "flex";
      });
    }
    if (closeRatingBtn) {
      closeRatingBtn.addEventListener("click", () => {
        triggerHaptic("light");
        if (ratingModal) ratingModal.style.display = "none";
      });
    }
    if (ratingModal) {
      ratingModal.addEventListener("click", (e) => {
        if (e.target === ratingModal) {
          ratingModal.style.display = "none";
        }
      });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupNavigation();
    setupCareerListeners();
    setupMaintenanceListeners();
    setupHallOfFameListeners();
    if (window.MAINTENANCE_DATA) {
      updateMaintenanceUI(window.MAINTENANCE_DATA);
    }
    authenticateUser();
  });
})();
