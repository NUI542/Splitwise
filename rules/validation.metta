;; validation.metta - the checks the agent runs on a deal and on each sale.
;;
;; Every rule is one equation. Rules with the same head all fire, so
;; (collapse (draft-rule V)) gathers every finding for version V. A finding is
;;   (violation Severity rule-id field ((key value) ...))
;; where Severity is error or warning and field names the part of the deal
;; (or sale) the finding is about. An empty result means the rule holds.
;; Lock-stage rules include every draft rule; see (lock-rule $v) below.

;; ---------------------------------------------------------------- lookups

(= (party-ids $v) (collapse (unique (match &self (deal-party $v $r $id $n $ro $w) $id))))
(= (share-ids $v) (collapse (unique (match &self (deal-share $v $r $id $k $x) $id))))
(= (artist-ids $v) (collapse (unique (match &self (deal-party $v $r $id $n artist $w) $id))))
(= (bps-values $v) (collapse (match &self (deal-share $v $r $id bps $x) $x)))
(= (royalty-of $v) (match &self (deal-royalty-bps $v $x) $x))

;; ------------------------------------------------------- unreadable input

(= (draft-rule $v)
   (match &self (missing $v $field)
     (violation error field-missing $field ())))

(= (draft-rule $v)
   (match &self (unreadable $v $field $raw)
     (violation error field-unreadable $field ((raw $raw)))))

;; ---------------------------------------------------------------- parties

(= (draft-rule $v)
   (match &self (, (deal-party $v $r1 $id $n1 $ro1 $w1) (deal-party $v $r2 $id $n2 $ro2 $w2))
     (if (< $r1 $r2)
         (violation error party-duplicate-id parties ((party $id) (rows ($r1 $r2))))
         (empty))))

(= (draft-rule $v)
   (match &self (, (deal-party $v $r1 $id1 $n1 $ro1 $w) (deal-party $v $r2 $id2 $n2 $ro2 $w))
     (if (and (< $r1 $r2) (and (not (== $id1 $id2)) (not (== $w none))))
         (violation error party-duplicate-wallet parties ((wallet $w) (parties ($id1 $id2))))
         (empty))))

(= (draft-rule $v)
   (match &self (, (deal-party $v $r1 $id1 $n $ro1 $w1) (deal-party $v $r2 $id2 $n $ro2 $w2))
     (if (and (< $r1 $r2) (not (== $id1 $id2)))
         (violation warning party-duplicate-name parties ((name $n) (parties ($id1 $id2))))
         (empty))))

(= (draft-rule $v)
   (let $ids (artist-ids $v)
     (if (== $ids ())
         (violation error artist-missing parties ())
         (if (> (count-of $ids) 1)
             (violation error artist-multiple parties ((artists $ids)))
             (empty)))))

(= (draft-rule $v)
   (let $parties (party-ids $v)
     (match &self (deal-share $v $r $id $k $x)
       (if (member-of $id $parties)
           (empty)
           (violation error share-without-party shares ((party $id) (row $r)))))))

(= (draft-rule $v)
   (let $shared (share-ids $v)
     (match &self (deal-party $v $r $id $n $ro $w)
       (if (member-of $id $shared)
           (empty)
           (violation error party-without-share parties ((party $id) (row $r)))))))

(= (draft-rule $v)
   (match &self (, (deal-share $v $r1 $id $k1 $x1) (deal-share $v $r2 $id $k2 $x2))
     (if (< $r1 $r2)
         (violation error share-duplicate shares ((party $id) (rows ($r1 $r2))))
         (empty))))

;; ---------------------------------------------------------------- wallets

(= (draft-rule $v)
   (match &self (deal-party $v $r $id $n $role none)
     (violation error wallet-missing parties ((party $id) (role $role)))))

(= (draft-rule $v)
   (match &self (deal-party $v $r $id $n $role $w)
     (if (== $w none)
         (empty)
         (let $owners (collapse (match &self (wallet-owner $w $o) $o))
           (if (== $owners ())
               (violation warning wallet-unregistered parties ((party $id) (wallet $w)))
               (if (member-of $id $owners)
                   (empty)
                   (let $owner (car-atom $owners)
                     (violation error wallet-owned-by-other parties
                       ((party $id) (wallet $w) (owner $owner))))))))))

;; ----------------------------------------------------------------- shares

(= (draft-rule $v)
   (let $xs (bps-values $v)
     (if (== $xs ())
         (empty)
         (let $total (sum-of $xs)
           (if (== $total 10000)
               (empty)
               (violation error shares-not-100 shares ((total-bps $total))))))))

(= (draft-rule $v)
   (match &self (deal-share $v $r $id $k $x)
     (if (> $x 0)
         (empty)
         (violation error share-not-positive shares ((party $id) (kind $k) (value $x))))))

(= (draft-rule $v)
   (match &self (deal-share $v $r $id bps $x)
     (if (whole? $x)
         (empty)
         (violation error share-not-whole-bps shares ((party $id) (bps $x))))))

(= (draft-rule $v)
   (match &self (deal-share $v $r $id fixed $x)
     (if (== (bps-values $v) ())
         (violation error share-fixed-amount shares ((party $id) (amount-minor $x)))
         (violation error share-mixed-forms shares ((party $id) (amount-minor $x))))))

;; ------------------------------------------------------- editions & price

(= (draft-rule $v)
   (match &self (deal-edition-count $v $n)
     (if (and (whole? $n) (> $n 0))
         (empty)
         (violation error edition-count-invalid edition_count ((edition-count $n))))))

(= (draft-rule $v)
   (match &self (, (deal-edition-count $v $n) (editions-sold $s))
     (if (> $s $n)
         (violation error editions-sold-exceeds-count edition_count ((sold $s) (edition-count $n)))
         (empty))))

(= (draft-rule $v)
   (match &self (deal-price $v $p $c)
     (if (> $p 0)
         (empty)
         (violation error price-not-positive price ((price-minor $p))))))

(= (draft-rule $v)
   (match &self (deal-price $v $p $c)
     (let $max (max-price)
       (if (> $p $max)
           (violation error price-out-of-range price ((price-minor $p) (max-minor $max)))
           (empty)))))

(= (draft-rule $v)
   (match &self (, (deal-price $v $p $pc) (deal-currency $v $dc))
     (if (== $pc $dc)
         (empty)
         (violation error price-currency-mismatch price ((price-currency $pc) (deal-currency $dc))))))

(= (draft-rule $v)
   (match &self (deal-currency $v $c)
     (if (== (collapse (match &self (currency $c $e) $e)) ())
         (violation error currency-unknown currency ((currency $c)))
         (empty))))

(= (draft-rule $v)
   (match &self (, (deal-price $v $p $c) (deal-share $v $r $id bps $x))
     (if (and (good-amount? $p) (and (whole? $x) (> $x 0)))
         (let $amount (mul-div-down $p $x 10000)
           (if (== $amount 0)
               (violation error price-too-small-to-split price ((party $id) (price-minor $p) (bps $x)))
               (empty)))
         (empty))))

;; ---------------------------------------------------------------- royalty

(= (draft-rule $v)
   (match &self (deal-royalty-bps $v $x)
     (if (and (>= $x 0) (< $x 10000))
         (empty)
         (violation error royalty-out-of-range royalty ((bps $x))))))

(= (draft-rule $v)
   (match &self (deal-royalty-bps $v $x)
     (if (whole? $x)
         (empty)
         (violation error royalty-not-whole-bps royalty ((bps $x))))))

(= (draft-rule $v)
   (match &self (deal-royalty-bps $v $x)
     (if (and (> $x 1000) (< $x 10000))
         (violation warning royalty-above-10 royalty ((bps $x)))
         (empty))))

;; The deal's own price stands in for a realistic resale price. At 0% there
;; is no royalty to split, so the rule doesn't apply.
(= (draft-rule $v)
   (match &self (, (deal-royalty-bps $v $x) (deal-price $v $p $c))
     (if (and (good-bps? $x) (and (> $x 0) (good-amount? $p)))
         (let $royalty (mul-div-down $p $x 10000)
         (let $others (collapse
                        (match &self (, (deal-party $v $r $id $n co-owner $w) (deal-share $v $r2 $id bps $b))
                          (mul-div-down $royalty $b 10000)))
           (if (== $others ())
               (empty)
               (if (== (max-of $others) 0)
                   (violation warning royalty-too-small royalty
                     ((bps $x) (reference-price-minor $p) (royalty-minor $royalty)))
                   (empty)))))
         (empty))))

;; ---------------------------------------------------------------- artwork

(= (draft-rule $v)
   (match &self (deal-artwork $v $aw)
     (if (== (collapse (match &self (artwork $aw $holder $consented) $holder)) ())
         (violation error artwork-unknown artwork_id ((artwork $aw)))
         (empty))))

(= (draft-rule $v)
   (match &self (, (deal-artwork $v $aw) (other-active-deal $other $aw))
     (violation error artwork-has-other-active-deal artwork_id ((artwork $aw) (other-deal $other)))))

(= (draft-rule $v)
   (match &self (, (deal-artwork $v $aw) (artwork $aw $holder $consented) (deal-party $v $r $id $n artist $w))
     (if (== $id $holder)
         (empty)
         (violation error artist-not-rights-holder parties
           ((artist $id) (rights-holder $holder) (artwork $aw))))))

(= (draft-rule $v)
   (match &self (, (deal-artwork $v $aw) (artwork $aw $holder $consented) (deal-edition-count $v $n))
     (if (> $n $consented)
         (violation error editions-exceed-consent edition_count ((edition-count $n) (consented $consented)))
         (empty))))

;; ============================================================ lock stage

(= (lock-rule $v) (draft-rule $v))

(= (lock-rule $v)
   (match &self (deal-party $v $r $id $n $role $w)
     (if (== (collapse (match &self (approval $v $id $t $h) $t)) ())
         (let $older (collapse (match &self (approval $ov $id $t $h) $ov))
           (if (== $older ())
               (violation error approval-missing approvals ((party $id) (version $v)))
               (let $last (max-of $older)
                 (violation error approval-for-old-version approvals
                   ((party $id) (approved-version $last) (version $v))))))
         (empty))))

(= (lock-rule $v)
   (match &self (, (approval $v $id $t $h) (deal-terms-hash $v $current))
     (if (== $h $current)
         (empty)
         (violation error terms-changed-after-approval approvals ((party $id) (version $v))))))

(= (lock-rule $v)
   (let $parties (party-ids $v)
     (match &self (approval $v $id $t $h)
       (if (member-of $id $parties)
           (empty)
           (violation error approval-from-non-party approvals ((party $id) (version $v)))))))

(= (lock-rule $v)
   (match &self (, (approval $v $id $t $h) (version-created $v $c))
     (if (< $t $c)
         (violation error approval-before-version approvals
           ((party $id) (approved-at $t) (version-created-at $c)))
         (empty))))

(= (lock-rule $v)
   (match &self (locked $v $t $h)
     (violation error version-already-locked version ((version $v) (locked-at $t)))))

(= (lock-rule $v)
   (match &self (latest-version $latest)
     (if (< $v $latest)
         (violation error version-not-latest version ((version $v) (latest $latest)))
         (empty))))

;; ============================================================ sale stage

;; The version in force at a time: the newest version locked at or before it.
(= (active-version-at $ts)
   (max-of (collapse (match &self (locked $v $lt $h) (if (<= $lt $ts) $v (empty))))))

(= (first-lock-time) (min-of (collapse (match &self (locked $v $lt $h) $lt))))

;; The wallet holding an edition: the receiver of its latest transfer, or none.
(= (holder-of $ed)
   (let $moves (collapse (match &self (transfer $tx $ed $from $to $t $seq) ($seq $to)))
   (let $last (foldl-atom $moves (-1 none) $acc $x
                (if (> (car-atom $x) (car-atom $acc)) $x $acc))
     (index-atom $last 1))))

(= (sale-rule $e)
   (match &self (sale $e $type $ed $p $c $seller $buyer $ts $named)
     (if (== (collapse (match &self (locked $v $lt $h) $v)) ())
         (violation error deal-not-locked sale ())
         (if (== (active-version-at $ts) -1)
             (let $first (first-lock-time)
               (violation error sale-before-lock sale ((sale-at $ts) (first-locked-at $first))))
             (empty)))))

(= (sale-rule $e)
   (match &self (sale $e $type $ed $p $c $seller $buyer $ts $named)
     (if (== $named none)
         (empty)
         (let $active (active-version-at $ts)
           (if (or (== $active -1) (== $named $active))
               (empty)
               (violation error sale-version-not-active sale
                 ((named-version $named) (active-version $active))))))))

(= (sale-rule $e)
   (match &self (sale $e $type $ed $p $c $seller $buyer $ts $named)
     (let $v (active-version-at $ts)
       (match &self (, (locked $v $lt $h) (deal-terms-hash $v $current))
         (if (== $h $current)
             (empty)
             (violation error locked-terms-changed sale ((version $v))))))))

(= (sale-rule $e)
   (match &self (sale $e $type $ed $p $c $seller $buyer $ts $named)
     (let $v (active-version-at $ts)
       (match &self (deal-edition-count $v $n)
         (if (and (whole? $ed) (and (>= $ed 1) (<= $ed $n)))
             (empty)
             (violation error edition-out-of-range sale ((edition $ed) (edition-count $n))))))))

(= (sale-rule $e)
   (match &self (sale $e primary $ed $p $c $seller $buyer $ts $named)
     (let $holder (holder-of $ed)
       (if (== $holder none)
           (empty)
           (violation error edition-already-sold sale ((edition $ed) (holder $holder)))))))

(= (sale-rule $e)
   (match &self (, (sale $e primary $ed $p $c $seller $buyer $ts $named) (mint-address $mint))
     (if (== $seller $mint)
         (empty)
         (violation error primary-seller-not-mint sale ((seller $seller) (mint $mint))))))

(= (sale-rule $e)
   (match &self (sale $e resale $ed $p $c $seller $buyer $ts $named)
     (let $holder (holder-of $ed)
       (if (== $holder none)
           (violation error resale-of-unsold-edition sale ((edition $ed)))
           (if (== $holder $seller)
               (empty)
               (violation error seller-not-holder sale ((edition $ed) (seller $seller) (holder $holder))))))))

(= (sale-rule $e)
   (match &self (sale $e $type $ed $p $c $seller $buyer $ts $named)
     (if (good-amount? $p)
         (empty)
         (violation error sale-price-invalid sale ((price-minor $p))))))

(= (sale-rule $e)
   (match &self (sale $e $type $ed $p $c $seller $buyer $ts $named)
     (let $v (active-version-at $ts)
       (match &self (deal-currency $v $dc)
         (if (== $c $dc)
             (empty)
             (violation error sale-currency-mismatch sale ((sale-currency $c) (deal-currency $dc))))))))
