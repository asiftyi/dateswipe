# 💘 DateSwipe — Tinder-style swipe dating web app

A complete, sellable dating web app: **swipe → match → chat → video call → games → gifts**,
with a paid **Premium** tier, coin wallet, and referral earnings. Installable on phones like a
native app (PWA). Backend is **Python stdlib only** — no pip, no database server.

## Run it

```bash
cd date-swipe
python3 app.py
# open: http://127.0.0.1:8767
```

First run creates `date_swipe.db` (SQLite) and `config.json` (app secret + admin token).
Demo data: `python3 seed_demo.py` → 8 fictional profiles, password `demo1234` for all.

## Features

| Area | What you get |
|---|---|
| 🔐 Auth | Email signup/login, PBKDF2 password hashing, signed HttpOnly session cookies, **18+ enforced** (birthdate check), banned users can't log in |
| 💘 Discover | Swipe deck with buttery drag physics, LIKE/NOPE/super-like, mutual-like → **match celebration** (confetti) |
| 💬 Chat | iMessage-style bubbles, timestamps, day dividers, typing shimmer, polls every 3s |
| 📹 Video calls | WebRTC peer-to-peer with REST-polling signaling (no WebSocket needed), Google STUN, mute/camera toggles |
| 🎮 Games | Tic-Tac-Toe + Rock-Paper-Scissors for matched users, **server-side move validation**, game invites in chat |
| 🎁 Gifts | 8-gift catalog (🌹10 → 🚀2000 coins), coin wallet, beautiful gift cards in chat |
| 💰 Referrals | Every user gets an 8-char code; referred adult signup → **+7 days Premium** for the referrer |
| ⭐ Premium | Unlimited likes, "liked you" list — `is_premium` + `premium_until` |
| 🛡️ Safety | Report, block (deletes matches), banned flag |
| 📱 PWA | Installable (Add to Home Screen), offline-cached shell, dark premium UI |

## Admin

Your **admin token** is printed on first server start and stored in `config.json`:

```bash
# grant 30 days premium
curl -X POST localhost:8767/api/admin/grant_premium \
  -H 'Content-Type: application/json' \
  -d '{"admin_token":"<TOKEN>","email":"user@mail.com","days":30}'

# grant coins (manual top-up)
curl -X POST localhost:8767/api/admin/grant_coins \
  -H 'Content-Type: application/json' \
  -d '{"admin_token":"<TOKEN>","email":"user@mail.com","coins":500}'

# view all referrals
curl 'localhost:8767/api/admin/referrals?admin_token=<TOKEN>'
```

## Connecting real payments (Stripe)

1. In Stripe Dashboard: create a **Payment Link** (e.g. $4.99/mo or a coin pack).
2. Put it in `config.json`: `"stripe_payment_link": "https://buy.stripe.com/..."`.
3. The app's Premium page and Wallet "Buy coins" button will link to it automatically.

**Automatic activation (webhooks):** the app currently uses *manual* activation —
after a customer pays, you run `grant_premium` / `grant_coins` (above). For full
automation, add a Stripe webhook endpoint that verifies the signature and calls the
same grant functions (webhook handler not included — it's ~40 lines with stdlib
`hmac`, ask your developer).

**Referral cash payouts:** in-app referral rewards are **Premium days** (automatic).
Any cash/affiliate payouts are settled **manually by the operator** outside the app.

## Ad monetization (Google AdSense)

The app has built-in ad slots (Discover feed bottom, Matches bottom, Chat above the
input bar) plus a Privacy Policy page — both are **required for AdSense approval**.
Slots render nothing until you configure them, so the layout never breaks.

**Steps:**
1. Deploy the app on your own **domain + HTTPS** (see Deploy notes).
2. Sign up at `google.com/adsense` with that domain. Google reviews the site
   (usually 1–2 weeks): it needs real content, the Privacy Policy page (included),
   and no policy violations.
3. In AdSense: create 3 **Display ad units** (one per placement) → note each
   **Ad slot ID**, and your publisher ID (`ca-pub-XXXXXXXXXXXXXXXX`).
4. In `config.json`:
   ```json
   "ads": {"enabled": true, "client_id": "ca-pub-XXXXXXXXXXXXXXXX",
           "slots": {"discover": "1111111111", "matches": "2222222222", "chat": "3333333333"}}
   ```
5. Restart `app.py`. Ads appear automatically.

**Dating-app policy notes:** AdSense allows mainstream dating sites but bans
sexually explicit content and escort/hookup-for-pay framing — keep profiles and
marketing clean, 18+ gate strictly enforced (already built in).
**Realistic earnings:** roughly $1–3 per 1,000 ad views. No users = no revenue;
ads pay once traffic exists. Avoid cheap networks (Adsterra etc.) — their
gambling/adult ads destroy trust in a dating app.

## Deploy notes

- Needs **HTTPS** (getUserMedia/video calls and PWA install require a secure context;
  `localhost` counts as secure for testing).
- Any small **VPS** works: `python3 app.py` behind nginx/Caddy as a reverse proxy.
  SQLite = single server; for scale, migrate to Postgres later.
- Keep `config.json` secret (it holds the session-signing key + admin token).

## Honest limits

- **Video calls are peer-to-peer via STUN.** Most home/mobile networks connect fine;
  symmetric/corporate NATs may fail without a **TURN server** (operator upgrade path:
  add `turn:` credentials to the `iceServers` list in `web/app.js`).
- **No App Store / Play Store listing** — it's a PWA: users install from the browser
  ("Add to Home Screen"). No push notifications without an FCM/APNs setup (not built in).
- **No full Ludo** — games are quick casual (Tic-Tac-Toe, Rock-Paper-Scissors) by design.
- **Moderation is manual** — reports land in the DB; review/ban via SQL or the admin token.
- **Free-plan abuse prevention** (fake profiles, spam) is the operator's job:
  consider email verification, rate limits, and photo moderation before public launch.
- **Real-money cashout** for coins is not built in.
