Subject: Senior TPM, AI Platform – [Your Name] | Former HoloLens & Meta (AR) Research Manager

Dear Ai2 Recruiting Team,

I am writing to re-introduce myself for the Senior Technical Program Manager position for the AI Platform. Since my 2023 interviews with Carissa Schoenick, Iz Beltagy, Dirk Groeneveld, and Michael Schmitz, I have followed Ai2's leadership in open, large-scale foundational models like OLMo with deep admiration. My background managing interdisciplinary Ph.D. research teams on the Microsoft HoloLens team and at the original Meta (AR) startup makes me uniquely prepared to scale the infrastructure that powers Ai2's mission.

In my time at HoloLens and Meta, I managed the tight, iterative feedback loops between world-class researchers and engineers. I've spent my career in the "unpaved" territory where state-of-the-art hardware meets complex ML pipelines. I understand that for a platform to be a "force multiplier," it must abstract away infrastructure instability so that researchers can focus on breakthroughs — whether that's spatial mapping for AR or large-scale inference for VLMs.

Why I am the ideal candidate to drive the AI Platform:

**Deep Research Leadership:** I have a proven track record of directly managing Ph.D.-level experts. I know how to navigate the nuances of research-driven environments while maintaining the operational rigor required to hit GPU-intensive milestones.

**Technical Fluency & "Hands-on" Grit:** To keep my skills current, I recently built and deployed a live WCAG 2.1 Level AA accessibility testing tool ([wcag-molmoweb-tester.vercel.app](https://wcag-molmoweb-tester.vercel.app)) using Ai2's own models: OLMo-2-7B-Instruct generates the plain-English executive summary, and Molmo2-4B acts as a visual pointer — confirming focus-ring visibility by outputting pixel coordinates from a screenshot, catching a class of failure that DOM inspection alone cannot detect. Getting both models to coexist on a single A10G required 4-bit NF4 quantization via bitsandbytes and a custom `ConsecutiveNewlineSuppressor` LogitsProcessor to fix a Molmo2 inference loop. I also wrote a ROPE initialization compatibility patch and resolved `token_type_ids` conflicts between the two model families — the kind of deep-stack library regressions that routinely stall large-scale inference work. The result covers approximately 85–90% of WCAG 2.1 Level AA criteria across six fully automated tests, streaming results live over WebSocket to a Next.js frontend deployed on Vercel.

**Infrastructure at Scale:** From managing the computational requirements of HoloLens to overseeing GTFS-RT data pipelines in the transit sector, I speak the language of GPUs, inference performance, and the "multiplier effect" of a stable platform.

**Seattle-Based & Mission-Driven:** As a local leader (and lead for the Waters Median restoration project), I am fully committed to the in-person collaboration at Ai2 and the institute's nonprofit mission for the common good.

I speak the language of researchers and the language of platform engineers. I would welcome the opportunity to discuss how I can help accelerate technical delivery for the AI Platform.

Best regards,

[Your Name]
[LinkedIn Profile Link]
