"""Deterministic brand extraction and WCAG contrast sanitation; no provider calls."""
from html.parser import HTMLParser
from io import BytesIO
import re
from urllib.parse import urljoin

from PIL import Image, UnidentifiedImageError

from bookgen.config.theme import ThemeConfig
from bookgen.schemas import DesignTokens


def _rgb(color: str) -> tuple[int, ...]:
    return tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))


def _luminance(color: str) -> float:
    values = [channel / 255 for channel in _rgb(color)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in values]
    return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast_ratio(foreground: str, background: str) -> float:
    light, dark = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def sanitize_contrast(foreground: str, background: str, minimum: float) -> str:
    if contrast_ratio(foreground, background) >= minimum:
        return foreground
    endpoint = max(('#000000', '#FFFFFF'), key=lambda color: contrast_ratio(color, background))
    if contrast_ratio(endpoint, background) < minimum:
        raise ValueError('Paper color cannot meet the configured contrast requirement')
    start, end = _rgb(foreground), _rgb(endpoint)
    # Walk the finite sRGB gamut toward the accessible endpoint, preserving hue.
    for step in range(1, 256):
        candidate = '#' + ''.join(f'{round(value + (target - value) * step / 255):02X}' for value, target in zip(start, end))
        if contrast_ratio(candidate, background) >= minimum:
            return candidate
    return endpoint  # pragma: no cover


def sanitize_tokens(tokens: DesignTokens, settings: ThemeConfig) -> DesignTokens:
    settings.require_complete()
    payload = tokens.model_dump()
    for name, value in payload.items():
        if name.startswith('color_') and not re.fullmatch(settings.color_pattern, value):
            raise ValueError('Colors must use six digit hexadecimal notation')
    # Every text role must remain readable on both paper and tinted surfaces.
    for name in ('color_ink_primary', 'color_ink_muted', 'color_brand_primary', 'color_brand_accent'):
        for background in (tokens.color_paper, tokens.color_surface_tint):
            payload[name] = sanitize_contrast(payload[name], background, settings.contrast_min_ratio)
        if contrast_ratio(payload[name], tokens.color_paper) < settings.contrast_min_ratio:
            raise ValueError('Paper and tint require incompatible text contrast')
    return DesignTokens.model_validate(payload)


class _BrandHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = ''
        self.styles: list[str] = []
        self.header_styles: list[str] = []
        self.logo = ''
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('name', '').lower() == 'theme-color':
            self.meta = values.get('content', '')
        if tag == 'style':
            self.in_style = True
        if tag == 'header' and values.get('style'):
            self.header_styles.append(values['style'])
        if tag == 'img' and 'logo' in ' '.join(values.get(name, '') for name in ('alt', 'class', 'id', 'src')).lower():
            self.logo = values.get('src', '')

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)


def extract_theme(url: str, *, fetcher, settings: ThemeConfig) -> DesignTokens:
    settings.require_complete()
    document = _BrandHTML()
    document.feed(fetcher.fetch(url).body.decode('utf-8', errors='replace'))
    payload = settings.preset_palettes[settings.default_preset].model_dump()
    payload.update(theme_id=url, palette_source='website_extracted')
    declarations = dict(re.findall(settings.css_color_pattern, '\n'.join(document.styles + document.header_styles)))
    primary = document.meta or next((declarations[name] for name in settings.css_primary_names if name in declarations), '')
    accent = next((declarations[name] for name in settings.css_accent_names if name in declarations), '')
    if not primary and document.logo:
        try:
            with Image.open(BytesIO(fetcher.fetch(urljoin(url, document.logo)).body)) as logo:
                logo.thumbnail((settings.logo_thumbnail_size, settings.logo_thumbnail_size))
                colors = logo.convert('RGBA').getdata()
                counts: dict[tuple, int] = {}
                for red, green, blue, alpha in colors:
                    if alpha:
                        color = (red, green, blue)
                        counts[color] = counts.get(color, 0) + 1
                if counts:
                    primary = '#' + ''.join(f'{channel:02X}' for channel in max(counts, key=counts.get))
        except (UnidentifiedImageError, OSError, ValueError):
            pass
    if not primary:
        raise ValueError('No brand colors found; choose a preset or manual palette')
    for name, color in (('color_brand_primary', primary), ('color_brand_accent', accent)):
        if color:
            payload[name] = '#' + ''.join(channel * 2 for channel in color[1:]) if len(color) == 4 and color.startswith('#') else color
    return sanitize_tokens(DesignTokens.model_validate(payload), settings)
