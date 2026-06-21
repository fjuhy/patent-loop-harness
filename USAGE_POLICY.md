# Usage Policy and Non-Goals

This project is an **experimental, human-in-the-loop drafting and prior-art
stress-test aid**. It selects candidate ideas and produces patent specification
*drafts* plus examiner-style critique for a human to review. It is not a filing
tool, not a patentability opinion, and not a substitute for a licensed patent
attorney (변리사).

## Intended use

- Generate and pressure-test draft specifications for a single invention at a time.
- Use the examiner / red-team / spot-check stages as a structured self-critique to
  find weaknesses early, before human and counsel review.
- Learn how prior-art and §102/§103 (신규성/진보성) arguments are framed.

## Non-goals (do not use this for)

- **Filing AI-generated drafts as-is.** Every output must be reviewed, corrected,
  and substantively reworked by a human, and reviewed by patent counsel, before any
  filing decision.
- **Bulk or automated patent generation / filing.** No claim-flooding, portfolio
  spamming, evergreening, or competitor claim-blocking. The per-run limit and quiet
  hours are deliberate anti-abuse defaults; do not remove them to mass-produce
  applications.
- **Misrepresenting AI-generated content as human-authored** to a patent office,
  partner, investor, or the public.
- **Relying on the tool's citations or verdicts as fact.** Generated references must
  be independently re-searched and verified; `DIRECT_OK`/`finalized` only means the
  draft passed the harness's automated self-checks.

## Inventorship and candor

- An AI cannot be a named inventor (Thaler v. Vidal; the DABUS decisions at
  KIPO/EPO/UK and elsewhere). A natural person must make a significant intellectual
  contribution to the conception of each claim. Editorial polishing of an AI draft is
  not, by itself, an inventive contribution.
- You are responsible for your patent office's duty-of-candor / good-faith rules
  (e.g. USPTO Rule 56), including disclosing material known prior art.

## Disclosure timing

- Generated specifications and the technical-overview HTML may describe an unfiled
  invention. Do not disclose them publicly before a filing/priority decision with
  counsel — pre-filing disclosure can destroy novelty (the EPO has essentially no
  grace period; KIPO/US grace periods require formal claims).

By using this software you agree to use it consistently with this policy. The
software is provided "AS IS" with no warranty (see `LICENSE`).
