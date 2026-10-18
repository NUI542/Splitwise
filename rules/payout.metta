;; payout.metta - how a sale's money is divided under a locked deal.
;;
;; Rules (the deal's decisions 4 and 6):
;;   primary sale: the price is split among co-owners by share.
;;   resale:       royalty = price * royalty rate, rounded down to the minor
;;                 unit; the seller receives price - royalty; the royalty is
;;                 split among co-owners in the same proportions.
;;   every split:  each share is rounded down; whatever is left over goes to
;;                 the artist, so the lines always add up to the amount split.
;;
;; Results carry their own trace. Each step is
;;   (step rule-name ((key value) ...))
;; and the plain-language explanation is filled in from these steps, so the
;; numbers explained are the numbers paid.
;; A payout line is (paid "party-id" Role "wallet" AmountMinor).

(= (artist-of $v) (match &self (deal-party $v $r $id $n artist $w) $id))

;; The registered owner of a wallet, or the wallet itself when unregistered.
(= (party-of-wallet $w)
   (let $owners (collapse (match &self (wallet-owner $w $o) $o))
     (if (== $owners ()) $w (car-atom $owners))))

;; Split $base by share: (split-result Lines ShareSteps LeftoverStep).
;; Each share is rounded down; the leftover is added to the artist's line.
;; (Written with collapse/match and nested let: map-atom and let* are far
;; slower in this interpreter.)
(= (split $v $base)
   (let $allocated (sum-of (collapse (match &self (deal-share $v $r $id bps $b)
                                       (mul-div-down $base $b 10000))))
   (let $leftover (- $base $allocated)
   (let $artist (artist-of $v)
   (let $lines (collapse
                 (match &self (, (deal-share $v $r $id bps $b) (deal-party $v $r2 $id $n $role $w))
                   (let $amount (mul-div-down $base $b 10000)
                     (if (== $id $artist)
                         (paid $id $role $w (+ $amount $leftover))
                         (paid $id $role $w $amount)))))
   (let $steps (collapse
                 (match &self (deal-share $v $r $id bps $b)
                   (let $product (* $base $b)
                     (step share-split
                       ((party $id) (base-minor $base) (share-bps $b) (product $product)
                        (dropped (% $product 10000)) (result-minor (/ $product 10000)))))))
     (split-result $lines $steps
       (step leftover-to-artist
         ((base-minor $base) (allocated-minor $allocated) (leftover-minor $leftover) (artist $artist))))))))))

;; Sum of the amounts on a list of (paid id role wallet amount) lines.
(= (lines-total $lines) (foldl-atom $lines 0 $acc $l (+ $acc (index-atom $l 4))))

;; (payout-result Version Type Lines Steps)
(= (payout $e)
   (match &self (sale $e $type $ed $p $c $seller $buyer $ts $named)
     (let $v (active-version-at $ts)
       (payout-for $type $v $p $seller))))

(= (payout-for primary $v $p $seller)
   (let (split-result $lines $share-steps $leftover-step) (split $v $p)
     (let $total (lines-total $lines)
       (payout-result $v primary $lines
         ((step primary-split ((price-minor $p) (version $v)))
          $share-steps
          $leftover-step
          (step sum-check ((total-minor $total) (expected-minor $p))))))))

(= (payout-for resale $v $p $seller)
   (let $rate (royalty-of $v)
   (let $royalty (mul-div-down $p $rate 10000)
   (let $proceeds (- $p $royalty)
   (let $seller-party (party-of-wallet $seller)
   (let (split-result $lines $share-steps $leftover-step) (split $v $royalty)
   (let $all (cons-atom (paid $seller-party seller $seller $proceeds) $lines)
   (let $total (lines-total $all)
     (payout-result $v resale $all
       ((step royalty-amount
          ((price-minor $p) (royalty-bps $rate) (product (* $p $rate))
           (dropped (% (* $p $rate) 10000)) (result-minor $royalty) (version $v)))
        (step seller-proceeds
          ((price-minor $p) (royalty-minor $royalty) (seller $seller-party) (result-minor $proceeds)))
        $share-steps
        $leftover-step
        (step sum-check ((total-minor $total) (expected-minor $p)))))))))))))

;; The split the deal would make on its own price; shown in the deal summary.
(= (preview-split $v)
   (match &self (deal-price $v $p $c)
     (let (split-result $lines $share-steps $leftover-step) (split $v $p)
       (preview $p $lines $leftover-step))))
