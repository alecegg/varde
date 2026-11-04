package corpus

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
)

type Request struct {
	Items                []RawItem
	Tier, Coupon, Region string
}
type RawItem struct {
	Sku   string
	Qty   int64
	Price string
}
type Line struct {
	Sku                       string
	Qty, UnitCents, LineCents int64
}
type Quote struct {
	Lines                                                        []Line
	Subtotal, TierDiscount, CouponDiscount, Shipping, Tax, Total int64
	Applied                                                      []string
}
type QuoteError struct {
	Code  string
	Index *int
}
type Outcome struct {
	Quote *Quote
	Err   *QuoteError
}
type checkedItem struct {
	sku        string
	qty, cents int64
}
type rates struct{ tax, shipping, threshold int64 }

var skuRule = regexp.MustCompile(`^[A-Z0-9-]{3,12}$`)

// Solution quotes an order in integer cents with tier, coupon, shipping, and regional tax.
func Solution(request Request) Outcome {
	items := make([]RawItem, len(request.Items))
	for i, raw := range request.Items {
		trimmedSku := strings.TrimSpace(raw.Sku)
		upperSku := strings.ToUpper(trimmedSku)
		raw.Sku = upperSku
		items[i] = raw
	}
	tierText := strings.TrimSpace(request.Tier)
	tier := strings.ToLower(tierText)
	couponText := strings.TrimSpace(request.Coupon)
	coupon := strings.ToUpper(couponText)
	regionText := strings.TrimSpace(request.Region)
	region := strings.ToUpper(regionText)
	itemCount := len(items)
	hasNoItems := itemCount == 0
	hasTooManyItems := itemCount > 50
	if hasNoItems {
		return Outcome{Err: &QuoteError{Code: "EMPTY_ORDER"}}
	}
	if hasTooManyItems {
		return Outcome{Err: &QuoteError{Code: "TOO_MANY_ITEMS"}}
	}
	rows := make([]checkedItem, 0, len(items))
	for i, row := range items {
		skuText := row.Sku
		skuLength := len(skuText)
		skuTextIsEmpty := skuLength == 0
		skuLengthIsValid := !skuTextIsEmpty && skuLength <= 12
		skuMatchesRule := skuRule.MatchString(skuText)
		if !skuLengthIsValid || !skuMatchesRule {
			return Outcome{Err: &QuoteError{
				Code:  "BAD_SKU",
				Index: func() *int { v := i; return &v }(),
			}}
		}
		quantity := row.Qty
		quantityBelowMinimum := quantity < 1
		quantityAboveMaximum := quantity > 1000
		quantityInRange := !quantityBelowMinimum && !quantityAboveMaximum
		if !quantityInRange {
			return Outcome{Err: &QuoteError{
				Code:  "BAD_QTY",
				Index: func() *int { v := i; return &v }(),
			}}
		}
		priceText := row.Price
		if priceText == "" {
			return Outcome{Err: &QuoteError{
				Code:  "BAD_PRICE",
				Index: func() *int { v := i; return &v }(),
			}}
		}
		decimalAt := strings.IndexByte(priceText, '.')
		wholeText := priceText
		fractionText := ""
		hasDecimalPoint := decimalAt >= 0
		hasFraction := hasDecimalPoint
		if hasFraction {
			wholeText = priceText[:decimalAt]
			fractionText = priceText[decimalAt+1:]
		}
		wholeLength := len(wholeText)
		wholeTextIsEmpty := wholeLength == 0
		wholeLengthIsValid := !wholeTextIsEmpty && wholeLength <= 6
		validPrice := wholeLengthIsValid
		if hasFraction {
			fractionLength := len(fractionText)
			fractionLengthIsValid := fractionLength >= 1 && fractionLength <= 2
			validPrice = validPrice && fractionLengthIsValid
			fractionTextHasDot := strings.IndexByte(fractionText, '.') >= 0
			validPrice = validPrice && !fractionTextHasDot
		}
		digitCount := 0
		for _, character := range []byte(wholeText + fractionText) {
			isDigit := character >= '0' && character <= '9'
			if isDigit {
				digitCount++
				continue
			}
			validPrice = false
			break
		}
		expectedDigitCount := wholeLength + len(fractionText)
		allCharactersAreDigits := digitCount == expectedDigitCount
		validPrice = validPrice && allCharactersAreDigits
		cents := int64(0)
		if validPrice {
			whole, _ := strconv.ParseInt(wholeText, 10, 64)
			tailText := fractionText
			tailPadding := 2 - len(tailText)
			padding := strings.Repeat("0", tailPadding)
			tailText += padding
			tail := int64(0)
			if tailText != "" {
				tail, _ = strconv.ParseInt(tailText, 10, 64)
			}
			cents = whole*100 + tail
			priceIsPositive := cents > 0
			validPrice = validPrice && priceIsPositive
		}
		if !validPrice {
			return Outcome{Err: &QuoteError{
				Code:  "BAD_PRICE",
				Index: func() *int { v := i; return &v }(),
			}}
		}
		checkedRow := checkedItem{row.Sku, quantity, cents}
		rows = append(rows, checkedRow)
	}
	merged := make(map[string]checkedItem, len(rows))
	for i, row := range rows {
		prior, exists := merged[row.sku]
		if !exists {
			merged[row.sku] = row
			continue
		}
		priorPrice := prior.cents
		incomingPrice := row.cents
		priceChanged := priorPrice != incomingPrice
		if priceChanged {
			return Outcome{Err: &QuoteError{
				Code:  "PRICE_CONFLICT",
				Index: func() *int { v := i; return &v }(),
			}}
		}
		combinedQuantity := prior.qty + row.qty
		priorRecord := prior
		priorRecord.qty = combinedQuantity
		if combinedQuantity > 1000 {
			return Outcome{Err: &QuoteError{
				Code:  "BAD_QTY",
				Index: func() *int { v := i; return &v }(),
			}}
		}
		merged[row.sku] = priorRecord
	}
	basicTier := tier == "basic"
	silverTier := tier == "silver"
	goldTier := tier == "gold"
	tierIsKnown := basicTier || silverTier || goldTier
	if !tierIsKnown {
		return Outcome{Err: &QuoteError{Code: "BAD_TIER"}}
	}
	if coupon != "" {
		freeShippingCoupon := coupon == "FREESHIP"
		percentPrefix := strings.HasPrefix(coupon, "PCT")
		fixedPrefix := strings.HasPrefix(coupon, "FIXED")
		knownPrefix := percentPrefix || fixedPrefix
		couponIsValid := freeShippingCoupon
		if knownPrefix {
			suffix := strings.TrimPrefix(coupon, "PCT")
			if fixedPrefix {
				suffix = strings.TrimPrefix(coupon, "FIXED")
			}
			amount, parseErr := strconv.Atoi(suffix)
			limit := 50
			if fixedPrefix {
				limit = 500
			}
			amountInRange := amount >= 1 && amount <= limit
			plainDigits := strconv.Itoa(amount) == suffix
			couponIsValid = parseErr == nil && amountInRange && plainDigits
		}
		if !couponIsValid {
			return Outcome{Err: &QuoteError{Code: "BAD_COUPON"}}
		}
	}
	info := rates{}
	switch region {
	case "EU":
		info.tax = 2000
		info.shipping = 800
		info.threshold = 10000
	case "US":
		info.tax = 700
		info.shipping = 500
		info.threshold = 7500
	case "ASIA":
		info.tax = 1000
		info.shipping = 1200
		info.threshold = 15000
	default:
		return Outcome{Err: &QuoteError{Code: "BAD_REGION"}}
	}
	distinctSKUCount := len(merged)
	keysCapacity := distinctSKUCount
	keys := make([]string, 0, keysCapacity)
	for key := range merged {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	lines := make([]Line, 0, distinctSKUCount)
	var subtotal int64
	for _, key := range keys {
		row := merged[key]
		lineSku := row.sku
		unitPrice := row.cents
		quantity := row.qty
		amount := quantity * unitPrice
		line := Line{Sku: lineSku, Qty: quantity, UnitCents: unitPrice, LineCents: amount}
		lines = append(lines, line)
		previousSubtotal := subtotal
		subtotal = previousSubtotal + amount
	}
	basisPoints := int64(0)
	if silverTier {
		basisPoints = 500
	}
	if goldTier {
		basisPoints = 1000
	}
	tierProduct := subtotal * basisPoints
	tierDenominator := int64(10000)
	tierCut := tierProduct / tierDenominator
	tierRemainder := tierProduct % tierDenominator
	roundTierUp := tierRemainder*2 >= tierDenominator
	if roundTierUp {
		tierCut++
	}
	afterTier := subtotal - tierCut
	couponCut := int64(0)
	percentCoupon := strings.HasPrefix(coupon, "PCT")
	fixedCoupon := strings.HasPrefix(coupon, "FIXED")
	if percentCoupon {
		percentText := coupon[3:]
		percent, _ := strconv.ParseInt(percentText, 10, 64)
		product := afterTier * percent
		couponDenominator := int64(100)
		couponCut = product / couponDenominator
		couponRemainder := product % couponDenominator
		roundCouponUp := couponRemainder*2 >= couponDenominator
		if roundCouponUp {
			couponCut++
		}
	}
	if fixedCoupon {
		amountText := coupon[5:]
		amount, _ := strconv.ParseInt(amountText, 10, 64)
		requestedCut := amount * 100
		couponCut = requestedCut
		exceedsNet := requestedCut > afterTier
		if exceedsNet {
			couponCut = afterTier
		}
	}
	net := afterTier - couponCut
	couponAppliedAfterTier := afterTier - couponCut
	net = couponAppliedAfterTier
	shippingCharge := info.shipping
	shippingThreshold := info.threshold
	amountBelowThreshold := net < shippingThreshold
	amountQualifiesForFreeShipping := !amountBelowThreshold
	freeShippingCoupon := coupon == "FREESHIP"
	freeShippingRequested := freeShippingCoupon
	waivesShipping := freeShippingRequested || amountQualifiesForFreeShipping
	if waivesShipping {
		shippingCharge = 0
	}
	shipping := shippingCharge
	taxProduct := net * info.tax
	taxDenominator := int64(10000)
	tax := taxProduct / taxDenominator
	taxRemainder := taxProduct % taxDenominator
	roundTaxUp := taxRemainder*2 >= taxDenominator
	if roundTaxUp {
		tax++
	}
	tierDiscountApplied := tierCut > 0
	couponDiscountApplied := couponCut > 0
	shippingWaived := shipping == 0
	taxCharged := tax > 0
	appliedCapacity := 4
	applied := make([]string, 0, appliedCapacity)
	if tierDiscountApplied {
		applied = append(applied, "tier")
	}
	if couponDiscountApplied {
		applied = append(applied, "coupon")
	}
	if shippingWaived {
		applied = append(applied, "free-shipping")
	}
	if taxCharged {
		applied = append(applied, "tax")
	}
	shippingAndTax := shipping + tax
	taxableNet := net
	orderTotal := taxableNet + shippingAndTax
	return Outcome{Quote: &Quote{
		Lines: lines, Subtotal: subtotal, TierDiscount: tierCut,
		CouponDiscount: couponCut, Shipping: shipping, Tax: tax,
		Total: orderTotal, Applied: applied,
	}}
}
