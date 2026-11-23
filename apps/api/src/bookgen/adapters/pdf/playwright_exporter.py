"""Bounded Chromium contexts, physical drift checks, and verified atomic PDF output."""
import asyncio
from io import BytesIO
from urllib.parse import quote

from PIL import Image
from playwright.async_api import async_playwright
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import Fit


class ExportDriftError(ValueError):
    pass


def image_ssim(first, second):
    """Windowed luminance SSIM at a common raster scale (8x8 sample windows)."""
    if first.size != second.size:
        return 0.0
    a = first.convert('L').resize((256, 256))
    b = second.convert('L').resize((256, 256))
    scores = []
    for y in range(0, 256, 8):
        for x in range(0, 256, 8):
            left = list(a.crop((x, y, x + 8, y + 8)).getdata())
            right = list(b.crop((x, y, x + 8, y + 8)).getdata())
            ma, mb = sum(left) / 64, sum(right) / 64
            va = sum((v - ma) ** 2 for v in left) / 64
            vb = sum((v - mb) ** 2 for v in right) / 64
            covariance = sum((u - ma) * (v - mb) for u, v in zip(left, right)) / 64
            scores.append(((2 * ma * mb + 6.5025) * (2 * covariance + 58.5225)) /
                ((ma * ma + mb * mb + 6.5025) * (va + vb + 58.5225)))
    return sum(scores) / len(scores)


class PlaywrightChunkExporter:
    def __init__(self, settings):
        self.settings = settings.require_complete()
        self.chunk_sizes = []
        self.ssim_scores = []

    async def _check_bounds(self, page, start, compact):
        return await page.evaluate('''() => Array.from(document.querySelectorAll('.print-page')).flatMap(wrapper => {
            const canvas = wrapper.querySelector('.page-canvas');
            const content = canvas.querySelector('.page-content');
            const box = content.getBoundingClientRect();
            const bad = canvas.dataset.overflow === 'true' || content.scrollWidth > content.clientWidth + 1 || content.scrollHeight > content.clientHeight + 1 ||
                Array.from(content.children).some(child => { const r = child.getBoundingClientRect(); return r.bottom > box.bottom + 1 || r.right > box.right + 1; });
            const toc = wrapper.querySelector('.print-toc');
            return bad || (toc && toc.getBoundingClientRect().bottom > box.bottom + 1) ? [Number(wrapper.dataset.pageNumber)] : [];
        })''')

    async def _chunk(self, browser, manifest, start, end, compact):
        config = self.settings
        async with await browser.new_context(viewport={'width': 1100, 'height': 1200}, device_scale_factor=1) as context:
            page = await context.new_page()
            # Pin the exact gated snapshot; a later compliance edit cannot change a chunk.
            await page.route('**/api/v1/sessions/*/print-data', lambda route: route.fulfill(
                status=200, content_type='application/json', body=manifest.model_dump_json()))
            url = f'{config.print_origin}/print/{quote(manifest.session_id, safe="")}?start={start}&end={end}&compact={int(compact)}'
            await page.goto(url, wait_until='networkidle', timeout=config.ready_timeout_ms)
            await page.wait_for_function('document.documentElement.dataset.printReady === "true"', timeout=config.ready_timeout_ms)
            bad = await self._check_bounds(page, start, compact)
            if bad:
                raise ExportDriftError(f'page {bad[0]} overflows before PDF')
            links = await page.locator('.print-toc a').evaluate_all('''elements => elements.map(a => {
                const rect = a.getBoundingClientRect(), wrapper = a.closest('.print-page'), box = wrapper.getBoundingClientRect();
                return {from: Number(wrapper.dataset.pageNumber) - 1, to: Number(a.dataset.destination) - 1,
                    rect: [rect.left - box.left, rect.top - box.top, rect.right - box.left, rect.bottom - box.top], height: box.height};
            })''')
            await page.emulate_media(media='print')
            previews = [await element.screenshot(animations='disabled') for element in await page.locator('.print-page').all()]
            data = await page.pdf(prefer_css_page_size=True, print_background=True, display_header_footer=False)
            reader = PdfReader(BytesIO(data))
            if len(reader.pages) != end - start:
                raise ExportDriftError(f'page {start + 1} physical count {len(reader.pages)} differs from {end - start}')
            # PDF rasterization is local; it never introduces a network or provider dependency.
            import pymupdf
            with pymupdf.open(stream=data, filetype='pdf') as raster:
                scores = []
                for offset, logical in enumerate(manifest.pages[start:end]):
                    physical = reader.pages[offset]
                    width, height = (210 / 25.4 * 72, 297 / 25.4 * 72) if manifest.context.page_size == 'A4' else (612, 792)
                    if abs(float(physical.mediabox.width) - width) > 1 or abs(float(physical.mediabox.height) - height) > 1:
                        raise ExportDriftError(f'page {logical.page_number} has incorrect physical dimensions')
                    text = ' '.join(physical.extract_text().split())
                    if any(' '.join(expected.split()) not in text for expected in logical.expected_text):
                        raise ExportDriftError(f'page {logical.page_number} searchable text differs')
                    pix = raster[offset].get_pixmap(matrix=pymupdf.Matrix(96 / 72, 96 / 72), alpha=False)
                    rendered = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
                    with Image.open(BytesIO(previews[offset])) as screenshot:
                        # Chromium rounds fractional CSS mm dimensions to raster pixel bounds.
                        if abs(rendered.width - screenshot.width) > 1 or abs(rendered.height - screenshot.height) > 1:
                            raise ExportDriftError(f'page {logical.page_number} raster dimensions differ')
                        score = image_ssim(screenshot, rendered.resize(screenshot.size))
                    if score < config.min_ssim:
                        raise ExportDriftError(f'page {logical.page_number} visual SSIM {score:.4f} below {config.min_ssim}')
                    scores.append(score)
            return data, links, scores

    async def export(self, manifest):
        config = self.settings
        chunks = [(start, min(start + config.chunk_pages, len(manifest.pages))) for start in range(0, len(manifest.pages), config.chunk_pages)]
        self.chunk_sizes = [end - start for start, end in chunks]
        semaphore = asyncio.Semaphore(config.max_contexts)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                async def render(index, start, end):
                    async with semaphore:
                        for attempt in range(config.max_drift_retries + 1):
                            try:
                                return await self._chunk(browser, manifest, start, end, bool(attempt))
                            except ExportDriftError as exc:
                                if attempt == config.max_drift_retries:
                                    raise ExportDriftError(f'chunk {index + 1}: {exc}') from exc
                tasks = [asyncio.create_task(render(index, start, end)) for index, (start, end) in enumerate(chunks)]
                try:
                    results = await asyncio.gather(*tasks)
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                await browser.close()
        writer = PdfWriter()
        all_links = []
        self.ssim_scores = []
        for data, links, scores in results:
            writer.append(PdfReader(BytesIO(data)), import_outline=False, excluded_fields=['/Annots'])
            all_links.extend(links)
            self.ssim_scores.extend(scores)
        writer.add_metadata({'/Title': manifest.context.title, '/Creator': 'Visual Book Generator'})
        for entry in manifest.toc:
            writer.add_outline_item(entry.title, entry.page_number - 1)
        for link in all_links:
            x0, y0, x1, y1 = link['rect']
            scale = float(writer.pages[link['from']].mediabox.height) / link['height']
            annotation = writer.add_annotation(link['from'], Link(rect=(x0 * scale, (link['height'] - y1) * scale, x1 * scale, (link['height'] - y0) * scale),
                target_page_index=link['to'], fit=Fit.fit()))
            annotation['/Dest'][0] = writer.pages[link['to']].indirect_reference
        output = BytesIO()
        writer.write(output)
        result = output.getvalue()
        if len(PdfReader(BytesIO(result)).pages) != len(manifest.pages):
            raise ExportDriftError('Merged physical page count differs')
        return result
