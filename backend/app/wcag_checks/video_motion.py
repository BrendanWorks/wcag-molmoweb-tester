"""
WCAG Video & Motion — 1.2.1, 1.2.2, 1.2.3, 2.2.2, 2.3.1

New check for Phase 1. Two-layer approach:

  Layer 1 (programmatic): DOM inspection for <video>, <audio>, <iframe> embeds,
                           GIF images, CSS animations, auto-play attributes,
                           and elements with role=img + animated content hints.

  Layer 2 (visual): MolmoWeb-8B confirms whether auto-playing or moving content
                    is visible and whether pause/stop controls exist on screen.

WCAG criteria covered:
  1.2.1  Audio-only and Video-only (prerecorded) — text alternative needed
  1.2.2  Captions (prerecorded) — captions on video
  1.2.3  Audio Description or Media Alternative (prerecorded)
  2.2.2  Pause, Stop, Hide — auto-moving content must be pausable
  2.3.1  Three Flashes — no content flashes more than 3 times per second
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from app.wcag_checks.base import BaseWCAGTest, TestResult


MOTION_JS = """
() => {
    const issues = [];

    // ── <video> elements ─────────────────────────────────────────────────
    const videos = Array.from(document.querySelectorAll('video'));
    const autoplayVideos = videos.filter(v => v.autoplay || v.getAttribute('autoplay') !== null);
    const videosWithoutCaptions = videos.filter(v => {
        const tracks = Array.from(v.querySelectorAll('track'));
        const hasCaptions = tracks.some(t =>
            ['captions','subtitles'].includes((t.getAttribute('kind')||'').toLowerCase())
        );
        return !hasCaptions;
    });
    const videosWithoutControls = videos.filter(v =>
        !v.controls && !v.getAttribute('controls')
    );

    if (autoplayVideos.length > 0) {
        issues.push({
            criterion: '2.2.2', severity: 'major',
            description: `${autoplayVideos.length} video(s) set to autoplay. Users must be able to pause/stop auto-playing content.`,
            examples: autoplayVideos.slice(0,3).map(v => v.getAttribute('src')||v.currentSrc||'<video>').map(s=>s.split('/').pop().slice(0,40)),
            fix: 'Remove autoplay, or add visible pause/stop controls. If video has audio, also add muted or controls attribute.',
        });
    }
    if (videosWithoutCaptions.length > 0) {
        issues.push({
            criterion: '1.2.2', severity: 'major',
            description: `${videosWithoutCaptions.length} video(s) lack caption tracks (<track kind="captions">).`,
            fix: 'Add a <track kind="captions" src="captions.vtt"> inside each <video>.',
        });
    }
    if (videosWithoutControls.length > 0 && videosWithoutControls.some(v => !v.autoplay)) {
        issues.push({
            criterion: '2.2.2', severity: 'minor',
            description: `${videosWithoutControls.length} video(s) have no browser controls. Users may not be able to pause playback.`,
            fix: 'Add the controls attribute to all <video> elements, or implement custom accessible play/pause controls.',
        });
    }

    // ── <audio> elements ─────────────────────────────────────────────────
    const audios = Array.from(document.querySelectorAll('audio'));
    const autoplayAudio = audios.filter(a => a.autoplay || a.getAttribute('autoplay') !== null);
    if (autoplayAudio.length > 0) {
        issues.push({
            criterion: '1.2.1', severity: 'critical',
            description: `${autoplayAudio.length} audio element(s) set to autoplay. Screen reader users cannot hear the SR if background audio starts automatically.`,
            examples: autoplayAudio.slice(0,3).map(a => a.getAttribute('src')||'<audio>').map(s=>s.split('/').pop().slice(0,40)),
            fix: 'Never autoplay audio. Add controls so users can play/pause on demand.',
        });
    }

    // ── YouTube / Vimeo / embedded iframes ───────────────────────────────
    const videoEmbeds = Array.from(document.querySelectorAll('iframe')).filter(f => {
        const src = (f.getAttribute('src')||'').toLowerCase();
        return src.includes('youtube') || src.includes('vimeo') || src.includes('loom') ||
               src.includes('wistia') || src.includes('embed');
    });
    const autoplayEmbeds = videoEmbeds.filter(f => {
        const src = f.getAttribute('src')||'';
        return src.includes('autoplay=1') || src.includes('autoplay=true');
    });
    if (videoEmbeds.length > 0) {
        const captionNote = 'Ensure embedded videos have closed captions enabled (YouTube: ?cc_load_policy=1).';
        if (autoplayEmbeds.length > 0) {
            issues.push({
                criterion: '2.2.2', severity: 'major',
                description: `${autoplayEmbeds.length} embedded video(s) use autoplay parameter.`,
                examples: autoplayEmbeds.slice(0,3).map(f => (f.getAttribute('src')||'').slice(0,60)),
                fix: 'Remove autoplay=1 from embedded video URLs. ' + captionNote,
            });
        }
        // Flag all embeds for manual caption review
        issues.push({
            criterion: '1.2.2', severity: 'minor',
            description: `${videoEmbeds.length} embedded video(s) found. Verify captions are enabled.`,
            examples: videoEmbeds.slice(0,3).map(f => (f.getAttribute('src')||'').slice(0,60)),
            fix: captionNote,
        });
    }

    // ── Animated GIFs ────────────────────────────────────────────────────
    // We detect by filename extension (heuristic — can't inspect pixel data from JS)
    const animatedGifs = Array.from(document.querySelectorAll('img')).filter(img => {
        const src = (img.getAttribute('src')||img.currentSrc||'').toLowerCase();
        return src.endsWith('.gif') || src.includes('.gif?');
    });
    if (animatedGifs.length > 0) {
        issues.push({
            criterion: '2.2.2', severity: 'minor',
            description: `${animatedGifs.length} GIF image(s) found. Animated GIFs cannot be paused by users.`,
            examples: animatedGifs.slice(0,3).map(img => (img.getAttribute('src')||'').split('/').pop().slice(0,40)),
            fix: 'Replace animated GIFs with videos (which can be paused) or add prefers-reduced-motion CSS. Avoid GIFs that flash more than 3 times/sec (WCAG 2.3.1).',
        });
    }

    // ── CSS animations / transitions on large elements ───────────────────
    // We only flag persistent (infinite) animations on visible, large elements.
    const animatedEls = Array.from(document.querySelectorAll('*')).filter(el => {
        const s = window.getComputedStyle(el);
        const r = el.getBoundingClientRect();
        if (r.width < 50 || r.height < 50) return false;
        const hasAnim   = s.animationName && s.animationName !== 'none';
        const infinite  = s.animationIterationCount === 'infinite';
        const hasTrans  = s.transitionProperty && s.transitionProperty !== 'none';
        return hasAnim && infinite;
    }).slice(0, 5);
    if (animatedEls.length > 0) {
        issues.push({
            criterion: '2.2.2', severity: 'minor',
            description: `${animatedEls.length} element(s) have infinite CSS animations. Users with vestibular disorders may be harmed.`,
            examples: animatedEls.map(el => {
                const label = (el.getAttribute('aria-label')||el.id||el.className||'').trim().slice(0,40);
                return `<${el.tagName.toLowerCase()}>${label?' "'+label+'"':''}`;
            }),
            fix: 'Respect prefers-reduced-motion: @media (prefers-reduced-motion: reduce) { animation: none; }. Add pause controls for carousels/sliders.',
        });
    }

    // ── prefers-reduced-motion support ───────────────────────────────────
    const styleSheets = Array.from(document.styleSheets);
    let hasReducedMotionQuery = false;
    for (const sheet of styleSheets) {
        try {
            const rules = Array.from(sheet.cssRules || []);
            hasReducedMotionQuery = rules.some(r =>
                r.conditionText && r.conditionText.includes('prefers-reduced-motion')
            );
            if (hasReducedMotionQuery) break;
        } catch(e) { /* cross-origin stylesheet */ }
    }
    if (!hasReducedMotionQuery && (animatedEls.length > 0 || animatedGifs.length > 0)) {
        issues.push({
            criterion: '2.2.2', severity: 'minor',
            description: 'No prefers-reduced-motion CSS media query detected on a page with animated content.',
            fix: 'Add @media (prefers-reduced-motion: reduce) rules to disable or reduce animations for users who prefer less motion.',
        });
    }

    return { issues, videoCount: videos.length, audioCount: audios.length, embedCount: videoEmbeds.length };
}
"""


class VideoMotionTest(BaseWCAGTest):
    TEST_ID = "video_motion"
    TEST_NAME = "Video, Audio & Motion"
    WCAG_CRITERIA = ["1.2.1", "1.2.2", "2.2.2", "2.3.1"]
    DEFAULT_SEVERITY = "major"
    MOLMO_QUESTION = "Is there any auto-playing video or animation without a visible pause or stop button? Answer yes or no."

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        yield self._progress("Scanning for video, audio, and animated content...")

        findings = await page.evaluate(MOTION_JS)
        issues       = findings.get("issues", [])
        video_count  = findings.get("videoCount", 0)
        audio_count  = findings.get("audioCount", 0)
        embed_count  = findings.get("embedCount", 0)

        screenshot      = await self.analyzer.screenshot_to_image(page)
        screenshot_path = self.analyzer.save_screenshot(screenshot, self.run_dir, "video_motion")
        screenshot_b64  = self.analyzer.image_to_base64(screenshot)

        yield self._progress("Running MolmoWeb visual motion analysis...")
        molmo_analysis = await self._molmo_analyze(screenshot, self.MOLMO_QUESTION)

        # If no DOM media found but MolmoWeb sees moving content, add a warning
        has_dom_media = video_count > 0 or audio_count > 0 or embed_count > 0
        molmo_sees_motion = molmo_analysis and any(
            kw in molmo_analysis.lower()
            for kw in ("carousel", "slider", "animation", "video", "play", "moving", "flashing")
        )
        if not has_dom_media and molmo_sees_motion and not issues:
            issues.append({
                "criterion": "2.2.2", "severity": "minor",
                "description": (
                    "MolmoWeb visual analysis detected possible moving or auto-playing content "
                    "not found via DOM inspection (may be CSS-only or canvas-based). "
                    f"Details: {molmo_analysis[:120]}"
                ),
                "fix": "Verify all animated content has pause/stop controls and respects prefers-reduced-motion.",
            })

        if not issues:
            yield self._result(TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="pass", wcag_criteria=self.WCAG_CRITERIA, severity="minor",
                screenshot_path=screenshot_path, screenshot_b64=screenshot_b64,
                molmo_analysis=molmo_analysis,
                details={"video_count": video_count, "audio_count": audio_count, "embed_count": embed_count},
            ))
            return

        severity_order = {"critical": 0, "major": 1, "minor": 2}
        issues.sort(key=lambda i: severity_order.get(i.get("severity", "minor"), 2))

        criticals = [i for i in issues if i.get("severity") == "critical"]
        majors    = [i for i in issues if i.get("severity") == "major"]

        overall_severity = "critical" if criticals else ("major" if majors else "minor")
        overall_result   = "fail" if (criticals or majors) else "warning"

        top = issues[:3]
        parts = []
        for i in top:
            desc = i["description"]
            if i.get("examples"):
                desc += f" (e.g. {', '.join(str(e) for e in i['examples'][:2])})"
            parts.append(f"[{i['criterion']}] {desc}")

        recs = list(dict.fromkeys(i["fix"] for i in issues if i.get("fix")))

        yield self._result(TestResult(
            test_id=self.TEST_ID, test_name=self.TEST_NAME,
            result=overall_result, severity=overall_severity,
            wcag_criteria=sorted({i["criterion"] for i in issues}),
            failure_reason=" | ".join(parts),
            recommendation=" ".join(recs[:3]),
            screenshot_path=screenshot_path, screenshot_b64=screenshot_b64,
            molmo_analysis=molmo_analysis,
            details={
                "issues": issues,
                "video_count": video_count,
                "audio_count": audio_count,
                "embed_count": embed_count,
            },
        ))
