# Microsoft sign-in (Entra ID / OpenID Connect)

Employees sign in with their Microsoft 365 account; the password and its 45-day
expiry stay in Microsoft. Accounts are matched by e-mail to an existing employee
(Employee e-mail or work e-mail). Nobody is created automatically.

## Try it locally (no Microsoft tenant needed)
In `.env`:

    SSO_ENABLED=True
    SSO_DEV_MOCK=True

Restart, open /login/ and click "Sign in with Microsoft". A development stand-in
asks which employee e-mail to sign in as. It only exists while DEBUG=True.

## Go live with Microsoft 365
1. Entra admin centre > App registrations > New registration. Single tenant.
   Redirect URI (Web): `https://<your-domain>/sso/callback/`
2. Copy the Directory (tenant) ID and Application (client) ID.
3. Certificates & secrets > New client secret; copy the secret *value*.
4. API permissions: Microsoft Graph > openid, profile, email (delegated) - the defaults.
5. In `.env` (and remove SSO_DEV_MOCK):

       SSO_ENABLED=True
       ENTRA_TENANT_ID=<tenant id>
       ENTRA_CLIENT_ID=<client id>
       ENTRA_CLIENT_SECRET=<secret value>
       SSO_ALLOWED_DOMAINS=infisetu.com        # optional
       SSO_REDIRECT_URI=https://<your-domain>/sso/callback/   # optional, must match step 1

6. Each employee's Infisetu MIS e-mail must equal their Microsoft sign-in address.

## Notes
- Keep one local admin password as a break-glass login in case Microsoft is unreachable.
- Restrict who may reach the site with Entra Conditional Access (named IP locations)
  and/or the web server / firewall.
- Tokens are verified (RS256 signature, issuer, audience, expiry, nonce, tenant) and
  the flow uses state + PKCE.
