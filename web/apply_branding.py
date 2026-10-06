#!/usr/bin/env python3
"""Turn a Vaultwarden web vault into the Multipass web vault.

    python3 multipass/web/apply_branding.py SRC_DIR DST_DIR [--icon multipass/brand/icon.svg]

SRC_DIR is the vault Vaultwarden ships (`docker cp <container>:/web-vault`, or a
bw_web_builds release unpacked). DST_DIR is written fresh; point Vaultwarden's
WEB_VAULT_FOLDER at it. Deterministic and idempotent: it only ever reads SRC_DIR,
so it re-runs unchanged on every upstream release (multipass/web/update.sh).

What it changes, and why it is a script rather than a fork of bitwarden/clients:
the visible name lives in three places only - the locale catalogues (a JSON
value per language), a handful of exact strings in the compiled JS, and the
icon files. Everything else (import-format names such as "Bitwarden (json)",
internal identifiers) is left alone on purpose: those name a FORMAT, not us.

Licensing: the vault is Bitwarden's GPL-3.0 web client as patched by Vaultwarden
(AGPL-3.0). The attribution paragraph in the footer is REPLACED, not removed;
it still names both projects and says we are not affiliated with Bitwarden Inc.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PRODUCT = 'Multipass'

# Exact strings in the compiled JS. Each must match at least once or the script
# fails: an upstream release that changes one is a signal to look, not to ship a
# half-branded vault.
JS_EXACT = [
    ('"Vaultwarden Web"', '"Multipass"'),
    ('alt","Vaultwarden"', 'alt","Multipass"'),
    ('issuer=Vaultwarden', 'issuer=Multipass'),
    ('otpauth://totp/Vaultwarden:', 'otpauth://totp/Multipass:'),
    (' A modified version of the Bitwarden® Web Vault for Vaultwarden '
     '(an unofficial rewrite of the Bitwarden® server).',
     # the wording Bitwarden's trademark guidelines give for a modified version
     ' Kikaron Multipass was developed using Bitwarden® open source software: a '
     'version of the Bitwarden® web vault (GPL-3.0) for Vaultwarden (AGPL-3.0), '
     'modified by Cornae (2026), without any warranty. Source: '
     'https://github.com/cornae/kikaron-multipass-web'),
    (' Vaultwarden is not associated with the Bitwarden® project nor '
     'Bitwarden Inc. ',
     ' Not affiliated with or endorsed by Bitwarden, Inc. '),
]
# Optional ones: matched if present, silently skipped otherwise.
JS_OPTIONAL = []

TEXT_FILES = ['index.html', 'manifest.json', 'browserconfig.xml',
              'cca56971e438d22818d6.json']


def sub_words(text):
    """'Bitwarden' -> product name, but never inside a URL or an e-mail."""
    return re.sub(r'(?<![/.@\w])Bitwarden(?!\.com|\.net|\.eu|\w)', PRODUCT, text)


# Words the vault says to a NEW person right after Kikaron has vouched for them,
# on the screen where they choose a master password. Bitwarden's text there is about
# joining an organisation and "creating an account"; here nothing of the sort
# happens, so it says what is true. English and Dutch (formal 'u', as everywhere
# in Kikaron); every other language gets the English rather than a translation of
# "join organisation". $CURRENT$ and $MAXIMUM$ are the client's own placeholders.
COPY = {
    'joinOrganization': {
        'en': 'Choose your Multipass password',
        'nl': 'Kies uw Multipass-wachtwoord'},
    'finishJoiningThisOrganizationBySettingAMasterPassword': {
        'en': 'This password protects everything in Multipass. Only you know it: '
              'Kikaron cannot read your vault and cannot reset the password, so keep it safe.',
        'nl': 'Dit wachtwoord beschermt alles in Multipass. Alleen u kent het: '
              'Kikaron kan uw kluis niet lezen en het wachtwoord niet herstellen. '
              'Bewaar het dus goed.'},
    'createAccount': {
        'en': 'Create Multipass vault',
        'nl': 'Multipass-kluis aanmaken'},
    'masterPassHintText': {
        'en': 'A reminder for yourself - never the password itself. '
              '$CURRENT$/$MAXIMUM$ characters max.',
        'nl': 'Een geheugensteuntje voor uzelf - nooit het wachtwoord zelf. '
              '$CURRENT$/$MAXIMUM$ tekens max.'},
}


# Dutch: the master password is the Multipass password, in every string the vault
# shows ("Hoofdwachtwoord", "Nieuw hoofdwachtwoord bevestigen", "...hint").
WORDS = {
    'nl': [(re.compile(r'[Hh]oofdwachtwoord'), 'Multipass-wachtwoord')],
}


# Dutch only, one key each: words for the set-password screen that are not a
# straight rename. confirmMasterPassword is that screen's label (the change-password
# screen has its own key, confirmNewMasterPass, and keeps its "Nieuw").
NL_COPY = {
    'confirmMasterPassword': 'Multipass-wachtwoord bevestigen',
}


def brand_locales(dst):
    changed = 0
    for path in (dst / 'locales').glob('*/messages.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        lang = path.parent.name.split('-')[0]
        for key, texts in COPY.items():
            if key in data:
                data[key]['message'] = texts.get(lang) or texts['en']
                changed += 1
        for key, entry in data.items():
            if key in COPY:
                continue
            msg = entry.get('message')
            if isinstance(msg, str):
                new = sub_words(msg)
                for pattern, repl in WORDS.get(lang, []):
                    new = pattern.sub(repl, new)
                if new != msg:
                    entry['message'] = new
                    changed += 1
        if lang == 'nl':
            for key, text in NL_COPY.items():
                if key in data:
                    data[key]['message'] = text
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    return changed


def brand_js(dst):
    seen = {src: 0 for src, _ in JS_EXACT}
    for path in list(dst.glob('*.js')) + list((dst / 'app').glob('*.js')):
        text = path.read_text(encoding='utf-8')
        new = text
        for src, repl in JS_EXACT + JS_OPTIONAL:
            if src in new:
                if src in seen:
                    seen[src] += new.count(src)
                new = new.replace(src, repl)
        if new != text:
            path.write_text(new, encoding='utf-8')
    missing = [s for s, n in seen.items() if not n]
    if missing:
        sys.exit('upstream changed - these strings no longer match:\n  '
                 + '\n  '.join(missing))
    bust_caches(dst)


def bust_caches(dst):
    """Browsers keep what they were first given under the same name for as long as
    they like, and the branded vault keeps upstream's names. Two things must not be
    served stale: the language files (fetched with a fixed ?cache= value baked into
    the app) and the app script itself (named by upstream's content hash, not ours).
    Both get a name that follows OUR content."""
    import hashlib
    h = hashlib.sha1()
    for path in sorted((dst / 'locales').glob('*/messages.json')):
        h.update(path.read_bytes())
    stamp = h.hexdigest()[:8]
    for main in list((dst / 'app').glob('main.*.js')):
        text = main.read_text(encoding='utf-8')
        text, n = re.subn(r'messages\.json\?cache=[0-9a-z]+', 'messages.json?cache=' + stamp, text)
        digest = hashlib.sha1(text.encode('utf-8')).hexdigest()[:20]
        renamed = main.with_name('main.%s.js' % digest)
        renamed.write_text(text, encoding='utf-8')
        main.unlink()
        for old_map in (dst / 'app').glob(main.name + '.map'):
            old_map.unlink()
        for ref in dst.rglob('*.html'):
            body = ref.read_text(encoding='utf-8')
            if main.name in body:
                ref.write_text(body.replace(main.name, renamed.name), encoding='utf-8')


def brand_script(dst):
    import hashlib
    source = (Path(__file__).resolve().parent / 'multipass.js').read_bytes()
    # named by content: a browser holding an earlier copy under a fixed name keeps it
    name = 'multipass.%s.js' % hashlib.sha1(source).hexdigest()[:12]
    (dst / name).write_bytes(source)
    index = dst / 'index.html'
    html = index.read_text(encoding='utf-8')
    tag = '<script src="%s"></script>' % name
    if tag not in html:
        if '</head>' not in html:
            sys.exit('index.html has no </head> to put the Multipass script in')
        html = html.replace('</head>', tag + '</head>', 1)
        index.write_text(html, encoding='utf-8')


def brand_bridge(dst):
    """The bridge Kikaron's own Multipass screens talk to (bridge.js): a page of its
    own on the vault host, and the same script on sso-connector.html, where the
    sign-in it starts comes back to. Named by content, like the rest."""
    import hashlib
    source = (Path(__file__).resolve().parent / 'bridge.js').read_text(encoding='utf-8')
    version = json.loads((dst / 'version.json').read_text(encoding='utf-8'))['version']
    source = source.replace('__MULTIPASS_CLIENT_VERSION__', version).encode('utf-8')
    name = 'multipass-bridge.%s.js' % hashlib.sha1(source).hexdigest()[:12]
    (dst / name).write_bytes(source)
    tag = '<script src="%s"></script>' % name
    (dst / 'multipass-bridge.html').write_text(
        '<!doctype html><html><head><meta charset="utf-8"><title>Multipass</title>'
        + tag + '</head><body></body></html>', encoding='utf-8')
    connector = dst / 'sso-connector.html'
    if not connector.exists():
        sys.exit('no sso-connector.html to put the bridge in')
    html = connector.read_text(encoding='utf-8')
    if tag not in html:
        html = html.replace('</head>', tag + '</head>', 1)
        connector.write_text(html, encoding='utf-8')


def brand_text(dst):
    for name in TEXT_FILES:
        path = dst / name
        if path.exists():
            text = path.read_text(encoding='utf-8')
            new = text.replace('Vaultwarden Web', PRODUCT).replace(
                'alt="Vaultwarden"', 'alt="%s"' % PRODUCT)
            new = sub_words(new)
            if new != text:
                path.write_text(new, encoding='utf-8')


THEME_CSS = (Path(__file__).resolve().parent / 'kikaron-theme.css').read_text(encoding='utf-8')

CSS_OVERRIDE = '''
/* MULTIPASS: the landing pages draw the Vaultwarden wordmark as an INLINE svg
   (paths classed tw-fill-marketing-logo) compiled into the JS. Hide those paths
   and lay our wordmark behind the same svg box. */
svg:has(path.tw-fill-marketing-logo) {
  background: url(images/logo.svg) no-repeat left center / contain;
}
.theme_dark svg:has(path.tw-fill-marketing-logo) {
  background-image: url(images/logo-white.svg);
}
svg path.tw-fill-marketing-logo { display: none; }
'''


def brand_css(dst):
    sheets = list(dst.glob('styles.*.css'))
    if not sheets:
        sys.exit('no stylesheet found')
    import hashlib
    for sheet in sheets:
        text = sheet.read_text(encoding='utf-8') + CSS_OVERRIDE + '\n' + THEME_CSS
        # A new file name for new content: browsers hold stylesheets under their
        # old hashed name for as long as they like, and ours is not upstream's.
        digest = hashlib.sha1(text.encode('utf-8')).hexdigest()[:20]
        renamed = sheet.with_name('styles.%s.css' % digest)
        renamed.write_text(text, encoding='utf-8')
        sheet.unlink()
        for old_map in dst.glob(sheet.name + '.map'):
            old_map.unlink()
        for ref in list(dst.rglob('*.html')) + list(dst.glob('*.js')) + list((dst / 'app').glob('*.js')):
            body = ref.read_text(encoding='utf-8')
            if sheet.name in body:
                ref.write_text(body.replace(sheet.name, renamed.name), encoding='utf-8')


def render(svg, out, size, background=None):
    cmd = ['convert', '-background', background or 'none', '-density', '600',
           str(svg), '-resize', size, str(out)]
    subprocess.run(cmd, check=True)


def wordmark_svg(path, icon_svg, fill):
    inner = re.sub(r'</?svg[^>]*>', '', icon_svg.read_text(encoding='utf-8'))
    path.write_text(
        '<svg version="1.1" viewBox="0 0 290 60" xmlns="http://www.w3.org/2000/svg">'
        '<title>%s</title><g transform="translate(4 4) scale(0.4333)">%s</g>'
        '<text x="68" y="42" font-family="Inter, Helvetica Neue, Arial, sans-serif" '
        'font-size="34" font-weight="600" fill="%s">%s</text></svg>'
        % (PRODUCT, inner, fill, PRODUCT), encoding='utf-8')


def brand_images(dst, icon):
    img = dst / 'images'
    icon_svg = Path(icon)
    for name, px in [('android-chrome-192x192.png', 192),
                     ('android-chrome-512x512.png', 512),
                     ('apple-touch-icon.png', 180),
                     ('favicon-16x16.png', 16), ('favicon-32x32.png', 32),
                     ('mstile-150x150.png', 150), ('icon-dark.png', 32),
                     ('icon-white.png', 32)]:
        for target in (img / name, img / 'icons' / name):
            if target.exists():
                render(icon_svg, target, '%dx%d' % (px, px))
    shutil.copyfile(icon_svg, img / 'icon-white.svg')
    if (img / 'icons' / 'safari-pinned-tab.svg').exists():
        shutil.copyfile(icon_svg, img / 'icons' / 'safari-pinned-tab.svg')
    # Wordmarks: the dark-text logo for light themes, the white one for dark.
    wordmark_svg(img / 'logo.svg', icon_svg, '#1f2433')
    wordmark_svg(img / 'logo-white.svg', icon_svg, '#ffffff')
    for svg, png in [('logo.svg', 'logo-dark@2x.png'),
                     ('logo-white.svg', 'logo-white@2x.png')]:
        if (img / png).exists():
            render(img / svg, img / png, '568x118')
    if (dst / 'favicon.ico').exists():
        subprocess.run(['convert', str(img / 'favicon-32x32.png'),
                        str(img / 'favicon-16x16.png'), str(dst / 'favicon.ico')],
                       check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--icon', default=str(Path(__file__).resolve().parents[1]
                                          / 'brand' / 'icon.svg'))
    args = ap.parse_args()
    src, dst = Path(args.src), Path(args.dst)
    if not (src / 'index.html').exists():
        sys.exit('%s does not look like a web vault' % src)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    n = brand_locales(dst)
    brand_js(dst)
    brand_text(dst)
    brand_css(dst)
    brand_script(dst)
    brand_bridge(dst)
    brand_images(dst, args.icon)
    # Guard: nothing user-visible may still say Vaultwarden Web or the old logo.
    left = [p for p in dst.glob('*.html') if 'Vaultwarden Web' in p.read_text(encoding='utf-8')]
    if left:
        sys.exit('unbranded: %s' % left)
    print('branded %d locale strings; vault ready in %s' % (n, dst))


if __name__ == '__main__':
    main()
