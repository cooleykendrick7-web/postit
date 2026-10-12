# Post It — prototype v1

Ken's fun, messy, Facebook-style social platform. Glossy black + neon red theme,
sticky-note posts, profile "worlds", and Post It Market.

## Run it

```bash
cd ~/workspace/postit
./venv/bin/uvicorn app:app --host 127.0.0.1 --port 8001
```

Open http://127.0.0.1:8001 — sign up and you're in. Local prototype only
(not deployed anywhere).

- DB: `postit.db` (SQLite, created on first run)
- Uploads: `uploads/` (avatars, covers, posts, stories, market)
- Admin panel: `/admin` — credentials in
  `~/workspace/goals/post-it-social-platform/hidden_files/admin-credentials.txt`
  (strong random password, generated once; never 1195)

## What's in v1 (all free, no paid services)

- Auth: signup/login/logout (bcrypt, cookie sessions). No SMS — users keep their own passwords.
- Profile "worlds": custom world title ("Kenny World"), name, bio, birthday,
  hometown, city, workplace, job title, avatar + cover uploads.
- Posts: text/photo/video/audio uploads, sticky-note cards with per-post color,
  edit/delete, privacy (Public / Friends / Only me / Custom allow+deny lists),
  share/repost, comments, 5 reactions (👍❤️😂🔥💀).
- Stories: photo/video, auto-expire after 24h, tray on home.
- Friends: request/accept/decline/remove; people search by name, job, city, hometown, workplace.
- Inbox: 1:1 messaging with block/unblock (blocks also hide profiles/posts).
- Home feed + Explore (public posts & worlds).
- Post It Market: listings (photos, price, categories, shipping toggle, meetup city),
  make-an-offer, sold/pending/active, seller star ratings, market groups, ISO posts.
- Verified: $5/mo 🌙⭐ badge page exists but checkout is DISABLED
  (`STRIPE_VERIFIED_ENABLED` env flag, default off) — UI shows "coming soon".
- Admin: list/search users, view any profile, block/unblock, delete accounts,
  message any user as "Post It Team", review reports, delete any post.
- Report buttons on posts feed the admin panel.

## Tests

`/tmp/postit_test.py` — 46 end-to-end checks (signup → post → friends → messaging →
market → admin), all passing.
