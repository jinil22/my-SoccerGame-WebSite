from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"

HOST = "0.0.0.0"
PORT = 8020
SESSION_COOKIE = "neon_derby_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "NeonAdmin2026!"

ONLINE_MATCH_SECONDS = 120
PRACTICE_MATCH_SECONDS = 90
FIELD = {"width": 1440, "height": 810, "margin_x": 96, "margin_y": 72}

lock = threading.Lock()
sessions: dict[str, str] = {}
queue: list[str] = []
player_to_match: dict[str, str] = {}
player_states: dict[str, dict] = {}
matches: dict[str, dict] = {}


def default_user(role: str = "player") -> dict:
    return {
        "password_hash": "",
        "recovery_code_hash": "",
        "role": role,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "trophies": 0,
        "season_points": 0,
        "season_matches": 0,
        "gold": 0,
        "upgrades": {
            "shot_power": 0,
            "sprint_speed": 0,
            "max_stamina": 0,
        },
    }


def ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    if not USERS_FILE.exists():
        USERS_FILE.write_text("{}", encoding="utf-8")
    users = read_users()
    if ADMIN_USERNAME not in users:
        users[ADMIN_USERNAME] = {**default_user("admin"), "password_hash": hash_password(ADMIN_PASSWORD)}
        write_users(users)


def read_users() -> dict:
    try:
        raw = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    changed = False
    for username, meta in list(raw.items()):
        role = meta.get("role", "player")
        merged = {
            **default_user(role),
            "password_hash": meta.get("password_hash", ""),
            "recovery_code_hash": meta.get("recovery_code_hash", ""),
            "role": role,
            "wins": meta.get("wins", 0),
            "draws": meta.get("draws", 0),
            "losses": meta.get("losses", 0),
            "trophies": meta.get("trophies", 0),
            "season_points": meta.get("season_points", 0),
            "season_matches": meta.get("season_matches", 0),
            "gold": meta.get("gold", 0),
            "upgrades": {
                "shot_power": meta.get("upgrades", {}).get("shot_power", 0),
                "sprint_speed": meta.get("upgrades", {}).get("sprint_speed", 0),
                "max_stamina": meta.get("upgrades", {}).get("max_stamina", 0),
            },
        }
        if merged != meta:
            raw[username] = merged
            changed = True
    if changed:
        write_users(raw)
    return raw


def write_users(users: dict) -> None:
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def normalize_username(username: str) -> str:
    return username.strip().lower()


def parse_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length).decode("utf-8") if length else ""
    if not raw:
        return {}
    if "application/json" in handler.headers.get("Content-Type", ""):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {key: values[0] for key, values in parse_qs(raw).items()}


def get_username_from_handler(handler: BaseHTTPRequestHandler) -> str | None:
    cookie_header = handler.headers.get("Cookie", "")
    if not cookie_header:
        return None
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    session = cookie.get(SESSION_COOKIE)
    if not session:
        return None
    return sessions.get(session.value)


def is_admin(username: str | None) -> bool:
    return bool(username) and read_users().get(username, {}).get("role") == "admin"


def reset_season_if_needed(player: dict) -> None:
    if player.get("season_matches", 0) >= 10:
        player["wins"] = 0
        player["draws"] = 0
        player["losses"] = 0
        player["season_matches"] = 0


def convert_points_to_trophies(player: dict) -> None:
    while player.get("season_points", 0) >= 10:
        player["season_points"] -= 10
        player["trophies"] = player.get("trophies", 0) + 1


def give_practice_reward(username: str, result: str) -> None:
    users = read_users()
    player = users.get(username)
    if not player:
        return
    if result == "win":
        player["gold"] += 30
    elif result == "draw":
        player["gold"] += 10
    write_users(users)


def award_online_progress(match: dict, forfeiter: str | None = None) -> None:
    users = read_users()
    left, right = match["players"]
    left_score = match["score"][left]
    right_score = match["score"][right]
    for username in [left, right]:
        player = users.get(username)
        if not player:
            continue
        reset_season_if_needed(player)
        if forfeiter == username:
            player["losses"] += 1
        elif forfeiter and forfeiter != username:
            player["wins"] += 1
            player["season_points"] += 3
            player["gold"] += 50
        elif left_score == right_score:
            player["draws"] += 1
            player["season_points"] += 1
            player["gold"] += 10
        elif (username == left and left_score > right_score) or (username == right and right_score > left_score):
            player["wins"] += 1
            player["season_points"] += 3
            player["gold"] += 50
        else:
            player["losses"] += 1
        convert_points_to_trophies(player)
        player["season_matches"] += 1
    write_users(users)


def cleanup_finished_player(username: str) -> None:
    match_id = player_to_match.get(username)
    if not match_id or match_id not in matches:
        player_to_match.pop(username, None)
        return
    if matches[match_id]["status"] == "finished":
        player_to_match.pop(username, None)
        player_states.pop(username, None)


def create_player_runtime(username: str, side: str) -> dict:
    users = read_users()
    upgrades = users.get(username, default_user()).get("upgrades", {})
    max_stamina = 100 + upgrades.get("max_stamina", 0) * 5
    return {
        "x": FIELD["width"] * (0.26 if side == "left" else 0.74),
        "y": FIELD["height"] / 2,
        "vx": 0.0,
        "vy": 0.0,
        "name": username,
        "side": side,
        "stamina": float(max_stamina),
        "max_stamina": float(max_stamina),
        "shot_bonus": upgrades.get("shot_power", 0) * 5.0,
        "sprint_bonus": upgrades.get("sprint_speed", 0) * 3.0,
        "sprint_flash": 0.0,
    }


def spawn_match() -> None:
    if len(queue) < 2:
        return
    left = queue.pop(0)
    right = queue.pop(0)
    match_id = secrets.token_hex(8)
    matches[match_id] = {
        "id": match_id,
        "players": [left, right],
        "score": {left: 0, right: 0},
        "time_left": float(ONLINE_MATCH_SECONDS),
        "status": "live",
        "end_type": "",
        "forfeiter": None,
        "events": [f"{left} vs {right} 경기 시작"],
        "chat": [],
        "field": FIELD,
        "ball": {"x": FIELD["width"] / 2, "y": FIELD["height"] / 2, "vx": 0.0, "vy": 0.0, "owner": None},
        "players_state": {
            left: create_player_runtime(left, "left"),
            right: create_player_runtime(right, "right"),
        },
        "last_tick": time.time(),
    }
    player_to_match[left] = match_id
    player_to_match[right] = match_id
    player_states[left] = {"up": False, "down": False, "left": False, "right": False, "sprint": False, "shoot": False, "steal": False}
    player_states[right] = {"up": False, "down": False, "left": False, "right": False, "sprint": False, "shoot": False, "steal": False}


def reset_positions(match: dict) -> None:
    left, right = match["players"]
    match["players_state"][left]["x"] = FIELD["width"] * 0.26
    match["players_state"][left]["y"] = FIELD["height"] / 2
    match["players_state"][right]["x"] = FIELD["width"] * 0.74
    match["players_state"][right]["y"] = FIELD["height"] / 2
    match["ball"] = {"x": FIELD["width"] / 2, "y": FIELD["height"] / 2, "vx": 0.0, "vy": 0.0, "owner": None}


def finish_match(match: dict, text: str, forfeiter: str | None = None, end_type: str = "normal") -> None:
    if match["status"] == "finished":
        return
    match["events"].insert(0, text)
    match["status"] = "finished"
    match["end_type"] = end_type
    match["forfeiter"] = forfeiter
    award_online_progress(match, forfeiter=forfeiter)


def update_match(match: dict, dt: float) -> None:
    if match["status"] != "live":
        return
    field = match["field"]
    goal_top = field["height"] / 2 - 90
    goal_bottom = field["height"] / 2 + 90
    match["time_left"] = max(0.0, match["time_left"] - dt)
    if match["time_left"] <= 0:
        left, right = match["players"]
        ls = match["score"][left]
        rs = match["score"][right]
        if ls > rs:
            finish_match(match, f"경기 종료 · {left} 승리")
        elif rs > ls:
            finish_match(match, f"경기 종료 · {right} 승리")
        else:
            finish_match(match, "경기 종료 · 무승부")
        return

    for username in match["players"]:
        state = player_states.get(username, {})
        player = match["players_state"][username]
        rival_name = match["players"][0] if match["players"][1] == username else match["players"][1]
        trailing_boost = 12 if match["score"][username] < match["score"][rival_name] else 0
        dx = (-1 if state.get("left") else 0) + (1 if state.get("right") else 0)
        dy = (-1 if state.get("up") else 0) + (1 if state.get("down") else 0)
        has_ball = match["ball"].get("owner") == username
        speed = 194 + trailing_boost - (10 if has_ball else 0)
        if state.get("sprint") and player["stamina"] > 0:
            speed = 276 + player["sprint_bonus"] + trailing_boost - (10 if has_ball else 0)
            player["stamina"] = max(0.0, player["stamina"] - 8.0 * dt)
            player["sprint_flash"] = 0.12
            if player["stamina"] <= 0:
                player["stamina"] = 0.0
                state["sprint"] = False
        else:
            player["stamina"] = min(player["max_stamina"], player["stamina"] + 2.2 * dt)
            player["sprint_flash"] = max(0.0, player["sprint_flash"] - dt)
        if dx or dy:
            mag = (dx * dx + dy * dy) ** 0.5 or 1
            player["x"] += dx / mag * speed * dt
            player["y"] += dy / mag * speed * dt
        player["x"] = max(field["margin_x"] + 26, min(field["width"] - field["margin_x"] - 26, player["x"]))
        player["y"] = max(field["margin_y"] + 26, min(field["height"] - field["margin_y"] - 26, player["y"]))

    ball = match["ball"]
    if ball["owner"] in match["players"]:
        owner_name = ball["owner"]
        owner = match["players_state"][owner_name]
        offset = 28 if owner["side"] == "left" else -28
        ball["x"] = owner["x"] + offset
        ball["y"] = owner["y"]
        if goal_top < ball["y"] < goal_bottom:
            if owner["side"] == "left" and ball["x"] >= field["width"] - field["margin_x"] - 13:
                match["score"][owner_name] += 1
                match["events"].insert(0, f"GOAL! {owner_name}")
                reset_positions(match)
                return
            if owner["side"] == "right" and ball["x"] <= field["margin_x"] + 13:
                match["score"][owner_name] += 1
                match["events"].insert(0, f"GOAL! {owner_name}")
                reset_positions(match)
                return

    if ball["owner"] is None:
        for username in match["players"]:
            player = match["players_state"][username]
            if ((player["x"] - ball["x"]) ** 2 + (player["y"] - ball["y"]) ** 2) ** 0.5 < 38:
                ball["owner"] = username
                break

    for username in match["players"]:
        state = player_states.get(username, {})
        player = match["players_state"][username]
        rival_name = match["players"][0] if match["players"][1] == username else match["players"][1]
        rival = match["players_state"][rival_name]
        if state.get("steal"):
            if ball["owner"] == rival_name and ((player["x"] - rival["x"]) ** 2 + (player["y"] - rival["y"]) ** 2) ** 0.5 < 52:
                ball["owner"] = username
                match["events"].insert(0, f"{username}가 공을 뺏었습니다.")
            state["steal"] = False
        if state.get("shoot") and ball["owner"] == username:
            direction = 1 if player["side"] == "left" else -1
            trailing_boost = 28 if match["score"][username] < match["score"][rival_name] else 0
            ball["owner"] = None
            ball["vx"] = (735 + player["shot_bonus"] + trailing_boost) * direction
            ball["vy"] = (ball["y"] - field["height"] / 2) * 0.18
            match["events"].insert(0, f"{username} 슛!")
        if state.get("shoot"):
            state["shoot"] = False

    if ball["owner"] is None:
        ball["x"] += ball["vx"] * dt
        ball["y"] += ball["vy"] * dt
        ball["vx"] *= 0.982
        ball["vy"] *= 0.982
        if abs(ball["vx"]) < 16:
            ball["vx"] = 0.0
        if abs(ball["vy"]) < 16:
            ball["vy"] = 0.0
        if ball["y"] < field["margin_y"] + 13 or ball["y"] > field["height"] - field["margin_y"] - 13:
            ball["vy"] *= -0.9
            ball["y"] = max(field["margin_y"] + 13, min(field["height"] - field["margin_y"] - 13, ball["y"]))
        if ball["x"] <= field["margin_x"] + 13:
            if goal_top < ball["y"] < goal_bottom:
                scorer = match["players"][1]
                match["score"][scorer] += 1
                match["events"].insert(0, f"GOAL! {scorer}")
                reset_positions(match)
                return
            ball["vx"] *= -0.88
            ball["x"] = field["margin_x"] + 13
        if ball["x"] >= field["width"] - field["margin_x"] - 13:
            if goal_top < ball["y"] < goal_bottom:
                scorer = match["players"][0]
                match["score"][scorer] += 1
                match["events"].insert(0, f"GOAL! {scorer}")
                reset_positions(match)
                return
            ball["vx"] *= -0.88
            ball["x"] = field["width"] - field["margin_x"] - 13

    match["events"] = match["events"][:10]


def game_loop() -> None:
    while True:
        time.sleep(0.016)
        with lock:
            spawn_match()
            for match in list(matches.values()):
                now = time.time()
                dt = max(0.0, min(0.05, now - match["last_tick"]))
                match["last_tick"] = now
                update_match(match, dt)


def render_page(title: str, body_class: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Anton&family=IBM+Plex+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body class="{body_class}">
  <div class="bg-grid"></div>
  {body}
  <script src="/static/game.js"></script>
</body>
</html>"""


HOME_HTML = render_page(
    "Neon Derby Online",
    "app-page",
    """
<header class="shell">
  <nav class="topbar">
    <div class="brand">NEON DERBY ONLINE</div>
    <div class="nav-links">
      <a href="/">홈</a>
      <a href="/login" data-auth="guest">로그인</a>
      <a href="/register" data-auth="guest">회원가입</a>
      <a href="/lobby">대기실</a>
      <a href="/practice">AI 연습</a>
      <a href="/spectate">관전</a>
      <a href="/rankings">순위표</a>
      <a href="/shop">상점</a>
      <a href="/account" data-auth="player">계정관리</a>
      <a href="/admin" data-auth="admin" hidden>관리자</a>
      <button class="button ghost" id="home-logout-button" type="button" hidden>로그아웃</button>
    </div>
  </nav>
</header>
<main class="home-layout">
  <section class="hero-card worldcup-card">
    <p class="eyebrow">WORLD CUP ONLINE</p>
    <h1>WORLD STAGE<br>1 VS 1</h1>
    <div class="hero-actions">
      <a class="button primary" href="/register" data-auth="guest">계정 만들기</a>
      <a class="button secondary" href="/login" data-auth="guest">로그인</a>
      <a class="button primary" href="/lobby" data-auth="player" hidden>온라인 매치</a>
      <a class="button secondary" href="/shop" data-auth="player" hidden>상점 가기</a>
      <a class="button ghost" href="/practice">AI 연습</a>
    </div>
  </section>
  <section class="info-grid">
    <article class="info-card home-session-card">
      <p class="eyebrow small">SESSION</p>
      <div id="home-session-box" class="profile-card"></div>
    </article>
    <article class="info-card"><p class="eyebrow small">MOVE</p><h3>방향키</h3><p>이동</p></article>
    <article class="info-card"><p class="eyebrow small">ACTION</p><h3>Space · E · D</h3><p>뺏기 · 질주 · 슛</p></article>
    <article class="info-card"><p class="eyebrow small">MATCH</p><h3>2 Minutes</h3><p>온라인 시즌전</p></article>
  </section>
</main>
""",
)


REGISTER_HTML = render_page(
    "Register",
    "auth-page",
    """
<main class="auth-layout">
  <section class="auth-card">
    <p class="eyebrow">REGISTER</p>
    <h1>회원가입</h1>
    <form id="register-form" class="auth-form">
      <input name="username" type="text" minlength="3" maxlength="20" placeholder="사용자 이름" required>
      <input name="password" type="password" minlength="4" maxlength="50" placeholder="비밀번호" required>
      <input name="password_confirm" type="password" minlength="4" maxlength="50" placeholder="비밀번호 확인" required>
      <input name="recovery_code" type="password" minlength="4" maxlength="50" placeholder="복구코드" required>
      <button class="button primary wide" type="submit">계정 만들기</button>
    </form>
    <p id="auth-message" class="message-box"></p>
    <div class="auth-links-row">
      <a class="auth-link" href="/">홈</a>
      <a class="auth-link" href="/login">로그인</a>
      <a class="auth-link" href="/find-id">아이디 찾기</a>
      <a class="auth-link" href="/reset-password">비밀번호 찾기</a>
    </div>
  </section>
</main>
""",
)


LOGIN_HTML = render_page(
    "Login",
    "auth-page",
    """
<main class="auth-layout">
  <section class="auth-card">
    <p class="eyebrow">LOGIN</p>
    <h1>로그인</h1>
    <form id="login-form" class="auth-form">
      <input name="username" type="text" minlength="3" maxlength="20" placeholder="사용자 이름" required>
      <input name="password" type="password" minlength="4" maxlength="50" placeholder="비밀번호" required>
      <button class="button primary wide" type="submit">로그인</button>
    </form>
    <p id="auth-message" class="message-box"></p>
    <div class="auth-links-row">
      <a class="auth-link" href="/">홈</a>
      <a class="auth-link" href="/register">회원가입</a>
      <a class="auth-link" href="/find-id">아이디 찾기</a>
      <a class="auth-link" href="/reset-password">비밀번호 찾기</a>
    </div>
  </section>
</main>
""",
)


FIND_ID_HTML = render_page(
    "Find ID",
    "auth-page",
    """
<main class="auth-layout">
  <section class="auth-card">
    <p class="eyebrow">FIND ID</p>
    <h1>아이디 찾기</h1>
    <form id="find-id-form" class="auth-form">
      <input name="recovery_code" type="password" minlength="4" maxlength="50" placeholder="복구코드" required>
      <button class="button primary wide" type="submit">아이디 찾기</button>
    </form>
    <p id="auth-message" class="message-box"></p>
    <div class="auth-links-row">
      <a class="auth-link" href="/">홈</a>
      <a class="auth-link" href="/login">로그인</a>
      <a class="auth-link" href="/reset-password">비밀번호 찾기</a>
    </div>
  </section>
</main>
""",
)


RESET_PASSWORD_HTML = render_page(
    "Reset Password",
    "auth-page",
    """
<main class="auth-layout">
  <section class="auth-card">
    <p class="eyebrow">RESET PASSWORD</p>
    <h1>비밀번호 찾기</h1>
    <form id="reset-password-form" class="auth-form">
      <input name="username" type="text" minlength="3" maxlength="20" placeholder="사용자 이름" required>
      <input name="recovery_code" type="password" minlength="4" maxlength="50" placeholder="복구코드" required>
      <input name="new_password" type="password" minlength="4" maxlength="50" placeholder="새 비밀번호" required>
      <input name="new_password_confirm" type="password" minlength="4" maxlength="50" placeholder="새 비밀번호 확인" required>
      <button class="button primary wide" type="submit">비밀번호 재설정</button>
    </form>
    <p id="auth-message" class="message-box"></p>
    <div class="auth-links-row">
      <a class="auth-link" href="/">홈</a>
      <a class="auth-link" href="/login">로그인</a>
      <a class="auth-link" href="/find-id">아이디 찾기</a>
    </div>
  </section>
</main>
""",
)


ACCOUNT_HTML = render_page(
    "Account",
    "auth-page",
    """
<main class="auth-layout">
  <section class="auth-card">
    <p class="eyebrow">ACCOUNT</p>
    <h1>계정 관리</h1>
    <form id="account-update-form" class="auth-form">
      <input name="new_username" type="text" minlength="3" maxlength="20" placeholder="새 아이디">
      <input name="current_password" type="password" minlength="4" maxlength="50" placeholder="현재 비밀번호" required>
      <input name="new_password" type="password" minlength="4" maxlength="50" placeholder="새 비밀번호">
      <input name="new_password_confirm" type="password" minlength="4" maxlength="50" placeholder="새 비밀번호 확인">
      <input name="new_recovery_code" type="password" minlength="4" maxlength="50" placeholder="새 복구코드">
      <button class="button primary wide" type="submit">변경 저장</button>
    </form>
    <p id="auth-message" class="message-box"></p>
    <div class="auth-links-row">
      <a class="auth-link" href="/">홈</a>
      <a class="auth-link" href="/lobby">대기실</a>
    </div>
  </section>
</main>
""",
)


LOBBY_HTML = render_page(
    "Lobby",
    "lobby-page",
    """
<header class="shell">
  <nav class="topbar">
    <div class="brand">NEON DERBY LOBBY</div>
    <div class="nav-links">
      <a href="/">홈</a><a href="/practice">AI 연습</a><a href="/spectate">관전</a><a href="/rankings">순위표</a><a href="/shop">상점</a>
    </div>
  </nav>
</header>
<main class="lobby-layout">
  <section class="lobby-card main">
    <p class="eyebrow">ONLINE MATCH</p>
    <h1>1 VS 1 대기실</h1>
    <div class="button-row">
      <button id="queue-button" class="button primary">매칭 시작</button>
      <button id="leave-queue-button" class="button secondary">대기 취소</button>
      <button id="logout-button" class="button ghost">로그아웃</button>
    </div>
    <p id="lobby-status" class="message-box"></p>
  </section>
  <section class="lobby-card"><p class="eyebrow small">ME</p><div id="me-card" class="profile-card"></div></section>
  <section class="lobby-card"><p class="eyebrow small">RULE</p><div class="rules-list"><div><strong>승리</strong><span>승점 3 · 50G</span></div><div><strong>무승부</strong><span>승점 1 · 10G</span></div><div><strong>트로피</strong><span>승점 10마다 +1</span></div></div></section>
</main>
""",
)


MATCH_HTML = render_page(
    "Match",
    "match-page",
    """
<main class="match-layout online-layout">
  <div class="floating-home"><a class="button ghost" href="/">홈</a></div>
  <section class="match-stage">
    <div id="rotate-notice" class="rotate-notice">가로로 돌리면 더 잘 보입니다.</div>
    <canvas id="online-canvas" width="1440" height="810"></canvas>
    <div class="score-overlay">
      <div id="match-status-text">연결 중...</div>
      <div id="score-line" class="score-line">0 : 0</div>
      <div id="timer-text">120</div>
    </div>
    <div id="mobile-controls" class="mobile-controls"></div>
  </section>
  <section class="match-top-panels">
    <div class="panel chat-panel"><p class="eyebrow small">CHAT</p><div id="chat-log" class="feed-log chat-log"></div><form id="chat-form" class="chat-form"><input id="chat-input" maxlength="120" placeholder="메시지 입력"><button class="button ghost" type="submit">전송</button></form></div>
  </section>
  <aside class="match-sidebar">
    <div class="panel"><p class="eyebrow small">PLAYER</p><div id="player-meta"></div><div class="profile-line"><span>체력</span><strong id="stamina-text">100 / 100</strong></div><div class="profile-line"><span>골드</span><strong id="gold-text">0 G</strong></div></div>
    <div class="panel control-panel"><p class="eyebrow small">CONTROL</p><div class="rules-list"><div><strong>이동</strong><span>방향키</span></div><div><strong>질주</strong><span>E</span></div><div><strong>슛</strong><span>D</span></div><div><strong>뺏기</strong><span>Space</span></div></div></div>
    <div class="button-row vertical">
      <button id="forfeit-button" class="button secondary">포기하고 나가기</button>
      <button id="admin-pause-button" class="button ghost" hidden>일시정지/재개</button>
      <button id="admin-score-self-button" class="button ghost" hidden>내 점수 +1</button>
      <button id="admin-score-opponent-button" class="button ghost" hidden>상대 점수 +1</button>
    </div>
  </aside>
</main>
""",
)


PRACTICE_HTML = render_page(
    "Practice",
    "match-page",
    f"""
<main class="match-layout">
  <div class="floating-home"><a class="button ghost" href="/">홈</a></div>
  <section class="match-stage">
    <div id="offline-rotate-notice" class="rotate-notice">가로로 돌리면 더 잘 보입니다.</div>
    <canvas id="offline-canvas" width="1440" height="810"></canvas>
    <div class="score-overlay">
      <div id="offline-status-text">연습 중</div>
      <div id="offline-score-line" class="score-line">0 : 0</div>
      <div id="offline-timer-text">{PRACTICE_MATCH_SECONDS}</div>
    </div>
    <div id="offline-mobile-controls" class="mobile-controls"></div>
  </section>
  <aside class="match-sidebar">
    <div class="panel"><p class="eyebrow small">REWARD</p><div class="profile-line"><span>승리</span><strong>30 G</strong></div><div class="profile-line"><span>무승부</span><strong>10 G</strong></div><div class="profile-line"><span>체력</span><strong id="offline-stamina-text">100 / 100</strong></div></div>
    <div class="panel control-panel"><p class="eyebrow small">CONTROL</p><div class="rules-list"><div><strong>이동</strong><span>방향키</span></div><div><strong>질주</strong><span>E</span></div><div><strong>슛</strong><span>D</span></div><div><strong>뺏기</strong><span>Space</span></div></div></div>
    <div class="panel"><div id="offline-overlay-banner" class="message-box">강화된 AI 연습 경기입니다.</div></div>
    <div class="button-row vertical"><button id="offline-reset-button" class="button primary">다시 시작</button><button id="offline-exit-button" class="button secondary">나가기</button></div>
  </aside>
</main>
""",
)


SPECTATE_HTML = render_page(
    "Spectate",
    "match-page",
    """
<main class="match-layout">
  <div class="floating-home"><a class="button ghost" href="/">홈</a></div>
  <section class="match-stage">
    <canvas id="spectate-canvas" width="1440" height="810"></canvas>
  </section>
  <aside class="match-sidebar">
    <div class="panel"><p class="eyebrow small">LIVE</p><div id="spectate-match-title">진행 중인 경기 없음</div><div id="spectate-score-line" class="score-line">-</div><div id="spectate-timer">-</div></div>
    <div class="panel"><p class="eyebrow small">MATCHES</p><div id="spectate-list" class="feed-log"></div></div>
    <div class="panel"><p class="eyebrow small">FEED</p><div id="spectate-feed" class="feed-log"></div></div>
  </aside>
</main>
""",
)


RANKINGS_HTML = render_page(
    "Rankings",
    "lobby-page",
    """
<header class="shell"><nav class="topbar"><div class="brand">NEON DERBY RANKINGS</div><div class="nav-links"><a href="/">홈</a><a href="/lobby">대기실</a><a href="/shop">상점</a></div></nav></header>
<main class="lobby-layout"><section class="lobby-card main"><p class="eyebrow">RANK TABLE</p><h1>플레이어 순위표</h1><p class="hero-text">트로피, 승점, 승리 수 순으로 정렬됩니다.</p></section><section class="lobby-card"><div id="rankings-board" class="admin-list"></div></section></main>
""",
)


SHOP_HTML = render_page(
    "Shop",
    "lobby-page shop-page",
    """
<header class="shell"><nav class="topbar"><div class="brand">NEON DERBY SHOP</div><div class="nav-links"><a href="/">홈</a><a href="/lobby">대기실</a><a href="/shop">상점</a></div></nav></header>
<main class="lobby-layout">
  <section class="lobby-card main"><p class="eyebrow">SHOP</p><h1>골드 상점</h1><div id="shop-wallet" class="profile-card"></div><p id="shop-message" class="message-box"></p></section>
  <section class="admin-grid">
    <article class="lobby-card"><p class="eyebrow small">SHOT POWER</p><div class="rules-list"><div><strong>효과</strong><span>슛파워 +5</span></div><div><strong>가격</strong><span>70 골드</span></div></div><button class="button primary wide shop-buy-button" data-item="shot_power">구매</button></article>
    <article class="lobby-card"><p class="eyebrow small">SPRINT SPEED</p><div class="rules-list"><div><strong>효과</strong><span>전력질주 +3</span></div><div><strong>가격</strong><span>80 골드</span></div></div><button class="button primary wide shop-buy-button" data-item="sprint_speed">구매</button></article>
    <article class="lobby-card"><p class="eyebrow small">STAMINA</p><div class="rules-list"><div><strong>효과</strong><span>최대 체력 +5</span></div><div><strong>가격</strong><span>50 골드</span></div></div><button class="button primary wide shop-buy-button" data-item="max_stamina">구매</button></article>
  </section>
</main>
""",
)


ADMIN_HTML = render_page(
    "Admin",
    "lobby-page",
    """
<header class="shell"><nav class="topbar"><div class="brand">NEON DERBY ADMIN</div><div class="nav-links"><a href="/">홈</a><a href="/lobby">대기실</a><a href="/admin">관리자</a></div></nav></header>
<main class="lobby-layout">
  <section class="lobby-card main"><p class="eyebrow">CONTROL</p><h1>관리자 패널</h1><div class="button-row"><button id="refresh-admin-button" class="button primary">새로고침</button><button id="clear-queue-button" class="button secondary">대기열 비우기</button><button id="end-matches-button" class="button ghost">모든 경기 종료</button></div><p id="admin-message" class="message-box"></p></section>
  <section class="admin-grid">
    <article class="lobby-card"><p class="eyebrow small">USERS</p><div id="admin-users" class="admin-list"></div></article>
    <article class="lobby-card"><p class="eyebrow small">QUEUE</p><div id="admin-queue" class="admin-list"></div></article>
    <article class="lobby-card"><p class="eyebrow small">MATCHES</p><div id="admin-matches" class="admin-list"></div></article>
  </section>
</main>
""",
)


class GameHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        username = get_username_from_handler(self)
        if parsed.path == "/":
            self._send_html(HOME_HTML)
            return
        if parsed.path == "/register":
            self._send_html(REGISTER_HTML)
            return
        if parsed.path == "/login":
            self._send_html(LOGIN_HTML)
            return
        if parsed.path == "/find-id":
            self._send_html(FIND_ID_HTML)
            return
        if parsed.path == "/reset-password":
            self._send_html(RESET_PASSWORD_HTML)
            return
        if parsed.path == "/account":
            self._send_html(ACCOUNT_HTML)
            return
        if parsed.path == "/lobby":
            self._send_html(LOBBY_HTML)
            return
        if parsed.path == "/match":
            self._send_html(MATCH_HTML)
            return
        if parsed.path == "/practice":
            self._send_html(PRACTICE_HTML)
            return
        if parsed.path == "/spectate":
            self._send_html(SPECTATE_HTML)
            return
        if parsed.path == "/rankings":
            self._send_html(RANKINGS_HTML)
            return
        if parsed.path == "/shop":
            self._send_html(SHOP_HTML)
            return
        if parsed.path == "/admin":
            self._send_html(ADMIN_HTML)
            return
        if parsed.path == "/static/styles.css":
            self._serve_static("styles.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/static/game.js":
            self._serve_static("game.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/api/me":
            users = read_users()
            player = users.get(username, default_user()) if username else default_user()
            self._send_json({
                "authenticated": bool(username),
                "username": username,
                "role": player.get("role"),
                "wins": player.get("wins", 0),
                "draws": player.get("draws", 0),
                "losses": player.get("losses", 0),
                "trophies": player.get("trophies", 0),
                "season_points": player.get("season_points", 0),
                "season_matches": player.get("season_matches", 0),
                "gold": player.get("gold", 0),
                "upgrades": player.get("upgrades", default_user()["upgrades"]),
            })
            return
        if parsed.path == "/api/lobby-state":
            self._send_json(self._lobby_state(username))
            return
        if parsed.path == "/api/match-state":
            self._send_json(self._match_state(username))
            return
        if parsed.path == "/api/rankings":
            self._send_json(self._rankings_state())
            return
        if parsed.path == "/api/shop-state":
            self._send_json(self._shop_state(username))
            return
        if parsed.path == "/api/chat-state":
            self._send_json(self._chat_state(username))
            return
        if parsed.path == "/api/spectate-list":
            self._send_json(self._spectate_list())
            return
        if parsed.path == "/api/spectate-state":
            match_id = parse_qs(parsed.query).get("match_id", [""])[0]
            self._send_json(self._spectate_state(match_id))
            return
        if parsed.path == "/api/admin/state":
            if not is_admin(username):
                self._send_json({"message": "관리자 권한이 필요합니다."}, HTTPStatus.FORBIDDEN)
                return
            self._send_json(self._admin_state(username))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = parse_body(self)
        username = get_username_from_handler(self)
        if parsed.path == "/api/register":
            return self._register(body)
        if parsed.path == "/api/login":
            return self._login(body)
        if parsed.path == "/api/logout":
            return self._logout()
        if parsed.path == "/api/find-id":
            return self._find_id(body)
        if parsed.path == "/api/reset-password":
            return self._reset_password(body)
        if parsed.path == "/api/account/update":
            if not username:
                self._send_json({"message": "로그인이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            return self._update_account(username, body)
        if parsed.path == "/api/queue/join":
            if not username:
                self._send_json({"message": "로그인이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            with lock:
                cleanup_finished_player(username)
                if username not in queue and username not in player_to_match:
                    queue.append(username)
            self._send_json({"message": "매칭 대기열에 참가했습니다."})
            return
        if parsed.path == "/api/queue/leave":
            if not username:
                self._send_json({"message": "로그인이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            with lock:
                if username in queue:
                    queue.remove(username)
            self._send_json({"message": "대기열에서 나왔습니다."})
            return
        if parsed.path == "/api/input":
            if not username:
                self._send_json({"message": "로그인이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            with lock:
                state = player_states.get(username)
                if state is not None:
                    for key in ["up", "down", "left", "right", "sprint", "shoot", "steal"]:
                        if key in body:
                            state[key] = bool(body[key])
            self._send_json({"ok": True})
            return
        if parsed.path == "/api/forfeit":
            if not username:
                self._send_json({"message": "로그인이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            with lock:
                match_id = player_to_match.get(username)
                if match_id and match_id in matches and matches[match_id]["status"] == "live":
                    opponent = matches[match_id]["players"][0] if matches[match_id]["players"][1] == username else matches[match_id]["players"][1]
                    finish_match(matches[match_id], f"{username} 포기 · {opponent} 승리", forfeiter=username, end_type="forfeit")
            self._send_json({"message": "경기를 포기했습니다."})
            return
        if parsed.path == "/api/practice/reward":
            if not username:
                self._send_json({"message": "로그인이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            result = str(body.get("result", "")).strip()
            if result not in {"win", "draw", "loss"}:
                self._send_json({"message": "잘못된 결과입니다."}, HTTPStatus.BAD_REQUEST)
                return
            give_practice_reward(username, result)
            self._send_json({"message": "연습 보상이 지급되었습니다."})
            return
        if parsed.path == "/api/shop/buy":
            if not username:
                self._send_json({"message": "로그인이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            return self._buy_shop_item(username, str(body.get("item", "")).strip())
        if parsed.path == "/api/chat/send":
            if not username:
                self._send_json({"message": "로그인이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            message = str(body.get("message", "")).strip()
            if not message:
                self._send_json({"message": "메시지를 입력해주세요."}, HTTPStatus.BAD_REQUEST)
                return
            return self._send_chat(username, message)
        if parsed.path == "/api/admin/clear-queue":
            if not is_admin(username):
                self._send_json({"message": "관리자 권한이 필요합니다."}, HTTPStatus.FORBIDDEN)
                return
            with lock:
                queue.clear()
            self._send_json({"message": "대기열을 비웠습니다."})
            return
        if parsed.path == "/api/admin/end-matches":
            if not is_admin(username):
                self._send_json({"message": "관리자 권한이 필요합니다."}, HTTPStatus.FORBIDDEN)
                return
            with lock:
                for match in matches.values():
                    finish_match(match, "관리자가 경기를 종료했습니다.")
            self._send_json({"message": "모든 경기를 종료했습니다."})
            return
        if parsed.path == "/api/admin/delete-user":
            if not is_admin(username):
                self._send_json({"message": "관리자 권한이 필요합니다."}, HTTPStatus.FORBIDDEN)
                return
            target = str(body.get("username", "")).strip()
            if not target or target == ADMIN_USERNAME:
                self._send_json({"message": "삭제할 수 없는 사용자입니다."}, HTTPStatus.BAD_REQUEST)
                return
            with lock:
                users = read_users()
                if target not in users:
                    self._send_json({"message": "존재하지 않는 사용자입니다."}, HTTPStatus.NOT_FOUND)
                    return
                users.pop(target, None)
                write_users(users)
                if target in queue:
                    queue.remove(target)
                if target in player_to_match:
                    match_id = player_to_match[target]
                    if match_id in matches:
                        finish_match(matches[match_id], f"{target} 계정 삭제로 경기 종료", forfeiter=target)
                for token, owner in list(sessions.items()):
                    if owner == target:
                        sessions.pop(token, None)
            self._send_json({"message": f"{target} 계정을 삭제했습니다."})
            return
        if parsed.path == "/api/admin/match-control":
            if not is_admin(username):
                self._send_json({"message": "관리자 권한이 필요합니다."}, HTTPStatus.FORBIDDEN)
                return
            action = str(body.get("action", "")).strip()
            with lock:
                match_id = player_to_match.get(username)
                if not match_id or match_id not in matches:
                    self._send_json({"message": "참가 중인 경기가 없습니다."}, HTTPStatus.BAD_REQUEST)
                    return
                match = matches[match_id]
                if action == "toggle_pause":
                    match["status"] = "paused" if match["status"] == "live" else "live"
                    match["events"].insert(0, "관리자가 경기 상태를 전환했습니다.")
                    self._send_json({"message": "경기 상태를 바꿨습니다."})
                    return
                if action in {"add_score_self", "add_score_opponent"}:
                    opponent = match["players"][0] if match["players"][1] == username else match["players"][1]
                    scorer = username if action == "add_score_self" else opponent
                    match["score"][scorer] += 1
                    match["events"].insert(0, f"관리자 권한으로 {scorer} 점수 +1")
                    reset_positions(match)
                    self._send_json({"message": "점수를 조정했습니다."})
                    return
            self._send_json({"message": "지원하지 않는 명령입니다."}, HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def _lobby_state(self, username: str | None) -> dict:
        if not username:
            return {"authenticated": False}
        users = read_users()
        player = users.get(username, default_user())
        with lock:
            cleanup_finished_player(username)
            match_id = player_to_match.get(username)
            opponent = None
            if match_id and match_id in matches:
                players = matches[match_id]["players"]
                opponent = players[0] if players[1] == username else players[1]
            return {
                "authenticated": True,
                "username": username,
                "role": player.get("role", "player"),
                "wins": player.get("wins", 0),
                "draws": player.get("draws", 0),
                "losses": player.get("losses", 0),
                "trophies": player.get("trophies", 0),
                "season_points": player.get("season_points", 0),
                "season_matches": player.get("season_matches", 0),
                "gold": player.get("gold", 0),
                "queued": username in queue,
                "in_match": bool(match_id),
                "opponent": opponent,
            }

    def _match_state(self, username: str | None) -> dict:
        if not username:
            return {"authenticated": False}
        users = read_users()
        player = users.get(username, default_user())
        with lock:
            match_id = player_to_match.get(username)
            if not match_id or match_id not in matches:
                return {"authenticated": True, "in_match": False}
            match = matches[match_id]
            opponent = match["players"][0] if match["players"][1] == username else match["players"][1]
            return {
                "authenticated": True,
                "in_match": True,
                "status": match["status"],
                "end_type": match.get("end_type", ""),
                "forfeiter": match.get("forfeiter"),
                "username": username,
                "opponent": opponent,
                "time_left": match["time_left"],
                "score": match["score"],
                "events": match["events"],
                "field": match["field"],
                "players": match["players_state"],
                "ball": match["ball"],
                "chat": match.get("chat", []),
                "is_admin": is_admin(username),
                "wins": player.get("wins", 0),
                "draws": player.get("draws", 0),
                "losses": player.get("losses", 0),
                "trophies": player.get("trophies", 0),
                "season_points": player.get("season_points", 0),
                "season_matches": player.get("season_matches", 0),
                "gold": player.get("gold", 0),
                "stamina": round(match["players_state"][username]["stamina"]),
                "max_stamina": round(match["players_state"][username]["max_stamina"]),
            }

    def _rankings_state(self) -> dict:
        users = read_users()
        rows = sorted(
            (
                {
                    "username": username,
                    "wins": user.get("wins", 0),
                    "draws": user.get("draws", 0),
                    "losses": user.get("losses", 0),
                    "trophies": user.get("trophies", 0),
                    "season_points": user.get("season_points", 0),
                    "season_matches": user.get("season_matches", 0),
                }
                for username, user in users.items()
                if user.get("role") != "admin"
            ),
            key=lambda row: (-row["trophies"], -row["season_points"], -row["wins"], row["losses"], row["username"]),
        )
        for index, row in enumerate(rows, start=1):
            row["rank"] = index
        return {"players": rows}

    def _chat_state(self, username: str | None) -> dict:
        if not username:
            return {"authenticated": False}
        with lock:
            match_id = player_to_match.get(username)
            if not match_id or match_id not in matches:
                return {"authenticated": True, "in_match": False, "messages": []}
            return {
                "authenticated": True,
                "in_match": True,
                "messages": matches[match_id].get("chat", []),
            }

    def _send_chat(self, username: str, message: str) -> None:
        safe_message = message[:120]
        with lock:
            match_id = player_to_match.get(username)
            if not match_id or match_id not in matches:
                self._send_json({"message": "진행 중인 경기가 없습니다."}, HTTPStatus.BAD_REQUEST)
                return
            chat = matches[match_id].setdefault("chat", [])
            chat.insert(0, {"author": username, "text": safe_message})
            matches[match_id]["chat"] = chat[:18]
        self._send_json({"message": "전송 완료"})

    def _shop_state(self, username: str | None) -> dict:
        if not username:
            return {"authenticated": False}
        player = read_users().get(username, default_user())
        return {
            "authenticated": True,
            "username": username,
            "gold": player.get("gold", 0),
            "upgrades": player.get("upgrades", default_user()["upgrades"]),
        }

    def _buy_shop_item(self, username: str, item: str) -> None:
        catalog = {
            "shot_power": {"price": 70, "step": 1},
            "sprint_speed": {"price": 80, "step": 1},
            "max_stamina": {"price": 50, "step": 1},
        }
        if item not in catalog:
            self._send_json({"message": "존재하지 않는 상품입니다."}, HTTPStatus.BAD_REQUEST)
            return
        users = read_users()
        player = users.get(username)
        if not player:
            self._send_json({"message": "사용자를 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
            return
        if player.get("gold", 0) < catalog[item]["price"]:
            self._send_json({"message": "골드가 부족합니다."}, HTTPStatus.BAD_REQUEST)
            return
        player["gold"] -= catalog[item]["price"]
        player["upgrades"][item] = player["upgrades"].get(item, 0) + catalog[item]["step"]
        write_users(users)
        self._send_json({"message": "구매가 완료되었습니다."})

    def _spectate_list(self) -> dict:
        with lock:
            return {
                "matches": [
                    {
                        "id": match_id,
                        "players": match["players"],
                        "status": match["status"],
                        "time_left": match["time_left"],
                        "score": match["score"],
                    }
                    for match_id, match in matches.items()
                    if match["status"] in {"live", "paused"}
                ]
            }

    def _spectate_state(self, match_id: str) -> dict:
        with lock:
            live_ids = [mid for mid, match in matches.items() if match["status"] in {"live", "paused"}]
            selected = match_id if match_id in live_ids else (live_ids[0] if live_ids else None)
            if not selected:
                return {"available": False}
            match = matches[selected]
            return {
                "available": True,
                "match_id": selected,
                "status": match["status"],
                "time_left": match["time_left"],
                "score": match["score"],
                "events": match["events"],
                "field": match["field"],
                "players": match["players_state"],
                "ball": match["ball"],
                "players_order": match["players"],
            }

    def _admin_state(self, username: str) -> dict:
        users = read_users()
        with lock:
            return {
                "authenticated": True,
                "username": username,
                "users": [
                    {
                        "username": name,
                        "role": meta.get("role", "player"),
                        "wins": meta.get("wins", 0),
                        "draws": meta.get("draws", 0),
                        "losses": meta.get("losses", 0),
                        "trophies": meta.get("trophies", 0),
                        "season_points": meta.get("season_points", 0),
                        "season_matches": meta.get("season_matches", 0),
                        "gold": meta.get("gold", 0),
                    }
                    for name, meta in users.items()
                ],
                "queue": list(queue),
                "matches": [
                    {
                        "id": match_id,
                        "players": match["players"],
                        "status": match["status"],
                        "score": match["score"],
                    }
                    for match_id, match in matches.items()
                ],
            }

    def _register(self, body: dict) -> None:
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", "")).strip()
        password_confirm = str(body.get("password_confirm", "")).strip()
        recovery_code = str(body.get("recovery_code", "")).strip()
        if len(username) < 3 or len(password) < 4:
            self._send_json({"message": "아이디는 3자 이상, 비밀번호는 4자 이상이어야 합니다."}, HTTPStatus.BAD_REQUEST)
            return
        if len(recovery_code) < 4:
            self._send_json({"message": "복구코드는 4자 이상이어야 합니다."}, HTTPStatus.BAD_REQUEST)
            return
        if password != password_confirm:
            self._send_json({"message": "비밀번호가 일치하지 않습니다."}, HTTPStatus.BAD_REQUEST)
            return
        users = read_users()
        normalized = normalize_username(username)
        if any(normalize_username(existing) == normalized for existing in users):
            self._send_json({"message": "이미 존재하는 사용자 이름입니다."}, HTTPStatus.BAD_REQUEST)
            return
        users[username] = {
            **default_user("player"),
            "password_hash": hash_password(password),
            "recovery_code_hash": hash_password(recovery_code),
        }
        write_users(users)
        self._send_json({"message": "회원가입이 완료되었습니다."})

    def _login(self, body: dict) -> None:
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", "")).strip()
        users = read_users()
        if username not in users or users[username]["password_hash"] != hash_password(password):
            self._send_json({"message": "아이디 또는 비밀번호가 올바르지 않습니다."}, HTTPStatus.UNAUTHORIZED)
            return
        if username in sessions.values():
            self._send_json({"message": "이미 로그인 중인 계정입니다."}, HTTPStatus.CONFLICT)
            return
        token = secrets.token_hex(16)
        sessions[token] = username
        self._send_json(
            {"message": "로그인 성공", "username": username},
            cookies={SESSION_COOKIE: token},
            cookie_max_age=SESSION_MAX_AGE,
        )

    def _logout(self) -> None:
        cookie_header = self.headers.get("Cookie", "")
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        session = cookie.get(SESSION_COOKIE)
        if session and session.value in sessions:
            owner = sessions.pop(session.value)
            with lock:
                if owner in queue:
                    queue.remove(owner)
        self._send_json({"message": "로그아웃 완료"}, cookies={SESSION_COOKIE: ""}, clear_cookie=True)

    def _find_id(self, body: dict) -> None:
        recovery_code = str(body.get("recovery_code", "")).strip()
        if len(recovery_code) < 4:
            self._send_json({"message": "복구코드를 입력해주세요."}, HTTPStatus.BAD_REQUEST)
            return
        code_hash = hash_password(recovery_code)
        users = read_users()
        matches_found = [username for username, meta in users.items() if meta.get("recovery_code_hash") == code_hash and meta.get("role") != "admin"]
        if len(matches_found) != 1:
            self._send_json({"message": "일치하는 계정을 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
            return
        self._send_json({"message": "아이디를 찾았습니다.", "username": matches_found[0]})

    def _reset_password(self, body: dict) -> None:
        username = str(body.get("username", "")).strip()
        recovery_code = str(body.get("recovery_code", "")).strip()
        new_password = str(body.get("new_password", "")).strip()
        new_password_confirm = str(body.get("new_password_confirm", "")).strip()
        users = read_users()
        if username not in users:
            self._send_json({"message": "존재하지 않는 사용자입니다."}, HTTPStatus.NOT_FOUND)
            return
        if users[username].get("recovery_code_hash") != hash_password(recovery_code):
            self._send_json({"message": "복구코드가 올바르지 않습니다."}, HTTPStatus.UNAUTHORIZED)
            return
        if len(new_password) < 4:
            self._send_json({"message": "새 비밀번호는 4자 이상이어야 합니다."}, HTTPStatus.BAD_REQUEST)
            return
        if new_password != new_password_confirm:
            self._send_json({"message": "새 비밀번호 확인이 일치하지 않습니다."}, HTTPStatus.BAD_REQUEST)
            return
        users[username]["password_hash"] = hash_password(new_password)
        write_users(users)
        self._send_json({"message": "비밀번호가 재설정되었습니다."})

    def _update_account(self, username: str, body: dict) -> None:
        current_password = str(body.get("current_password", "")).strip()
        new_username = str(body.get("new_username", "")).strip()
        new_password = str(body.get("new_password", "")).strip()
        new_password_confirm = str(body.get("new_password_confirm", "")).strip()
        new_recovery_code = str(body.get("new_recovery_code", "")).strip()
        users = read_users()
        player = users.get(username)
        if not player or player.get("password_hash") != hash_password(current_password):
            self._send_json({"message": "현재 비밀번호가 올바르지 않습니다."}, HTTPStatus.UNAUTHORIZED)
            return
        if new_password and new_password != new_password_confirm:
            self._send_json({"message": "새 비밀번호 확인이 일치하지 않습니다."}, HTTPStatus.BAD_REQUEST)
            return
        if new_password and len(new_password) < 4:
            self._send_json({"message": "새 비밀번호는 4자 이상이어야 합니다."}, HTTPStatus.BAD_REQUEST)
            return
        if new_recovery_code and len(new_recovery_code) < 4:
            self._send_json({"message": "복구코드는 4자 이상이어야 합니다."}, HTTPStatus.BAD_REQUEST)
            return
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        session = cookie.get(SESSION_COOKIE)
        session_token = session.value if session else None
        updated_username = username
        if new_username and normalize_username(new_username) != normalize_username(username):
            if username in queue or username in player_to_match:
                self._send_json({"message": "대기열/경기 중에는 아이디를 변경할 수 없습니다."}, HTTPStatus.BAD_REQUEST)
                return
            if any(normalize_username(existing) == normalize_username(new_username) for existing in users):
                self._send_json({"message": "이미 존재하는 사용자 이름입니다."}, HTTPStatus.BAD_REQUEST)
                return
            users[new_username] = users.pop(username)
            updated_username = new_username
            if session_token and session_token in sessions:
                sessions[session_token] = new_username
        if new_password:
            users[updated_username]["password_hash"] = hash_password(new_password)
        if new_recovery_code:
            users[updated_username]["recovery_code_hash"] = hash_password(new_recovery_code)
        write_users(users)
        self._send_json({"message": "계정 정보가 변경되었습니다.", "username": updated_username})

    def _serve_static(self, relative_path: str, content_type: str) -> None:
        file_path = STATIC_DIR / relative_path
        if not file_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Static file not found")
            return
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self,
        payload: dict,
        status: HTTPStatus = HTTPStatus.OK,
        cookies: dict[str, str] | None = None,
        clear_cookie: bool = False,
        cookie_max_age: int | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookies:
            for name, value in cookies.items():
                cookie = SimpleCookie()
                cookie[name] = value
                cookie[name]["path"] = "/"
                cookie[name]["samesite"] = "Lax"
                if clear_cookie:
                    cookie[name]["max-age"] = 0
                elif cookie_max_age is not None:
                    cookie[name]["max-age"] = cookie_max_age
                self.send_header("Set-Cookie", cookie.output(header="").strip())
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def run() -> None:
    ensure_storage()
    threading.Thread(target=game_loop, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), GameHandler)
    print(f"Neon Derby Online is running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
