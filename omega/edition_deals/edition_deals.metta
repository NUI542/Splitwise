;; Edition Deal Agent plugin for Omega (plugin API of Omega v0.1.20).
;;
;; Gives the Omega agent six skills for talking about edition deals. They
;; can look and run the watch, but never approve, lock, sell or reset:
;; every decision stays with the deal agent's own MeTTa rules.
;;
;; Install: see omega/README.md. The plugin lives in
;; {REPO}/plugins/edition_deals/ and is listed in config/plugins.yaml.

!(import! &self (library Omega ./plugins/edition_deals/edition_deal_skills.py))

(= (edaApiBase) (empty))

(= (loadOmegaPlugin)
    (progn
        ; Where the Edition Deal Agent API is. Override with edaApiBase=...
        ; on the command line or in config/config.yaml. From Omega's Docker
        ; container, the host machine is host.docker.internal.
        (configure edaApiBase "http://host.docker.internal:8000")
        (log INFO "edition-deals-plugin" (strings-concat ("Edition Deal Agent API: " (edaApiBase))))
        (add-skill deal-status
            "Show every edition deal and which version of it is in force"
            ())
        (add-skill recent-sales
            "Show the latest edition sales and who was paid what"
            ())
        (add-skill explain-payout
            "Explain, from the deal agent's own trace, why someone was paid an amount for an edition sale"
            (sale_id_in_quotes party_id_or_wallet_in_quotes))
        (add-skill scan-royalties
            "Check the chain for edition resales where the royalty was not paid, and report what needs a look"
            ())
        (add-skill open-flags
            "List open royalty flags, each with its evidence and the amounts owed"
            ())
        (add-skill check-deal
            "Check a draft edition deal, written as JSON, against every rule without saving it"
            (deal_json_in_quotes))))

(= (deal-status) (py-call (edition_deal_skills.deal_status (edaApiBase))))
(= (recent-sales) (py-call (edition_deal_skills.recent_sales (edaApiBase) "5")))
(= (explain-payout $sale $party) (py-call (edition_deal_skills.explain_payout (edaApiBase) $sale $party)))
(= (scan-royalties) (py-call (edition_deal_skills.scan_royalties (edaApiBase))))
(= (open-flags) (py-call (edition_deal_skills.open_flags (edaApiBase))))
(= (check-deal $json) (py-call (edition_deal_skills.check_deal (edaApiBase) $json)))
