# Hyperframes Composition Brief: Voxline

## Objective
Короткий launch-ролик для Voxline (голосові ШІ-агенти для дзвінків).

## Output
- Composition directory: `promo-video/composition/`
- Rendered video: `promo-video/brag.mp4`
- Format: landscape — 1920x1080
- Duration: 21s

## Source Material
- Project root: D:\Voxline
- Primary files read: `landing/index.html` (копірайт uk, CSS-змінні, макети), структура `frontend/src/pages`
- Product name: Voxline
- Tagline: «Дзвінки клієнтам, які робить ШІ»
- Key UI to recreate: картка живого дзвінка з розшифровкою, картка «Підсумок дзвінка», картка кампанії
- Copy verbatim: див. `brag-plan.md` (усі репліки, рядки підсумку, SMS, «Готові почути, як це звучить?», «Замовити демо»)

## Creative Direction
- Tone preset: app-store; direction: «підслухана розмова»
- Hook: заголовок лендингу, градієнтний другий рядок на 3.70s
- Outro: «Готові почути, як це звучить?» + кнопка «Замовити демо»
- Avoid: generic SaaS language, абстрактні заливки, контакти менеджера

## Visual Identity
- Background #f6f7fb, surface #fff, text #0b1220, accent #2563eb→#7c5cff
- Fonts: Inter (display+body), JetBrains Mono (таймер)

## Storyboard
Див. `brag-plan.md`: 1 Hook 3.7s · 2 Live call 6.3s · 3 Call result 4.3s · 4 Scale 3.6s · 5 Outro 3.1s.

## Audio
- Role: warm bed + sparse accents
- Music: `assets/music/happy-beats-business-moves-vol-11-by-ende-dot-app.mp3`, vol ~0.32, fade-out 1.5s
- Cue guidance: preset vol-11, strong cues 3.70 / 12.65 / 17.91, beats 10.54 / 11.06 / 11.60 / 12.12
- Audio-reactive: subtle; `assets/music/rms.json` (30 fps, виділено ffmpeg) модулює фоновий glow і підсвітку картки дзвінка
- SFX: impactSoft_medium_001 (reveal 3.7), drop_001/002 (репліки), select_008 (рядки підсумку), impactBell_heavy_000 (Доставлено, фінал), mouseclick1 (клік демо)

## Hyperframes Instructions
Нативний контракт Hyperframes (`data-composition-id`, `data-start`/`data-duration`, GSAP paused timeline на `window.__timelines`). Домен-скіли Hyperframes у цьому середовищі не встановлені, тому використано `npx hyperframes docs`. Gate: `npx hyperframes check`.
