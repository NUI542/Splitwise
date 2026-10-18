;; deal_schema.metta - the shape of the facts the agent reasons over, and the
;; catalogue of rules it applies.
;;
;; The Python service writes these facts for each request; the rule files
;; only read them. V is a deal version number. Text values (IDs, names,
;; wallets, currencies, hashes) are strings; fixed choices are symbols.
;; Times are Unix seconds. Money is whole minor units. Shares and the
;; royalty rate are basis points (10000 = 100%).
;;
;; Deal terms (one set per version)
;;   (deal-id "deal-1")
;;   (version-created V Time)
;;   (deal-artwork V "artwork-id")
;;   (deal-currency V "KES")
;;   (deal-edition-count V Count)
;;   (deal-price V AmountMinor "KES")
;;   (deal-royalty-bps V Bps)
;;   (deal-party V Row "party-id" "name" Role Wallet)  Role: artist | co-owner
;;                                                     Wallet: "address" | none
;;   (deal-share V Row "party-id" Kind Value)          Kind: bps | fixed
;;   (deal-terms-hash V "sha256")
;;   (missing V field)                                 a field with no value
;;   (unreadable V field "raw text")                   a field that isn't a number
;;
;; Consent and locking
;;   (approval V "party-id" Time "terms-hash-approved")
;;   (locked V Time "terms-hash-at-lock")
;;   (latest-version V)
;;
;; Context
;;   (currency "KES" Exponent)
;;   (wallet-owner "address" "party-id")
;;   (artwork "artwork-id" "rights-holder-id" ConsentedEditions)
;;   (other-active-deal "deal-id" "artwork-id")
;;   (editions-sold Count)
;;   (mint-address "mint:deal-1")
;;
;; Sales and the chain
;;   (sale "event-id" Type Edition PriceMinor "KES" "seller" "buyer" Time NamedVersion)
;;        Type: primary | resale   NamedVersion: number | none
;;   (transfer "tx" Edition "from" "to" Time Seq)
;;   (payment "tx" "from" "to" AmountMinor "KES")
;;   (ledger-sale "event-id" "tx" Edition Type PriceMinor Version)

;; The largest price the agent accepts: KES 10 billion in cents. It keeps
;; price * 10000 far below the 64-bit integer limit.
(max-price-minor 1000000000000)

;; Rule catalogue: (rule-doc rule-id stage "what the rule requires")
;; Draft stage: checked live while the deal is being written.
(rule-doc field-missing draft "Every term of the deal has a value.")
(rule-doc field-unreadable draft "Numbers in the deal are written as numbers.")
(rule-doc party-duplicate-id draft "Each co-owner appears once, under one ID.")
(rule-doc party-duplicate-wallet draft "Two co-owners never share one payout wallet; one wallet means one person.")
(rule-doc party-duplicate-name draft "Two co-owners with the same name are probably one person listed twice.")
(rule-doc artist-missing draft "Exactly one co-owner is the artist, because leftover cents go to the artist.")
(rule-doc artist-multiple draft "Exactly one co-owner is the artist, because leftover cents go to the artist.")
(rule-doc share-without-party draft "Everyone who receives a share is listed as a co-owner.")
(rule-doc party-without-share draft "Every co-owner receives a share.")
(rule-doc share-duplicate draft "Each co-owner has exactly one share.")
(rule-doc wallet-missing draft "Every co-owner has a payout wallet.")
(rule-doc wallet-owned-by-other draft "A co-owner's payout wallet belongs to that co-owner.")
(rule-doc wallet-unregistered draft "Payout wallets are registered, so their owner can be confirmed.")
(rule-doc shares-not-100 draft "Shares add up to exactly 100%.")
(rule-doc share-not-positive draft "Every share is more than zero; a zero share contradicts being a co-owner.")
(rule-doc share-not-whole-bps draft "Shares are whole basis points (0.01% steps).")
(rule-doc share-fixed-amount draft "Shares are percentages, so they hold at every price.")
(rule-doc share-mixed-forms draft "Shares are all percentages; percentages and fixed amounts can't both hold at every price.")
(rule-doc edition-count-invalid draft "The edition count is a whole number above zero.")
(rule-doc editions-sold-exceeds-count draft "The edition count is at least the number of editions already sold.")
(rule-doc price-not-positive draft "The price is more than zero.")
(rule-doc price-out-of-range draft "The price is within the supported range.")
(rule-doc price-currency-mismatch draft "The price is in the deal's currency.")
(rule-doc currency-unknown draft "The deal's currency is one the agent knows.")
(rule-doc price-too-small-to-split draft "The price is large enough that every share is at least one minor unit.")
(rule-doc royalty-out-of-range draft "The resale royalty is at least 0% and below 100%.")
(rule-doc royalty-not-whole-bps draft "The royalty is whole basis points (0.01% steps).")
(rule-doc royalty-above-10 draft "Royalties above 10% are allowed, but many marketplaces ignore them.")
(rule-doc royalty-too-small draft "At a realistic resale price, co-owners other than the artist receive something.")
(rule-doc artwork-unknown draft "The deal is for a recorded artwork.")
(rule-doc artwork-has-other-active-deal draft "One artwork is governed by one active deal.")
(rule-doc artist-not-rights-holder draft "The artist on the deal is the artwork's recorded rights holder.")
(rule-doc editions-exceed-consent draft "The edition count is within what the rights holder consented to.")
;; Lock stage: everything above, plus consent and versions.
(rule-doc approval-missing lock "Every co-owner has approved this exact version.")
(rule-doc approval-for-old-version lock "An approval counts only for the version it was given for.")
(rule-doc terms-changed-after-approval lock "Terms can't change after someone approved them.")
(rule-doc approval-from-non-party lock "Only co-owners on the deal can approve it.")
(rule-doc approval-before-version lock "An approval can't be dated before the version it approves existed.")
(rule-doc version-already-locked lock "A version is locked once; changes need a new version.")
(rule-doc version-not-latest lock "Only the newest version can be locked.")
;; Sale stage: checked on every sale event.
(rule-doc deal-not-locked sale "Sales happen only under a locked deal.")
(rule-doc sale-before-lock sale "A sale can't be dated before the deal was locked.")
(rule-doc sale-version-not-active sale "A sale uses the deal version that was active when it happened.")
(rule-doc locked-terms-changed sale "Locked terms are never edited in place.")
(rule-doc edition-out-of-range sale "The edition number is between 1 and the edition count.")
(rule-doc edition-already-sold sale "Each edition has one primary sale.")
(rule-doc resale-of-unsold-edition sale "Only an edition that was sold can be resold.")
(rule-doc seller-not-holder sale "The seller of a resale holds the edition.")
(rule-doc primary-seller-not-mint sale "A primary sale comes from the deal's mint.")
(rule-doc sale-price-invalid sale "The sale price is a whole, positive amount within range.")
(rule-doc sale-currency-mismatch sale "The sale is in the deal's currency.")
;; Payout steps: each step in a payout trace names one of these.
(rule-doc primary-split payout "A primary sale's price is split among the co-owners by share.")
(rule-doc royalty-amount payout "On a resale, the royalty is the price times the royalty rate, rounded down to the minor unit.")
(rule-doc seller-proceeds payout "The seller of a resale receives the price minus the royalty.")
(rule-doc share-split payout "Each co-owner receives their share of the amount, rounded down to the minor unit.")
(rule-doc leftover-to-artist payout "Whatever is left after every share is rounded down goes to the artist.")
(rule-doc sum-check payout "The payout lines add up exactly to the amount paid.")
;; Watch stage: how each transfer on the chain is classified.
(rule-doc primary-sale-recorded watch "A mint that matches a recorded primary sale.")
(rule-doc mint-without-ledger-sale watch "A mint with no recorded primary sale can't be verified.")
(rule-doc no-active-deal watch "A transfer with no locked deal in force can't be checked.")
(rule-doc no-payment-evidence watch "A transfer with no payment from the new holder is not proof of a sale.")
(rule-doc royalty-paid watch "Every co-owner received their royalty share in the sale transaction.")
(rule-doc royalty-missing watch "A paid sale where some co-owners did not receive their royalty share.")
