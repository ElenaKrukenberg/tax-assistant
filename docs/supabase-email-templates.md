# Supabase emails: templates and setup

Ready-to-paste templates for **Dashboard → Authentication → Email Templates**.
Two templates matter: the first email to a new address uses **Confirm signup**,
every later one uses **Magic Link**.

The email language follows the UI language via `{{ .Data.locale }}` — the
frontend passes it in `signInWithOtp` (options.data.locale) and it lands in
user_metadata. Known limit: the very first email to a brand-new address may
arrive in English (the metadata is not written yet at send time).

## Subject (both templates)

```
{{ if eq .Data.locale "ru" }}Ваша ссылка для входа в German Tax Assistant{{ else if eq .Data.locale "de" }}Ihr Anmeldelink für German Tax Assistant{{ else if eq .Data.locale "tr" }}German Tax Assistant giriş bağlantınız{{ else }}Your sign-in link for German Tax Assistant{{ end }}
```

Fallback if the Subject field rejects template syntax:

```
German Tax Assistant: sign-in link / Ссылка для входа
```

## Magic Link — body

```html
{{ if eq .Data.locale "ru" }}
<h2>Вход в German Tax Assistant</h2>
<p>Нажмите на ссылку, чтобы войти. Она действует один раз.</p>
<p><a href="{{ .ConfirmationURL }}">Войти</a></p>
<p>Если вы не запрашивали вход, просто удалите это письмо.</p>
{{ else if eq .Data.locale "de" }}
<h2>Anmeldung bei German Tax Assistant</h2>
<p>Klicken Sie auf den Link, um sich anzumelden. Er ist einmal gültig.</p>
<p><a href="{{ .ConfirmationURL }}">Anmelden</a></p>
<p>Wenn Sie diese Anmeldung nicht angefordert haben, löschen Sie diese E-Mail einfach.</p>
{{ else if eq .Data.locale "tr" }}
<h2>German Tax Assistant girişi</h2>
<p>Giriş yapmak için bağlantıya tıklayın. Bir kez geçerlidir.</p>
<p><a href="{{ .ConfirmationURL }}">Giriş yap</a></p>
<p>Bu girişi siz istemediyseniz bu e-postayı silebilirsiniz.</p>
{{ else }}
<h2>Sign in to German Tax Assistant</h2>
<p>Click the link to sign in. It works once.</p>
<p><a href="{{ .ConfirmationURL }}">Sign in</a></p>
<p>If you did not request this, you can simply delete this email.</p>
{{ end }}
```

## Confirm signup — body

Same idea, first-contact wording: the link confirms the address and signs in.

```html
{{ if eq .Data.locale "ru" }}
<h2>Добро пожаловать в German Tax Assistant</h2>
<p>Нажмите на ссылку: она подтвердит адрес и сразу выполнит вход.</p>
<p><a href="{{ .ConfirmationURL }}">Подтвердить и войти</a></p>
<p>Если вы не создавали аккаунт, просто удалите это письмо.</p>
{{ else if eq .Data.locale "de" }}
<h2>Willkommen bei German Tax Assistant</h2>
<p>Klicken Sie auf den Link: Er bestätigt Ihre Adresse und meldet Sie direkt an.</p>
<p><a href="{{ .ConfirmationURL }}">Bestätigen und anmelden</a></p>
<p>Wenn Sie kein Konto erstellt haben, löschen Sie diese E-Mail einfach.</p>
{{ else if eq .Data.locale "tr" }}
<h2>German Tax Assistant'a hoş geldiniz</h2>
<p>Bağlantıya tıklayın: adresinizi doğrular ve sizi doğrudan giriş yaptırır.</p>
<p><a href="{{ .ConfirmationURL }}">Doğrula ve giriş yap</a></p>
<p>Hesap oluşturmadıysanız bu e-postayı silebilirsiniz.</p>
{{ else }}
<h2>Welcome to German Tax Assistant</h2>
<p>Click the link: it confirms your address and signs you in.</p>
<p><a href="{{ .ConfirmationURL }}">Confirm and sign in</a></p>
<p>If you did not create an account, you can simply delete this email.</p>
{{ end }}
```

## Sender name

On the built-in mailer the sender is always "Supabase Auth
<noreply@mail.app.supabase.io>" — **it cannot be changed without custom SMTP**;
a platform limit, not a setting. Options:

1. **Leave it until after the submission.** Zero hours; keeps the 2 emails/hour
   project-wide limit.
2. **Gmail SMTP** (Settings → Auth → SMTP): sender becomes "German Tax
   Assistant <your@gmail.com>", limit grows to ~500/day. Fine for a study
   project. ~1 hour.
3. **Resend/Brevo with an own domain**: a real noreply@domain — right for a
   product, out of the sprint's horizon.

Recommendation: option 2, in the same polish phase as Google OAuth — Google
removes the demo's email dependency entirely, SMTP fixes sender and limit for
those who still sign in by link.
