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
  const chatScreenModal = document.getElementById("chatScreenModal");
  let currentChatMatchId = null;
  let currentChatPartner = null;

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
        if (type === "success" || type === "warning" || type === "error") {
          tg.HapticFeedback.notificationOccurred(type);
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
    if (!(options.body instanceof FormData) && !options.headers["Content-Type"]) {
      options.headers["Content-Type"] = "application/json";
    }

    const res = await fetch(url, options);
    if (res.status === 401) {
      console.warn("[StudMatch] Token expired or 401, re-authenticating...");
      await authenticateUser();
      return;
    }
    let data;
    try {
      data = await res.json();
    } catch (e) {
      data = { status: "error", detail: `Ошибка ответа сервера (${res.status})` };
    }
    return data;
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
                if (state.currentUser?.mode) {
                  await setMode(state.currentUser.mode, false);
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
                fetchInitialBadges();
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
        if (state.currentUser?.mode) {
          await setMode(state.currentUser.mode, false);
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
        fetchInitialBadges();
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
    const curMode = state.currentUser?.mode || "dating";
    document.getElementById("pillDating")?.classList.toggle("active", curMode === "dating");
    document.getElementById("pillCareer")?.classList.toggle("active", curMode === "career");
    document.getElementById("pillProjects")?.classList.toggle("active", curMode === "projects");
    document.body.classList.toggle("career-theme", curMode === "career");
    document.body.classList.toggle("projects-theme", curMode === "projects");
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
    document.getElementById("pillProjects")?.addEventListener("click", () => setMode("projects"));

    // Кнопка открытия фильтров в шапке
    const openFiltersBtn = document.getElementById("openFiltersBtn");
    if (openFiltersBtn) {
      openFiltersBtn.addEventListener("click", openFiltersModal);
    }

    // Кнопки в Empty State колоды
    document.getElementById("resetSwipesDeckBtn")?.addEventListener("click", resetSwipesAndReload);
    document.getElementById("changeFiltersDeckBtn")?.addEventListener("click", openFiltersModal);

    setupModalListeners();
    setupAdminListeners();
    setupSupportListeners();
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

      // Клик по своей истории (открывает профиль)
      document.getElementById("myStoryItem")?.addEventListener("click", () => {
        triggerHaptic("medium");
        switchTab("profile");
      });

      // Клик по анкетам других пользователей
      row.querySelectorAll(".story-item[data-user-id]").forEach((item) => {
        item.addEventListener("click", () => {
          const uid = item.dataset.userId;
          if (uid) {
            triggerHaptic("light");
            openDetailsSheet(uid, { source: "story" });
          }
        });
      });
    } catch (e) {
      console.warn("[StudMatch] Failed to load stories:", e);
    }
  }

  function parseRolesList(roles) {
    if (Array.isArray(roles)) {
      return roles.map((r) => String(r).trim()).filter(Boolean);
    }
    if (typeof roles === "string") {
      return roles.split(",").map((r) => r.trim()).filter(Boolean);
    }
    return [];
  }

  function showAppToast(message, duration = 3000) {
    let toast = document.getElementById("appGlobalToast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "appGlobalToast";
      toast.className = "app-toast";
      document.body.appendChild(toast);
    }

    let displayMsg = message;
    if (typeof message === "object" && message !== null) {
      if (Array.isArray(message)) {
        displayMsg = message.map((m) => {
          if (typeof m === "object" && m !== null) {
            const field = m.loc && m.loc.length ? `(${m.loc[m.loc.length - 1]}): ` : "";
            return `${field}${m.msg || m.message || JSON.stringify(m)}`;
          }
          return String(m);
        }).join("; ");
      } else if (message.detail) {
        if (Array.isArray(message.detail)) {
          displayMsg = message.detail.map((m) => {
            if (typeof m === "object" && m !== null) {
              const field = m.loc && m.loc.length ? `(${m.loc[m.loc.length - 1]}): ` : "";
              return `${field}${m.msg || m.message || JSON.stringify(m)}`;
            }
            return String(m);
          }).join("; ");
        } else {
          displayMsg = String(message.detail);
        }
      } else if (message.msg || message.message) {
        displayMsg = message.msg || message.message;
      } else {
        displayMsg = JSON.stringify(message);
      }
    }

    toast.textContent = displayMsg || "Произошла ошибка";
    toast.classList.add("visible");
    triggerHaptic("success");

    if (window._appToastTimeout) {
      clearTimeout(window._appToastTimeout);
    }
    window._appToastTimeout = setTimeout(() => {
      toast.classList.remove("visible");
    }, duration);
  }

  function openTelegramContact(username) {
    if (!username) return;
    const clean = username.replace(/^@/, "").trim();
    if (!clean) return;
    const url = `https://t.me/${clean}`;
    if (tg && tg.openTelegramLink) {
      tg.openTelegramLink(url);
    } else if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.openTelegramLink) {
      window.Telegram.WebApp.openTelegramLink(url);
    } else {
      window.open(url, "_blank");
    }
  }
  window.openTelegramContact = openTelegramContact;

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
      showAppToast("🔄 История свайпов сброшена! Ваши мэтчи и чаты сохранены");
    } catch (e) {
      console.error("Reset swipes error:", e);
      showAppToast("🔄 История свайпов сброшена! Ваши мэтчи и чаты сохранены");
    }
  }

  function updateNavBadges(counts = {}) {
    const likesBadge = document.getElementById("navLikesBadge");
    const matchesBadge = document.getElementById("navMatchesBadge");

    if (likesBadge && counts.likes !== undefined) {
      if (counts.likes > 0) {
        likesBadge.textContent = counts.likes > 99 ? "99+" : counts.likes;
        likesBadge.style.display = "flex";
      } else {
        likesBadge.style.display = "none";
      }
    }

    if (matchesBadge && counts.matches !== undefined) {
      if (counts.matches > 0) {
        matchesBadge.textContent = counts.matches > 99 ? "99+" : counts.matches;
        matchesBadge.style.display = "flex";
      } else {
        matchesBadge.style.display = "none";
      }
    }
  }

  async function fetchInitialBadges() {
    try {
      const [likesData, matchesData] = await Promise.allSettled([
        apiFetch("/api/webapp/incoming_likes"),
        apiFetch("/api/webapp/matches"),
      ]);

      let likesCount = 0;
      if (likesData.status === "fulfilled" && likesData.value) {
        likesCount = likesData.value.count || (likesData.value.likes ? likesData.value.likes.length : 0);
      }

      let matchesCount = 0;
      if (matchesData.status === "fulfilled" && matchesData.value && matchesData.value.matches) {
        matchesCount = matchesData.value.matches.reduce((sum, m) => sum + (m.unread_count || 0), 0);
      }

      updateNavBadges({ likes: likesCount, matches: matchesCount });
    } catch (e) {
      console.warn("Could not load initial badges:", e);
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

  let currentCareerView = "swipe";

  function setCareerSubnavView(view) {
    currentCareerView = view;
    triggerHaptic("light");
    document.getElementById("btnCareerSubnavSwipe")?.classList.toggle("active", view === "swipe");
    document.getElementById("btnCareerSubnavFeed")?.classList.toggle("active", view === "feed");

    const deckWrapper = document.querySelector(".deck-container");
    const careerView = document.getElementById("careerFeedView");
    const projectsFeedView = document.getElementById("projectsFeedView");
    const projectsMyView = document.getElementById("projectsMyView");
    const exploreScreen = document.getElementById("screen-explore");

    if (projectsFeedView) projectsFeedView.style.display = "none";
    if (projectsMyView) projectsMyView.style.display = "none";

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

  let currentProjectsView = "swipe";

  function setProjectsSubnavView(view) {
    currentProjectsView = view;
    triggerHaptic("light");
    document.getElementById("btnProjectsSubnavSwipe")?.classList.toggle("active", view === "swipe");
    document.getElementById("btnProjectsSubnavFeed")?.classList.toggle("active", view === "feed");
    document.getElementById("btnProjectsSubnavMy")?.classList.toggle("active", view === "my");

    const deckWrapper = document.querySelector(".deck-container");
    const careerView = document.getElementById("careerFeedView");
    const projectsFeedView = document.getElementById("projectsFeedView");
    const projectsMyView = document.getElementById("projectsMyView");
    const exploreScreen = document.getElementById("screen-explore");

    if (careerView) careerView.style.display = "none";

    if (view === "swipe") {
      document.body.classList.remove("feed-view-active");
      if (deckWrapper) deckWrapper.style.display = "flex";
      if (projectsFeedView) projectsFeedView.style.display = "none";
      if (projectsMyView) projectsMyView.style.display = "none";
      if (exploreScreen) exploreScreen.style.overflowY = "hidden";
      state.feed = [];
      state.currentCardIndex = 0;
      loadFeed();
    } else if (view === "feed") {
      document.body.classList.add("feed-view-active");
      if (deckWrapper) deckWrapper.style.display = "none";
      if (projectsFeedView) projectsFeedView.style.display = "block";
      if (projectsMyView) projectsMyView.style.display = "none";
      if (exploreScreen) {
        exploreScreen.style.overflowY = "auto";
        exploreScreen.style.webkitOverflowScrolling = "touch";
      }
      loadProjectsFeed();
    } else if (view === "my") {
      document.body.classList.add("feed-view-active");
      if (deckWrapper) deckWrapper.style.display = "none";
      if (projectsFeedView) projectsFeedView.style.display = "none";
      if (projectsMyView) projectsMyView.style.display = "block";
      if (exploreScreen) {
        exploreScreen.style.overflowY = "auto";
        exploreScreen.style.webkitOverflowScrolling = "touch";
      }
      loadMyProjects();
    }
  }

  async function setMode(targetMode, syncServer = true) {
    if (!["dating", "career", "projects"].includes(targetMode)) {
      targetMode = "dating";
    }

    try {
      localStorage.setItem("studmatch_mode", targetMode);
    } catch (e) {}

    // 1. Мгновенное визуальное переключение пилюль (Optimistic UI)
    document.getElementById("pillDating")?.classList.toggle("active", targetMode === "dating");
    document.getElementById("pillCareer")?.classList.toggle("active", targetMode === "career");
    document.getElementById("pillProjects")?.classList.toggle("active", targetMode === "projects");
    if (syncServer) {
      triggerHaptic("medium");
    }

    if (state.currentUser) {
      state.currentUser.mode = targetMode;
    }

    // Мгновенное обновление текста и иконки режима в профиле
    const modeLabel = document.getElementById("profileModeLabel");
    if (modeLabel) {
      if (targetMode === "career") modeLabel.textContent = "💼 Карьера";
      else if (targetMode === "projects") modeLabel.textContent = "💡 Проекты";
      else modeLabel.textContent = "💘 Знакомства";
    }
    const modeStat = document.getElementById("profileModeStat");
    if (modeStat) {
      if (targetMode === "career") modeStat.textContent = "💼";
      else if (targetMode === "projects") modeStat.textContent = "💡";
      else modeStat.textContent = "💘";
    }

    const brandTitle = document.querySelector(".header-brand .brand-title");
    const careerSubnav = document.getElementById("careerSubnavToggle");
    const projectsSubnav = document.getElementById("projectsSubnavToggle");
    const exploreScreen = document.getElementById("screen-explore");
    const deckWrapper = document.querySelector(".deck-container");
    const careerView = document.getElementById("careerFeedView");
    const projectsFeedView = document.getElementById("projectsFeedView");
    const projectsMyView = document.getElementById("projectsMyView");

    if (targetMode === "career") {
      document.body.classList.add("career-theme");
      document.body.classList.remove("projects-theme");
      if (brandTitle) brandTitle.textContent = "StudMatch";
      if (careerSubnav) careerSubnav.style.display = "flex";
      if (projectsSubnav) projectsSubnav.style.display = "none";
      if (projectsFeedView) projectsFeedView.style.display = "none";
      if (projectsMyView) projectsMyView.style.display = "none";
      setCareerSubnavView(currentCareerView || "swipe");
    } else if (targetMode === "projects") {
      document.body.classList.add("projects-theme");
      document.body.classList.remove("career-theme");
      if (brandTitle) brandTitle.textContent = "StudMatch";
      if (careerSubnav) careerSubnav.style.display = "none";
      if (projectsSubnav) projectsSubnav.style.display = "flex";
      if (careerView) careerView.style.display = "none";
      setProjectsSubnavView(currentProjectsView || "swipe");
    } else {
      document.body.classList.remove("career-theme");
      document.body.classList.remove("projects-theme");
      document.body.classList.remove("feed-view-active");
      if (brandTitle) brandTitle.textContent = "StudMatch";
      if (careerSubnav) careerSubnav.style.display = "none";
      if (projectsSubnav) projectsSubnav.style.display = "none";
      if (careerView) careerView.style.display = "none";
      if (projectsFeedView) projectsFeedView.style.display = "none";
      if (projectsMyView) projectsMyView.style.display = "none";
      if (deckWrapper) deckWrapper.style.display = "flex";
      if (exploreScreen) exploreScreen.style.overflowY = "hidden";
      state.feed = [];
      state.currentCardIndex = 0;
      await loadFeed();
    }

    if (syncServer) {
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
  }

  async function toggleMode() {
    if (!state.currentUser) return;
    const modes = ["dating", "career", "projects"];
    const curIdx = modes.indexOf(state.currentUser.mode);
    const nextMode = modes[(curIdx + 1) % modes.length];
    await setMode(nextMode);
  }

  let isFetchingMore = false;

  // 3. Загрузка ленты свайпов (Feed)
  async function loadFeed() {
    try {
      console.log("[StudMatch] Loading feed profiles/projects...");
      const isProjectsMode = state.currentUser?.mode === "projects";
      const feedUrl = isProjectsMode ? "/api/webapp/projects/feed" : "/api/webapp/feed";
      const data = await apiFetch(feedUrl);
      console.log("[StudMatch] Feed received:", data);

      const items = isProjectsMode
        ? (data?.projects || []).map((p) => ({ ...p, is_project: true }))
        : (data?.profiles || []);

      state.feed = items;
      state.currentCardIndex = 0;
      if (state.feed.length === 0) {
        deckEmpty.style.display = "flex";
      } else {
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

  async function fetchMoreCards() {
    if (isFetchingMore) return;
    isFetchingMore = true;
    try {
      console.log("[StudMatch] Prefetching more cards for infinite swipe stream...");
      const isProjectsMode = state.currentUser?.mode === "projects";
      const feedUrl = isProjectsMode ? "/api/webapp/projects/feed" : "/api/webapp/feed";
      const data = await apiFetch(feedUrl);

      const incomingList = isProjectsMode
        ? (data?.projects || []).map((p) => ({ ...p, is_project: true }))
        : (data?.profiles || []);

      if (Array.isArray(incomingList) && incomingList.length > 0) {
        // Отрезаем уже свайпнутые карточки для экономии памяти
        const remaining = state.feed.slice(state.currentCardIndex);
        const remainingIds = new Set(remaining.map((p) => (p.is_project ? p.id : p.user_id)));

        // Добавляем только новые карточки, которых еще нет в остатке колоды
        const freshProfiles = incomingList.filter((p) => !remainingIds.has(p.is_project ? p.id : p.user_id));

        if (freshProfiles.length > 0) {
          state.feed = remaining.concat(freshProfiles);
          state.currentCardIndex = 0;
          renderCardStack();
        } else if (remaining.length === 0) {
          // Если колода была пуста (например, при малом пуле анкет 1-2 человека)
          state.feed = incomingList;
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
    visibleCards.forEach((item, index) => {
      const isTop = index === visibleCards.length - 1;
      const cardEl = (item.is_project || state.currentUser?.mode === "projects")
        ? createProjectCardElement(item, isTop)
        : createCardElement(item, isTop);
      deckContainer.appendChild(cardEl);

      if (isTop) {
        initCardDrag(cardEl, item);
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

    const photosMeta = profile.photos_meta || photos.map((p, i) => ({ url: p, is_private: false, index: i }));

    card.innerHTML = `
      ${barsHtml}
      <img src="${photos[0]}" class="card-photo-bg" alt="${escapeHtml(profile.name)}" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />
      <div class="photo-private-overlay" style="display: none;">
        <div class="photo-private-lock-icon">🔒</div>
        <div class="photo-private-text">Фото скрыто автором</div>
        <div class="photo-private-subtext">Станет доступно после взаимного мэтча</div>
      </div>
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

        <!-- Authentic Figma Action Buttons (Reference Matched) -->
        <div class="card-actions-row">
          <button class="action-btn dislike" data-action="skip" title="Пропустить">
            <svg class="action-btn-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#111111" stroke-width="3.5" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
          <button class="action-btn superlike" data-action="superlike" title="Суперлайк">
            <svg class="action-btn-icon" width="28" height="28" viewBox="0 0 24 24" fill="white">
              <path d="M12 2.5L15.09 8.76L22 9.77L17 14.64L18.18 21.5L12 18.25L5.82 21.5L7 14.64L2 9.77L8.91 8.76L12 2.5Z"/>
            </svg>
          </button>
          <button class="action-btn like ${isCareer ? 'career-like' : ''}" data-action="like" title="${isCareer ? 'Предложить проект' : 'Нравится'}">
            ${isCareer 
              ? `<svg class="action-btn-icon" width="22" height="22" viewBox="0 0 24 24" fill="white">
                   <path d="M20 6h-4V4c0-1.11-.89-2-2-2h-4c-1.11 0-2 .89-2 2v2H4c-1.11 0-1.99.89-1.99 2L2 19c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V8c0-1.11-.89-2-2-2zm-6 0h-4V4h4v2z"/>
                 </svg>`
              : `<svg class="action-btn-icon" width="24" height="24" viewBox="0 0 24 24" fill="white">
                   <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
                 </svg>`}
          </button>
        </div>
      </div>
    `;

    // Обработка кликов по левой/правой зоне для переключения фото
    const tapLeft = card.querySelector(".card-tap-left");
    const tapRight = card.querySelector(".card-tap-right");
    const photoImg = card.querySelector(".card-photo-bg");
    const storyBars = card.querySelectorAll(".story-bar");
    const privateOverlay = card.querySelector(".photo-private-overlay");

    const updateCardPhoto = (idx) => {
      const meta = photosMeta[idx] || { is_private: false };
      photoImg.onerror = function() { this.onerror = null; this.src = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"; };
      photoImg.src = photos[idx];
      storyBars.forEach((bar, i) => bar.classList.toggle("active", i <= idx));
      if (meta.is_private) {
        photoImg.classList.add("photo-private");
        if (privateOverlay) privateOverlay.style.display = "flex";
      } else {
        photoImg.classList.remove("photo-private");
        if (privateOverlay) privateOverlay.style.display = "none";
      }
    };

    if (tapLeft && tapRight && photos.length > 1) {
      tapLeft.addEventListener("click", (e) => {
        e.stopPropagation();
        let idx = parseInt(card.dataset.photoIndex || "0", 10);
        if (idx > 0) {
          idx--;
          card.dataset.photoIndex = idx.toString();
          updateCardPhoto(idx);
          triggerHaptic("light");
        }
      });

      tapRight.addEventListener("click", (e) => {
        e.stopPropagation();
        let idx = parseInt(card.dataset.photoIndex || "0", 10);
        if (idx < photos.length - 1) {
          idx++;
          card.dataset.photoIndex = idx.toString();
          updateCardPhoto(idx);
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

    const dislikeBtn = card.querySelector(".action-btn.dislike");
    const superlikeBtn = card.querySelector(".action-btn.superlike");
    const likeBtn = card.querySelector(".action-btn.like");

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

      // Отрисовка штампов и тактильная подсветка кнопок
      if (currentX > 35) {
        likeStamp.style.opacity = Math.min(1, (currentX - 35) / 80);
        nopeStamp.style.opacity = 0;
        superStamp.style.opacity = 0;
        likeBtn?.classList.add("drag-hint-active");
        dislikeBtn?.classList.remove("drag-hint-active");
        superlikeBtn?.classList.remove("drag-hint-active");
      } else if (currentX < -35) {
        nopeStamp.style.opacity = Math.min(1, (-currentX - 35) / 80);
        likeStamp.style.opacity = 0;
        superStamp.style.opacity = 0;
        dislikeBtn?.classList.add("drag-hint-active");
        likeBtn?.classList.remove("drag-hint-active");
        superlikeBtn?.classList.remove("drag-hint-active");
      } else if (currentY < -40 && Math.abs(currentX) < 40) {
        superStamp.style.opacity = Math.min(1, (-currentY - 40) / 70);
        likeStamp.style.opacity = 0;
        nopeStamp.style.opacity = 0;
        superlikeBtn?.classList.add("drag-hint-active");
        likeBtn?.classList.remove("drag-hint-active");
        dislikeBtn?.classList.remove("drag-hint-active");
      } else {
        likeStamp.style.opacity = 0;
        nopeStamp.style.opacity = 0;
        superStamp.style.opacity = 0;
        dislikeBtn?.classList.remove("drag-hint-active");
        superlikeBtn?.classList.remove("drag-hint-active");
        likeBtn?.classList.remove("drag-hint-active");
      }
    }

    function onEnd() {
      if (!isDragging) return;
      isDragging = false;

      dislikeBtn?.classList.remove("drag-hint-active");
      superlikeBtn?.classList.remove("drag-hint-active");
      likeBtn?.classList.remove("drag-hint-active");

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
      if (profile.is_project || state.currentUser?.mode === "projects") {
        sendProjectSwipe(profile.id, action, comment, profile);
      } else {
        sendSwipe(profile.user_id, action, comment, profile);
      }

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

  const pendingSwipeIds = new Set();

  async function sendSwipe(targetId, action, comment = null, candidate = null) {
    if (pendingSwipeIds.has(targetId)) {
      console.warn("⚠️ Swipe already in flight for candidate:", targetId);
      return;
    }
    pendingSwipeIds.add(targetId);
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
    } finally {
      pendingSwipeIds.delete(targetId);
    }
  }

  async function sendProjectSwipe(projectId, action, comment = null, project = null) {
    const key = `proj_${projectId}`;
    if (pendingSwipeIds.has(key)) {
      console.warn("⚠️ Project swipe already in flight:", projectId);
      return;
    }
    pendingSwipeIds.add(key);
    try {
      const res = await apiFetch("/api/webapp/projects/swipe", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId, action: action, comment: comment }),
      });
      if (res && res.is_match) {
        showMatchPopup(
          {
            name: project?.founder?.name || "Фаундер стартапа",
            photos: [project?.founder?.avatar_url],
            match_id: res.match?.id || res.match?.match_id,
          },
          project
        );
      }
    } catch (e) {
      console.error("Project swipe error:", e);
    } finally {
      pendingSwipeIds.delete(key);
    }
  }

  function handleProjectSwipeAction(project, action, comment = null) {
    if (state.isSwiping) return;
    const topCard = deckContainer.querySelector(".swipe-card:last-child");
    if (!topCard) return;

    if (action === "like") {
      finishSwipe(topCard, project, "like", 500, 0);
    } else if (action === "superlike") {
      finishSwipe(topCard, project, "superlike", 0, -600, comment);
    } else {
      finishSwipe(topCard, project, "skip", -500, 0);
    }
  }

  function createProjectCardElement(project, isTop) {
    const card = document.createElement("div");
    card.className = "swipe-card project-card-swipe";
    card.dataset.projectId = project.id;
    card.dataset.userId = "proj_" + project.id;

    const stageMap = {
      idea: { label: "💡 Идея", cls: "stage-idea" },
      mvp: { label: "🛠 MVP", cls: "stage-mvp" },
      launched: { label: "🚀 Запущен", cls: "stage-launched" },
      hackathon: { label: "🏆 Хакатон", cls: "stage-hackathon" },
    };
    const stageInfo = stageMap[project.stage] || { label: "💡 Проект", cls: "stage-idea" };
    const coverUrl = project.cover_url || "/static/webapp/assets/mascot_hero_3d.jpg?v=20260904_29";

    const rolesList = parseRolesList(project.required_roles);
    const rolesHtml = rolesList.length > 0
      ? `<div class="project-roles-tags" style="margin:6px 0;">
           ${rolesList.slice(0, 4).map((r) => `<span class="project-role-tag">#${escapeHtml(r)}</span>`).join("")}
         </div>`
      : "";

    const founder = project.founder || {};
    const founderAvatar = founder.avatar_url || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80";
    const founderUni = [founder.university, founder.year ? `${founder.year} курс` : ""].filter(Boolean).join(" • ");

    card.innerHTML = `
      <img src="${escapeHtml(coverUrl)}" class="card-photo-bg" alt="${escapeHtml(project.title)}" onerror="this.onerror=null;this.src='/static/webapp/assets/mascot_hero_3d.jpg';" />
      <div class="card-gradient-overlay" style="background: linear-gradient(180deg, rgba(15,23,42,0.1) 0%, rgba(15,23,42,0.85) 60%, rgba(15,23,42,0.98) 100%);"></div>

      <div class="stamp like-stamp" style="border-color:#F59E0B;color:#F59E0B;">В КОМАНДУ</div>
      <div class="stamp nope-stamp">SKIP</div>
      <div class="stamp super-stamp" style="border-color:#D97706;color:#D97706;">ПИТЧ</div>

      <div class="card-top-bar" style="margin-top: 10px;">
        <div class="card-tags-top">
          <span class="project-stage-badge ${stageInfo.cls}">${stageInfo.label}</span>
          ${project.conditions ? `<span class="card-tag" style="background:rgba(245,158,11,0.2);color:#FBBF24;border:1px solid rgba(245,158,11,0.4);">🤝 ${escapeHtml(project.conditions)}</span>` : ""}
        </div>
      </div>

      <div class="card-info-bottom">
        <div class="card-title-row">
          <span class="card-name" style="font-size:22px;color:#F59E0B;">${escapeHtml(project.title)}</span>
          <button class="action-btn info" data-action="info" title="Подробнее" style="margin-left:auto;background:rgba(245,158,11,0.2);border:1px solid rgba(245,158,11,0.4);">ℹ️</button>
        </div>

        <div style="font-size:14px;font-weight:700;color:#F8FAFC;margin:4px 0;line-height:1.3;">
          ${escapeHtml(project.pitch)}
        </div>

        ${rolesHtml}

        <div style="display:flex;align-items:center;gap:8px;margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.1);">
          <img src="${escapeHtml(founderAvatar)}" style="width:28px;height:28px;border-radius:50%;object-fit:cover;border:1.5px solid #F59E0B;" alt="${escapeHtml(founder.name)}" />
          <div style="font-size:12px;color:#CBD5E1;">
            <b>Фаундер:</b> ${escapeHtml(founder.name)} ${founderUni ? `(${escapeHtml(founderUni)})` : ""}
          </div>
        </div>

        <div class="card-actions-row" style="margin-top:12px;">
          <button class="action-btn dislike" data-action="skip" title="Пропустить">
            <svg class="action-btn-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#111111" stroke-width="3.5" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
          <button class="action-btn superlike" data-action="superlike" title="Откликнуться с питчем" style="background:linear-gradient(135deg, #F59E0B, #D97706);">
            <svg class="action-btn-icon" width="26" height="26" viewBox="0 0 24 24" fill="white">
              <path d="M12 2.5L15.09 8.76L22 9.77L17 14.64L18.18 21.5L12 18.25L5.82 21.5L7 14.64L2 9.77L8.91 8.76L12 2.5Z"/>
            </svg>
          </button>
          <button class="action-btn like" data-action="like" title="Хочу в команду!" style="background:linear-gradient(135deg, #F59E0B, #B45309);">
            <svg class="action-btn-icon" width="24" height="24" viewBox="0 0 24 24" fill="white">
              <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
            </svg>
          </button>
        </div>
      </div>
    `;

    card.querySelectorAll(".action-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const action = btn.dataset.action;
        if (action === "info") {
          openProjectDetailsModal(project);
        } else if (action === "superlike") {
          openProjectSuperlikeModal(project);
        } else {
          handleProjectSwipeAction(project, action);
        }
      });
    });

    card.addEventListener("click", () => {
      openProjectDetailsModal(project);
    });

    return card;
  }

  function openProjectSuperlikeModal(project) {
    const comment = prompt("💡 Расскажи фаундеру, какую роль ты хочешь занять в проекте и какой у тебя опыт:");
    if (comment && comment.trim()) {
      handleProjectSwipeAction(project, "superlike", comment.trim());
    }
  }

  // 5.5 Отправка рейтинга из имеющихся суперлайков
  async function handleSendRatingToUser(targetUserId, onRatingUpdated) {
    const currentBalance = state.currentUser?.superlike_balance || 0;
    if (currentBalance <= 0) {
      triggerHaptic("warning");
      openSuperlikeModal({ id: targetUserId, user_id: targetUserId });
      return;
    }

    try {
      triggerHaptic("medium");
      const resp = await apiFetch("/api/webapp/profile/send_rating", {
        method: "POST",
        body: JSON.stringify({ target_user_id: targetUserId }),
      });

      if (!resp) return;

      if (resp.status === "ok") {
        triggerHaptic("success");
        if (state.currentUser) {
          state.currentUser.superlike_balance = resp.remaining_superlikes;
        }
        if (typeof onRatingUpdated === "function") {
          onRatingUpdated(resp.new_target_rating, resp.remaining_superlikes);
        }
        const balLabel = document.getElementById("superlikeBalanceLabel");
        if (balLabel) balLabel.textContent = resp.remaining_superlikes;
        if (tg && tg.showAlert) {
          tg.showAlert(`⭐ Вы отправили 1 суперлайк! Рейтинг пользователя увеличен на +1. Осталось суперлайков: ${resp.remaining_superlikes} ⭐`);
        }
      } else {
        triggerHaptic("warning");
        if (tg && tg.showAlert) {
          tg.showAlert(resp.detail || "Не удалось отправить рейтинг.");
        }
      }
    } catch (e) {
      console.error("Error sending rating:", e);
      triggerHaptic("warning");
      if (tg && tg.showAlert) {
        tg.showAlert("Ошибка при отправке рейтинга. Проверьте баланс.");
      }
    }
  }

  // ─── Fullscreen Photo Gallery Viewer (Reference 1) ─────────────────
  let currentGalleryPhotos = [];
  let currentGalleryIndex = 0;
  let currentGalleryIsOwn = false;
  let currentGalleryOnDelete = null;

  function openFullscreenGallery(photos, initialIndex = 0, isOwnProfile = false, onDelete = null) {
    triggerHaptic("medium");
    const modal = document.getElementById("fullscreenGalleryModal");
    const mainImg = document.getElementById("fullscreenGalleryImg");
    const counter = document.getElementById("galleryPhotoCounter");
    const strip = document.getElementById("galleryThumbnailsStrip");
    const closeBtn = document.getElementById("closeGalleryModalBtn");
    const deleteBtn = document.getElementById("deleteGalleryPhotoBtn");
    if (!modal) return;

    if (!photos || photos.length === 0) {
      photos = ["https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"];
    }

    currentGalleryPhotos = photos.map((p) => (typeof p === "string" ? p : (p.url || p)));
    currentGalleryIndex = Math.max(0, Math.min(initialIndex, currentGalleryPhotos.length - 1));
    currentGalleryIsOwn = !!isOwnProfile;
    currentGalleryOnDelete = onDelete;

    if (deleteBtn) {
      deleteBtn.style.visibility = currentGalleryIsOwn ? "visible" : "hidden";
      deleteBtn.onclick = () => {
        triggerHaptic("medium");
        const doDelete = async () => {
          try {
            const photoUrl = currentGalleryPhotos[currentGalleryIndex];
            const resp = await apiFetch("/api/webapp/profile/photos", {
              method: "DELETE",
              body: JSON.stringify({ index: currentGalleryIndex, photo_url: photoUrl }),
            });
            if (resp && resp.status === "ok") {
              triggerHaptic("success");
              showAppToast("Фото удалено");
              const remainingPhotos = resp.photos || [];
              if (remainingPhotos.length === 0) {
                closeFullscreenGallery();
              } else {
                currentGalleryPhotos = remainingPhotos;
                currentGalleryIndex = Math.max(0, Math.min(currentGalleryIndex, currentGalleryPhotos.length - 1));
                renderGalleryView();
              }
              if (typeof currentGalleryOnDelete === "function") {
                currentGalleryOnDelete(remainingPhotos);
              }
              if (typeof loadProfile === "function") {
                loadProfile();
              }
            } else {
              triggerHaptic("error");
              showAppToast(resp?.detail || "Ошибка при удалении фото");
            }
          } catch (err) {
            console.error("Gallery delete error:", err);
            triggerHaptic("error");
            showAppToast("Не удалось удалить фото");
          }
        };

        if (window.Telegram?.WebApp?.showConfirm) {
          window.Telegram.WebApp.showConfirm("Удалить эту фотографию из профиля?", (ok) => {
            if (ok) doDelete();
          });
        } else if (confirm("Удалить эту фотографию из профиля?")) {
          doDelete();
        }
      };
    }

    function renderGalleryView() {
      if (mainImg) {
        mainImg.style.opacity = "0.4";
        mainImg.src = currentGalleryPhotos[currentGalleryIndex];
        mainImg.onload = () => { mainImg.style.opacity = "1"; };
        mainImg.onerror = () => {
          mainImg.style.opacity = "1";
          mainImg.src = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80";
        };
      }
      if (counter) {
        counter.textContent = `${currentGalleryIndex + 1} / ${currentGalleryPhotos.length}`;
      }
      if (strip) {
        strip.innerHTML = currentGalleryPhotos.map((url, idx) => `
          <div class="gallery-thumb-item ${idx === currentGalleryIndex ? "active" : ""}" data-thumb-idx="${idx}">
            <img src="${url}" alt="thumb" onerror="this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=200&q=80';" />
          </div>
        `).join("");

        strip.querySelectorAll(".gallery-thumb-item").forEach((thumb) => {
          thumb.addEventListener("click", () => {
            triggerHaptic("light");
            currentGalleryIndex = parseInt(thumb.dataset.thumbIdx, 10);
            renderGalleryView();
          });
        });
      }
    }

    renderGalleryView();
    modal.classList.add("active");

    if (closeBtn) {
      closeBtn.onclick = closeFullscreenGallery;
    }

    // Touch swipe on main image container
    let touchStartX = 0;
    let touchStartY = 0;
    const mainWrap = document.getElementById("fullscreenGalleryMain");
    if (mainWrap) {
      mainWrap.ontouchstart = (e) => {
        touchStartX = e.changedTouches[0].screenX;
        touchStartY = e.changedTouches[0].screenY;
      };
      mainWrap.ontouchend = (e) => {
        const diffX = e.changedTouches[0].screenX - touchStartX;
        const diffY = e.changedTouches[0].screenY - touchStartY;
        if (Math.abs(diffX) > Math.abs(diffY) && Math.abs(diffX) > 40) {
          if (diffX < 0 && currentGalleryIndex < currentGalleryPhotos.length - 1) {
            triggerHaptic("light");
            currentGalleryIndex++;
            renderGalleryView();
          } else if (diffX > 0 && currentGalleryIndex > 0) {
            triggerHaptic("light");
            currentGalleryIndex--;
            renderGalleryView();
          }
        } else if (diffY > 90 && Math.abs(diffY) > Math.abs(diffX)) {
          closeFullscreenGallery();
        }
      };
    }
  }

  function closeFullscreenGallery() {
    triggerHaptic("light");
    const modal = document.getElementById("fullscreenGalleryModal");
    if (modal) modal.classList.remove("active");
    const deleteBtn = document.getElementById("deleteGalleryPhotoBtn");
    if (deleteBtn) deleteBtn.style.visibility = "hidden";
  }
  window.openFullscreenGallery = openFullscreenGallery;
  window.closeFullscreenGallery = closeFullscreenGallery;

  // ─── Gallery Grid Builder (2 Top + 3/4 Bottom) ──────────────────────
  function buildGalleryGridHtml(photos, photosMeta, isOwnProfile = false) {
    const rawList = Array.isArray(photos) ? photos : [];
    const total = rawList.length;

    const getDeleteBtnHtml = (idx) => isOwnProfile ? `
      <button class="gallery-cell-delete-btn" data-delete-index="${idx}" title="Удалить это фото" aria-label="Удалить фото">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>
    ` : "";

    const uploadCellHtml = `
      <div class="gallery-upload-cell" id="galleryUploadCell" title="Загрузить новое фото" role="button" tabindex="0">
        <div class="gallery-upload-icon-circle">+</div>
        <div class="gallery-upload-text">Добавить<br/>фото</div>
      </div>
    `;

    // Case 0: No photos
    if (total === 0) {
      if (!isOwnProfile) return "";
      return `
        <div class="profile-gallery-grid">
          <div class="gallery-grid-row-top" style="grid-template-columns: 1fr;">
            <div class="gallery-upload-cell" id="galleryUploadCell" style="aspect-ratio: 16/10; border-radius: 18px;">
              <div class="gallery-upload-icon-circle">+</div>
              <div class="gallery-upload-text" style="font-size:13px;">Добавить фото в профиль</div>
            </div>
          </div>
        </div>
      `;
    }

    // Case 1: Exactly 1 photo
    if (total === 1) {
      const pm = photosMeta && photosMeta[0];
      const isPrivate = !isOwnProfile && pm && pm.is_private;

      if (isOwnProfile) {
        return `
          <div class="profile-gallery-grid">
            <div class="gallery-grid-row-top">
              <div class="gallery-grid-cell" data-gallery-index="0">
                <img src="${rawList[0]}" alt="Photo 1" onerror="this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />
                ${getDeleteBtnHtml(0)}
              </div>
              ${uploadCellHtml}
            </div>
          </div>
        `;
      }

      return `
        <div class="profile-gallery-grid">
          <div class="gallery-grid-row-top" style="grid-template-columns: 1fr;">
            <div class="gallery-grid-cell" data-gallery-index="0" style="aspect-ratio: 16/10;">
              <img src="${rawList[0]}" alt="Photo 1" onerror="this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />
              ${isPrivate ? `
                <div class="photo-private-overlay">
                  <div class="photo-private-lock-icon">🔒</div>
                  <div class="photo-private-text">Фото скрыто</div>
                  <div class="photo-private-subtext">Откроется после мэтча</div>
                </div>
              ` : ""}
            </div>
          </div>
        </div>
      `;
    }

    // Case 2+: Two or more photos
    const rowTop = rawList.slice(0, 2);
    let topHtml = rowTop.map((url, i) => {
      const pm = photosMeta && photosMeta[i];
      const isPrivate = !isOwnProfile && pm && pm.is_private;
      return `
        <div class="gallery-grid-cell" data-gallery-index="${i}">
          <img src="${url}" alt="Photo ${i + 1}" onerror="this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />
          ${getDeleteBtnHtml(i)}
          ${isPrivate ? `
            <div class="photo-private-overlay">
              <div class="photo-private-lock-icon">🔒</div>
              <div class="photo-private-text">Фото скрыто</div>
            </div>
          ` : ""}
        </div>
      `;
    }).join("");

    let bottomHtml = "";
    if (isOwnProfile) {
      const rowBottomPhotos = rawList.slice(2, 6);
      const rowBottomItems = rowBottomPhotos.map((url, idx) => {
        const actualIdx = idx + 2;
        return `
          <div class="gallery-grid-cell" data-gallery-index="${actualIdx}">
            <img src="${url}" alt="Photo ${actualIdx + 1}" onerror="this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=400&q=80';" />
            ${getDeleteBtnHtml(actualIdx)}
          </div>
        `;
      });

      if (total < 6) {
        rowBottomItems.push(uploadCellHtml);
      }

      if (rowBottomItems.length > 0) {
        const bottomGridCols = rowBottomItems.length === 4 ? "grid-template-columns: repeat(4, 1fr);" : "";
        bottomHtml = `
          <div class="gallery-grid-row-bottom" style="${bottomGridCols}">
            ${rowBottomItems.join("")}
          </div>
        `;
      }
    } else {
      const rowBottom = rawList.slice(2, 5);
      const remaining = total > 5 ? total - 5 : 0;
      if (rowBottom.length > 0) {
        bottomHtml = `
          <div class="gallery-grid-row-bottom">
            ${rowBottom.map((url, idx) => {
              const actualIdx = idx + 2;
              const pm = photosMeta && photosMeta[actualIdx];
              const isPrivate = pm && pm.is_private;
              const isLastWithMore = (idx === 2 && remaining > 0);
              return `
                <div class="gallery-grid-cell" data-gallery-index="${actualIdx}">
                  <img src="${url}" alt="Photo ${actualIdx + 1}" onerror="this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=400&q=80';" />
                  ${isPrivate ? `
                    <div class="photo-private-overlay">
                      <div class="photo-private-lock-icon" style="font-size:16px;">🔒</div>
                    </div>
                  ` : ""}
                  ${isLastWithMore ? `
                    <div class="gallery-grid-overlay-more">+${remaining}</div>
                  ` : ""}
                </div>
              `;
            }).join("")}
          </div>
        `;
      }
    }

    return `
      <div class="profile-gallery-grid">
        <div class="gallery-grid-row-top" style="${rowTop.length === 1 ? 'grid-template-columns: 1fr;' : ''}">
          ${topHtml}
        </div>
        ${bottomHtml}
      </div>
    `;
  }

  // ─── Hero Slider Swipe Handler ────────────────────────────────────
  function setupHeroSlider(containerEl, photos) {
    if (!containerEl || !photos || photos.length <= 1) return;
    const slider = containerEl.querySelector(".profile-hero-slider");
    const dots = containerEl.querySelectorAll(".profile-hero-dot");
    if (!slider) return;

    let activeIdx = 0;
    function updateSlide(newIdx) {
      activeIdx = Math.max(0, Math.min(newIdx, photos.length - 1));
      slider.style.transform = `translateX(-${activeIdx * 100}%)`;
      dots.forEach((d, i) => d.classList.toggle("active", i === activeIdx));
    }

    let touchStartX = 0;
    containerEl.addEventListener("touchstart", (e) => {
      touchStartX = e.changedTouches[0].screenX;
    }, { passive: true });

    containerEl.addEventListener("touchend", (e) => {
      const diffX = e.changedTouches[0].screenX - touchStartX;
      if (Math.abs(diffX) > 35) {
        if (diffX < 0 && activeIdx < photos.length - 1) {
          triggerHaptic("light");
          updateSlide(activeIdx + 1);
        } else if (diffX > 0 && activeIdx > 0) {
          triggerHaptic("light");
          updateSlide(activeIdx - 1);
        }
      }
    }, { passive: true });
  }

  // Helper: Open chat or message modal
  function handleProfileMessageClick(profile) {
    triggerHaptic("medium");
    const targetUserId = profile.user_id || profile.id;
    const existingMatch = (state.matches || []).find(
      (m) => (m.partner && (m.partner.id === targetUserId || m.partner.user_id === targetUserId)) || m.user_id === targetUserId
    );
    if (existingMatch) {
      closeDetailsSheet();
      openChat(existingMatch.id || existingMatch.match_id);
      return;
    }

    // Not matched yet: check privacy settings
    const whoCanMessage = profile.privacy?.who_can_message || "matches";
    if (whoCanMessage === "nobody") {
      showAppToast("🔒 Пользователь ограничил входящие сообщения");
    } else if (whoCanMessage === "everyone") {
      closeDetailsSheet();
      openSuperlikeModal(profile);
    } else {
      showAppToast("🔒 Сообщения доступны после взаимного мэтча. Поставьте лайк или суперлайк!");
    }
  }

  // 6. Детальная анкета пользователя (Универсальная карточка профиля для всех экранов)
  async function openDetailsSheet(profileOrId, options = {}) {
    triggerHaptic("medium");
    const body = document.getElementById("detailsSheetBody");
    if (!body || !detailsSheetOverlay) return;

    const source = options.source || "feed";
    let profile = null;

    // Поддержка передачи как объекта анкеты, так и ID пользователя
    let targetId = null;
    if (typeof profileOrId === "number" || typeof profileOrId === "string") {
      targetId = profileOrId;
    } else if (profileOrId && typeof profileOrId === "object" && (!profileOrId.name || !profileOrId.photos)) {
      targetId = profileOrId.user_id || profileOrId.id;
    }

    if (targetId) {
      body.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:360px;padding:60px 20px;gap:16px;color:var(--text-muted);">
          <div class="spinner" style="width:38px;height:38px;border:3px solid rgba(108,92,231,0.2);border-top-color:#6C5CE7;border-radius:50%;animation:spin 0.8s linear infinite;"></div>
          <div style="font-size:14px;font-weight:600;color:var(--text-main);">Загрузка анкеты...</div>
        </div>
      `;
      detailsSheetOverlay.classList.add("active");

      // Telegram BackButton интеграция
      if (tg?.BackButton) {
        tg.BackButton.show();
        if (chatScreenModal && chatScreenModal.style.display === "flex") {
          tg.BackButton.offClick(closeChat);
        }
        tg.BackButton.onClick(closeDetailsSheet);
      }

      try {
        const res = await apiFetch(`/api/webapp/user/${targetId}`);
        if (!detailsSheetOverlay.classList.contains("active")) return;
        if (!res || !res.user) {
          body.innerHTML = `
            <div style="text-align:center;padding:60px 20px;color:#EF4444;">
              <div style="font-size:40px;margin-bottom:12px;">😕</div>
              <div style="font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text-main);">Не удалось загрузить анкету</div>
              <p style="font-size:13px;color:var(--text-muted);margin-bottom:20px;">Возможно, профиль был скрыт или удалён</p>
              <button class="btn-secondary" id="closeErrDetailsSheetBtn" style="padding:10px 24px;">Закрыть</button>
            </div>
          `;
          document.getElementById("closeErrDetailsSheetBtn")?.addEventListener("click", closeDetailsSheet);
          return;
        }
        profile = res.user;
      } catch (err) {
        if (!detailsSheetOverlay.classList.contains("active")) return;
        body.innerHTML = `
          <div style="text-align:center;padding:60px 20px;color:#EF4444;">
            <div style="font-size:40px;margin-bottom:12px;">⚠️</div>
            <div style="font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text-main);">Ошибка сети</div>
            <button class="btn-secondary" id="closeErrDetailsSheetBtn" style="padding:10px 24px;">Закрыть</button>
          </div>
        `;
        document.getElementById("closeErrDetailsSheetBtn")?.addEventListener("click", closeDetailsSheet);
        return;
      }
    } else if (profileOrId && typeof profileOrId === "object") {
      profile = profileOrId;
    }

    if (!profile) return;

    const targetUserId = profile.user_id || profile.id;
    const isMe = Boolean(
      profile.is_me ||
      (state.currentUser && String(state.currentUser.id) === String(targetUserId))
    );
    profile.is_me = isMe;

    const existingMatch = (state.matches || []).find(
      (m) =>
        (m.partner && (String(m.partner.id) === String(targetUserId) || String(m.partner.user_id) === String(targetUserId))) ||
        String(m.user_id) === String(targetUserId)
    );
    const hasMatch = Boolean(profile.has_match || existingMatch || source === "match" || source === "chat");
    profile.has_match = hasMatch;
    const matchId = profile.match_id || existingMatch?.id || existingMatch?.match_id;

    // Telegram username и разблокировка контактов
    const tgUsername = profile.tg_username || existingMatch?.partner?.tg_username || existingMatch?.tg_username;
    const isTgUnlocked = Boolean(profile.is_tg_unlocked || existingMatch?.is_tg_unlocked);

    // Показывать свайпы (Пропустить / Лайк / Суперлайк) ТОЛЬКО при просмотре из ленты свайпов не для себя и без мэтча
    const showSwipeFloating = (source === "feed" && !isMe && !hasMatch);

    const rawPhotos = profile.photos && profile.photos.length > 0
      ? profile.photos
      : [profile.avatar || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"];

    const photosMeta = profile.photos_meta || rawPhotos.map((p, i) => ({ url: p, is_private: false, index: i }));
    const photos = rawPhotos;

    // Build Hero Slides
    const heroSlidesHtml = photos.map((url, i) => `
      <div class="profile-hero-slide" data-slide-index="${i}">
        <img src="${url}" class="profile-hero-img" alt="${escapeHtml(profile.name || 'Student')}" onerror="this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />
      </div>
    `).join("");

    // Build Hero Indicators
    const indicatorsHtml = photos.length > 1
      ? `<div class="profile-hero-indicators">${photos.map((_, i) => `<div class="profile-hero-dot ${i === 0 ? 'active' : ''}"></div>`).join("")}</div>`
      : "";

    // Subtitle text (University • Major • Course)
    const subtitleParts = [];
    if (profile.university) subtitleParts.push(profile.university);
    if (profile.major) subtitleParts.push(profile.major);
    if (profile.year) subtitleParts.push(`${profile.year} курс`);
    const subtitleText = subtitleParts.length > 0 ? subtitleParts.join(" • ") : "Студент StudMatch";

    // Online status indicator
    let onlineStatusHtml = "";
    if (profile.is_online) {
      onlineStatusHtml = `<span class="profile-online-badge" style="display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:600;color:#10B981;margin-top:3px;"><span style="width:7px;height:7px;border-radius:50%;background:#10B981;display:inline-block;"></span>${escapeHtml(profile.online_status_text || "онлайн")}</span>`;
    } else if (profile.online_status_text) {
      onlineStatusHtml = `<span style="font-size:12px;font-weight:500;color:var(--text-muted);display:inline-block;margin-top:3px;">${escapeHtml(profile.online_status_text)}</span>`;
    }

    // Location text
    const locationCity = profile.city || profile.university_city || "Москва";
    const locationUniv = profile.university ? `, ${profile.university}` : "";
    const distanceText = profile.distance ? `${profile.distance} км` : "1 км";

    // Interests pills with checkmarks
    const tags = profile.tags || [];
    const interestsHtml = tags.map((t, idx) => `
      <span class="profile-interest-pill ${idx < 2 ? 'highlighted' : ''}">
        ${idx < 2 ? '<span class="profile-interest-check">✔</span>' : ''}
        ${t.emoji || '🏷'} ${escapeHtml(t.name)}
      </span>
    `).join("");

    // Career information
    let careerHtml = "";
    if (profile.career_goal || profile.career_custom_skills || profile.career_portfolio_url || profile.career_work_format) {
      careerHtml = `
        <div class="profile-card-section">
          <div class="profile-section-title-row">
            <h4 class="profile-section-title">💼 Карьера и навыки</h4>
          </div>
          <div class="profile-career-box">
            ${profile.career_work_format ? `<div class="profile-career-item"><b>Формат:</b> ${escapeHtml(profile.career_work_format)}</div>` : ""}
            ${profile.career_custom_skills ? `<div class="profile-career-item"><b>Навыки:</b> ${escapeHtml(profile.career_custom_skills)}</div>` : ""}
            ${profile.career_goal ? `<div class="profile-career-item"><b>Цель:</b> ${escapeHtml(profile.career_goal)}</div>` : ""}
            ${profile.career_portfolio_url ? `<a href="${escapeHtml(profile.career_portfolio_url)}" target="_blank" class="sheet-link-btn" style="margin-top:8px;">🔗 Портфолио / Резюме</a>` : ""}
          </div>
        </div>
      `;
    }

    // Projects & Startups information
    let projectHtml = "";
    if (profile.project_role || profile.project_skills || profile.project_bio) {
      projectHtml = `
        <div class="profile-card-section">
          <div class="profile-section-title-row">
            <h4 class="profile-section-title">💡 Проекты и стартапы</h4>
          </div>
          <div class="profile-career-box" style="background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.2);">
            ${profile.project_role ? `<div class="profile-career-item"><b>Роль в проектах:</b> ${escapeHtml(profile.project_role)}</div>` : ""}
            ${profile.project_skills ? `<div class="profile-career-item"><b>Стек / Навыки:</b> ${escapeHtml(profile.project_skills)}</div>` : ""}
            ${profile.project_bio ? `<div class="profile-career-item"><b>О себе:</b> ${escapeHtml(profile.project_bio)}</div>` : ""}
          </div>
        </div>
      `;
    }

    // Gallery Grid
    const galleryGridHtml = buildGalleryGridHtml(photos, photosMeta, isMe);

    // About text
    const bioText = profile.goal || profile.about || profile.bio || "";
    const isBioLong = bioText.length > 140;

    // Floating actions markup (skip / like / superlike)
    const floatingActionsHtml = showSwipeFloating ? `
      <div class="profile-floating-actions">
        <button class="floating-action-btn dislike" id="candidateDislikeBtn" title="Пропустить">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#F97316" stroke-width="3" stroke-linecap="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
        <button class="floating-action-btn like" id="candidateLikeBtn" title="Лайк">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="white">
            <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
          </svg>
        </button>
        <button class="floating-action-btn superlike" id="candidateSuperlikeBtn" title="Суперлайк">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="#8B5CF6">
            <path d="M12 2.5L15.09 8.76L22 9.77L17 14.64L18.18 21.5L12 18.25L5.82 21.5L7 14.64L2 9.77L8.91 8.76L12 2.5Z"/>
          </svg>
        </button>
      </div>
    ` : "";

    // Header Airplane button
    const isChatOpenForPartner = Boolean(
      chatScreenModal &&
      chatScreenModal.style.display === "flex" &&
      currentChatPartner &&
      String(currentChatPartner.id) === String(targetUserId)
    );
    const airplaneBtnHtml = isMe ? "" : `
      <button class="profile-airplane-btn" id="candidateAirplaneBtn" title="${hasMatch ? (isChatOpenForPartner ? 'Вернуться в чат' : 'Открыть чат') : 'Написать сообщение'}">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#FF4B6E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>
      </button>
    `;

    // Action buttons at the bottom of the card
    let actionButtonsHtml = "";
    if (isMe) {
      actionButtonsHtml = `
        <div style="display:flex;flex-direction:column;gap:10px;">
          <div style="background:rgba(108,92,231,0.08);color:var(--primary, #6C5CE7);padding:12px 16px;border-radius:14px;font-size:13.5px;font-weight:700;text-align:center;">
            👤 Это ваш профиль
          </div>
          <button type="button" class="btn-primary" id="btnEditMyProfileFromDetails" style="width:100%;padding:14px;font-weight:700;border-radius:14px;">
            ⚙️ Редактировать анкету
          </button>
        </div>
      `;
    } else if (hasMatch) {
      const chatBtnText = isChatOpenForPartner ? "💬 Вернуться в чат" : "💬 Чат в приложении";

      if (isTgUnlocked && tgUsername) {
        const cleanTg = tgUsername.replace(/^@/, "").trim();
        actionButtonsHtml = `
          <div style="display:flex;flex-direction:column;gap:10px;">
            <button type="button" class="btn-primary" id="btnOpenTelegramDirectDetails" style="width:100%;background:linear-gradient(135deg, #229ED9, #0088cc);color:#fff;font-weight:700;padding:14px;border-radius:14px;">
              ✈️ Написать в Telegram (@${escapeHtml(cleanTg)})
            </button>
            <button type="button" class="btn-secondary" id="btnOpenChatFromDetails" style="width:100%;padding:13px;border-radius:14px;font-weight:600;">
              ${chatBtnText}
            </button>
          </div>
        `;
      } else {
        actionButtonsHtml = `
          <button type="button" class="btn-primary" id="btnOpenChatFromDetails" style="width:100%;padding:14px;font-weight:700;border-radius:14px;">
            ${chatBtnText}
          </button>
        `;
      }
    } else if (source !== "feed") {
      actionButtonsHtml = `
        <div style="display:flex;flex-direction:column;gap:10px;">
          <div style="background:var(--surface-subtle, #f1f5f9);color:var(--text-muted, #64748b);padding:12px 16px;border-radius:14px;font-size:13px;font-weight:500;text-align:center;line-height:1.4;">
            ✨ Общение станет доступно после взаимного лайка в ленте свайпов
          </div>
          <button type="button" class="btn-primary" id="btnGoToExploreFromDetails" style="width:100%;padding:13px;border-radius:14px;font-weight:700;">
            🔍 Искать анкеты в ленте
          </button>
        </div>
      `;
    }

    // Additional actions: Rating transfer, Admin toolbar, Report
    let additionalActionsHtml = "";
    if (!isMe) {
      additionalActionsHtml += `
        <button type="button" class="btn-send-rating" id="sheetSendRatingBtn" data-alias-btn="matchSendRatingBtn">
          <span class="btn-rating-icon">⭐</span>
          <span class="btn-rating-text">Отправить рейтинг (+1 б.)</span>
          <span class="btn-rating-balance" id="sheetRatingBalance">${state.currentUser?.superlike_balance || 0} ⭐</span>
        </button>
      `;
    }

    if (state.currentUser?.is_superadmin || state.currentUser?.id === 149620234) {
      additionalActionsHtml += `
        <div class="admin-quick-toolbar" style="padding:12px;background:#f8f9fe;border-radius:14px;border:1px dashed #6c5ce7;">
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
      `;
    }

    if (!isMe) {
      additionalActionsHtml += `
        <button class="sheet-report-btn" id="sheetReportBtn">
          🚩 Пожаловаться на анкету
        </button>
      `;
    }

    body.innerHTML = `
      <div class="profile-view-wrapper">
        <!-- Top Hero Section -->
        <div class="profile-hero-wrap" id="candidateHeroWrap">
          <button class="profile-hero-back-btn" id="closeCandidateSheetBtn" aria-label="Назад">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#E53935" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="15 18 9 12 15 6"></polyline>
            </svg>
          </button>
          ${indicatorsHtml}
          <div class="profile-hero-gradient-top"></div>
          <div class="profile-hero-gradient-bottom"></div>
          <div class="profile-hero-slider">
            ${heroSlidesHtml}
          </div>
        </div>

        <!-- White Content Card -->
        <div class="profile-sheet-card ${showSwipeFloating ? '' : 'no-floating'}">
          ${!showSwipeFloating ? '<div class="sheet-drag-pill"></div>' : ''}
          ${floatingActionsHtml}

          <!-- Header: Name, Age, Subtitle & Airplane Button -->
          <div class="profile-header-row">
            <div class="profile-header-left">
              <h2 class="profile-name-title">
                ${escapeHtml(profile.name || "Студент")}${profile.age ? `, ${profile.age}` : ""}
                ${profile.is_verified ? "🎓" : ""} ${profile.is_premium ? "💎" : ""}
                <span class="sheet-rating-badge match-rating-badge" id="sheetRatingBadge" data-alias-badge="matchRatingBadge">⭐ <span id="sheetRatingVal">${profile.rating_score || 0}</span></span>
              </h2>
              <p class="profile-role-subtitle">${escapeHtml(subtitleText)}</p>
              ${onlineStatusHtml}
            </div>
            ${airplaneBtnHtml}
          </div>

          <!-- Section: Location -->
          <div class="profile-card-section">
            <div class="profile-section-title-row">
              <h4 class="profile-section-title">Локация</h4>
            </div>
            <div class="profile-location-wrap">
              <p class="profile-location-text">${escapeHtml(locationCity)}${escapeHtml(locationUniv)}</p>
              <span class="profile-distance-badge">📍 ${escapeHtml(distanceText)}</span>
            </div>
          </div>

          <!-- Section: About -->
          ${bioText ? `
            <div class="profile-card-section">
              <div class="profile-section-title-row">
                <h4 class="profile-section-title">О себе</h4>
              </div>
              <div class="profile-about-text ${isBioLong ? 'clamped' : ''}" id="candidateAboutText">
                ${escapeHtml(bioText)}
              </div>
              ${isBioLong ? `<button class="profile-readmore-btn" id="candidateReadMoreBtn">Читать дальше</button>` : ""}
            </div>
          ` : ""}

          <!-- Section: Interests -->
          ${tags.length > 0 ? `
            <div class="profile-card-section">
              <div class="profile-section-title-row">
                <h4 class="profile-section-title">Интересы</h4>
              </div>
              <div class="profile-interests-wrap">
                ${interestsHtml}
              </div>
              ${profile.custom_interests ? `<p style="font-size:13.5px;color:#6B7280;margin-top:8px;">${escapeHtml(profile.custom_interests)}</p>` : ""}
            </div>
          ` : ""}

          <!-- Section: Career (if exists) -->
          ${careerHtml}

          <!-- Section: Projects (if exists) -->
          ${projectHtml}

          <!-- Section: Gallery -->
          ${photos.length > 0 ? `
            <div class="profile-card-section">
              <div class="profile-section-title-row">
                <h4 class="profile-section-title">Галерея</h4>
                <button class="profile-section-action-link" id="candidateSeeAllBtn">Все фото (${photos.length})</button>
              </div>
              ${galleryGridHtml}
            </div>
          ` : ""}

          <!-- Bottom Actions (Adaptive + Rating + Admin + Report) -->
          <div style="margin-top: 24px; display: flex; flex-direction: column; gap: 12px;">
            ${actionButtonsHtml}
            ${additionalActionsHtml}
          </div>
        </div>
      </div>
    `;

    detailsSheetOverlay.classList.add("active");

    // Telegram BackButton интеграция
    if (tg?.BackButton) {
      tg.BackButton.show();
      if (chatScreenModal && chatScreenModal.style.display === "flex") {
        tg.BackButton.offClick(closeChat);
      }
      tg.BackButton.onClick(closeDetailsSheet);
    }

    // Setup hero slider gestures
    const heroWrap = document.getElementById("candidateHeroWrap");
    setupHeroSlider(heroWrap, photos);

    // Hero photo tap -> open fullscreen gallery
    heroWrap?.querySelectorAll(".profile-hero-slide").forEach((slide, i) => {
      slide.addEventListener("click", () => {
        openFullscreenGallery(photos, i);
      });
    });

    // Gallery cells tap -> open fullscreen gallery
    body.querySelectorAll(".gallery-grid-cell").forEach((cell) => {
      cell.addEventListener("click", () => {
        const idx = parseInt(cell.dataset.galleryIndex, 10) || 0;
        openFullscreenGallery(photos, idx);
      });
    });

    document.getElementById("candidateSeeAllBtn")?.addEventListener("click", () => {
      openFullscreenGallery(photos, 0);
    });

    // Read more toggle
    const readMoreBtn = document.getElementById("candidateReadMoreBtn");
    const aboutText = document.getElementById("candidateAboutText");
    if (readMoreBtn && aboutText) {
      readMoreBtn.addEventListener("click", () => {
        triggerHaptic("light");
        const isClamped = aboutText.classList.contains("clamped");
        if (isClamped) {
          aboutText.classList.remove("clamped");
          readMoreBtn.textContent = "Свернуть";
        } else {
          aboutText.classList.add("clamped");
          readMoreBtn.textContent = "Читать дальше";
        }
      });
    }

    // Close button
    document.getElementById("closeCandidateSheetBtn")?.addEventListener("click", closeDetailsSheet);

    // Airplane / Direct message button
    document.getElementById("candidateAirplaneBtn")?.addEventListener("click", () => {
      if (isMe) return;
      if (hasMatch) {
        if (isChatOpenForPartner) {
          closeDetailsSheet();
          return;
        }
        closeDetailsSheet();
        if (matchId) {
          openChat(matchId);
        } else {
          switchTab("matches");
        }
      } else if (source === "feed") {
        handleProfileMessageClick(profile);
      } else {
        showAppToast("✨ Общение станет доступно после взаимного лайка в ленте свайпов");
      }
    });

    // Reaction buttons (Swipe Floating)
    if (showSwipeFloating) {
      document.getElementById("candidateDislikeBtn")?.addEventListener("click", () => {
        closeDetailsSheet();
        handleSwipeAction(profile, "skip");
      });
      document.getElementById("candidateSuperlikeBtn")?.addEventListener("click", () => {
        closeDetailsSheet();
        openSuperlikeModal(profile);
      });
      document.getElementById("candidateLikeBtn")?.addEventListener("click", () => {
        closeDetailsSheet();
        handleSwipeAction(profile, "like");
      });
    }

    // Adaptive action buttons
    document.getElementById("btnEditMyProfileFromDetails")?.addEventListener("click", () => {
      closeDetailsSheet();
      openProfileEditModal("dating");
    });

    document.getElementById("btnGoToExploreFromDetails")?.addEventListener("click", () => {
      closeDetailsSheet();
      switchTab("explore");
    });

    document.getElementById("btnOpenTelegramDirectDetails")?.addEventListener("click", () => {
      triggerHaptic("medium");
      openTelegramContact(tgUsername);
    });

    document.getElementById("btnOpenChatFromDetails")?.addEventListener("click", () => {
      closeDetailsSheet();
      if (isChatOpenForPartner) {
        return;
      }
      if (matchId) {
        openChat(matchId);
      } else {
        switchTab("matches");
      }
    });

    // Rating and Report (handles sheetSendRatingBtn and matchSendRatingBtn)
    (document.getElementById("sheetSendRatingBtn") || document.getElementById("matchSendRatingBtn"))?.addEventListener("click", () => {
      handleSendRatingToUser(targetUserId, (newRating, remainingBalance) => {
        profile.rating_score = newRating;
        const rVal = document.getElementById("sheetRatingVal") || document.getElementById("matchRatingVal");
        if (rVal) rVal.textContent = newRating;
        const bTag = document.getElementById("sheetRatingBalance") || document.getElementById("matchRatingBalance");
        if (bTag) bTag.textContent = `${remainingBalance} ⭐`;
        const topCardRating = document.querySelector(".card.top-card .card-rating-badge span");
        if (topCardRating) topCardRating.textContent = newRating;
      });
    });

    document.getElementById("sheetReportBtn")?.addEventListener("click", () => {
      closeDetailsSheet();
      openReportModal(profile);
    });

    // Admin buttons
    if (state.currentUser?.is_superadmin || state.currentUser?.id === 149620234) {
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
  }

  function closeDetailsSheet() {
    triggerHaptic("light");
    detailsSheetOverlay.classList.remove("active");
    if (chatScreenModal && chatScreenModal.style.display === "flex") {
      if (tg?.BackButton) {
        tg.BackButton.show();
        tg.BackButton.offClick(closeDetailsSheet);
        tg.BackButton.onClick(closeChat);
      }
    } else {
      if (tg?.BackButton) {
        tg.BackButton.offClick(closeDetailsSheet);
        tg.BackButton.hide();
      }
    }
  }

  window.openDetailsSheet = openDetailsSheet;
  window.closeDetailsSheet = closeDetailsSheet;

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

    setupPrivacyListeners();
    setupProfileEditListeners();
  }

  // 7.1. Модальное окно настроек приватности профиля
  async function openPrivacyModal() {
    triggerHaptic("medium");
    const modal = document.getElementById("privacyModal");
    if (!modal) return;

    try {
      const data = await apiFetch("/api/webapp/privacy");
      if (data && data.privacy) {
        const priv = data.privacy;
        // 1. Онлайн
        const onlineVal = priv.online_visibility || "all";
        document.querySelectorAll("#onlineVisibilityPills .privacy-pill").forEach((pill) => {
          pill.classList.toggle("active", pill.dataset.val === onlineVal);
        });

        // 2. Сообщения
        const msgVal = priv.message_permission || "matches";
        document.querySelectorAll("#messagePermissionPills .privacy-pill").forEach((pill) => {
          pill.classList.toggle("active", pill.dataset.val === msgVal);
        });

        // 3. Личные данные
        const togEmp = document.getElementById("privacyToggleEmployer");
        const togAge = document.getElementById("privacyToggleHideAge");
        const togCourse = document.getElementById("privacyToggleHideCourse");
        const togEmail = document.getElementById("privacyToggleHideEmail");

        if (togEmp) togEmp.checked = Boolean(priv.allow_employer_access);
        if (togAge) togAge.checked = Boolean(priv.hide_age);
        if (togCourse) togCourse.checked = Boolean(priv.hide_course);
        if (togEmail) togEmail.checked = Boolean(priv.hide_email);

        // 4. Фотографии
        renderPrivacyPhotos(data.photos || []);
      }
    } catch (e) {
      console.warn("Failed to load privacy settings:", e);
    }
    modal.classList.add("active");
  }

  function closePrivacyModal() {
    triggerHaptic("light");
    const modal = document.getElementById("privacyModal");
    if (modal) modal.classList.remove("active");
  }

  function renderPrivacyPhotos(photos) {
    const grid = document.getElementById("privacyPhotosGrid");
    if (!grid) return;

    if (!photos || photos.length === 0) {
      grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:24px 16px;color:var(--text-muted);font-size:13px;background:rgba(255,255,255,0.7);border-radius:16px;border:1px dashed rgba(230,233,245,0.9);">У вас пока нет загруженных фото</div>`;
      return;
    }

    grid.innerHTML = photos.map((p, idx) => {
      const isMain = Boolean(p.is_main || idx === 0);
      const isPrivate = Boolean(p.is_private);
      return `
        <div class="privacy-photo-card" data-photo-id="${escapeHtml(String(p.id))}">
          <div class="privacy-photo-thumb-wrap">
            <img src="${escapeHtml(p.url)}" class="privacy-photo-thumb ${isPrivate ? 'blurred' : ''}" alt="Фото" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=300&q=80';" />
            <div class="privacy-photo-status-badge ${isMain ? 'main' : (isPrivate ? 'locked' : 'open')}">
              ${isMain ? '⭐ Главное' : (isPrivate ? '🔒 До мэтча' : '👁 Публично')}
            </div>
            ${!isMain ? `
              <div class="privacy-photo-overlay-lock" style="${isPrivate ? '' : 'display: none;'}">
                <div class="privacy-photo-overlay-lock-icon">🔒</div>
              </div>
            ` : ''}
          </div>
          ${isMain ? `
            <div class="privacy-photo-main-tag">Всегда открыто</div>
          ` : `
            <button type="button" class="privacy-photo-action-btn ${isPrivate ? 'is-locked' : ''}" data-photo-id="${escapeHtml(String(p.id))}">
              <span class="photo-btn-icon">${isPrivate ? '🔒' : '👁️'}</span>
              <span class="photo-btn-text">${isPrivate ? 'Скрыто' : 'Открыто'}</span>
            </button>
          `}
        </div>
      `;
    }).join("");

    // Обработчик переключения приватности фото
    grid.querySelectorAll(".privacy-photo-action-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const photoId = btn.dataset.photoId;
        if (!photoId) return;
        triggerHaptic("light");
        btn.disabled = true;

        try {
          const res = await apiFetch("/api/webapp/privacy/photo-toggle", {
            method: "POST",
            body: JSON.stringify({ photo_id: photoId }),
          });
          if (res && res.status === "ok") {
            const isNowPrivate = Boolean(res.is_private);
            btn.classList.toggle("is-locked", isNowPrivate);
            
            const iconEl = btn.querySelector(".photo-btn-icon");
            const textEl = btn.querySelector(".photo-btn-text");
            if (iconEl) iconEl.textContent = isNowPrivate ? "🔒" : "👁️";
            if (textEl) textEl.textContent = isNowPrivate ? "Скрыто" : "Открыто";

            const card = btn.closest(".privacy-photo-card");
            if (card) {
              const img = card.querySelector(".privacy-photo-thumb");
              const badge = card.querySelector(".privacy-photo-status-badge");
              const overlayLock = card.querySelector(".privacy-photo-overlay-lock");
              
              if (img) img.classList.toggle("blurred", isNowPrivate);
              if (overlayLock) overlayLock.style.display = isNowPrivate ? "flex" : "none";
              if (badge) {
                badge.className = `privacy-photo-status-badge ${isNowPrivate ? 'locked' : 'open'}`;
                badge.textContent = isNowPrivate ? '🔒 До мэтча' : '👁 Публично';
              }
            }
          }
        } catch (err) {
          console.error("Error toggling photo privacy:", err);
          triggerHaptic("warning");
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  async function savePrivacySettings() {
    triggerHaptic("medium");
    const saveBtn = document.getElementById("savePrivacyBtn");
    const saveIcon = saveBtn?.querySelector(".save-icon");
    const saveLabel = saveBtn?.querySelector(".save-label");

    if (saveBtn) {
      saveBtn.disabled = true;
      if (saveIcon) saveIcon.textContent = "⏳";
      if (saveLabel) saveLabel.textContent = "Сохраняем...";
    }

    try {
      const activeOnlinePill = document.querySelector("#onlineVisibilityPills .privacy-pill.active");
      const onlineVisibility = activeOnlinePill ? activeOnlinePill.dataset.val : "all";

      const activeMsgPill = document.querySelector("#messagePermissionPills .privacy-pill.active");
      const messagePermission = activeMsgPill ? activeMsgPill.dataset.val : "matches";

      const allowEmployer = Boolean(document.getElementById("privacyToggleEmployer")?.checked);
      const hideAge = Boolean(document.getElementById("privacyToggleHideAge")?.checked);
      const hideCourse = Boolean(document.getElementById("privacyToggleHideCourse")?.checked);
      const hideEmail = Boolean(document.getElementById("privacyToggleHideEmail")?.checked);

      const res = await apiFetch("/api/webapp/privacy", {
        method: "POST",
        body: JSON.stringify({
          online_visibility: onlineVisibility,
          message_permission: messagePermission,
          allow_employer_access: allowEmployer,
          hide_age: hideAge,
          hide_course: hideCourse,
          hide_email: hideEmail,
        }),
      });

      if (res && res.status === "ok") {
        triggerHaptic("success");
        if (saveIcon) saveIcon.textContent = "✅";
        if (saveLabel) saveLabel.textContent = "Сохранено!";
        setTimeout(() => {
          closePrivacyModal();
        }, 400);
      }
    } catch (err) {
      console.error("Failed to save privacy settings:", err);
      triggerHaptic("warning");
      if (tg && tg.showAlert) {
        tg.showAlert("Не удалось сохранить настройки. Попробуйте снова.");
      }
    } finally {
      if (saveBtn) {
        setTimeout(() => {
          saveBtn.disabled = false;
          if (saveIcon) saveIcon.textContent = "✨";
          if (saveLabel) saveLabel.textContent = "Сохранить настройки";
        }, 600);
      }
    }
  }

  function setupPrivacyListeners() {
    document.getElementById("closePrivacyModalBtn")?.addEventListener("click", closePrivacyModal);

    const privacyModalEl = document.getElementById("privacyModal");
    privacyModalEl?.addEventListener("click", (e) => {
      if (e.target === privacyModalEl) {
        closePrivacyModal();
      }
    });

    // Online pills
    document.querySelectorAll("#onlineVisibilityPills .privacy-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        triggerHaptic("light");
        document.querySelectorAll("#onlineVisibilityPills .privacy-pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
      });
    });

    // Message pills
    document.querySelectorAll("#messagePermissionPills .privacy-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        triggerHaptic("light");
        document.querySelectorAll("#messagePermissionPills .privacy-pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
      });
    });

    // Save button
    document.getElementById("savePrivacyBtn")?.addEventListener("click", savePrivacySettings);
  }

  // 7.2. Модальное окно редактирования профиля (Знакомства + Карьера)
  let cachedInterestTags = null;

  function openProfileEditModal(initialTab = null) {
    triggerHaptic("medium");
    const modal = document.getElementById("profileEditModal");
    if (!modal) {
      console.error("[StudMatch] #profileEditModal not found in DOM!");
      return;
    }

    const u = state.currentUser || {};

    // 1. Установка активной вкладки (dating, career или projects)
    let activeTab = initialTab;
    if (!activeTab) {
      if (u.mode === "career") activeTab = "career";
      else if (u.mode === "projects") activeTab = "projects";
      else activeTab = "dating";
    }
    switchProfileEditTab(activeTab);

    // 2. Заполнение полей Знакомств
    const nameInput = document.getElementById("editDatingName");
    const ageInput = document.getElementById("editDatingAge");
    const yearSelect = document.getElementById("editDatingYear");
    const majorInput = document.getElementById("editDatingMajor");
    const goalInput = document.getElementById("editDatingGoal");
    const customInterestsInput = document.getElementById("editDatingCustomInterests");

    if (nameInput) nameInput.value = u.name || "";
    if (ageInput) ageInput.value = u.age || "";
    if (yearSelect) yearSelect.value = String(u.year || 1);
    if (majorInput) majorInput.value = u.major || "";
    if (goalInput) goalInput.value = u.goal || "";
    if (customInterestsInput) customInterestsInput.value = u.custom_interests || "";

    // Пол (Gender pills)
    const userGender = u.gender || "male";
    document.querySelectorAll("#editDatingGenderPills .gender-pill").forEach((pill) => {
      pill.classList.toggle("active", pill.dataset.gender === userGender);
    });

    // Кого ищете (Target gender pills)
    const targetGender = u.target_gender || "all";
    document.querySelectorAll("#editDatingTargetGenderPills .gender-pill").forEach((pill) => {
      pill.classList.toggle("active", pill.dataset.target === targetGender);
    });

    // 3. Заполнение полей Карьеры
    const careerGoalInput = document.getElementById("editCareerGoal");
    const careerSkillsInput = document.getElementById("editCareerSkills");
    const careerFormatSelect = document.getElementById("editCareerFormat");
    const careerPortfolioInput = document.getElementById("editCareerPortfolio");

    if (careerGoalInput) careerGoalInput.value = u.career_goal || "";
    if (careerSkillsInput) careerSkillsInput.value = u.career_custom_skills || "";
    if (careerFormatSelect) careerFormatSelect.value = u.career_work_format || "Удалённо";
    if (careerPortfolioInput) careerPortfolioInput.value = u.career_portfolio_url || "";

    // 4. Заполнение полей Проектов
    const projectRoleInput = document.getElementById("editProjectRole");
    const projectSkillsInput = document.getElementById("editProjectSkills");
    const projectBioInput = document.getElementById("editProjectBio");

    if (projectRoleInput) projectRoleInput.value = u.project_role || "";
    if (projectSkillsInput) projectSkillsInput.value = u.project_skills || "";
    if (projectBioInput) projectBioInput.value = u.project_bio || "";

    // Мгновенно активируем и отображаем модальное окно
    modal.classList.add("active");

    // Интеграция с нативной кнопкой «Назад» Telegram
    if (tg?.BackButton) {
      tg.BackButton.show();
      tg.BackButton.onClick(closeProfileEditModal);
    }

    // Теги интересов отрисовываем асинхронно
    renderProfileEditTags(u).catch((err) => {
      console.warn("Failed to render edit tags:", err);
    });
  }

  function closeProfileEditModal() {
    triggerHaptic("light");
    const modal = document.getElementById("profileEditModal");
    if (modal) modal.classList.remove("active");

    if (tg?.BackButton) {
      tg.BackButton.offClick(closeProfileEditModal);
      const isDetailsOpen = document.getElementById("detailsSheetOverlay")?.classList.contains("active");
      const isChatOpen = chatScreenModal && chatScreenModal.style.display === "flex";
      if (isDetailsOpen) {
        tg.BackButton.show();
        tg.BackButton.onClick(closeDetailsSheet);
      } else if (isChatOpen) {
        tg.BackButton.show();
        tg.BackButton.onClick(closeChat);
      } else {
        tg.BackButton.hide();
      }
    }
  }

  function switchProfileEditTab(tabName) {
    document.querySelectorAll(".profile-edit-tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.editTab === tabName);
    });
    const datingPane = document.getElementById("paneEditDating");
    const careerPane = document.getElementById("paneEditCareer");
    const projectsPane = document.getElementById("paneEditProjects");
    if (datingPane) datingPane.classList.toggle("active", tabName === "dating");
    if (careerPane) careerPane.classList.toggle("active", tabName === "career");
    if (projectsPane) projectsPane.classList.toggle("active", tabName === "projects");
  }

  async function renderProfileEditTags(u) {
    const cloud = document.getElementById("editDatingTagsCloud");
    if (!cloud) return;

    if (!cachedInterestTags) {
      try {
        const res = await apiFetch("/api/webapp/tags");
        if (res && res.tags) {
          cachedInterestTags = res.tags;
        }
      } catch (err) {
        console.warn("Failed to load interest tags:", err);
      }
    }

    const tags = cachedInterestTags || [];
    const currentTagIds = new Set();
    if (Array.isArray(u.interest_ids)) {
      u.interest_ids.forEach((id) => currentTagIds.add(Number(id)));
    } else if (Array.isArray(u.tags)) {
      u.tags.forEach((t) => {
        if (typeof t === "object" && t.id) currentTagIds.add(Number(t.id));
      });
    }

    if (tags.length === 0) {
      cloud.innerHTML = `<span style="font-size:12px;color:var(--text-muted);padding:4px;">Теги загружаются...</span>`;
      return;
    }

    cloud.innerHTML = tags.map((t) => {
      const isSelected = currentTagIds.has(Number(t.id));
      return `
        <button type="button" class="edit-tag-chip ${isSelected ? 'selected' : ''}" data-tag-id="${t.id}">
          ${escapeHtml(t.emoji || "✨")} ${escapeHtml(t.name)}
        </button>
      `;
    }).join("");

    cloud.querySelectorAll(".edit-tag-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        triggerHaptic("light");
        chip.classList.toggle("selected");
      });
    });
  }

  async function saveProfileEdit() {
    triggerHaptic("medium");
    const saveBtn = document.getElementById("saveProfileEditBtn");

    const name = document.getElementById("editDatingName")?.value.trim() || "";
    const ageRaw = document.getElementById("editDatingAge")?.value;
    const yearRaw = document.getElementById("editDatingYear")?.value;
    const major = document.getElementById("editDatingMajor")?.value.trim() || "";
    const goal = document.getElementById("editDatingGoal")?.value.trim() || "";
    const customInterests = document.getElementById("editDatingCustomInterests")?.value.trim() || "";

    const activeGenderBtn = document.querySelector("#editDatingGenderPills .gender-pill.active");
    const gender = activeGenderBtn?.dataset.gender || "male";

    const activeTargetBtn = document.querySelector("#editDatingTargetGenderPills .gender-pill.active");
    const targetGender = activeTargetBtn?.dataset.target || "all";

    const selectedTagIds = Array.from(document.querySelectorAll("#editDatingTagsCloud .edit-tag-chip.selected"))
      .map((chip) => parseInt(chip.dataset.tagId, 10))
      .filter((id) => !isNaN(id));

    // Валидация полей
    if (!name) {
      showAppToast("Укажите ваше имя");
      return;
    }

    const age = parseInt(ageRaw, 10);
    if (isNaN(age) || age < 16 || age > 35) {
      showAppToast("Возраст должен быть от 16 до 35 лет");
      return;
    }

    const year = parseInt(yearRaw, 10) || 1;

    // Карьерные поля
    const careerGoal = document.getElementById("editCareerGoal")?.value.trim() || "";
    const careerSkills = document.getElementById("editCareerSkills")?.value.trim() || "";
    const careerFormat = document.getElementById("editCareerFormat")?.value || "Удалённо";
    const careerPortfolio = document.getElementById("editCareerPortfolio")?.value.trim() || "";

    // Проектные поля
    const projectRole = document.getElementById("editProjectRole")?.value.trim() || "";
    const projectSkills = document.getElementById("editProjectSkills")?.value.trim() || "";
    const projectBio = document.getElementById("editProjectBio")?.value.trim() || "";

    const payload = {
      name: name,
      age: age,
      year: year,
      major: major,
      goal: goal,
      custom_interests: customInterests,
      interest_ids: selectedTagIds,
      gender: gender,
      target_gender: targetGender,
      career_goal: careerGoal,
      career_custom_skills: careerSkills,
      career_work_format: careerFormat,
      career_portfolio_url: careerPortfolio,
      project_role: projectRole,
      project_skills: projectSkills,
      project_bio: projectBio,
    };

    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = "⏳ Сохраняем...";
    }

    try {
      const res = await apiFetch("/api/webapp/profile", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (res && res.status === "ok") {
        triggerHaptic("success");
        showAppToast("Анкета успешно сохранена! ✨");

        // Обновляем локальный стейт текущего пользователя
        if (state.currentUser && res.profile) {
          Object.assign(state.currentUser, res.profile);
        }

        closeProfileEditModal();
        await loadProfile();
      } else {
        triggerHaptic("error");
        showAppToast(res?.detail || "Не удалось сохранить анкету");
      }
    } catch (err) {
      console.error("Save profile error:", err);
      triggerHaptic("error");
      showAppToast("Ошибка соединения при сохранении");
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = "💾 Сохранить изменения";
      }
    }
  }

  function setupProfileEditListeners() {
    document.getElementById("profileEditCloseBtn")?.addEventListener("click", closeProfileEditModal);

    const modal = document.getElementById("profileEditModal");
    modal?.addEventListener("click", (e) => {
      if (e.target === modal) {
        closeProfileEditModal();
      }
    });

    // Tab buttons
    document.querySelectorAll(".profile-edit-tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        triggerHaptic("light");
        const tab = btn.dataset.editTab;
        if (tab) switchProfileEditTab(tab);
      });
    });

    // Gender pills
    document.querySelectorAll("#editDatingGenderPills .gender-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        triggerHaptic("light");
        document.querySelectorAll("#editDatingGenderPills .gender-pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
      });
    });

    // Target gender pills
    document.querySelectorAll("#editDatingTargetGenderPills .gender-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        triggerHaptic("light");
        document.querySelectorAll("#editDatingTargetGenderPills .gender-pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
      });
    });

    // Save button
    document.getElementById("saveProfileEditBtn")?.addEventListener("click", saveProfileEdit);
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
        updateNavBadges({ matches: 0 });
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
      const totalUnread = data.matches.reduce((sum, m) => sum + (m.unread_count || 0), 0);
      updateNavBadges({ matches: totalUnread });

      container.innerHTML = data.matches
        .map((m) => {
          const photoUrl = m.photo_url || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80";
          const verified = m.is_verified ? " 🎓" : "";
          const prem = m.is_premium ? " 💎" : "";
          const unreadBadge = m.unread_count > 0 ? `<div class="match-unread-badge">${m.unread_count}</div>` : "";
          const onlineDot = m.is_online ? `<div class="match-online-dot"></div>` : "";

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
                ${onlineDot}
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
            openDetailsSheet(pid, { source: "match" });
          }
        });
      });
    } catch (e) {
      container.innerHTML = '<div style="text-align:center;padding:30px;color:red;">Ошибка загрузки</div>';
    }
  }

  // 10. Открытие полной анкеты мэтча (алиас к универсальной карточке openDetailsSheet)
  async function openMatchFullProfile(partnerId, options = {}) {
    return openDetailsSheet(partnerId, { source: "match", ...options });
  }
  window.openMatchFullProfile = openMatchFullProfile;

  // ─── 11. In-App Chat Controller & Real-Time Engine ─────────────
  let currentChatMatchData = null;
  let chatWebSocket = null;
  let typingTimer = null;
  let isSendingTyping = false;
  let chatPingInterval = null;

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
  const chatScrollBottomBtn = document.getElementById("chatScrollBottomBtn");
  const chatScrollUnreadBadge = document.getElementById("chatScrollUnreadBadge");
  let chatUnreadWhileScrolled = 0;
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
    if (chatScrollBottomBtn) chatScrollBottomBtn.style.display = "none";
    chatUnreadWhileScrolled = 0;
    updateScrollBottomBtnBadge();

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
      if (!data) {
        throw new Error("Не удалось связаться с сервером");
      }
      if (data.status === "error" || data.detail) {
        throw new Error(data.detail || "Не удалось загрузить диалог");
      }

      // Принимаем данные диалога как из data.match, так и из корневого объекта data
      const matchData = data.match || {
        id: data.match_id || matchId,
        match_id: data.match_id || matchId,
        partner: data.partner,
        is_tg_unlocked: Boolean(data.is_tg_unlocked),
        my_tg_approved: Boolean(data.my_tg_approved),
        partner_tg_approved: Boolean(data.partner_tg_approved),
        partner_tg_username: data.partner_tg_username || data.partner?.tg_username,
      };

      if (!matchData.partner) {
        throw new Error("Собеседник не найден или диалог недоступен");
      }

      currentChatMatchData = matchData;
      currentChatPartner = matchData.partner;
      currentChatMatchData.partner_tg_username = matchData.partner_tg_username || matchData.partner?.tg_username;

      // Обновляем шапку чата
      if (chatPartnerName) {
        chatPartnerName.textContent = currentChatPartner.name || "Собеседник";
      }
      if (chatPartnerPremBadge) {
        chatPartnerPremBadge.style.display = currentChatPartner.is_premium ? "inline" : "none";
      }
      if (chatPartnerAvatar) {
        const photo = currentChatPartner.photo_url || currentChatPartner.avatar_url || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80";
        chatPartnerAvatar.src = photo;
        chatPartnerAvatar.onerror = function() {
          this.onerror = null;
          this.src = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80";
        };
      }
      if (chatTypingName) {
        chatTypingName.textContent = currentChatPartner.name || "Собеседник";
      }
      const isOnline = Boolean(currentChatPartner.is_online);
      if (chatPartnerStatus) {
        chatPartnerStatus.textContent = currentChatPartner.online_status_text || (isOnline ? "онлайн" : "был(а) недавно");
      }
      if (chatPartnerOnlineDot) {
        chatPartnerOnlineDot.style.display = isOnline ? "block" : "none";
      }

      // Отрисовываем баннер Telegram
      renderChatTgBanner(currentChatMatchData);

      // Отрисовываем сообщения
      if (chatLoadingSpinner) chatLoadingSpinner.style.display = "none";
      renderChatMessages(data.messages || []);

      // Проверка прав приватности на отправку сообщений
      const chatBlockedBanner = document.getElementById("chatBlockedBanner");
      const chatBlockedBannerText = document.getElementById("chatBlockedBannerText");
      if (data.can_send_message === false) {
        if (chatBlockedBanner) {
          chatBlockedBanner.style.display = "flex";
          if (chatBlockedBannerText) {
            chatBlockedBannerText.textContent = data.message_block_reason || "Отправка сообщений ограничена пользователем";
          }
        }
        if (chatInputText) {
          chatInputText.disabled = true;
          chatInputText.placeholder = data.message_block_reason || "Сообщения ограничены";
        }
        if (chatSendBtn) {
          chatSendBtn.disabled = true;
          chatSendBtn.style.opacity = "0.4";
        }
      } else {
        if (chatBlockedBanner) chatBlockedBanner.style.display = "none";
        if (chatInputText) {
          chatInputText.disabled = false;
          chatInputText.placeholder = "Напишите сообщение...";
        }
        if (chatSendBtn) {
          chatSendBtn.style.opacity = "1";
        }
      }

      // Подключаем WebSocket
      connectChatWebSocket(matchId);

    } catch (err) {
      console.error("[Chat] Error loading chat:", err);
      if (chatLoadingSpinner) chatLoadingSpinner.style.display = "none";
      if (chatMessagesInner) {
        const errMsg = (err && err.message) ? escapeHtml(err.message) : "Не удалось загрузить сообщения. Попробуйте позже.";
        chatMessagesInner.innerHTML = `
          <div style="text-align:center;padding:40px 20px;color:var(--text-muted);">
            <div style="font-size:36px;margin-bottom:8px;">⚠️</div>
            <div>${errMsg}</div>
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
    if (chatScrollBottomBtn) chatScrollBottomBtn.style.display = "none";
    chatUnreadWhileScrolled = 0;
    updateScrollBottomBtnBadge();
    const chatBlockedBanner = document.getElementById("chatBlockedBanner");
    if (chatBlockedBanner) chatBlockedBanner.style.display = "none";
    if (chatInputText) {
      chatInputText.disabled = false;
      chatInputText.placeholder = "Напишите сообщение...";
    }
    if (chatSendBtn) {
      chatSendBtn.style.opacity = "1";
    }
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

    const partnerUsername = matchData.partner_tg_username || matchData.partner?.tg_username;
    if (matchData.is_tg_unlocked && partnerUsername) {
      const cleanTg = String(partnerUsername).replace("@", "").trim();
      chatTgBanner.innerHTML = `
        <div class="chat-tg-banner-text">
          <div class="chat-tg-banner-title">🎉 Контакты Telegram открыты!</div>
          <div class="chat-tg-banner-desc">Вы и собеседник обоюдно подтвердили переход в Telegram.</div>
        </div>
        <button type="button" class="chat-tg-banner-btn unlocked" id="btnChatBannerOpenTg">
          <span>💬 @${escapeHtml(cleanTg)}</span>
        </button>
      `;

      document.getElementById("btnChatBannerOpenTg")?.addEventListener("click", () => {
        triggerHaptic("medium");
        openTelegramContact(cleanTg);
      });
    } else if (matchData.is_tg_unlocked) {
      chatTgBanner.innerHTML = `
        <div class="chat-tg-banner-text">
          <div class="chat-tg-banner-title">🎉 Контакты открыты!</div>
          <div class="chat-tg-banner-desc">Вы и собеседник подтвердили переход в Telegram. Напишите в чате, чтобы обменяться контактами напрямую!</div>
        </div>
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

  function isChatNearBottom(threshold = 90) {
    if (!chatMessagesContainer) return true;
    const dist = chatMessagesContainer.scrollHeight - chatMessagesContainer.scrollTop - chatMessagesContainer.clientHeight;
    return dist <= threshold;
  }

  function updateScrollBottomBtnBadge() {
    if (!chatScrollUnreadBadge) return;
    if (chatUnreadWhileScrolled > 0) {
      chatScrollUnreadBadge.textContent = chatUnreadWhileScrolled > 99 ? "99+" : String(chatUnreadWhileScrolled);
      chatScrollUnreadBadge.style.display = "flex";
    } else {
      chatScrollUnreadBadge.style.display = "none";
    }
  }

  function scrollChatToBottom(smooth = false) {
    if (!chatMessagesContainer) return;
    const doScroll = () => {
      if (!chatMessagesContainer) return;
      if (smooth) {
        chatMessagesContainer.scrollTo({
          top: chatMessagesContainer.scrollHeight,
          behavior: "smooth"
        });
      } else {
        chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
      }
    };
    requestAnimationFrame(doScroll);
    setTimeout(doScroll, 50);
    setTimeout(doScroll, 200);
  }

  // Отправка текстового сообщения
  async function sendChatMessage() {
    if (!currentChatMatchId || !chatInputText || chatInputText.disabled) return;
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
      if (!chatMessagesInner.querySelector(".chat-msg-row") && !chatMessagesInner.querySelector(".chat-system-card")) {
        chatMessagesInner.innerHTML = "";
      }
      chatMessagesInner.insertAdjacentHTML("beforeend", renderMessageHtml(optimisticMsg));
      chatUnreadWhileScrolled = 0;
      updateScrollBottomBtnBadge();
      if (chatScrollBottomBtn) chatScrollBottomBtn.style.display = "none";
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
          if (!chatMessagesInner.querySelector(".chat-msg-row") && !chatMessagesInner.querySelector(".chat-system-card")) {
            chatMessagesInner.innerHTML = "";
          }
          const nearBottom = isChatNearBottom(90);
          chatMessagesInner.insertAdjacentHTML("beforeend", renderMessageHtml({
            id: msg.id,
            text: msg.text,
            msg_type: msg.msg_type,
            is_mine: false,
            is_read: true,
            created_at: msg.created_at,
          }));

          if (nearBottom) {
            scrollChatToBottom(true);
          } else {
            chatUnreadWhileScrolled++;
            updateScrollBottomBtnBadge();
            if (chatScrollBottomBtn) {
              chatScrollBottomBtn.style.display = "flex";
            }
          }
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
          if (isChatNearBottom(90)) {
            scrollChatToBottom(true);
          }
        }
      }
    } else if (data.type === "tg_approval_update") {
      triggerHaptic("success");
      if (currentChatMatchData) {
        currentChatMatchData.is_tg_unlocked = data.is_tg_unlocked;
        if (data.is_tg_unlocked && data.partner_tg_username) {
          currentChatMatchData.partner_tg_username = data.partner_tg_username;
        } else if (data.is_tg_unlocked && currentChatMatchId && !currentChatMatchData.partner_tg_username) {
          apiFetch(`/api/webapp/matches/${currentChatMatchId}/messages`).then((freshData) => {
            if (freshData) {
              const freshMatch = freshData.match || freshData;
              currentChatMatchData.partner_tg_username = freshMatch.partner_tg_username || freshMatch.partner?.tg_username;
              renderChatTgBanner(currentChatMatchData);
            }
          }).catch(console.warn);
        }
        renderChatTgBanner(currentChatMatchData);
      }
      if (data.system_message && chatMessagesInner) {
        if (!chatMessagesInner.querySelector(".chat-msg-row") && !chatMessagesInner.querySelector(".chat-system-card")) {
          chatMessagesInner.innerHTML = "";
        }
        chatMessagesInner.insertAdjacentHTML("beforeend", renderMessageHtml({
          id: data.system_message.id,
          text: data.system_message.text,
          msg_type: data.system_message.msg_type || "system",
          is_mine: false,
          created_at: data.system_message.created_at,
        }));
        if (isChatNearBottom(90)) {
          scrollChatToBottom(true);
        }
      }

    } else if (data.type === "user_online") {
      if (!data.user_id || (currentChatPartner && String(data.user_id) === String(currentChatPartner.id))) {
        if (currentChatPartner) currentChatPartner.is_online = true;
        if (chatPartnerOnlineDot) chatPartnerOnlineDot.style.display = "block";
        if (chatPartnerStatus) chatPartnerStatus.textContent = "онлайн";
      }
    } else if (data.type === "user_offline") {
      if (!data.user_id || (currentChatPartner && String(data.user_id) === String(currentChatPartner.id))) {
        if (currentChatPartner) currentChatPartner.is_online = false;
        if (chatPartnerOnlineDot) chatPartnerOnlineDot.style.display = "none";
        if (chatPartnerStatus) chatPartnerStatus.textContent = "был(а) недавно";
      }
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
        openDetailsSheet(currentChatPartner.id, { source: "chat" });
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
        openDetailsSheet(currentChatPartner.id, { source: "chat" });
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

    chatInputText.addEventListener("focus", () => {
      setTimeout(() => {
        scrollChatToBottom(true);
      }, 250);
    });
  }

  if (chatSendBtn) {
    chatSendBtn.addEventListener("click", sendChatMessage);
  }

  if (chatMessagesContainer) {
    chatMessagesContainer.addEventListener("scroll", () => {
      const dist = chatMessagesContainer.scrollHeight - chatMessagesContainer.scrollTop - chatMessagesContainer.clientHeight;
      if (dist > 120) {
        if (chatScrollBottomBtn) chatScrollBottomBtn.style.display = "flex";
      } else if (dist <= 40) {
        if (chatScrollBottomBtn) chatScrollBottomBtn.style.display = "none";
        chatUnreadWhileScrolled = 0;
        updateScrollBottomBtnBadge();
      }
    });
  }

  if (chatScrollBottomBtn) {
    chatScrollBottomBtn.addEventListener("click", () => {
      triggerHaptic("light");
      chatUnreadWhileScrolled = 0;
      updateScrollBottomBtnBadge();
      chatScrollBottomBtn.style.display = "none";
      scrollChatToBottom(true);
    });
  }

  if (tg) {
    tg.onEvent("viewportChanged", () => {
      if (chatScreenModal && chatScreenModal.style.display === "flex") {
        if (isChatNearBottom(120)) {
          scrollChatToBottom(false);
        }
      }
    });
  }

  // 12. Deep Linking (startapp=chat_{match_id} / chat_{user_id})
  function checkStartParamDeepLink() {
    let startParam = "";
    try {
      // 1. Приоритетно проверяем URL query параметры (при клике на инлайн-кнопку WebAppInfo)
      const urlParams = new URLSearchParams(window.location.search);
      startParam = urlParams.get("startapp") || urlParams.get("tgWebAppStartParam") || urlParams.get("chat") || "";

      // 2. Если в search пусто, проверяем hash (передается Telegram WebApp)
      if (!startParam && window.location.hash) {
        const hashStr = window.location.hash.slice(1);
        const hashParams = new URLSearchParams(hashStr);
        startParam = hashParams.get("startapp") || hashParams.get("tgWebAppStartParam") || hashParams.get("chat") || "";
        if (!startParam && hashParams.get("tgWebAppData")) {
          try {
            const initDataStr = hashParams.get("tgWebAppData");
            const initDataParams = new URLSearchParams(initDataStr);
            startParam = initDataParams.get("start_param") || "";
          } catch (err) {}
        }
      }

      // 3. Если все еще пусто, проверяем Telegram WebApp initDataUnsafe
      if (!startParam && tg?.initDataUnsafe?.start_param) {
        startParam = tg.initDataUnsafe.start_param;
      }
    } catch (e) {
      console.warn("[DeepLink] Error reading start param:", e);
    }

    if (!startParam) return;

    // Поддерживаем форматы: "chat_UUID", "chat_USERID", "user_USERID", "UUID", "USERID"
    let targetChatId = "";
    if (typeof startParam === "string") {
      startParam = startParam.trim();
      if (startParam.startsWith("chat_")) {
        targetChatId = startParam.replace("chat_", "").trim();
      } else if (startParam.startsWith("user_")) {
        targetChatId = startParam.replace("user_", "").trim();
      } else if (startParam.length >= 8 && (startParam.includes("-") || !isNaN(startParam))) {
        targetChatId = startParam;
      }
    }

    if (targetChatId) {
      console.log("[DeepLink] Opening chat from deep link target:", targetChatId);
      // Очищаем параметры из URL, чтобы при ручном обновлении страницы не зацикливалось
      try {
        const cleanUrl = window.location.pathname + (window.location.hash || "");
        window.history.replaceState({}, document.title, cleanUrl);
      } catch (e) {}

      // Открываем диалог (небольшая задержка 100мс для завершения отрисовки DOM)
      setTimeout(() => {
        openChat(targetChatId);
      }, 100);
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

      const likesCount = data.count || (data.likes ? data.likes.length : 0);
      updateNavBadges({ likes: likesCount });

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
          const botUser = window.BOT_USERNAME || "edudating_bot";
          const link = `https://t.me/${botUser}?start=premium`;
          if (tg && tg.openTelegramLink) {
            tg.openTelegramLink(link);
          } else {
            window.open(link, "_blank");
          }
          if (tg && tg.close) {
            try {
              tg.close();
            } catch (err) {
              console.warn("Could not close Telegram WebApp:", err);
            }
          }
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

  // 11. Раздел «Профиль» (Reference 2)
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

      const hasRealPhotos = (Array.isArray(u.raw_photos) && u.raw_photos.length > 0)
        || (Array.isArray(u.photos) && u.photos.length > 0 && !u.photos[0].includes("images.unsplash.com"));
      const userPhotos = hasRealPhotos ? u.photos : [];
      const photos = userPhotos.length > 0
        ? userPhotos
        : [u.avatar || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"];

      const photosMeta = u.photos_meta || photos.map((p, i) => ({ url: p, is_private: false, index: i }));

      // Hero slides
      const heroSlidesHtml = photos.map((url, i) => `
        <div class="profile-hero-slide" data-slide-index="${i}">
          <img src="${url}" class="profile-hero-img" alt="${escapeHtml(u.name || 'User')}" onerror="this.src='https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80';" />
        </div>
      `).join("");

      // Hero indicators
      const indicatorsHtml = photos.length > 1
        ? `<div class="profile-hero-indicators">${photos.map((_, i) => `<div class="profile-hero-dot ${i === 0 ? 'active' : ''}"></div>`).join("")}</div>`
        : "";

      // Subtitle
      const subtitleParts = [];
      if (u.university) subtitleParts.push(u.university);
      if (u.major) subtitleParts.push(u.major);
      if (u.year) subtitleParts.push(`${u.year} курс`);
      const subtitleText = subtitleParts.length > 0 ? subtitleParts.join(" • ") : "Студент StudMatch";

      // Location
      const locationCity = u.city || u.university_city || "Москва";
      const locationUniv = u.university ? `, ${u.university}` : "";

      // Interests pills
      const tags = u.tags || [];
      const interestsHtml = tags.map((t, idx) => `
        <span class="profile-interest-pill ${idx < 2 ? 'highlighted' : ''}">
          ${idx < 2 ? '<span class="profile-interest-check">✔</span>' : ''}
          ${t.emoji || '🏷'} ${escapeHtml(t.name)}
        </span>
      `).join("");

      // Career information
      let careerHtml = "";
      if (u.career_goal || u.career_custom_skills || u.career_portfolio_url || u.career_work_format) {
        careerHtml = `
          <div class="profile-card-section">
            <div class="profile-section-title-row">
              <h4 class="profile-section-title">💼 Профессиональная информация</h4>
            </div>
            <div class="profile-career-box">
              ${u.career_work_format ? `<div class="profile-career-item"><b>Формат:</b> ${escapeHtml(u.career_work_format)}</div>` : ""}
              ${u.career_custom_skills ? `<div class="profile-career-item"><b>Навыки:</b> ${escapeHtml(u.career_custom_skills)}</div>` : ""}
              ${u.career_goal ? `<div class="profile-career-item"><b>Цель:</b> ${escapeHtml(u.career_goal)}</div>` : ""}
              ${u.career_portfolio_url ? `<a href="${escapeHtml(u.career_portfolio_url)}" target="_blank" class="sheet-link-btn" style="margin-top:8px;">🔗 Открыть портфолио / резюме</a>` : ""}
            </div>
          </div>
        `;
      }

      // Gallery Grid
      const galleryGridHtml = buildGalleryGridHtml(userPhotos, photosMeta, true);

      // Bio text
      const bioText = u.goal || u.about || u.bio || "";
      const isBioLong = bioText.length > 140;

      container.innerHTML = `
        <div class="profile-view-wrapper">
          <!-- Top Hero Section -->
          <div class="profile-hero-wrap" id="myProfileHeroWrap">
            ${indicatorsHtml}
            <div class="profile-hero-gradient-top"></div>
            <div class="profile-hero-gradient-bottom"></div>
            <div class="profile-hero-slider">
              ${heroSlidesHtml}
            </div>
          </div>

          <!-- White Content Card -->
          <div class="profile-sheet-card">
            <!-- Floating Management Actions for Own Profile -->
            <div class="profile-manage-actions">
              <button class="profile-manage-btn secondary" id="btnMyPrivacyTop">
                <span style="font-size:16px;">🔒</span> Приватность
              </button>
              <button class="profile-manage-btn primary" id="btnMyEditTop">
                <span style="font-size:16px;">✏️</span> Редактировать
              </button>
              <button class="profile-manage-btn secondary" id="btnMyFiltersTop">
                <span style="font-size:16px;">🎯</span> Фильтры
              </button>
            </div>

            <!-- Header: Name, Age, Subtitle & Edit Button -->
            <div class="profile-header-row">
              <div class="profile-header-left">
                <h2 class="profile-name-title">
                  ${escapeHtml(u.name || "Студент")}${u.age ? `, ${u.age}` : ""}
                  ${u.is_verified ? "🎓" : ""} ${u.is_premium ? "💎" : ""}
                </h2>
                <p class="profile-role-subtitle">${escapeHtml(subtitleText)}</p>
              </div>
              <button class="profile-airplane-btn" id="btnMyEditQuick" title="Редактировать анкету">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FF4B6E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                </svg>
              </button>
            </div>

            <!-- Stats Bar -->
            <div class="profile-stats-row" style="margin-bottom: 22px; padding: 12px 8px; background: #F9FAFB; border-radius: 16px; border: 1px solid #F3F4F6;">
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

            <!-- Section: Location -->
            <div class="profile-card-section">
              <div class="profile-section-title-row">
                <h4 class="profile-section-title">Локация</h4>
              </div>
              <div class="profile-location-wrap">
                <p class="profile-location-text">${escapeHtml(locationCity)}${escapeHtml(locationUniv)}</p>
                <span class="profile-distance-badge">📍 Мой ВУЗ</span>
              </div>
            </div>

            <!-- Section: About -->
            ${bioText ? `
              <div class="profile-card-section">
                <div class="profile-section-title-row">
                  <h4 class="profile-section-title">О себе</h4>
                </div>
                <div class="profile-about-text ${isBioLong ? 'clamped' : ''}" id="myProfileAboutText">
                  ${escapeHtml(bioText)}
                </div>
                ${isBioLong ? `<button class="profile-readmore-btn" id="myProfileReadMoreBtn">Читать дальше</button>` : ""}
              </div>
            ` : ""}

            <!-- Section: Interests -->
            ${tags.length > 0 ? `
              <div class="profile-card-section">
                <div class="profile-section-title-row">
                  <h4 class="profile-section-title">Интересы</h4>
                </div>
                <div class="profile-interests-wrap">
                  ${interestsHtml}
                </div>
                ${u.custom_interests ? `<p style="font-size:13.5px;color:#6B7280;margin-top:8px;">${escapeHtml(u.custom_interests)}</p>` : ""}
              </div>
            ` : ""}

            <!-- Section: Career (if exists) -->
            ${careerHtml}

            <!-- Section: Gallery -->
            <div class="profile-card-section" id="profileGallerySection">
              <div class="profile-section-title-row">
                <h4 class="profile-section-title">Галерея</h4>
                <div style="display:flex;align-items:center;gap:8px;">
                  ${userPhotos.length < 6 ? `
                    <button class="gallery-header-upload-btn" id="btnHeaderUploadPhoto" type="button">
                      <span style="font-size:14px;font-weight:900;line-height:1;">+</span> Добавить
                    </button>
                  ` : ""}
                  ${userPhotos.length > 0 ? `
                    <button class="profile-section-action-link" id="myProfileSeeAllBtn" type="button">Все фото (${userPhotos.length})</button>
                  ` : ""}
                </div>
              </div>
              ${galleryGridHtml}
            </div>

            <!-- Settings and Management Menu Card -->
            <div class="profile-settings-menu-card">
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
              <div class="profile-menu-item" id="btnOpenPrivacySettings">
                <div style="display: flex; align-items: center; gap: 12px;">
                  <span style="font-size: 20px;">🔒</span>
                  <div style="text-align: left;">
                    <div style="font-size: 14.5px; font-weight: 700; color: var(--text-main);">Настройки приватности</div>
                    <div style="font-size: 11.5px; color: var(--text-muted); font-weight: 500;">Онлайн, фото, сообщения, видимость данных</div>
                  </div>
                </div>
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
          </div>
        </div>
      `;

      // Setup Hero Slider gestures
      const heroWrap = document.getElementById("myProfileHeroWrap");
      setupHeroSlider(heroWrap, photos);

      // Hero slides tap -> open fullscreen gallery
      heroWrap?.querySelectorAll(".profile-hero-slide").forEach((slide, i) => {
        slide.addEventListener("click", () => {
          openFullscreenGallery(userPhotos.length > 0 ? userPhotos : photos, i, hasRealPhotos, () => {
            loadProfile();
          });
        });
      });

      // Gallery cells tap -> open fullscreen gallery
      container.querySelectorAll(".gallery-grid-cell").forEach((cell) => {
        cell.addEventListener("click", () => {
          const idx = parseInt(cell.dataset.galleryIndex, 10) || 0;
          openFullscreenGallery(userPhotos, idx, true, () => {
            loadProfile();
          });
        });
      });

      document.getElementById("myProfileSeeAllBtn")?.addEventListener("click", () => {
        openFullscreenGallery(userPhotos, 0, true, () => {
          loadProfile();
        });
      });

      // Delete buttons on individual gallery cells
      const handleDeleteProfilePhoto = async (idx, targetUrl) => {
        triggerHaptic("medium");
        const doDelete = async () => {
          try {
            showAppToast("Удаление фото...");
            const resp = await apiFetch("/api/webapp/profile/photos", {
              method: "DELETE",
              body: JSON.stringify({ index: idx, photo_url: targetUrl }),
            });
            if (resp && resp.status === "ok") {
              triggerHaptic("success");
              showAppToast("Фото удалено");
              await loadProfile();
            } else {
              triggerHaptic("error");
              showAppToast(resp?.detail || "Ошибка при удалении фото");
            }
          } catch (err) {
            console.error("Delete photo error:", err);
            triggerHaptic("error");
            showAppToast("Не удалось удалить фото");
          }
        };

        if (window.Telegram?.WebApp?.showConfirm) {
          window.Telegram.WebApp.showConfirm("Удалить эту фотографию из профиля?", (ok) => {
            if (ok) doDelete();
          });
        } else if (confirm("Удалить эту фотографию из профиля?")) {
          doDelete();
        }
      };

      container.querySelectorAll(".gallery-cell-delete-btn").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const idx = parseInt(btn.dataset.deleteIndex, 10);
          const targetUrl = userPhotos[idx];
          handleDeleteProfilePhoto(idx, targetUrl);
        });
      });

      // Upload cells in gallery
      container.querySelectorAll(".gallery-upload-cell").forEach((cell) => {
        cell.addEventListener("click", (e) => {
          e.stopPropagation();
          triggerHaptic("light");
          document.getElementById("profilePhotoFileInput")?.click();
        });
      });

      // Header upload button
      document.getElementById("btnHeaderUploadPhoto")?.addEventListener("click", (e) => {
        e.stopPropagation();
        triggerHaptic("light");
        document.getElementById("profilePhotoFileInput")?.click();
      });

      // Setup photo file input listener (wire once)
      const fileInput = document.getElementById("profilePhotoFileInput");
      if (fileInput && !fileInput.dataset.wired) {
        fileInput.dataset.wired = "true";
        fileInput.addEventListener("change", async (e) => {
          const file = e.target.files && e.target.files[0];
          e.target.value = "";
          if (!file) return;

          if (!file.type.match(/^image\/(jpeg|jpg|png|webp)$/i)) {
            triggerHaptic("error");
            showAppToast("Поддерживаются только JPG, PNG или WebP");
            return;
          }

          if (file.size > 10 * 1024 * 1024) {
            triggerHaptic("error");
            showAppToast("Максимальный размер фото — 10 МБ");
            return;
          }

          const uploadCell = document.getElementById("galleryUploadCell");
          if (uploadCell) {
            uploadCell.classList.add("loading");
            uploadCell.innerHTML = `
              <div class="gallery-upload-spinner"></div>
              <div class="gallery-upload-text">Загрузка...</div>
            `;
          }
          const headerBtn = document.getElementById("btnHeaderUploadPhoto");
          if (headerBtn) {
            headerBtn.disabled = true;
            headerBtn.textContent = "Загрузка...";
          }

          triggerHaptic("light");
          showAppToast("Загрузка фото...");

          try {
            const formData = new FormData();
            formData.append("photo", file);

            const resp = await apiFetch("/api/webapp/profile/photos", {
              method: "POST",
              body: formData,
            });

            if (resp && resp.status === "ok") {
              triggerHaptic("success");
              showAppToast("Фото успешно добавлено! 📸");
              await loadProfile();
            } else {
              triggerHaptic("error");
              showAppToast(resp?.detail || "Не удалось загрузить фото");
              await loadProfile();
            }
          } catch (err) {
            console.error("Upload error:", err);
            triggerHaptic("error");
            showAppToast("Ошибка соединения при загрузке фото");
            await loadProfile();
          }
        });
      }

      // Read more toggle for own profile
      const readMoreBtn = document.getElementById("myProfileReadMoreBtn");
      const aboutText = document.getElementById("myProfileAboutText");
      if (readMoreBtn && aboutText) {
        readMoreBtn.addEventListener("click", () => {
          triggerHaptic("light");
          const isClamped = aboutText.classList.contains("clamped");
          if (isClamped) {
            aboutText.classList.remove("clamped");
            readMoreBtn.textContent = "Свернуть";
          } else {
            aboutText.classList.add("clamped");
            readMoreBtn.textContent = "Читать дальше";
          }
        });
      }

      // Wire edit buttons
      const handleEdit = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        triggerHaptic("medium");
        openProfileEditModal();
      };
      document.getElementById("btnMyEditTop")?.addEventListener("click", handleEdit);
      document.getElementById("btnMyEditQuick")?.addEventListener("click", handleEdit);

      // Top action buttons
      document.getElementById("btnMyPrivacyTop")?.addEventListener("click", openPrivacyModal);
      document.getElementById("btnMyFiltersTop")?.addEventListener("click", openFiltersModal);

      // Settings list event listeners
      if (u.is_superadmin) {
        document.getElementById("btnOpenAdminHub")?.addEventListener("click", openAdminHubModal);
      }
      document.getElementById("btnToggleProfileMode")?.addEventListener("click", toggleMode);
      document.getElementById("btnOpenSearchFilters")?.addEventListener("click", openFiltersModal);
      document.getElementById("btnOpenPrivacySettings")?.addEventListener("click", openPrivacyModal);
      document.getElementById("btnOpenOnboarding")?.addEventListener("click", () => openOnboarding(true));

      // Notification toggle
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
        openSupportDeck();
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
        } else if (tab === "support") {
          document.getElementById("adminPaneSupport")?.classList.add("active");
          loadAdminSupportTickets();
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

  // ─── 13. Support Deck Controller ───────────────────────────
  let selectedSupportCategory = "bug";
  let selectedSupportFile = null;

  function collectDeviceDiagnostics() {
    let plat = "web";
    if (tg?.platform) {
      plat = tg.platform;
    } else {
      const ua = navigator.userAgent.toLowerCase();
      if (/iphone|ipad|ipod/.test(ua)) plat = "ios";
      else if (/android/.test(ua)) plat = "android";
      else if (/macintosh|mac os x/.test(ua)) plat = "macos";
      else if (/windows/.test(ua)) plat = "windows";
    }

    return {
      platform: plat,
      tg_version: tg?.version || "unknown",
      tg_color_scheme: tg?.colorScheme || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
      user_agent: navigator.userAgent || "",
      screen_width: window.screen?.width || window.innerWidth,
      screen_height: window.screen?.height || window.innerHeight,
      viewport_height: window.innerHeight,
      device_pixel_ratio: window.devicePixelRatio || 1,
      language: navigator.language || "ru",
      active_tab: state.activeTab || "profile",
      client_time: new Date().toISOString()
    };
  }

  function updateTelemetryDisplay() {
    const diag = collectDeviceDiagnostics();
    const content = document.getElementById("supportTelemetryContent");
    if (content) {
      content.innerHTML = `
        <div><b>Платформа:</b> ${escapeHtml(diag.platform.toUpperCase())}</div>
        <div><b>Разрешение:</b> ${diag.screen_width}×${diag.screen_height} (viewport: ${diag.viewport_height}px)</div>
        <div><b>Версия Telegram:</b> ${escapeHtml(diag.tg_version)} (${escapeHtml(diag.tg_color_scheme)})</div>
        <div><b>Вкладка:</b> ${escapeHtml(diag.active_tab)}</div>
        <div style="margin-top:4px;word-break:break-all;color:var(--text-muted);font-size:10px;">${escapeHtml(diag.user_agent)}</div>
      `;
    }
  }

  function openSupportDeck() {
    triggerHaptic("light");
    const modal = document.getElementById("supportDeckModal");
    if (!modal) return;
    modal.classList.add("active");
    updateTelemetryDisplay();
    loadSupportHistory();
  }

  function closeSupportDeck() {
    triggerHaptic("light");
    const modal = document.getElementById("supportDeckModal");
    if (modal) modal.classList.remove("active");
  }

  async function loadSupportHistory() {
    const list = document.getElementById("supportHistoryList");
    const empty = document.getElementById("supportHistoryEmpty");
    const loading = document.getElementById("supportHistoryLoading");
    const countBadge = document.getElementById("supportHistoryCount");

    if (!list) return;
    if (loading) loading.style.display = "flex";
    if (empty) empty.style.display = "none";
    list.innerHTML = "";

    try {
      const data = await apiFetch("/api/webapp/support/tickets");
      if (loading) loading.style.display = "none";

      if (!data || !data.tickets || data.tickets.length === 0) {
        if (empty) empty.style.display = "block";
        if (countBadge) countBadge.style.display = "none";
        return;
      }

      if (countBadge) {
        countBadge.textContent = data.tickets.length;
        countBadge.style.display = "inline-block";
      }

      const catEmojis = {
        bug: "🐛 Ошибка",
        feature: "💡 Идея",
        question: "❓ Вопрос",
        account: "👤 Профиль",
        other: "💬 Другое"
      };

      const statusLabels = {
        open: { text: "🟡 Ожидает ответа", cls: "open" },
        in_progress: { text: "🔵 В работе", cls: "in_progress" },
        resolved: { text: "🟢 Решено", cls: "resolved" },
        closed: { text: "⚫ Закрыто", cls: "closed" }
      };

      list.innerHTML = data.tickets.map(t => {
        const st = statusLabels[t.status] || { text: t.status, cls: "open" };
        const cat = catEmojis[t.category] || t.category;
        const screenshotHtml = t.screenshot_url
          ? `<div style="margin-top:6px;"><a href="${t.screenshot_url}" target="_blank" style="font-size:12px;color:var(--primary);text-decoration:none;">📎 Прикрепленный скриншот</a></div>`
          : "";
        const replyHtml = t.admin_reply
          ? `<div class="support-ticket-reply-box">
              <div class="support-ticket-reply-title">💬 Ответ службы заботы (${t.resolved_at || 'недавно'}):</div>
              <div class="support-ticket-reply-text">${escapeHtml(t.admin_reply)}</div>
             </div>`
          : "";

        return `
          <div class="support-ticket-item">
            <div class="support-ticket-item-header">
              <span class="support-ticket-cat-badge">${cat}</span>
              <span class="support-ticket-status-pill ${st.cls}">${st.text}</span>
            </div>
            <div class="support-ticket-message">${escapeHtml(t.message)}</div>
            ${screenshotHtml}
            ${replyHtml}
            <div style="font-size:10.5px;color:var(--text-muted);margin-top:6px;">🕒 ${t.created_at}</div>
          </div>
        `;
      }).join("");

    } catch (e) {
      if (loading) loading.style.display = "none";
      if (list) list.innerHTML = '<div style="text-align:center;padding:20px;color:red;">Не удалось загрузить историю</div>';
    }
  }

  async function submitSupportTicket() {
    const textEl = document.getElementById("supportMessageText");
    const submitBtn = document.getElementById("supportSubmitBtn");
    if (!textEl || !submitBtn) return;

    const text = textEl.value.trim();
    if (text.length < 5) {
      triggerHaptic("error");
      if (tg && tg.showAlert) {
        tg.showAlert("Пожалуйста, опишите проблему подробнее (минимум 5 символов).");
      } else {
        alert("Пожалуйста, опишите проблему подробнее (минимум 5 символов).");
      }
      textEl.focus();
      return;
    }

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span>⏳ Отправка...</span>';
    triggerHaptic("medium");

    try {
      const formData = new FormData();
      formData.append("category", selectedSupportCategory);
      formData.append("message", text);
      formData.append("device_info", JSON.stringify(collectDeviceDiagnostics()));
      if (selectedSupportFile) {
        formData.append("screenshot", selectedSupportFile);
      }

      await apiFetch("/api/webapp/support/tickets", {
        method: "POST",
        body: formData,
      });

      triggerHaptic("success");
      const successMsg = "Спасибо! Ваше обращение принято в службу заботы. Ответ поступит вам в Telegram и отобразится во вкладке «Мои обращения». ❤️";
      if (tg && tg.showAlert) {
        tg.showAlert(successMsg);
      } else {
        alert(successMsg);
      }

      // Reset form
      textEl.value = "";
      const charCounter = document.getElementById("supportCharCount");
      if (charCounter) charCounter.textContent = "0";
      selectedSupportFile = null;
      const preview = document.getElementById("supportScreenshotPreview");
      const fileInput = document.getElementById("supportScreenshotInput");
      if (preview) preview.style.display = "none";
      if (fileInput) fileInput.value = "";

      // Switch to history tab
      document.querySelectorAll(".support-tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".support-pane").forEach(p => p.classList.remove("active"));
      const historyTabBtn = document.querySelector('.support-tab-btn[data-support-tab="history"]');
      const historyPane = document.getElementById("supportPaneHistory");
      if (historyTabBtn) historyTabBtn.classList.add("active");
      if (historyPane) historyPane.classList.add("active");
      loadSupportHistory();

    } catch (e) {
      triggerHaptic("error");
      const err = e.message || "Ошибка отправки обращения. Попробуйте еще раз.";
      if (tg && tg.showAlert) tg.showAlert(err);
      else alert(err);
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerHTML = '<span>🚀 Отправить в службу заботы</span>';
    }
  }

  function setupSupportListeners() {
    // Support Deck open / close
    document.getElementById("supportDeckCloseBtn")?.addEventListener("click", closeSupportDeck);
    const modal = document.getElementById("supportDeckModal");
    modal?.addEventListener("click", (e) => {
      if (e.target === modal) closeSupportDeck();
    });

    // Support tabs
    document.querySelectorAll(".support-tab-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        triggerHaptic("light");
        const tab = btn.dataset.supportTab;
        document.querySelectorAll(".support-tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".support-pane").forEach(p => p.classList.remove("active"));
        btn.classList.add("active");

        if (tab === "new") {
          document.getElementById("supportPaneNew")?.classList.add("active");
        } else if (tab === "history") {
          document.getElementById("supportPaneHistory")?.classList.add("active");
          loadSupportHistory();
        }
      });
    });

    // Category chips
    document.querySelectorAll(".support-cat-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        triggerHaptic("light");
        document.querySelectorAll(".support-cat-chip").forEach(c => c.classList.remove("active"));
        chip.classList.add("active");
        selectedSupportCategory = chip.dataset.category || "other";
      });
    });

    // Char counter
    const textarea = document.getElementById("supportMessageText");
    const counter = document.getElementById("supportCharCount");
    if (textarea && counter) {
      textarea.addEventListener("input", () => {
        counter.textContent = textarea.value.length;
      });
    }

    // Screenshot file handling
    const fileInput = document.getElementById("supportScreenshotInput");
    const preview = document.getElementById("supportScreenshotPreview");
    const previewImg = document.getElementById("supportScreenshotImg");
    const removeBtn = document.getElementById("supportScreenshotRemoveBtn");

    fileInput?.addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (file) {
        if (file.size > 10 * 1024 * 1024) {
          alert("Размер файла не должен превышать 10 МБ");
          fileInput.value = "";
          return;
        }
        selectedSupportFile = file;
        const reader = new FileReader();
        reader.onload = (re) => {
          if (previewImg) previewImg.src = re.target.result;
          if (preview) preview.style.display = "inline-block";
        };
        reader.readAsDataURL(file);
        triggerHaptic("light");
      }
    });

    removeBtn?.addEventListener("click", () => {
      selectedSupportFile = null;
      if (fileInput) fileInput.value = "";
      if (preview) preview.style.display = "none";
      if (previewImg) previewImg.src = "";
      triggerHaptic("light");
    });

    // Telemetry details accordion toggle
    const telemToggle = document.getElementById("supportTelemetryToggle");
    const telemDetails = document.getElementById("supportTelemetryDetails");
    const telemArrow = document.getElementById("supportTelemetryArrow");
    telemToggle?.addEventListener("click", () => {
      if (telemDetails) {
        const isHidden = telemDetails.style.display === "none";
        telemDetails.style.display = isHidden ? "block" : "none";
        if (telemArrow) telemArrow.textContent = isHidden ? "▴" : "▾";
      }
    });

    // Submit button
    document.getElementById("supportSubmitBtn")?.addEventListener("click", submitSupportTicket);

    // Empty state "Написать обращение" button
    document.getElementById("supportHistoryCreateBtn")?.addEventListener("click", () => {
      document.querySelector('.support-tab-btn[data-support-tab="new"]')?.click();
    });
  }

  // Superadmin Hub: Support tab loader
  async function loadAdminSupportTickets() {
    const container = document.getElementById("adminSupportList");
    if (!container) return;
    container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);">Загрузка обращений...</div>';

    try {
      const data = await apiFetch("/api/webapp/admin/support/tickets");
      if (!data || !data.tickets || data.tickets.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);">🎉 Нет обращений в поддержку</div>';
        return;
      }

      const catNames = {
        bug: "🐛 Ошибка",
        feature: "💡 Идея",
        question: "❓ Вопрос",
        account: "👤 Профиль",
        other: "💬 Другое"
      };

      container.innerHTML = data.tickets.map(t => {
        const cat = catNames[t.category] || t.category;
        const userTitle = t.user_username ? `@${t.user_username}` : `ID ${t.user_id}`;
        const devSnippet = t.device_info ? (t.device_info.length > 50 ? t.device_info.slice(0, 50) + '...' : t.device_info) : 'Девайс не указан';
        const replyInfo = t.admin_reply
          ? `<div style="font-size:12px;color:#059669;margin-bottom:8px;background:rgba(16,185,129,0.1);padding:6px 10px;border-radius:8px;"><b>Ответ:</b> ${escapeHtml(t.admin_reply)}</div>`
          : "";

        return `
          <div class="admin-support-card">
            <div class="admin-support-header">
              <span>#${t.id.slice(0, 8)} · ${cat}</span>
              <span class="badge ${t.status === 'open' ? 'badge-warning' : 'badge-success'}">${t.status}</span>
            </div>
            <div style="font-size:13px;font-weight:700;margin-bottom:4px;">
              ${escapeHtml(t.user_name)} <span style="font-weight:400;color:var(--text-muted);">(${userTitle})</span>
            </div>
            <div class="admin-support-text">${escapeHtml(t.message)}</div>
            ${t.screenshot_url ? `<div style="margin-bottom:8px;"><a href="${t.screenshot_url}" target="_blank" style="font-size:12px;color:var(--primary);">📎 Скриншот</a></div>` : ''}
            ${replyInfo}
            <div class="admin-support-meta">
              <span>🕒 ${t.created_at}</span>
              <span>📱 ${escapeHtml(devSnippet)}</span>
            </div>
            <div style="display:flex;gap:8px;margin-top:6px;">
              <button class="btn-primary" style="padding:6px 12px;font-size:12px;" onclick="window.replyAdminSupportTicket('${t.id}', '${escapeHtml(t.user_name)}')">
                💬 Ответить в TG
              </button>
            </div>
          </div>
        `;
      }).join("");

    } catch (e) {
      container.innerHTML = '<div style="text-align:center;padding:20px;color:red;">Ошибка загрузки обращений</div>';
    }
  }

  window.replyAdminSupportTicket = async function(ticketId, userName) {
    const replyText = prompt(`Ответ для ${userName} (сообщение придет в Telegram):`);
    if (!replyText || !replyText.trim()) return;

    triggerHaptic("medium");
    try {
      await apiFetch(`/api/webapp/admin/support/tickets/${ticketId}/reply`, {
        method: "POST",
        body: JSON.stringify({ reply: replyText.trim(), status: "resolved" })
      });
      triggerHaptic("success");
      loadAdminSupportTickets();
    } catch (e) {
      alert("Ошибка отправки ответа: " + e.message);
    }
  };

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
      openDetailsSheet(cand.user_id, { source: "career" });
    });

    const bannerImg = card.querySelector(".career-card-banner");
    bannerImg?.addEventListener("click", () => {
      openDetailsSheet(cand.user_id, { source: "career" });
    });

    return card;
  }

  async function sendCareerConnect(targetUserId, btn) {
    if (pendingSwipeIds.has(targetUserId)) return;
    pendingSwipeIds.add(targetUserId);
    triggerHaptic("medium");
    if (!btn) {
      pendingSwipeIds.delete(targetUserId);
      return;
    }

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
          btn.onclick = () => {
            const mId = res.match?.match_id || res.match?.id;
            if (mId) {
              openChat(mId);
            } else {
              switchTab("matches");
            }
          };
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
    } finally {
      pendingSwipeIds.delete(targetUserId);
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

  // ─── StudMatch Projects & Startups Controller ───
  let projectsActiveStage = "all";
  let projectsActiveRole = "all";
  let projectsSearchQuery = "";
  let projectsSearchTimeout = null;

  async function loadProjectsFeed() {
    const feedContainer = document.getElementById("projectsFeedList");
    if (!feedContainer) return;

    feedContainer.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 20px;color:var(--text-muted);">
        <div style="font-size:36px;margin-bottom:12px;animation:figmaHeartPulse 1s infinite;">💡</div>
        <div style="font-size:14px;font-weight:600;color:#F59E0B;">Загрузка проектов и стартапов...</div>
      </div>
    `;

    try {
      let url = `/api/webapp/projects/feed?stage=${encodeURIComponent(projectsActiveStage)}&role=${encodeURIComponent(projectsActiveRole)}`;
      if (projectsSearchQuery.trim()) {
        url += `&q=${encodeURIComponent(projectsSearchQuery.trim())}`;
      }

      const res = await apiFetch(url);
      if (!res || !res.projects || res.projects.length === 0) {
        feedContainer.innerHTML = `
          <div class="career-empty-state">
            <div class="career-empty-icon">💡</div>
            <h3 class="career-empty-title">Проекты не найдены</h3>
            <p class="career-empty-desc">
              Попробуйте изменить стадию, роль или сбросить поисковый фильтр.
            </p>
            <button class="btn-primary" id="resetProjectsFiltersBtn" style="background:#F59E0B;margin-top:10px;width:auto;padding:10px 20px;">
              🔄 Показать все проекты
            </button>
          </div>
        `;
        document.getElementById("resetProjectsFiltersBtn")?.addEventListener("click", () => {
          projectsActiveStage = "all";
          projectsActiveRole = "all";
          projectsSearchQuery = "";
          const searchInput = document.getElementById("projectsSearchInput");
          if (searchInput) searchInput.value = "";
          document.querySelectorAll("#projectsStageChips .project-stage-chip").forEach((c) => {
            c.classList.toggle("active", c.dataset.stage === "all");
          });
          document.querySelectorAll("#projectsRoleChips .project-role-chip").forEach((c) => {
            c.classList.toggle("active", c.dataset.role === "all");
          });
          loadProjectsFeed();
        });
        return;
      }

      feedContainer.innerHTML = "";
      res.projects.forEach((proj) => {
        const card = renderProjectCatalogCard(proj);
        feedContainer.appendChild(card);
      });
    } catch (e) {
      console.error("[StudMatch] Projects feed error:", e);
      feedContainer.innerHTML = `
        <div class="career-empty-state">
          <div class="career-empty-icon">⚠️</div>
          <h3 class="career-empty-title">Ошибка загрузки проектов</h3>
          <p class="career-empty-desc">Не удалось связаться с сервером. Попробуйте еще раз.</p>
          <button class="btn-primary" id="retryProjectsFeedBtn" style="background:#F59E0B;margin-top:10px;width:auto;padding:10px 20px;">
            🔄 Повторить
          </button>
        </div>
      `;
      document.getElementById("retryProjectsFeedBtn")?.addEventListener("click", () => loadProjectsFeed());
    }
  }

  function renderProjectCatalogCard(proj) {
    const card = document.createElement("div");
    card.className = "project-catalog-card";
    card.dataset.projectId = proj.id;

    const stageMap = {
      idea: { label: "💡 Идея", cls: "stage-idea" },
      mvp: { label: "🛠 MVP / Прототип", cls: "stage-mvp" },
      launched: { label: "🚀 Запущен", cls: "stage-launched" },
      hackathon: { label: "🏆 Хакатон", cls: "stage-hackathon" },
    };
    const stageInfo = stageMap[proj.stage] || { label: "💡 Проект", cls: "stage-idea" };

    const rolesList = parseRolesList(proj.required_roles);
    const rolesHtml = rolesList.map((r) => `<span class="project-role-tag">#${escapeHtml(r)}</span>`).join("");

    const founder = proj.founder || {};
    const founderAvatar = founder.avatar_url || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80";
    const founderUni = [founder.university, founder.year ? `${founder.year} курс` : ""].filter(Boolean).join(" • ");

    const isMyProject = state.currentUser && (String(state.currentUser.id) === String(proj.founder?.id || proj.user_id));

    let actionBtnHtml = "";
    if (isMyProject) {
      actionBtnHtml = `
        <button class="btn-project-apply" style="background:rgba(245,158,11,0.2);color:#F59E0B;" data-action="edit">
          ✏️ Мой проект
        </button>
      `;
    } else {
      actionBtnHtml = `
        <button class="btn-project-apply" data-action="apply">
          🚀 Хочу в команду!
        </button>
      `;
    }

    card.innerHTML = `
      <div class="project-catalog-card-header">
        <div>
          <span class="project-stage-badge ${stageInfo.cls}">${stageInfo.label}</span>
          <h4 class="project-catalog-card-title">${escapeHtml(proj.title)}</h4>
        </div>
        ${proj.conditions ? `<span class="project-conditions-badge">${escapeHtml(proj.conditions)}</span>` : ""}
      </div>

      <div class="project-catalog-card-pitch">
        ${escapeHtml(proj.pitch)}
      </div>

      <p class="project-catalog-card-desc">
        ${escapeHtml(proj.description || "")}
      </p>

      ${rolesHtml ? `<div class="project-roles-tags">${rolesHtml}</div>` : ""}

      <div class="project-catalog-card-footer">
        <div class="project-catalog-founder-wrap">
          <img src="${escapeHtml(founderAvatar)}" class="project-catalog-founder-avatar" alt="${escapeHtml(founder.name)}" onerror="this.src='/static/webapp/assets/mascot_hero_3d.jpg';" />
          <div class="project-catalog-founder-info">
            <span class="project-catalog-founder-name">${escapeHtml(founder.name)}</span>
            ${founderUni ? `<span class="project-catalog-founder-uni">${escapeHtml(founderUni)}</span>` : ""}
          </div>
        </div>
        <div class="project-catalog-card-btns">
          <button class="btn-project-details" data-action="details">
            📄 Подробнее
          </button>
          ${actionBtnHtml}
        </div>
      </div>
    `;

    card.querySelector("[data-action='details']")?.addEventListener("click", () => {
      openProjectDetailsModal(proj);
    });

    const applyBtn = card.querySelector("[data-action='apply']");
    applyBtn?.addEventListener("click", async () => {
      triggerHaptic("medium");
      applyBtn.disabled = true;
      applyBtn.innerHTML = "⏳ Отправка...";
      try {
        const res = await apiFetch("/api/webapp/projects/swipe", {
          method: "POST",
          body: JSON.stringify({ project_id: proj.id, action: "like" }),
        });
        if (res && res.status === "ok") {
          triggerHaptic("success");
          applyBtn.className = "btn-project-apply connected";
          applyBtn.innerHTML = "✓ Заявка отправлена!";
          if (res.is_match) {
            showMatchPopup({
              name: proj.founder?.name || "Фаундер стартапа",
              photo_url: proj.founder?.avatar_url,
              match_id: res.match?.id || res.match?.match_id
            }, proj);
          }
        } else {
          applyBtn.disabled = false;
          applyBtn.innerHTML = "🚀 Хочу в команду!";
        }
      } catch (err) {
        console.error("Apply project error:", err);
        applyBtn.disabled = false;
        applyBtn.innerHTML = "🚀 Хочу в команду!";
      }
    });

    const editBtn = card.querySelector("[data-action='edit']");
    editBtn?.addEventListener("click", () => {
      openProjectCreateModal(proj);
    });

    return card;
  }

  function openProjectDetailsModal(proj) {
    const modal = document.getElementById("projectDetailsModal");
    if (!modal) return;
    triggerHaptic("medium");

    const stageMap = {
      idea: { label: "💡 Идея", cls: "stage-idea" },
      mvp: { label: "🛠 MVP / Прототип", cls: "stage-mvp" },
      launched: { label: "🚀 Запущен", cls: "stage-launched" },
      hackathon: { label: "🏆 Хакатон", cls: "stage-hackathon" },
    };
    const stageInfo = stageMap[proj.stage] || { label: "💡 Проект", cls: "stage-idea" };

    const stageBadge = document.getElementById("detailProjectStageBadge");
    if (stageBadge) {
      stageBadge.className = `project-stage-badge ${stageInfo.cls}`;
      stageBadge.textContent = stageInfo.label;
    }

    const titleEl = document.getElementById("detailProjectTitle");
    if (titleEl) titleEl.textContent = proj.title || "Без названия";

    const founder = proj.founder || {};
    const avatarEl = document.getElementById("detailFounderAvatar");
    if (avatarEl) {
      avatarEl.src = founder.avatar_url || "/static/webapp/assets/mascot_hero_3d.jpg";
    }
    const nameEl = document.getElementById("detailFounderName");
    if (nameEl) nameEl.textContent = founder.name || "Фаундер";
    const uniEl = document.getElementById("detailFounderUni");
    if (uniEl) {
      uniEl.textContent = [founder.university, founder.year ? `${founder.year} курс` : "", founder.major].filter(Boolean).join(" • ");
    }

    const pitchEl = document.getElementById("detailProjectPitch");
    if (pitchEl) pitchEl.textContent = proj.pitch || "";

    const descEl = document.getElementById("detailProjectDesc");
    if (descEl) descEl.textContent = proj.description || "";

    const rolesContainer = document.getElementById("detailProjectRoles");
    if (rolesContainer) {
      const roles = parseRolesList(proj.required_roles);
      rolesContainer.innerHTML = roles.map((r) => `<span class="project-role-tag">#${escapeHtml(r)}</span>`).join("");
    }

    const condEl = document.getElementById("detailProjectConditions");
    if (condEl) condEl.textContent = proj.conditions || "По договорённости";

    const demoLink = document.getElementById("detailDemoLink");
    if (demoLink) {
      if (proj.demo_url) {
        demoLink.href = proj.demo_url;
        demoLink.style.display = "inline-flex";
      } else {
        demoLink.style.display = "none";
      }
    }

    const deckLink = document.getElementById("detailDeckLink");
    if (deckLink) {
      if (proj.pitchdeck_url) {
        deckLink.href = proj.pitchdeck_url;
        deckLink.style.display = "inline-flex";
      } else {
        deckLink.style.display = "none";
      }
    }

    const footer = document.getElementById("detailActionsFooter");
    const isMe = state.currentUser && (String(state.currentUser.id) === String(proj.founder?.id || proj.user_id));
    if (footer) {
      if (isMe) {
        footer.innerHTML = `
          <button class="btn-primary" id="detailEditProjectBtn" style="background:linear-gradient(135deg, #F59E0B, #D97706);width:100%;">
            ✏️ Редактировать проект
          </button>
        `;
        document.getElementById("detailEditProjectBtn")?.addEventListener("click", () => {
          modal.style.display = "none";
          openProjectCreateModal(proj);
        });
      } else {
        footer.innerHTML = `
          <button class="btn-secondary" id="detailSkipBtn">✕ Пропустить</button>
          <button class="btn-primary" id="detailLikeBtn" style="background: linear-gradient(135deg, #F59E0B, #D97706);">
            👍 Хочу в команду!
          </button>
        `;
        document.getElementById("detailSkipBtn")?.addEventListener("click", () => {
          modal.style.display = "none";
          sendProjectSwipe(proj.id, "skip", null, proj);
        });
        document.getElementById("detailLikeBtn")?.addEventListener("click", () => {
          modal.style.display = "none";
          sendProjectSwipe(proj.id, "like", null, proj);
        });
      }
    }

    modal.style.display = "flex";
  }

  async function loadMyProjects() {
    const listContainer = document.getElementById("projectsMyList");
    if (!listContainer) return;

    listContainer.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 20px;color:var(--text-muted);">
        <div style="font-size:36px;margin-bottom:12px;animation:figmaHeartPulse 1s infinite;">📂</div>
        <div style="font-size:14px;font-weight:600;color:#F59E0B;">Загрузка ваших проектов...</div>
      </div>
    `;

    try {
      const res = await apiFetch("/api/webapp/projects/my");
      if (!res || !res.projects || res.projects.length === 0) {
        listContainer.innerHTML = `
          <div class="career-empty-state">
            <div class="career-empty-icon">💡</div>
            <h3 class="career-empty-title">У вас пока нет проектов</h3>
            <p class="career-empty-desc">
              Создайте свой стартап, проект или команду для хакатона и найдите лучших единомышленников в StudMatch!
            </p>
            <button class="btn-primary" id="btnCreateFirstProject" style="background:linear-gradient(135deg, #F59E0B, #D97706);margin-top:10px;width:auto;padding:12px 24px;">
              🚀 Создать первый проект
            </button>
          </div>
        `;
        document.getElementById("btnCreateFirstProject")?.addEventListener("click", () => {
          openProjectCreateModal();
        });
        return;
      }

      listContainer.innerHTML = "";
      res.projects.forEach((proj) => {
        const item = document.createElement("div");
        item.className = "project-my-card";
        item.dataset.projectId = proj.id;

        const candCount = proj.candidates_count || 0;
        const candLabel = candCount === 1 ? "1 отклик" : `${candCount} откликов`;

        item.innerHTML = `
          <div class="project-my-card-header">
            <div>
              <h4 class="project-my-card-title">${escapeHtml(proj.title)}</h4>
              <span class="project-stage-badge" style="margin-top:4px;">${escapeHtml(proj.stage.toUpperCase())}</span>
            </div>
            <button class="project-my-cand-badge" data-action="candidates">
              👥 ${candLabel}
            </button>
          </div>
          <p class="project-my-card-pitch">${escapeHtml(proj.pitch)}</p>
          <div class="project-my-card-actions">
            <button class="btn-secondary-sm" data-action="edit">✏️ Изменить</button>
            <button class="btn-secondary-sm" data-action="candidates">👥 Отклики (${candCount})</button>
            <button class="btn-secondary-sm" style="color:#EF4444;" data-action="delete">🗑 Удалить</button>
          </div>
        `;

        item.querySelectorAll("[data-action='candidates']").forEach((btn) => {
          btn.addEventListener("click", () => {
            openFounderCandidatesModal(proj.id, proj.title);
          });
        });

        item.querySelector("[data-action='edit']")?.addEventListener("click", () => {
          openProjectCreateModal(proj);
        });

        item.querySelector("[data-action='delete']")?.addEventListener("click", async () => {
          if (!confirm(`Вы действительно хотите удалить проект «${proj.title}»?`)) return;
          try {
            triggerHaptic("warning");
            const dRes = await apiFetch(`/api/webapp/projects/${proj.id}`, { method: "DELETE" });
            if (dRes && dRes.status === "ok") {
              triggerHaptic("success");
              showAppToast("Проект успешно удалён");
              loadMyProjects();
            }
          } catch (delErr) {
            console.error("Delete project error:", delErr);
            showAppToast("Ошибка при удалении проекта");
          }
        });

        listContainer.appendChild(item);
      });
    } catch (e) {
      console.error("[StudMatch] Load my projects error:", e);
      listContainer.innerHTML = `
        <div class="career-empty-state">
          <div class="career-empty-icon">⚠️</div>
          <h3 class="career-empty-title">Ошибка сети</h3>
          <p class="career-empty-desc">Не удалось загрузить ваши проекты.</p>
        </div>
      `;
    }
  }

  async function openFounderCandidatesModal(projectId, projectTitle) {
    const modal = document.getElementById("founderCandidatesModal");
    const titleEl = document.getElementById("candidatesModalTitle");
    const listEl = document.getElementById("founderCandidatesList");
    if (!modal || !listEl) return;

    if (titleEl) titleEl.textContent = `Отклики: ${projectTitle}`;
    listEl.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 20px;color:var(--text-muted);">
        <div style="font-size:36px;margin-bottom:12px;animation:figmaHeartPulse 1s infinite;">👥</div>
        <div style="font-size:14px;font-weight:600;color:#F59E0B;">Загрузка кандидатов...</div>
      </div>
    `;
    modal.style.display = "flex";

    try {
      const res = await apiFetch(`/api/webapp/projects/${projectId}/candidates`);
      if (!res || !res.candidates || res.candidates.length === 0) {
        listEl.innerHTML = `
          <div class="career-empty-state">
            <div class="career-empty-icon">✨</div>
            <h3 class="career-empty-title">Пока нет новых откликов</h3>
            <p class="career-empty-desc">
              Как только студенты проявят интерес к проекту, их заявки и профили появятся здесь.
            </p>
          </div>
        `;
        return;
      }

      listEl.innerHTML = "";
      res.candidates.forEach((cand) => {
        const row = document.createElement("div");
        row.className = "founder-candidate-card";

        const candUni = [cand.university, cand.year ? `${cand.year} курс` : "", cand.major].filter(Boolean).join(" • ");

        row.innerHTML = `
          <div class="founder-candidate-header">
            <img src="${escapeHtml(cand.avatar_url)}" class="founder-candidate-avatar" alt="${escapeHtml(cand.name)}" onerror="this.src='/static/webapp/assets/mascot_hero_3d.jpg';" />
            <div class="founder-candidate-info">
              <h4 class="founder-candidate-name">${escapeHtml(cand.name)}</h4>
              ${candUni ? `<p class="founder-candidate-uni">${escapeHtml(candUni)}</p>` : ""}
            </div>
          </div>

          ${cand.project_role ? `<div class="founder-candidate-badge">🎯 Роль: ${escapeHtml(cand.project_role)}</div>` : ""}
          ${cand.project_skills ? `<div class="founder-candidate-skills">💻 <b>Стек:</b> ${escapeHtml(cand.project_skills)}</div>` : ""}
          ${cand.project_bio ? `<p class="founder-candidate-bio">"${escapeHtml(cand.project_bio)}"</p>` : ""}
          ${cand.comment ? `<div class="founder-candidate-pitch-box">💬 <b>Питч:</b> ${escapeHtml(cand.comment)}</div>` : ""}

          <div class="founder-candidate-actions">
            <button class="btn-secondary-sm" data-action="skip">✕ Пропустить</button>
            <button class="btn-primary-sm" style="background:linear-gradient(135deg, #F59E0B, #D97706);" data-action="accept">🤝 В команду!</button>
          </div>
        `;

        const skipBtn = row.querySelector("[data-action='skip']");
        skipBtn?.addEventListener("click", async () => {
          triggerHaptic("light");
          row.style.opacity = "0.4";
          try {
            await apiFetch(`/api/webapp/projects/${projectId}/swipe_candidate`, {
              method: "POST",
              body: JSON.stringify({ candidate_user_id: cand.user_id, action: "skip" }),
            });
            row.remove();
            if (listEl.children.length === 0) {
              openFounderCandidatesModal(projectId, projectTitle);
            }
          } catch (e) {
            console.error("Skip candidate error:", e);
            row.style.opacity = "1";
          }
        });

        const acceptBtn = row.querySelector("[data-action='accept']");
        acceptBtn?.addEventListener("click", async () => {
          triggerHaptic("success");
          acceptBtn.disabled = true;
          acceptBtn.innerHTML = "⏳ Принимаем...";
          try {
            const mRes = await apiFetch(`/api/webapp/projects/${projectId}/swipe_candidate`, {
              method: "POST",
              body: JSON.stringify({ candidate_user_id: cand.user_id, action: "like" }),
            });
            if (mRes && mRes.status === "ok") {
              row.remove();
              modal.style.display = "none";
              showMatchPopup({
                name: cand.name,
                photo_url: cand.avatar_url,
                match_id: mRes.match?.id || mRes.match?.match_id
              });
            }
          } catch (e) {
            console.error("Accept candidate error:", e);
            acceptBtn.disabled = false;
            acceptBtn.innerHTML = "🤝 В команду!";
          }
        });

        listEl.appendChild(row);
      });
    } catch (e) {
      console.error("[StudMatch] Load candidates error:", e);
      listEl.innerHTML = `<div class="career-empty-state"><p class="career-empty-desc">Ошибка загрузки кандидатов</p></div>`;
    }
  }

  function openProjectCreateModal(projectToEdit = null) {
    const modal = document.getElementById("projectCreateModal");
    if (!modal) return;
    triggerHaptic("medium");

    const titleEl = document.getElementById("projectModalTitle");
    const editIdInput = document.getElementById("projectEditId");
    const titleInput = document.getElementById("projectInputTitle");
    const pitchInput = document.getElementById("projectInputPitch");
    const descInput = document.getElementById("projectInputDesc");
    const stageSelect = document.getElementById("projectInputStage");
    const condSelect = document.getElementById("projectInputConditions");
    const rolesInput = document.getElementById("projectInputRoles");
    const demoInput = document.getElementById("projectInputDemo");
    const deckUrlInput = document.getElementById("projectInputDeckUrl");
    const deckNameEl = document.getElementById("projectDeckFileName");
    const saveBtn = document.getElementById("saveProjectBtn");

    if (projectToEdit) {
      if (titleEl) titleEl.textContent = "Редактировать проект";
      if (editIdInput) editIdInput.value = projectToEdit.id;
      if (titleInput) titleInput.value = projectToEdit.title || "";
      if (pitchInput) pitchInput.value = projectToEdit.pitch || "";
      if (descInput) descInput.value = projectToEdit.description || "";
      if (stageSelect) stageSelect.value = projectToEdit.stage || "idea";
      if (condSelect) condSelect.value = projectToEdit.conditions || "За опыт / pet-проект";
      if (rolesInput) {
        rolesInput.value = Array.isArray(projectToEdit.required_roles)
          ? projectToEdit.required_roles.join(", ")
          : (projectToEdit.required_roles || "");
      }
      if (demoInput) demoInput.value = projectToEdit.demo_url || "";
      if (deckUrlInput) deckUrlInput.value = projectToEdit.pitchdeck_url || "";
      if (deckNameEl) {
        deckNameEl.textContent = projectToEdit.pitchdeck_url ? "✓ Презентация прикреплена" : "Прикрепить презентацию / питчдек (PDF до 20MB)";
      }
      if (saveBtn) saveBtn.textContent = "💾 Сохранить изменения";
    } else {
      if (titleEl) titleEl.textContent = "Новый проект";
      if (editIdInput) editIdInput.value = "";
      if (titleInput) titleInput.value = "";
      if (pitchInput) pitchInput.value = "";
      if (descInput) descInput.value = "";
      if (stageSelect) stageSelect.value = "idea";
      if (condSelect) condSelect.value = "За опыт / pet-проект";
      if (rolesInput) rolesInput.value = "";
      if (demoInput) demoInput.value = "";
      if (deckUrlInput) deckUrlInput.value = "";
      if (deckNameEl) deckNameEl.textContent = "Прикрепить презентацию / питчдек (PDF до 20MB)";
      if (saveBtn) saveBtn.textContent = "🚀 Опубликовать проект";
    }

    modal.style.display = "flex";
  }

  async function saveProject() {
    const editId = document.getElementById("projectEditId")?.value;
    const title = document.getElementById("projectInputTitle")?.value.trim() || "";
    const pitch = document.getElementById("projectInputPitch")?.value.trim() || "";
    const description = document.getElementById("projectInputDesc")?.value.trim() || "";
    const stage = document.getElementById("projectInputStage")?.value || "idea";
    const conditions = document.getElementById("projectInputConditions")?.value || "За опыт / pet-проект";
    const rawRoles = document.getElementById("projectInputRoles")?.value.trim() || "";
    const required_roles = rawRoles ? rawRoles.split(",").map((r) => r.trim()).filter(Boolean) : [];
    const demo_url = document.getElementById("projectInputDemo")?.value.trim() || null;
    const pitchdeck_url = document.getElementById("projectInputDeckUrl")?.value.trim() || null;
    const saveBtn = document.getElementById("saveProjectBtn");

    if (!title) {
      showAppToast("Укажите название проекта");
      return;
    }
    if (!pitch) {
      showAppToast("Укажите краткий питч проекта");
      return;
    }
    if (!description) {
      showAppToast("Опишите ваш проект и цели");
      return;
    }

    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.innerHTML = "⏳ Сохранение...";
    }

    const payload = {
      title,
      pitch,
      description,
      stage,
      conditions,
      required_roles,
      demo_url,
      pitchdeck_url,
    };

    try {
      let res = null;
      if (editId) {
        res = await apiFetch(`/api/webapp/projects/${editId}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
      } else {
        res = await apiFetch("/api/webapp/projects", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }

      if (res && res.status === "ok") {
        triggerHaptic("success");
        showAppToast(editId ? "Проект успешно обновлён! ✨" : "Проект успешно опубликован! 🚀");
        document.getElementById("projectCreateModal").style.display = "none";
        if (currentProjectsView === "feed") {
          loadProjectsFeed();
        } else if (currentProjectsView === "my") {
          loadMyProjects();
        } else {
          loadFeed();
        }
      } else {
        showAppToast(res?.detail || "Не удалось сохранить проект");
      }
    } catch (err) {
      console.error("Save project error:", err);
      showAppToast("Ошибка сети при сохранении проекта");
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.innerHTML = editId ? "💾 Сохранить изменения" : "🚀 Опубликовать проект";
      }
    }
  }

  function setupProjectsListeners() {
    // 1. Projects Subnav toggle buttons
    document.getElementById("btnProjectsSubnavSwipe")?.addEventListener("click", () => {
      setProjectsSubnavView("swipe");
    });
    document.getElementById("btnProjectsSubnavFeed")?.addEventListener("click", () => {
      setProjectsSubnavView("feed");
    });
    document.getElementById("btnProjectsSubnavMy")?.addEventListener("click", () => {
      setProjectsSubnavView("my");
    });

    // 2. Stage chips
    document.querySelectorAll("#projectsStageChips .project-stage-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        triggerHaptic("light");
        document.querySelectorAll("#projectsStageChips .project-stage-chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        projectsActiveStage = chip.dataset.stage || "all";
        loadProjectsFeed();
      });
    });

    // 3. Role chips
    document.querySelectorAll("#projectsRoleChips .project-role-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        triggerHaptic("light");
        document.querySelectorAll("#projectsRoleChips .project-role-chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        projectsActiveRole = chip.dataset.role || "all";
        loadProjectsFeed();
      });
    });

    // 4. Search input with debounce
    const searchInput = document.getElementById("projectsSearchInput");
    const clearBtn = document.getElementById("projectsSearchClearBtn");

    searchInput?.addEventListener("input", (e) => {
      const val = e.target.value;
      if (clearBtn) clearBtn.style.display = val ? "block" : "none";
      if (projectsSearchTimeout) clearTimeout(projectsSearchTimeout);
      projectsSearchTimeout = setTimeout(() => {
        projectsSearchQuery = val;
        loadProjectsFeed();
      }, 350);
    });

    clearBtn?.addEventListener("click", () => {
      if (searchInput) searchInput.value = "";
      clearBtn.style.display = "none";
      projectsSearchQuery = "";
      loadProjectsFeed();
    });

    // 5. Create project triggers
    document.getElementById("openProjectCreateBtn")?.addEventListener("click", () => openProjectCreateModal());
    document.getElementById("projectsComposerCard")?.addEventListener("click", () => openProjectCreateModal());
    document.getElementById("btnMyCreateProject")?.addEventListener("click", () => openProjectCreateModal());

    // 6. Project Create Modal close & save
    document.getElementById("projectCreateCloseBtn")?.addEventListener("click", () => {
      document.getElementById("projectCreateModal").style.display = "none";
    });
    document.getElementById("saveProjectBtn")?.addEventListener("click", saveProject);

    // 7. Pitchdeck File Upload Trigger
    const uploadTrigger = document.getElementById("projectDeckUploadTrigger");
    const fileInput = document.getElementById("projectInputDeckFile");
    const deckFileName = document.getElementById("projectDeckFileName");
    const deckUrlInput = document.getElementById("projectInputDeckUrl");

    uploadTrigger?.addEventListener("click", () => {
      fileInput?.click();
    });

    fileInput?.addEventListener("change", async (e) => {
      const file = e.target.files?.[0];
      if (!file) return;

      if (file.size > 20 * 1024 * 1024) {
        showAppToast("Файл слишком большой (максимум 20MB)");
        fileInput.value = "";
        return;
      }

      if (deckFileName) deckFileName.textContent = `⏳ Загрузка ${file.name}...`;

      try {
        const formData = new FormData();
        formData.append("file", file);

        const initData = window.Telegram?.WebApp?.initData || "";
        const token = localStorage.getItem("studmatch_token") || "";

        const headers = {};
        if (initData) headers["X-Telegram-Init-Data"] = initData;
        if (token) headers["Authorization"] = `Bearer ${token}`;

        const resp = await fetch("/api/webapp/projects/upload_deck", {
          method: "POST",
          headers,
          body: formData,
        });

        const resData = await resp.json();
        if (resp.ok && resData.url) {
          triggerHaptic("success");
          if (deckUrlInput) deckUrlInput.value = resData.url;
          if (deckFileName) deckFileName.textContent = `✓ ${resData.filename || file.name}`;
          showAppToast("Презентация прикреплена! 📄");
        } else {
          throw new Error(resData.detail || "Upload error");
        }
      } catch (err) {
        console.error("Upload deck error:", err);
        triggerHaptic("error");
        if (deckFileName) deckFileName.textContent = "Ошибка загрузки. Попробуйте еще раз";
        showAppToast("Не удалось загрузить файл");
      }
    });

    // 8. Project Details Modal close
    document.getElementById("projectDetailsCloseBtn")?.addEventListener("click", () => {
      document.getElementById("projectDetailsModal").style.display = "none";
    });

    // 9. Founder Candidates Modal close
    document.getElementById("founderCandidatesCloseBtn")?.addEventListener("click", () => {
      document.getElementById("founderCandidatesModal").style.display = "none";
    });
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
          if (uid) openDetailsSheet(uid, { source: "hall" });
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
            if (uid) openDetailsSheet(uid, { source: "hall" });
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

    const achBtn = document.getElementById("openBotAchievementsBtn");
    if (achBtn) {
      achBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        triggerHaptic("medium");

        const originalHtml = achBtn.innerHTML;
        achBtn.disabled = true;
        achBtn.innerHTML = `<span>⏳ Отправляем боту...</span>`;

        const botUsername = window.BOT_USERNAME || "edudating_bot";
        const fallbackLink = `https://t.me/${botUsername}?start=achievements`;

        try {
          const resp = await apiFetch("/api/webapp/achievements/request-bot-upload", {
            method: "POST",
          });

          if (resp && resp.status === "ok") {
            triggerHaptic("success");
            achBtn.innerHTML = `<span>✅ Готово! Бот ждёт в чате</span>`;
            setTimeout(() => {
              if (tg && tg.close) {
                try {
                  tg.close();
                } catch (closeErr) {
                  console.warn("Could not close Telegram WebApp:", closeErr);
                }
              }
            }, 500);
            return;
          }

          if (resp && resp.status === "need_profile") {
            triggerHaptic("warning");
            const msg = resp.message || "Сначала заполни анкету в боте!";
            if (tg && tg.showAlert) {
              tg.showAlert(msg);
            } else {
              alert(msg);
            }
            achBtn.disabled = false;
            achBtn.innerHTML = originalHtml;
            return;
          }

          throw new Error(resp?.message || "Server error");
        } catch (err) {
          console.warn("Server trigger failed, falling back to openTelegramLink:", err);
          if (tg && tg.openTelegramLink) {
            tg.openTelegramLink(fallbackLink);
          } else {
            window.open(fallbackLink, "_blank");
          }
          setTimeout(() => {
            if (tg && tg.close) {
              try {
                tg.close();
              } catch (closeErr) {
                console.warn("Could not close Telegram WebApp:", closeErr);
              }
            }
          }, 500);
        } finally {
          setTimeout(() => {
            achBtn.disabled = false;
            achBtn.innerHTML = originalHtml;
          }, 3000);
        }
      });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    try {
      const savedMode = localStorage.getItem("studmatch_mode");
      if (savedMode && ["dating", "career", "projects"].includes(savedMode)) {
        document.getElementById("pillDating")?.classList.toggle("active", savedMode === "dating");
        document.getElementById("pillCareer")?.classList.toggle("active", savedMode === "career");
        document.getElementById("pillProjects")?.classList.toggle("active", savedMode === "projects");
        document.body.classList.toggle("career-theme", savedMode === "career");
        document.body.classList.toggle("projects-theme", savedMode === "projects");
        if (savedMode === "projects") {
          const projectsSubnav = document.getElementById("projectsSubnavToggle");
          if (projectsSubnav) projectsSubnav.style.display = "flex";
        } else if (savedMode === "career") {
          const careerSubnav = document.getElementById("careerSubnavToggle");
          if (careerSubnav) careerSubnav.style.display = "flex";
        }
      }
    } catch (e) {}

    setupNavigation();
    setupCareerListeners();
    setupProjectsListeners();
    setupMaintenanceListeners();
    setupHallOfFameListeners();
    if (window.MAINTENANCE_DATA) {
      updateMaintenanceUI(window.MAINTENANCE_DATA);
    }
    authenticateUser();
  });
})();
