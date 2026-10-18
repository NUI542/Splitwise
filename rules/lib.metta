;; lib.metta - small helpers shared by the rule files.
;;
;; Money is always a whole number of minor units (cents for KES). MeTTa's
;; integer `/` truncates toward zero, which equals rounding down for the
;; non-negative amounts the rules divide. Integers are 64-bit and wrap on
;; overflow, so prices are capped (see max-price-minor in deal_schema.metta).

;; Sum of a list of numbers.
(= (sum-of $xs) (foldl-atom $xs 0 $acc $x (+ $acc $x)))

;; Largest value in a list of non-negative numbers; -1 for an empty list.
(= (max-of $xs) (foldl-atom $xs -1 $acc $x (if (> $x $acc) $x $acc)))

;; Smallest value in a list of non-negative numbers; -1 for an empty list.
(= (min-of $xs)
   (if (== $xs ())
       -1
       (let* (($head (car-atom $xs))
              ($tail (cdr-atom $xs)))
         (foldl-atom $tail $head $acc $x (if (< $x $acc) $x $acc)))))

;; Number of items in a list.
(= (count-of $xs) (size-atom $xs))

;; True when $x is in the list $xs.
(= (member-of $x $xs) (foldl-atom $xs False $acc $y (or $acc (== $x $y))))

;; True for a whole number (an int, or a float with no fractional part).
(= (whole? $n) (== (% $n 1) 0))

;; a * b / d, rounded down. Only used on whole, non-negative inputs.
(= (mul-div-down $a $b $d) (/ (* $a $b) $d))

;; The configured price ceiling, in minor units.
(= (max-price) (match &self (max-price-minor $m) $m))

;; A usable money amount: whole, positive and at most the price ceiling.
(= (good-amount? $p) (and (whole? $p) (and (> $p 0) (<= $p (max-price)))))

;; A usable rate in basis points: whole and in [0, 10000).
(= (good-bps? $x) (and (whole? $x) (and (>= $x 0) (< $x 10000))))
