;; Edition Deal Agent skills for OmegaClaw.
;;
;; Add these to OmegaClaw's src/skills.metta, with edition_deal_skills.py
;; importable from OmegaClaw's Python path (see omega/README.md). The
;; bridges follow the py-call pattern from OmegaClaw's skill guide. They
;; only read and watch; nothing here can approve, lock, sell or reset.

(= (deal-status) (py-call (edition_deal_skills.deal_status)))
(= (recent-sales) (py-call (edition_deal_skills.recent_sales "5")))
(= (explain-payout $sale $party) (py-call (edition_deal_skills.explain_payout $sale $party)))
(= (scan-royalties) (py-call (edition_deal_skills.scan_royalties)))
(= (open-flags) (py-call (edition_deal_skills.open_flags)))
(= (check-deal $json) (py-call (edition_deal_skills.check_deal $json)))

;; Lines to add to the list that getSkills returns, so the LLM knows the
;; skills exist (put them under their own heading, e.g. EDITION DEALS):
;;
;; "- Show every edition deal and which version is in force: (deal-status)"
;; "- Show the latest sales and who was paid what: (recent-sales)"
;; "- Explain why someone got paid an amount for a sale: (explain-payout sale_id_in_quotes party_id_in_quotes)"
;; "- Check the chain for resales where the royalty wasn't paid: (scan-royalties)"
;; "- List open royalty flags with the evidence: (open-flags)"
;; "- Check a draft deal against every rule without saving it: (check-deal deal_json_in_quotes)"
