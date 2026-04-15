const keys = { up: false, down: false, left: false, right: false, sprint: false, shoot: false, steal: false };
const actionLatch = { shoot: false, steal: false };
let inputInFlight = false;
let practiceRewardClaimed = false;
let matchInputTimer = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || "요청에 실패했습니다.");
  return data;
}

function setMessage(text) {
  const box = document.getElementById("auth-message") || document.getElementById("lobby-status") || document.getElementById("shop-message") || document.getElementById("admin-message");
  if (box) box.textContent = text;
}

function preventArrowScroll() {
  window.addEventListener("keydown", (event) => {
    if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " ", "e", "E", "d", "D"].includes(event.key)) event.preventDefault();
  }, { passive: false, capture: true });
}

function isMobile() {
  return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent || "");
}

function updateRotateNotice(id) {
  const notice = document.getElementById(id);
  if (!notice) return;
  notice.hidden = !isMobile();
}

function initHome() {
  const sessionBox = document.getElementById("home-session-box");
  if (!sessionBox) return;
  const authNodes = document.querySelectorAll("[data-auth]");
  const logoutButton = document.getElementById("home-logout-button");
  const applyView = (state) => {
    authNodes.forEach((node) => {
      const mode = node.dataset.auth;
      let show = false;
      if (mode === "guest") show = !state.authenticated;
      if (mode === "player") show = !!state.authenticated;
      if (mode === "admin") show = state.role === "admin";
      node.hidden = !show;
    });
    if (logoutButton) {
      logoutButton.hidden = !state.authenticated;
      logoutButton.onclick = async () => {
        await api("/api/logout", { method: "POST", body: "{}" });
        window.location.href = "/";
      };
    }
  };
  api("/api/me").then((state) => {
    applyView(state);
    if (state.authenticated) {
      sessionBox.innerHTML = `
        <div class="profile-line"><span>상태</span><strong>로그인 유지</strong></div>
        <div class="profile-line"><span>사용자</span><strong>${state.username}</strong></div>
        <div class="profile-line"><span>전적</span><strong>${state.wins}승 ${state.draws}무 ${state.losses}패</strong></div>
        <div class="profile-line"><span>트로피</span><strong>${state.trophies}개</strong></div>
        <div class="profile-line"><span>승점</span><strong>${state.season_points}점</strong></div>
        <div class="profile-line"><span>골드</span><strong>${state.gold} G</strong></div>
      `;
    } else {
      sessionBox.innerHTML = `<div class="profile-line"><span>상태</span><strong>비로그인</strong></div><div class="profile-line"><span>안내</span><strong>로그인 후 온라인 매치</strong></div>`;
    }
  }).catch(() => {
    sessionBox.innerHTML = `<div class="profile-line"><span>상태</span><strong>확인 실패</strong></div>`;
  });
}

function initAuth() {
  const registerForm = document.getElementById("register-form");
  const loginForm = document.getElementById("login-form");
  const findIdForm = document.getElementById("find-id-form");
  const resetPasswordForm = document.getElementById("reset-password-form");
  const accountUpdateForm = document.getElementById("account-update-form");
  if (registerForm) {
    registerForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(registerForm);
      if (form.get("password") !== form.get("password_confirm")) return setMessage("비밀번호와 비밀번호 확인이 일치하지 않습니다.");
      try {
        const result = await api("/api/register", {
          method: "POST",
          body: JSON.stringify({
            username: form.get("username"),
            password: form.get("password"),
            password_confirm: form.get("password_confirm"),
            recovery_code: form.get("recovery_code"),
          }),
        });
        setMessage(result.message);
        registerForm.reset();
        setTimeout(() => {
          window.location.href = "/login";
        }, 700);
      } catch (error) {
        setMessage(error.message);
      }
    });
  }
  if (loginForm) {
    loginForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(loginForm);
      try {
        await api("/api/login", {
          method: "POST",
          body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
        });
        window.location.href = "/lobby";
      } catch (error) {
        setMessage(error.message);
      }
    });
  }
  if (findIdForm) {
    findIdForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(findIdForm);
      try {
        const result = await api("/api/find-id", {
          method: "POST",
          body: JSON.stringify({ recovery_code: form.get("recovery_code") }),
        });
        setMessage(`찾은 아이디: ${result.username}`);
      } catch (error) {
        setMessage(error.message);
      }
    });
  }
  if (resetPasswordForm) {
    resetPasswordForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(resetPasswordForm);
      if (form.get("new_password") !== form.get("new_password_confirm")) return setMessage("새 비밀번호 확인이 일치하지 않습니다.");
      try {
        const result = await api("/api/reset-password", {
          method: "POST",
          body: JSON.stringify({
            username: form.get("username"),
            recovery_code: form.get("recovery_code"),
            new_password: form.get("new_password"),
            new_password_confirm: form.get("new_password_confirm"),
          }),
        });
        setMessage(result.message);
        setTimeout(() => { window.location.href = "/login"; }, 700);
      } catch (error) {
        setMessage(error.message);
      }
    });
  }
  if (accountUpdateForm) {
    accountUpdateForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(accountUpdateForm);
      if (form.get("new_password") && form.get("new_password") !== form.get("new_password_confirm")) {
        return setMessage("새 비밀번호 확인이 일치하지 않습니다.");
      }
      try {
        const result = await api("/api/account/update", {
          method: "POST",
          body: JSON.stringify({
            new_username: form.get("new_username"),
            current_password: form.get("current_password"),
            new_password: form.get("new_password"),
            new_password_confirm: form.get("new_password_confirm"),
            new_recovery_code: form.get("new_recovery_code"),
          }),
        });
        setMessage(result.message);
        accountUpdateForm.reset();
      } catch (error) {
        setMessage(error.message);
      }
    });
  }
}

function goBackOrFallback(path = "/lobby") {
  const sameOriginReferrer = document.referrer && new URL(document.referrer).origin === window.location.origin;
  if (sameOriginReferrer && history.length > 1) return history.back();
  window.location.href = path;
}

function drawMatch(ctx, payload) {
  const { field, players, ball } = payload;
  const goalTop = field.height / 2 - 90;
  const goalHeight = 180;
  ctx.clearRect(0, 0, field.width, field.height);
  ctx.fillStyle = "#0f6d45";
  ctx.fillRect(0, 0, field.width, field.height);
  ctx.fillStyle = "rgba(255,255,255,0.18)";
  ctx.fillRect(field.margin_x - 28, goalTop, 28, goalHeight);
  ctx.fillRect(field.width - field.margin_x, goalTop, 28, goalHeight);
  ctx.strokeStyle = "rgba(255,255,255,0.85)";
  ctx.lineWidth = 5;
  ctx.strokeRect(field.margin_x - 28, goalTop, 28, goalHeight);
  ctx.strokeRect(field.width - field.margin_x, goalTop, 28, goalHeight);
  ctx.strokeStyle = "rgba(255,255,255,0.9)";
  ctx.lineWidth = 6;
  ctx.strokeRect(field.margin_x, field.margin_y, field.width - field.margin_x * 2, field.height - field.margin_y * 2);
  ctx.beginPath();
  ctx.moveTo(field.width / 2, field.margin_y);
  ctx.lineTo(field.width / 2, field.height - field.margin_y);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(field.width / 2, field.height / 2, 95, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = "#d9fdf1";
  Object.values(players).forEach((player) => {
    const stamina = typeof player.stamina === "number" ? player.stamina : (typeof player.maxStamina === "number" ? player.maxStamina : null);
    const maxStamina = typeof player.max_stamina === "number"
      ? player.max_stamina
      : (typeof player.maxStamina === "number" ? player.maxStamina : null);
    if (stamina !== null && maxStamina) {
      const barWidth = 58;
      const barHeight = 7;
      const barX = player.x - barWidth / 2;
      const barY = player.y - 46;
      const ratio = Math.max(0, Math.min(1, stamina / maxStamina));
      ctx.fillStyle = "rgba(4,16,22,0.78)";
      ctx.fillRect(barX, barY, barWidth, barHeight);
      ctx.fillStyle = ratio > 0.45 ? "#57f09f" : ratio > 0.2 ? "#ffd166" : "#ff7f67";
      ctx.fillRect(barX + 1, barY + 1, (barWidth - 2) * ratio, barHeight - 2);
      ctx.strokeStyle = "rgba(255,255,255,0.3)";
      ctx.lineWidth = 1;
      ctx.strokeRect(barX, barY, barWidth, barHeight);
    }
    ctx.beginPath();
    ctx.fillStyle = player.side === "left" ? "#72d7ff" : "#ff8b64";
    ctx.arc(player.x, player.y, 26, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#041016";
    ctx.font = "700 20px 'IBM Plex Sans KR'";
    ctx.textAlign = "center";
    ctx.fillText(player.name, player.x, player.y - 58);
  });
  ctx.beginPath();
  ctx.fillStyle = "#ffffff";
  ctx.arc(ball.x, ball.y, 13, 0, Math.PI * 2);
  ctx.fill();
}

function initLobby() {
  const queueButton = document.getElementById("queue-button");
  const meCard = document.getElementById("me-card");
  if (!queueButton || !meCard) return;
  document.getElementById("leave-queue-button").addEventListener("click", async () => {
    try {
      const result = await api("/api/queue/leave", { method: "POST", body: "{}" });
      setMessage(result.message);
    } catch (error) {
      setMessage(error.message);
    }
  });
  queueButton.addEventListener("click", async () => {
    try {
      const result = await api("/api/queue/join", { method: "POST", body: "{}" });
      setMessage(result.message);
    } catch (error) {
      setMessage(error.message);
    }
  });
  document.getElementById("logout-button").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST", body: "{}" });
    window.location.href = "/";
  });
  const poll = async () => {
    try {
      const state = await api("/api/lobby-state");
      if (!state.authenticated) return (window.location.href = "/login");
      meCard.innerHTML = `
        <div class="profile-line"><span>이름</span><strong>${state.username}</strong></div>
        <div class="profile-line"><span>권한</span><strong>${state.role === "admin" ? "관리자" : "플레이어"}</strong></div>
        <div class="profile-line"><span>전적</span><strong>${state.wins}승 ${state.draws}무 ${state.losses}패</strong></div>
        <div class="profile-line"><span>트로피</span><strong>${state.trophies}개</strong></div>
        <div class="profile-line"><span>승점</span><strong>${state.season_points}점</strong></div>
        <div class="profile-line"><span>시즌 진행</span><strong>${state.season_matches}/10</strong></div>
        <div class="profile-line"><span>골드</span><strong>${state.gold} G</strong></div>
        <div class="profile-line"><span>대기열</span><strong>${state.queued ? "참가 중" : "대기 안 함"}</strong></div>
      `;
      if (state.in_match) {
        setMessage(`${state.opponent} 님과 매칭되었습니다.`);
        setTimeout(() => { window.location.href = "/match"; }, 400);
        return;
      }
    } catch (error) {
      setMessage(error.message);
    }
    setTimeout(poll, 1200);
  };
  poll();
}

function initRankings() {
  const board = document.getElementById("rankings-board");
  if (!board) return;
  api("/api/rankings").then((state) => {
    board.innerHTML = state.players.length ? state.players.map((player) => `
      <div class="admin-line multi">
        <span>#${player.rank} ${player.username}<br><small>${player.season_matches}/10 경기</small></span>
        <div class="admin-actions"><strong>${player.trophies}T · ${player.season_points}점</strong><small>${player.wins}승 ${player.draws}무 ${player.losses}패</small></div>
      </div>
    `).join("") : `<div class="admin-line"><span>순위 데이터 없음</span><strong>-</strong></div>`;
  }).catch((error) => {
    board.innerHTML = `<div class="admin-line"><span>${error.message}</span><strong>-</strong></div>`;
  });
}

function initShop() {
  const wallet = document.getElementById("shop-wallet");
  if (!wallet) return;
  const load = async () => {
    try {
      const state = await api("/api/shop-state");
      if (!state.authenticated) return (window.location.href = "/login");
      wallet.innerHTML = `
        <div class="profile-line"><span>이름</span><strong>${state.username}</strong></div>
        <div class="profile-line"><span>골드</span><strong>${state.gold} G</strong></div>
        <div class="profile-line"><span>슛파워</span><strong>+${state.upgrades.shot_power * 5}</strong></div>
        <div class="profile-line"><span>전력질주</span><strong>+${state.upgrades.sprint_speed * 3}</strong></div>
        <div class="profile-line"><span>체력</span><strong>+${state.upgrades.max_stamina * 5}</strong></div>
      `;
    } catch (error) {
      setMessage(error.message);
    }
  };
  document.querySelectorAll(".shop-buy-button").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const result = await api("/api/shop/buy", {
          method: "POST",
          body: JSON.stringify({ item: button.dataset.item }),
        });
        setMessage(result.message);
        load();
      } catch (error) {
        setMessage(error.message);
      }
    });
  });
  load();
}

function initAdmin() {
  const usersBox = document.getElementById("admin-users");
  if (!usersBox) return;
  const queueBox = document.getElementById("admin-queue");
  const matchesBox = document.getElementById("admin-matches");
  const refresh = async () => {
    try {
      const state = await api("/api/admin/state");
      usersBox.innerHTML = state.users.map((user) => `
        <div class="admin-line multi">
          <span>${user.username}<br><small>${user.role} · ${user.trophies}T · ${user.season_points}P · ${user.gold}G</small></span>
          <div class="admin-actions">
            <strong>${user.wins}W ${user.draws}D ${user.losses}L</strong>
            ${user.role === "admin" ? "" : `<button class="button ghost admin-delete-button" data-user="${user.username}">삭제</button>`}
          </div>
        </div>
      `).join("");
      queueBox.innerHTML = state.queue.length ? state.queue.map((user) => `<div class="admin-line"><span>${user}</span><strong>queue</strong></div>`).join("") : `<div class="admin-line"><span>대기열 비어 있음</span><strong>-</strong></div>`;
      matchesBox.innerHTML = state.matches.length ? state.matches.map((match) => `<div class="admin-line multi"><span>${match.players.join(" vs ")}</span><strong>${Object.values(match.score).join(" : ")} · ${match.status}</strong></div>`).join("") : `<div class="admin-line"><span>진행 중 경기 없음</span><strong>-</strong></div>`;
      document.querySelectorAll(".admin-delete-button").forEach((button) => {
        button.onclick = async () => {
          try {
            const result = await api("/api/admin/delete-user", { method: "POST", body: JSON.stringify({ username: button.dataset.user }) });
            setMessage(result.message);
            refresh();
          } catch (error) {
            setMessage(error.message);
          }
        };
      });
    } catch (error) {
      setMessage(error.message);
    }
  };
  document.getElementById("refresh-admin-button").onclick = refresh;
  document.getElementById("clear-queue-button").onclick = async () => {
    try {
      setMessage((await api("/api/admin/clear-queue", { method: "POST", body: "{}" })).message);
      refresh();
    } catch (error) {
      setMessage(error.message);
    }
  };
  document.getElementById("end-matches-button").onclick = async () => {
    try {
      setMessage((await api("/api/admin/end-matches", { method: "POST", body: "{}" })).message);
      refresh();
    } catch (error) {
      setMessage(error.message);
    }
  };
  refresh();
}

function initMatchControls() {
  preventArrowScroll();
  const onKey = (event, pressed) => {
    const code = event.code;
    if (code === "ArrowUp") keys.up = pressed;
    if (code === "ArrowDown") keys.down = pressed;
    if (code === "ArrowLeft") keys.left = pressed;
    if (code === "ArrowRight") keys.right = pressed;
    if (code === "KeyE") keys.sprint = pressed;
    if (code === "KeyD" && pressed) actionLatch.shoot = true;
    if (code === "Space" && pressed) actionLatch.steal = true;
  };
  window.addEventListener("keydown", (event) => onKey(event, true));
  window.addEventListener("keyup", (event) => onKey(event, false));
}

function initMobileControls(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  if (!isMobile()) {
    container.innerHTML = "";
    container.classList.remove("mobile-enabled");
    keys.up = false;
    keys.down = false;
    keys.left = false;
    keys.right = false;
    return;
  }
  container.classList.add("mobile-enabled");
  container.innerHTML = `
    <div class="mobile-pad left-pad">
      <div class="joystick-shell">
        <div class="joystick-base" id="${containerId}-joystick-base">
          <div class="joystick-thumb" id="${containerId}-joystick-thumb"></div>
        </div>
      </div>
    </div>
    <div class="mobile-pad right-pad">
      <div class="pad-row"><button data-key="shoot">X</button><button data-key="steal">A</button></div>
      <div class="pad-row single"><button data-key="sprint">B</button></div>
    </div>
  `;
  const joystickBase = document.getElementById(`${containerId}-joystick-base`);
  const joystickThumb = document.getElementById(`${containerId}-joystick-thumb`);
  let joystickPointerId = null;

  const resetJoystick = () => {
    keys.up = false;
    keys.down = false;
    keys.left = false;
    keys.right = false;
    if (joystickThumb) joystickThumb.style.transform = "translate(0px, 0px)";
  };

  const applyJoystick = (clientX, clientY) => {
    if (!joystickBase || !joystickThumb) return;
    const rect = joystickBase.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    let dx = clientX - centerX;
    let dy = clientY - centerY;
    const maxRadius = rect.width * 0.26;
    const distance = Math.hypot(dx, dy) || 1;
    if (distance > maxRadius) {
      dx = (dx / distance) * maxRadius;
      dy = (dy / distance) * maxRadius;
    }
    joystickThumb.style.transform = `translate(${dx}px, ${dy}px)`;
    keys.left = dx < -10;
    keys.right = dx > 10;
    keys.up = dy < -10;
    keys.down = dy > 10;
  };

  if (joystickBase) {
    joystickBase.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      joystickPointerId = event.pointerId;
      joystickBase.setPointerCapture(event.pointerId);
      applyJoystick(event.clientX, event.clientY);
    });
    joystickBase.addEventListener("pointermove", (event) => {
      if (joystickPointerId !== event.pointerId) return;
      event.preventDefault();
      applyJoystick(event.clientX, event.clientY);
    });
    const endJoystick = (event) => {
      if (joystickPointerId !== event.pointerId) return;
      joystickPointerId = null;
      resetJoystick();
    };
    joystickBase.addEventListener("pointerup", endJoystick);
    joystickBase.addEventListener("pointercancel", endJoystick);
    joystickBase.addEventListener("lostpointercapture", () => {
      joystickPointerId = null;
      resetJoystick();
    });
  }

  container.querySelectorAll("button").forEach((button) => {
    let activePointerId = null;
    const bind = (pressed) => {
      const key = button.dataset.key;
      if (key === "shoot" && pressed) {
        actionLatch.shoot = true;
        return;
      }
      if (key === "steal" && pressed) {
        actionLatch.steal = true;
        return;
      }
      keys[key] = pressed;
    };
    button.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      activePointerId = event.pointerId;
      button.setPointerCapture(event.pointerId);
      bind(true);
    });
    ["pointerup", "pointercancel", "lostpointercapture", "pointerleave"].forEach((name) => button.addEventListener(name, (event) => {
      if (activePointerId !== null && event.pointerId !== undefined && event.pointerId !== activePointerId) return;
      event.preventDefault();
      activePointerId = null;
      bind(false);
    }));
  });
}

function updateControlGuides() {
  document.querySelectorAll(".control-panel .rules-list").forEach((list) => {
    if (isMobile()) {
      list.innerHTML = `
        <div><strong>이동</strong><span>왼쪽 조이스틱</span></div>
        <div><strong>질주</strong><span>B 버튼</span></div>
        <div><strong>슛</strong><span>X 버튼</span></div>
        <div><strong>뺏기</strong><span>A 버튼</span></div>
      `;
    } else {
      list.innerHTML = `
        <div><strong>이동</strong><span>방향키</span></div>
        <div><strong>질주</strong><span>E</span></div>
        <div><strong>슛</strong><span>D</span></div>
        <div><strong>뺏기</strong><span>Space</span></div>
      `;
    }
  });
}

async function sendInputLoop() {
  if (inputInFlight) return;
  inputInFlight = true;
  try {
    await api("/api/input", {
      method: "POST",
      body: JSON.stringify({
        up: keys.up,
        down: keys.down,
        left: keys.left,
        right: keys.right,
        sprint: keys.sprint,
        shoot: actionLatch.shoot,
        steal: actionLatch.steal,
      }),
    });
    actionLatch.shoot = false;
    actionLatch.steal = false;
  } catch {}
  inputInFlight = false;
}

function initMatch() {
  const canvas = document.getElementById("online-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  initMatchControls();
  initMobileControls("mobile-controls");
  updateRotateNotice("rotate-notice");
  updateControlGuides();
  const feed = document.getElementById("feed-log");
  const statusText = document.getElementById("match-status-text");
  const timerText = document.getElementById("timer-text");
  const scoreLine = document.getElementById("score-line");
  const playerMeta = document.getElementById("player-meta");
  const staminaText = document.getElementById("stamina-text");
  const goldText = document.getElementById("gold-text");
  const chatLog = document.getElementById("chat-log");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const forfeitButton = document.getElementById("forfeit-button");
  const adminPause = document.getElementById("admin-pause-button");
  const adminScoreSelf = document.getElementById("admin-score-self-button");
  const adminScoreOpponent = document.getElementById("admin-score-opponent-button");

  forfeitButton.onclick = async () => {
    try {
      await api("/api/forfeit", { method: "POST", body: "{}" });
    } finally {
      goBackOrFallback("/lobby");
    }
  };
  adminPause.onclick = () => api("/api/admin/match-control", { method: "POST", body: JSON.stringify({ action: "toggle_pause" }) }).catch(() => {});
  adminScoreSelf.onclick = () => api("/api/admin/match-control", { method: "POST", body: JSON.stringify({ action: "add_score_self" }) }).catch(() => {});
  adminScoreOpponent.onclick = () => api("/api/admin/match-control", { method: "POST", body: JSON.stringify({ action: "add_score_opponent" }) }).catch(() => {});
  if (chatForm && chatInput) {
    chatForm.onsubmit = async (event) => {
      event.preventDefault();
      const message = chatInput.value.trim();
      if (!message) return;
      try {
        await api("/api/chat/send", { method: "POST", body: JSON.stringify({ message }) });
        chatInput.value = "";
      } catch (error) {
        setMessage(error.message);
      }
    };
  }

  const poll = async () => {
    try {
      const state = await api("/api/match-state");
      if (!state.authenticated) return (window.location.href = "/login");
      if (!state.in_match) return goBackOrFallback("/lobby");
      statusText.textContent = state.status === "paused" ? "일시정지" : "경기 중";
      timerText.textContent = Math.ceil(state.time_left);
      scoreLine.textContent = `${state.score[state.username] ?? 0} : ${state.score[state.opponent] ?? 0}`;
      staminaText.textContent = `${state.stamina} / ${state.max_stamina}`;
      goldText.textContent = `${state.gold} G`;
      playerMeta.innerHTML = `
        <div class="profile-line"><span>이름</span><strong>${state.username}</strong></div>
        <div class="profile-line"><span>상대</span><strong>${state.opponent}</strong></div>
        <div class="profile-line"><span>전적</span><strong>${state.wins}승 ${state.draws}무 ${state.losses}패</strong></div>
        <div class="profile-line"><span>트로피</span><strong>${state.trophies}개</strong></div>
        <div class="profile-line"><span>승점</span><strong>${state.season_points}점</strong></div>
      `;
      adminPause.hidden = !state.is_admin;
      adminScoreSelf.hidden = !state.is_admin;
      adminScoreOpponent.hidden = !state.is_admin;
      feed.innerHTML = state.events.map((item) => `<div class="feed-item">${item}</div>`).join("");
      if (chatLog) {
        chatLog.innerHTML = (state.chat || []).map((entry) => `<div class="feed-item"><strong>${entry.author}</strong> ${entry.text}</div>`).join("");
      }
      drawMatch(ctx, { field: state.field, players: state.players, ball: state.ball });
      if (state.status === "finished") {
        if (state.end_type === "forfeit") {
          return goBackOrFallback("/lobby");
        }
        setTimeout(() => { window.location.href = "/lobby"; }, 1200);
        return;
      }
    } catch {}
    setTimeout(poll, 90);
  };
  if (matchInputTimer) clearInterval(matchInputTimer);
  matchInputTimer = setInterval(() => { sendInputLoop(); }, 50);
  poll();
}

function createOfflineState() {
  return {
    field: { width: 1440, height: 810, margin_x: 96, margin_y: 72 },
    players: {
      PLAYER: { x: 1440 * 0.26, y: 810 / 2, side: "left", name: "PLAYER", stamina: 100, maxStamina: 100 },
      "AI BOT": { x: 1440 * 0.74, y: 810 / 2, side: "right", name: "AI BOT", stamina: 100, maxStamina: 100 },
    },
    ball: { x: 720, y: 405, vx: 0, vy: 0, owner: null },
    score: { PLAYER: 0, "AI BOT": 0 },
    events: ["강화된 AI 연습 경기 시작"],
    timeLeft: 90,
    status: "live",
    stamina: 100,
    maxStamina: 100,
  };
}

function resetOfflinePositions(state) {
  state.players.PLAYER.x = state.field.width * 0.26;
  state.players.PLAYER.y = state.field.height / 2;
  state.players["AI BOT"].x = state.field.width * 0.74;
  state.players["AI BOT"].y = state.field.height / 2;
  state.ball = { x: state.field.width / 2, y: state.field.height / 2, vx: 0, vy: 0, owner: null };
}

function initOfflineMatch() {
  const canvas = document.getElementById("offline-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const overlay = document.getElementById("offline-overlay-banner");
  initMatchControls();
  initMobileControls("offline-mobile-controls");
  updateRotateNotice("offline-rotate-notice");
  updateControlGuides();
  let state = createOfflineState();
  let last = performance.now();
  practiceRewardClaimed = false;

  const pushEvent = (text) => {
    state.events.unshift(text);
    state.events = state.events.slice(0, 10);
  };

  const finish = async () => {
    if (practiceRewardClaimed) return;
    practiceRewardClaimed = true;
    const result = state.score.PLAYER > state.score["AI BOT"] ? "win" : state.score.PLAYER === state.score["AI BOT"] ? "draw" : "loss";
    overlay.textContent = result === "win" ? "AI 연습 승리 · 30G" : result === "draw" ? "AI 연습 무승부 · 10G" : "AI 연습 종료";
    try { await api("/api/practice/reward", { method: "POST", body: JSON.stringify({ result }) }); } catch {}
  };

  document.getElementById("offline-reset-button").onclick = () => {
    state = createOfflineState();
    practiceRewardClaimed = false;
    overlay.textContent = "강화된 AI 연습 경기입니다.";
  };
  document.getElementById("offline-exit-button").onclick = () => goBackOrFallback("/");

  const update = async (dt) => {
    if (state.status !== "live") return;
    state.timeLeft = Math.max(0, state.timeLeft - dt);
    if (state.timeLeft <= 0) {
      state.status = "finished";
      pushEvent("연습 경기 종료");
      await finish();
      return;
    }
    const { field, players, ball } = state;
    const player = players.PLAYER;
    const ai = players["AI BOT"];
    const marginX = field.margin_x;
    const marginY = field.margin_y;
    const goalTop = field.height / 2 - 90;
    const goalBottom = field.height / 2 + 90;
    const moveEntity = (entity, dx, dy, speed) => {
      if (dx || dy) {
        const mag = Math.hypot(dx, dy) || 1;
        entity.x += (dx / mag) * speed * dt;
        entity.y += (dy / mag) * speed * dt;
      }
      entity.x = Math.max(marginX + 26, Math.min(field.width - marginX - 26, entity.x));
      entity.y = Math.max(marginY + 26, Math.min(field.height - marginY - 26, entity.y));
    };
    const playerHasBall = ball.owner === "PLAYER";
    const aiHasBall = ball.owner === "AI BOT";
    const playerDx = (keys.left ? -1 : 0) + (keys.right ? 1 : 0);
    const playerDy = (keys.up ? -1 : 0) + (keys.down ? 1 : 0);
    if (keys.sprint && state.stamina > 0) state.stamina = Math.max(0, state.stamina - 8 * dt);
    else state.stamina = Math.min(state.maxStamina, state.stamina + 2.2 * dt);
    player.stamina = state.stamina;
    player.maxStamina = state.maxStamina;
    moveEntity(player, playerDx, playerDy, (keys.sprint && state.stamina > 0) ? (playerHasBall ? 266 : 276) : (playerHasBall ? 184 : 194));

    const aiTargetX = aiHasBall ? marginX + 80 : ball.x;
    const aiTargetY = aiHasBall ? field.height / 2 : ball.y;
    const aiDx = aiTargetX < ai.x - 8 ? -1 : aiTargetX > ai.x + 8 ? 1 : 0;
    const aiDy = aiTargetY < ai.y - 8 ? -1 : aiTargetY > ai.y + 8 ? 1 : 0;
    const aiSpeed = aiHasBall ? 230 : 222;
    ai.stamina = 100;
    ai.maxStamina = 100;
    moveEntity(ai, aiDx, aiDy, aiSpeed);

    if (ball.owner === "PLAYER") {
      ball.x = player.x + 28;
      ball.y = player.y;
    } else if (ball.owner === "AI BOT") {
      ball.x = ai.x - 28;
      ball.y = ai.y;
    }

    if (ball.owner === "PLAYER" && goalTop < ball.y && ball.y < goalBottom && ball.x >= field.width - marginX - 13) {
      state.score.PLAYER += 1;
      pushEvent("GOAL! PLAYER");
      resetOfflinePositions(state);
      return;
    }
    if (ball.owner === "AI BOT" && goalTop < ball.y && ball.y < goalBottom && ball.x <= marginX + 13) {
      state.score["AI BOT"] += 1;
      pushEvent("GOAL! AI BOT");
      resetOfflinePositions(state);
      return;
    }

    if (ball.owner === null) {
      if (Math.hypot(player.x - ball.x, player.y - ball.y) < 38) ball.owner = "PLAYER";
      if (Math.hypot(ai.x - ball.x, ai.y - ball.y) < 44) ball.owner = "AI BOT";
    }

    const stealPressed = actionLatch.steal;
    const shootPressed = actionLatch.shoot;
    actionLatch.steal = false;
    actionLatch.shoot = false;

    if (stealPressed && ball.owner === "AI BOT" && Math.hypot(player.x - ai.x, player.y - ai.y) < 52) {
      ball.owner = "PLAYER";
      pushEvent("PLAYER가 공을 뺏었습니다.");
    }

    if (ball.owner === "PLAYER" && shootPressed) {
      ball.owner = null;
      ball.vx = 740;
      ball.vy = (ball.y - field.height / 2) * 0.18;
      pushEvent("PLAYER 슛!");
    }
    if (ball.owner === "AI BOT" && (ai.x < field.width * 0.64 || Math.abs(ai.y - field.height / 2) < 65)) {
      ball.owner = null;
      ball.vx = -775;
      ball.vy = (ball.y - field.height / 2) * 0.2;
      pushEvent("AI BOT 슛!");
    }
    if (ball.owner === null) {
      ball.x += ball.vx * dt;
      ball.y += ball.vy * dt;
      ball.vx *= 0.982;
      ball.vy *= 0.982;
      if (Math.abs(ball.vx) < 16) ball.vx = 0;
      if (Math.abs(ball.vy) < 16) ball.vy = 0;
      if (ball.y < marginY + 13 || ball.y > field.height - marginY - 13) {
        ball.vy *= -0.9;
        ball.y = Math.max(marginY + 13, Math.min(field.height - marginY - 13, ball.y));
      }
      if (ball.x <= marginX + 13) {
        if (goalTop < ball.y && ball.y < goalBottom) {
          state.score["AI BOT"] += 1;
          pushEvent("GOAL! AI BOT");
          resetOfflinePositions(state);
          return;
        }
        ball.vx *= -0.88;
        ball.x = marginX + 13;
      }
      if (ball.x >= field.width - marginX - 13) {
        if (goalTop < ball.y && ball.y < goalBottom) {
          state.score.PLAYER += 1;
          pushEvent("GOAL! PLAYER");
          resetOfflinePositions(state);
          return;
        }
        ball.vx *= -0.88;
        ball.x = field.width - marginX - 13;
      }
    }
  };

  const render = () => {
    document.getElementById("offline-status-text").textContent = state.status === "finished" ? "연습 종료" : "연습 중";
    document.getElementById("offline-timer-text").textContent = Math.ceil(state.timeLeft);
    document.getElementById("offline-score-line").textContent = `${state.score.PLAYER} : ${state.score["AI BOT"]}`;
    document.getElementById("offline-stamina-text").textContent = `${Math.round(state.stamina)} / ${Math.round(state.maxStamina)}`;
    drawMatch(ctx, { field: state.field, players: state.players, ball: state.ball });
  };

  const loop = async (now) => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    await update(dt);
    render();
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

function initSpectate() {
  const canvas = document.getElementById("spectate-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const listBox = document.getElementById("spectate-list");
  const title = document.getElementById("spectate-match-title");
  const scoreLine = document.getElementById("spectate-score-line");
  const timer = document.getElementById("spectate-timer");
  const feed = document.getElementById("spectate-feed");
  let currentMatchId = "";
  const loadList = async () => {
    try {
      const state = await api("/api/spectate-list");
      listBox.innerHTML = state.matches.length ? state.matches.map((match) => `
        <button class="spectate-match-button" data-id="${match.id}">${match.players.join(" vs ")}</button>
      `).join("") : `<div class="feed-item">진행 중인 경기가 없습니다.</div>`;
      listBox.querySelectorAll(".spectate-match-button").forEach((button) => {
        button.onclick = () => { currentMatchId = button.dataset.id; };
      });
      if (!currentMatchId && state.matches[0]) currentMatchId = state.matches[0].id;
    } catch {}
  };
  const poll = async () => {
    await loadList();
    try {
      const state = await api(`/api/spectate-state?match_id=${encodeURIComponent(currentMatchId)}`);
      if (!state.available) {
        title.textContent = "진행 중인 경기 없음";
        scoreLine.textContent = "-";
        timer.textContent = "-";
        feed.innerHTML = "";
      } else {
        currentMatchId = state.match_id;
        title.textContent = state.players_order.join(" vs ");
        scoreLine.textContent = `${state.score[state.players_order[0]]} : ${state.score[state.players_order[1]]}`;
        timer.textContent = Math.ceil(state.time_left);
        feed.innerHTML = state.events.map((item) => `<div class="feed-item">${item}</div>`).join("");
        drawMatch(ctx, { field: state.field, players: state.players, ball: state.ball });
      }
    } catch {}
    setTimeout(poll, 1000);
  };
  poll();
}

function boot() {
  initHome();
  initAuth();
  initLobby();
  initRankings();
  initShop();
  initAdmin();
  initMatch();
  initOfflineMatch();
  initSpectate();
}

boot();
