# z2u-online

Keeps the z2u seller account online 24/7 using GitHub Actions (free on public repos).
Login uses your browser cookies stored in the secret `Z2U_COOKIES`, so secrets never appear in code or logs.

1. In Chrome, log in to z2u.com, install the free "Cookie-Editor" extension, open it on z2u.com -> Export -> JSON.
2. Repo Settings -> Secrets and variables -> Actions -> New secret: `Z2U_COOKIES` = the copied JSON.
3. Actions -> z2u online -> Run workflow. It self-chains every ~6h.
4. Red X / "LOGGED OUT" email = export fresh cookies and update the secret.
