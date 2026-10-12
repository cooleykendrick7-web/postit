# Post It — Route & Template Contract (BINDING)

Backend implements EXACTLY these routes. Frontend templates use EXACTLY these
template names, context variable names, and form field names.

## Global context (available in every template)
- `user` — logged-in user dict or None: {id, name, email, world_title, avatar,
  verified (0/1)}
- `logo_url` = "/static/logo.png"
- `flash` — optional string message to show
- `verified_enabled` — 0/1, whether Stripe verified checkout is enabled

## Post card partial: `partials/post_card.html`
Context var: `post` — dict with keys:
  id, user_id, author_name, author_avatar, verified, world_title, body, kind
  ('text'|'photo'|'video'|'audio'), media (url or ""), color (hex), privacy,
  created_at (display string), counts {like,love,laugh,fire,skull},
  my_reaction (kind or ""), comments_count, comments (list, only on detail page;
  on feed show just count), shared (None or dict of original post with keys
  id, author_name, verified, body, media, kind), can_edit (bool), can_delete (bool),
  is_owner (bool)
Reaction buttons POST to `/post/{id}/react` with field `kind`.
Comment form (detail page only) POSTs to `/post/{id}/comment` with field `body`.
Share button POSTs to `/post/{id}/share`.
Report: small form POST to `/post/{id}/report` with field `reason`.
Edit (owner): inline form POST to `/post/{id}/edit` with field `body`.
Delete (owner): POST to `/post/{id}/delete`.

## Stories tray partial: `partials/stories.html`
Context var: `stories` — list of {id, user_id, user_name, avatar, media, kind,
verified}. Links to `/stories/{id}`.

## Routes & templates

| Method | Path | Template | Context |
|---|---|---|---|
| GET | / | (redirect /home or /login) | |
| GET | /signup | auth/signup.html | |
| POST | /signup | fields: name, email, password | -> redirect /home |
| GET | /login | auth/login.html | error? |
| POST | /login | fields: email, password | -> redirect /home |
| GET | /logout | redirect / | |
| GET | /home | home.html | user, stories, posts (list of post-card dicts) |
| POST | /posts | fields: body, media (file), color, privacy, allow (csv ids), deny (csv ids) | -> redirect /home |
| GET | /post/{id} | post.html | post (with comments list) |
| POST | /post/{id}/edit | field: body | -> redirect back |
| POST | /post/{id}/delete | | -> redirect /home |
| POST | /post/{id}/comment | field: body | -> redirect /post/{id} |
| POST | /post/{id}/react | field: kind | -> JSON {ok, counts, my_reaction} |
| POST | /post/{id}/share | | -> redirect /home |
| POST | /post/{id}/report | field: reason | -> redirect back |
| GET | /world/{id} | profile.html | profile (user dict + extra: bio, birthday, hometown, city, workplace, job_title, cover, friend_count, is_owner, is_friend, req_status ('none'|'pending_in'|'pending_out'|'friends'), blocked_by_me), posts |
| GET | /settings/profile | profile_edit.html | profile |
| POST | /settings/profile | fields: world_title, name, bio, birthday, hometown, city, workplace, job_title, avatar (file), cover (file) | -> redirect /world/{id} |
| GET | /friends | friends.html | incoming (requests), sent, friends |
| POST | /friends/request/{id} | | |
| POST | /friends/accept/{id} | | |
| POST | /friends/decline/{id} | | |
| POST | /friends/remove/{id} | | |
| GET | /search | search.html | q, results (user dicts with verified) |
| POST | /stories | field: media (file) | -> redirect /home |
| GET | /stories/{id} | story.html | story {id, user_id, user_name, avatar, verified, media, kind, created_at} |
| GET | /inbox | inbox.html | convos [{other_id, other_name, other_avatar, verified, last_body, last_at, unread}] |
| GET | /inbox/{uid} | thread.html | other {id,name,avatar,verified}, messages [{id, mine (bool), body, created_at}] |
| POST | /inbox/{uid} | field: body | -> redirect /inbox/{uid} |
| POST | /block/{uid} | | -> redirect back |
| POST | /unblock/{uid} | | -> redirect back |
| GET | /explore | explore.html | posts (public post cards), worlds (list of user dicts) |
| GET | /market | market.html | listings, groups, iso_posts, categories, q |
| GET | /market/new | listing_form.html | categories |
| POST | /market/new | fields: title, category, price, description, shipping (checkbox "1"), meetup_city, photos (files, multiple) | -> redirect /market/{id} |
| GET | /market/{id} | listing.html | listing {id,title,category,price,description,photos[],shipping,meetup_city,status,seller (user dict),created_at}, is_owner, offers (owner only), avg_rating, rating_count |
| POST | /market/{id}/offer | fields: amount, message | |
| POST | /market/{id}/status | field: status (active/pending/sold) | owner only |
| POST | /market/{id}/delete | | owner only |
| POST | /market/seller/{uid}/rate | fields: stars, comment | |
| GET | /market/groups/new | group_form.html | |
| POST | /market/groups/new | fields: name, description | -> redirect /market/groups/{id} |
| GET | /market/groups/{id} | group.html | group {id,name,description,owner_name,member_count}, is_member, posts [{id,user_name,avatar,verified,body,created_at}] |
| POST | /market/groups/{id}/join | | |
| POST | /market/groups/{id}/post | field: body | |
| GET | /market/iso/new | iso_form.html | categories |
| POST | /market/iso/new | fields: title, description, category, max_price | -> redirect /market |
| GET | /verified | verified.html | enabled |
| POST | /verified/checkout | | -> 400 "coming soon" when disabled |
| GET | /admin/login | admin/login.html | error? |
| POST | /admin/login | field: password | -> redirect /admin |
| GET | /admin/logout | | |
| GET | /admin | admin/dashboard.html | stats {users, posts, reports_open, listings}, recent_reports |
| GET | /admin/users | admin/users.html | q, users |
| GET | /admin/user/{id} | admin/user_detail.html | profile, posts |
| POST | /admin/user/{id}/block | | |
| POST | /admin/user/{id}/unblock | | |
| POST | /admin/user/{id}/delete | | |
| POST | /admin/user/{id}/message | field: body | sends as "Post It Team" |
| GET | /admin/reports | admin/reports.html | reports [{id, reporter_name, target_type, target_id, reason, status, created_at}] |
| POST | /admin/reports/{id}/resolve | | |
| GET | /admin/posts | admin/posts.html | posts (with author names) |
| POST | /admin/post/{id}/delete | | |

## Theme
- Glossy black + neon red. Background near-black (#0a0a0c), cards dark chrome
  gradients, neon red (#ff2222) glows/accents, white text.
- Logo at /static/logo.png — header shows logo + "Post It" wordmark.
- Sticky-note post cards: note background = post.color; dark colors get light text.
- Verified badge: `🌙⭐` in a span.verified-badge next to names everywhere, plus
  gold-tinted profile header for verified users (CSS class .verified-glow).
- Mobile-first, single static/style.css, vanilla JS only (inline or /static/app.js).
- All forms: plain HTML forms POST (no JS required). Reactions may use fetch w/
  graceful fallback (also work as plain form posts).

## Notes
- Uploaded media URLs look like /uploads/posts/<file>, /uploads/avatars/<file>, etc.
- Avatars may be "" → show a default initial circle (CSS).
- Dates are pre-formatted display strings.
- Every page extends base.html. base.html has blocks: title, content, extra_js.
- Nav in base.html: Home, Explore, Market, Inbox (with unread dot if `unread_count`>0),
  Friends, Verified, profile (world) link, Logout.
