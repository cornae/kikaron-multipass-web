# Kikaron Multipass - the web vault

The web vault of **Multipass**, Kikaron's password manager, is a modified version,
made by Cornae (2026), of the [Bitwarden web vault](https://github.com/bitwarden/clients)
(GPL-3.0) as built for [Vaultwarden](https://github.com/dani-garcia/vaultwarden)
([bw_web_builds](https://github.com/dani-garcia/bw_web_builds), AGPL-3.0). The
server is Vaultwarden itself, unmodified.

Not made, endorsed or supported by Bitwarden Inc. "Bitwarden" is a trademark of
Bitwarden Inc.; Multipass does not use it as its name or logo.

## Licence

GPL-3.0 (see [LICENSE](LICENSE)), WITHOUT ANY WARRANTY. The copyright of the
original code stays with its authors; the changes here are © Cornae 2026 under the
same licence.

## What is changed, and how

The vault Vaultwarden ships is not edited by hand: `web/apply_branding.py` turns it
into the Multipass vault, deterministically, on every upstream release
(`web/update.sh`, `web/auto-update.sh`). Changed since 2026-10-05:

- the product name in the texts (`Bitwarden` / `Vaultwarden Web` -> `Multipass`),
  the icon and the wordmark (`brand/`); the attribution line is rewritten, not
  removed, and names both upstream projects, this modification and this source
- a Kikaron look (`web/kikaron-theme.css`), appended to the vault's stylesheet
- `web/multipass.js`: behaviour when the vault is framed by Kikaron
- `web/bridge.js`: `multipass-bridge.html`, through which Kikaron's own Multipass
  screens sign in and call the vault API (the keys never leave the browser)
- Dutch: "hoofdwachtwoord" -> "Multipass-wachtwoord"

```bash
python3 web/apply_branding.py <vault-from-the-image> <output-dir>
```

The Android app is [kikaron-multipass-android](https://github.com/cornae/kikaron-multipass-android).
