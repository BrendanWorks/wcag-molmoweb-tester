"""
WCAG Page Structure & Semantics — 1.1.1, 1.3.1, 1.4.1, 2.2.2, 2.4.2,
                                   2.4.4, 2.5.8, 3.1.1, 4.1.1, 4.1.2

Layer 1 (programmatic): single JS evaluation — alt text, headings, landmarks,
                         duplicate IDs, vague links, table headers, ARIA misuse.
Layer 2 (visual): MolmoWeb-8B describes heading hierarchy and landmark regions
                  visible in the screenshot, surfacing CSS-only layout issues.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from app.wcag_checks.base import BaseWCAGTest, TestResult


# JS is unchanged from PointCheck v1 — reproduced in full for self-containment.
STRUCTURE_JS = """
() => {
    const issues = [];

    const lang = document.documentElement.getAttribute('lang') || '';
    if (!lang.trim()) {
        issues.push({criterion:'3.1.1',severity:'serious',
            description:'Missing lang attribute on <html>. Screen readers cannot determine page language.',
            fix:'Add lang="en" (or appropriate code) to the <html> tag.'});
    }

    const title = (document.title||'').trim();
    if (!title) {
        issues.push({criterion:'2.4.2',severity:'serious',
            description:'Page has no <title> element.',
            fix:'Add a descriptive <title> to the <head>.'});
    } else if (title.length<5 || /^(untitled|page|home|index)$/i.test(title)) {
        issues.push({criterion:'2.4.2',severity:'moderate',
            description:`Page title "${title}" is not descriptive.`,
            fix:'Use a title that describes the page content.'});
    }

    const images = Array.from(document.querySelectorAll('img'));
    const missingAlt = images.filter(img => !img.hasAttribute('alt'));
    const emptyAltOnMeaningful = images.filter(img => {
        if(!img.hasAttribute('alt')||img.getAttribute('alt')!=='') return false;
        const r=img.getBoundingClientRect();
        const role=img.getAttribute('role')||'';
        const isDecorative=role==='presentation'||role==='none'||
                           img.getAttribute('aria-hidden')==='true'||r.width<10||r.height<10;
        const isLinked=!!img.closest('a');
        const isLarge=r.width>100&&r.height>100;
        return !isDecorative&&(isLinked||isLarge);
    });
    const filenameAlt = images.filter(img => {
        const alt=img.getAttribute('alt')||'';
        return /\\.(png|jpg|jpeg|gif|svg|webp)$/i.test(alt)||/^img_?\\d+/i.test(alt);
    });
    if(missingAlt.length>0){
        issues.push({criterion:'1.1.1',severity:'critical',
            description:`${missingAlt.length} image(s) missing alt attribute entirely.`,
            examples:missingAlt.slice(0,3).map(img=>(img.getAttribute('src')||'').split('/').pop().slice(0,40)),
            fix:'Add alt="" for decorative images, or descriptive alt text for meaningful images.'});
    }
    if(emptyAltOnMeaningful.length>0){
        issues.push({criterion:'1.1.1',severity:'serious',
            description:`${emptyAltOnMeaningful.length} large/linked image(s) have empty alt text but appear meaningful.`,
            examples:emptyAltOnMeaningful.slice(0,3).map(img=>(img.getAttribute('src')||'').split('/').pop().slice(0,40)),
            fix:'Provide descriptive alt text for images that convey information.'});
    }
    if(filenameAlt.length>0){
        issues.push({criterion:'1.1.1',severity:'moderate',
            description:`${filenameAlt.length} image(s) have filename-style alt text.`,
            examples:filenameAlt.slice(0,2).map(img=>img.getAttribute('alt')),
            fix:'Replace filename alt text with a description of what the image shows.'});
    }

    const headings=Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
        .filter(h=>{const r=h.getBoundingClientRect();return r.width>0||r.height>0;});
    const h1s=headings.filter(h=>h.tagName==='H1');
    if(h1s.length===0&&document.body){
        issues.push({criterion:'1.3.1',severity:'serious',
            description:'No <h1> found. Every page should have a single main heading.',
            fix:'Add one <h1> that describes the main topic of the page.'});
    } else if(h1s.length>1){
        issues.push({criterion:'1.3.1',severity:'moderate',
            description:`${h1s.length} <h1> elements found. Pages should have exactly one.`,
            examples:h1s.slice(0,3).map(h=>(h.innerText||'').trim().slice(0,50)),
            fix:'Use one <h1> per page.'});
    }
    const skips=[]; let prevLevel=0;
    for(const h of headings){
        const level=parseInt(h.tagName[1]);
        if(prevLevel>0&&level>prevLevel+1)
            skips.push(`<h${prevLevel}> → <h${level}> "${(h.innerText||'').trim().slice(0,40)}"`);
        prevLevel=level;
    }
    if(skips.length>0){
        issues.push({criterion:'1.3.1',severity:'moderate',
            description:`Heading levels skipped ${skips.length} time(s).`,
            examples:skips.slice(0,3),
            fix:'Do not skip heading levels. Use h1→h2→h3 in order.'});
    }

    const mainLandmarks=Array.from(document.querySelectorAll('main,[role="main"]'))
        .filter(el=>{const r=el.getBoundingClientRect();return r.width>0||r.height>0;});
    if(mainLandmarks.length===0){
        issues.push({criterion:'1.3.1',severity:'serious',
            description:'No <main> landmark found.',
            fix:'Wrap the primary page content in a <main> element.'});
    } else if(mainLandmarks.length>1){
        issues.push({criterion:'1.3.1',severity:'serious',
            description:`${mainLandmarks.length} <main> landmarks found. A page should have exactly one.`,
            fix:'Consolidate page content into a single <main> element.'});
    }
    const navLandmarks=Array.from(document.querySelectorAll('nav,[role="navigation"]'));
    const totalLinks=document.querySelectorAll('a[href]').length;
    if(navLandmarks.length===0&&totalLinks>=5){
        issues.push({criterion:'1.3.1',severity:'minor',
            description:`No <nav> landmark found, but the page has ${totalLinks} links.`,
            fix:'Wrap groups of navigation links in <nav> elements.'});
    }

    const idCounts={};
    Array.from(document.querySelectorAll('[id]')).forEach(el=>{
        const id=el.id.trim();
        if(id)idCounts[id]=(idCounts[id]||0)+1;
    });
    const dupIds=Object.entries(idCounts).filter(([,c])=>c>1).map(([id])=>id);
    if(dupIds.length>0){
        issues.push({criterion:'4.1.1',severity:'serious',
            description:`${dupIds.length} duplicate ID value(s) found. Breaks ARIA associations.`,
            examples:dupIds.slice(0,5),
            fix:'Every id attribute must be unique within the page.'});
    }

    const blinkEls=Array.from(document.querySelectorAll('blink'));
    const marqueeEls=Array.from(document.querySelectorAll('marquee'));
    if(blinkEls.length>0||marqueeEls.length>0){
        const parts=[];
        if(blinkEls.length>0)parts.push(`${blinkEls.length} <blink> element(s)`);
        if(marqueeEls.length>0)parts.push(`${marqueeEls.length} <marquee> element(s)`);
        issues.push({criterion:'2.2.2',severity:'serious',
            description:`${parts.join(' and ')} found — deprecated moving content users cannot pause.`,
            examples:[...blinkEls.slice(0,2).map(el=>`<blink> "${(el.innerText||'').trim().slice(0,40)}"`),...marqueeEls.slice(0,2).map(el=>`<marquee> "${(el.innerText||'').trim().slice(0,40)}"`)].slice(0,3),
            fix:'Remove <blink> and <marquee>. Use CSS with prefers-reduced-motion if animation is needed.'});
    }

    const VAGUE=/^(click here|here|read more|more|learn more|details|link|this|continue|go|view|see more|info|information|download|click|tap)$/i;
    const vagueLinks=Array.from(document.querySelectorAll('a[href]')).filter(a=>{
        const text=(a.innerText||a.getAttribute('aria-label')||'').trim();
        const title=a.getAttribute('title')||'';
        const ariaLabel=a.getAttribute('aria-label')||'';
        if(ariaLabel.trim().length>10||title.trim().length>10)return false;
        return VAGUE.test(text)&&text.length<15;
    });
    if(vagueLinks.length>0){
        issues.push({criterion:'2.4.4',severity:'serious',
            description:`${vagueLinks.length} link(s) have vague text that doesn't describe the destination.`,
            examples:[...new Set(vagueLinks.map(a=>(a.innerText||'').trim()))].slice(0,5),
            fix:'Use descriptive link text, or add aria-label="Read more about [topic]".'});
    }

    const MIN_TARGET_PX=24;
    const smallTargets=Array.from(document.querySelectorAll(
        'a[href],button,input:not([type="hidden"]),select,textarea,[role="button"],[role="link"]'
    )).filter(el=>{
        const tab=el.getAttribute('tabindex');
        if(tab!==null&&parseInt(tab)<0)return false;
        const r=el.getBoundingClientRect();
        return r.width>0&&r.height>0&&(r.width<MIN_TARGET_PX||r.height<MIN_TARGET_PX);
    }).map(el=>{
        const r=el.getBoundingClientRect();
        const label=(el.innerText||el.getAttribute('aria-label')||el.getAttribute('value')||el.getAttribute('placeholder')||'').trim().slice(0,40);
        return `<${el.tagName.toLowerCase()}>${label?' "'+label+'"':''} (${Math.round(r.width)}×${Math.round(r.height)}px)`;
    }).slice(0,5);
    if(smallTargets.length>0){
        issues.push({criterion:'2.5.8',severity:'minor',
            description:`${smallTargets.length} interactive element(s) have touch targets smaller than 24×24px (WCAG 2.2 AA).`,
            examples:smallTargets,
            fix:'Ensure all interactive elements have a minimum 24×24px clickable area.'});
    }

    const ariaIssues=[];
    const roleNeedsName=['button','link','checkbox','radio','textbox','combobox','listbox','option','menuitem','tab','treeitem'];
    const unnamedRoles=Array.from(document.querySelectorAll('[role]')).filter(el=>{
        const role=el.getAttribute('role');
        if(!roleNeedsName.includes(role))return false;
        const name=el.getAttribute('aria-label')||el.getAttribute('aria-labelledby')||(el.innerText||'').trim();
        return !name;
    });
    if(unnamedRoles.length>0)ariaIssues.push(`${unnamedRoles.length} element(s) with interactive role but no accessible name`);
    const hiddenFocusable=Array.from(document.querySelectorAll(
        '[aria-hidden="true"] a,[aria-hidden="true"] button,[aria-hidden="true"] input,[aria-hidden="true"] [tabindex]'
    )).filter(el=>{const tab=el.getAttribute('tabindex');return tab===null||parseInt(tab)>=0;});
    if(hiddenFocusable.length>0)ariaIssues.push(`${hiddenFocusable.length} focusable element(s) inside aria-hidden="true"`);
    if(ariaIssues.length>0){
        issues.push({criterion:'4.1.2',severity:'serious',
            description:ariaIssues.join('; '),
            fix:'Ensure all interactive elements have accessible names. Do not place focusable elements inside aria-hidden.'});
    }

    const untitledFrames=Array.from(document.querySelectorAll('iframe,frame')).filter(f=>{
        return !((f.getAttribute('title')||'').trim()||(f.getAttribute('aria-label')||'').trim()||f.getAttribute('aria-labelledby'));
    });
    if(untitledFrames.length>0){
        issues.push({criterion:'4.1.2',severity:'serious',
            description:`${untitledFrames.length} iframe(s) have no title attribute.`,
            examples:untitledFrames.slice(0,3).map(f=>(f.getAttribute('src')||'<iframe>').split('/').pop().slice(0,50)),
            fix:'Add a descriptive title attribute to every <iframe>.'});
    }

    return issues;
}
"""

SEVERITY_ORDER = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}

CRITERION_LABEL = {
    "1.1.1": "Non-text Content",
    "1.3.1": "Info and Relationships",
    "1.4.1": "Use of Color",
    "2.2.2": "Pause, Stop, Hide",
    "2.4.2": "Page Titled",
    "2.4.4": "Link Purpose",
    "2.5.8": "Target Size (Minimum)",
    "3.1.1": "Language of Page",
    "4.1.1": "Parsing",
    "4.1.2": "Name, Role, Value",
}


class PageStructureTest(BaseWCAGTest):
    TEST_ID = "page_structure"
    TEST_NAME = "Page Structure & Semantics"
    WCAG_CRITERIA = ["1.1.1", "1.3.1", "1.4.1", "2.2.2", "2.4.2", "2.4.4", "2.5.8", "3.1.1", "4.1.1", "4.1.2"]
    DEFAULT_SEVERITY = "serious"
    MOLMO_QUESTION = "Where is the main heading on this page? Describe its location, text, and visual prominence."

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        yield self._progress("Running structural checks (alt text, headings, lang, links, ARIA)...")

        issues = await page.evaluate(STRUCTURE_JS)

        # 2.5.8 is WCAG 2.2 AA only
        if self.wcag_version == "2.1":
            issues = [i for i in issues if i.get("criterion") != "2.5.8"]

        screenshot = await self.analyzer.screenshot_to_image(page)
        screenshot_path = self.analyzer.save_screenshot(screenshot, self.run_dir, "page_structure")
        screenshot_b64  = self.analyzer.image_to_base64(screenshot)

        yield self._progress("Running MolmoWeb visual structure analysis...")
        molmo_analysis = await self._molmo_analyze(screenshot, self.MOLMO_QUESTION)

        if not issues:
            yield self._result(TestResult(
                test_id=self.TEST_ID, test_name=self.TEST_NAME,
                result="pass", wcag_criteria=self.WCAG_CRITERIA, severity="minor",
                screenshot_path=screenshot_path, screenshot_b64=screenshot_b64,
                molmo_analysis=molmo_analysis, details={"issues": []},
            ))
            return

        issues.sort(key=lambda i: (SEVERITY_ORDER.get(i.get("severity", "minor"), 3), i.get("criterion", "")))

        criticals  = [i for i in issues if i.get("severity") == "critical"]
        seriouses  = [i for i in issues if i.get("severity") == "serious"]
        moderates  = [i for i in issues if i.get("severity") == "moderate"]
        minors     = [i for i in issues if i.get("severity") == "minor"]

        overall_severity = "critical" if criticals else ("serious" if seriouses else ("moderate" if moderates else "minor"))
        overall_result   = "fail" if (criticals or seriouses) else ("warning" if moderates else "warning")

        top = (criticals + seriouses + moderates + minors)[:3]
        parts = []
        for i in top:
            label = CRITERION_LABEL.get(i["criterion"], i["criterion"])
            desc  = i["description"]
            if i.get("examples"):
                desc += f" (e.g. {', '.join(str(e) for e in i['examples'][:2])})"
            parts.append(f"[{i['criterion']} {label}] {desc}")

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
                "critical_count":  len(criticals),
                "serious_count":   len(seriouses),
                "moderate_count":  len(moderates),
                "minor_count":     len(minors),
            },
        ))
