# Login page handoff (next frontend task)

Backend foundation is ready. Do **not** redesign auth APIs again for the landing page — wire the UI to the routes below.

## Intended public UX

1. **Student login (default landing)**
   - Fields: enrollment number (11 digits), password
   - Links: “Forgot password?” → call `POST /auth/password/forgot` (currently 501 until SMTP/OTP configured)
   - Optional: “First-time activation” (future; accounts may start as `pending_activation`)

2. **Admin entry**
   - Visible secondary action: “Are you an admin? Admin Login”
   - Navigates to a dedicated admin login view/state (not the same form as students)
   - Fields: username, password
   - Backend rejects non-admin accounts on the admin endpoint

3. **Security (frontend rules)**
   - Never send or trust a client-chosen `role`
   - Never authorize profile views by enrollment number from the URL alone — always use `Authorization: Bearer <token>` and `GET /auth/me`
   - Store token as today (`cc_token`); also store `cc_role` from the **response** for UI gating only (server still enforces)

## API map

| UI action | Method | Path | Body |
|-----------|--------|------|------|
| Student login | POST | `/auth/student/login` | `{ "enrollment_number": "01123456789", "password": "..." }` |
| Admin login | POST | `/auth/admin/login` | `{ "username": "admin", "password": "..." }` |
| Legacy login (current SPA) | POST | `/auth/login` | `{ "username", "password" }` — keep until SPA is updated |
| Profile / greeting | GET | `/auth/me` | Bearer token |
| Update profile | PATCH | `/auth/me` | Student-editable fields only (JWT identity) |
| Public register | POST | `/auth/register` | **Disabled (403)** — do not offer as default |
| Forgot password | POST | `/auth/password/forgot` | 501 until configured |
| Change password | POST | `/auth/password/change` | 501 until configured |

Successful login response includes: `access_token`, `role`, `full_name`, optional `first_name`, optional `enrollment_number`.

### Profile completion (`GET`/`PATCH /auth/me`)

For **students**, `profile_complete` is true only when all of these are present:
`first_name`, `last_name`, `enrollment_number`, `course`, `academic_year`, `current_semester`, `email`.

`email_verified` is **not** required for completion (only for trusting email for password recovery later).

Student-editable allowlist (further gated fill-once): `email` (always; resets verification), plus `first_name` / `last_name` / `academic_year` / `current_semester` only when currently empty. Never: role, account_status, enrollment_number, course.

## Required config before OTP / rate limits

- SMTP (or equivalent) for real email delivery — never fake OTP emails
- `LOGIN_RATE_LIMIT_PER_MINUTE`, password-reset hourly caps, OTP TTL + max attempts
- See `AUTH_SECURITY_CONFIG_NOTES` in `app/routers/auth_router.py`

## Provisioning

- Admin bootstrap: `python scripts/seed_users.py`
- Students: copy `scripts/provision_students_TEMPLATE.py` locally; mark demo rows with `is_demo=1`; hash passwords at runtime
