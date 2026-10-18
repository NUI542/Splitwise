;; classification.metta - is the deal being honoured on the chain?
;;
;; A transfer is not proof of a sale. The agent only says a royalty is
;; missing when the same transaction shows the new holder paying for the
;; edition. Each transfer gets one class:
;;   PRIMARY_SALE          a mint matching a recorded primary sale (no flag)
;;   SALE_ROYALTY_PAID     a paid sale where every co-owner got their share
;;   SALE_ROYALTY_MISSING  a paid sale where some co-owners were not paid
;;   TRANSFER_UNVERIFIED   no evidence of a sale: a gift, a wallet move, or a
;;                         sale settled off the chain. Nobody is accused.
;;
;; Result:
;;   (watch-result "tx" Edition Class rule-id Version
;;                 ((key value) ...)      evidence
;;                 ((owe "party-id" "wallet" Due Received Short) ...)
;;                 Steps)                 the royalty calculation, if any

(= (is-mint? $w) (not (== (collapse (match &self (mint-address $w) found)) ())))

;; Everything the new holder paid inside the transaction: the sale price.
(= (buyer-paid $tx $buyer)
   (sum-of (collapse (match &self (payment $tx $buyer $to $amt $c) $amt))))

;; Everything a wallet received inside the transaction.
(= (received $tx $wallet)
   (sum-of (collapse (match &self (payment $tx $from $wallet $amt $c) $amt))))

;; The recorded sale for a transaction, or none. (Not named ledger-event:
;; that is a key inside evidence, and a function of the same name would be
;; evaluated there.)
(= (recorded-sale-of $tx)
   (let $events (collapse (match &self (ledger-sale $e $tx $ed $type $p $v) $e))
     (if (== $events ()) none (car-atom $events))))

;; Co-owners who received less than their royalty share.
(= (shortfalls $tx $lines)
   (collapse
     (let (paid $id $role $w $due) (superpose $lines)
       (let $got (received $tx $w)
         (if (< $got $due)
             (owe $id $w $due $got (- $due $got))
             (empty))))))

(= (classify-all)
   (collapse (match &self (transfer $tx $ed $from $to $ts $seq)
     (classify-transfer $tx $ed $from $to $ts))))

(= (classify-transfer $tx $ed $from $to $ts)
   (if (is-mint? $from)
       (classify-mint $tx $ed $from $to $ts)
       (classify-secondary $tx $ed $from $to $ts)))

;; (Nested let rather than let*, which is far slower in this interpreter.)
(= (classify-mint $tx $ed $from $to $ts)
   (let $event (recorded-sale-of $tx)
   (let $v (active-version-at $ts)
   (let $paid (buyer-paid $tx $to)
     (if (== $event none)
         (watch-result $tx $ed TRANSFER_UNVERIFIED mint-without-ledger-sale $v
           ((from $from) (to $to) (buyer-paid-minor $paid) (ledger-event none)) () ())
         (watch-result $tx $ed PRIMARY_SALE primary-sale-recorded $v
           ((from $from) (to $to) (buyer-paid-minor $paid) (ledger-event $event)) () ()))))))

(= (classify-secondary $tx $ed $from $to $ts)
   (let $v (active-version-at $ts)
   (let $price (buyer-paid $tx $to)
   (let $event (recorded-sale-of $tx)
     (if (== $v -1)
         (watch-result $tx $ed TRANSFER_UNVERIFIED no-active-deal $v
           ((from $from) (to $to) (buyer-paid-minor $price) (ledger-event $event)) () ())
         (if (== $price 0)
             (watch-result $tx $ed TRANSFER_UNVERIFIED no-payment-evidence $v
               ((from $from) (to $to) (buyer-paid-minor 0) (ledger-event $event)) () ())
             (classify-paid-sale $tx $ed $from $to $v $price $event)))))))

(= (classify-paid-sale $tx $ed $from $to $v $price $event)
   (let $rate (royalty-of $v)
   (let $royalty (mul-div-down $price $rate 10000)
   (let (split-result $lines $share-steps $leftover-step) (split $v $royalty)
   (let $owed (shortfalls $tx $lines)
   (let $received-total (foldl-atom $lines 0 $acc $l (+ $acc (received $tx (index-atom $l 3))))
   (let $evidence ((from $from) (to $to) (buyer-paid-minor $price) (royalty-due-minor $royalty)
                   (royalty-received-minor $received-total) (ledger-event $event))
   (let $steps ((step royalty-amount
                  ((price-minor $price) (royalty-bps $rate) (product (* $price $rate))
                   (dropped (% (* $price $rate) 10000)) (result-minor $royalty) (version $v)))
                $share-steps
                $leftover-step)
     (if (== $owed ())
         (watch-result $tx $ed SALE_ROYALTY_PAID royalty-paid $v $evidence () $steps)
         (watch-result $tx $ed SALE_ROYALTY_MISSING royalty-missing $v $evidence $owed $steps))))))))))
