/**
 * StudMatch Telegram Mini App (TWA / WebApp) Core Client
 * Touch-driven swipe engine, Telegram initData auth, Haptic feedback, tabs & matching.
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
  };

  // DOM Elements
  const deckContainer = document.getElementById("cardDeck");
  const deckEmpty = document.getElementById("deckEmpty");
  const matchModal = document.getElementById("matchModal");
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
      // Re-auth
      await authenticateUser();
      return;
    }
    return await res.json();
  }

  // 1. Авторизация
  async function authenticateUser() {
    const initData = tg?.initData || "dev_mock";
    try {
      const res = await fetch("/api/webapp/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: initData }),
      });
      const data = await res.json();
      if (data.status === "ok") {
        state.token = data.token;
        state.currentUser = data.user;
        localStorage.setItem("studmatch_token", data.token);
        updateHeaderUser();
        loadFeed();
      }
    } catch (err) {
      console.error("Auth error:", err);
    }
  }

  function updateHeaderUser() {
    const modeBadge = document.getElementById("headerModeBadge");
    if (modeBadge && state.currentUser) {
      const isCareer = state.currentUser.mode === "career";
      modeBadge.textContent = isCareer ? "💼 Карьера" : "💘 Знакомства";
    }
  }

  // 2. Навигация по табам (Explore, Likes, Matches, Profile)
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
      const data = await apiFetch("/api/webapp/feed");
      if (data && data.profiles) {
        state.feed = data.profiles;
        state.currentCardIndex = 0;
        renderCardStack();
      }
    } catch (err) {
      console.error("Feed error:", err);
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

  function createCardElement(profile, isTop) {
    const card = document.createElement("div");
    card.className = "swipe-card";
    card.dataset.userId = profile.user_id;

    const photoUrl = profile.photos && profile.photos.length > 0
      ? profile.photos[0]
      : "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80";

    const verifiedBadge = profile.is_verified ? '<span class="card-badge verified">🎓 ВУЗ</span>' : "";
    const premiumBadge = profile.is_premium ? '<span class="card-badge premium">💎 VIP</span>' : "";
    const yearStr = profile.year ? `${profile.year} курс` : "";
    const univStr = profile.university ? profile.university : "";

    const tagsHtml = (profile.tags || [])
      .slice(0, 3)
      .map((t) => `<span class="card-tag">${t.emoji || "🏷"} ${t.name}</span>`)
      .join("");

    card.innerHTML = `
      <img src="${photoUrl}" class="card-photo-bg" alt="${profile.name}" />
      <div class="card-gradient-overlay"></div>

      <div class="stamp like-stamp">LIKE</div>
      <div class="stamp nope-stamp">SKIP</div>
      <div class="stamp super-stamp">SUPER</div>

      <div class="card-top-bar">
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
        </div>
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

    // Кнопки действий
    card.querySelectorAll(".action-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const action = btn.dataset.action;
        handleSwipeAction(profile, action);
      });
    });

    return card;
  }

  // 4. Сенсорный свайп-движок (Touch & Mouse Drag)
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

      // Пороги срабатывания
      if (currentX > 90) {
        finishSwipe(card, profile, "like", 500, 0);
      } else if (currentX < -90) {
        finishSwipe(card, profile, "skip", -500, 0);
      } else if (currentY < -100 && Math.abs(currentX) < 60) {
        finishSwipe(card, profile, "superlike", 0, -600);
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

  function finishSwipe(card, profile, action, exitX, exitY) {
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

      // Отправка свайпа на бэкенд
      sendSwipe(profile.user_id, action);
    }, 300);
  }

  function handleSwipeAction(profile, action) {
    if (state.isSwiping) return;
    const topCard = deckContainer.querySelector(".swipe-card:last-child");
    if (!topCard) return;

    if (action === "like") {
      finishSwipe(topCard, profile, "like", 500, 0);
    } else if (action === "superlike") {
      finishSwipe(topCard, profile, "superlike", 0, -600);
    } else {
      finishSwipe(topCard, profile, "skip", -500, 0);
    }
  }

  async function sendSwipe(targetId, action) {
    try {
      const res = await apiFetch("/api/webapp/swipe", {
        method: "POST",
        body: JSON.stringify({ target_id: targetId, action: action }),
      });
      if (res && res.is_match && res.match) {
        showMatchPopup(res.match);
      }
    } catch (e) {
      console.error("Swipe API error:", e);
    }
  }

  // 5. Всплывающее окно взаимного мэтча (Match Popup)
  function showMatchPopup(partner) {
    triggerHaptic("success");
    const pNameEl = document.getElementById("matchPartnerName");
    const pAvatarEl = document.getElementById("matchPartnerAvatar");
    const myAvatarEl = document.getElementById("matchMyAvatar");
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

  const matchCloseBtn = document.getElementById("matchCloseBtn");
  if (matchCloseBtn) {
    matchCloseBtn.addEventListener("click", () => {
      matchModal.classList.remove("active");
    });
  }

  // 6. Загрузка раздела «Мэтчи»
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
            <div class="match-item">
              <img src="${photoUrl}" class="match-avatar" alt="${escapeHtml(m.name)}" />
              <div class="match-info">
                <div class="match-name-row">
                  <span class="match-name">${escapeHtml(m.name)}${verified}${prem}</span>
                </div>
                <div class="match-univ">${m.university || "Студент"} ${m.year ? `• ${m.year} курс` : ""}</div>
              </div>
              <a href="${chatUrl}" target="_blank" class="match-chat-btn">
                💬 Написать
              </a>
            </div>
          `;
        })
        .join("");
    } catch (e) {
      container.innerHTML = '<div style="text-align:center;padding:30px;color:red;">Ошибка загрузки</div>';
    }
  }

  // 7. Загрузка раздела «Симпатии» (Incoming Likes)
  async function loadIncomingLikes() {
    const container = document.getElementById("likesContainer");
    if (!container) return;

    try {
      const data = await apiFetch("/api/webapp/incoming_likes");
      if (!data) return;

      if (!data.is_premium) {
        // Пейволл-тизер
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

  // 8. Загрузка профиля (Profile)
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
          <div class="profile-menu-item" id="btnOpenBotSettings">
            <span>⚙️ Настройки в боте</span>
            <span>→</span>
          </div>
        </div>
      `;

      document.getElementById("btnToggleProfileMode")?.addEventListener("click", toggleMode);
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

  // Запуск приложения
  document.addEventListener("DOMContentLoaded", () => {
    setupNavigation();
    authenticateUser();
  });
})();
